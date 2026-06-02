from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from spt_core.auth import current_user, login_form, logout_button
from spt_core.db import current_database_label, init_db
from spt_core.services.login_event_service import list_login_events
from spt_core.services.log_service import list_logs
from spt_core.services.time_record_service import list_time_records
from spt_core.ui import render_result, setup_page
from spt_core.utils import today_str

setup_page("超慧科技製造部｜工時紀錄系統")
init_db()

logo_path = Path("assets/super_plus_logo.png")
if logo_path.exists():
    st.image(str(logo_path), width=220)
st.title("超慧科技製造部_工時紀錄")
st.caption("SPT-time-tracking-system｜PostgreSQL / Neon 單一真實來源架構｜260602 舊專案清理轉換版")

user = current_user()
if not user:
    st.info("請登入後使用系統。首次啟動會自動建立管理員帳號。")
    login_form()
    st.stop()

logout_button()
st.success(f"已登入：{user['display_name']}（{user['role']}）")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("資料來源", current_database_label())
with col2:
    active = list_time_records({"work_date_from": today_str(), "work_date_to": today_str(), "status": "active"})
    st.metric("今日進行中", len(active.data or []))
with col3:
    done = list_time_records({"work_date_from": today_str(), "work_date_to": today_str(), "status": "completed"})
    st.metric("今日已完工", len(done.data or []))
with col4:
    logs = list_logs(limit=20)
    st.metric("最近 LOG", len(logs.data or []))

st.divider()
st.subheader("今日工時摘要")
today_records = list_time_records({"work_date_from": today_str(), "work_date_to": today_str()})
render_result(today_records, success_text=None)
if today_records.ok and today_records.data:
    df = pd.DataFrame(today_records.data)
    show_cols = [
        "work_date", "employee_id", "employee_name", "work_order_no", "process_name",
        "start_time", "end_time", "status", "work_minutes", "average_minutes",
    ]
    st.dataframe(df[[c for c in show_cols if c in df.columns]], use_container_width=True, hide_index=True)
else:
    st.info("今日尚無工時紀錄。")

st.subheader("最近操作 LOG")
if logs.ok and logs.data:
    st.dataframe(pd.DataFrame(logs.data), use_container_width=True, hide_index=True)

st.subheader("最近登入紀錄")
login_events = list_login_events(limit=10)
if login_events.ok and login_events.data:
    st.dataframe(pd.DataFrame(login_events.data), use_container_width=True, hide_index=True)
