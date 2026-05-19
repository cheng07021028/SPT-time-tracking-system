# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
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
    export_system_settings_permanent,
)

from services.github_retention_service import load_cleanup_settings, run_due_github_cleanup_if_needed, save_cleanup_settings, REMOTE_ALLOWED_ROOTS

from services.auto_backup_service import (
    create_backup_by_mode,
    get_available_backup_modes,
    get_runtime_environment,
    get_schedule_status,
    load_backup_schedule,
    normalize_backup_mode,
    run_due_backup_if_needed,
    save_backup_schedule,
    start_auto_backup_scheduler_once,
    validate_backup_destination,
)

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




# -----------------------------------------------------------------------------
# V3.23: System settings permanent-file health center
# -----------------------------------------------------------------------------
def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _file_health_row(path: Path, label: str) -> dict:
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    mtime = ""
    ok = False
    detail = "檔案不存在"
    if exists:
        try:
            mtime = pd.to_datetime(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            mtime = ""
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            ok = isinstance(payload, (dict, list))
            if isinstance(payload, dict):
                keys = list(payload.keys())[:8]
                detail = "JSON 可讀；keys=" + ", ".join(map(str, keys))
            elif isinstance(payload, list):
                detail = f"JSON 可讀；list rows={len(payload)}"
            else:
                detail = "JSON 可讀"
        except Exception as exc:
            ok = False
            detail = f"JSON 讀取失敗：{exc}"
    return {
        "項目 / Item": label,
        "狀態 / Status": "✅ 正常" if ok else "⚠️ 異常",
        "路徑 / Path": str(path.relative_to(_project_root())) if str(path).startswith(str(_project_root())) else str(path),
        "存在 / Exists": exists,
        "大小 / Size": size,
        "最後修改 / Modified": mtime,
        "說明 / Detail": detail,
    }


def _render_system_settings_health_center() -> None:
    root = _project_root()
    health_targets = [
        (root / "data" / "config" / "system_settings.json", "系統設定主檔 / system_settings.json"),
        (root / "data" / "persistent_state" / "spt_system_settings.json", "系統設定狀態檔 / spt_system_settings.json"),
        (root / "data" / "persistent_modules" / "13_system_settings" / "system_settings.json", "13 模組永久檔 / 13_system_settings"),
        (root / "data" / "config" / "auto_external_backup_schedule.json", "每日自動備份設定 / backup schedule"),
        (root / "data" / "persistent_state" / "auto_external_backup_state.json", "每日自動備份狀態 / backup state"),
    ]
    rows = [_file_health_row(path, label) for path, label in health_targets]
    ok_count = sum(1 for r in rows if str(r.get("狀態 / Status", "")).startswith("✅"))

    with st.expander("系統設定永久保存健康檢查 / System Settings Persistence Health", expanded=True):
        st.caption(
            "此區檢查 13｜系統設定與每日自動備份設定是否真的寫入 data/ 永久檔。"
            "設定後應保持不變，直到下次再套用設定。"
        )
        h1, h2, h3 = st.columns(3)
        h1.metric("永久檔正常 / Healthy Files", f"{ok_count}/{len(rows)}")
        h2.metric("目前工時頁重置時間", get_live_page_reset_time())
        h3.metric("備份設定檔", "已檢查")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=230)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("◇ 重新檢查永久設定檔 / Recheck", use_container_width=True, key="v323_recheck_system_settings_health"):
                st.rerun()
        with c2:
            if can_manage and st.button("▣ 立即刷新永久設定檔 / Refresh Permanent Settings", use_container_width=True, key="v323_refresh_system_settings_files"):
                try:
                    result = export_system_settings_permanent(reason="manual_refresh_from_health_center", write_history=True)
                    if result.get("ok"):
                        st.success("已重新寫入系統設定永久檔。")
                    else:
                        st.warning(f"永久檔刷新結果：{result}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"刷新永久設定檔失敗：{exc}")
        if ok_count < 3:
            st.warning("部分 13 系統設定永久檔不存在或不可讀。請按『立即刷新永久設定檔』建立/修復。")
        else:
            st.success("13 系統設定永久檔已存在且可讀。")

def _export_permanent_settings(message: str) -> None:
    """Create the dedicated 13｜系統設定 permanent JSON only.

    不再呼叫全系統 flush_pending_permanent_state，避免在一般設定套用後
    被其他模組的 pending/export 流程干擾，導致設定看起來回到原始值。
    """
    try:
        res = export_system_settings_permanent("13_system_settings_page_apply", write_history=True)
        if res.get("ok"):
            st.success(message + "，已寫入 13 系統設定永久檔。")
        else:
            st.warning(message + "，但 13 系統設定永久檔寫入結果需確認。")
    except Exception as exc:
        st.warning(f"{message}，但 13 系統設定永久檔建立失敗：{exc}")


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
    """Daily backup settings with three professional modes.

    V3.05 rules:
    - Local Windows backup: only when Streamlit is truly running on Windows.
    - Cloud project backup: usable on Streamlit Cloud/Linux, writes under data/_external_backup.
    - GitHub cloud backup: uses existing GitHub cloud persistence service.
    """
    st.subheader("每日自動備份設定 / Daily Backup Schedule")
    st.caption(
        "備份模式分為三種，避免 Windows 本機路徑與 Streamlit Cloud/Linux 雲端環境混淆。"
        "系統會依目前執行環境自動停用不適用的模式。"
    )

    try:
        start_auto_backup_scheduler_once()
        cfg = load_backup_schedule()
        status = get_schedule_status()
    except Exception as exc:
        st.error(f"自動備份服務載入失敗：{exc}")
        st.divider()
        return

    env_info = get_runtime_environment()
    runtime_label = status.get("runtime_label") or ("Windows 本機" if env_info.get("is_windows") else ("Streamlit Cloud / Linux 雲端" if env_info.get("is_streamlit_cloud_like") else str(env_info.get("system") or "Unknown")))
    current_mode = normalize_backup_mode(cfg.get("backup_mode"))

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("排程狀態", "啟用" if cfg.get("enabled") else "停用")
    s2.metric("每日時間", str(cfg.get("daily_time") or "未設定"))
    s3.metric("備份模式", {"local_windows": "本機 Windows", "cloud_project": "雲端專案內", "github_cloud": "GitHub 雲端"}.get(current_mode, current_mode))
    s4.metric("執行環境", runtime_label)
    st.caption(f"下次執行：{status.get('next_run') or '-'}｜專案根目錄：{env_info.get('project_root')}")

    state = status.get("state", {}) or {}
    if state.get("last_backup_at"):
        st.info(
            f"最近備份：{state.get('last_backup_at')}｜"
            f"模式：{state.get('last_backup_mode') or status.get('backup_mode') or '-'}｜"
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
        enabled = st.checkbox("啟用每日自動備份", value=bool(cfg.get("enabled")), key="spt_v305_backup_enabled")
        modes = get_available_backup_modes()
        mode_labels = {m["mode"]: m["label"] for m in modes}
        mode_desc = {m["mode"]: m["description"] for m in modes}
        available = {m["mode"]: bool(m.get("available")) for m in modes}
        mode_options = [m["mode"] for m in modes]
        if current_mode not in mode_options:
            current_mode = mode_options[0]
        selected_mode = st.radio(
            "備份模式 / Backup Mode",
            options=mode_options,
            index=mode_options.index(current_mode),
            format_func=lambda x: mode_labels.get(x, x),
            horizontal=True,
            key="spt_v305_backup_mode",
        )
        st.caption(mode_desc.get(selected_mode, ""))

        if not available.get(selected_mode, True):
            st.warning("目前執行環境不支援這個備份模式。系統已停用相關路徑操作，請改用雲端專案內備份或 GitHub 雲端備份。")

        col_a, col_b = st.columns([1, 2])
        with col_a:
            daily_time = st.time_input(
                "每日備份時間",
                value=pd.to_datetime(str(cfg.get("daily_time") or "17:30")).time(),
                key="spt_v305_backup_daily_time",
            )
            keep_days = st.number_input(
                "保留天數",
                min_value=1,
                max_value=3650,
                value=int(cfg.get("keep_days") or 30),
                step=1,
                key="spt_v305_backup_keep_days",
            )
        with col_b:
            if selected_mode == "local_windows":
                target_folder = st.text_input(
                    "本機 Windows 備份資料夾完整路徑",
                    value=str(cfg.get("target_folder") or ""),
                    placeholder="例如：D:/SPT_Backup/TimeTracking 或 E:\\Backup\\SPT",
                    key="spt_v305_backup_target_folder",
                    disabled=not available.get(selected_mode, True),
                )
                st.caption("只有公司電腦本機執行 streamlit run 時，才能寫入 D:/、E:/ 或 OneDrive 本機資料夾。")
            elif selected_mode == "cloud_project":
                target_folder = "data/_external_backup"
                st.text_input("雲端專案內備份位置", value=target_folder, disabled=True, key="spt_v305_cloud_project_path")
                st.caption("適合 Streamlit Cloud/Linux。備份會放在專案 data/_external_backup；建議再搭配 GitHub 或下載保存。")
            else:
                target_folder = ""
                st.text_input("GitHub 備份目標", value="GitHub Contents API：data/persistent_state / data/persistent_modules", disabled=True, key="spt_v305_github_target")
                st.caption("需在 Secrets 設定 GITHUB_TOKEN、GITHUB_REPOSITORY、GITHUB_BRANCH。")

        validation = validate_backup_destination(selected_mode, target_folder, create=False)
        if validation.get("ok"):
            st.success(validation.get("message", "備份目的地可用。"))
        else:
            st.warning(validation.get("message", "備份目的地尚未通過檢查。"))
        if validation.get("runtime_label"):
            st.caption(f"目前執行環境：{validation.get('runtime_label')}｜備份模式：{mode_labels.get(selected_mode, selected_mode)}")

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("▣ 儲存自動備份設定", key="spt_v305_save_backup_schedule", use_container_width=True):
                try:
                    saved = save_backup_schedule({
                        "enabled": bool(enabled),
                        "daily_time": daily_time.strftime("%H:%M"),
                        "backup_mode": selected_mode,
                        "target_folder": str(target_folder or "").strip(),
                        "keep_days": int(keep_days),
                        "include_project_configs": True,
                        "include_streamlit_config": True,
                    })
                    start_auto_backup_scheduler_once()
                    st.success(f"已儲存自動備份設定：{mode_labels.get(saved.get('backup_mode'), saved.get('backup_mode'))}｜每日 {saved.get('daily_time')}。")
                except Exception as exc:
                    st.error(f"儲存自動備份設定失敗：{exc}")
        with b2:
            if st.button("◇ 建立/測試備份目的地", key="spt_v305_test_backup_destination", use_container_width=True):
                res = validate_backup_destination(selected_mode, target_folder, create=True)
                if res.get("ok"):
                    st.success(res.get("message", f"備份目的地測試成功：{res.get('path', '')}"))
                else:
                    st.error(res.get("message", res))
        with b3:
            if st.button("▣ 立即依目前模式完整備份", key="spt_v305_run_backup_now", use_container_width=True):
                try:
                    save_backup_schedule({
                        "enabled": bool(enabled),
                        "daily_time": daily_time.strftime("%H:%M"),
                        "backup_mode": selected_mode,
                        "target_folder": str(target_folder or "").strip(),
                        "keep_days": int(keep_days),
                    })
                    result = create_backup_by_mode(selected_mode, target_folder, reason="ui_manual_backup_from_13_v305", create_target=True)
                    if result.get("ok"):
                        st.success(
                            f"備份完成：{result.get('backup_dir', result.get('mode', ''))}｜"
                            f"檔案數：{result.get('file_count', 0)}｜"
                            f"大小：{_format_bytes_v296(result.get('total_bytes'))}"
                        )
                    else:
                        st.error(f"備份失敗：{result.get('message', result.get('errors', result))}")
                except Exception as exc:
                    st.error(f"備份失敗：{exc}")

    with st.expander("三種備份模式說明 / Backup Mode Guide", expanded=False):
        st.markdown(
            """
            **本機 Windows 備份**  
            適合公司電腦本機執行 `streamlit run streamlit_app.py`，可寫入 `D:/`、`E:/`、OneDrive 本機資料夾。  

            **雲端專案內備份**  
            適合 Streamlit Cloud / Linux。備份到 `data/_external_backup`，不會要求 Windows 路徑。  

            **GitHub 雲端備份**  
            使用既有 GitHub Contents API，把永久 JSON 與資料狀態上傳到 GitHub。需設定 `GITHUB_TOKEN`。  
            """
        )

    if st.button("◇ 檢查今日排程是否到期並補跑", key="spt_v305_run_due_backup_check", use_container_width=True):
        try:
            result = run_due_backup_if_needed(force=False)
            if result.get("skipped"):
                st.info(f"目前不用補跑：{result.get('reason')}")
            elif result.get("ok"):
                st.success(f"排程備份已完成：{result.get('backup_dir', result.get('mode', ''))}")
            else:
                st.error(f"排程備份失敗：{result}")
        except Exception as exc:
            st.error(f"排程檢查失敗：{exc}")

    st.divider()



def _render_github_cleanup_schedule_center() -> None:
    """V3.26: GitHub retention schedule settings in 13｜系統設定."""
    with st.expander("GitHub 定期清理設定 / GitHub Cleanup Schedule", expanded=False):
        st.caption("此功能只清理 GitHub 上有時間戳的備份/history 檔；預設不刪 latest 主檔，不影響目前顯示與功能。")
        try:
            cfg = load_cleanup_settings()
        except Exception as exc:
            st.error(f"讀取 GitHub 清理設定失敗：{exc}")
            return
        roots = cfg.get("roots", ["data/persistent_state/history", "data/persistent_state/audit_history", "data/persistent_modules"])
        gc1, gc2, gc3, gc4 = st.columns(4)
        enabled = gc1.checkbox("啟用定期清理", value=bool(cfg.get("enabled", False)), key="v326_13_cleanup_enabled", disabled=not can_manage)
        freq_options = ["daily", "weekly", "monthly"]
        current_freq = str(cfg.get("frequency", "weekly"))
        freq_idx = freq_options.index(current_freq) if current_freq in freq_options else 1
        frequency = gc2.selectbox("清理週期", freq_options, index=freq_idx, key="v326_13_cleanup_frequency", disabled=not can_manage)
        keep_days = gc3.number_input("保留天數", min_value=7, max_value=3650, value=int(cfg.get("keep_days", 90)), key="v326_13_cleanup_keep_days", disabled=not can_manage)
        gc4.metric("上次執行", cfg.get("last_run_at") or "尚未執行")
        selected_roots = st.multiselect("GitHub 清理範圍", REMOTE_ALLOWED_ROOTS, default=[r for r in roots if r in REMOTE_ALLOWED_ROOTS], key="v326_13_cleanup_roots", disabled=not can_manage)
        delete_undated = st.checkbox("允許刪除無日期檔案（不建議）", value=bool(cfg.get("delete_undated_files", False)), key="v326_13_cleanup_undated", disabled=not can_manage)
        c1, c2 = st.columns(2)
        if can_manage and c1.button("儲存 GitHub 定期清理設定", use_container_width=True, key="v326_13_save_cleanup"):
            res = save_cleanup_settings({**cfg, "enabled": bool(enabled), "frequency": frequency, "keep_days": int(keep_days), "roots": selected_roots, "delete_undated_files": bool(delete_undated)})
            st.success("GitHub 定期清理設定已保存。")
            st.json(res)
        if can_manage and c2.button("檢查並執行到期清理", use_container_width=True, key="v326_13_run_due_cleanup"):
            res = run_due_github_cleanup_if_needed()
            if res.get("skipped"):
                st.info(res.get("message", "尚未到期。"))
            else:
                st.warning(f"GitHub 清理完成：刪除 {res.get('deleted_count', 0)} 個檔案。")
                st.json(res)


# V3.23：先顯示系統設定永久保存健康檢查，再顯示自動備份設定。
_render_system_settings_health_center()

# V3.20：每日自動備份設定必須保留在 13｜系統設定，不可被系統設定修正覆蓋移除。
_render_external_auto_backup_center()

# V3.26：GitHub 定期清理設定，避免 history/backup 檔案無限制累積。
_render_github_cleanup_schedule_center()

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
