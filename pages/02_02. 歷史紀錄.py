# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.time_record_service import load_records, save_time_records
from services.master_data_service import load_employees, load_work_orders
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms

st.set_page_config(page_title="02. 歷史紀錄", page_icon="📚", layout="wide")
apply_theme()
render_header("02｜歷史紀錄", "完整工時明細查詢、資料編輯、儲存與 Excel 匯出")

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
edited = render_table(df, "history_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at"], key="history_editor", height=520)
if edited is not None:
    csave, cdl = st.columns([1, 1])
    if csave.button("💾 儲存編輯 / Save Changes", use_container_width=True):
        count = save_time_records(edited)
        st.success(f"已儲存 {count} 筆歷史紀錄。")
        st.rerun()

if not df.empty:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="歷史紀錄")
    st.download_button("下載 Excel / Export Excel", data=bio.getvalue(), file_name=f"SPT_歷史紀錄_{start}_{end}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
