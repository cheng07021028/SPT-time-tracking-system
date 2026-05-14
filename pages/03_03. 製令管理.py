# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.master_data_service import load_work_orders, upsert_work_order, import_work_orders_df, save_work_orders_df
from services.log_service import write_log
from services.table_ui_service import render_table

st.set_page_config(page_title="03. 製令管理", page_icon="📦", layout="wide")
apply_theme()
render_header("03｜製令管理", "支援 Excel 上傳、貼上資料、手動新增、清單編輯與儲存")


def parse_pasted_table(text: str) -> pd.DataFrame:
    text = (text or "").strip()
    if not text:
        return pd.DataFrame()
    delimiter = "\t" if "\t" in text else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [[cell.strip() for cell in row] for row in reader if any(str(cell).strip() for cell in row)]
    if not rows:
        return pd.DataFrame()
    first = rows[0]
    known_headers = {"製令", "P/N", "Type", "組立地點", "客戶", "備註", "work_order", "part_no", "type_name", "assembly_location", "customer", "note"}
    has_header = any(str(x).strip() in known_headers for x in first)
    if has_header:
        headers = [str(x).strip() or f"欄位{i+1}" for i, x in enumerate(first)]
        data_rows = rows[1:]
    else:
        max_cols = max(len(r) for r in rows)
        headers = ["製令", "P/N", "Type", "組立地點", "客戶", "備註"][:max_cols]
        if len(headers) < max_cols:
            headers += [f"欄位{i+1}" for i in range(len(headers), max_cols)]
        data_rows = rows
    max_cols = max([len(headers)] + [len(r) for r in data_rows])
    if len(headers) < max_cols:
        headers += [f"欄位{i+1}" for i in range(len(headers), max_cols)]
    elif len(headers) > max_cols:
        headers = headers[:max_cols]
    normalized = []
    for row in data_rows:
        row = list(row[:max_cols]) + [""] * max(0, max_cols - len(row))
        normalized.append(row)
    return pd.DataFrame(normalized, columns=headers)


TAB_UPLOAD, TAB_PASTE, TAB_MANUAL, TAB_LIST = st.tabs(["Excel 匯入", "貼上資料", "手動新增", "製令清單編輯"])

with TAB_UPLOAD:
    f = st.file_uploader("上傳製令 Excel / Upload Work Order Excel", type=["xlsx", "xlsm", "xls"])
    if f:
        df = pd.read_excel(f).fillna("")
        st.dataframe(df.head(50), use_container_width=True)
        if st.button("匯入製令資料 / Import", use_container_width=True):
            count = import_work_orders_df(df)
            st.success(f"已匯入 {count} 筆製令資料")
            st.rerun()

with TAB_PASTE:
    st.caption("建議欄位：製令、P/N、Type、組立地點、客戶、備註。英文欄位：work_order, part_no, type_name, assembly_location, customer, note")
    pasted = st.text_area("從 Excel 複製後貼上 / Paste from Excel", height=220)
    if st.button("解析並匯入貼上資料 / Parse and Import", use_container_width=True):
        df = parse_pasted_table(pasted)
        if df.empty:
            st.warning("沒有可匯入的資料，請先從 Excel 複製資料後貼上。")
        else:
            st.dataframe(df.head(50), use_container_width=True, hide_index=True)
            count = import_work_orders_df(df)
            st.success(f"已匯入 {count} 筆")
            st.rerun()

with TAB_MANUAL:
    with st.form("manual_wo"):
        c1, c2, c3 = st.columns(3)
        wo = c1.text_input("製令 * / Work Order")
        part = c2.text_input("P/N / Part No.")
        typ = c3.text_input("Type / Type")
        loc = c1.text_input("組立地點 / Assembly Location")
        cust = c2.text_input("客戶 / Customer")
        note = c3.text_input("備註 / Note")
        ok = st.form_submit_button("儲存製令 / Save")
    if ok:
        if not wo.strip():
            st.warning("請先輸入製令。")
        else:
            upsert_work_order({"work_order": wo, "part_no": part, "type_name": typ, "assembly_location": loc, "customer": cust, "note": note})
            write_log("UPSERT_WORK_ORDER", f"新增/更新製令 {wo}", "work_orders", wo)
            st.success("已儲存")
            st.rerun()

with TAB_LIST:
    df = load_work_orders(active_only=False)
    editable_cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    if not df.empty:
        df = df[[c for c in editable_cols if c in df.columns]]
    edited = render_table(df, "work_orders", editable=True, disabled=["id", "created_at", "updated_at"], key="work_order_editor", height=560)
    if edited is not None and st.button("💾 儲存製令清單 / Save Work Orders", use_container_width=True):
        count = save_work_orders_df(edited)
        st.success(f"已儲存 {count} 筆製令資料。")
        st.rerun()
