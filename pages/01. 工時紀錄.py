# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from services.theme_service import apply_theme, render_header
from services.master_data_service import load_employees, load_work_orders
from services.time_record_service import get_active_record, get_active_group, start_work, finish_work, today_records
from services.db_service import query_one
from services.table_ui_service import render_table

st.set_page_config(page_title="01. 工時紀錄", page_icon="▶️", layout="wide")
apply_theme()
render_header("01｜工時紀錄", "快速開始、同步作業、暫停、下班、完工｜自動記錄時間與扣除休息")

PROCESS_OPTIONS = ["前置鈑金", "LP改造", "骨架組立", "配電", "模組", "水平", "S.T.", "清潔", "收機", "包機", "Packing", "異常", "設變", "重工", "教育訓練", "IPQC", "其他"]

employees = load_employees(active_only=True, in_factory_only=False)
work_orders = load_work_orders(active_only=True)

if employees.empty or work_orders.empty:
    st.warning("請先到『03. 製令管理』與『04. 人員名單』匯入或新增資料。")
    st.stop()

left, right = st.columns([1.1, 1])
with left:
    st.subheader("開始作業 / Start Work")
    emp_label = st.selectbox("工號 / 姓名｜Employee", employees.apply(lambda r: f"{r['employee_id']}｜{r['employee_name']}", axis=1).tolist())
    emp_id = emp_label.split("｜")[0]
    employee = query_one("SELECT * FROM employees WHERE employee_id=?", (emp_id,))

    wo_label = st.selectbox("製令｜Work Order", work_orders.apply(lambda r: f"{r['work_order']}｜{r.get('part_no','')}｜{r.get('type_name','')}", axis=1).tolist())
    wo_no = wo_label.split("｜")[0]
    work_order = query_one("SELECT * FROM work_orders WHERE work_order=?", (wo_no,))

    process = st.selectbox("工段名稱｜Process", PROCESS_OPTIONS)
    remark = st.text_area("備註｜Remark", height=90)
    auto_pause = st.checkbox("切換不同工段時，自動暫停同人員其他未結束作業｜Auto pause different process", value=True)

    active = get_active_record(emp_id)
    if active:
        group = get_active_group(int(active["id"]))
        st.info(f"目前作業中：{active['process_name']}，同步計時 {len(group)} 筆。開始其中任一不同工段時，舊工段會自動暫停。")

    if st.button("▶ 開始作業 / Start", use_container_width=True):
        rid = start_work(employee, work_order, process, remark, auto_pause_old=auto_pause)
        st.success(f"已開始作業，紀錄編號：{rid}")
        st.rerun()

with right:
    st.subheader("結束目前作業 / Finish Work")
    emp_label2 = st.selectbox("選擇人員｜Employee", employees.apply(lambda r: f"{r['employee_id']}｜{r['employee_name']}", axis=1).tolist(), key="end_emp")
    emp_id2 = emp_label2.split("｜")[0]
    active2 = get_active_record(emp_id2)
    if not active2:
        st.success("此人員目前沒有未結束作業。")
    else:
        group_df = get_active_group(int(active2["id"]))
        st.markdown(
            f"""
<div class="spt-card spt-glow">
<b>目前作業中 / Active Work</b><br>
工段：{active2['process_name']}<br>
同步計時：{len(group_df)} 筆<br>
說明：按下暫停、下班或完工時，會同步結束同一人員、同一天、同一工段的所有未結束計時，並平均分配工時。<br>
</div>
""",
            unsafe_allow_html=True,
        )
        render_table(group_df, "active_parallel_group", editable=False, height=230)
        end_remark = st.text_input("結束備註｜Finish Remark", key="end_remark")
        c1, c2, c3 = st.columns(3)
        if c1.button("⏸ 暫停 / Pause", use_container_width=True):
            n = finish_work(active2["id"], "暫停", end_remark, finish_parallel_group=True)
            st.success(f"已同步暫停 {n} 筆並平均計算工時。")
            st.rerun()
        if c2.button("🏁 完工 / Complete", use_container_width=True):
            n = finish_work(active2["id"], "完工", end_remark, finish_parallel_group=True)
            st.success(f"已同步完工 {n} 筆並平均計算工時。")
            st.rerun()
        if c3.button("🌙 下班 / Off Duty", use_container_width=True):
            n = finish_work(active2["id"], "下班", end_remark, finish_parallel_group=True)
            st.success(f"已同步下班 {n} 筆並平均計算工時。")
            st.rerun()

st.divider()
st.subheader("今日工時紀錄 / Today Records")
df = today_records()
render_table(df, "today_records", editable=False, height=420)
