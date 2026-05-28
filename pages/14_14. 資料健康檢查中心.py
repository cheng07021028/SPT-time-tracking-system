# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.timezone_service import today_date
from services.backup_queue_status_service import (
    collect_backup_queue_status,
    flush_backup_queues_now,
    status_rows_for_table,
)
from services.time_record_integrity_service import (
    audit_time_record_integrity,
    repair_0102_authority_non_destructive,
    recover_log_only_start_records_to_pending,
    export_audit_excel_bytes,
)
from services.regression_test_service import (
    run_v157_regression_suite,
    export_v157_regression_excel_bytes,
    compact_result_rows,
)
from services.backup_restore_service import (
    create_full_backup_snapshot,
    list_backup_snapshots,
    inspect_backup_zip_bytes,
    restore_missing_time_records_from_backup,
    backup_manifest_rows,
)
from services.system_monitoring_service import (
    collect_system_monitoring_snapshot,
    export_monitoring_excel_bytes,
    monitoring_summary_rows,
)

from services.log_only_pending_close_service import (
    collect_log_only_pending_close_candidates,
    close_log_only_pending_records,
    export_pending_close_excel_bytes,
)

# V166E2: import V166C/V166D LOG snapshot helpers in a dependency-safe way.
# 部署時若只套到 page 檔、service 檔尚未同步，不能讓 14 頁整頁崩潰。
try:
    from services.log_snapshot_service import (
        collect_log_snapshot_recovery_candidates,
        recover_records_from_log_snapshots,
        export_log_snapshot_candidates_excel_bytes,
        get_log_snapshot_status,
        get_log_snapshot_coverage_status,
        backfill_missing_log_snapshots,
        export_log_snapshot_coverage_excel_bytes,
    )
    V166C_LOG_SNAPSHOT_IMPORT_OK = True
    V166C_LOG_SNAPSHOT_IMPORT_ERROR = ""
except Exception as _v166c_log_snapshot_import_error:  # pragma: no cover - deployment guard
    V166C_LOG_SNAPSHOT_IMPORT_OK = False
    V166C_LOG_SNAPSHOT_IMPORT_ERROR = str(_v166c_log_snapshot_import_error)

    def _v166e2_missing_log_snapshot_result(*_args, **_kwargs):
        return {
            "ok": False,
            "version": "V166E2_missing_log_snapshot_dependency_guard",
            "reason": "V166C/V166D LOG snapshot service dependency is missing or outdated: " + V166C_LOG_SNAPSHOT_IMPORT_ERROR,
            "rows": [],
            "candidate_count": 0,
            "missing_count": 0,
            "time_related_log_count": 0,
            "with_snapshot_count": 0,
            "without_snapshot_count": 0,
            "coverage_percent": 0.0,
            "updated_count": 0,
            "recovered_count": 0,
            "read_only": True,
            "production_write_path_changed": False,
        }

    def _v166e2_empty_excel_bytes(*_args, **_kwargs):
        from io import BytesIO
        import pandas as _pd
        bio = BytesIO()
        _pd.DataFrame([
            {
                "status": "V166C/V166D LOG snapshot service dependency is missing or outdated",
                "reason": V166C_LOG_SNAPSHOT_IMPORT_ERROR,
            }
        ]).to_excel(bio, index=False)
        bio.seek(0)
        return bio.getvalue()

    collect_log_snapshot_recovery_candidates = _v166e2_missing_log_snapshot_result
    recover_records_from_log_snapshots = _v166e2_missing_log_snapshot_result
    get_log_snapshot_status = _v166e2_missing_log_snapshot_result
    get_log_snapshot_coverage_status = _v166e2_missing_log_snapshot_result
    backfill_missing_log_snapshots = _v166e2_missing_log_snapshot_result
    export_log_snapshot_candidates_excel_bytes = _v166e2_empty_excel_bytes
    export_log_snapshot_coverage_excel_bytes = _v166e2_empty_excel_bytes

from services.page_hygiene_service import (
    collect_page_hygiene_status,
    cleanup_duplicate_mojibake_pages,
    page_hygiene_rows,
)

from services.daily_close_service import (
    close_work_date,
    daily_close_report,
    export_daily_close_excel_bytes,
    list_daily_close_status,
    reopen_work_date,
)

MODULE_CODE = "14_data_health"

st.set_page_config(page_title="14. 資料健康檢查中心", page_icon="🛡️", layout="wide")
apply_theme()

# V153B: 14 is now an independent permission-managed module.
# Do not borrow 12_module_persistence permissions and do not swallow permission errors.
require_module_access(MODULE_CODE, "can_view")

try:
    CAN_EXPORT = bool(check_permission(MODULE_CODE, "can_export") or check_permission(MODULE_CODE, "can_manage"))
except Exception:
    CAN_EXPORT = False
try:
    CAN_REPAIR = bool(check_permission(MODULE_CODE, "can_manage"))
except Exception:
    CAN_REPAIR = False

render_header("14｜資料健康檢查中心", "工時紀錄稽核、資料遺失檢查、01/02 權威檔非破壞式修復")

st.warning(
    "本頁只用於資料健康檢查與非破壞式修復。檢查不寫入；修復只合併缺漏資料到 01/02 權威檔，"
    "不刪除、不重新編號、不用畫面局部資料覆蓋完整歷史。"
)
st.caption(
    "權限說明：進入本頁需 14 模組 can_view；下載 Excel 需 can_export；執行非破壞式修復需 can_manage。"
)


st.markdown("### V166 系統監控儀表板 / System Monitoring Dashboard")
st.caption(
    "此區為唯讀監控，不寫入、不刪除、不重算、不補送 GitHub。"
    "用來快速確認線上人數估算、今日作業量、未結束作業、長時間作業、備份佇列、資料庫/寫入錯誤與資料健康摘要。"
)

if "v166_monitoring_snapshot" not in st.session_state:
    # V166E: do not run monitoring automatically when the page loads or a checkbox/editor reruns.
    # The snapshot is collected only after pressing 「刷新系統監控」.
    st.session_state["v166_monitoring_snapshot"] = {
        "version": "V166_system_monitoring_dashboard",
        "level": "IDLE",
        "risk_score": 0,
        "warnings": ["尚未執行系統監控；請按『刷新系統監控』。"],
        "metrics": {},
        "summary_rows": [],
        "read_only": True,
        "production_write_path_changed": False,
    }

v166_c1, v166_c2, v166_c3, v166_c4 = st.columns([1, 1, 1, 1])
v166_work_date = v166_c1.date_input("監控日期 / Monitor Date", value=today_date(), key="v166_monitor_date")
v166_window = v166_c2.number_input("線上估算分鐘", min_value=5, max_value=240, value=30, step=5, key="v166_active_window")
v166_include_integrity = v166_c3.checkbox("包含資料健康檢查 / Slower", value=False, key="v166_include_integrity")
v166_c4.info("預設快速監控；勾選資料健康檢查會較慢，但可顯示 LOG 有但工時缺失等異常。")

v166_b1, v166_b2 = st.columns([1, 3])
if v166_b1.button("🔄 刷新系統監控", use_container_width=True, key="v166_refresh_monitoring"):
    with st.spinner("正在讀取 01/02/06/11、SQLite、備份佇列與監控摘要；此動作唯讀不寫入..."):
        st.session_state["v166_monitoring_snapshot"] = collect_system_monitoring_snapshot(
            work_date=str(v166_work_date),
            active_user_window_minutes=int(v166_window),
            include_integrity_audit=bool(v166_include_integrity),
            integrity_start_date=str(v166_work_date),
            integrity_end_date=str(v166_work_date),
        )
    st.rerun()
v166_b2.caption("V166 不改正式資料流程；production_write_path_changed 必須維持 False。")

v166_snapshot = st.session_state.get("v166_monitoring_snapshot") or {}
v166_metrics = v166_snapshot.get("metrics", {}) if isinstance(v166_snapshot.get("metrics"), dict) else {}
v166_level = str(v166_snapshot.get("level") or "UNKNOWN")
if v166_level == "OK":
    st.success(f"系統監控狀態 OK｜檢查時間：{v166_snapshot.get('checked_at', '')}")
elif v166_level == "WARN":
    st.warning(f"系統監控有需注意項目｜風險分數：{v166_snapshot.get('risk_score', 0)}｜檢查時間：{v166_snapshot.get('checked_at', '')}")
elif v166_level == "IDLE":
    st.info("V166E：本區改為手動刷新；勾選選項或編輯表格不會自動啟動監控運算。")
else:
    st.error(f"系統監控發現高風險或檢查錯誤｜風險分數：{v166_snapshot.get('risk_score', 0)}｜檢查時間：{v166_snapshot.get('checked_at', '')}")

for warning in v166_snapshot.get("warnings", [])[:5]:
    st.caption(f"• {warning}")

v166_m1, v166_m2, v166_m3, v166_m4, v166_m5, v166_m6 = st.columns(6)
v166_m1.metric("線上估算", v166_metrics.get("active_user_estimate", 0))
v166_m2.metric("今日開始 LOG", v166_metrics.get("today_start_logs", 0))
v166_m3.metric("今日結束 LOG", v166_metrics.get("today_end_logs", 0))
v166_m4.metric("未結束作業", v166_metrics.get("active_work_total", 0))
v166_m5.metric("超過12H", v166_metrics.get("active_over_12h", 0))
v166_m6.metric("DB/寫入錯誤", v166_metrics.get("today_db_write_error_logs", 0))

v166_m7, v166_m8, v166_m9, v166_m10, v166_m11, v166_m12 = st.columns(6)
v166_m7.metric("今日工時紀錄", v166_metrics.get("today_time_records", 0))
v166_m8.metric("GitHub待上傳", v166_metrics.get("backup_authority_pending", 0))
v166_m9.metric("事件待上傳", v166_metrics.get("backup_event_pending", 0))
v166_m10.metric("LOG待同步", "是" if v166_metrics.get("backup_log_pending") else "否")
v166_m11.metric("健康重大異常", v166_metrics.get("integrity_critical", "未檢查"))
v166_m12.metric("LOG缺工時", v166_metrics.get("log_start_missing_count", "未檢查"))

try:
    st.dataframe(pd.DataFrame(monitoring_summary_rows(v166_snapshot)), use_container_width=True, hide_index=True, height=300)
except Exception:
    pass

with st.expander("V166 監控詳細資料 / Monitoring Details", expanded=False):
    tab_active, tab_long, tab_users, tab_process, tab_sources, tab_raw = st.tabs([
        "未結束作業", "長時間作業", "線上估算", "今日工段", "來源統計", "原始摘要"
    ])
    with tab_active:
        st.dataframe(pd.DataFrame(v166_snapshot.get("active_work_preview_rows", [])), use_container_width=True, hide_index=True, height=320)
    with tab_long:
        st.dataframe(pd.DataFrame(v166_snapshot.get("long_active_over_12h_rows", [])), use_container_width=True, hide_index=True, height=320)
    with tab_users:
        st.dataframe(pd.DataFrame(v166_snapshot.get("active_users_rows", [])), use_container_width=True, hide_index=True, height=320)
    with tab_process:
        st.dataframe(pd.DataFrame(v166_snapshot.get("process_rows", [])), use_container_width=True, hide_index=True, height=320)
    with tab_sources:
        st.dataframe(pd.DataFrame(v166_snapshot.get("source_rows", [])), use_container_width=True, hide_index=True, height=320)
    with tab_raw:
        st.json({
            "version": v166_snapshot.get("version"),
            "checked_at": v166_snapshot.get("checked_at"),
            "level": v166_snapshot.get("level"),
            "risk_score": v166_snapshot.get("risk_score"),
            "read_only": v166_snapshot.get("read_only"),
            "production_write_path_changed": v166_snapshot.get("production_write_path_changed"),
            "sqlite_info": v166_snapshot.get("sqlite_info"),
            "last_backup": v166_snapshot.get("last_backup"),
            "backup_summary": {k: v for k, v in (v166_snapshot.get("backup_summary") or {}).items() if k != "raw"},
            "integrity_summary": v166_snapshot.get("integrity_summary"),
        })

if CAN_EXPORT:
    st.download_button(
        "⬇️ 下載 V166 系統監控 Excel",
        data=export_monitoring_excel_bytes(v166_snapshot),
        file_name=f"SPT_V166_系統監控_{v166_snapshot.get('work_date', '')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="v166_download_monitoring_excel",
    )
else:
    st.info("你的帳號沒有 14 模組匯出權限，因此不能下載 V166 系統監控 Excel。")

st.divider()


st.markdown("### V163 每日資料結帳與鎖定 / Daily Close & Lock")
st.caption(
    "此區用於每日結帳、鎖定已結帳日期、建立結帳備份與輸出結帳報告。"
    "鎖定後該日期的開始、結束、儲存、刪除、重算與匯入會被保護；如需更正，請先重新開啟日期。"
)

v163_today = today_date()
if "v163_daily_close_report" not in st.session_state:
    st.session_state["v163_daily_close_report"] = None
if "v163_daily_close_action" not in st.session_state:
    st.session_state["v163_daily_close_action"] = None

v163_c1, v163_c2, v163_c3, v163_c4 = st.columns([1, 1, 1, 1])
v163_work_date = v163_c1.date_input("結帳日期 / Work Date", value=v163_today, key="v163_work_date")
v163_create_backup = v163_c2.checkbox("結帳時建立完整備份", value=True, disabled=not CAN_REPAIR, key="v163_create_backup")
v163_block_critical = v163_c3.checkbox("有重大異常時阻止結帳", value=True, disabled=not CAN_REPAIR, key="v163_block_critical")
v163_require_no_active = v163_c4.checkbox("有未結束作業時阻止結帳", value=True, disabled=not CAN_REPAIR, key="v163_require_no_active")

v163_note = st.text_input("結帳備註 / Note", value="", key="v163_close_note")

v163_b1, v163_b2, v163_b3, v163_b4 = st.columns([1, 1, 1, 1])
if v163_b1.button("🔍 檢查結帳狀態", use_container_width=True, key="v163_check_daily_close"):
    with st.spinner("正在檢查當日工時、未結束作業與資料健康摘要..."):
        st.session_state["v163_daily_close_report"] = daily_close_report(str(v163_work_date))
    st.rerun()

v163_confirm_close = v163_b2.checkbox("確認結帳", value=False, disabled=not CAN_REPAIR, key="v163_confirm_close")
if v163_b3.button(
    "✅ 執行每日結帳並鎖定",
    use_container_width=True,
    disabled=(not CAN_REPAIR) or (not v163_confirm_close),
    key="v163_close_work_date",
):
    with st.spinner("正在執行每日結帳：檢查未結束作業、資料健康摘要與建立備份..."):
        st.session_state["v163_daily_close_action"] = close_work_date(
            str(v163_work_date),
            note=v163_note,
            require_no_active=bool(v163_require_no_active),
            create_backup=bool(v163_create_backup),
            block_on_critical_health=bool(v163_block_critical),
        )
        st.session_state["v163_daily_close_report"] = daily_close_report(str(v163_work_date))
    st.rerun()

v163_confirm_reopen = v163_b4.checkbox("確認重新開啟", value=False, disabled=not CAN_REPAIR, key="v163_confirm_reopen")
if st.button(
    "🔓 重新開啟已結帳日期以便更正",
    use_container_width=True,
    disabled=(not CAN_REPAIR) or (not v163_confirm_reopen),
    key="v163_reopen_work_date",
):
    with st.spinner("正在重新開啟已結帳日期；此動作只解除鎖定，不修改工時資料..."):
        st.session_state["v163_daily_close_action"] = reopen_work_date(str(v163_work_date), reason=v163_note or "管理員重新開啟日期更正")
        st.session_state["v163_daily_close_report"] = daily_close_report(str(v163_work_date))
    st.rerun()

v163_action = st.session_state.get("v163_daily_close_action")
if isinstance(v163_action, dict) and v163_action:
    if v163_action.get("ok"):
        st.success("V163 操作完成。")
    else:
        reason = v163_action.get("reason") or "unknown"
        if reason == "active_records_exist":
            st.error(f"仍有未結束作業 {v163_action.get('active_count', 0)} 筆，已阻止結帳。請先下班/暫停/完工，或取消『有未結束作業時阻止結帳』後再執行。")
        elif reason == "critical_health_issues":
            st.error(f"資料健康檢查仍有重大異常 {v163_action.get('critical_count', 0)} 筆，已阻止結帳。")
        else:
            st.warning(f"V163 操作未完成：{reason}")
    with st.expander("V163 最近一次操作結果", expanded=False):
        st.json(v163_action)

v163_report = st.session_state.get("v163_daily_close_report")
if not isinstance(v163_report, dict) or not v163_report:
    try:
        v163_report = daily_close_report(str(v163_work_date))
    except Exception as exc:
        v163_report = {"ok": False, "error": str(exc), "work_date": str(v163_work_date)}

if isinstance(v163_report, dict):
    dc1, dc2, dc3, dc4, dc5 = st.columns(5)
    dc1.metric("工作日期", v163_report.get("work_date", str(v163_work_date)))
    dc2.metric("結帳狀態", "已鎖定" if v163_report.get("closed") else "未結帳")
    dc3.metric("當日工時筆數", v163_report.get("record_count", 0))
    dc4.metric("未結束作業", v163_report.get("active_count", 0))
    hs = v163_report.get("health_summary") if isinstance(v163_report.get("health_summary"), dict) else {}
    dc5.metric("重大異常", hs.get("critical_count", 0) if isinstance(hs, dict) else 0)

    if v163_report.get("closed"):
        close_info = v163_report.get("close_info") if isinstance(v163_report.get("close_info"), dict) else {}
        st.success(f"{v163_report.get('work_date')} 已結帳鎖定。結帳人：{close_info.get('closed_by','')}；時間：{close_info.get('closed_at','')}。")
    else:
        if int(v163_report.get("active_count") or 0) > 0:
            st.warning("此日期仍有未結束作業，建議先處理完再結帳。")
        else:
            st.info("此日期尚未結帳；若確認資料正確，可執行每日結帳並鎖定。")

    if v163_report.get("active_records"):
        with st.expander("V163 未結束作業明細 / Active Records Blocking Close", expanded=True):
            st.dataframe(pd.DataFrame(v163_report.get("active_records") or []), use_container_width=True, hide_index=True, height=260)

    with st.expander("V163 當日狀態統計與健康摘要", expanded=False):
        st.json({
            "status_counts": v163_report.get("status_counts", {}),
            "health_summary": v163_report.get("health_summary", {}),
            "close_info": v163_report.get("close_info", {}),
        })

    if CAN_EXPORT:
        try:
            st.download_button(
                "⬇️ 下載 V163 每日結帳報告 Excel",
                data=export_daily_close_excel_bytes(str(v163_work_date)),
                file_name=f"SPT_V163_每日結帳報告_{v163_work_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="v163_download_daily_close_excel",
            )
        except Exception as exc:
            st.warning(f"產生 V163 Excel 報告失敗：{exc}")

with st.expander("最近 14 日結帳狀態 / Recent Daily Close Status", expanded=False):
    try:
        st.dataframe(list_daily_close_status(end_date=str(v163_work_date), days=14), use_container_width=True, hide_index=True, height=320)
    except Exception as exc:
        st.error(f"讀取每日結帳狀態失敗：{exc}")

if not CAN_REPAIR:
    st.info("你的帳號沒有 14 模組 can_manage 權限，因此只能查看結帳狀態，不能執行結帳或重新開啟。")

st.divider()


st.markdown("### V159 頁面路由健康檢查 / Page Route Hygiene")
st.caption(
    "此區檢查 pages 目錄是否仍有 #Uxxxx 舊亂碼頁面。若同一模組同時存在舊亂碼頁與正常中文頁，"
    "Streamlit 會多掃描舊頁面，還可能載入舊邏輯，造成頁面變慢或修正看似未生效。"
)
if "v159_page_hygiene_status" not in st.session_state:
    try:
        st.session_state["v159_page_hygiene_status"] = collect_page_hygiene_status()
    except Exception as exc:
        st.session_state["v159_page_hygiene_status"] = {"status": "ERROR", "items": [], "error": str(exc)}

v159_c1, v159_c2, v159_c3 = st.columns([1, 1, 2])
if v159_c1.button("🔄 重新檢查頁面路由", use_container_width=True, key="v159_refresh_page_hygiene"):
    st.session_state["v159_page_hygiene_status"] = collect_page_hygiene_status()
    st.rerun()

v159_confirm_cleanup = v159_c2.checkbox(
    "確認清理安全重複頁",
    value=False,
    disabled=not CAN_REPAIR,
    key="v159_confirm_cleanup",
    help="只會清理已有正常中文頁面對應的 #Uxxxx 舊頁面。",
)
if v159_c3.button(
    "🧹 清理重複 #U 舊頁面",
    use_container_width=True,
    disabled=(not CAN_REPAIR) or (not v159_confirm_cleanup),
    key="v159_apply_page_cleanup",
):
    st.session_state["v159_page_hygiene_cleanup_result"] = cleanup_duplicate_mojibake_pages(apply=True)
    st.session_state["v159_page_hygiene_status"] = collect_page_hygiene_status()
    st.rerun()

v159_status = st.session_state.get("v159_page_hygiene_status") or {}
v159_summary_cols = st.columns(4)
v159_summary_cols[0].metric("頁面檔總數", v159_status.get("total_py_pages", 0))
v159_summary_cols[1].metric("#U 舊頁面", v159_status.get("mojibake_pages", 0))
v159_summary_cols[2].metric("可安全清理", v159_status.get("safe_to_remove", 0))
v159_summary_cols[3].metric("需暫時保留", v159_status.get("must_keep", 0))

if str(v159_status.get("status") or "") == "OK":
    st.success("頁面路由正常：沒有偵測到 #Uxxxx 舊亂碼頁面。")
elif int(v159_status.get("safe_to_remove", 0) or 0) > 0:
    st.warning("偵測到可安全清理的重複 #U 舊頁面。建議清理後 Commit / Push，再 Reboot App。")
elif int(v159_status.get("must_keep", 0) or 0) > 0:
    st.info("仍有 #U 頁面，但目前沒有正常中文頁面可替代，因此系統暫時保留，避免模組消失。")

v159_rows = v159_status.get("items", [])
if v159_rows:
    with st.expander("V159 頁面路由檢查明細", expanded=False):
        st.dataframe(pd.DataFrame(v159_rows), use_container_width=True, hide_index=True, height=260)

v159_cleanup_result = st.session_state.get("v159_page_hygiene_cleanup_result")
if isinstance(v159_cleanup_result, dict) and v159_cleanup_result:
    with st.expander("最近一次 V159 清理結果", expanded=False):
        st.json(v159_cleanup_result)

st.divider()


st.markdown("### V158 一鍵備份 / 還原中心")
st.caption(
    "此區用於建立完整資料備份 ZIP，以及從備份 ZIP 非破壞式補回缺失的工時紀錄。"
    "還原只補缺漏，不刪除、不覆蓋、不重新編號，並尊重 02_history tombstone。"
)

v158_c1, v158_c2, v158_c3 = st.columns([1, 1, 2])
if "v158_backup_result" not in st.session_state:
    st.session_state["v158_backup_result"] = None
if "v158_inspect_result" not in st.session_state:
    st.session_state["v158_inspect_result"] = None
if "v158_restore_result" not in st.session_state:
    st.session_state["v158_restore_result"] = None

create_backup_disabled = not CAN_REPAIR
if v158_c1.button("📦 建立完整備份 ZIP", use_container_width=True, disabled=create_backup_disabled, key="v158_create_backup"):
    with st.spinner("正在建立完整資料備份 ZIP；此動作只讀取資料，不修改正式紀錄..."):
        st.session_state["v158_backup_result"] = create_full_backup_snapshot(reason="manual_v158_from_health_center", save_to_disk=True)
    st.rerun()

if v158_c2.button("🔄 重新讀取最近備份", use_container_width=True, key="v158_refresh_backup_list"):
    st.session_state.pop("v158_backup_list", None)
    st.rerun()

if create_backup_disabled:
    v158_c3.info("你的帳號沒有 14 模組 can_manage 權限，不能建立備份或執行還原。")
else:
    v158_c3.info("建議每次大版本更新前，先建立完整備份 ZIP 並下載保存。")

v158_backup_result = st.session_state.get("v158_backup_result")
if isinstance(v158_backup_result, dict) and v158_backup_result.get("ok"):
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("備份檔案數", v158_backup_result.get("file_count", 0))
    b2.metric("備份大小", f"{int(v158_backup_result.get('size', 0) or 0) / 1024:.1f} KB")
    b3.metric("建立時間", v158_backup_result.get("created_at", ""))
    b4.metric("SHA256", str(v158_backup_result.get("sha256", ""))[:10] + "...")
    st.success("完整備份 ZIP 已建立。請下載保存；本機也會留存在 data/permanent_store/_backups/v158。")
    st.download_button(
        "⬇️ 下載完整備份 ZIP",
        data=v158_backup_result.get("zip_bytes", b""),
        file_name=v158_backup_result.get("file_name", "SPT_V158_full_backup.zip"),
        mime="application/zip",
        use_container_width=True,
        disabled=not CAN_EXPORT,
        help=None if CAN_EXPORT else "你的帳號沒有 14 模組匯出權限。",
        key="v158_download_backup_zip",
    )

with st.expander("最近本機備份 / Recent Local Backups", expanded=False):
    try:
        backup_list = list_backup_snapshots(limit=10)
        if backup_list:
            st.dataframe(pd.DataFrame(backup_list), use_container_width=True, hide_index=True, height=260)
        else:
            st.info("尚未建立 V158 本機備份。")
    except Exception as exc:
        st.error(f"讀取最近備份失敗：{exc}")

st.markdown("#### 檢查備份 ZIP / Inspect Backup ZIP")
backup_file = st.file_uploader(
    "上傳 V158 備份 ZIP，僅用於檢查或非破壞式補回缺失工時資料",
    type=["zip"],
    key="v158_backup_uploader",
)
if backup_file is not None:
    uploaded_bytes = backup_file.getvalue()
    if st.button("🔎 檢查上傳的備份 ZIP", use_container_width=True, key="v158_inspect_uploaded_backup"):
        st.session_state["v158_inspect_result"] = inspect_backup_zip_bytes(uploaded_bytes)
        st.session_state["v158_restore_result"] = None
        st.rerun()

inspect_result = st.session_state.get("v158_inspect_result")
if isinstance(inspect_result, dict) and inspect_result:
    if inspect_result.get("ok"):
        st.success("備份 ZIP 可讀取。")
        st.dataframe(pd.DataFrame(backup_manifest_rows(inspect_result)), use_container_width=True, hide_index=True, height=260)
    else:
        st.error(f"備份 ZIP 無法讀取：{inspect_result.get('reason')}")

if backup_file is not None and isinstance(inspect_result, dict) and inspect_result.get("ok"):
    st.markdown("#### 非破壞式補回缺失工時資料 / Non-destructive Missing Row Restore")
    st.caption(
        "此功能只會從備份 ZIP 找出目前 01/02 缺少的 time_records 並補回。"
        "現有資料不覆蓋；已刪除 tombstone 資料不復活；預設先 Dry Run。"
    )
    r1, r2, r3 = st.columns([1, 1, 2])
    restore_dry_run = r1.checkbox("只模擬 / Dry Run", value=True, key="v158_restore_dry_run")
    restore_github = r2.checkbox("套用後同步 GitHub", value=True, disabled=restore_dry_run or not CAN_REPAIR, key="v158_restore_github")
    if not CAN_REPAIR:
        r3.info("你的帳號沒有 14 模組 can_manage 權限，不能執行補回。")
    else:
        r3.warning("實際補回前請先確認 Dry Run 結果；補回為新增缺漏列，不會刪除或覆蓋現有列。")
    if st.button("🛠️ 從備份非破壞式補回缺失工時資料", use_container_width=True, disabled=not CAN_REPAIR, key="v158_restore_missing"):
        with st.spinner("正在比對備份與目前 01/02 資料；只補缺漏，不覆蓋現有資料..."):
            st.session_state["v158_restore_result"] = restore_missing_time_records_from_backup(
                uploaded_bytes,
                dry_run=bool(restore_dry_run),
                github=bool(restore_github),
                reason="manual_v158_restore_from_health_center",
            )
        st.rerun()

restore_result = st.session_state.get("v158_restore_result")
if isinstance(restore_result, dict) and restore_result:
    if restore_result.get("ok"):
        rr1, rr2, rr3, rr4, rr5 = st.columns(5)
        rr1.metric("備份工時列", restore_result.get("backup_total_rows", 0))
        rr2.metric("目前工時列", restore_result.get("current_total_rows", 0))
        rr3.metric("可補回缺漏", restore_result.get("missing_rows", 0))
        rr4.metric("略過已存在", restore_result.get("skipped_existing", 0))
        rr5.metric("略過已刪除", restore_result.get("skipped_deleted_tombstone", 0))
        if restore_result.get("dry_run"):
            st.info("Dry Run 完成，尚未寫入。確認缺漏筆數合理後，可取消 Dry Run 再執行。")
        else:
            st.success(
                f"補回完成：01/02 權威檔目前 {restore_result.get('saved_authority_rows', 0)} 筆；"
                f"SQLite cache 補入 {restore_result.get('sqlite_inserted', 0)} 筆。"
            )
        with st.expander("補回結果詳細資料 / Restore Detail", expanded=False):
            st.json(restore_result)
    else:
        st.error(f"補回失敗：{restore_result.get('reason')}")

st.divider()

st.markdown("### 備份佇列狀態 / Backup Queue Status")
st.caption(
    "此區只顯示與補送備份佇列，不修改工時內容、不刪除、不重算、不覆蓋 01/02 歷史。"
)
if "v155_backup_status" not in st.session_state:
    try:
        st.session_state["v155_backup_status"] = collect_backup_queue_status()
    except Exception as exc:
        st.session_state["v155_backup_status"] = {"level": "ERROR", "summary": {}, "errors": [{"source": "status", "error": str(exc)}]}

bs1, bs2, bs3 = st.columns([1, 1, 2])
if bs1.button("🔄 重新讀取備份狀態", use_container_width=True, key="v155_refresh_backup_status"):
    st.session_state["v155_backup_status"] = collect_backup_queue_status()
    st.rerun()

flush_disabled = not CAN_REPAIR
if bs2.button("☁️ 手動補送備份佇列", use_container_width=True, disabled=flush_disabled, key="v155_flush_backup_queue"):
    with st.spinner("正在補送 GitHub 權威檔 / LOG / 工時事件佇列，這不會修改工時資料..."):
        st.session_state["v155_flush_result"] = flush_backup_queues_now(reason="manual_v155_from_health_center", max_seconds=14)
        st.session_state["v155_backup_status"] = st.session_state["v155_flush_result"].get("after") or collect_backup_queue_status()
    st.rerun()
if flush_disabled:
    bs3.info("你的帳號沒有 14 模組 can_manage 權限，只能查看狀態，不能手動補送備份。")

backup_status = st.session_state.get("v155_backup_status") or {}
summary = backup_status.get("summary", {}) if isinstance(backup_status.get("summary"), dict) else {}
level = str(backup_status.get("level") or "UNKNOWN")
if level == "OK":
    st.success(f"備份佇列狀態正常。檢查時間：{backup_status.get('checked_at', '')}")
elif level == "WARN":
    st.warning(f"仍有待補送或需注意的備份項目。檢查時間：{backup_status.get('checked_at', '')}")
else:
    st.error(f"備份狀態有錯誤，請展開詳細資訊。檢查時間：{backup_status.get('checked_at', '')}")

bk1, bk2, bk3, bk4, bk5 = st.columns(5)
bk1.metric("權威檔待上傳", summary.get("authority_pending", 0))
bk2.metric("工時事件待上傳", summary.get("event_pending", 0))
bk3.metric("LOG 待同步", "是" if summary.get("log_pending") else "否")
bk4.metric("LOG 未同步數", summary.get("log_write_count_since_sync", 0))
bk5.metric("錯誤數", summary.get("error_count", 0))

try:
    st.dataframe(pd.DataFrame(status_rows_for_table(backup_status)), use_container_width=True, hide_index=True, height=230)
except Exception:
    pass

with st.expander("備份佇列詳細資料 / Backup Queue Details", expanded=False):
    st.json(backup_status)

if "v155_flush_result" in st.session_state:
    with st.expander("最近一次手動補送結果 / Last Manual Flush Result", expanded=False):
        st.json(st.session_state["v155_flush_result"])


st.markdown("### V157 自動回歸測試 / 50人壓力模擬")
st.caption(
    "此測試完全在暫存沙盒資料庫中執行，不寫正式工時資料、不寫 GitHub、不刪除、不重算。"
    "目的：更新後快速驗證多人同時紀錄、多筆同步作業、事件紀錄、row shard 與 Active Work 防呆是否仍正常。"
)

v157_c1, v157_c2, v157_c3 = st.columns([1, 1, 2])
v157_workers = v157_c1.number_input("模擬人數 / Simulated Users", min_value=1, max_value=200, value=50, step=1, key="v157_workers")
v157_parallel = v157_c2.number_input("每人同步作業筆數", min_value=1, max_value=5, value=2, step=1, key="v157_parallel")
v157_c3.info("建議正式部署後先跑 50 人 × 每人 2 筆。測試結果只代表核心資料邏輯與併發保護，不會修改正式資料。")

if "v157_regression_result" not in st.session_state:
    st.session_state["v157_regression_result"] = None

run_disabled = not CAN_REPAIR
if st.button("🧪 執行 V157 回歸測試 + 壓力模擬", use_container_width=True, disabled=run_disabled, key="v157_run_regression"):
    if run_disabled:
        st.error("你的帳號沒有 14 模組 can_manage 權限，不能執行壓力模擬。")
    else:
        progress_bar = st.progress(0.0)
        progress_text = st.empty()
        def _v157_progress(pct: float, msg: str) -> None:
            try:
                progress_bar.progress(min(max(float(pct), 0.0), 1.0))
                progress_text.caption(msg)
            except Exception:
                pass
        with st.spinner("V157 正在執行非破壞式沙盒壓力測試..."):
            st.session_state["v157_regression_result"] = run_v157_regression_suite(
                worker_count=int(v157_workers),
                works_per_worker=int(v157_parallel),
                include_import_checks=True,
                progress_callback=_v157_progress,
            )
        st.rerun()

if run_disabled:
    st.info("你的帳號沒有 14 模組 can_manage 權限，因此只能查看本區說明，不能執行壓力模擬。")

v157_result = st.session_state.get("v157_regression_result")
if v157_result:
    v157_summary = v157_result.get("summary", {}) if isinstance(v157_result.get("summary"), dict) else {}
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("PASS", v157_summary.get("pass_count", 0))
    r2.metric("WARN", v157_summary.get("warn_count", 0))
    r3.metric("FAIL", v157_summary.get("fail_count", 0))
    r4.metric("模擬紀錄數", v157_summary.get("expected_records", 0))
    r5.metric("耗時秒", v157_result.get("elapsed_seconds", 0))
    if bool(v157_result.get("ok")):
        st.success("V157 回歸測試通過：沙盒壓力測試未發現資料遺失、覆蓋或假作業中。")
    else:
        st.error("V157 回歸測試發現 FAIL，請展開檢查結果確認。")
    v157_rows = compact_result_rows(v157_result)
    if v157_rows:
        st.dataframe(pd.DataFrame(v157_rows), use_container_width=True, hide_index=True, height=360)
    v157_excel = export_v157_regression_excel_bytes(v157_result)
    st.download_button(
        "⬇️ 下載 V157 測試報告 Excel",
        data=v157_excel,
        file_name=f"SPT_V157_回歸測試_50人壓力模擬_{today_date()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=not CAN_EXPORT,
        help=None if CAN_EXPORT else "你的帳號沒有 14 模組匯出權限。",
        key="v157_download_excel",
    )
    with st.expander("V157 原始測試結果 JSON", expanded=False):
        safe = dict(v157_result)
        if isinstance(safe.get("checks"), pd.DataFrame):
            safe["checks"] = safe["checks"].to_dict(orient="records")
        st.json(safe)

st.divider()

if "v153_audit_result" not in st.session_state:
    st.session_state["v153_audit_result"] = None

c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
start_date = c1.date_input("檢查開始日期 / Start", value=today_date() - timedelta(days=7), key="v153_start_date")
end_date = c2.date_input("檢查結束日期 / End", value=today_date(), key="v153_end_date")
github_backup = c3.checkbox(
    "修復後同步 GitHub",
    value=True,
    help="正式修復建議勾選；若 GitHub 很慢，可先取消，之後再手動備份。",
    disabled=not CAN_REPAIR,
)
dry_run = c4.checkbox("只模擬修復 / Dry Run", value=True, disabled=not CAN_REPAIR)

b1, b2, b3 = st.columns([1, 1, 1])
if b1.button("🔍 執行資料健康檢查", use_container_width=True, key="v153_run_audit"):
    if start_date > end_date:
        st.error("開始日期不可大於結束日期。")
        st.stop()
    with st.spinner("正在比對 LOG、01/02 權威檔、SQLite、row shard、event journal..."):
        st.session_state["v153_audit_result"] = audit_time_record_integrity(str(start_date), str(end_date))
    st.rerun()

result = st.session_state.get("v153_audit_result")

if result:
    summary = result.get("summary", {})
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("合併後工時筆數", summary.get("merged_records", 0))
    s2.metric("START LOG 筆數", summary.get("log_start_count", 0))
    s3.metric("異常總數", summary.get("issue_count", 0))
    s4.metric("重大異常", summary.get("critical_count", 0))
    s5.metric("可自動修復", summary.get("repairable_count", 0))

    issues = result.get("issues")
    if isinstance(issues, pd.DataFrame) and not issues.empty:
        st.markdown("### 異常清單 / Issue List")
        st.dataframe(issues, use_container_width=True, hide_index=True, height=520)
    else:
        st.success("目前檢查範圍內未發現工時資料重大異常。")

    with st.expander("來源統計 / Source Counts", expanded=False):
        st.json(summary.get("source_counts", {}))

    with st.expander("合併後資料預覽 / Merged Records Preview", expanded=False):
        merged = result.get("merged_records")
        if isinstance(merged, pd.DataFrame) and not merged.empty:
            st.dataframe(merged.head(500), use_container_width=True, hide_index=True, height=420)
        else:
            st.info("沒有可預覽的合併資料。")

    excel_bytes = export_audit_excel_bytes(result)
    st.download_button(
        "⬇️ 下載資料健康檢查 Excel",
        data=excel_bytes,
        file_name=f"SPT_V153_資料健康檢查_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        disabled=not CAN_EXPORT,
        help=None if CAN_EXPORT else "你的帳號沒有 14 模組匯出權限。",
    )

    st.divider()
    st.markdown("### 非破壞式修復 / Non-destructive Repair")
    st.caption(
        "修復會把 02_history、01_time_records、SQLite、row shard、event row 中仍可完整還原的工時資料合併後，"
        "寫回 01/02 canonical。只剩 LOG 的資料不會自動補，避免產生不完整紀錄。"
    )

    if not CAN_REPAIR:
        st.info("你的帳號沒有 14 模組管理權限，因此只能檢查，不能執行修復。")
    else:
        confirm = st.checkbox("我確認執行非破壞式合併修復", key="v153_confirm_repair")
        if b2.button("🛠️ 執行非破壞式修復", use_container_width=True, disabled=not confirm, key="v153_repair_button"):
            with st.spinner("正在進行非破壞式合併修復..."):
                repair_result = repair_0102_authority_non_destructive(
                    github=bool(github_backup),
                    start_date=str(start_date),
                    end_date=str(end_date),
                    dry_run=bool(dry_run),
                )
            st.session_state["v153_repair_result"] = repair_result
            if repair_result.get("ok"):
                st.success("修復流程完成。" + ("（Dry Run，未寫入）" if repair_result.get("dry_run") else ""))
            else:
                st.error(f"修復未執行或失敗：{repair_result.get('reason')}")
            st.json(repair_result)

    st.markdown("### LOG-only 待補還原 / LOG-only Pending Recovery")
    st.caption(
        "上方可自動修復 = NO 的 LOG_START_MISSING_TIME_RECORD，代表只剩 LOG 能證明曾按下開始，"
        "但 LOG 不含完整 INSERT 參數，所以不能直接算成正式工時。此功能只會新增『待人工確認』補登列，"
        "不刪除、不覆蓋、不重新編號，補回後請到 01/02 檢查 P/N、機型、組立地點、結束時間與工時。"
    )
    if not CAN_REPAIR:
        st.info("你的帳號沒有 14 模組管理權限，因此不能從 LOG 建立待補還原紀錄。")
    else:
        log_recovery_confirm = st.checkbox(
            "我確認從 LOG 建立待人工確認的補登紀錄",
            key="v164b_confirm_log_only_recovery",
        )
        if st.button(
            "🧩 從 LOG 建立待補工時紀錄",
            use_container_width=True,
            disabled=not log_recovery_confirm,
            key="v164b_log_only_recovery_button",
        ):
            with st.spinner("正在從 LOG 產生待補還原紀錄..."):
                log_recovery_result = recover_log_only_start_records_to_pending(
                    github=bool(github_backup),
                    start_date=str(start_date),
                    end_date=str(end_date),
                    dry_run=bool(dry_run),
                )
            st.session_state["v164b_log_recovery_result"] = log_recovery_result
            if log_recovery_result.get("ok"):
                st.success(
                    "LOG 待補還原流程完成。"
                    + ("（Dry Run，未寫入）" if log_recovery_result.get("dry_run") else "")
                    + f" 候選 {log_recovery_result.get('candidate_count', 0)} 筆，"
                    + f"01 新增 {log_recovery_result.get('created_01_count', 0)} 筆，"
                    + f"02 新增 {log_recovery_result.get('created_02_count', 0)} 筆。"
                )
            else:
                st.error(f"LOG 待補還原失敗：{log_recovery_result.get('reason')}")
            st.json(log_recovery_result)

    if st.session_state.get("v164b_log_recovery_result"):
        with st.expander("V164B LOG 待補還原結果", expanded=False):
            st.json(st.session_state.get("v164b_log_recovery_result"))



st.divider()
st.markdown("### V166B LOG-only 待補紀錄人工結算 / Pending Recovery Close")
st.caption(
    "此區專門結算 V164B 從 LOG 救回的『待人工確認』資料。"
    "不會把舊資料塞回 01 Active Work，也不會觸發一般開始/結束流程；只在你確認結束時間後，"
    "更新 01/02 權威檔、計算扣休息後工時、寫入 event journal、row shard 與 LOG。"
)

v166b_c1, v166b_c2, v166b_c3 = st.columns([1, 1, 2])
v166b_suggest_hours = v166b_c1.number_input(
    "建議下一筆開始搜尋小時", min_value=1, max_value=48, value=18, step=1, key="v166b_suggest_hours"
)
v166b_c2.metric("目前模式", "Dry Run" if dry_run else "正式寫入")
v166b_c3.info("建議先 Dry Run，確認結束時間與工時正確後，再取消 Dry Run 正式結算。")

if "v166b_pending_close_snapshot" not in st.session_state:
    st.session_state["v166b_pending_close_snapshot"] = None
if "v166b_pending_close_result" not in st.session_state:
    st.session_state["v166b_pending_close_result"] = None

v166b_refresh_col, v166b_export_col = st.columns([1, 1])
if v166b_refresh_col.button("🔄 重新讀取待補結算清單", use_container_width=True, key="v166b_refresh_pending_close"):
    with st.spinner("正在讀取 V164B 待人工確認資料，並尋找同工號下一筆開始時間作為結束建議..."):
        st.session_state["v166b_pending_close_snapshot"] = collect_log_only_pending_close_candidates(
            start_date=str(start_date),
            end_date=str(end_date),
            suggestion_max_hours=int(v166b_suggest_hours),
        )
        st.session_state.pop("v166b_pending_close_effective_df", None)
    st.rerun()

if st.session_state.get("v166b_pending_close_snapshot") is None:
    # V166E: no automatic query on page load/editor rerun. Press reload button to collect candidates.
    st.session_state["v166b_pending_close_snapshot"] = {
        "ok": True, "manual_refresh_required": True, "rows": [], "pending_count": 0,
        "suggested_count": 0, "checked_at": "尚未讀取，請按『重新讀取待補結算清單』"
    }

v166b_snapshot = st.session_state.get("v166b_pending_close_snapshot") or {}
v166b_rows = v166b_snapshot.get("rows", []) if isinstance(v166b_snapshot, dict) else []
v166b_pending_count = int(v166b_snapshot.get("pending_count", 0) or 0) if isinstance(v166b_snapshot, dict) else 0
v166b_suggested_count = int(v166b_snapshot.get("suggested_count", 0) or 0) if isinstance(v166b_snapshot, dict) else 0

v166b_m1, v166b_m2, v166b_m3 = st.columns(3)
v166b_m1.metric("待補結算筆數", v166b_pending_count)
v166b_m2.metric("有建議結束時間", v166b_suggested_count)
v166b_m3.metric("檢查時間", v166b_snapshot.get("checked_at", "") if isinstance(v166b_snapshot, dict) else "")

if v166b_pending_count <= 0:
    st.success("目前日期範圍內沒有 V164B LOG-only 待人工確認未結算資料。")
else:
    st.warning(
        "請確認每筆結束時間。若『建議結束時間』空白，請手動輸入；"
        "若系統用同工號下一筆開始時間建議，仍需由管理員確認現場事實。"
    )
    v166b_df = pd.DataFrame(v166b_rows)
    editable_cols = [
        "結算 / Close", "identity_key", "record_key", "id", "工號 / Employee ID", "姓名 / Name",
        "製令 / Work Order", "工段 / Process", "開始時間 / Start", "建議結束時間 / Suggested End",
        "結束時間 / End Timestamp", "結束狀態 / Close Status", "補登備註 / Close Note", "建議來源 / Suggestion"
    ]
    for col in editable_cols:
        if col not in v166b_df.columns:
            v166b_df[col] = ""
    v166b_df = v166b_df[editable_cols]
    column_config = {}
    try:
        column_config = {
            "結算 / Close": st.column_config.CheckboxColumn("結算", help="勾選後才會納入補登結算"),
            "結束狀態 / Close Status": st.column_config.SelectboxColumn(
                "結束狀態", options=["補登結束", "下班", "暫停", "完工"], required=True
            ),
            "補登備註 / Close Note": st.column_config.TextColumn("補登備註"),
            "結束時間 / End Timestamp": st.column_config.TextColumn("結束時間 / End Timestamp", help="格式：YYYY-MM-DD HH:MM:SS"),
        }
    except Exception:
        column_config = {}
    # V166E: keep the editor inside a form, so checkbox/cell edits do not rerun the page
    # or trigger expensive collection logic.  Changes are committed only by pressing the form submit.
    stored_v166b_df = st.session_state.get("v166b_pending_close_effective_df")
    if isinstance(stored_v166b_df, pd.DataFrame) and set(["identity_key", "record_key"]).issubset(stored_v166b_df.columns):
        try:
            current_keys = set(v166b_df["identity_key"].astype(str).tolist())
            stored_keys = set(stored_v166b_df["identity_key"].astype(str).tolist())
            if current_keys == stored_keys:
                v166b_df = stored_v166b_df.copy()
        except Exception:
            pass

    sb1, sb2, sb3 = st.columns([1, 1, 2])
    if sb1.button("☑️ 結算全部勾選", use_container_width=True, key="v166b2_select_all_pending_close"):
        v166b_df["結算 / Close"] = True
        st.session_state["v166b_pending_close_effective_df"] = v166b_df.copy()
        st.rerun()
    if sb2.button("⬜ 結算全部取消勾選", use_container_width=True, key="v166b2_clear_all_pending_close"):
        v166b_df["結算 / Close"] = False
        st.session_state["v166b_pending_close_effective_df"] = v166b_df.copy()
        st.rerun()
    sb3.caption("V166E：勾選或填入結束時間後，先按下方『暫存勾選與結束時間』，不會自動執行結算。")

    with st.form("v166e_v166b_pending_close_editor_form", clear_on_submit=False):
        v166b_edit_df = st.data_editor(
            v166b_df,
            use_container_width=True,
            hide_index=True,
            height=420,
            key="v166b_pending_close_editor",
            column_config=column_config,
            disabled=[
                "identity_key", "record_key", "id", "工號 / Employee ID", "姓名 / Name",
                "製令 / Work Order", "工段 / Process", "開始時間 / Start", "建議結束時間 / Suggested End", "建議來源 / Suggestion"
            ],
        )
        v166b_editor_commit = st.form_submit_button("💾 暫存勾選與結束時間 / Update Selection", use_container_width=True)
    if v166b_editor_commit and isinstance(v166b_edit_df, pd.DataFrame):
        st.session_state["v166b_pending_close_effective_df"] = v166b_edit_df.copy()
    v166b_effective_df = st.session_state.get("v166b_pending_close_effective_df") if isinstance(st.session_state.get("v166b_pending_close_effective_df"), pd.DataFrame) else v166b_edit_df

    selected_df = v166b_effective_df[v166b_effective_df["結算 / Close"].astype(bool)].copy() if isinstance(v166b_effective_df, pd.DataFrame) and not v166b_effective_df.empty else pd.DataFrame()
    st.caption(f"已勾選 {len(selected_df)} 筆。正式結算前請確認結束時間不可空白，且結束時間必須大於開始時間。")

    v166b_confirm = st.checkbox(
        "我確認要將勾選的 LOG-only 待補紀錄依畫面結束時間進行人工結算",
        disabled=not CAN_REPAIR,
        key="v166b_confirm_pending_close",
    )
    close_disabled = (not CAN_REPAIR) or (not v166b_confirm) or selected_df.empty
    if st.button("✅ 執行 V166B 待補紀錄人工結算", use_container_width=True, disabled=close_disabled, key="v166b_close_pending_button"):
        requests = []
        for _, r in selected_df.iterrows():
            requests.append({
                "identity_key": str(r.get("identity_key", "") or ""),
                "record_key": str(r.get("record_key", "") or ""),
                "id": str(r.get("id", "") or ""),
                "end_timestamp": str(r.get("結束時間 / End Timestamp", "") or ""),
                "close_status": str(r.get("結束狀態 / Close Status", "") or "補登結束"),
                "note": str(r.get("補登備註 / Close Note", "") or ""),
            })
        with st.spinner("正在進行 V166B LOG-only 待補人工結算..."):
            v166b_result = close_log_only_pending_records(
                requests,
                github=bool(github_backup),
                dry_run=bool(dry_run),
            )
        st.session_state["v166b_pending_close_result"] = v166b_result
        if v166b_result.get("ok"):
            st.success(
                "V166B 待補人工結算完成。"
                + ("（Dry Run，未寫入）" if v166b_result.get("dry_run") else "")
                + f" 結算 {v166b_result.get('closed_count', 0)} 筆。"
            )
            if not v166b_result.get("dry_run"):
                st.session_state["v166b_pending_close_snapshot"] = None
        else:
            st.error(f"V166B 待補人工結算失敗：{v166b_result.get('reason', '')}")
        st.json(v166b_result)

    if CAN_EXPORT:
        v166b_export_col.download_button(
            "⬇️ 下載待補結算清單 Excel",
            data=export_pending_close_excel_bytes(v166b_snapshot),
            file_name=f"SPT_V166B_LOG_only_待補結算_{start_date}_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="v166b_download_pending_close_excel",
        )

if not CAN_REPAIR:
    st.info("你的帳號沒有 14 模組 can_manage 權限，因此不能執行 V166B 待補人工結算。")

if st.session_state.get("v166b_pending_close_result"):
    with st.expander("V166B 最近一次待補人工結算結果", expanded=False):
        st.json(st.session_state.get("v166b_pending_close_result"))




st.divider()
if not V166C_LOG_SNAPSHOT_IMPORT_OK:
    st.warning(
        "V166C/V166D LOG 快照服務檔案尚未同步或版本過舊。"
        "本頁其他健康檢查仍可使用；請套用 V166E2 依賴修復包後重新部署 / Reboot App。"
    )

st.markdown("### V166C LOG 完整快照保存與精準還原 / LOG Full Snapshot Recovery")
st.caption(
    "V166C 會在新的 time_records LOG 明細中保存完整 JSON 快照。"
    "若未來 01/02 又發生資料遺失或被覆蓋，可優先從 LOG 快照非破壞式補回，"
    "比 V164B LOG-only 文字待補更接近原始 02 歷史紀錄內容。"
)

if "v166c_log_snapshot_result" not in st.session_state:
    st.session_state["v166c_log_snapshot_result"] = None
if "v166c_log_snapshot_recovery_result" not in st.session_state:
    st.session_state["v166c_log_snapshot_recovery_result"] = None

v166c_c1, v166c_c2, v166c_c3 = st.columns([1, 1, 2])
v166c_limit = v166c_c1.number_input("LOG掃描上限", min_value=500, max_value=50000, value=5000, step=500, key="v166c_log_snapshot_limit")
v166c_c2.metric("目前模式", "Dry Run" if dry_run else "正式寫入")
v166c_c3.info("此功能只處理 V166C 之後產生、且 LOG detail 內含完整快照 JSON 的紀錄；舊 LOG 仍走 V164B / V166B 流程。")

v166c_b1, v166c_b2 = st.columns([1, 1])
if v166c_b1.button("🔎 掃描 V166C LOG 快照", use_container_width=True, key="v166c_scan_log_snapshots"):
    with st.spinner("正在掃描 06 LOG 內的 V166C 完整快照，並比對目前 01/02 是否缺失..."):
        st.session_state["v166c_log_snapshot_result"] = collect_log_snapshot_recovery_candidates(
            start_date=str(start_date),
            end_date=str(end_date),
            limit=int(v166c_limit),
        )
        st.session_state.pop("v166c_log_snapshot_effective_df", None)
    st.rerun()

if st.session_state.get("v166c_log_snapshot_result") is None:
    # V166E: no automatic LOG scan on page load/editor rerun. Press scan button to collect candidates.
    st.session_state["v166c_log_snapshot_result"] = {
        "ok": True, "manual_scan_required": True, "rows": [], "candidate_count": 0,
        "missing_count": 0, "checked_at": "尚未掃描，請按『掃描 V166C LOG 快照』"
    }

v166c_snapshot = st.session_state.get("v166c_log_snapshot_result") or {}
v166c_rows = v166c_snapshot.get("rows", []) if isinstance(v166c_snapshot, dict) else []
v166c_candidate_count = int(v166c_snapshot.get("candidate_count", 0) or 0) if isinstance(v166c_snapshot, dict) else 0
v166c_missing_count = int(v166c_snapshot.get("missing_count", 0) or 0) if isinstance(v166c_snapshot, dict) else 0

v166c_m1, v166c_m2, v166c_m3 = st.columns(3)
v166c_m1.metric("LOG快照候選", v166c_candidate_count)
v166c_m2.metric("目前缺失可補", v166c_missing_count)
v166c_m3.metric("檢查時間", v166c_snapshot.get("checked_at", "") if isinstance(v166c_snapshot, dict) else "")

if not v166c_snapshot.get("ok", True):
    st.error(f"V166C LOG 快照掃描失敗：{v166c_snapshot.get('reason', '')}")
elif v166c_candidate_count <= 0:
    st.info("目前日期範圍內尚未找到 V166C 完整快照 LOG。此功能會從套用 V166C 後的新 LOG 開始累積資料。")
else:
    v166c_df = pd.DataFrame(v166c_rows)
    display_cols = [
        "復原 / Recover", "是否缺失 / Missing", "log_id", "log_time", "action_type", "target_id",
        "identity_key", "record_key", "id", "工號 / Employee ID", "姓名 / Name", "製令 / Work Order",
        "P/N / 料號", "機型 / Model", "工段 / Process", "狀態 / Status", "開始時間 / Start", "結束時間 / End",
        "工時 / Hours", "工時 / HH:MM:SS", "snapshot_hash",
    ]
    for col in display_cols:
        if col not in v166c_df.columns:
            v166c_df[col] = ""
    v166c_df = v166c_df[display_cols]
    try:
        v166c_column_config = {
            "復原 / Recover": st.column_config.CheckboxColumn("復原", help="只會補目前缺失的資料；已存在資料不會覆蓋"),
            "是否缺失 / Missing": st.column_config.CheckboxColumn("缺失", disabled=True),
        }
    except Exception:
        v166c_column_config = {}
    # V166E: keep LOG snapshot recovery editor in a form; edits are committed only by submit.
    stored_v166c_df = st.session_state.get("v166c_log_snapshot_effective_df")
    if isinstance(stored_v166c_df, pd.DataFrame) and "identity_key" in stored_v166c_df.columns:
        try:
            if set(stored_v166c_df["identity_key"].astype(str).tolist()) == set(v166c_df["identity_key"].astype(str).tolist()):
                v166c_df = stored_v166c_df.copy()
        except Exception:
            pass
    with st.form("v166e_v166c_log_snapshot_recovery_form", clear_on_submit=False):
        v166c_edit_df = st.data_editor(
            v166c_df,
            use_container_width=True,
            hide_index=True,
            height=420,
            key="v166c_log_snapshot_recovery_editor",
            column_config=v166c_column_config,
            disabled=[c for c in display_cols if c != "復原 / Recover"],
        )
        v166c_editor_commit = st.form_submit_button("💾 暫存復原勾選 / Update Recovery Selection", use_container_width=True)
    if v166c_editor_commit and isinstance(v166c_edit_df, pd.DataFrame):
        st.session_state["v166c_log_snapshot_effective_df"] = v166c_edit_df.copy()
    v166c_effective_df = st.session_state.get("v166c_log_snapshot_effective_df") if isinstance(st.session_state.get("v166c_log_snapshot_effective_df"), pd.DataFrame) else v166c_edit_df
    v166c_selected = v166c_effective_df[v166c_effective_df["復原 / Recover"].astype(bool)].copy() if isinstance(v166c_effective_df, pd.DataFrame) and not v166c_effective_df.empty else pd.DataFrame()
    st.caption(f"已勾選 {len(v166c_selected)} 筆。V166C 正式復原只會做非破壞式合併，不會刪除、不重新編號、不覆蓋既有資料。")

    v166c_confirm = st.checkbox(
        "我確認要從 V166C LOG 完整快照補回勾選的缺失工時紀錄",
        disabled=not CAN_REPAIR,
        key="v166c_confirm_log_snapshot_recovery",
    )
    v166c_disabled = (not CAN_REPAIR) or (not v166c_confirm) or v166c_selected.empty
    if st.button("✅ 執行 V166C LOG 快照精準還原", use_container_width=True, disabled=v166c_disabled, key="v166c_run_log_snapshot_recovery"):
        selected_keys = [str(x) for x in v166c_selected.get("identity_key", []).tolist() if str(x).strip()]
        with st.spinner("正在從 V166C LOG 完整快照非破壞式補回 01/02..."):
            v166c_result = recover_records_from_log_snapshots(
                selected_identity_keys=selected_keys,
                start_date=str(start_date),
                end_date=str(end_date),
                github=bool(github_backup),
                dry_run=bool(dry_run),
                limit=int(v166c_limit),
            )
        st.session_state["v166c_log_snapshot_recovery_result"] = v166c_result
        if v166c_result.get("ok"):
            st.success(
                "V166C LOG 快照還原完成。"
                + ("（Dry Run，未寫入）" if v166c_result.get("dry_run") else "")
                + f" 補回 {v166c_result.get('recovered_count', 0)} 筆。"
            )
            if not v166c_result.get("dry_run"):
                st.session_state["v166c_log_snapshot_result"] = None
        else:
            st.error(f"V166C LOG 快照還原失敗：{v166c_result.get('reason', '')}")
        st.json(v166c_result)

    if CAN_EXPORT:
        v166c_b2.download_button(
            "⬇️ 下載 V166C LOG 快照候選 Excel",
            data=export_log_snapshot_candidates_excel_bytes(v166c_snapshot),
            file_name=f"SPT_V166C_LOG完整快照候選_{start_date}_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="v166c_download_log_snapshot_candidates",
        )

if not CAN_REPAIR:
    st.info("你的帳號沒有 14 模組 can_manage 權限，因此不能執行 V166C LOG 快照還原。")

if st.session_state.get("v166c_log_snapshot_recovery_result"):
    with st.expander("V166C 最近一次 LOG 快照還原結果", expanded=False):
        st.json(st.session_state.get("v166c_log_snapshot_recovery_result"))


st.divider()
st.markdown("### V166D LOG 快照覆蓋率補強 / Snapshot Coverage Guard")
st.caption(
    "V166D 會在 V152 durable layer 已持有完整工時 rows 時，額外寫入一筆含完整 JSON 快照的 LOG，"
    "提高後續精準還原成功率。此區可檢查 LOG 快照覆蓋率，並可把可回查到完整資料的舊 LOG 補上快照。"
)

if "v166d_log_snapshot_coverage" not in st.session_state:
    st.session_state["v166d_log_snapshot_coverage"] = None
if "v166d_log_snapshot_backfill_result" not in st.session_state:
    st.session_state["v166d_log_snapshot_backfill_result"] = None

v166d_c1, v166d_c2, v166d_c3 = st.columns([1, 1, 2])
v166d_limit = v166d_c1.number_input("V166D LOG覆蓋率掃描上限", min_value=500, max_value=100000, value=10000, step=500, key="v166d_log_snapshot_coverage_limit")
v166d_c2.metric("目前模式", "Dry Run" if dry_run else "正式寫入")
v166d_c3.info("正式補強只會更新 06 LOG detail，加上可還原快照；不會修改 01/02 工時資料。")

v166d_b1, v166d_b2, v166d_b3 = st.columns([1, 1, 1])
if v166d_b1.button("📊 檢查 V166D LOG 快照覆蓋率", use_container_width=True, key="v166d_check_log_snapshot_coverage"):
    with st.spinner("正在檢查 time_records 相關 LOG 的快照覆蓋率..."):
        st.session_state["v166d_log_snapshot_coverage"] = get_log_snapshot_coverage_status(
            start_date=str(start_date),
            end_date=str(end_date),
            limit=int(v166d_limit),
        )
    st.rerun()

if st.session_state.get("v166d_log_snapshot_coverage") is None:
    # V166E: no automatic coverage scan on page load/editor rerun. Press check button to collect coverage.
    st.session_state["v166d_log_snapshot_coverage"] = {
        "ok": True, "manual_scan_required": True, "rows": [],
        "time_related_log_count": 0, "with_snapshot_count": 0, "without_snapshot_count": 0,
        "coverage_percent": 0.0, "checked_at": "尚未檢查，請按『檢查 V166D LOG 快照覆蓋率』"
    }

v166d_cov = st.session_state.get("v166d_log_snapshot_coverage") or {}
v166d_k1, v166d_k2, v166d_k3, v166d_k4 = st.columns(4)
v166d_k1.metric("工時相關LOG", int(v166d_cov.get("time_related_log_count", 0) or 0))
v166d_k2.metric("已有快照", int(v166d_cov.get("with_snapshot_count", 0) or 0))
v166d_k3.metric("尚未覆蓋", int(v166d_cov.get("without_snapshot_count", 0) or 0))
v166d_k4.metric("覆蓋率", f"{float(v166d_cov.get('coverage_percent', 0) or 0):.2f}%")

if not v166d_cov.get("ok", True):
    st.error(f"V166D 覆蓋率檢查失敗：{v166d_cov.get('reason', '')}")
else:
    v166d_rows = v166d_cov.get("rows", []) or []
    if v166d_rows:
        v166d_df = pd.DataFrame(v166d_rows)
        v166d_show_cols = ["log_id", "log_time", "action_type", "target_table", "target_id", "has_snapshot", "detail_size", "source", "message"]
        for col in v166d_show_cols:
            if col not in v166d_df.columns:
                v166d_df[col] = ""
        st.dataframe(v166d_df[v166d_show_cols].head(500), use_container_width=True, hide_index=True, height=260)
    else:
        st.info("目前日期範圍內沒有找到 time_records 相關 LOG。")

v166d_confirm = st.checkbox(
    "我確認只補強 06 LOG detail 快照，不修改 01/02 工時資料",
    disabled=not CAN_REPAIR,
    key="v166d_confirm_backfill_log_snapshot",
)
v166d_disabled = (not CAN_REPAIR) or (not v166d_confirm)
if v166d_b2.button("🧩 補強舊 LOG 快照", use_container_width=True, disabled=v166d_disabled, key="v166d_backfill_missing_log_snapshots"):
    with st.spinner("正在把可回查到完整資料的舊 LOG 補上 V166C/V166D 快照..."):
        v166d_result = backfill_missing_log_snapshots(
            start_date=str(start_date),
            end_date=str(end_date),
            limit=int(v166d_limit),
            dry_run=bool(dry_run),
            github=bool(github_backup),
        )
    st.session_state["v166d_log_snapshot_backfill_result"] = v166d_result
    st.session_state["v166d_log_snapshot_coverage"] = None
    if v166d_result.get("ok"):
        st.success(
            "V166D LOG 快照補強完成。"
            + ("（Dry Run，未寫入）" if v166d_result.get("dry_run") else "")
            + f" 可補強/已補強 {v166d_result.get('updated_count', 0)} 筆。"
        )
    else:
        st.error(f"V166D LOG 快照補強失敗：{v166d_result.get('reason', '')}")
    st.json(v166d_result)

if CAN_EXPORT and v166d_cov.get("ok", True):
    v166d_b3.download_button(
        "⬇️ 下載 V166D 覆蓋率報告",
        data=export_log_snapshot_coverage_excel_bytes(v166d_cov),
        file_name=f"SPT_V166D_LOG快照覆蓋率_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="v166d_download_log_snapshot_coverage",
    )

if not CAN_REPAIR:
    st.info("你的帳號沒有 14 模組 can_manage 權限，因此不能執行 V166D LOG 快照補強。")

if st.session_state.get("v166d_log_snapshot_backfill_result"):
    with st.expander("V166D 最近一次 LOG 快照補強結果", expanded=False):
        st.json(st.session_state.get("v166d_log_snapshot_backfill_result"))


if b3.button("🧹 清除本頁檢查結果", use_container_width=True, key="v153_clear_result"):
    st.session_state["v153_audit_result"] = None
    st.session_state.pop("v153_repair_result", None)
    st.rerun()

st.caption("V159：已加入頁面路由健康檢查，建議清除已存在正常中文對應頁的 #Uxxxx 舊頁面，避免 Streamlit 掃描舊頁與載入舊邏輯。")

# -----------------------------------------------------------------------------
# V182-V188 consolidated audit center (direct overwrite, read-only by default)
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown("### V182-V188 一次彙整檢查中心 / Consolidated Diagnostics")
st.caption(
    "本區把 01/02/SQLite 一致性、舊重複資料、LOGRECOVERY、06 LOG 錯誤分類、備份狀態提示、版本健康檢查集中在同一份報告。"
    "預設只讀，不刪除、不覆蓋、不重新編號。"
)

try:
    from services.data_consistency_audit_service import (
        collect_v182_consolidated_audit,
        export_v182_audit_excel_bytes,
    )
    _v182_import_error = ""
except Exception as _v182_exc:  # deployment guard
    collect_v182_consolidated_audit = None
    export_v182_audit_excel_bytes = None
    _v182_import_error = str(_v182_exc)

if _v182_import_error:
    st.error("V182 一次彙整檢查服務尚未正確載入：" + _v182_import_error)
else:
    v182_c1, v182_c2, v182_c3 = st.columns([1, 1, 2])
    v182_limit = v182_c1.number_input("最多列出異常筆數", min_value=100, max_value=10000, value=1000, step=100, key="v182_limit_rows")
    v182_run = v182_c2.button("🔍 執行 V182-V188 一次彙整檢查", use_container_width=True, key="v182_run_consolidated_audit")
    v182_c3.info("勾選、切換或輸入不會自動運算；只有按下執行才會讀取資料並產生報告。")

    if v182_run:
        with st.spinner("正在執行 01/02/SQLite/tombstone/LOGRECOVERY/LOG 錯誤/版本健康彙整檢查..."):
            st.session_state["v182_consolidated_audit_report"] = collect_v182_consolidated_audit(limit_rows=int(v182_limit))

    v182_report = st.session_state.get("v182_consolidated_audit_report")
    if v182_report:
        s1, s2, s3, s4 = st.columns(4)
        severity_rows = v182_report.get("severity_summary", []) or []
        sev_map = {str(x.get("severity")): int(x.get("count", 0) or 0) for x in severity_rows if isinstance(x, dict)}
        s1.metric("CRITICAL", sev_map.get("CRITICAL", 0))
        s2.metric("HIGH", sev_map.get("HIGH", 0))
        s3.metric("檢查秒數", v182_report.get("elapsed_seconds", 0))
        s4.metric("寫入正式資料", "否" if not v182_report.get("production_write_path_changed") else "是")

        if v182_report.get("recommendations"):
            st.warning("\n".join([f"- {x}" for x in v182_report.get("recommendations", [])]))

        tabs = st.tabs([
            "來源數量",
            "異常摘要",
            "異常明細",
            "重複資料",
            "LOG錯誤分類",
            "版本健康",
            "備份狀態提示",
        ])
        with tabs[0]:
            st.dataframe(pd.DataFrame(v182_report.get("source_counts", [])), use_container_width=True, hide_index=True)
        with tabs[1]:
            c1, c2 = st.columns(2)
            c1.dataframe(pd.DataFrame(v182_report.get("severity_summary", [])), use_container_width=True, hide_index=True)
            c2.dataframe(pd.DataFrame(v182_report.get("issue_summary", [])), use_container_width=True, hide_index=True)
        with tabs[2]:
            st.dataframe(pd.DataFrame(v182_report.get("issue_rows", [])), use_container_width=True, hide_index=True)
        with tabs[3]:
            st.dataframe(pd.DataFrame(v182_report.get("duplicate_rows", [])), use_container_width=True, hide_index=True)
        with tabs[4]:
            c1, c2 = st.columns([1, 2])
            c1.dataframe(pd.DataFrame(v182_report.get("log_error_summary", [])), use_container_width=True, hide_index=True)
            c2.dataframe(pd.DataFrame(v182_report.get("log_error_rows", [])), use_container_width=True, hide_index=True)
        with tabs[5]:
            st.dataframe(pd.DataFrame(v182_report.get("version_rows", [])), use_container_width=True, hide_index=True)
        with tabs[6]:
            st.dataframe(pd.DataFrame(v182_report.get("backup_rows", [])), use_container_width=True, hide_index=True)

        if CAN_EXPORT and export_v182_audit_excel_bytes is not None:
            st.download_button(
                "⬇️ 下載 V182-V188 一次彙整檢查 Excel",
                data=export_v182_audit_excel_bytes(v182_report),
                file_name=f"SPT_V182_一次彙整檢查_{v182_report.get('generated_at','').replace(':','').replace(' ','_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="v182_download_excel",
            )
        elif not CAN_EXPORT:
            st.info("你的帳號沒有 14 模組匯出權限，因此不能下載 V182 Excel。")
    else:
        st.info("尚未執行 V182-V188 一次彙整檢查。")

# -----------------------------------------------------------------------------
# V189-V190 backend pagination and database migration assessment
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown("### V189-V190 大表後端分頁與正式資料庫轉換評估 / Backend Pagination & DB Migration Assessment")
st.caption(
    "本區只做讀取檢查與評估，不切換資料庫、不改 01/02 交易流程、不改畫面樣式。"
    "V189 提供 SQL LIMIT/OFFSET 後端分頁檢查；V190 評估 PostgreSQL / SQL Server 轉換準備度。"
)

try:
    from services.large_table_backend_pagination_service import (
        collect_v189_large_table_report,
        export_v189_report_excel_bytes,
    )
    _v189_import_error = ""
except Exception as _v189_exc:
    collect_v189_large_table_report = None
    export_v189_report_excel_bytes = None
    _v189_import_error = str(_v189_exc)

try:
    from services.database_migration_assessment_service import (
        collect_v190_database_migration_assessment,
        export_v190_assessment_excel_bytes,
    )
    _v190_import_error = ""
except Exception as _v190_exc:
    collect_v190_database_migration_assessment = None
    export_v190_assessment_excel_bytes = None
    _v190_import_error = str(_v190_exc)

v189190_c1, v189190_c2, v189190_c3 = st.columns([1, 1, 2])
v189_page_size = v189190_c1.number_input("V189 後端分頁測試筆數", min_value=100, max_value=5000, value=500, step=100, key="v189_page_size")
v189_run = v189190_c2.button("⚡ 執行 V189 大表後端分頁檢查", use_container_width=True, key="v189_run_backend_pagination")
v190_run = v189190_c3.button("🧭 執行 V190 PostgreSQL / SQL Server 轉換評估", use_container_width=True, key="v190_run_migration_assessment")

if _v189_import_error:
    st.error("V189 後端分頁服務尚未正確載入：" + _v189_import_error)
elif v189_run and callable(collect_v189_large_table_report):
    with st.spinner("正在執行 V189 大表後端分頁檢查..."):
        st.session_state["v189_large_table_report"] = collect_v189_large_table_report(page_size=int(v189_page_size))

if _v190_import_error:
    st.error("V190 資料庫轉換評估服務尚未正確載入：" + _v190_import_error)
elif v190_run and callable(collect_v190_database_migration_assessment):
    with st.spinner("正在執行 V190 PostgreSQL / SQL Server 轉換評估..."):
        st.session_state["v190_database_migration_assessment"] = collect_v190_database_migration_assessment()

v189_report = st.session_state.get("v189_large_table_report")
if v189_report:
    st.markdown("#### V189 大表後端分頁檢查結果")
    v189_k1, v189_k2, v189_k3, v189_k4 = st.columns(4)
    v189_k1.metric("正式寫入路徑改變", "否" if not v189_report.get("production_write_path_changed") else "是")
    v189_k2.metric("畫面樣式改變", "否" if not v189_report.get("visual_changed") else "是")
    v189_k3.metric("測試頁筆數", int(v189_report.get("page_size", 0) or 0))
    v189_k4.metric("檢查秒數", v189_report.get("elapsed_seconds", 0))
    tabs_v189 = st.tabs(["資料表", "查詢煙霧測試", "建議"])
    with tabs_v189[0]:
        st.dataframe(pd.DataFrame(v189_report.get("table_checks", [])), use_container_width=True, hide_index=True)
    with tabs_v189[1]:
        st.dataframe(pd.DataFrame(v189_report.get("smoke_results", [])), use_container_width=True, hide_index=True)
    with tabs_v189[2]:
        for rec in v189_report.get("recommendations", []) or []:
            st.write(f"- {rec}")
    if CAN_EXPORT and callable(export_v189_report_excel_bytes):
        st.download_button(
            "⬇️ 下載 V189 大表後端分頁檢查 Excel",
            data=export_v189_report_excel_bytes(v189_report),
            file_name=f"SPT_V189_大表後端分頁檢查_{str(v189_report.get('generated_at','')).replace(':','').replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="v189_download_report",
        )
else:
    st.info("尚未執行 V189 大表後端分頁檢查。")

v190_report = st.session_state.get("v190_database_migration_assessment")
if v190_report:
    st.markdown("#### V190 PostgreSQL / SQL Server 轉換前評估")
    summary = v190_report.get("summary", {}) or {}
    v190_k1, v190_k2, v190_k3, v190_k4 = st.columns(4)
    v190_k1.metric("SQLite資料表", int(summary.get("sqlite_table_count", 0) or 0))
    v190_k2.metric("SQLite總列數", f"{int(summary.get('sqlite_total_rows', 0) or 0):,}")
    v190_k3.metric("外部DB已啟用", "否" if not v190_report.get("external_database_enabled") else "是")
    v190_k4.metric("現在可直接切正式DB", "否" if not v190_report.get("safe_to_switch_live_database_now") else "是")
    if not v190_report.get("safe_to_switch_live_database_now"):
        st.warning("V190 評估結論：目前不建議直接切 PostgreSQL / SQL Server。建議先做 dual-write shadow mode，穩定比對後再切換。")
    tabs_v190 = st.tabs(["Schema", "JSON權威檔", "轉換步驟", "DB選型", "風險"])
    with tabs_v190[0]:
        st.dataframe(pd.DataFrame(v190_report.get("schema_rows", [])), use_container_width=True, hide_index=True)
    with tabs_v190[1]:
        st.dataframe(pd.DataFrame(v190_report.get("json_authority_rows", [])), use_container_width=True, hide_index=True)
    with tabs_v190[2]:
        st.dataframe(pd.DataFrame(v190_report.get("migration_steps", [])), use_container_width=True, hide_index=True)
    with tabs_v190[3]:
        st.dataframe(pd.DataFrame(v190_report.get("backend_recommendations", [])), use_container_width=True, hide_index=True)
    with tabs_v190[4]:
        st.dataframe(pd.DataFrame(v190_report.get("risk_rows", [])), use_container_width=True, hide_index=True)
    if CAN_EXPORT and callable(export_v190_assessment_excel_bytes):
        st.download_button(
            "⬇️ 下載 V190 資料庫轉換評估 Excel",
            data=export_v190_assessment_excel_bytes(v190_report),
            file_name=f"SPT_V190_DB轉換評估_{str(v190_report.get('generated_at','')).replace(':','').replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="v190_download_report",
        )
else:
    st.info("尚未執行 V190 PostgreSQL / SQL Server 轉換前評估。")
