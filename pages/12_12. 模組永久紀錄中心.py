# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.module_persistence_service import (
    MODULE_TABLE_MAP,
    bootstrap_module_persistence,
    export_all_modules,
    export_module_records,
    get_module_status,
    protect_gitignore_rules,
    rebuild_global_index,
)

try:
    from services.security_service import require_login, require_permission
except Exception:
    require_login = None
    require_permission = None

apply_theme()
if require_login:
    require_login()
if require_permission:
    require_permission("09_persistence", "can_view")

render_header("12", "模組永久紀錄中心", "每個模組獨立 records、settings、audit 與 history 時間戳備份")

st.markdown("### 模組獨立永久紀錄 / Independent Permanent Module Records")
st.info("每個模組都有獨立 records.json、settings.json、audit.jsonl 與 history 時間戳備份。這些檔案位於 data/persistent_modules/，更新程式模組時不應覆蓋。")

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("建立永久資料夾 / Bootstrap", use_container_width=True):
        protect_gitignore_rules()
        result = bootstrap_module_persistence(username=st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM")))
        st.success("已建立模組永久資料夾與設定索引")
        st.json(result)
with c2:
    if st.button("匯出全部模組紀錄 / Export All", use_container_width=True):
        result = export_all_modules(username=st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM")))
        st.success("全部模組紀錄已匯出到 data/persistent_modules")
        st.json({k: v.get("counts", {}) for k, v in result.items()})
with c3:
    if st.button("重建全域索引 / Rebuild Index", use_container_width=True):
        result = rebuild_global_index()
        st.success("全域索引已重建")
        st.json(result)

st.divider()
st.markdown("### 模組狀態 / Module Status")
status_df = pd.DataFrame(get_module_status())
st.dataframe(status_df, use_container_width=True, hide_index=True, height=420)

st.divider()
st.markdown("### 單一模組匯出 / Export Single Module")
module_options = {f'{v["name_zh"]} / {v["name_en"]} ({k})': k for k, v in MODULE_TABLE_MAP.items()}
selected_label = st.selectbox("選擇模組 / Select Module", list(module_options.keys()))
if st.button("匯出選定模組 / Export Selected Module", use_container_width=True):
    module_code = module_options[selected_label]
    result = export_module_records(module_code, username=st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM")))
    if result.get("ok"):
        st.success("已匯出模組永久紀錄")
    else:
        st.error(result.get("message", "匯出失敗"))
    st.json(result)
