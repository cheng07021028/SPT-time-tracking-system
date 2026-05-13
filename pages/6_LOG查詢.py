# -*- coding: utf-8 -*-
from __future__ import annotations
import streamlit as st
from services.theme_service import apply_theme, render_header
from services.log_service import load_logs

st.set_page_config(page_title="06 LOG 查詢", page_icon="🧾", layout="wide")
apply_theme()
render_header("06｜LOG 查詢", "人員動作、系統事件、異常紀錄追溯")

limit = st.slider("讀取筆數", 100, 3000, 500, step=100)
df = load_logs(limit)
if not df.empty:
    c1, c2, c3 = st.columns(3)
    action = c1.multiselect("動作類型", sorted(df["action_type"].dropna().unique().tolist()))
    level = c2.multiselect("等級", sorted(df["level"].dropna().unique().tolist()))
    keyword = c3.text_input("關鍵字")
    view = df.copy()
    if action:
        view = view[view["action_type"].isin(action)]
    if level:
        view = view[view["level"].isin(level)]
    if keyword:
        mask = view.astype(str).apply(lambda s: s.str.contains(keyword, case=False, na=False)).any(axis=1)
        view = view[mask]
    st.dataframe(view, use_container_width=True, hide_index=True)
else:
    st.info("尚無 LOG")
