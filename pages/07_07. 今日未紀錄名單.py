# -*- coding: utf-8 -*-
from datetime import date
import pandas as pd
import streamlit as st

from services.auth_service import require_module
from services.ui import apply_theme, page_header, excel_download_button
from services.permanent_store import load_records

MODULE = "07_missing"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)
today = st.date_input("日期", value=date.today()).strftime("%Y-%m-%d")
emps = pd.DataFrame(load_records("04_employees", []))
trs = pd.DataFrame(load_records("01_time_records", []))
if emps.empty:
    st.info("請先在 04 人員名單建立資料。")
else:
    for c in ["工號", "姓名", "單位", "今日出勤"]:
        if c not in emps.columns: emps[c] = ""
    working = emps[emps["今日出勤"].astype(str).str.lower().isin(["true","1","yes","是","出勤","y"])]
    if working.empty:
        working = emps[emps.get("在職", "").astype(str).str.lower().isin(["true","1","yes","是","在職","y"])] if "在職" in emps.columns else emps
    recorded_ids = set()
    if not trs.empty and "日期" in trs.columns and "工號" in trs.columns:
        recorded_ids = set(trs[trs["日期"].astype(str).str[:10] == today]["工號"].astype(str))
    missing = working[~working["工號"].astype(str).isin(recorded_ids)]
    st.metric("今日未紀錄人數", len(missing))
    st.dataframe(missing, use_container_width=True, hide_index=True)
    excel_download_button(missing, "missing_today.xlsx")
