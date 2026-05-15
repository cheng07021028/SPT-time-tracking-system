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

st.set_page_config(page_title="13. 系統設定", page_icon="⚙️", layout="wide")
apply_theme()
require_module_access("13_system_settings", "can_view")
render_header("13｜系統設定", "工段名稱下拉選單、休息時間扣除規則｜可新增、刪除、修改並永久保存")

can_manage = check_permission("13_system_settings", "can_manage") or check_permission("13_system_settings", "can_edit")
if not can_manage:
    st.warning("你目前只有查看權限，設定修改需由管理員或具備 13 系統設定 can_manage / can_edit 權限的人員操作。")

st.info("本頁設定會寫入資料庫並觸發既有永久 JSON / GitHub 備份流程。01 工時紀錄的工段下拉選單、工時計算扣除休息時間會直接讀取這裡的設定。")

st.subheader("一、工段名稱設定 / Process Options")
proc_df = load_process_options_df(active_only=False)
if proc_df.empty:
    proc_df = pd.DataFrame(columns=["id", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
proc_edit = proc_df.copy()
if "刪除" not in proc_edit.columns:
    proc_edit.insert(0, "刪除", False)

if can_manage:
    st.caption("效能模式：修改工段表格不會立即重跑；按下『執行』才會永久儲存或刪除。")
    with st.form("system_process_options_batch_form", clear_on_submit=False):
        edited_proc = render_table(
            proc_edit,
            "system_process_options",
            editable=True,
            disabled=["id", "created_at", "updated_at"],
            key="system_process_options_editor",
            height=420,
        )
        proc_action = st.radio(
            "工段設定動作 / Action",
            ["💾 套用並永久儲存工段名稱設定", "🗑️ 刪除勾選工段"],
            horizontal=True,
            key="system_process_options_action",
        )
        proc_submitted = st.form_submit_button("✅ 執行 / Apply", use_container_width=True)

    if proc_submitted and edited_proc is not None:
        if proc_action.startswith("💾"):
            save_df = edited_proc.drop(columns=["刪除"], errors="ignore")
            count = save_process_options_df(save_df)
            st.success(f"已永久儲存工段名稱設定 {count} 筆。")
            st.rerun()
        else:
            try:
                delete_ids = [int(x) for x in edited_proc[edited_proc["刪除"].astype(bool)]["id"].dropna().tolist()]
            except Exception:
                delete_ids = []
            if not delete_ids:
                st.warning("請先勾選要刪除的工段。")
            else:
                count = delete_process_options(delete_ids)
                st.success(f"已刪除工段名稱設定 {count} 筆。")
                st.rerun()
else:
    render_table(
        proc_edit,
        "system_process_options",
        editable=False,
        key="system_process_options_view",
        height=420,
    )

st.divider()
st.subheader("二、休息時間設定 / Rest Periods")
st.caption("工時計算會扣除啟用中的休息時間。格式請使用 HH:MM，例如 10:30、12:00。")
rest_df = load_rest_periods_df(active_only=False)
if rest_df.empty:
    rest_df = pd.DataFrame(columns=["id", "name", "start_time", "end_time", "is_active", "sort_order"])
rest_edit = rest_df.copy()
if "刪除" not in rest_edit.columns:
    rest_edit.insert(0, "刪除", False)

if can_manage:
    st.caption("效能模式：修改休息時間表格不會立即重跑；按下『執行』才會永久儲存或刪除。")
    with st.form("system_rest_periods_batch_form", clear_on_submit=False):
        edited_rest = render_table(
            rest_edit,
            "system_rest_periods",
            editable=True,
            disabled=["id"],
            key="system_rest_periods_editor",
            height=360,
        )
        rest_action = st.radio(
            "休息時間設定動作 / Action",
            ["💾 套用並永久儲存休息時間設定", "🗑️ 刪除勾選休息時間"],
            horizontal=True,
            key="system_rest_periods_action",
        )
        rest_submitted = st.form_submit_button("✅ 執行 / Apply", use_container_width=True)

    if rest_submitted and edited_rest is not None:
        if rest_action.startswith("💾"):
            save_df = edited_rest.drop(columns=["刪除"], errors="ignore")
            count = save_rest_periods_df(save_df)
            st.success(f"已永久儲存休息時間設定 {count} 筆，後續工時計算會套用新規則。")
            st.rerun()
        else:
            try:
                rest_delete_ids = [int(x) for x in edited_rest[edited_rest["刪除"].astype(bool)]["id"].dropna().tolist()]
            except Exception:
                rest_delete_ids = []
            if not rest_delete_ids:
                st.warning("請先勾選要刪除的休息時間。")
            else:
                count = delete_rest_periods(rest_delete_ids)
                st.success(f"已刪除休息時間設定 {count} 筆。")
                st.rerun()
else:
    render_table(
        rest_edit,
        "system_rest_periods",
        editable=False,
        key="system_rest_periods_view",
        height=360,
    )
