# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.time_record_service import load_records, save_time_records, delete_time_records, recalculate_time_records
from services.master_data_service import load_employees, load_work_orders
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms

st.set_page_config(page_title="02. 歷史紀錄", page_icon="📚", layout="wide")
apply_theme()
require_module_access("02_history")
render_header("02｜歷史紀錄", "完整工時明細查詢、資料編輯、刪除、重新計算與 Excel 匯出")

employees = load_employees(active_only=False)
work_orders = load_work_orders(active_only=False)

c1, c2, c3, c4 = st.columns(4)
start = c1.date_input("開始日期 / Start Date", value=date.today() - timedelta(days=7))
end = c2.date_input("結束日期 / End Date", value=date.today())
emp_opts = [""] + ([] if employees.empty else employees["employee_id"].astype(str).tolist())
wo_opts = [""] + ([] if work_orders.empty else work_orders["work_order"].astype(str).tolist())
emp = c3.selectbox("工號 / Employee ID", emp_opts)
wo = c4.selectbox("製令 / Work Order", wo_opts)

df = load_records(str(start), str(end), emp or None, wo or None)

m1, m2, m3, m4 = st.columns(4)
m1.metric("筆數 / Records", f"{len(df):,}")
m2.metric("總工時 / Total Time", hours_to_hms(df['work_hours'].sum()) if not df.empty else "00:00:00")
m3.metric("作業中 / Active", f"{(df['end_timestamp'].isna()).sum():,}" if not df.empty else "0")
m4.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}" if not df.empty else "0")

st.subheader("歷史明細編輯 / Editable History")

can_edit = check_permission("02_history", "can_edit")
can_delete = check_permission("02_history", "can_delete")

if not can_edit:
    st.info("目前帳號只有查詢權限；若需修改或刪除歷史紀錄，請由管理員在權限管理開放 02 歷史紀錄的編輯/刪除權限。")
    render_table(df, "history_records", editable=False, height=520)
else:
    edit_key = "history_edit_enabled"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = False
    ec1, ec2, ec3 = st.columns([1, 1, 2])
    if ec1.button("✏️ 啟動編輯 / Enable Edit", use_container_width=True, key="history_enable_edit"):
        st.session_state[edit_key] = True
        st.rerun()
    if ec2.button("🔒 停止編輯 / Stop Edit", use_container_width=True, key="history_stop_edit"):
        st.session_state[edit_key] = False
        st.rerun()
    ec3.info("編輯啟動後可修改資料；勾選『刪除』後可整列刪除。刪除需具備 can_delete 權限。")

    if st.session_state[edit_key]:
        edit_df = df.copy()
        if "刪除" not in edit_df.columns:
            edit_df.insert(0, "刪除", False)
        edited = render_table(edit_df, "history_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at"], key="history_editor", height=560)
        if edited is not None:
            try:
                delete_rows = edited[edited["刪除"].astype(bool)] if "刪除" in edited.columns else pd.DataFrame()
                delete_ids = [int(x) for x in delete_rows["id"].dropna().tolist()]
            except Exception:
                delete_ids = []

            csave, crecalc, cdelete = st.columns(3)
            if csave.button("💾 儲存編輯 / Save Changes", use_container_width=True, key="history_save_changes"):
                save_df = edited.drop(columns=["刪除"], errors="ignore")
                count = save_time_records(save_df)
                st.success(f"已儲存 {count} 筆歷史紀錄。")
                st.rerun()

            if crecalc.button("🧮 重新計算勾選紀錄工時", use_container_width=True, key="history_recalc_selected", disabled=len(delete_ids) == 0):
                count = recalculate_time_records(delete_ids)
                st.success(f"已重新計算 {count} 筆工時。")
                st.rerun()

            if cdelete.button(f"🗑️ 刪除勾選整列紀錄（{len(delete_ids)}）", use_container_width=True, key="history_delete_selected", disabled=(len(delete_ids) == 0 or not can_delete)):
                count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")
                st.success(f"已刪除 {count} 筆歷史紀錄。")
                st.rerun()
            if delete_ids and not can_delete:
                st.warning("你已勾選刪除，但目前帳號沒有 02 歷史紀錄的刪除權限。")
    else:
        render_table(df, "history_records", editable=False, height=520)

if not df.empty:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="歷史紀錄")
    st.download_button("下載 Excel / Export Excel", data=bio.getvalue(), file_name=f"SPT_歷史紀錄_{start}_{end}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
