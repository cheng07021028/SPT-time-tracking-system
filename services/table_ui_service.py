# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from typing import Iterable

import pandas as pd
import streamlit as st

from .db_service import execute, query_one
from .duration_service import hours_to_hms

COLUMN_LABELS: dict[str, str] = {
    "id": "ID / ID",
    "record_key": "紀錄鍵 / Record Key",
    "status": "狀態 / Status",
    "work_order": "製令 / Work Order",
    "part_no": "P/N / Part No.",
    "type_name": "機型 / Type",
    "process_name": "工段名稱 / Process",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "start_action": "開始動作 / Start Action",
    "start_timestamp": "開始時間戳 / Start Timestamp",
    "end_action": "結束動作 / End Action",
    "end_timestamp": "結束時間戳 / End Timestamp",
    "remark": "備註 / Remark",
    "start_date": "開始日期 / Start Date",
    "start_time": "開始時間 / Start Time",
    "end_date": "結束日期 / End Date",
    "end_time": "結束時間 / End Time",
    "work_hours": "工時小計 / Work Time",
    "assembly_location": "組立地點 / Assembly Location",
    "group_key": "群組鍵 / Group Key",
    "is_group_work": "同時作業 / Parallel Work",
    "source": "來源 / Source",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
    "customer": "客戶 / Customer",
    "note": "備註 / Note",
    "is_active": "啟用 / Active",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "今日出勤 / Today Attendance",
    "log_time": "LOG時間 / Log Time",
    "user_name": "使用者 / User",
    "action_type": "動作類型 / Action Type",
    "target_table": "目標資料表 / Target Table",
    "target_id": "目標ID / Target ID",
    "message": "訊息 / Message",
    "detail": "明細 / Detail",
    "level": "等級 / Level",
    "total_hours": "累積工時 / Total Time",
    "record_count": "紀錄筆數 / Record Count",
    "active_count": "作業中筆數 / Active Count",
    "today_record_count": "今日紀錄筆數 / Today Records",
    "last_start_time": "最後開始時間 / Last Start",
    "count": "筆數 / Count",
    "avg_hours": "平均工時 / Avg Time",
}

DEFAULT_WIDTHS: dict[str, int] = {
    "id": 70,
    "record_key": 280,
    "work_order": 150,
    "part_no": 170,
    "type_name": 230,
    "process_name": 140,
    "employee_id": 120,
    "employee_name": 130,
    "start_timestamp": 190,
    "end_timestamp": 190,
    "remark": 260,
    "note": 260,
    "message": 360,
    "detail": 420,
    "created_at": 180,
    "updated_at": 180,
}


_TABLE_UI_SCHEMA_READY = False
_WIDTH_CACHE_TTL_SECONDS = 300


def label_for(col: str) -> str:
    return COLUMN_LABELS.get(col, f"{col} / {col}")


def ensure_table_ui_schema() -> None:
    global _TABLE_UI_SCHEMA_READY
    if _TABLE_UI_SCHEMA_READY:
        return
    execute(
        """
        CREATE TABLE IF NOT EXISTS table_ui_settings (
            table_key TEXT PRIMARY KEY,
            widths_json TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    _TABLE_UI_SCHEMA_READY = True


def load_widths(table_key: str) -> dict[str, int]:
    ensure_table_ui_schema()
    cache_key = f"_spt_width_cache_{table_key}"
    try:
        cached = st.session_state.get(cache_key)
        if cached and time.time() - float(cached.get("ts", 0)) < _WIDTH_CACHE_TTL_SECONDS:
            return dict(cached.get("data", {}))
    except Exception:
        pass
    row = query_one("SELECT widths_json FROM table_ui_settings WHERE table_key=?", (table_key,))
    if not row or not row.get("widths_json"):
        widths = {}
    else:
        try:
            data = json.loads(row["widths_json"])
            widths = {str(k): int(v) for k, v in data.items() if str(v).isdigit() or isinstance(v, int)}
        except Exception:
            widths = {}
    try:
        st.session_state[cache_key] = {"ts": time.time(), "data": widths}
    except Exception:
        pass
    return widths


def save_widths(table_key: str, widths: dict[str, int]) -> None:
    ensure_table_ui_schema()
    execute(
        """
        INSERT INTO table_ui_settings(table_key, widths_json, updated_at)
        VALUES (?, ?, datetime('now','localtime'))
        ON CONFLICT(table_key) DO UPDATE SET
            widths_json=excluded.widths_json,
            updated_at=excluded.updated_at
        """,
        (table_key, json.dumps(widths, ensure_ascii=False)),
    )
    try:
        st.session_state[f"_spt_width_cache_{table_key}"] = {"ts": time.time(), "data": dict(widths)}
    except Exception:
        pass


def _column_config(col: str, width: int | None = None):
    label = label_for(col)
    w = int(width or DEFAULT_WIDTHS.get(col, 140))
    if col in {"is_active", "is_in_factory", "is_today_attendance", "is_group_work", "刪除", "delete", "selected"}:
        return st.column_config.CheckboxColumn(label, width=w)
    if col in {"work_hours", "total_hours", "avg_hours"}:
        return st.column_config.TextColumn(label, width=w)
    if col in {"id", "record_count", "active_count", "today_record_count", "count"}:
        return st.column_config.NumberColumn(label, width=w)
    return st.column_config.TextColumn(label, width=w)


def build_column_config(table_key: str, df: pd.DataFrame) -> dict:
    widths = load_widths(table_key)
    return {col: _column_config(col, widths.get(col)) for col in df.columns}


def render_width_settings(table_key: str, df: pd.DataFrame, title: str = "欄寬設定 / Column Width Settings") -> None:
    """Lazy width editor.

    Streamlit executes widgets inside collapsed expanders, so the old version generated
    dozens of number_input widgets on every page load. This made module switching slow.
    V1.39 keeps the feature, but only renders the heavy controls when the user explicitly opens it.
    """
    if df is None or df.empty:
        return
    show_key = f"show_widths_{table_key}"
    show = st.toggle(f"⚙️ 顯示{title}", value=False, key=show_key)
    if not show:
        return
    widths = load_widths(table_key)
    with st.expander(title, expanded=True):
        st.caption("目前 Streamlit 無法直接讀取滑鼠拖拉後的欄寬，因此此處提供可永久儲存的欄寬設定。平常保持關閉可加快模組載入速度。")
        new_widths: dict[str, int] = {}
        cols = st.columns(4)
        for idx, col in enumerate(df.columns):
            default_width = int(widths.get(col, DEFAULT_WIDTHS.get(col, 140)))
            with cols[idx % 4]:
                new_widths[col] = st.number_input(label_for(col), min_value=60, max_value=700, value=default_width, step=10, key=f"width_{table_key}_{col}")
        if st.button("儲存欄寬設定 / Save Column Widths", key=f"save_widths_{table_key}", use_container_width=True):
            save_widths(table_key, new_widths)
            st.success("已儲存欄寬設定。")
            st.rerun()


def _format_duration_columns_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return UI copy with duration columns formatted as HH:MM:SS."""
    out = df.copy()
    for col in ["work_hours", "total_hours", "avg_hours"]:
        if col in out.columns:
            out[col] = out[col].map(hours_to_hms)
    return out


def _render_sort_controls(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """Add explicit sorting controls because Streamlit table sorting is not always obvious in edit mode."""
    if df is None or df.empty or len(df.columns) == 0:
        return df
    with st.expander("排序設定 / Sort Settings", expanded=False):
        c1, c2, c3 = st.columns([2, 1, 1])
        sort_col = c1.selectbox("排序欄位 / Sort Column", list(df.columns), format_func=label_for, key=f"sort_col_{table_key}")
        ascending = c2.radio("排序方向 / Direction", ["升冪 / ASC", "降冪 / DESC"], horizontal=True, key=f"sort_dir_{table_key}") == "升冪 / ASC"
        apply_sort = c3.checkbox("套用排序 / Apply", value=False, key=f"sort_apply_{table_key}")
        if apply_sort and sort_col in df.columns:
            try:
                return df.sort_values(sort_col, ascending=ascending, kind="mergesort", na_position="last").reset_index(drop=True)
            except Exception:
                st.warning("此欄位暫時無法排序，已維持原順序。")
    return df


def render_table(df: pd.DataFrame, table_key: str, *, editable: bool = False, disabled: Iterable[str] | None = None, key: str | None = None, height: int | None = None) -> pd.DataFrame | None:
    if df is None or df.empty:
        st.info("目前沒有資料 / No data")
        return None
    df = _render_sort_controls(table_key, df)
    render_width_settings(table_key, df)
    display_df = _format_duration_columns_for_display(df)
    cfg = build_column_config(table_key, display_df)
    disabled_cols = list(disabled or [])
    if "work_hours" in display_df.columns and "work_hours" not in disabled_cols:
        disabled_cols.append("work_hours")
    if "total_hours" in display_df.columns and "total_hours" not in disabled_cols:
        disabled_cols.append("total_hours")
    if "avg_hours" in display_df.columns and "avg_hours" not in disabled_cols:
        disabled_cols.append("avg_hours")
    if editable:
        return st.data_editor(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config=cfg,
            disabled=disabled_cols,
            num_rows="fixed",
            key=key or f"editor_{table_key}",
            height=height,
        )
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config=cfg,
        height=height,
        key=key or f"frame_{table_key}",
    )
    return None
