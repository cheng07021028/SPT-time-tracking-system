from __future__ import annotations

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.work_order_service import create_work_order, list_work_orders, soft_delete_work_order, update_work_order
from spt_core.ui import render_result, setup_page

setup_page("03 製令管理")
init_db()
user = require_login()

st.title("03. 製令管理")

with st.expander("新增製令", expanded=True):
    with st.form("create_wo"):
        work_order_no = st.text_input("製令號")
        model = st.text_input("機種 / 型號")
        product_name = st.text_input("品名")
        planned_qty = st.number_input("預計數量", min_value=0.0, value=0.0)
        process_flow_text = st.text_input("製程順序（逗號分隔，例如 DEW,ASM,TEST,PACK）")
        submitted = st.form_submit_button("新增製令")
    if submitted:
        flow = [x.strip().upper() for x in process_flow_text.split(",") if x.strip()]
        render_result(create_work_order(user, work_order_no, model, product_name, planned_qty, flow))
        st.rerun()

st.subheader("製令清單")
result = list_work_orders(active_only=False)
rows = result.data or []
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    selected = st.selectbox("選擇製令", [r["work_order_no"] for r in rows])
    col1, col2 = st.columns(2)
    with col1:
        status = st.selectbox("狀態", ["open", "running", "closed", "hold"], key="wo_status")
        if st.button("更新狀態"):
            render_result(update_work_order(user, selected, status=status))
            st.rerun()
    with col2:
        reason = st.text_input("刪除原因", value="管理員人工刪除", key="wo_delete_reason")
        if st.button("刪除未使用製令"):
            render_result(soft_delete_work_order(user, selected, reason=reason))
            st.rerun()
else:
    st.info("尚無製令。")
