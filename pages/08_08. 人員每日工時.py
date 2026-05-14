# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
import streamlit as st
import plotly.express as px

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.db_service import query_df
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms

st.set_page_config(page_title="08. 人員每日工時", page_icon="⏱️", layout="wide")
apply_theme()
require_module_access("08_daily_hours")
render_header("08｜人員每日工時", "每日應紀錄 7~7.5 小時，快速辨識偏低、超時、未紀錄")

selected = st.date_input("日期 / Date", value=date.today())
d = selected.strftime("%Y-%m-%d")

df = query_df("""
SELECT e.employee_id, e.employee_name, e.department, e.title,
       COALESCE(SUM(t.work_hours), 0) AS total_hours,
       COUNT(t.id) AS record_count,
       SUM(CASE WHEN t.end_timestamp IS NULL THEN 1 ELSE 0 END) AS active_count
FROM employees e
LEFT JOIN time_records t
  ON e.employee_id=t.employee_id AND t.start_date=?
WHERE e.is_active=1 AND e.is_in_factory=1 AND e.is_today_attendance=1
GROUP BY e.employee_id, e.employee_name, e.department, e.title
ORDER BY total_hours ASC, e.employee_id
""", (d,))

if not df.empty:
    def status(h, cnt, active):
        if active and active > 0:
            return "作業中"
        if cnt == 0:
            return "未紀錄"
        if h < 7:
            return "偏低"
        if h <= 7.5:
            return "正常"
        return "超時"

    df["status"] = df.apply(lambda r: status(r["total_hours"], r["record_count"], r["active_count"]), axis=1)
    df["累積工時 / Total Time"] = df["total_hours"].map(hours_to_hms)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("出勤在廠人數 / Attendance", f"{len(df):,}")
    c2.metric("累積工時 / Total Time", hours_to_hms(df["total_hours"].sum()))
    c3.metric("未紀錄 / No Record", f"{(df['status']=='未紀錄').sum():,}")
    c4.metric("偏低 / Low", f"{(df['status']=='偏低').sum():,}")

    st.subheader("工時分布 / Time Distribution")
    chart_df = df.copy()
    fig = px.bar(
        chart_df.sort_values("total_hours", ascending=False),
        x="employee_name",
        y="total_hours",
        color="status",
        hover_data={
            "employee_id": True,
            "department": True,
            "title": True,
            "record_count": True,
            "active_count": True,
            "total_hours": ":.2f",
            "累積工時 / Total Time": True,
        },
        labels={"employee_name": "人員", "total_hours": "累積時數", "status": "狀態"},
        title="人員每日累積工時 / Daily Employee Time",
    )
    fig.update_layout(
        template="plotly_dark",
        height=420,
        margin=dict(l=20, r=20, t=60, b=80),
        yaxis_title="累積時數",
        xaxis_title="人員",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("目前沒有符合條件的人員資料 / No employee data")

render_table(df, "daily_employee_hours", editable=False, height=620)
