# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
import streamlit as st
from services.theme_service import apply_theme, render_header
from services.db_service import query_df

st.set_page_config(page_title="07 今日未紀錄名單", page_icon="⚠️", layout="wide")
apply_theme()
render_header("07｜今日未紀錄名單", "出勤 / 在廠但尚未有任何工時紀錄的人員")

today = date.today().strftime("%Y-%m-%d")
df = query_df("""
SELECT e.employee_id, e.employee_name, e.department, e.title, e.is_in_factory, e.is_today_attendance,
       MAX(t.start_timestamp) AS last_start_time,
       COUNT(t.id) AS today_record_count
FROM employees e
LEFT JOIN time_records t
  ON e.employee_id=t.employee_id AND t.start_date=?
WHERE e.is_active=1 AND e.is_in_factory=1 AND e.is_today_attendance=1
GROUP BY e.employee_id, e.employee_name, e.department, e.title, e.is_in_factory, e.is_today_attendance
HAVING COUNT(t.id)=0
ORDER BY e.employee_id
""", (today,))

st.metric("今日未紀錄人數", f"{len(df):,}")
st.dataframe(df, use_container_width=True, hide_index=True)
