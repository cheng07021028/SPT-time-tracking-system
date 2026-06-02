from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.employee_service import list_employees
from spt_core.services.process_service import list_processes
from spt_core.services.time_record_service import delete_time_record, finish_work, list_active_records, list_time_records, start_work
from spt_core.services.work_order_service import list_work_orders
from spt_core.ui import render_result, setup_page
from spt_core.utils import today_str

setup_page("01 工時紀錄")
init_db()
user = require_login()

st.title("01. 工時紀錄")
st.caption("開始作業、完工作業、同組平均、刪除防復活。")

employees = list_employees(active_only=True).data or []
work_orders = list_work_orders(active_only=True).data or []
processes = list_processes(active_only=True).data or []

start_tab, active_tab, today_tab = st.tabs(["開始作業", "進行中 / 完工 / 刪除", "今日明細"])

with start_tab:
    st.subheader("開始作業")
    if not employees:
        st.warning("尚無啟用人員，請先到 04 人員名單新增。")
    if not work_orders:
        st.warning("尚無開啟中的製令，請先到 03 製令管理新增。")
    if not processes:
        st.warning("尚無啟用工段，請先到 13 系統設定新增。")
    with st.form("start_work_form"):
        employee_map = {f"{e['employee_id']}｜{e['employee_name']}": e["employee_id"] for e in employees}
        wo_map = {f"{w['work_order_no']}｜{w.get('product_name') or ''}": w["work_order_no"] for w in work_orders}
        process_map = {f"{p['process_code']}｜{p['process_name']}": p["process_code"] for p in processes}
        employee_label = st.selectbox("人員", list(employee_map.keys()) if employee_map else [])
        wo_label = st.selectbox("製令", list(wo_map.keys()) if wo_map else [])
        process_label = st.selectbox("工段", list(process_map.keys()) if process_map else [])
        submitted = st.form_submit_button("開始作業")
    if submitted:
        if employee_label and wo_label and process_label:
            result = start_work(
                user,
                employee_map[employee_label],
                wo_map[wo_label],
                process_map[process_label],
                idempotency_key=f"start:{uuid.uuid4().hex}",
            )
            render_result(result)
            if result.ok:
                st.rerun()

with active_tab:
    st.subheader("目前進行中")
    active = list_active_records()
    render_result(active, success_text=None)
    rows = active.data or []
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        record_ids = [r["record_id"] for r in rows]
        selected_id = st.selectbox("選擇紀錄", record_ids, format_func=lambda rid: next((f"{r['employee_id']}｜{r['work_order_no']}｜{r['process_name']}｜{r['start_time']}" for r in rows if r['record_id'] == rid), rid))
        col1, col2 = st.columns(2)
        with col1:
            finish_group = st.checkbox("同 group_key 一起完工並平均", value=True)
            if st.button("完工作業", type="primary"):
                render_result(finish_work(user, selected_id, finish_group=finish_group))
                st.rerun()
        with col2:
            reason = st.text_input("刪除原因", value="管理員人工刪除")
            if st.button("刪除紀錄（soft delete + LOG）"):
                render_result(delete_time_record(user, selected_id, reason=reason))
                st.rerun()
    else:
        st.info("目前沒有進行中的作業。")

with today_tab:
    st.subheader("今日明細")
    today = list_time_records({"work_date_from": today_str(), "work_date_to": today_str()}, limit=1000)
    if today.ok and today.data:
        st.dataframe(pd.DataFrame(today.data), use_container_width=True, hide_index=True)
    else:
        st.info("今日尚無資料。")
