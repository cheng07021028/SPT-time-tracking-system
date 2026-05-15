# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.crud_table_service import load_employees, save_employees
from services.db_service import query_df
from services.table_ui_service import render_table

st.set_page_config(page_title="07. 今日未紀錄名單", page_icon="⚠️", layout="wide")
apply_theme()
require_module_access("07_missing")
render_header(
    "07｜今日未紀錄名單",
    "今日出勤與在廠狀態維護、未紀錄工時人員查詢｜同一頁面完成，不再分成兩個頁籤。",
)

STATE_KEY = "v202_today_attendance_editor"
EDITOR_REV_KEY = "v202_today_attendance_editor_rev"
COLS = [
    "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at",
]


def rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in COLS:
        if c not in out.columns:
            out[c] = False if c in {"is_active", "is_in_factory", "is_today_attendance"} else ""
    for c in ["is_active", "is_in_factory", "is_today_attendance"]:
        out[c] = out[c].fillna(False).astype(bool)
    return out[COLS]


def reload_employees() -> None:
    st.session_state[STATE_KEY] = ensure_cols(load_employees())
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def touch_editor() -> None:
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


if STATE_KEY not in st.session_state:
    reload_employees()

can_edit = check_permission("07_missing", "can_edit") or check_permission("04_employees", "can_edit")

st.subheader("今日出勤名單編輯 / Today Attendance Editor")
st.info("本頁直接維護『在廠』與『今日出勤』狀態，下面同步顯示今日未紀錄名單；修改後必須按『確認儲存今日出勤設定』才會永久套用。")

if not can_edit:
    st.warning("目前帳號沒有今日出勤 / 人員名單編輯權限，只能查看資料。")
    view_df = st.session_state[STATE_KEY].copy()
    render_table(view_df, "today_attendance_readonly_v202", editable=False, height=460)
else:
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("🏭 全選在廠", use_container_width=True, key="v202_today_factory_all_on"):
        st.session_state[STATE_KEY]["is_in_factory"] = True
        touch_editor()
        rerun()
    if c2.button("🏭 取消全選在廠", use_container_width=True, key="v202_today_factory_all_off"):
        st.session_state[STATE_KEY]["is_in_factory"] = False
        touch_editor()
        rerun()
    if c3.button("📅 全選今日出勤", use_container_width=True, key="v202_today_attendance_all_on"):
        st.session_state[STATE_KEY]["is_today_attendance"] = True
        touch_editor()
        rerun()
    if c4.button("📅 取消全選今日出勤", use_container_width=True, key="v202_today_attendance_all_off"):
        st.session_state[STATE_KEY]["is_today_attendance"] = False
        touch_editor()
        rerun()

    c5, c6, c7, c8 = st.columns(4)
    if c5.button("✅ 啟用全選", use_container_width=True, key="v202_today_active_all_on"):
        st.session_state[STATE_KEY]["is_active"] = True
        touch_editor()
        rerun()
    if c6.button("⬜ 啟用全取消", use_container_width=True, key="v202_today_active_all_off"):
        st.session_state[STATE_KEY]["is_active"] = False
        touch_editor()
        rerun()
    if c7.button("🔄 重新載入", use_container_width=True, key="v202_today_reload"):
        reload_employees()
        rerun()
    c8.caption("批次按鈕只改畫面暫存，按儲存後才寫入。")

    editor_key = f"today_attendance_editor_v202_{st.session_state.get(EDITOR_REV_KEY, 0)}"
    edited = st.data_editor(
        st.session_state[STATE_KEY],
        hide_index=True,
        use_container_width=True,
        height=460,
        disabled=["id", "employee_id", "employee_name", "department", "title", "note", "created_at", "updated_at"],
        column_order=COLS,
        column_config={
            "id": st.column_config.NumberColumn("ID / ID", width="small"),
            "employee_id": st.column_config.TextColumn("工號 / Employee ID", width="medium"),
            "employee_name": st.column_config.TextColumn("姓名 / Name", width="medium"),
            "department": st.column_config.TextColumn("單位 / Department", width="medium"),
            "title": st.column_config.TextColumn("職稱 / Title", width="medium"),
            "is_active": st.column_config.CheckboxColumn("啟用 / Active", width="small"),
            "is_in_factory": st.column_config.CheckboxColumn("在廠 / In Factory", width="small"),
            "is_today_attendance": st.column_config.CheckboxColumn("今日出勤 / Today Attendance", width="small"),
            "note": st.column_config.TextColumn("備註 / Note", width="large"),
            "created_at": st.column_config.TextColumn("建立時間 / Created At", width="medium"),
            "updated_at": st.column_config.TextColumn("更新時間 / Updated At", width="medium"),
        },
        key=editor_key,
    )

    st.session_state[STATE_KEY] = ensure_cols(edited)
    if st.button("💾 確認儲存今日出勤設定 / Save Today Attendance", type="primary", use_container_width=True, key="save_today_attendance_v202"):
        save_df = st.session_state[STATE_KEY].copy()
        save_df.insert(0, "_delete", False)
        result = save_employees(save_df)
        reload_employees()
        st.success(f"今日出勤設定已儲存：新增/覆寫 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。")
        rerun()

st.divider()
st.subheader("今日未紀錄名單 / Missing Today")
today = date.today().strftime("%Y-%m-%d")
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
