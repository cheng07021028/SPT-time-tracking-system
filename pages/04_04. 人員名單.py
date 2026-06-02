# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from io import BytesIO
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

st.set_page_config(page_title="04. 人員名單", page_icon="⧉", layout="wide")
apply_theme()
require_module_access("04_employees")
render_header("04｜人員名單", "人員主檔、在廠狀態、今日出勤勾選、清單編輯、刪除與儲存")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("04", "人員名單")
except Exception:
    _SPT_V40_PAGE_TOKEN = None

STATE_KEY = "v138_employees_editor"
EDITOR_VERSION_KEY = "v253_employees_editor_version"
EDITOR_IGNORE_RETURN_KEY = "v263_employees_ignore_next_editor_return"


def _editor_key() -> str:
    if EDITOR_VERSION_KEY not in st.session_state:
        st.session_state[EDITOR_VERSION_KEY] = 0
    return f"employees_data_editor_v253_{st.session_state[EDITOR_VERSION_KEY]}"


def _refresh_editor_widget() -> None:
    # V63：與 10｜權限管理同樣清除全域 column_settings_service 的 data_editor 草稿。
    # 原因：全域 wrapper 會保存舊畫面，導致批次按鈕已執行但 checkbox 顯示未同步。
    try:
        for _k0 in list(st.session_state.keys()):
            sk = str(_k0)
            if sk.startswith("employees_data_editor_v253_") or "employees_data_editor" in sk:
                st.session_state.pop(_k0, None)
    except Exception:
        pass
    try:
        from services.column_settings_service import clear_editor_draft
        clear_editor_draft("employees_data_editor")
        clear_editor_draft("employees")
    except Exception:
        pass
    st.session_state[EDITOR_IGNORE_RETURN_KEY] = True
    st.session_state[EDITOR_VERSION_KEY] = int(st.session_state.get(EDITOR_VERSION_KEY, 0)) + 1

COLS = [
    "_delete", "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at",
]

# V61：表格實際欄名也改成與 10｜權限管理相同的中英雙語欄名。
# 內部儲存仍維持 canonical 欄位，避免影響 01/07/08 等模組串接。
DISPLAY_COLUMNS = {
    "_delete": "刪除 / Delete",
    "id": "ID / ID",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "is_active": "啟用 / Active",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "今日出勤 / Today Attendance",
    "note": "備註 / Note",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
}
DISPLAY_TO_INTERNAL = {v: k for k, v in DISPLAY_COLUMNS.items()}
EDITOR_COLS = [DISPLAY_COLUMNS[c] for c in COLS]
BOOL_INTERNAL_COLS = ["_delete", "is_active", "is_in_factory", "is_today_attendance"]
BOOL_DISPLAY_COLS = [DISPLAY_COLUMNS[c] for c in BOOL_INTERNAL_COLS]



def _excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, index=False, sheet_name=str(name)[:31] or "Sheet1")
    return bio.getvalue()

def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    # Accept both internal columns and bilingual editor columns, then normalize back.
    df = df.rename(columns={c: DISPLAY_TO_INTERNAL.get(c, c) for c in df.columns})
    for c in COLS:
        if c not in df.columns:
            df[c] = False if c in ["_delete", "is_active", "is_in_factory", "is_today_attendance"] else ""
    for c in BOOL_INTERNAL_COLS:
        df[c] = df[c].map(_to_bool_value).fillna(False).astype(bool) if c in df.columns else False
    return df[COLS]


def _to_bool_value(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    text = str(v).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否", ""}:
        return False
    return bool(v)


def _to_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_cols(df)
    return work.rename(columns=DISPLAY_COLUMNS)[EDITOR_COLS]


def _from_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_cols(df)


def _commit_current_editor_widget_state() -> None:
    """V67: commit data_editor widget delta into this page draft before any buttons/KPI read it.

    Streamlit reruns top-to-bottom.  Buttons above the table can run before the
    editor return value is copied back to STATE_KEY, so checkbox/text edits may
    appear to disappear.  This only synchronizes the in-memory draft; it does not
    save business data or change any other feature.
    """
    try:
        from services.data_editor_state_service import commit_editor_widget_state_to_session
        commit_editor_widget_state_to_session(
            state_key=STATE_KEY,
            editor_key=_editor_key(),
            to_editor_df=_to_editor_df,
            from_editor_df=_from_editor_df,
            ensure_df=ensure_cols,
        )
    except Exception:
        pass


def _current_internal_df() -> pd.DataFrame:
    _commit_current_editor_widget_state()
    return ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))


def _bulk_set_bool_column(col: str, value: bool) -> None:
    """V64: 批次按鈕重新指定整份 DataFrame，避免 in-place 修改被 data_editor 舊草稿覆蓋。"""
    df = _current_internal_df().copy()
    if col not in df.columns:
        df[col] = False
    df[col] = bool(value)
    st.session_state[STATE_KEY] = ensure_cols(df)
    _refresh_editor_widget()
    rerun()


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
    if isinstance(v, bool):
        return v
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    text = _normalize_text(v).lower()
    if text in ["", "0", "false", "否", "n", "no", "off", "unchecked", "☐", "□", "停用", "離職", "不在", "未出勤", "disabled", "inactive", "none", "nan"]:
        return False
    if text in ["1", "true", "是", "y", "yes", "on", "checked", "☑", "✅", "啟用", "在廠", "出勤", "勾選"]:
        return True
    return False


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
        if isinstance(employee_id, str) or isinstance(employee_name, str):
            return ensure_cols(pd.DataFrame()), has_header, warnings

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

    if "v253_employee_edit_enabled" not in st.session_state:
        st.session_state["v253_employee_edit_enabled"] = False
    employee_edit_enabled = bool(st.session_state.get("v253_employee_edit_enabled", False))
    ec1, ec2, ec3 = st.columns([1.2, 1.2, 3])
    with ec1:
        if st.button("◇ 啟動編輯 / Enable Edit", use_container_width=True, disabled=employee_edit_enabled, key="v253_enable_employee_edit"):
            st.session_state["v253_employee_edit_enabled"] = True
            _refresh_editor_widget()
            rerun()
    with ec2:
        if st.button("◌ 停止編輯 / Lock Edit", use_container_width=True, disabled=not employee_edit_enabled, key="v253_disable_employee_edit"):
            st.session_state["v253_employee_edit_enabled"] = False
            reload_data()
            _refresh_editor_widget()
            rerun()
    with ec3:
        if employee_edit_enabled:
            st.success("目前：已啟動編輯。修改後請按儲存才會正式寫入。")
        else:
            st.info("目前：唯讀保護。請先啟動編輯，再新增、修改、刪除、匯入或貼上人員名單。")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("⊕ 新增空白列 / Add Row", use_container_width=True, disabled=not employee_edit_enabled):
        blank = pd.DataFrame([{
            "_delete": False, "id": "", "employee_id": "", "employee_name": "",
            "department": "", "title": "", "is_active": True, "is_in_factory": True,
            "is_today_attendance": True, "note": "", "created_at": "", "updated_at": ""
        }])
        st.session_state[STATE_KEY] = pd.concat([blank, _current_internal_df()], ignore_index=True)
        _refresh_editor_widget()
        rerun()
    if c2.button("☑ 刪除全選 / Select Delete", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_delete_all_on"):
        _bulk_set_bool_column("_delete", True)
    if c3.button("☐ 刪除取消 / Clear Delete", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_delete_all_off"):
        _bulk_set_bool_column("_delete", False)
    if c4.button("☑ 啟用全選 / Active All", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_active_all_on"):
        _bulk_set_bool_column("is_active", True)
    if c5.button("☐ 啟用取消 / Inactive All", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_active_all_off"):
        _bulk_set_bool_column("is_active", False)
    if c6.button("⟳ 重新載入 / Reload", use_container_width=True):
        reload_data()
        _refresh_editor_widget()
        rerun()

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("☑ 在廠全選 / Factory All", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_factory_all_on"):
        _bulk_set_bool_column("is_in_factory", True)
    if b2.button("☐ 在廠取消 / Clear Factory", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_factory_all_off"):
        _bulk_set_bool_column("is_in_factory", False)
    if b3.button("☑ 今日出勤全選 / Attendance All", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_attendance_all_on"):
        _bulk_set_bool_column("is_today_attendance", True)
    if b4.button("☐ 今日出勤取消 / Clear Attendance", use_container_width=True, disabled=not employee_edit_enabled, key="v64_employee_attendance_all_off"):
        _bulk_set_bool_column("is_today_attendance", False)

    st.warning("勾選「刪除 / Delete」後按下儲存，才會真正刪除資料。工號 / Employee ID、姓名 / Name 為必填。")
    e1, e2 = st.columns(2)
    e1.download_button("⟰ 下載目前人員名單 / Export Employees", data=_excel_bytes({"employees": load_employees()}), file_name="SPT_人員名單.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    tpl = pd.DataFrame(columns=["工號", "姓名", "單位", "職稱", "啟用", "在廠", "今日出勤", "備註"])
    e2.download_button("⟰ 下載人員匯入範本 / Download Template", data=_excel_bytes({"template": tpl}), file_name="SPT_人員匯入範本.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    st.info("V64：批次按鈕已改為重新指定整份暫存表；刪除 / 啟用 / 在廠 / 今日出勤全選與取消會立即刷新 checkbox，不再被舊 data_editor 草稿蓋回。")
    _commit_current_editor_widget_state()
    st.session_state[STATE_KEY] = _current_internal_df()
    editor_df = _to_editor_df(st.session_state[STATE_KEY])
    # V120：穩定編輯模式。把 data_editor 與儲存按鈕放在同一個 form，
    # 避免每修改一格就 rerun 跳回頁面上方；批次按鈕與原儲存邏輯不變。
    with st.form("v120_employee_stable_editor_form", clear_on_submit=False):
        edited = st.data_editor(
            editor_df,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            height=560,
            column_order=EDITOR_COLS,
            column_config={
                DISPLAY_COLUMNS["_delete"]: st.column_config.CheckboxColumn("刪除 / Delete", width="medium"),
                DISPLAY_COLUMNS["id"]: st.column_config.NumberColumn("ID / ID", disabled=True, width="small"),
                DISPLAY_COLUMNS["employee_id"]: st.column_config.TextColumn("工號 / Employee ID", required=True, width="medium"),
                DISPLAY_COLUMNS["employee_name"]: st.column_config.TextColumn("姓名 / Name", required=True, width="medium"),
                DISPLAY_COLUMNS["department"]: st.column_config.TextColumn("單位 / Department", width="medium"),
                DISPLAY_COLUMNS["title"]: st.column_config.TextColumn("職稱 / Title", width="medium"),
                DISPLAY_COLUMNS["is_active"]: st.column_config.CheckboxColumn("啟用 / Active", width="medium"),
                DISPLAY_COLUMNS["is_in_factory"]: st.column_config.CheckboxColumn("在廠 / In Factory", width="medium"),
                DISPLAY_COLUMNS["is_today_attendance"]: st.column_config.CheckboxColumn("今日出勤 / Today Attendance", width="medium"),
                DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width="large"),
                DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", disabled=True, width="medium"),
                DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", disabled=True, width="medium"),
            },
            key=_editor_key(),
            disabled=not employee_edit_enabled,
        )
        submitted_employees = st.form_submit_button("▣ 確認儲存人員清單 / Save Employees", type="primary", use_container_width=True, disabled=not employee_edit_enabled)
    ignore_editor_return = bool(st.session_state.pop(EDITOR_IGNORE_RETURN_KEY, False))
    if employee_edit_enabled and isinstance(edited, pd.DataFrame) and not ignore_editor_return:
        st.session_state[STATE_KEY] = _from_editor_df(edited.copy())

    if submitted_employees:
        current_df = _current_internal_df()
        delete_mask = current_df["_delete"].map(_to_bool_value).fillna(False).astype(bool)
        deleted_count = int(delete_mask.sum())
        save_df = current_df.loc[~delete_mask].drop(columns=["_delete"], errors="ignore").copy()
        result = save_employees(save_df)
        reload_data()
        _refresh_editor_widget()
        st.session_state["v253_employee_edit_enabled"] = False
        st.success(f"儲存完成：目前保留/更新 {len(save_df)} 筆，刪除 {deleted_count} 筆，略過 {result.get('skipped', 0)} 筆。")
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
            if a1.button("⊕ 加入清單編輯 / Add to Editor", type="secondary", use_container_width=True, key="add_pasted_employees_to_editor_v138", disabled=not st.session_state.get("v253_employee_edit_enabled", False)):
                st.session_state[STATE_KEY] = pd.concat([parsed, _current_internal_df()], ignore_index=True)
                st.success("已加入『人員清單編輯』頁，請切回第一個頁籤確認後按儲存。")

            if a2.button("▣ 直接儲存貼上資料 / Save Pasted Employees", type="primary", use_container_width=True, key="save_pasted_employees_v138", disabled=not st.session_state.get("v253_employee_edit_enabled", False)):
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

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

