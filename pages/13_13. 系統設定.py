# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from services.auth_service import require_module, current_user
from services.app_config import DEFAULT_PROCESS_OPTIONS, DEFAULT_REST_PERIODS
from services.ui import apply_theme, page_header, configurable_editor, df_to_rows
from services.permanent_store import load_records, save_records, log_event

MODULE = "13_system_settings"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)

st.subheader("工段 / 作業項目設定")
proc_rows = load_records("13_system_settings_process", DEFAULT_PROCESS_OPTIONS)
pdf = pd.DataFrame(proc_rows)
for c in ["工段分類", "工段", "啟用", "排序", "備註"]:
    if c not in pdf.columns: pdf[c] = ""
ped = configurable_editor(MODULE, "process", pdf[["工段分類", "工段", "啟用", "排序", "備註"]], allow_edit=True, allow_delete=True)
if st.button("套用並永久儲存工段設定", type="primary"):
    require_module(MODULE, "edit")
    save_records("13_system_settings_process", df_to_rows(ped), current_user(), "save_process_settings")
    log_event(MODULE, "save_process_settings", current_user(), "OK", f"{len(ped)} rows")
    st.success("工段設定已永久保存。")
    st.rerun()

st.divider()
st.subheader("休息時間設定 / Rest Periods")
rest_rows = load_records("13_system_settings_rest", DEFAULT_REST_PERIODS)
rdf = pd.DataFrame(rest_rows)
for c in ["名稱", "開始", "結束", "啟用", "備註"]:
    if c not in rdf.columns: rdf[c] = ""
red = configurable_editor(MODULE, "rest", rdf[["名稱", "開始", "結束", "啟用", "備註"]], allow_edit=True, allow_delete=True)
if st.button("套用並永久儲存休息時間", type="primary"):
    require_module(MODULE, "edit")
    save_records("13_system_settings_rest", df_to_rows(red), current_user(), "save_rest_periods")
    log_event(MODULE, "save_rest_periods", current_user(), "OK", f"{len(red)} rows")
    st.success("休息時間已永久保存，工時計算會讀取此唯一設定。")
    st.rerun()
