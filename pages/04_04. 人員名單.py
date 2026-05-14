# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import pandas as pd
import streamlit as st

try:
    from services.theme_service import apply_theme, render_header
except Exception:
    def apply_theme():
        pass
    def render_header(title: str, subtitle: str = ""):
        st.title(title)
        if subtitle:
            st.caption(subtitle)

from services.crud_table_service import load_employees, save_employees

st.set_page_config(page_title="04. 人員名單", page_icon="👥", layout="wide")
apply_theme()
render_header("04｜人員名單", "人員主檔、在廠狀態、今日出勤勾選、清單編輯、刪除與儲存")

STATE_KEY = "v114_employees_editor"
COLS = [
    "_delete", "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at",
]


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLS:
        if c not in df.columns:
            df[c] = False if c in ["_delete", "is_active", "is_in_factory", "is_today_attendance"] else ""
    return df[COLS]


def _normalize_text(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def _split_paste_line(line: str) -> list[str]:
    line = line.strip()
    if "\t" in line:
        return [x.strip() for x in line.split("\t")]
    if "," in line:
        return [x.strip() for x in line.split(",")]
    # Excel / chat copy sometimes becomes multiple spaces instead of tabs.
    parts = [x.strip() for x in re.split(r"\s{2,}", line) if x.strip()]
    if len(parts) <= 1:
        parts = [x.strip() for x in line.split()]
    return parts


def parse_pasted_employees(raw: str) -> pd.DataFrame:
    """Parse pasted employee data.

    支援：
    - 有標題列：工號、姓名、單位、職稱、備註
    - 無標題列：工號、姓名、單位、職稱、備註
    - 分隔符：Excel Tab、逗號、多個空白
    """
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [_split_paste_line(line) for line in lines]
    if not rows:
        return ensure_cols(pd.DataFrame())

    header_tokens = {"工號", "employee_id", "employee id", "姓名", "name", "員工姓名", "單位", "department", "職稱", "title"}
    first = [str(x).strip().lower() for x in rows[0]]
    has_header = any(x in header_tokens for x in first)

    if has_header:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])
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
            "employee_id": pick("工號", "員工編號", "人員編號", "employee_id", "employee id", "id"),
            "employee_name": pick("姓名", "員工姓名", "人員姓名", "employee_name", "employee name", "name"),
            "department": pick("單位", "部門", "課別", "department", "dept"),
            "title": pick("職稱", "工段", "title", "job title"),
            "is_active": True,
            "is_in_factory": True,
            "is_today_attendance": True,
            "note": pick("備註", "note", "remark", "說明"),
            "created_at": "",
            "updated_at": "",
        })
    else:
        padded = [r + [""] * (5 - len(r)) for r in rows]
        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "employee_id": [r[0] for r in padded],
            "employee_name": [r[1] for r in padded],
            "department": [r[2] for r in padded],
            "title": [r[3] for r in padded],
            "is_active": True,
            "is_in_factory": True,
            "is_today_attendance": True,
            "note": [r[4] for r in padded],
            "created_at": "",
            "updated_at": "",
        })

    for c in ["employee_id", "employee_name", "department", "title", "note"]:
        df[c] = df[c].map(_normalize_text)
    df = df[(df["employee_id"] != "") & (df["employee_name"] != "")].copy()
    return ensure_cols(df)


def reload_data():
    df = load_employees()
    df.insert(0, "_delete", False)
    st.session_state[STATE_KEY] = ensure_cols(df)


if STATE_KEY not in st.session_state:
    reload_data()


tab1, tab2, tab3 = st.tabs(["人員清單編輯", "Excel 匯入", "貼上資料"])

with tab1:
    st.subheader("人員清單編輯 / Editable Employees")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("➕ 新增空白列", use_container_width=True):
        blank = pd.DataFrame([{
            "_delete": False, "id": "", "employee_id": "", "employee_name": "",
            "department": "", "title": "", "is_active": True, "is_in_factory": True,
            "is_today_attendance": True, "note": "", "created_at": "", "updated_at": ""
        }])
        st.session_state[STATE_KEY] = pd.concat([blank, st.session_state[STATE_KEY]], ignore_index=True)
        rerun()
    if c2.button("🗑️ 刪除欄全選", use_container_width=True):
        st.session_state[STATE_KEY]["_delete"] = True
        rerun()
    if c3.button("↩️ 刪除欄取消", use_container_width=True):
        st.session_state[STATE_KEY]["_delete"] = False
        rerun()
    if c4.button("✅ 啟用全選", use_container_width=True):
        st.session_state[STATE_KEY]["is_active"] = True
        rerun()
    if c5.button("⬜ 啟用全取消", use_container_width=True):
        st.session_state[STATE_KEY]["is_active"] = False
        rerun()
    if c6.button("🔄 重新載入", use_container_width=True):
        reload_data()
        rerun()

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("🏭 在廠全選", use_container_width=True):
        st.session_state[STATE_KEY]["is_in_factory"] = True
        rerun()
    if b2.button("🏭 在廠全取消", use_container_width=True):
        st.session_state[STATE_KEY]["is_in_factory"] = False
        rerun()
    if b3.button("📅 今日出勤全選", use_container_width=True):
        st.session_state[STATE_KEY]["is_today_attendance"] = True
        rerun()
    if b4.button("📅 今日出勤全取消", use_container_width=True):
        st.session_state[STATE_KEY]["is_today_attendance"] = False
        rerun()

    st.warning("勾選「刪除 / Delete」後按下儲存，才會真正刪除資料。工號 / Employee ID、姓名 / Name 為必填。")

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
            "employee_id": st.column_config.TextColumn("工號 / Employee ID", required=True, width="medium"),
            "employee_name": st.column_config.TextColumn("姓名 / Name", required=True, width="medium"),
            "department": st.column_config.TextColumn("單位 / Department", width="medium"),
            "title": st.column_config.TextColumn("職稱 / Title", width="medium"),
            "is_active": st.column_config.CheckboxColumn("啟用 / Active", width="small"),
            "is_in_factory": st.column_config.CheckboxColumn("在廠 / In Factory", width="small"),
            "is_today_attendance": st.column_config.CheckboxColumn("今日出勤 / Today", width="small"),
            "note": st.column_config.TextColumn("備註 / Note", width="large"),
            "created_at": st.column_config.TextColumn("建立時間 / Created At", disabled=True, width="medium"),
            "updated_at": st.column_config.TextColumn("更新時間 / Updated At", disabled=True, width="medium"),
        },
        key="employees_data_editor_v117",
    )
    st.session_state[STATE_KEY] = ensure_cols(edited)

    if st.button("💾 儲存人員清單 / Save Employees", type="primary", use_container_width=True):
        result = save_employees(st.session_state[STATE_KEY])
        reload_data()
        st.success(f"儲存完成：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}")
        rerun()

with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    uploaded = st.file_uploader("上傳人員 Excel", type=["xlsx", "xlsm", "xls"])
    if uploaded is not None:
        source_df = pd.read_excel(uploaded)
        st.dataframe(source_df, use_container_width=True)
        st.info("可先確認欄位，再複製到『貼上資料』或『人員清單編輯』處理。")

with tab3:
    st.subheader("貼上資料 / Paste Data")
    st.caption("V1.17 loaded｜貼上後會在預覽表格上方顯示兩個存檔按鈕")
    st.caption("支援格式：工號、姓名、單位、職稱、備註。可從 Excel 直接複製貼上。")
    raw = st.text_area("貼上 Excel 複製資料", height=260, key="employees_paste_raw_v117")

    if raw.strip():
        parsed = parse_pasted_employees(raw)
        if parsed.empty:
            st.error("解析後沒有可儲存資料。請確認至少包含：工號、姓名。")
        else:
            st.success(f"已解析 {len(parsed)} 筆人員資料。請確認下方預覽後，可直接存檔或加入清單編輯。")

            a1, a2 = st.columns(2)
            if a1.button("➕ 加入清單編輯 / Add to Editor", type="secondary", use_container_width=True, key="add_pasted_employees_to_editor_v117"):
                st.session_state[STATE_KEY] = pd.concat([parsed, st.session_state[STATE_KEY]], ignore_index=True)
                st.success("已加入『人員清單編輯』頁，請切回第一個頁籤確認後按儲存。")

            if a2.button("💾 直接儲存貼上資料 / Save Pasted Employees", type="primary", use_container_width=True, key="save_pasted_employees_v117"):
                result = save_employees(parsed)
                reload_data()
                st.success(f"貼上資料已儲存：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}")
                rerun()

            st.markdown("### 解析後資料預覽 / Parsed Preview")
            st.dataframe(
                parsed[["employee_id", "employee_name", "department", "title", "note", "is_active", "is_in_factory", "is_today_attendance"]],
                use_container_width=True,
                height=360,
            )
    else:
        st.info("請先貼上 Excel 資料；貼上後會出現『加入清單編輯』與『直接儲存貼上資料』按鈕。")
