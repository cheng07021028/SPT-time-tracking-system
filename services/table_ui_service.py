# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Iterable

import pandas as pd
import streamlit as st

from .db_service import execute, query_one

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
    "work_hours": "工時小計 / Work Hours",
    "assembly_location": "組立地點 / Assembly Location",
    "group_key": "群組鍵 / Group Key",
    "is_group_work": "群組作業 / Group Work",
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
    "total_hours": "累積工時 / Total Hours",
    "record_count": "紀錄筆數 / Record Count",
    "active_count": "作業中筆數 / Active Count",
    "today_record_count": "今日紀錄筆數 / Today Records",
    "last_start_time": "最後開始時間 / Last Start",
    "count": "筆數 / Count",
    "avg_hours": "平均工時 / Avg Hours",
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


def label_for(col: str) -> str:
    return COLUMN_LABELS.get(col, f"{col} / {col}")


def ensure_table_ui_schema() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS table_ui_settings (
            table_key TEXT PRIMARY KEY,
            widths_json TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )


def load_widths(table_key: str) -> dict[str, int]:
    ensure_table_ui_schema()
    row = query_one("SELECT widths_json FROM table_ui_settings WHERE table_key=?", (table_key,))
    if not row or not row.get("widths_json"):
        return {}
    try:
        data = json.loads(row["widths_json"])
        return {str(k): int(v) for k, v in data.items() if str(v).isdigit() or isinstance(v, int)}
    except Exception:
        return {}


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


def _column_config(col: str, width: int | None = None):
    label = label_for(col)
    w = int(width or DEFAULT_WIDTHS.get(col, 140))
    if col in {"is_active", "is_in_factory", "is_today_attendance", "is_group_work"}:
        return st.column_config.CheckboxColumn(label, width=w)
    if col in {"work_hours", "total_hours", "avg_hours"}:
        return st.column_config.NumberColumn(label, width=w, format="%.2f")
    if col in {"id", "record_count", "active_count", "today_record_count", "count"}:
        return st.column_config.NumberColumn(label, width=w)
    return st.column_config.TextColumn(label, width=w)


def build_column_config(table_key: str, df: pd.DataFrame) -> dict:
    widths = load_widths(table_key)
    return {col: _column_config(col, widths.get(col)) for col in df.columns}


def render_width_settings(table_key: str, df: pd.DataFrame, title: str = "欄寬設定 / Column Width Settings") -> None:
    if df is None or df.empty:
        return
    widths = load_widths(table_key)
    with st.expander(title, expanded=False):
        st.caption("目前 Streamlit 無法直接讀取滑鼠拖拉後的欄寬，因此此處提供可永久儲存的欄寬設定。調整後按儲存，換頁或重開仍會保留。")
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


def render_table(df: pd.DataFrame, table_key: str, *, editable: bool = False, disabled: Iterable[str] | None = None, key: str | None = None, height: int | None = None) -> pd.DataFrame | None:
    if df is None or df.empty:
        st.info("目前沒有資料 / No data")
        return None
    render_width_settings(table_key, df)
    cfg = build_column_config(table_key, df)
    disabled_cols = list(disabled or [])
    if editable:
        return st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            column_config=cfg,
            disabled=disabled_cols,
            num_rows="fixed",
            key=key or f"editor_{table_key}",
            height=height,
        )
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg, height=height)
    return None
