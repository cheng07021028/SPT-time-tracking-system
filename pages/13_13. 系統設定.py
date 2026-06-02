# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO
from datetime import datetime
import json
from pathlib import Path
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.ui_size_service import apply_dropdown_menu_size_only
from services.security_service import require_module_access, check_permission
from services.table_ui_service import render_table
from services.system_settings_service import (
    delete_process_categories,
    delete_process_options,
    delete_rest_periods,
    load_process_categories_df,
    load_process_options_df,
    load_process_category_choices,
    save_process_categories_df,
    save_default_process_category,
    get_default_process_category,
    load_rest_periods_df,
    save_process_options_df,
    save_rest_periods_df,
    get_live_page_reset_time,
    save_live_page_reset_time,
    export_system_settings_permanent,
)

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

from services.settings_durability_service import (
    get_critical_settings_health,
    upload_critical_settings_to_github,
    download_critical_settings_from_github,
)

st.set_page_config(page_title="13. 系統設定", page_icon="⌬️", layout="wide")
apply_theme()
apply_dropdown_menu_size_only(560)
require_module_access("13_system_settings", "can_view")
render_header("13｜系統設定", "工段名稱下拉選單、休息時間扣除規則｜新增、刪除、修改、套用後永久保存")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("13", "系統設定")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


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

SYSTEM_DELETE_COL = "刪除 / Delete"

def _normalize_delete_column(df: pd.DataFrame, delete_col: str = SYSTEM_DELETE_COL) -> pd.DataFrame:
    out = df.copy()
    out = out.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore") if delete_col != "刪除" else out
    if delete_col not in out.columns:
        out.insert(0, delete_col, False)
    else:
        out[delete_col] = out[delete_col].fillna(False).astype(bool)
    return out


def _delete_mask(df: pd.DataFrame) -> pd.Series:
    col = SYSTEM_DELETE_COL if SYSTEM_DELETE_COL in df.columns else ("刪除" if "刪除" in df.columns else "")
    if not col:
        return pd.Series(False, index=df.index)
    return df[col].fillna(False).astype(bool)



# ===================== V144 Category Process Editor Category-Switch Guard =====================
# 目的：13｜系統設定「類別對應工段設定」切換顯示類別時，data_editor 不得沿用上一個類別的舊草稿。
# 病根：Streamlit data_editor 以固定 key 保存前一次表格狀態；選擇 GPTC 後，若 key 未變，
#      可能仍顯示/送出 BWBS 的編輯草稿，造成「上方是 GPTC，下方明細是 BWBS」。

def _v144_safe_key_part(value) -> str:
    text = str(value or "").strip()
    out = []
    for ch in text:
        if ch.isalnum() or ch in {"_", "-"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "all"


def _v144_clear_process_option_editor_state(reason: str = "category_changed") -> None:
    """Clear all process-option editor drafts when the selected category changes.

    V49: Streamlit keeps st.data_editor state by widget key.  The 13. 系統設定
    process editor must never reuse an old category draft after switching category
    or toggling edit mode.  Clear every process-option editor/draft key and bump
    a nonce so the next editor is created with a brand-new key.
    """
    targets = [
        "system_process_options_editor",
        "system_process_options_draft",
        "system_process_options_form",
        "submit_save_processes",
        "submit_delete_processes",
        "system_process_options",
        "_spt_v144_last_process_category",
    ]
    for k in list(st.session_state.keys()):
        sk = str(k)
        if any(t in sk for t in targets):
            st.session_state.pop(k, None)
    try:
        st.session_state["_spt_v49_process_editor_nonce"] = int(st.session_state.get("_spt_v49_process_editor_nonce", 0)) + 1
        st.session_state["_spt_v49_process_editor_reset_reason"] = str(reason or "category_changed")
    except Exception:
        pass
    try:
        from services.column_settings_service import clear_editor_draft
        clear_editor_draft("system_process_options")
        clear_editor_draft("system_process_options_editor_v192")
        clear_editor_draft("system_process_options_editor_v144")
        clear_editor_draft("system_process_options_editor_v41")
    except Exception:
        pass


def _v144_normalize_category_text(value) -> str:
    text = str(value or "").strip()
    return text or "全部 / 通用"


def _v144_process_rows_match_selected_category(df: pd.DataFrame, selected_category: str) -> tuple[bool, list[str]]:
    """Return whether an edited process table belongs to the selected category.

    Empty new rows are ignored.  Any non-empty category that differs from the
    selected filter is treated as stale editor state and blocked from saving.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return True, []
    selected = _v144_normalize_category_text(selected_category)
    mismatches: list[str] = []
    category_cols = [c for c in ["category_name", "category", "類別", "類別 / Category", "type_name", "機型"] if c in df.columns]
    if not category_cols:
        return True, []
    for _, row in df.iterrows():
        # 完全空白新增列不檢查。
        try:
            has_business_value = any(
                str(row.get(c, "")).strip()
                for c in ["process_name", "工段名稱", "工段名稱 / Process", "note", "備註", "備註 / Note"]
                if c in df.columns
            )
        except Exception:
            has_business_value = True
        if not has_business_value:
            continue
        for c in category_cols:
            val = str(row.get(c, "") or "").strip()
            if val and val != selected:
                mismatches.append(val)
    return len(mismatches) == 0, sorted(set(mismatches))


def _v144_prepare_process_save_df_for_category(df: pd.DataFrame, selected_category: str) -> pd.DataFrame:
    """Force all saved process rows to the selected category after validation."""
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    selected = _v144_normalize_category_text(selected_category)
    if "category_name" not in out.columns:
        out.insert(1 if len(out.columns) else 0, "category_name", selected)
    out["category_name"] = selected
    # 移除舊別名欄，避免 save_process_options_df 誤讀到其他類別別名。
    for c in ["category", "類別", "類別 / Category", "type_name", "機型"]:
        if c in out.columns and c != "category_name":
            out = out.drop(columns=[c], errors="ignore")
    return out


def _v49_force_process_table_category(df: pd.DataFrame, selected_category: str) -> pd.DataFrame:
    """Return a display/editor dataframe whose category column strictly matches the loaded category.

    This is a defensive UI guard.  Even if a stale data_editor payload or an
    older service fallback tries to provide another category, the table shown in
    13. 系統設定 must match the loaded category before it is rendered.
    """
    selected = _v144_normalize_category_text(selected_category)
    base_cols = ["id", "category_name", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"]
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame([{
            "id": "",
            "category_name": selected,
            "process_name": "",
            "is_active": True,
            "sort_order": 1,
            "note": "",
            "created_at": "",
            "updated_at": "",
        }])
    out = df.copy()
    # Normalize category aliases first, then drop stale alias columns.
    if "category_name" not in out.columns:
        out.insert(1 if len(out.columns) else 0, "category_name", selected)
    out["category_name"] = out["category_name"].map(_v144_normalize_category_text)
    out = out[out["category_name"].eq(selected)].copy()
    for c in ["category", "類別", "類別 / Category", "type_name", "機型"]:
        if c in out.columns and c != "category_name":
            out = out.drop(columns=[c], errors="ignore")
    if out.empty:
        out = pd.DataFrame([{
            "id": "",
            "category_name": selected,
            "process_name": "",
            "is_active": True,
            "sort_order": 1,
            "note": "",
            "created_at": "",
            "updated_at": "",
        }])
    else:
        out["category_name"] = selected
    for c in base_cols:
        if c not in out.columns:
            out[c] = "" if c not in {"is_active", "sort_order"} else (True if c == "is_active" else None)
    return out

# =================== END V144 Category Process Editor Category-Switch Guard ===================



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
    """V25: keep the health center but make page open fast.

    The old version rendered several dataframes and scanned many files on every page open.
    That made 13｜系統設定 feel slow even when the user only wanted to edit categories/processes.
    This version shows a lightweight summary first; full diagnostics run only when requested.
    """
    root = _project_root()
    health_targets = [
        (root / "data" / "permanent_store" / "config" / "system_settings.json", "系統設定主檔 / system_settings.json"),
        (root / "data" / "permanent_store" / "persistent_state" / "spt_system_settings.json", "系統設定狀態檔 / spt_system_settings.json"),
        (root / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "system_settings.json", "13 模組永久檔 / 13_system_settings"),
        (root / "data" / "permanent_store" / "config" / "auto_external_backup_schedule.json", "每日自動備份設定 / backup schedule"),
        (root / "data" / "permanent_store" / "persistent_state" / "auto_external_backup_state.json", "每日自動備份狀態 / backup state"),
    ]
    quick_rows = []
    for path, label in health_targets:
        try:
            quick_rows.append({"項目 / Item": label, "存在 / Exists": path.exists(), "最後修改 / Modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if path.exists() else ""})
        except Exception:
            quick_rows.append({"項目 / Item": label, "存在 / Exists": False, "最後修改 / Modified": ""})
    ok_count = sum(1 for r in quick_rows if r.get("存在 / Exists"))

    with st.expander("系統設定永久保存健康檢查 / System Settings Persistence Health", expanded=False):
        h1, h2, h3 = st.columns(3)
        h1.metric("永久檔存在 / Existing Files", f"{ok_count}/{len(quick_rows)}")
        h2.metric("目前工時頁重置時間", get_live_page_reset_time())
        h3.metric("完整檢查", "按需執行")
        st.dataframe(pd.DataFrame(quick_rows), use_container_width=True, hide_index=True, height=180)

        run_full = st.checkbox("顯示完整永久檔 / GitHub 診斷 / Show full diagnostics", value=False, key="v25_show_full_system_health")
        if run_full:
            rows = [_file_health_row(path, label) for path, label in health_targets]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=230)
            st.markdown("#### 重要設定檔 GitHub 永久化狀態 / Critical Settings GitHub Durability")
            critical_rows = get_critical_settings_health()
            st.dataframe(pd.DataFrame(critical_rows), use_container_width=True, hide_index=True, height=260)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.button("◇ 重新檢查永久設定檔 / Recheck", use_container_width=True, key="v25_recheck_system_settings_health")
        with c2:
            if can_manage and st.button("▣ 立即刷新永久設定檔 / Refresh Permanent Settings", use_container_width=True, key="v25_refresh_system_settings_files"):
                try:
                    result = export_system_settings_permanent(reason="manual_refresh_from_health_center", write_history=True)
                    st.success("已重新寫入系統設定永久檔。" if result.get("ok") else f"永久檔刷新結果：{result}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"刷新永久設定檔失敗：{exc}")
        with c3:
            if can_manage and st.button("⇧ 同步設定到 GitHub / Sync Settings to GitHub", use_container_width=True, key="v25_sync_settings_to_github"):
                result = upload_critical_settings_to_github(archive=True, source="13_system_settings_health_button")
                if result.get("ok"):
                    st.success(f"設定檔已同步到 GitHub：{result.get('upload_count', 0)} 個檔案。")
                elif result.get("skipped"):
                    st.warning(result.get("message", "GitHub 未設定，已略過。"))
                else:
                    st.error(f"GitHub 同步失敗：{result.get('message', result.get('failures', ''))}")
        with c4:
            if can_manage and st.button("⇩ 從 GitHub 載入缺少設定 / Load Missing from GitHub", use_container_width=True, key="v25_load_missing_settings_from_github"):
                result = download_critical_settings_from_github(only_missing=True, source="13_system_settings_health_button")
                if result.get("ok"):
                    st.success("已從 GitHub 載入缺少的設定檔。")
                    st.rerun()
                elif result.get("skipped"):
                    st.warning(result.get("message", "GitHub 未設定，已略過。"))
                else:
                    st.error(f"GitHub 載入失敗：{result.get('failures', result.get('message', ''))}")

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
        if sk in prefixes or any(sk.startswith(p) for p in prefixes) or any(p in sk for p in prefixes):
            st.session_state.pop(k, None)
    # V63：同步清除全域 column_settings_service 的編輯草稿。
    # 否則 13 系統設定按套用/刪除後，DB 已更新但 data_editor 還可能顯示舊草稿。
    try:
        from services.column_settings_service import clear_editor_draft
        for p in prefixes:
            clear_editor_draft(p)
        clear_editor_draft("system_process_categories")
        clear_editor_draft("system_process_options")
        clear_editor_draft("system_rest_periods")
    except Exception:
        pass


def _refresh_after_apply(message: str, *edit_mode_keys: str) -> None:
    """After confirm/apply, leave edit mode and force a clean screen reload."""
    for k in edit_mode_keys:
        if k:
            st.session_state[k] = False
    _clear_editor_state(
        "system_process_options_editor_v192",
        "system_process_options_editor_v144",
        "system_process_options_draft_v58",
        "system_process_options_draft_v144",
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

    # V97：13 系統設定開頁必須秒級。自動備份排程/狀態檢查改為使用者展開後再載入，
    # 避免每次進入 13 頁面都觸發檔案掃描、排程檢查或雲端同步。
    try:
        cfg = load_backup_schedule()
    except Exception as exc:
        st.error(f"自動備份設定讀取失敗：{exc}")
        st.divider()
        return

    if not st.session_state.get("spt_v97_backup_center_loaded", False):
        env_info = get_runtime_environment()
        current_mode = normalize_backup_mode(cfg.get("backup_mode"))
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("排程狀態", "啟用" if cfg.get("enabled") else "停用")
        s2.metric("每日時間", str(cfg.get("daily_time") or "未設定"))
        s3.metric("備份模式", {"local_windows": "本機 Windows", "cloud_project": "雲端專案內", "github_cloud": "GitHub 雲端"}.get(current_mode, current_mode))
        s4.metric("執行環境", "Windows 本機" if env_info.get("is_windows") else ("Streamlit Cloud / Linux 雲端" if env_info.get("is_streamlit_cloud_like") else str(env_info.get("system") or "Unknown")))
        st.caption("V97 快速載入模式：自動備份詳細狀態、目的地檢查與補跑備份不會在開頁時自動執行。")
        if st.button("載入自動備份詳細設定 / Load Backup Settings", key="spt_v97_load_backup_center", use_container_width=True):
            st.session_state["spt_v97_backup_center_loaded"] = True
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()
        st.divider()
        return

    try:
        start_auto_backup_scheduler_once()
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
                st.text_input("GitHub 備份目標", value="GitHub Contents API：data/permanent_store/persistent_state / data/permanent_store/persistent_modules", disabled=True, key="spt_v305_github_target")
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



# ===================== V41 13 Lazy Load Fast Entry =====================
# 原則：進入 13 頁面只顯示控制台與摘要；選擇區塊並按「載入」後才讀取該區資料。
# 下拉、勾選、輸入、表格編輯都只暫存；只有按套用/儲存/刪除/查詢才寫入 Neon 或做重查。

def _v41_finish_page() -> None:
    try:
        _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
    except Exception:
        pass


def _v41_finish_and_stop() -> None:
    _v41_finish_page()
    st.stop()


_V41_SECTION_OPTIONS = [
    "總覽 / Quick Overview",
    "類別與工段設定 / Category & Process",
    "休息時間設定 / Rest Periods",
    "Excel 匯入匯出 / Excel Import Export",
    "每日自動備份設定 / Daily Backup",
    "永久保存健康檢查 / Persistence Health",
]

st.subheader("系統設定控制台 / System Settings Console")
st.caption("V41 快速進頁：進入此模組不再一次載入所有工段、休息時間、備份、Excel 與診斷資料。請選擇區塊後按『載入設定區塊』，才讀取該區資料。")

_current_section = st.session_state.get("spt_13_active_section_v41", _V41_SECTION_OPTIONS[0])
if _current_section not in _V41_SECTION_OPTIONS:
    _current_section = _V41_SECTION_OPTIONS[0]

with st.form("spt_13_section_selector_form_v41", clear_on_submit=False):
    _pending_section = st.selectbox(
        "選擇要設定的區塊 / Choose settings area",
        _V41_SECTION_OPTIONS,
        index=_V41_SECTION_OPTIONS.index(_current_section),
        key="spt_13_pending_section_v41",
        help="選擇下拉選單只暫存；按『載入設定區塊』後才載入該區資料。",
    )
    _load_section = st.form_submit_button("▣ 載入設定區塊 / Load Settings Area", use_container_width=True)
if _load_section:
    st.session_state["spt_13_active_section_v41"] = _pending_section
    # 切換區塊時清掉重表格草稿，避免舊 editor 狀態污染新區塊。
    _clear_editor_state(
        "system_process_categories",
        "system_process_options",
        "system_rest_periods",
        "spt_v97_backup_center_loaded",
    )
    st.rerun()

section = st.session_state.get("spt_13_active_section_v41", _V41_SECTION_OPTIONS[0])
st.info(f"目前載入區塊：{section}。未按套用/儲存/查詢前，不會正式寫入 Neon 或執行大量運算。")

if section == "總覽 / Quick Overview":
    st.markdown("### 快速總覽 / Quick Overview")
    s1, s2, s3, s4 = st.columns(4)
    try:
        s1.metric("預設類別", get_default_process_category())
    except Exception:
        s1.metric("預設類別", "讀取失敗")
    try:
        s2.metric("01 每日重整時間", get_live_page_reset_time())
    except Exception:
        s2.metric("01 每日重整時間", "讀取失敗")
    s3.metric("資料權威", "Neon / PostgreSQL")
    s4.metric("載入模式", "按需載入")
    st.success("13 系統設定已切換為 V41 按需載入模式。選擇上方區塊並按『載入設定區塊』後才會載入詳細資料。")
    st.warning("大量操作如 Excel 匯出、備份檢查、永久檔診斷不會在進頁時自動執行，避免右上角長時間運轉。")
    _v41_finish_and_stop()

if section == "永久保存健康檢查 / Persistence Health":
    _render_system_settings_health_center()
    _v41_finish_and_stop()

if section == "每日自動備份設定 / Daily Backup":
    _render_external_auto_backup_center()
    _v41_finish_and_stop()

if section == "Excel 匯入匯出 / Excel Import Export":
    st.subheader("零、系統設定 Excel 上傳 / 下載 / System Settings Excel")
    st.caption("V41：Excel 匯出與匯入只在按下按鈕後執行，不在進入 13 頁面時讀取全部資料。")
    exp1, exp2 = st.columns(2)
    with exp1:
        if st.button("⟰ 產生並下載全部系統設定 Excel / Prepare Export", use_container_width=True, key="v41_prepare_system_settings_excel"):
            current_process_export = load_process_options_df(active_only=False)
            current_rest_export = load_rest_periods_df(active_only=False)
            app_settings_export = pd.DataFrame([{"setting_key": "live_page_reset_time", "setting_value": get_live_page_reset_time(), "note": "01 工時紀錄每日重新整理時間 HH:MM"}])
            st.session_state["v41_system_settings_excel_bytes"] = _excel_bytes({"process_options": current_process_export, "rest_periods": current_rest_export, "app_settings": app_settings_export})
            st.session_state["v41_system_settings_excel_ready"] = True
    if st.session_state.get("v41_system_settings_excel_ready"):
        st.download_button(
            "⬇️ 下載全部系統設定 Excel / Download All System Settings",
            data=st.session_state.get("v41_system_settings_excel_bytes", b""),
            file_name="SPT_系統設定.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    if can_manage:
        with st.expander("上傳系統設定 Excel / Upload System Settings", expanded=False):
            setting_file = st.file_uploader("上傳系統設定 Excel / Upload System Settings", type=["xlsx", "xlsm", "xls"], key="system_settings_excel_upload_v41")
            if setting_file is not None:
                try:
                    sheets = pd.read_excel(setting_file, sheet_name=None)
                    st.success("已讀取系統設定 Excel，請確認後按下方按鈕套用。")
                    for nm, dfp in sheets.items():
                        with st.expander(f"預覽：{nm}", expanded=False):
                            st.dataframe(dfp, use_container_width=True, height=220)
                    if st.button("▣ 確認匯入並永久套用系統設定 / Import Settings", type="primary", use_container_width=True, key="import_system_settings_excel_v41"):
                        p_count = r_count = 0
                        if "process_options" in sheets:
                            p_count = save_process_options_df(sheets["process_options"].copy())
                        if "rest_periods" in sheets:
                            r_count = save_rest_periods_df(sheets["rest_periods"].copy())
                        if "app_settings" in sheets:
                            adf = sheets["app_settings"]
                            for _, row in adf.iterrows():
                                if str(row.get("setting_key", "")).strip() == "live_page_reset_time":
                                    save_live_page_reset_time(str(row.get("setting_value", "02:00")).strip())
                        _export_permanent_settings(f"已匯入系統設定：工段 {p_count} 筆、休息時間 {r_count} 筆")
                        _refresh_after_apply("已匯入並永久套用系統設定，畫面已重新整理。")
                except Exception as exc:
                    st.error(f"系統設定 Excel 讀取失敗：{exc}")
    _v41_finish_and_stop()

if section == "類別與工段設定 / Category & Process":
    st.subheader("一、類別與工段名稱設定 / Category & Process Options")
    st.caption("類別與工段採按需載入。工段表只查目前套用的類別，不再進頁時讀取全部工段。")

    category_choices = load_process_category_choices(include_common=True)
    current_default_category = get_default_process_category()
    if current_default_category not in category_choices:
        current_default_category = category_choices[0] if category_choices else ""
    if not category_choices:
        st.warning("目前沒有任何啟用類別，請先在類別清單管理新增並套用類別。")

    cat1, cat3 = st.columns([2, 3])
    with cat1:
        with st.form("system_default_process_category_form_v41", clear_on_submit=False):
            if category_choices:
                selected_default_category = st.selectbox(
                    "預設類別 / Default Category",
                    category_choices,
                    index=category_choices.index(current_default_category) if current_default_category in category_choices else 0,
                    help="選擇下拉選單只暫存；按『套用預設類別』才寫入 Neon。",
                    key="system_default_process_category_v48_pending",
                )
            else:
                selected_default_category = ""
                st.info("請先建立啟用類別。")
            apply_default_clicked = st.form_submit_button("▣ 套用預設類別", use_container_width=True, disabled=not can_manage)
        if can_manage and apply_default_clicked:
            saved_category = save_default_process_category(selected_default_category)
            _export_permanent_settings(f"已套用預設類別：{saved_category}")
            _refresh_after_apply(f"已套用預設類別：{saved_category}，畫面已重新整理。")
    with cat3:
        st.info("下拉、勾選與表格編輯只暫存；只有按套用/刪除才寫入 Neon。")

    st.markdown("#### 類別清單管理 / Category Master")
    cat_df = load_process_categories_df(active_only=False)
    if cat_df.empty:
        cat_df = pd.DataFrame(columns=["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    cat_view = _normalize_delete_column(cat_df)
    cat_edit_key = "_spt_13_category_edit_mode"
    if can_manage:
        cc1, cc2, cc3 = st.columns([1, 1, 4])
        if not st.session_state.get(cat_edit_key, False):
            if cc1.button("◇ 啟動編輯類別 / Enable Edit", key="enable_category_edit_v41", use_container_width=True):
                _set_edit_mode(cat_edit_key, True)
        else:
            if cc1.button("◌ 停止編輯類別 / Lock Edit", key="disable_category_edit_v41", use_container_width=True):
                _set_edit_mode(cat_edit_key, False)
        cc2.caption("新增：啟動編輯後，在表格最下方新增列。")

    if can_manage and st.session_state.get(cat_edit_key, False):
        st.info("編輯類別時不會立即寫入或重算；只有按下表單按鈕才寫入 Neon。")
        cat_draft_key = "system_process_categories_draft_v41"
        with st.form("system_process_categories_form_v41", clear_on_submit=False):
            edited_cat = render_table(
                cat_view,
                "system_process_categories",
                editable=True,
                disabled=["id", "created_at", "updated_at"],
                key="system_process_categories_editor_v41_form",
                height=300,
                num_rows="dynamic",
            )
            cat_apply_col, cat_delete_col = st.columns(2)
            with cat_apply_col:
                cat_apply_clicked = st.form_submit_button("◈ 套用並永久儲存類別 / Save Categories", type="primary", use_container_width=True, key="submit_save_categories_v42")
            with cat_delete_col:
                cat_delete_clicked = st.form_submit_button("◉ 刪除勾選類別 / Delete Selected", type="primary", use_container_width=True, key="submit_delete_categories_v42")
        if isinstance(edited_cat, pd.DataFrame):
            st.session_state[cat_draft_key] = edited_cat.copy()
        if cat_apply_clicked or cat_delete_clicked:
            edited_cat = st.session_state.get(cat_draft_key, edited_cat)
            if edited_cat is None:
                st.warning("找不到可套用的類別表格內容，請重新載入後再試。")
                st.stop()
            if cat_apply_clicked:
                save_df = edited_cat.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore")
                count = save_process_categories_df(save_df)
                _export_permanent_settings(f"已套用類別設定 {count} 筆")
                _refresh_after_apply(f"已套用類別設定 {count} 筆，畫面已重新整理。", cat_edit_key)
            else:
                try:
                    ids = [int(float(x)) for x in edited_cat[_delete_mask(edited_cat)]["id"].dropna().tolist()]
                except Exception:
                    ids = []
                if not ids:
                    st.warning("請先勾選要刪除的既有類別，再按確認套用。")
                else:
                    count = delete_process_categories(ids)
                    _export_permanent_settings(f"已刪除類別設定 {count} 筆")
                    _refresh_after_apply(f"已刪除類別設定 {count} 筆，畫面已重新整理。", cat_edit_key)
    else:
        render_table(cat_view.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore"), "system_process_categories", editable=False, height=260)

    st.markdown("#### 類別對應工段設定 / Category-specific Process Options")
    all_category_choices = load_process_category_choices(include_common=True)
    if current_default_category not in all_category_choices:
        current_default_category = all_category_choices[0] if all_category_choices else ""
    _applied_process_category = st.session_state.get("system_process_category_filter_applied_v41", current_default_category)
    if _applied_process_category not in all_category_choices:
        _applied_process_category = current_default_category if current_default_category in all_category_choices else (all_category_choices[0] if all_category_choices else "")
        st.session_state["system_process_category_filter_applied_v41"] = _applied_process_category
    with st.form("system_process_category_filter_form_v41", clear_on_submit=False):
        if all_category_choices:
            pending_filter_category = st.selectbox(
                "顯示類別 / Show Category",
                all_category_choices,
                index=all_category_choices.index(_applied_process_category) if _applied_process_category in all_category_choices else 0,
                key="system_process_category_filter_v48_pending",
                help="選擇下拉選單只暫存；按『載入此類別工段』後才查 Neon。",
            )
        else:
            pending_filter_category = ""
            st.info("目前沒有可顯示的啟用類別。")
        apply_filter_category = st.form_submit_button("▣ 載入此類別工段 / Load Category Processes", use_container_width=True)
    if apply_filter_category:
        st.session_state["system_process_category_filter_applied_v41"] = pending_filter_category
        st.session_state["_spt_13_process_edit_mode"] = False
        _v144_clear_process_option_editor_state("process_category_applied_v49")
        st.rerun()
    filter_category = st.session_state.get("system_process_category_filter_applied_v41", _applied_process_category)
    # V48: if the dropdown value was changed but the Load button was not pressed,
    # do not show the previously loaded category table under the new dropdown label.
    # This keeps "顯示類別 / Show Category" and the visible table from looking mismatched.
    if pending_filter_category and pending_filter_category != filter_category and not apply_filter_category:
        st.info(f"已選擇『{pending_filter_category}』但尚未載入。請按『載入此類別工段』後再顯示表格。")
        _v41_finish_and_stop()
    if not filter_category:
        st.warning("目前沒有已套用的類別，請先建立並啟用類別。")
        _v41_finish_and_stop()

    _v144_current_process_category = _v144_normalize_category_text(filter_category)
    _v144_last_process_category = st.session_state.get("_spt_v144_last_process_category")
    if _v144_last_process_category is not None and _v144_last_process_category != _v144_current_process_category:
        _v144_clear_process_option_editor_state("process_category_changed")
    st.session_state["_spt_v144_last_process_category"] = _v144_current_process_category
    _v144_process_category_key = _v144_safe_key_part(_v144_current_process_category)
    st.caption(f"目前已載入類別 / Loaded Category：{filter_category}")

    proc_df = load_process_options_df(active_only=False, category_name=filter_category)
    # V49 final display/editor guard: both readonly and editable tables must
    # strictly match the loaded category before rendering.
    _v44_selected_process_category = _v144_normalize_category_text(filter_category or "全部 / 通用")
    proc_df = _v49_force_process_table_category(proc_df, _v44_selected_process_category)
    proc_view = _normalize_delete_column(proc_df)

    proc_edit_key = "_spt_13_process_edit_mode"
    if can_manage:
        c1, c2, c3 = st.columns([1, 1, 4])
        if not st.session_state.get(proc_edit_key, False):
            if c1.button("◇ 啟動編輯工段 / Enable Edit", key="enable_process_edit_v49", use_container_width=True):
                _v144_clear_process_option_editor_state("enable_process_edit_v49")
                _set_edit_mode(proc_edit_key, True)
                st.rerun()
        else:
            if c1.button("◌ 停止編輯工段 / Lock Edit", key="disable_process_edit_v49", use_container_width=True):
                _v144_clear_process_option_editor_state("disable_process_edit_v49")
                _set_edit_mode(proc_edit_key, False)
                st.rerun()
        c2.caption("新增：啟動編輯後，在表格最下方新增列。刪除：勾選『刪除』後確認執行。")

    if can_manage and st.session_state.get(proc_edit_key, False):
        st.info("編輯工段時不會立即寫入或重算；只有按下表單按鈕才寫入 Neon。")
        _v49_process_editor_nonce = int(st.session_state.get("_spt_v49_process_editor_nonce", 0))
        proc_draft_key = f"system_process_options_draft_v49_{_v144_process_category_key}_{_v49_process_editor_nonce}"
        with st.form(f"system_process_options_form_v49_{_v144_process_category_key}_{_v49_process_editor_nonce}", clear_on_submit=False):
            edited_proc = render_table(
                proc_view,
                "system_process_options",
                editable=True,
                disabled=["id", "category_name", "created_at", "updated_at"],
                key=f"system_process_options_editor_v49_form_{_v144_process_category_key}_{_v49_process_editor_nonce}",
                height=430,
                num_rows="dynamic",
            )
            proc_apply_col, proc_delete_col = st.columns(2)
            with proc_apply_col:
                proc_apply_clicked = st.form_submit_button("◈ 套用並永久儲存工段 / Save Processes", type="primary", use_container_width=True, key=f"submit_save_processes_v49_{_v144_process_category_key}_{_v49_process_editor_nonce}")
            with proc_delete_col:
                proc_delete_clicked = st.form_submit_button("◉ 刪除勾選工段 / Delete Selected", type="primary", use_container_width=True, key=f"submit_delete_processes_v49_{_v144_process_category_key}_{_v49_process_editor_nonce}")
        if isinstance(edited_proc, pd.DataFrame):
            st.session_state[proc_draft_key] = _v49_force_process_table_category(edited_proc, filter_category or "全部 / 通用").copy()
        if proc_apply_clicked or proc_delete_clicked:
            edited_proc = st.session_state.get(proc_draft_key, edited_proc)
            if isinstance(edited_proc, pd.DataFrame):
                edited_proc = _v49_force_process_table_category(edited_proc, filter_category or "全部 / 通用")
            if edited_proc is None:
                st.warning("找不到可套用的工段表格內容，請重新載入後再試。")
                st.stop()
            if proc_apply_clicked:
                save_df = edited_proc.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore")
                ok_category, mismatches = _v144_process_rows_match_selected_category(save_df, filter_category or "全部 / 通用")
                if not ok_category:
                    _v144_clear_process_option_editor_state("process_category_mismatch_blocked")
                    st.error("偵測到工段表格草稿不是目前選定類別，已阻止儲存。" f"目前選定：{filter_category}；草稿含有：{', '.join(mismatches[:8])}。")
                    st.stop()
                save_df = _v144_prepare_process_save_df_for_category(save_df, filter_category or "全部 / 通用")
                count = save_process_options_df(save_df)
                _export_permanent_settings(f"已套用 {filter_category} 類別工段設定 {count} 筆")
                _refresh_after_apply(f"已套用 {filter_category} 類別工段設定 {count} 筆，畫面已重新整理。", proc_edit_key)
            else:
                try:
                    ids = [int(float(x)) for x in edited_proc[_delete_mask(edited_proc)]["id"].dropna().tolist()]
                except Exception:
                    ids = []
                if not ids:
                    st.warning("請先勾選要刪除的既有工段，再按確認套用。")
                else:
                    count = delete_process_options(ids)
                    _export_permanent_settings(f"已刪除工段名稱設定 {count} 筆")
                    _refresh_after_apply(f"已刪除工段名稱設定 {count} 筆，畫面已重新整理。", proc_edit_key)
    else:
        render_table(proc_view.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore"), "system_process_options", editable=False, height=420)

    _v41_finish_and_stop()

if section == "休息時間設定 / Rest Periods":
    st.subheader("二、休息時間設定 / Rest Periods")
    st.caption("這裡會套用到工時計算。格式請使用 HH:MM。只有『啟用』的休息時間會被扣除。")
    rest_df = load_rest_periods_df(active_only=False)
    if rest_df.empty:
        rest_df = pd.DataFrame(columns=["id", "name", "start_time", "end_time", "is_active", "sort_order"])
    rest_view = _normalize_delete_column(rest_df)

    rest_edit_key = "_spt_13_rest_edit_mode"
    if can_manage:
        c1, c2, c3 = st.columns([1, 1, 4])
        if not st.session_state.get(rest_edit_key, False):
            if c1.button("◇ 啟動編輯休息時間 / Enable Edit", key="enable_rest_edit_v41", use_container_width=True):
                _set_edit_mode(rest_edit_key, True)
        else:
            if c1.button("◌ 停止編輯休息時間 / Lock Edit", key="disable_rest_edit_v41", use_container_width=True):
                _set_edit_mode(rest_edit_key, False)
        c2.caption("新增：啟動編輯後，在表格最下方新增列。刪除：勾選『刪除』後確認執行。")

    if can_manage and st.session_state.get(rest_edit_key, False):
        st.info("編輯休息時間時不會立即寫入或重算；只有按下表單按鈕才寫入 Neon。")
        rest_draft_key = "system_rest_periods_draft_v41"
        with st.form("system_rest_periods_form_v41", clear_on_submit=False):
            edited_rest = render_table(
                rest_view,
                "system_rest_periods",
                editable=True,
                disabled=["id"],
                key="system_rest_periods_editor_v41_form",
                height=360,
                num_rows="dynamic",
            )
            rest_apply_col, rest_delete_col = st.columns(2)
            with rest_apply_col:
                rest_apply_clicked = st.form_submit_button("◈ 套用並永久儲存休息時間 / Save Rest Periods", type="primary", use_container_width=True, key="submit_save_rest_periods_v42")
            with rest_delete_col:
                rest_delete_clicked = st.form_submit_button("◉ 刪除勾選休息時間 / Delete Selected", type="primary", use_container_width=True, key="submit_delete_rest_periods_v42")
        if isinstance(edited_rest, pd.DataFrame):
            st.session_state[rest_draft_key] = edited_rest.copy()
        if rest_apply_clicked or rest_delete_clicked:
            edited_rest = st.session_state.get(rest_draft_key, edited_rest)
            if edited_rest is None:
                st.warning("找不到可套用的休息時間表格內容，請重新載入後再試。")
                st.stop()
            if rest_apply_clicked:
                save_df = edited_rest.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore")
                count = save_rest_periods_df(save_df)
                _export_permanent_settings(f"已套用休息時間設定 {count} 筆")
                _refresh_after_apply(f"已套用休息時間設定 {count} 筆，畫面已重新整理。", rest_edit_key)
            else:
                try:
                    ids = [int(float(x)) for x in edited_rest[_delete_mask(edited_rest)]["id"].dropna().tolist()]
                except Exception:
                    ids = []
                if not ids:
                    st.warning("請先勾選要刪除的既有休息時間，再按確認套用。")
                else:
                    count = delete_rest_periods(ids)
                    _export_permanent_settings(f"已刪除休息時間設定 {count} 筆")
                    _refresh_after_apply(f"已刪除休息時間設定 {count} 筆，畫面已重新整理。", rest_edit_key)
    else:
        render_table(rest_view.drop(columns=[SYSTEM_DELETE_COL, "刪除"], errors="ignore"), "system_rest_periods", editable=False, height=360)
    st.success("設定套用後的串接：01｜工時紀錄工段下拉選單讀取啟用工段；工時計算與 02｜歷史紀錄重新計算會使用啟用中的休息時間。")
    _v41_finish_and_stop()

_v41_finish_page()
# =================== END V41 13 Lazy Load Fast Entry ===================
