# -*- coding: utf-8 -*-
from __future__ import annotations
import pandas as pd
import streamlit as st
from services.theme_service import apply_theme, render_header
from services.master_data_service import load_work_orders, upsert_work_order, import_work_orders_df
from services.log_service import write_log

st.set_page_config(page_title="03 製令管理", page_icon="📦", layout="wide")
apply_theme()
render_header("03｜製令管理", "支援 Excel 上傳、貼上資料、手動新增")

TAB_UPLOAD, TAB_PASTE, TAB_MANUAL, TAB_LIST = st.tabs(["Excel 匯入", "貼上資料", "手動新增", "製令清單"])

with TAB_UPLOAD:
    f = st.file_uploader("上傳製令 Excel", type=["xlsx", "xlsm", "xls"])
    if f:
        df = pd.read_excel(f)
        st.dataframe(df.head(50), use_container_width=True)
        if st.button("匯入製令資料", use_container_width=True):
            count = import_work_orders_df(df)
            st.success(f"已匯入 {count} 筆製令資料")
            st.rerun()

with TAB_PASTE:
    st.caption("建議欄位：製令、P/N、Type、組立地點、客戶、備註。也可用英文欄位：work_order, part_no, type_name, assembly_location, customer, note")
    pasted = st.text_area("從 Excel 複製後貼上", height=220)
    if st.button("解析並匯入貼上資料", use_container_width=True) and pasted.strip():
        rows = [line.split("\t") for line in pasted.strip().splitlines()]
        df = pd.DataFrame(rows[1:], columns=rows[0]) if len(rows) > 1 else pd.DataFrame(rows)
        count = import_work_orders_df(df)
        st.success(f"已匯入 {count} 筆")
        st.rerun()

with TAB_MANUAL:
    with st.form("manual_wo"):
        c1, c2, c3 = st.columns(3)
        wo = c1.text_input("製令 *")
        part = c2.text_input("P/N")
        typ = c3.text_input("Type")
        loc = c1.text_input("組立地點")
        cust = c2.text_input("客戶")
        note = c3.text_input("備註")
        ok = st.form_submit_button("儲存製令")
    if ok:
        upsert_work_order({"work_order": wo, "part_no": part, "type_name": typ, "assembly_location": loc, "customer": cust, "note": note})
        write_log("UPSERT_WORK_ORDER", f"新增/更新製令 {wo}", "work_orders", wo)
        st.success("已儲存")
        st.rerun()

with TAB_LIST:
    df = load_work_orders(active_only=False)
    st.dataframe(df, use_container_width=True, hide_index=True)
