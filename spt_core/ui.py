from __future__ import annotations

import streamlit as st

from .result import Result


def setup_page(title: str) -> None:
    st.set_page_config(page_title=title, page_icon="⏱️", layout="wide")
    st.markdown(
        """
        <style>
        .stApp { background: radial-gradient(circle at top left, #0B2A44 0, #06111F 35%, #030915 100%); }
        div[data-testid="stMetric"] { border: 1px solid rgba(0,213,255,.25); border-radius: 16px; padding: 12px; background: rgba(5,28,45,.55); }
        .spt-card { border: 1px solid rgba(0,213,255,.25); border-radius: 16px; padding: 16px; background: rgba(5,28,45,.55); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_result(result: Result, success_text: str | None = "完成") -> None:
    if result.ok:
        if success_text is not None and (result.message or success_text):
            st.success(result.message or success_text)
        for warning in result.warnings:
            st.warning(warning)
    else:
        st.error(result.message or "操作失敗")
        for error in result.errors:
            st.caption(error)
