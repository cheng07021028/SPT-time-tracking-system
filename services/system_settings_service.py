# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - System Settings Service V1.82

集中管理：
1. 工段名稱下拉選單（原本寫死在 01 工時紀錄程式內）
2. 休息時間設定（供工時計算扣除休息使用）

所有寫入都走 db_service.execute，因此會觸發既有永久 JSON / GitHub 備份流程。
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd

from .db_service import execute, query_df
from .log_service import write_log

DEFAULT_PROCESS_OPTIONS = [
    "前置鈑金", "LP改造", "骨架組立", "配電", "模組", "水平", "S.T.", "清潔", "收機", "包機",
    "Packing", "異常", "設變", "重工", "教育訓練", "IPQC", "其他",
]

DEFAULT_REST_PERIODS = [
    {"name": "上午休息", "start_time": "10:30", "end_time": "10:45", "is_active": 1, "sort_order": 1},
    {"name": "午休", "start_time": "12:00", "end_time": "13:00", "is_active": 1, "sort_order": 2},
    {"name": "下午休息", "start_time": "15:00", "end_time": "15:15", "is_active": 1, "sort_order": 3},
    {"name": "晚餐休息", "start_time": "18:00", "end_time": "18:30", "is_active": 1, "sort_order": 4},
    {"name": "晚上休息", "start_time": "20:00", "end_time": "20:15", "is_active": 1, "sort_order": 5},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_system_settings_schema() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    now = _now()
    for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
        execute(
            """
            INSERT OR IGNORE INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
            VALUES (?, 1, ?, '系統預設工段，可於 13 系統設定修改', ?, ?)
            """,
            (name, idx, now, now),
        )


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:
    ensure_system_settings_schema()
    sql = "SELECT id, process_name, is_active, sort_order, note, created_at, updated_at FROM process_options WHERE 1=1"
    params: list = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY sort_order, id"
    return query_df(sql, params)


def get_process_options() -> list[str]:
    df = load_process_options_df(active_only=True)
    if df.empty:
        return DEFAULT_PROCESS_OPTIONS.copy()
    names = [str(x).strip() for x in df["process_name"].dropna().tolist() if str(x).strip()]
    return names or DEFAULT_PROCESS_OPTIONS.copy()


def save_process_options_df(df: pd.DataFrame) -> int:
    ensure_system_settings_schema()
    if df is None:
        return 0
    now = _now()
    count = 0
    work = df.copy().fillna("")
    # 重新整理順序與空白列；process_name 是設定值主鍵，不允許空白。
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(r.get("process_name", "")).strip()
        if not name:
            continue
        is_active = 1 if bool(r.get("is_active", True)) else 0
        try:
            sort_order = int(r.get("sort_order") or idx)
        except Exception:
            sort_order = idx
        note = str(r.get("note", "") or "")
        rid = r.get("id", "")
        if str(rid).strip() and str(rid).strip().lower() != "nan":
            execute(
                """
                UPDATE process_options
                SET process_name=?, is_active=?, sort_order=?, note=?, updated_at=?
                WHERE id=?
                """,
                (name, is_active, sort_order, note, now, int(float(rid))),
            )
        else:
            execute(
                """
                INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (name, is_active, sort_order, note, now, now),
            )
        count += 1
    write_log("SAVE_PROCESS_OPTIONS", f"儲存工段名稱設定 {count} 筆", "process_options")
    return count


def delete_process_options(ids: Iterable[int]) -> int:
    ensure_system_settings_schema()
    count = 0
    for rid in ids or []:
        try:
            i = int(rid)
        except Exception:
            continue
        execute("DELETE FROM process_options WHERE id=?", (i,))
        count += 1
    if count:
        write_log("DELETE_PROCESS_OPTIONS", f"刪除工段名稱設定 {count} 筆", "process_options", level="WARN")
    return count


def load_rest_periods_df(active_only: bool = False) -> pd.DataFrame:
    ensure_system_settings_schema()
    sql = "SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods WHERE 1=1"
    params: list = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY sort_order, id"
    return query_df(sql, params)


def save_rest_periods_df(df: pd.DataFrame) -> int:
    ensure_system_settings_schema()
    if df is None:
        return 0
    count = 0
    work = df.copy().fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(r.get("name", "")).strip() or f"休息{idx}"
        start_time = str(r.get("start_time", "")).strip()
        end_time = str(r.get("end_time", "")).strip()
        if not start_time or not end_time:
            continue
        is_active = 1 if bool(r.get("is_active", True)) else 0
        try:
            sort_order = int(r.get("sort_order") or idx)
        except Exception:
            sort_order = idx
        rid = r.get("id", "")
        if str(rid).strip() and str(rid).strip().lower() != "nan":
            execute(
                """
                UPDATE rest_periods
                SET name=?, start_time=?, end_time=?, is_active=?, sort_order=?
                WHERE id=?
                """,
                (name, start_time, end_time, is_active, sort_order, int(float(rid))),
            )
        else:
            execute(
                """
                INSERT INTO rest_periods(name, start_time, end_time, is_active, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, start_time, end_time, is_active, sort_order),
            )
        count += 1
    write_log("SAVE_REST_PERIODS", f"儲存休息時間設定 {count} 筆", "rest_periods")
    return count


def delete_rest_periods(ids: Iterable[int]) -> int:
    ensure_system_settings_schema()
    count = 0
    for rid in ids or []:
        try:
            i = int(rid)
        except Exception:
            continue
        execute("DELETE FROM rest_periods WHERE id=?", (i,))
        count += 1
    if count:
        write_log("DELETE_REST_PERIODS", f"刪除休息時間設定 {count} 筆", "rest_periods", level="WARN")
    return count
