# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import login_logs_df, require_module_access
from services.table_ui_service import render_table

st.set_page_config(page_title="11. 登入紀錄", page_icon="🛡️", layout="wide")
apply_theme()
require_module_access("11_login_logs")
render_header("11｜登入紀錄", "登入、登出、閒置自動登出、權限不足與安全事件查詢")

limit = st.slider("讀取筆數 / Limit", 100, 5000, 1000, step=100)
df = login_logs_df(limit)

if df.empty:
    st.info("目前沒有登入紀錄。")
else:
    c1, c2, c3 = st.columns(3)
    event = c1.multiselect("事件 / Event", sorted(df["event_type"].dropna().unique().tolist()))
    result = c2.multiselect("結果 / Result", sorted(df["result"].dropna().unique().tolist()))
    keyword = c3.text_input("關鍵字 / Keyword")
    view = df.copy()
    if event:
        view = view[view["event_type"].isin(event)]
    if result:
        view = view[view["result"].isin(result)]
    if keyword:
        mask = view.astype(str).apply(lambda s: s.str.contains(keyword, case=False, na=False)).any(axis=1)
        view = view[mask]
    render_table(view, "security_login_logs", editable=False, height=620)
