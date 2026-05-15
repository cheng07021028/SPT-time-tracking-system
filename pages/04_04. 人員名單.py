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

try:
    from services.security_service import require_module_access
except Exception:
    def require_module_access(module_code: str):
        return True

st.set_page_config(page_title="04. 人員名單", page_icon="👥", layout="wide")
apply_theme()
require_module_access("04_employees")
render_header("04｜人員名單", "人員主檔、在廠狀態、今日出勤勾選、清單編輯、刪除與儲存")

STATE_KEY = "v138_employees_editor"
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


def _normalize_header_name(v) -> str:
    """Normalize pasted/Excel header names for robust mapping."""
    text = "" if pd.isna(v) else str(v)
    text = text.strip().lower()
    for ch in [" ", "\t", "\n", "\r", "_", "-", "－", "—", "/", "／", "\\", ".", "．", "：", ":", "（", "）", "(", ")"]:
        text = text.replace(ch, "")
    return text


def _is_truthy(v) -> bool:
    text = _normalize_text(v).lower()
    if text in ["", "0", "false", "否", "n", "no", "停用", "離職", "不在", "未出勤", "disabled", "inactive"]:
        return False
    return True


def _find_col(source: pd.DataFrame, aliases: list[str]):
    norm_to_col = {_normalize_header_name(c): c for c in source.columns}
    norm_aliases = [_normalize_header_name(a) for a in aliases]
    for alias in norm_aliases:
        if alias in norm_to_col:
            return norm_to_col[alias]
    # Fuzzy contains match for messy Excel headers like「工號 / Employee ID」
    for alias in norm_aliases:
        for norm_col, real_col in norm_to_col.items():
            if alias and (alias in norm_col or norm_col in alias):
                return real_col
    return None


def _pick_series(source: pd.DataFrame, aliases: list[str], default=""):
    col = _find_col(source, aliases)
    if col is None:
        return default
    return source[col]


def _row_looks_like_header(row: list[str], alias_groups: dict[str, list[str]]) -> bool:
    norm_row = {_normalize_header_name(x) for x in row}
    hits = 0
    for aliases in alias_groups.values():
        norm_aliases = {_normalize_header_name(a) for a in aliases}
        if norm_row & norm_aliases:
            hits += 1
    return hits >= 1


def parse_pasted_employees(raw: str) -> tuple[pd.DataFrame, bool, list[str]]:
    """Parse pasted employee data by header names when a header row exists.

    支援有標題列依欄名自動對應，不再依欄位順序硬吃資料。
    可辨識範例：工號、姓名、單位、部門、課別、職稱、工段、啟用、在廠、今日出勤、備註。
    無標題列時才使用預設順序：工號、姓名、單位、職稱、備註。
    """
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [_split_paste_line(line) for line in lines]
    warnings: list[str] = []
    if not rows:
        return ensure_cols(pd.DataFrame()), False, warnings

    alias_groups = {
        "employee_id": ["工號", "員工編號", "人員編號", "employee id", "employee_id", "emp id", "empid", "id", "編號"],
        "employee_name": ["姓名", "員工姓名", "人員姓名", "employee name", "employee_name", "name", "名字"],
        "department": ["單位", "部門", "課別", "廠別", "department", "dept", "section"],
        "title": ["職稱", "職務", "工段", "title", "job title", "position", "作業類別"],
        "note": ["備註", "note", "remark", "remarks", "說明", "memo"],
        "is_active": ["啟用", "active", "is active", "is_active", "在職", "狀態", "有效"],
        "is_in_factory": ["在廠", "在廠內", "in factory", "is in factory", "is_in_factory", "現場", "廠內"],
        "is_today_attendance": ["今日出勤", "今天出勤", "出勤", "today", "attendance", "is_today_attendance", "今日到班"],
    }

    has_header = _row_looks_like_header(rows[0], alias_groups)

    if has_header:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])

        employee_id = _pick_series(source, alias_groups["employee_id"])
        employee_name = _pick_series(source, alias_groups["employee_name"])
        department = _pick_series(source, alias_groups["department"])
        title = _pick_series(source, alias_groups["title"])
        note = _pick_series(source, alias_groups["note"])
        active_series = _pick_series(source, alias_groups["is_active"], default=None)
        factory_series = _pick_series(source, alias_groups["is_in_factory"], default=None)
        today_series = _pick_series(source, alias_groups["is_today_attendance"], default=None)

        if isinstance(employee_id, str):
            warnings.append("找不到『工號』欄位，資料將無法儲存。請確認標題列包含：工號 / 員工編號 / Employee ID。")
        if isinstance(employee_name, str):
            warnings.append("找不到『姓名』欄位，資料將無法儲存。請確認標題列包含：姓名 / 員工姓名 / Name。")

        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "employee_id": employee_id,
            "employee_name": employee_name,
            "department": department,
            "title": title,
            "is_active": True if active_series is None else active_series.map(_is_truthy),
            "is_in_factory": True if factory_series is None else factory_series.map(_is_truthy),
            "is_today_attendance": True if today_series is None else today_series.map(_is_truthy),
            "note": note,
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
        warnings.append("未偵測到標題列，已用預設順序解析：工號、姓名、單位、職稱、備註。")

    for c in ["employee_id", "employee_name", "department", "title", "note"]:
        df[c] = df[c].map(_normalize_text)
    before = len(df)
    df = df[(df["employee_id"] != "") & (df["employee_name"] != "")].copy()
    dropped = before - len(df)
    if dropped > 0:
        warnings.append(f"已略過 {dropped} 筆缺少工號或姓名的資料列。")
    return ensure_cols(df), has_header, warnings

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

    st.caption("效能模式：編輯表格時不會每點一格就重新運算；只有按下儲存才會寫入與重新載入。")
    with st.form("employees_editor_batch_form", clear_on_submit=False):
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
            key="employees_data_editor_v138",
        )
        submitted_employees = st.form_submit_button("💾 儲存人員清單 / Save Employees", type="primary", use_container_width=True)

    if submitted_employees:
        st.session_state[STATE_KEY] = ensure_cols(edited)
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
    st.caption("V1.38 loaded｜支援『有標題列』貼上，系統會依標題列名稱自動對應欄位。")
    st.caption("有標題列支援：工號、姓名、單位、部門、課別、職稱、工段、啟用、在廠、今日出勤、備註。無標題列時才用預設順序。")
    raw = st.text_area("貼上 Excel 複製資料", height=260, key="employees_paste_raw_v138")

    if raw.strip():
        parsed, has_header, parse_warnings = parse_pasted_employees(raw)
        if parsed.empty:
            st.error("解析後沒有可儲存資料。請確認至少包含：工號、姓名。")
        else:
            if has_header:
                st.success(f"已偵測到標題列，並依標題列自動對應欄位；已解析 {len(parsed)} 筆人員資料。")
            else:
                st.success(f"已解析 {len(parsed)} 筆人員資料。請確認下方預覽後，可直接存檔或加入清單編輯。")
            for msg in parse_warnings:
                st.warning(msg)

            a1, a2 = st.columns(2)
            if a1.button("➕ 加入清單編輯 / Add to Editor", type="secondary", use_container_width=True, key="add_pasted_employees_to_editor_v138"):
                st.session_state[STATE_KEY] = pd.concat([parsed, st.session_state[STATE_KEY]], ignore_index=True)
                st.success("已加入『人員清單編輯』頁，請切回第一個頁籤確認後按儲存。")

            if a2.button("💾 直接儲存貼上資料 / Save Pasted Employees", type="primary", use_container_width=True, key="save_pasted_employees_v138"):
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
        st.info("請先貼上 Excel 資料。建議包含標題列，例如：工號、姓名、單位、職稱、備註。")
