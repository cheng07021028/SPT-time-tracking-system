# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.table_ui_service import render_table
from services.system_settings_service import (
    delete_process_options,
    delete_rest_periods,
    load_process_options_df,
    load_rest_periods_df,
    save_process_options_df,
    save_rest_periods_df,
    get_live_page_reset_time,
    save_live_page_reset_time,
)
from services.persistence_guard_service import (
    create_persistent_backup,
    check_persistent_health,
    restore_latest_persistent_backup,
    ensure_initialized_marker,
    is_initialized,
    list_persistent_backups,
)
from services.auto_backup_service import (
    create_external_full_backup,
    get_schedule_status,
    load_backup_schedule,
    run_due_backup_if_needed,
    save_backup_schedule,
    start_auto_backup_scheduler_once,
    validate_target_folder,
)

from services.db_service import flush_pending_permanent_state

st.set_page_config(page_title="13. 系統設定", page_icon="⌬️", layout="wide")
apply_theme()
require_module_access("13_system_settings", "can_view")
render_header("13｜系統設定", "工段名稱下拉選單、休息時間扣除規則｜新增、刪除、修改、套用後永久保存")

can_manage = check_permission("13_system_settings", "can_manage") or check_permission("13_system_settings", "can_edit")
if not can_manage:
    st.warning("你目前只有查看權限，設定修改需由管理員或具備 13 系統設定 can_manage / can_edit 權限的人員操作。")

st.info(
    "設定套用後會立即寫入資料庫，並建立永久設定檔。"
    "01｜工時紀錄的工段下拉選單會讀取這裡的啟用工段；"
    "工時計算會依這裡啟用的休息時間扣除。"
)

_pending_message = st.session_state.pop("_spt_13_pending_apply_message", "")
if _pending_message:
    st.success(_pending_message)



def _excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, data in sheets.items():
            (data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)).to_excel(writer, index=False, sheet_name=str(name)[:31] or "Sheet1")
    return bio.getvalue()

def _bool_from_any(v, default=True):
    text = str(v).strip().lower() if v is not None else ""
    if text in {"0", "false", "no", "n", "停用", "否", "inactive"}:
        return False
    if text in {"1", "true", "yes", "y", "啟用", "是", "active"}:
        return True
    return default

def _normalize_delete_column(df: pd.DataFrame, delete_col: str = "刪除") -> pd.DataFrame:
    out = df.copy()
    if delete_col not in out.columns:
        out.insert(0, delete_col, False)
    else:
        out[delete_col] = out[delete_col].fillna(False).astype(bool)
    return out


def _export_permanent_settings(message: str) -> None:
    """Create local permanent JSON immediately, but do not push GitHub here.

    GitHub push is intentionally kept on 09｜資料永久保存與備份 to avoid the
    10~20 second delay after every settings change.  The local permanent JSON is
    enough to survive normal project reload/update flows when committed or backed up.
    """
    try:
        res = flush_pending_permanent_state(upload_github=False)
        if res.get("ok"):
            st.success(message + "，已建立永久設定檔。")
        else:
            st.warning(message + "，但永久設定檔建立結果需到 09｜資料永久保存與備份確認。")
    except Exception as exc:
        st.warning(f"{message}，但永久設定檔建立失敗：{exc}")


def _set_edit_mode(key: str, enabled: bool) -> None:
    st.session_state[key] = bool(enabled)
    st.rerun()


def _clear_editor_state(*keys: str) -> None:
    """Clear data_editor/form states so the next paint reloads data from DB."""
    prefixes = tuple(str(k) for k in keys if k)
    for k in list(st.session_state.keys()):
        sk = str(k)
        if sk in prefixes or any(sk.startswith(p) for p in prefixes):
            st.session_state.pop(k, None)


def _refresh_after_apply(message: str, *edit_mode_keys: str) -> None:
    """After confirm/apply, leave edit mode and force a clean screen reload."""
    for k in edit_mode_keys:
        if k:
            st.session_state[k] = False
    _clear_editor_state(
        "system_process_options_editor_v192",
        "system_process_apply_action_v192",
        "system_rest_periods_editor_v192",
        "system_rest_apply_action_v192",
    )
    st.session_state["_spt_13_pending_apply_message"] = message
    st.rerun()





def _short_path(path) -> str:
    try:
        p = str(path).replace("\\", "/")
        marker = "/data/_persistent_backup/"
        if marker in p:
            return "data/_persistent_backup/" + p.split(marker, 1)[1]
        return p
    except Exception:
        return str(path)




def _format_bytes_v296(n) -> str:
    try:
        n = float(n or 0)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024 or unit == "TB":
                return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n):,} {unit}"
            n /= 1024
    except Exception:
        return "0 B"


def _render_external_auto_backup_center() -> None:
    """Daily scheduled external full backup settings in 13｜系統設定.

    Browser-based Streamlit cannot open a native folder picker.  The professional
    and stable approach is to enter/paste an absolute folder path and validate it.
    """
    st.subheader("每日自動備份設定 / Daily External Backup Schedule")
    st.caption(
        "設定每日固定時間，自動把所有專案設定檔與正式資料備份到指定資料夾。"
        "備份包含 data 內正式資料、權限、歷史、工時紀錄、表格紀錄、系統設定；.streamlit 設定會鏡像到 data/config/_project_config_mirror 後一起備份；"
        "會排除內部備份資料夾，避免遞迴備份越來越大。"
    )

    try:
        start_auto_backup_scheduler_once()
        cfg = load_backup_schedule()
        status = get_schedule_status()
    except Exception as exc:
        st.error(f"自動備份服務載入失敗：{exc}")
        st.divider()
        return

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("排程狀態", "啟用" if cfg.get("enabled") else "停用")
    s2.metric("每日時間", str(cfg.get("daily_time") or "未設定"))
    s3.metric("目標資料夾", "可寫入" if status.get("target_ok") else "未通過")
    s4.metric("下次執行", str(status.get("next_run") or "-"))

    state = status.get("state", {}) or {}
    if state.get("last_backup_at"):
        st.info(
            f"最近備份：{state.get('last_backup_at')}｜"
            f"檔案數：{state.get('last_file_count', 0)}｜"
            f"大小：{_format_bytes_v296(state.get('last_total_bytes'))}｜"
            f"路徑：{state.get('last_backup_dir', '')}"
        )
    if state.get("last_scheduler_error"):
        st.warning(f"最近排程錯誤：{state.get('last_scheduler_error')}")

    if not can_manage:
        st.info("你目前只有查看權限。自動備份設定與還原需 can_manage / can_edit 權限。")
        st.divider()
        return

    with st.expander("設定每日自動備份 / Configure Daily Backup", expanded=True):
        enabled = st.checkbox("啟用每日自動備份", value=bool(cfg.get("enabled")), key="spt_v296_ext_backup_enabled")
        col_a, col_b = st.columns([1, 2])
        with col_a:
            daily_time = st.time_input(
                "每日備份時間",
                value=pd.to_datetime(str(cfg.get("daily_time") or "17:30")).time(),
                key="spt_v296_ext_backup_daily_time",
            )
            keep_days = st.number_input(
                "保留天數",
                min_value=1,
                max_value=3650,
                value=int(cfg.get("keep_days") or 30),
                step=1,
                key="spt_v296_ext_backup_keep_days",
            )
        with col_b:
            target_folder = st.text_input(
                "備份目標資料夾完整路徑",
                value=str(cfg.get("target_folder") or ""),
                placeholder="例如：D:\\SPT_Backup\\TimeTracking 或 E:\\Backup\\SPT",
                key="spt_v296_ext_backup_target_folder",
            )
            st.caption("Streamlit 網頁無法開啟 Windows 原生資料夾挑選器；請複製/貼上完整資料夾路徑，系統會檢查是否可寫入。")

        validation = validate_target_folder(target_folder, create=False)
        if target_folder:
            if validation.get("ok"):
                st.success(f"目標資料夾可寫入：{validation.get('path')}")
            else:
                st.warning(validation.get("message", "目標資料夾尚未通過檢查。"))

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("▣ 儲存自動備份設定", key="spt_v296_save_ext_backup_schedule", use_container_width=True):
                try:
                    saved = save_backup_schedule({
                        "enabled": bool(enabled),
                        "daily_time": daily_time.strftime("%H:%M"),
                        "target_folder": str(target_folder or "").strip(),
                        "keep_days": int(keep_days),
                        "include_project_configs": True,
                        "include_streamlit_config": True,
                    })
                    start_auto_backup_scheduler_once()
                    st.success(f"已儲存自動備份設定：每日 {saved.get('daily_time')}。")
                except Exception as exc:
                    st.error(f"儲存自動備份設定失敗：{exc}")
        with b2:
            if st.button("◇ 建立/測試目標資料夾", key="spt_v296_test_ext_backup_folder", use_container_width=True):
                res = validate_target_folder(target_folder, create=True)
                if res.get("ok"):
                    st.success(f"目標資料夾建立/測試成功：{res.get('path')}")
                else:
                    st.error(res.get("message", res))
        with b3:
            if st.button("▣ 立即完整備份到指定資料夾", key="spt_v296_run_ext_backup_now", use_container_width=True):
                try:
                    # Save current setting first so scheduler and manual backup are consistent.
                    save_backup_schedule({
                        "enabled": bool(enabled),
                        "daily_time": daily_time.strftime("%H:%M"),
                        "target_folder": str(target_folder or "").strip(),
                        "keep_days": int(keep_days),
                    })
                    result = create_external_full_backup(target_folder, reason="ui_manual_external_full_backup_from_13", create_target=True)
                    if result.get("ok"):
                        st.success(
                            f"完整備份完成：{result.get('backup_dir')}｜"
                            f"檔案數：{result.get('file_count')}｜"
                            f"大小：{_format_bytes_v296(result.get('total_bytes'))}"
                        )
                    else:
                        st.error(f"備份失敗：{result.get('message', result.get('errors', result))}")
                except Exception as exc:
                    st.error(f"備份失敗：{exc}")

    with st.expander("備份內容說明 / Backup Coverage", expanded=False):
        st.markdown(
            """
            **會備份：**
            - `data/persistent_modules/`：各模組表格紀錄、歷史紀錄、工時紀錄、製令、人員等 JSON 資料
            - `data/persistent_state/`：永久狀態、欄位設定、權限狀態、保護狀態
            - `data/database/`：SQLite 資料庫，包含權限、工時、歷史、系統設定等資料表
            - `data/config/` 與 `data` 內其他正式設定檔
            - `data/config/_project_config_mirror/`：`.streamlit/config.toml`、`.streamlit/secrets.toml` 與部署設定鏡像檔
            - `requirements.txt`、`README.md` 等部署參考設定

            **會排除：**
            - `data/_persistent_backup/`
            - `data/_persistent_corrupt/`
            - `data/_persistent_restore_replaced/`
            - `__pycache__/`

            目標資料夾建議放在專案外，例如 `D:\\SPT_Backup\\TimeTracking`，避免被 GitHub 或專案更新流程誤處理。
            """
        )

    if st.button("◇ 檢查今日排程是否到期並補跑", key="spt_v296_run_due_backup_check", use_container_width=True):
        try:
            result = run_due_backup_if_needed(force=False)
            if result.get("skipped"):
                st.info(f"目前不用補跑：{result.get('reason')}")
            elif result.get("ok"):
                st.success(f"排程備份已完成：{result.get('backup_dir')}")
            else:
                st.error(f"排程備份失敗：{result}")
        except Exception as exc:
            st.error(f"排程檢查失敗：{exc}")

    st.divider()

def _render_persistence_guard_center() -> None:
    """Render data/settings protection tools inside 13｜系統設定.

    This replaces .bat execution. It only uses Streamlit buttons and Python service calls.
    It must not restore deleted panels such as Operation Results or Dropdown Size Settings.
    """
    st.subheader("資料與設定保護中心 / Persistence Guard")
    st.caption(
        "不用執行 .bat。這裡可直接建立正式使用標記、手動備份、健康檢查與最近備份還原。"
        "此功能只保護資料與設定，不修改工時計算、權限邏輯或畫面樣式。"
    )

    try:
        initialized = bool(is_initialized())
        backups = list_persistent_backups()
    except Exception as exc:
        st.error(f"資料保護服務載入失敗：{exc}")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("正式使用標記", "已建立" if initialized else "未建立")
    k2.metric("備份數量", len(backups))
    k3.metric("最近備份", backups[0].name if backups else "無")
    k4.metric("執行方式", "系統設定內按鈕")

    if backups:
        with st.expander("最近備份清單 / Latest Backups", expanded=False):
            backup_rows = []
            for p in backups[:10]:
                try:
                    backup_rows.append({
                        "備份資料夾": p.name,
                        "路徑": _short_path(p),
                        "修改時間": pd.to_datetime(p.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception:
                    backup_rows.append({"備份資料夾": str(p), "路徑": _short_path(p), "修改時間": ""})
            st.dataframe(pd.DataFrame(backup_rows), use_container_width=True, hide_index=True)

    if not can_manage:
        st.info("你目前只有查看權限。備份、初始化與還原需 can_manage / can_edit 權限。")
        try:
            health = check_persistent_health(write_manifest=False)
            with st.expander("查看目前資料健康摘要 / Health Summary", expanded=False):
                st.json({
                    "initialized": health.get("initialized"),
                    "db_exists": health.get("db_exists"),
                    "warnings": health.get("warnings", []),
                    "errors": health.get("errors", []),
                    "db_counts": health.get("db_counts", {}),
                })
        except Exception as exc:
            st.warning(f"健康檢查讀取失敗：{exc}")
        st.divider()
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("▣ 啟用資料保護並建立備份", key="spt_persistence_guard_install_ui_v295", use_container_width=True):
            try:
                ensure_initialized_marker()
                result = create_persistent_backup(reason="ui_install_from_13_system_settings", include_database=True)
                if result.get("ok"):
                    st.success(f"資料保護已啟用，已建立備份：{result.get('backup_dir')}｜檔案數：{result.get('file_count')}")
                else:
                    st.error(f"資料保護啟用失敗：{result}")
            except Exception as exc:
                st.error(f"資料保護啟用失敗：{exc}")

    with c2:
        if st.button("▣ 立即備份資料與設定", key="spt_persistence_guard_backup_ui_v295", use_container_width=True):
            try:
                result = create_persistent_backup(reason="ui_manual_backup_from_13_system_settings", include_database=True)
                if result.get("ok"):
                    st.success(f"已完成備份：{result.get('backup_dir')}｜檔案數：{result.get('file_count')}")
                else:
                    st.error(f"備份失敗：{result}")
            except Exception as exc:
                st.error(f"備份失敗：{exc}")

    with c3:
        if st.button("◇ 執行資料健康檢查", key="spt_persistence_guard_health_ui_v295", use_container_width=True):
            try:
                st.session_state["_spt_13_persistence_health_v295"] = check_persistent_health(write_manifest=True)
            except Exception as exc:
                st.session_state["_spt_13_persistence_health_v295"] = {"errors": [str(exc)], "warnings": []}

    health = st.session_state.get("_spt_13_persistence_health_v295")
    if health:
        errors = health.get("errors", []) or []
        warnings = health.get("warnings", []) or []
        if errors:
            st.error("資料健康檢查發現錯誤，請先不要覆蓋或重啟大量資料。")
        elif warnings:
            st.warning("資料健康檢查有警告，建議先備份後再更新模組。")
        else:
            st.success("資料健康檢查通過，目前未發現資料遺失或回預設風險。")
        with st.expander("健康檢查明細 / Health Check Detail", expanded=False):
            st.json({
                "initialized": health.get("initialized"),
                "db_exists": health.get("db_exists"),
                "db_path": health.get("db_path"),
                "db_counts": health.get("db_counts", {}),
                "warnings": warnings,
                "errors": errors,
                "json_status": health.get("json_status", []),
            })

    with st.expander("危險操作：還原最近備份 / Restore Latest Backup", expanded=False):
        st.warning("還原會把 data/persistent_modules、data/persistent_state、data/database 回復到最近備份。請先確認目前資料已備份。")
        confirm_restore = st.checkbox("我確認要還原最近備份", key="spt_persistence_guard_restore_confirm_v295")
        include_secrets = st.checkbox("同時還原 .streamlit 設定檔 / secrets（一般不建議）", value=False, key="spt_persistence_guard_restore_secrets_v295")
        if st.button("↺ 還原最近備份", key="spt_persistence_guard_restore_ui_v295", use_container_width=True, disabled=not confirm_restore):
            try:
                result = restore_latest_persistent_backup(include_secrets=include_secrets)
                if result.get("ok"):
                    st.success(f"已還原最近備份：{result.get('source')}｜還原項目：{', '.join(result.get('restored', []))}")
                    st.info("建議現在 Reboot App，讓系統重新讀取還原後的資料。")
                else:
                    st.error(f"還原失敗：{result.get('message', result)}")
            except Exception as exc:
                st.error(f"還原失敗：{exc}")

    st.divider()

_render_persistence_guard_center()

# -----------------------------------------------------------------------------
# 0) Excel import/export for all system settings
# -----------------------------------------------------------------------------
st.subheader("零、系統設定 Excel 上傳 / 下載 / System Settings Excel")
current_process_export = load_process_options_df(active_only=False)
current_rest_export = load_rest_periods_df(active_only=False)
app_settings_export = pd.DataFrame([{"setting_key": "live_page_reset_time", "setting_value": get_live_page_reset_time(), "note": "01 工時紀錄每日重新整理時間 HH:MM"}])
st.download_button(
    "⟰ 下載全部系統設定 Excel / Export All System Settings",
    data=_excel_bytes({"process_options": current_process_export, "rest_periods": current_rest_export, "app_settings": app_settings_export}),
    file_name="SPT_系統設定.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
if can_manage:
    setting_file = st.file_uploader("上傳系統設定 Excel / Upload System Settings", type=["xlsx", "xlsm", "xls"], key="system_settings_excel_upload_v243")
    if setting_file is not None:
        try:
            sheets = pd.read_excel(setting_file, sheet_name=None)
            st.success("已讀取系統設定 Excel，請確認後按下方按鈕套用。")
            for nm, dfp in sheets.items():
                with st.expander(f"預覽：{nm}", expanded=False):
                    st.dataframe(dfp, use_container_width=True, height=220)
            if st.button("▣ 確認匯入並永久套用系統設定 / Import Settings", type="primary", use_container_width=True, key="import_system_settings_excel_v243"):
                p_count = r_count = 0
                if "process_options" in sheets:
                    pdf = sheets["process_options"].copy()
                    p_count = save_process_options_df(pdf)
                if "rest_periods" in sheets:
                    rdf = sheets["rest_periods"].copy()
                    r_count = save_rest_periods_df(rdf)
                if "app_settings" in sheets:
                    adf = sheets["app_settings"]
                    for _, row in adf.iterrows():
                        if str(row.get("setting_key", "")).strip() == "live_page_reset_time":
                            save_live_page_reset_time(str(row.get("setting_value", "02:00")).strip())
                _export_permanent_settings(f"已匯入系統設定：工段 {p_count} 筆、休息時間 {r_count} 筆")
                _refresh_after_apply("已匯入並永久套用系統設定，畫面已重新整理。")
        except Exception as exc:
            st.error(f"系統設定 Excel 讀取失敗：{exc}")
st.divider()
# -----------------------------------------------------------------------------
# 1) Process options
# -----------------------------------------------------------------------------
st.subheader("一、工段名稱設定 / Process Options")
st.caption("這裡會套用到 01｜工時紀錄的『工段名稱』下拉選單。只有『啟用』的工段會出現在下拉選單。")
proc_df = load_process_options_df(active_only=False)
if proc_df.empty:
    proc_df = pd.DataFrame(columns=["id", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
proc_view = _normalize_delete_column(proc_df)

proc_edit_key = "_spt_13_process_edit_mode"
if can_manage:
    c1, c2, c3 = st.columns([1, 1, 4])
    if not st.session_state.get(proc_edit_key, False):
        if c1.button("◇ 啟動編輯工段", key="enable_process_edit", use_container_width=True):
            _set_edit_mode(proc_edit_key, True)
    else:
        if c1.button("◌ 停止編輯工段", key="disable_process_edit", use_container_width=True):
            _set_edit_mode(proc_edit_key, False)
    c2.caption("新增：啟動編輯後，在表格最下方新增列。刪除：勾選『刪除』後確認執行。")

if can_manage and st.session_state.get(proc_edit_key, False):
    st.info("目前為工段編輯模式：可新增、修改、勾選刪除。完成後請選擇動作並按『確認套用』，才會永久保存與套用到 01 工時紀錄。")
    with st.form("system_process_options_apply_form", clear_on_submit=False):
        edited_proc = render_table(
            proc_view,
            "system_process_options",
            editable=True,
            disabled=["id", "created_at", "updated_at"],
            key="system_process_options_editor_v192",
            height=430,
            num_rows="dynamic",
        )
        action = st.radio(
            "確認後執行動作",
            ["套用並永久儲存工段名稱設定", "刪除勾選工段"],
            horizontal=True,
            key="system_process_apply_action_v192",
        )
        submitted = st.form_submit_button("▣ 確認套用 / Apply", type="primary", use_container_width=True)

    if submitted and edited_proc is not None:
        if action == "套用並永久儲存工段名稱設定":
            save_df = edited_proc.drop(columns=["刪除"], errors="ignore")
            count = save_process_options_df(save_df)
            _export_permanent_settings(f"已套用工段名稱設定 {count} 筆")
            _refresh_after_apply(f"已套用工段名稱設定 {count} 筆，畫面已重新整理。", proc_edit_key)
        else:
            try:
                ids = [int(float(x)) for x in edited_proc[edited_proc["刪除"].astype(bool)]["id"].dropna().tolist()]
            except Exception:
                ids = []
            if not ids:
                st.warning("請先勾選要刪除的既有工段，再按確認套用。新增尚未儲存的空白列不需要刪除，直接清空即可。")
            else:
                count = delete_process_options(ids)
                _export_permanent_settings(f"已刪除工段名稱設定 {count} 筆")
                _refresh_after_apply(f"已刪除工段名稱設定 {count} 筆，畫面已重新整理。", proc_edit_key)
else:
    render_table(proc_view.drop(columns=["刪除"], errors="ignore"), "system_process_options", editable=False, height=420)

st.divider()

# -----------------------------------------------------------------------------
# 2) Rest periods
# -----------------------------------------------------------------------------
st.subheader("二、休息時間設定 / Rest Periods")
st.caption("這裡會套用到工時計算。格式請使用 HH:MM，例如 10:30、12:00。只有『啟用』的休息時間會被扣除。")
rest_df = load_rest_periods_df(active_only=False)
if rest_df.empty:
    rest_df = pd.DataFrame(columns=["id", "name", "start_time", "end_time", "is_active", "sort_order"])
rest_view = _normalize_delete_column(rest_df)

rest_edit_key = "_spt_13_rest_edit_mode"
if can_manage:
    c1, c2, c3 = st.columns([1, 1, 4])
    if not st.session_state.get(rest_edit_key, False):
        if c1.button("◇ 啟動編輯休息時間", key="enable_rest_edit", use_container_width=True):
            _set_edit_mode(rest_edit_key, True)
    else:
        if c1.button("◌ 停止編輯休息時間", key="disable_rest_edit", use_container_width=True):
            _set_edit_mode(rest_edit_key, False)
    c2.caption("新增：啟動編輯後，在表格最下方新增列。刪除：勾選『刪除』後確認執行。")

if can_manage and st.session_state.get(rest_edit_key, False):
    st.info("目前為休息時間編輯模式：可新增、修改、勾選刪除。完成後請按『確認套用』，才會永久保存並套用到工時計算。")
    with st.form("system_rest_periods_apply_form", clear_on_submit=False):
        edited_rest = render_table(
            rest_view,
            "system_rest_periods",
            editable=True,
            disabled=["id"],
            key="system_rest_periods_editor_v192",
            height=360,
            num_rows="dynamic",
        )
        action = st.radio(
            "確認後執行動作",
            ["套用並永久儲存休息時間設定", "刪除勾選休息時間"],
            horizontal=True,
            key="system_rest_apply_action_v192",
        )
        submitted = st.form_submit_button("▣ 確認套用 / Apply", type="primary", use_container_width=True)

    if submitted and edited_rest is not None:
        if action == "套用並永久儲存休息時間設定":
            save_df = edited_rest.drop(columns=["刪除"], errors="ignore")
            count = save_rest_periods_df(save_df)
            _export_permanent_settings(f"已套用休息時間設定 {count} 筆")
            _refresh_after_apply(f"已套用休息時間設定 {count} 筆，畫面已重新整理。", rest_edit_key)
        else:
            try:
                ids = [int(float(x)) for x in edited_rest[edited_rest["刪除"].astype(bool)]["id"].dropna().tolist()]
            except Exception:
                ids = []
            if not ids:
                st.warning("請先勾選要刪除的既有休息時間，再按確認套用。新增尚未儲存的空白列不需要刪除，直接清空即可。")
            else:
                count = delete_rest_periods(ids)
                _export_permanent_settings(f"已刪除休息時間設定 {count} 筆")
                _refresh_after_apply(f"已刪除休息時間設定 {count} 筆，畫面已重新整理。", rest_edit_key)
else:
    render_table(rest_view.drop(columns=["刪除"], errors="ignore"), "system_rest_periods", editable=False, height=360)

st.divider()
st.success("設定套用後的串接：01｜工時紀錄工段下拉選單立即讀取啟用工段；工時計算與 02｜歷史紀錄重新計算會使用啟用中的休息時間。")
