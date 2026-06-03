from __future__ import annotations

import uuid

import streamlit as st

from .services.user_service import authenticate
from .ui import render_result


def current_user() -> dict | None:
    return st.session_state.get("spt_user")


def login_form() -> None:
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        submitted = st.form_submit_button("登入")
    if submitted:
        session_id = st.session_state.setdefault("spt_session_id", uuid.uuid4().hex)
        result = authenticate(username, password, session_id=session_id)
        render_result(result)
        if result.ok:
            st.session_state["spt_user"] = result.data
            st.rerun()


def require_login() -> dict:
    user = current_user()
    if not user:
        st.warning("請先回首頁登入。")
        st.stop()
    return user


def logout_button() -> None:
    cols = st.columns([1, 5])
    with cols[0]:
        if st.button("登出"):
            st.session_state.pop("spt_user", None)
            st.rerun()
