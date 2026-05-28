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

from services.page_hygiene_service import (
    collect_page_hygiene_status,
    cleanup_duplicate_mojibake_pages,
    page_hygiene_rows,
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

if b3.button("🧹 清除本頁檢查結果", use_container_width=True, key="v153_clear_result"):
    st.session_state["v153_audit_result"] = None
    st.session_state.pop("v153_repair_result", None)
    st.rerun()

st.caption("V159：已加入頁面路由健康檢查，建議清除已存在正常中文對應頁的 #Uxxxx 舊頁面，避免 Streamlit 掃描舊頁與載入舊邏輯。")
