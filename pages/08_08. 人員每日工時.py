# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.db_service import query_df
from services.table_ui_service import render_table

st.set_page_config(page_title="08. 人員每日工時", page_icon="⏱️", layout="wide")
apply_theme()
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("出勤在廠人數 / Attendance", f"{len(df):,}")
    c2.metric("未紀錄 / No Record", f"{(df['status']=='未紀錄').sum():,}")
    c3.metric("偏低 / Low", f"{(df['status']=='偏低').sum():,}")
    c4.metric("正常/超時 / OK/Over", f"{((df['status']=='正常') | (df['status']=='超時')).sum():,}")

render_table(df, "daily_employee_hours", editable=False, height=620)
