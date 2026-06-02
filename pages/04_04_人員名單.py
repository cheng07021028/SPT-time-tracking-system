from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.employee_service import create_employee, list_employees, soft_delete_employee, update_employee
from spt_core.ui import render_result, setup_page

setup_page("04 人員名單")
init_db()
user = require_login()

st.title("04. 人員名單")

with st.expander("新增人員", expanded=True):
    with st.form("create_employee"):
        employee_id = st.text_input("工號")
        employee_name = st.text_input("姓名")
        department = st.text_input("部門", value="製造部")
        team = st.text_input("班別 / 組別")
        role = st.text_input("職務")
        permission_group = st.selectbox("預設權限群組", ["operator", "supervisor", "admin"])
        submitted = st.form_submit_button("新增人員")
    if submitted:
        key = f"employee:create:{employee_id}:{uuid.uuid4().hex}"
        render_result(create_employee(user, employee_id, employee_name, department, team, role, permission_group, idempotency_key=key))
        st.rerun()

st.subheader("人員清單")
rows = list_employees(active_only=False).data or []
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    selected = st.selectbox("選擇人員", [r["employee_id"] for r in rows])
    col1, col2 = st.columns(2)
    with col1:
        active = st.checkbox("啟用", value=True)
        if st.button("更新啟用狀態"):
            render_result(update_employee(user, selected, active=active))
            st.rerun()
    with col2:
        reason = st.text_input("停用 / 刪除原因", value="管理員人工停用")
        if st.button("停用並 soft delete"):
            render_result(soft_delete_employee(user, selected, reason=reason))
            st.rerun()
else:
    st.info("尚無人員。")
