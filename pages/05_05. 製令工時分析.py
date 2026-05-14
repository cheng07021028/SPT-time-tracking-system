# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
import streamlit as st
import plotly.express as px

from services.theme_service import apply_theme, render_header
from services.time_record_service import load_records, save_time_records
from services.table_ui_service import render_table

st.set_page_config(page_title="05. 製令工時分析", page_icon="📊", layout="wide")
apply_theme()
render_header("05｜製令工時分析", "製令、工段、人員累積工時 BI 分析與明細編輯")

c1, c2 = st.columns(2)
start = c1.date_input("開始日期 / Start Date", value=date.today() - timedelta(days=30))
end = c2.date_input("結束日期 / End Date", value=date.today())
df = load_records(str(start), str(end))

if df.empty:
    st.info("查無工時資料 / No records")
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("總工時 / Total Hours", f"{df['work_hours'].sum():.2f}")
m2.metric("製令數 / Work Orders", f"{df['work_order'].nunique():,}")
m3.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}")
m4.metric("工段數 / Processes", f"{df['process_name'].nunique():,}")

by_wo = df.groupby("work_order", dropna=False).agg(work_hours=("work_hours", "sum"), count=("id", "count")).reset_index().sort_values("work_hours", ascending=False)
by_proc = df.groupby("process_name", dropna=False).agg(work_hours=("work_hours", "sum"), count=("id", "count")).reset_index().sort_values("work_hours", ascending=False)
by_emp = df.groupby(["employee_id", "employee_name"], dropna=False).agg(work_hours=("work_hours", "sum"), count=("id", "count")).reset_index().sort_values("work_hours", ascending=False)

tab1, tab2, tab3, tab4 = st.tabs(["製令分析", "工段分析", "人員分析", "明細編輯"])
with tab1:
    st.subheader("製令累積工時 / Work Order Hours")
    st.plotly_chart(px.bar(by_wo.head(30), x="work_order", y="work_hours", text_auto=True), use_container_width=True)
    render_table(by_wo, "analysis_by_work_order", editable=False, height=380)
with tab2:
    st.subheader("工段累積工時 / Process Hours")
    st.plotly_chart(px.bar(by_proc, x="process_name", y="work_hours", text_auto=True), use_container_width=True)
    render_table(by_proc, "analysis_by_process", editable=False, height=380)
with tab3:
    st.subheader("人員累積工時 / Employee Hours")
    st.plotly_chart(px.bar(by_emp.head(40), x="employee_name", y="work_hours", color="employee_id", text_auto=True), use_container_width=True)
    render_table(by_emp, "analysis_by_employee", editable=False, height=380)
with tab4:
    st.caption("此處編輯的是分析來源明細，儲存後會影響歷史紀錄與後續統計。")
    edited = render_table(df, "analysis_detail_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at"], key="analysis_detail_editor", height=520)
    if edited is not None and st.button("💾 儲存分析明細 / Save Detail Records", use_container_width=True):
        count = save_time_records(edited)
        st.success(f"已儲存 {count} 筆明細。")
        st.rerun()
