# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from services.auth_service import require_module, current_user
from services.ui import apply_theme, page_header, excel_download_button, delete_by_date_range_jsonl
from services.permanent_store import read_jsonl, system_path, log_event

MODULE = "06_logs"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)
path = system_path("audit_logs.jsonl")
df = pd.DataFrame(read_jsonl(path))
if df.empty:
    st.info("目前尚無 LOG。")
else:
    c1,c2,c3 = st.columns(3)
    start = c1.date_input("開始日期").strftime("%Y-%m-%d")
    end = c2.date_input("結束日期").strftime("%Y-%m-%d")
    q = c3.text_input("關鍵字")
    view = df.copy()
    if "時間" in view.columns:
        view = view[(view["時間"].astype(str).str[:10] >= start) & (view["時間"].astype(str).str[:10] <= end)]
    if q:
        view = view[view.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)]
    st.dataframe(view, use_container_width=True, hide_index=True)
    excel_download_button(view, "system_logs.xlsx")
    if st.button("刪除日期區間 LOG", type="primary"):
        require_module(MODULE, "delete")
        n = delete_by_date_range_jsonl(path, start, end)
        log_event(MODULE, "delete_logs", current_user(), "OK", f"deleted {n}")
        st.success(f"已刪除 {n} 筆。")
        st.rerun()
