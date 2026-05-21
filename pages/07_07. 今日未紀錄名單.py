# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
import pandas as pd
from services.timezone_service import today_date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.crud_table_service import load_employees, save_employees
from services.db_service import query_df
from services.table_ui_service import render_table

st.set_page_config(page_title="07. 今日未紀錄名單", page_icon="⟁️", layout="wide")
apply_theme()
require_module_access("07_missing")
render_header(
    "07｜今日未紀錄名單",
    "今日出勤與在廠狀態維護、未紀錄工時人員查詢｜同一頁面完成，不再分成兩個頁籤。",
)

STATE_KEY = "v202_today_attendance_editor"
EDITOR_REV_KEY = "v202_today_attendance_editor_rev"
EDITOR_IGNORE_RETURN_KEY = "v263_today_attendance_ignore_next_editor_return"
COLS = [
    "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at",
]

# V61：今日出勤維護表格也使用與 10｜權限管理相同的中英雙語實際欄名。
DISPLAY_COLUMNS = {
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
BOOL_INTERNAL_COLS = ["is_active", "is_in_factory", "is_today_attendance"]


def rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


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


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = out.rename(columns={c: DISPLAY_TO_INTERNAL.get(c, c) for c in out.columns})
    for c in COLS:
        if c not in out.columns:
            out[c] = False if c in {"is_active", "is_in_factory", "is_today_attendance"} else ""
    for c in BOOL_INTERNAL_COLS:
        out[c] = out[c].map(_to_bool_value).fillna(False).astype(bool)
    return out[COLS]


def _to_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_cols(df).rename(columns=DISPLAY_COLUMNS)[EDITOR_COLS]


def _from_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_cols(df)


def reload_employees() -> None:
    st.session_state[STATE_KEY] = ensure_cols(load_employees())
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def touch_editor() -> None:
    # V63：清除 Streamlit widget state + 全域 column_settings_service 草稿，
    # 避免批次按鈕已改暫存資料，但 data_editor 仍顯示舊 checkbox。
    try:
        for _k0 in list(st.session_state.keys()):
            sk = str(_k0)
            if sk.startswith("today_attendance_editor_v202_") or "today_attendance_editor" in sk:
                st.session_state.pop(_k0, None)
    except Exception:
        pass
    try:
        from services.column_settings_service import clear_editor_draft
        clear_editor_draft("today_attendance_editor")
        clear_editor_draft("today_attendance")
    except Exception:
        pass
    st.session_state[EDITOR_IGNORE_RETURN_KEY] = True
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def _current_internal_df() -> pd.DataFrame:
    return ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))


def _bulk_set_bool_column(col: str, value: bool) -> None:
    """V64: 批次按鈕重新指定整份 DataFrame，避免 in-place 修改被 data_editor 舊草稿覆蓋。"""
    df = _current_internal_df().copy()
    if col not in df.columns:
        df[col] = False
    df[col] = bool(value)
    st.session_state[STATE_KEY] = ensure_cols(df)
    touch_editor()
    rerun()


if STATE_KEY not in st.session_state:
    reload_employees()

can_edit = check_permission("07_missing", "can_edit") or check_permission("04_employees", "can_edit")

st.subheader("今日出勤名單編輯 / Today Attendance Editor")
st.info("V64：本頁直接維護『啟用 / 在廠 / 今日出勤』狀態；批次按鈕會重新指定整份暫存表並刷新 data_editor，checkbox 顯示與暫存資料保持一致。")

if not can_edit:
    st.warning("目前帳號沒有今日出勤 / 人員名單編輯權限，只能查看資料。")
    view_df = st.session_state[STATE_KEY].copy()
    render_table(view_df, "today_attendance_readonly_v202", editable=False, height=460)
else:
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("☑ 在廠全選 / Factory All", use_container_width=True, key="v64_today_factory_all_on"):
        _bulk_set_bool_column("is_in_factory", True)
    if c2.button("☐ 在廠取消 / Clear Factory", use_container_width=True, key="v64_today_factory_all_off"):
        _bulk_set_bool_column("is_in_factory", False)
    if c3.button("☑ 今日出勤全選 / Attendance All", use_container_width=True, key="v64_today_attendance_all_on"):
        _bulk_set_bool_column("is_today_attendance", True)
    if c4.button("☐ 今日出勤取消 / Clear Attendance", use_container_width=True, key="v64_today_attendance_all_off"):
        _bulk_set_bool_column("is_today_attendance", False)

    c5, c6, c7, c8 = st.columns(4)
    if c5.button("☑ 啟用全選 / Active All", use_container_width=True, key="v64_today_active_all_on"):
        _bulk_set_bool_column("is_active", True)
    if c6.button("☐ 啟用取消 / Inactive All", use_container_width=True, key="v64_today_active_all_off"):
        _bulk_set_bool_column("is_active", False)
    if c7.button("⟳ 重新載入 / Reload", use_container_width=True, key="v202_today_reload"):
        reload_employees()
        rerun()
    c8.caption("批次按鈕只改畫面暫存，按儲存後才寫入。")

    editor_key = f"today_attendance_editor_v202_{st.session_state.get(EDITOR_REV_KEY, 0)}"
    st.session_state[STATE_KEY] = ensure_cols(st.session_state[STATE_KEY])
    editor_df = _to_editor_df(st.session_state[STATE_KEY])
    edited = st.data_editor(
        editor_df,
        hide_index=True,
        use_container_width=True,
        height=460,
        disabled=[DISPLAY_COLUMNS[c] for c in ["id", "employee_id", "employee_name", "department", "title", "note", "created_at", "updated_at"]],
        column_order=EDITOR_COLS,
        column_config={
            DISPLAY_COLUMNS["id"]: st.column_config.NumberColumn("ID / ID", width="small"),
            DISPLAY_COLUMNS["employee_id"]: st.column_config.TextColumn("工號 / Employee ID", width="medium"),
            DISPLAY_COLUMNS["employee_name"]: st.column_config.TextColumn("姓名 / Name", width="medium"),
            DISPLAY_COLUMNS["department"]: st.column_config.TextColumn("單位 / Department", width="medium"),
            DISPLAY_COLUMNS["title"]: st.column_config.TextColumn("職稱 / Title", width="medium"),
            DISPLAY_COLUMNS["is_active"]: st.column_config.CheckboxColumn("啟用 / Active", width="medium"),
            DISPLAY_COLUMNS["is_in_factory"]: st.column_config.CheckboxColumn("在廠 / In Factory", width="medium"),
            DISPLAY_COLUMNS["is_today_attendance"]: st.column_config.CheckboxColumn("今日出勤 / Today Attendance", width="medium"),
            DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width="large"),
            DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", width="medium"),
            DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", width="medium"),
        },
        key=editor_key,
    )

    ignore_editor_return = bool(st.session_state.pop(EDITOR_IGNORE_RETURN_KEY, False))
    if isinstance(edited, pd.DataFrame) and not ignore_editor_return:
        st.session_state[STATE_KEY] = _from_editor_df(edited)
    if st.button("▣ 確認儲存今日出勤設定 / Save Today Attendance", type="primary", use_container_width=True, key="save_today_attendance_v61"):
        save_df = st.session_state[STATE_KEY].copy()
        save_df.insert(0, "_delete", False)
        result = save_employees(save_df)
        reload_employees()
        st.success(f"今日出勤設定已儲存：目前保留/更新 {len(save_df)} 筆，略過 {result.get('skipped', 0)} 筆。")
        rerun()

st.divider()
st.subheader("今日未紀錄名單 / Missing Today")
today = today_date().strftime("%Y-%m-%d")
df = query_df(
    """
    SELECT e.employee_id, e.employee_name, e.department, e.title, e.is_in_factory, e.is_today_attendance,
           MAX(t.start_timestamp) AS last_start_time,
           COUNT(t.id) AS today_record_count
    FROM employees e
    LEFT JOIN time_records t
      ON e.employee_id=t.employee_id AND t.start_date=?
    WHERE e.is_active=1 AND e.is_in_factory=1 AND e.is_today_attendance=1
    GROUP BY e.employee_id, e.employee_name, e.department, e.title, e.is_in_factory, e.is_today_attendance
    HAVING COUNT(t.id)=0
    ORDER BY e.employee_id
    """,
    (today,),
)

st.metric("今日未紀錄人數 / Missing Records", f"{len(df):,}")
render_table(df, "missing_today_v202", editable=False, height=460)
