# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
import pandas as pd
from services.timezone_service import today_date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.crud_table_service import load_employees, save_employees
from services.time_record_service import load_records
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


def _v37_clear_widget_state(prefix: str) -> None:
    # Bulk buttons must win over the previous data_editor widget delta.
    for k in list(st.session_state.keys()):
        if str(k).startswith(prefix):
            try:
                del st.session_state[k]
            except Exception:
                pass

def touch_editor() -> None:
    _v37_clear_widget_state("today_attendance_editor_v202_")
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


# V25: stable callbacks for bulk buttons.
def _v25_today_batch(action: str) -> None:
    df = st.session_state.get(STATE_KEY)
    if df is None or not isinstance(df, pd.DataFrame):
        reload_employees()
        df = st.session_state.get(STATE_KEY, pd.DataFrame())
    df = ensure_cols(df.copy())
    if action == "factory_on":
        df["is_in_factory"] = True
    elif action == "factory_off":
        df["is_in_factory"] = False
    elif action == "today_on":
        df["is_today_attendance"] = True
    elif action == "today_off":
        df["is_today_attendance"] = False
    elif action == "active_on":
        df["is_active"] = True
    elif action == "active_off":
        df["is_active"] = False
    elif action == "reload":
        reload_employees()
        return
    st.session_state[STATE_KEY] = ensure_cols(df)
    st.session_state["v37_today_bulk_just_applied"] = True
    touch_editor()


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
    c1.button("⬡ 全選在廠", use_container_width=True, key="v25_today_factory_all_on", on_click=_v25_today_batch, args=("factory_on",))
    c2.button("⬡ 取消全選在廠", use_container_width=True, key="v25_today_factory_all_off", on_click=_v25_today_batch, args=("factory_off",))
    c3.button("⧖ 全選今日出勤", use_container_width=True, key="v25_today_attendance_all_on", on_click=_v25_today_batch, args=("today_on",))
    c4.button("⧖ 取消全選今日出勤", use_container_width=True, key="v25_today_attendance_all_off", on_click=_v25_today_batch, args=("today_off",))

    c5, c6, c7, c8 = st.columns(4)
    c5.button("◈ 啟用全選", use_container_width=True, key="v25_today_active_all_on", on_click=_v25_today_batch, args=("active_on",))
    c6.button("◌ 啟用全取消", use_container_width=True, key="v25_today_active_all_off", on_click=_v25_today_batch, args=("active_off",))
    c7.button("⟳ 重新載入", use_container_width=True, key="v25_today_reload", on_click=_v25_today_batch, args=("reload",))
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

    if st.session_state.pop("v37_today_bulk_just_applied", False):
        # Keep the bulk-button result. Do not let the old data_editor return value write it back to 0.
        pass
    else:
        st.session_state[STATE_KEY] = ensure_cols(edited)
    if st.button("▣ 確認儲存今日出勤設定 / Save Today Attendance", type="primary", use_container_width=True, key="save_today_attendance_v202"):
        save_df = st.session_state[STATE_KEY].copy()
        save_df.insert(0, "_delete", False)
        result = save_employees(save_df)
        reload_employees()
        st.success(f"今日出勤設定已儲存：新增/覆寫 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。")
        rerun()

st.divider()
st.subheader("今日未紀錄名單 / Missing Today")
today = today_date().strftime("%Y-%m-%d")
# V29: 直接使用權威檔資料計算，不再依賴 SQLite 查詢延遲。
emp_df = ensure_cols(load_employees())
rec_df = load_records(start_date=today, end_date=today)
if rec_df is None:
    rec_df = pd.DataFrame()
base = emp_df.copy()
for col in ["is_active", "is_in_factory", "is_today_attendance"]:
    if col not in base.columns:
        base[col] = False
    base[col] = base[col].astype(str).str.lower().str.strip().isin(["1", "true", "yes", "y", "是", "啟用", "在廠", "出勤"]) | (base[col] == 1) | (base[col] == True)
base = base[(base["is_active"]) & (base["is_in_factory"]) & (base["is_today_attendance"])]
if not rec_df.empty and "employee_id" in rec_df.columns:
    today_recs = rec_df.copy()
    if "start_date" in today_recs.columns:
        today_recs = today_recs[today_recs["start_date"].astype(str) == today]
    elif "work_date" in today_recs.columns:
        today_recs = today_recs[today_recs["work_date"].astype(str) == today]
    grp = today_recs.groupby("employee_id", dropna=False).agg(
        last_start_time=("start_timestamp", "max") if "start_timestamp" in today_recs.columns else ("employee_id", "size"),
        today_record_count=("employee_id", "size"),
    ).reset_index()
    df = base.merge(grp, on="employee_id", how="left")
else:
    df = base.copy()
    df["last_start_time"] = ""
    df["today_record_count"] = 0
if "today_record_count" not in df.columns:
    df["today_record_count"] = 0
df["today_record_count"] = df["today_record_count"].fillna(0).astype(int)
df = df[df["today_record_count"] == 0].sort_values("employee_id", kind="stable").reset_index(drop=True)
show_cols = ["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]
for c in show_cols:
    if c not in df.columns:
        df[c] = ""
df = df[show_cols]

st.metric("今日未紀錄人數 / Missing Records", f"{len(df):,}")
render_table(df, "missing_today_v202", editable=False, height=460)
