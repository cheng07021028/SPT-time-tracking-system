# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

try:
    from services.theme_service import apply_theme, render_header
except Exception:
    def apply_theme(): pass
    def render_header(title: str, subtitle: str = ""):
        st.title(title)
        if subtitle: st.caption(subtitle)

from services.crud_table_service import load_work_orders, save_work_orders

st.set_page_config(page_title="03. 製令管理", page_icon="📋", layout="wide")
apply_theme()
render_header("03｜製令管理", "Excel 匯入、貼上資料、手動新增、頁面編輯、刪除、全選與存檔")

STATE_KEY = "v114_work_orders_editor"
COLS = ["_delete", "id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]

def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()

def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLS:
        if c not in df.columns:
            df[c] = False if c in ["_delete", "is_active"] else ""
    return df[COLS]


def _normalize_text(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

def parse_pasted_work_orders(raw: str) -> pd.DataFrame:
    """Parse tab/comma pasted work order data into editable DB columns.

    支援兩種格式：
    1. 有標題列：製令 / work_order / P/N / part_no / Type / 客戶...
    2. 無標題列：依序視為 製令、P/N、機型、組立地點、客戶、備註
    """
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = []
    for line in lines:
        if "\t" in line:
            parts = [x.strip() for x in line.split("\t")]
        else:
            parts = [x.strip() for x in line.split(",")]
        rows.append(parts)
    if not rows:
        return ensure_cols(pd.DataFrame())

    header_tokens = {"製令", "工單", "工令", "work_order", "work order", "wo", "mo", "p/n", "part", "type", "機型", "客戶", "customer"}
    first = [x.strip().lower() for x in rows[0]]
    has_header = any(x in header_tokens for x in first)

    if has_header:
        source = pd.DataFrame(rows[1:], columns=rows[0])
        lower_map = {str(c).strip().lower(): c for c in source.columns}
        def pick(*names):
            for name in names:
                key = name.strip().lower()
                if key in lower_map:
                    return source[lower_map[key]]
            return ""
        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": pick("製令", "工單", "工令", "製令號碼", "work_order", "work order", "wo", "mo"),
            "part_no": pick("p/n", "pn", "part_no", "part no", "料號"),
            "type_name": pick("type", "type_name", "機型", "型號"),
            "assembly_location": pick("組立地點", "assembly_location", "assembly location", "地點"),
            "customer": pick("客戶", "customer", "client"),
            "note": pick("備註", "note", "remark", "說明"),
            "is_active": True,
            "created_at": "",
            "updated_at": "",
        })
    else:
        padded = [r + [""] * (6 - len(r)) for r in rows]
        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": [r[0] for r in padded],
            "part_no": [r[1] for r in padded],
            "type_name": [r[2] for r in padded],
            "assembly_location": [r[3] for r in padded],
            "customer": [r[4] for r in padded],
            "note": [r[5] for r in padded],
            "is_active": True,
            "created_at": "",
            "updated_at": "",
        })
    for c in ["work_order", "part_no", "type_name", "assembly_location", "customer", "note"]:
        df[c] = df[c].map(_normalize_text)
    df = df[df["work_order"] != ""].copy()
    return ensure_cols(df)

def reload_data():
    df = load_work_orders()
    df.insert(0, "_delete", False)
    st.session_state[STATE_KEY] = ensure_cols(df)

if STATE_KEY not in st.session_state:
    reload_data()

tab1, tab2, tab3 = st.tabs(["製令清單編輯", "Excel 匯入", "貼上資料"])

with tab1:
    st.subheader("製令清單編輯 / Editable Work Orders")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("➕ 新增空白列", use_container_width=True):
        blank = pd.DataFrame([{
            "_delete": False, "id": "", "work_order": "", "part_no": "", "type_name": "",
            "assembly_location": "", "customer": "", "note": "", "is_active": True,
            "created_at": "", "updated_at": ""
        }])
        st.session_state[STATE_KEY] = pd.concat([blank, st.session_state[STATE_KEY]], ignore_index=True)
        rerun()
    if c2.button("✅ 啟用全選", use_container_width=True):
        st.session_state[STATE_KEY]["is_active"] = True
        rerun()
    if c3.button("⬜ 啟用全取消", use_container_width=True):
        st.session_state[STATE_KEY]["is_active"] = False
        rerun()
    if c4.button("🗑️ 刪除欄全選", use_container_width=True):
        st.session_state[STATE_KEY]["_delete"] = True
        rerun()
    if c5.button("↩️ 刪除欄取消", use_container_width=True):
        st.session_state[STATE_KEY]["_delete"] = False
        rerun()
    if c6.button("🔄 重新載入", use_container_width=True):
        reload_data()
        rerun()

    st.warning("勾選「刪除 / Delete」後按下儲存，才會真正刪除資料。製令 / Work Order 為必填。")

    edited = st.data_editor(
        st.session_state[STATE_KEY],
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        height=560,
        column_order=COLS,
        column_config={
            "_delete": st.column_config.CheckboxColumn("刪除 / Delete", width="small"),
            "id": st.column_config.NumberColumn("ID / ID", disabled=True, width="small"),
            "work_order": st.column_config.TextColumn("製令 / Work Order", required=True, width="medium"),
            "part_no": st.column_config.TextColumn("P/N / Part No.", width="medium"),
            "type_name": st.column_config.TextColumn("機型 / Type", width="large"),
            "assembly_location": st.column_config.TextColumn("組立地點 / Assembly Location", width="medium"),
            "customer": st.column_config.TextColumn("客戶 / Customer", width="medium"),
            "note": st.column_config.TextColumn("備註 / Note", width="large"),
            "is_active": st.column_config.CheckboxColumn("啟用 / Active", width="small"),
            "created_at": st.column_config.TextColumn("建立時間 / Created At", disabled=True, width="medium"),
            "updated_at": st.column_config.TextColumn("更新時間 / Updated At", disabled=True, width="medium"),
        },
        key="work_orders_data_editor_v114",
    )
    st.session_state[STATE_KEY] = ensure_cols(edited)

    if st.button("💾 儲存製令清單 / Save Work Orders", type="primary", use_container_width=True):
        result = save_work_orders(st.session_state[STATE_KEY])
        reload_data()
        st.success(f"儲存完成：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}")
        rerun()

with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    uploaded = st.file_uploader("上傳製令 Excel", type=["xlsx", "xlsm", "xls"])
    if uploaded is not None:
        df = pd.read_excel(uploaded)
        st.dataframe(df, use_container_width=True)
        st.info("先確認欄位後，可複製到清單編輯頁新增/修正。下一版可接續做欄位對應直接匯入。")

with tab3:
    st.subheader("貼上資料 / Paste Data")
    raw = st.text_area("貼上 Excel 複製資料", height=220)
    if raw.strip():
        rows = [r.split("\t") for r in raw.splitlines() if r.strip()]
        max_len = max(len(r) for r in rows)
        st.dataframe(pd.DataFrame([r + [""] * (max_len-len(r)) for r in rows]), use_container_width=True)
