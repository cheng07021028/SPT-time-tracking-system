from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.process_service import list_processes, upsert_process
from spt_core.services.settings_service import list_settings, set_setting
from spt_core.ui import render_result, setup_page
from spt_core.utils import json_loads

setup_page("13 系統設定")
init_db()
user = require_login()

st.title("13. 系統設定")
st.caption("Service 層不依賴 Streamlit；本頁只負責 UI 顯示與呼叫 service。")

settings_tab, process_tab = st.tabs(["系統參數", "工段設定"])

with settings_tab:
    st.subheader("系統參數")
    result = list_settings(user)
    render_result(result, success_text=None)
    rows = result.data or []
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("### 更新設定")
    key = st.selectbox("設定鍵", ["timezone", "enable_group_average", "auto_pause_different_group", "break_windows", "default_query_limit"])
    current = next((r.get("parsed_value") for r in rows if r.get("setting_key") == key), "")
    value_text = st.text_area("設定值 JSON", value=json.dumps(current, ensure_ascii=False, indent=2))
    if st.button("儲存設定"):
        try:
            value = json.loads(value_text)
        except Exception as exc:
            st.error(f"JSON 格式錯誤：{exc}")
        else:
            render_result(set_setting(user, key, value))
            st.rerun()

with process_tab:
    st.subheader("工段設定")
    processes = list_processes(active_only=False).data or []
    if processes:
        st.dataframe(pd.DataFrame(processes), use_container_width=True, hide_index=True)
    with st.form("process_form"):
        process_code = st.text_input("工段代碼")
        process_name = st.text_input("工段名稱")
        sort_order = st.number_input("排序", value=0, step=1)
        active = st.checkbox("啟用", value=True)
        allow_parallel = st.checkbox("允許平行作業", value=True)
        allow_group_average = st.checkbox("允許群組平均", value=True)
        standard_minutes = st.number_input("標準工時（分鐘，可 0）", value=0.0)
        submitted = st.form_submit_button("儲存工段")
    if submitted:
        render_result(upsert_process(user, process_code, process_name, int(sort_order), active, allow_parallel, allow_group_average, float(standard_minutes)))
        st.rerun()
