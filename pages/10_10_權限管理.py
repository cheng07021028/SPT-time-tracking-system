from __future__ import annotations

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.user_service import create_user, list_users, reset_password, set_user_active
from spt_core.ui import render_result, setup_page

setup_page("10 權限管理")
init_db()
user = require_login()

st.title("10. 權限管理")

with st.expander("新增使用者", expanded=True):
    with st.form("create_user"):
        username = st.text_input("帳號")
        display_name = st.text_input("顯示名稱")
        password = st.text_input("初始密碼", type="password")
        role = st.selectbox("角色", ["operator", "supervisor", "admin"])
        submitted = st.form_submit_button("新增使用者")
    if submitted:
        render_result(create_user(user, username, display_name, password, role))
        st.rerun()

result = list_users(user)
render_result(result, success_text=None)
rows = result.data or []
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    selected = st.selectbox("選擇帳號", [r["username"] for r in rows])
    c1, c2 = st.columns(2)
    with c1:
        new_password = st.text_input("新密碼", type="password")
        if st.button("重設密碼"):
            render_result(reset_password(user, selected, new_password))
    with c2:
        active = st.checkbox("啟用", value=True)
        if st.button("更新帳號狀態"):
            render_result(set_user_active(user, selected, active))
            st.rerun()
