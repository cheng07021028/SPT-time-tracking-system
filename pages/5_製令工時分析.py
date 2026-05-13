# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
import streamlit as st
import plotly.express as px
from services.theme_service import apply_theme, render_header
from services.time_record_service import load_records

st.set_page_config(page_title="05 製令工時分析", page_icon="📊", layout="wide")
apply_theme()
render_header("05｜製令工時分析", "製令、工段、人員累積工時 BI 分析")

c1, c2 = st.columns(2)
start = c1.date_input("開始日期", value=date.today() - timedelta(days=30))
end = c2.date_input("結束日期", value=date.today())
df = load_records(str(start), str(end))

if df.empty:
    st.info("查無工時資料")
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("總工時", f"{df['work_hours'].sum():.2f}")
m2.metric("製令數", f"{df['work_order'].nunique():,}")
m3.metric("人員數", f"{df['employee_id'].nunique():,}")
m4.metric("工段數", f"{df['process_name'].nunique():,}")

by_wo = df.groupby("work_order", dropna=False)["work_hours"].sum().reset_index().sort_values("work_hours", ascending=False)
by_proc = df.groupby("process_name", dropna=False)["work_hours"].sum().reset_index().sort_values("work_hours", ascending=False)
by_emp = df.groupby(["employee_id", "employee_name"], dropna=False)["work_hours"].sum().reset_index().sort_values("work_hours", ascending=False)

left, right = st.columns(2)
with left:
    st.subheader("製令累積工時")
    st.plotly_chart(px.bar(by_wo.head(30), x="work_order", y="work_hours", text_auto=True), use_container_width=True)
    st.dataframe(by_wo, use_container_width=True, hide_index=True)
with right:
    st.subheader("工段累積工時")
    st.plotly_chart(px.bar(by_proc, x="process_name", y="work_hours", text_auto=True), use_container_width=True)
    st.dataframe(by_proc, use_container_width=True, hide_index=True)

st.subheader("人員累積工時")
st.plotly_chart(px.bar(by_emp.head(40), x="employee_name", y="work_hours", color="employee_id", text_auto=True), use_container_width=True)
st.dataframe(by_emp, use_container_width=True, hide_index=True)
