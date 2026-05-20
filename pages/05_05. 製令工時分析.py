# -*- coding: utf-8 -*-
import pandas as pd
import plotly.express as px
import streamlit as st

from services.auth_service import require_module
from services.ui import apply_theme, page_header, excel_download_button
from services.permanent_store import load_records

MODULE = "05_analysis"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)
rows = load_records("02_history", []) + load_records("01_time_records", [])
df = pd.DataFrame(rows)
if df.empty:
    st.info("目前尚無工時資料。")
else:
    for c in ["製令", "工段", "工號", "姓名", "工時小計"]:
        if c not in df.columns: df[c] = ""
    def to_sec(x):
        try:
            h,m,s = [int(v) for v in str(x).split(":")[:3]]
            return h*3600+m*60+s
        except Exception:
            return 0
    df["秒數"] = df["工時小計"].map(to_sec)
    q = st.text_input("搜尋製令 / 工段 / 人員")
    if q:
        mask = df.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
        df = df[mask]
    summary = df.groupby(["製令", "工段"], dropna=False)["秒數"].sum().reset_index()
    summary["工時(H)"] = (summary["秒數"] / 3600).round(2)
    st.dataframe(summary, use_container_width=True, hide_index=True)
    if not summary.empty:
        st.plotly_chart(px.bar(summary, x="製令", y="工時(H)", color="工段", title="製令 / 工段工時分析"), use_container_width=True)
    excel_download_button(summary, "work_order_analysis.xlsx")
