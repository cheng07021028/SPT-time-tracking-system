# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from services.auth_service import require_module
from services.ui import apply_theme, page_header, excel_download_button
from services.permanent_store import load_records

MODULE = "08_daily_hours"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)
rows = load_records("02_history", []) + load_records("01_time_records", [])
df = pd.DataFrame(rows)
if df.empty:
    st.info("目前尚無工時資料。")
else:
    for c in ["日期", "工號", "姓名", "單位", "工時小計"]:
        if c not in df.columns: df[c] = ""
    def to_sec(x):
        try:
            h,m,s = [int(v) for v in str(x).split(":")[:3]]
            return h*3600+m*60+s
        except Exception:
            return 0
    df["秒數"] = df["工時小計"].map(to_sec)
    c1,c2,c3 = st.columns(3)
    emp = c1.text_input("工號 / 姓名")
    unit = c2.text_input("單位")
    dt = c3.text_input("日期包含", value="")
    view = df.copy()
    if emp:
        view = view[view[["工號","姓名"]].astype(str).apply(lambda col: col.str.contains(emp, case=False, na=False)).any(axis=1)]
    if unit and "單位" in view.columns:
        view = view[view["單位"].astype(str).str.contains(unit, case=False, na=False)]
    if dt:
        view = view[view["日期"].astype(str).str.contains(dt, case=False, na=False)]
    summary = view.groupby(["日期", "工號", "姓名"], dropna=False)["秒數"].sum().reset_index()
    summary["每日工時"] = summary["秒數"].map(lambda s: f"{int(s)//3600:02d}:{(int(s)%3600)//60:02d}:{int(s)%60:02d}")
    summary = summary.drop(columns=["秒數"])
    st.dataframe(summary, use_container_width=True, hide_index=True)
    excel_download_button(summary, "daily_hours.xlsx")
