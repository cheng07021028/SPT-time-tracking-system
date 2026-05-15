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

edited_proc = render_table(
    proc_edit,
    "system_process_options",
    editable=can_manage,
    disabled=["id", "created_at", "updated_at"] if can_manage else list(proc_edit.columns),
    key="system_process_options_editor",
    height=420,
)

if can_manage and edited_proc is not None:
    p1, p2 = st.columns(2)
    if p1.button("💾 套用並永久儲存工段名稱設定", use_container_width=True, key="save_process_options"):
        save_df = edited_proc.drop(columns=["刪除"], errors="ignore")
        count = save_process_options_df(save_df)
        st.success(f"已永久儲存工段名稱設定 {count} 筆。")
        st.rerun()
    try:
        delete_ids = [int(x) for x in edited_proc[edited_proc["刪除"].astype(bool)]["id"].dropna().tolist()]
    except Exception:
        delete_ids = []
    if p2.button(f"🗑️ 刪除勾選工段（{len(delete_ids)}）", use_container_width=True, key="delete_process_options", disabled=len(delete_ids) == 0):
        count = delete_process_options(delete_ids)
        st.success(f"已刪除工段名稱設定 {count} 筆。")
        st.rerun()

st.divider()
st.subheader("二、休息時間設定 / Rest Periods")
st.caption("工時計算會扣除啟用中的休息時間。格式請使用 HH:MM，例如 10:30、12:00。")
rest_df = load_rest_periods_df(active_only=False)
if rest_df.empty:
    rest_df = pd.DataFrame(columns=["id", "name", "start_time", "end_time", "is_active", "sort_order"])
rest_edit = rest_df.copy()
if "刪除" not in rest_edit.columns:
    rest_edit.insert(0, "刪除", False)

edited_rest = render_table(
    rest_edit,
    "system_rest_periods",
    editable=can_manage,
    disabled=["id"] if can_manage else list(rest_edit.columns),
    key="system_rest_periods_editor",
    height=360,
)

if can_manage and edited_rest is not None:
    r1, r2 = st.columns(2)
    if r1.button("💾 套用並永久儲存休息時間設定", use_container_width=True, key="save_rest_periods"):
        save_df = edited_rest.drop(columns=["刪除"], errors="ignore")
        count = save_rest_periods_df(save_df)
        st.success(f"已永久儲存休息時間設定 {count} 筆，後續工時計算會套用新規則。")
        st.rerun()
    try:
        rest_delete_ids = [int(x) for x in edited_rest[edited_rest["刪除"].astype(bool)]["id"].dropna().tolist()]
    except Exception:
        rest_delete_ids = []
    if r2.button(f"🗑️ 刪除勾選休息時間（{len(rest_delete_ids)}）", use_container_width=True, key="delete_rest_periods", disabled=len(rest_delete_ids) == 0):
        count = delete_rest_periods(rest_delete_ids)
        st.success(f"已刪除休息時間設定 {count} 筆。")
        st.rerun()
