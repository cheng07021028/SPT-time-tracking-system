# -*- coding: utf-8 -*-
from __future__ import annotations

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
)
from services.db_service import flush_pending_permanent_state

st.set_page_config(page_title="13. 系統設定", page_icon="⚙️", layout="wide")
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
        if c1.button("✏️ 啟動編輯工段", key="enable_process_edit", use_container_width=True):
            _set_edit_mode(proc_edit_key, True)
    else:
        if c1.button("🔒 停止編輯工段", key="disable_process_edit", use_container_width=True):
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
        submitted = st.form_submit_button("✅ 確認套用 / Apply", type="primary", use_container_width=True)

    if submitted and edited_proc is not None:
        if action == "套用並永久儲存工段名稱設定":
            save_df = edited_proc.drop(columns=["刪除"], errors="ignore")
            count = save_process_options_df(save_df)
            _export_permanent_settings(f"已套用工段名稱設定 {count} 筆")
            _refresh_after_apply(f"已套用工段名稱設定 {count} 筆，畫面已重新整理。", proc_edit_key)
        else:
            selected_df = edited_proc[edited_proc["刪除"].astype(bool)].copy() if "刪除" in edited_proc.columns else pd.DataFrame()
            try:
                ids = [int(float(x)) for x in selected_df["id"].dropna().tolist() if str(x).strip().lower() not in {"", "nan", "none"}]
            except Exception:
                ids = []
            transient_count = 0
            if not selected_df.empty and "id" in selected_df.columns:
                transient_count = int(selected_df["id"].isna().sum())
            if not ids and transient_count <= 0:
                st.warning("請先勾選要刪除的工段，再按確認套用。")
            else:
                count = delete_process_options(ids) if ids else 0
                _export_permanent_settings(f"已刪除工段名稱設定 {count} 筆")
                extra = f"；另已清除未儲存新增列 {transient_count} 筆" if transient_count else ""
                _refresh_after_apply(f"已刪除工段名稱設定 {count} 筆{extra}，畫面已重新整理。", proc_edit_key)
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
        if c1.button("✏️ 啟動編輯休息時間", key="enable_rest_edit", use_container_width=True):
            _set_edit_mode(rest_edit_key, True)
    else:
        if c1.button("🔒 停止編輯休息時間", key="disable_rest_edit", use_container_width=True):
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
        submitted = st.form_submit_button("✅ 確認套用 / Apply", type="primary", use_container_width=True)

    if submitted and edited_rest is not None:
        if action == "套用並永久儲存休息時間設定":
            save_df = edited_rest.drop(columns=["刪除"], errors="ignore")
            count = save_rest_periods_df(save_df)
            _export_permanent_settings(f"已套用休息時間設定 {count} 筆")
            _refresh_after_apply(f"已套用休息時間設定 {count} 筆，畫面已重新整理。", rest_edit_key)
        else:
            selected_df = edited_rest[edited_rest["刪除"].astype(bool)].copy() if "刪除" in edited_rest.columns else pd.DataFrame()
            try:
                ids = [int(float(x)) for x in selected_df["id"].dropna().tolist() if str(x).strip().lower() not in {"", "nan", "none"}]
            except Exception:
                ids = []
            transient_count = 0
            if not selected_df.empty and "id" in selected_df.columns:
                transient_count = int(selected_df["id"].isna().sum())
            if not ids and transient_count <= 0:
                st.warning("請先勾選要刪除的休息時間，再按確認套用。")
            else:
                count = delete_rest_periods(ids) if ids else 0
                _export_permanent_settings(f"已刪除休息時間設定 {count} 筆")
                extra = f"；另已清除未儲存新增列 {transient_count} 筆" if transient_count else ""
                _refresh_after_apply(f"已刪除休息時間設定 {count} 筆{extra}，畫面已重新整理。", rest_edit_key)
else:
    render_table(rest_view.drop(columns=["刪除"], errors="ignore"), "system_rest_periods", editable=False, height=360)

st.divider()
st.success("設定套用後的串接：01｜工時紀錄工段下拉選單立即讀取啟用工段；工時計算與 02｜歷史紀錄重新計算會使用啟用中的休息時間。")
