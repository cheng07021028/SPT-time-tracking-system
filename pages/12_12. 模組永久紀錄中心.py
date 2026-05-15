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
from services.security_service import require_module_access
from services.table_ui_service import render_table

st.set_page_config(page_title="12. 模組永久紀錄中心", page_icon="🗂️", layout="wide")
apply_theme()
require_module_access("12_module_persistence", "can_view")
render_header("12｜模組永久紀錄中心", "每個模組獨立 records、settings、audit 與 history 時間戳備份")

# V2.01：進頁面時先重建索引，避免新增模組 12/13 後狀態表仍停留舊清單。
try:
    protect_gitignore_rules()
    rebuild_global_index()
except Exception as exc:
    st.warning(f"模組永久索引重建時發生警告，但不影響查詢：{exc}")

st.markdown("### 模組獨立永久紀錄 / Independent Permanent Module Records")
st.info("每個模組都有獨立 records.json、settings.json、audit.jsonl 與 history 時間戳備份。這些檔案位於 data/persistent_modules/，更新程式模組時不應覆蓋。")

c1, c2, c3 = st.columns(3)
username = st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM"))
with c1:
    if st.button("建立 / 補齊永久資料夾 / Bootstrap", use_container_width=True):
        protect_gitignore_rules()
        result = bootstrap_module_persistence(username=username)
        st.success("已建立或補齊模組永久資料夾與設定索引")
        st.json(result)
        st.rerun()
with c2:
    if st.button("匯出全部模組紀錄 / Export All", use_container_width=True):
        result = export_all_modules(username=username)
        st.success("全部模組紀錄已匯出到 data/persistent_modules")
        st.json({k: v.get("counts", {}) for k, v in result.items()})
        st.rerun()
with c3:
    if st.button("重建全域索引 / Rebuild Index", use_container_width=True):
        result = rebuild_global_index()
        st.success("全域索引已重建")
        st.json(result)
        st.rerun()

st.divider()
st.markdown("### 模組狀態 / Module Status")
status_df = pd.DataFrame(get_module_status())

# 明確檢查 12，避免使用者看到狀態表缺漏卻不知道原因。
if not status_df.empty and not (status_df["模組代碼 / Module Code"].astype(str) == "12_module_persistence").any():
    st.error("狀態表缺少 12_module_persistence。請覆蓋 V2.01 的 services/module_persistence_service.py 後重新啟動 Streamlit。")
else:
    st.caption("V2.01：已補齊 12｜模組永久紀錄中心、13｜系統設定與新增模組狀態。")

render_table(status_df, "12_module_persistence_status", editable=False, height=460)

st.divider()
st.markdown("### 單一模組匯出 / Export Single Module")
module_options = {f'{v["name_zh"]} / {v["name_en"]} ({k})': k for k, v in MODULE_TABLE_MAP.items()}
selected_label = st.selectbox("選擇模組 / Select Module", list(module_options.keys()))
if st.button("匯出選定模組 / Export Selected Module", use_container_width=True):
    module_code = module_options[selected_label]
    result = export_module_records(module_code, username=username)
    st.success("已匯出模組永久紀錄")
    st.json({"module_code": module_code, "counts": result.get("counts", {}), "exported_at": result.get("exported_at", "")})
    st.rerun()
