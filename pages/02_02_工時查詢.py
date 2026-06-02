from __future__ import annotations

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.employee_service import list_employees
from spt_core.services.process_service import list_processes
from spt_core.services.time_record_service import list_time_records
from spt_core.services.work_order_service import list_work_orders
from spt_core.ui import setup_page
from spt_core.utils import today_str

setup_page("02 工時查詢")
init_db()
user = require_login()

st.title("02. 工時紀錄查詢")

employees = list_employees(active_only=False).data or []
work_orders = list_work_orders(active_only=False).data or []
processes = list_processes(active_only=False).data or []

with st.form("query_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        d1 = st.date_input("起始日期")
    with col2:
        d2 = st.date_input("結束日期")
    with col3:
        status = st.selectbox("狀態", ["", "active", "completed", "paused", "deleted"])
    emp_options = [""] + [e["employee_id"] for e in employees]
    wo_options = [""] + [w["work_order_no"] for w in work_orders]
    pc_options = [""] + [p["process_code"] for p in processes]
    c1, c2, c3 = st.columns(3)
    with c1:
        emp = st.selectbox("工號", emp_options)
    with c2:
        wo = st.selectbox("製令", wo_options)
    with c3:
        pc = st.selectbox("工段", pc_options)
    include_deleted = st.checkbox("包含已刪除紀錄（僅管理員建議使用）", value=False)
    submitted = st.form_submit_button("查詢")

if submitted:
    filters = {"work_date_from": d1.isoformat(), "work_date_to": d2.isoformat()}
    if status:
        filters["status"] = status
    if emp:
        filters["employee_id"] = emp
    if wo:
        filters["work_order_no"] = wo
    if pc:
        filters["process_code"] = pc
    result = list_time_records(filters, include_deleted=include_deleted, limit=5000)
else:
    result = list_time_records({"work_date_from": today_str(), "work_date_to": today_str()}, limit=500)

if result.ok and result.data:
    df = pd.DataFrame(result.data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button("下載 CSV", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="spt_time_records.csv", mime="text/csv")
else:
    st.info("查無資料。")
