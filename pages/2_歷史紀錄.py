# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import pandas as pd
import streamlit as st
from services.theme_service import apply_theme, render_header
from services.time_record_service import load_records
from services.master_data_service import load_employees, load_work_orders

st.set_page_config(page_title="02 歷史紀錄", page_icon="📚", layout="wide")
apply_theme()
render_header("02｜歷史紀錄", "完整工時明細查詢與 Excel 匯出")

employees = load_employees(active_only=False)
work_orders = load_work_orders(active_only=False)

c1, c2, c3, c4 = st.columns(4)
start = c1.date_input("開始日期", value=date.today() - timedelta(days=7))
end = c2.date_input("結束日期", value=date.today())
emp_opts = [""] + ([] if employees.empty else employees["employee_id"].astype(str).tolist())
wo_opts = [""] + ([] if work_orders.empty else work_orders["work_order"].astype(str).tolist())
emp = c3.selectbox("工號", emp_opts)
wo = c4.selectbox("製令", wo_opts)

df = load_records(str(start), str(end), emp or None, wo or None)

m1, m2, m3, m4 = st.columns(4)
m1.metric("筆數", f"{len(df):,}")
m2.metric("總工時", f"{df['work_hours'].sum():.2f}" if not df.empty else "0.00")
m3.metric("作業中", f"{(df['end_timestamp'].isna()).sum():,}" if not df.empty else "0")
m4.metric("人員數", f"{df['employee_id'].nunique():,}" if not df.empty else "0")

st.dataframe(df, use_container_width=True, hide_index=True)

if not df.empty:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="歷史紀錄")
    st.download_button("下載 Excel", data=bio.getvalue(), file_name=f"SPT_歷史紀錄_{start}_{end}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
