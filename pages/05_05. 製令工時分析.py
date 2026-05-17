# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from services.timezone_service import today_date
import plotly.express as px
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.time_record_service import load_records, save_time_records
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms

st.set_page_config(page_title="05. 製令工時分析", page_icon="⧈", layout="wide")
apply_theme()
require_module_access("05_analysis")
render_header("05｜製令工時分析", "製令、工段、人員累積工時分析與明細編輯")

c1, c2 = st.columns(2)
start = c1.date_input("開始日期 / Start Date", value=today_date() - timedelta(days=30))
end = c2.date_input("結束日期 / End Date", value=today_date())
df = load_records(str(start), str(end))

if df.empty:
    st.info("查無工時資料 / No records")
    st.stop()

df["work_hours"] = pd.to_numeric(df["work_hours"], errors="coerce").fillna(0)
df["work_time_text"] = df["work_hours"].map(hours_to_hms)

m1, m2, m3, m4 = st.columns(4)
m1.metric("累積工時 / Total Time", hours_to_hms(df["work_hours"].sum()))
m2.metric("製令數 / Work Orders", f"{df['work_order'].nunique():,}")
m3.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}")
m4.metric("工段數 / Processes", f"{df['process_name'].nunique():,}")

by_wo = (
    df.groupby("work_order", dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"))
    .reset_index()
    .sort_values("total_hours", ascending=False)
)
by_wo["工時 / Time"] = by_wo["total_hours"].map(hours_to_hms)

by_proc = (
    df.groupby("process_name", dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"))
    .reset_index()
    .sort_values("total_hours", ascending=False)
)
by_proc["工時 / Time"] = by_proc["total_hours"].map(hours_to_hms)

by_emp = (
    df.groupby(["employee_id", "employee_name"], dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"))
    .reset_index()
    .sort_values("total_hours", ascending=False)
)
by_emp["工時 / Time"] = by_emp["total_hours"].map(hours_to_hms)

trend = (
    df.groupby("start_date", dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"))
    .reset_index()
    .sort_values("start_date")
)
trend["工時 / Time"] = trend["total_hours"].map(hours_to_hms)

plotly_template = "plotly_dark"


def style_fig(fig, height: int = 430):
    fig.update_layout(
        template=plotly_template,
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=60, b=80),
        font=dict(size=13),
        yaxis_title="累積時數",
    )
    fig.update_traces(marker_line_width=0.8)
    return fig


tab1, tab2, tab3, tab4, tab5 = st.tabs(["製令分析", "工段分析", "人員分析", "趨勢分析", "明細編輯"])

with tab1:
    st.subheader("製令累積工時 / Work Order Time")
    fig = px.bar(
        by_wo.head(30),
        x="work_order",
        y="total_hours",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True},
        labels={"work_order": "製令 / Work Order", "total_hours": "累積時數 / Total Hours", "count": "筆數"},
        title="Top 30 製令累積工時 / Top Work Order Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 460), use_container_width=True)
    render_table(by_wo.drop(columns=["工時 / Time"], errors="ignore"), "analysis_by_work_order", editable=False, height=380)

with tab2:
    st.subheader("工段累積工時 / Process Time")
    fig = px.bar(
        by_proc,
        x="process_name",
        y="total_hours",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True},
        labels={"process_name": "工段 / Process", "total_hours": "累積時數 / Total Hours", "count": "筆數"},
        title="工段累積工時 / Process Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 460), use_container_width=True)
    render_table(by_proc.drop(columns=["工時 / Time"], errors="ignore"), "analysis_by_process", editable=False, height=380)

with tab3:
    st.subheader("人員累積工時 / Employee Time")
    fig = px.bar(
        by_emp.head(40),
        x="employee_name",
        y="total_hours",
        color="employee_id",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "employee_id": True},
        labels={"employee_name": "人員 / Employee", "total_hours": "累積時數 / Total Hours", "employee_id": "工號"},
        title="Top 40 人員累積工時 / Top Employee Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 480), use_container_width=True)
    render_table(by_emp.drop(columns=["工時 / Time"], errors="ignore"), "analysis_by_employee", editable=False, height=380)

with tab4:
    st.subheader("每日趨勢 / Daily Trend")
    fig = px.line(
        trend,
        x="start_date",
        y="total_hours",
        markers=True,
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True},
        labels={"start_date": "日期 / Date", "total_hours": "累積時數 / Total Hours"},
        title="每日累積工時趨勢 / Daily Time Trend",
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(style_fig(fig, 430), use_container_width=True)
    render_table(trend.drop(columns=["工時 / Time"], errors="ignore"), "analysis_daily_trend", editable=False, height=320)

with tab5:
    st.caption("此處編輯的是分析來源明細，儲存後會影響歷史紀錄與後續統計。工時欄位以 00:00:00 顯示，需調整時請改開始/結束時間後重新計算。")
    st.info("V1.89：明細編輯已改成確認後才儲存。表格內輸入不會立即觸發整頁運算。")
    with st.form("analysis_detail_commit_form", clear_on_submit=False):
        edited = render_table(df.drop(columns=["work_time_text"], errors="ignore"), "analysis_detail_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at", "work_hours"], key="analysis_detail_editor", height=520)
        submitted_analysis_detail = st.form_submit_button("▣ 確認儲存分析明細 / Save Detail Records", type="primary", use_container_width=True)
    if submitted_analysis_detail and edited is not None:
        count = save_time_records(edited)
        st.success(f"已儲存 {count} 筆明細。")
        st.rerun()
