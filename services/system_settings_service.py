# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - System Settings Service V1.88

集中管理：
1. 工段名稱下拉選單（供 01 工時紀錄使用）
2. 休息時間設定（供工時計算扣除休息使用）

V1.88 修正重點：
- 查詢設定時不再每次執行 INSERT OR IGNORE，避免一般切換模組也觸發永久備份/GitHub 同步。
- 系統設定 schema 只在每個 Python process 初始化一次。
- 只有真正按下儲存/刪除時才寫入資料庫。
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd

from .db_service import execute, query_df, query_one
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

_SYSTEM_SETTINGS_SCHEMA_READY = False
_PROCESS_OPTIONS_CACHE: list[str] | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _valid_hhmm(value: str) -> bool:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return False
    try:
        h = int(parts[0]); m = int(parts[1])
    except Exception:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def _normalize_hhmm(value: str) -> str:
    text = str(value or "").strip()
    h, m = [int(x) for x in text.split(":")[:2]]
    return f"{h:02d}:{m:02d}"


def _clear_settings_cache() -> None:
    global _PROCESS_OPTIONS_CACHE
    _PROCESS_OPTIONS_CACHE = None
    try:
        from .calculation_service import clear_rest_periods_cache
        clear_rest_periods_cache()
    except Exception:
        pass


def ensure_system_settings_schema() -> None:
    """Prepare setting tables once without causing repeated backup sync.

    Important: do not run seed INSERT statements on every read. Even INSERT OR IGNORE
    is still a write operation to our db_service and may trigger expensive permanent
    export/GitHub sync. This was the main reason pages looked like they were always
    running after adding 13｜系統設定.
    """
    global _SYSTEM_SETTINGS_SCHEMA_READY
    if _SYSTEM_SETTINGS_SCHEMA_READY:
        return

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
    execute(
        """
        CREATE TABLE IF NOT EXISTS rest_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
        """
    )

    now = _now()

    # Seed only when the table is truly empty. Do not use INSERT OR IGNORE on every page load.
    try:
        row = query_one("SELECT COUNT(*) AS c FROM process_options") or {"c": 0}
        if int(row.get("c") or 0) == 0:
            for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
                execute(
                    """
                    INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
                    VALUES (?, 1, ?, '系統預設工段，可於 13 系統設定修改', ?, ?)
                    """,
                    (name, idx, now, now),
                )
    except Exception:
        pass

    try:
        row = query_one("SELECT COUNT(*) AS c FROM rest_periods") or {"c": 0}
        if int(row.get("c") or 0) == 0:
            for item in DEFAULT_REST_PERIODS:
                execute(
                    """
                    INSERT INTO rest_periods(name, start_time, end_time, is_active, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item["name"], item["start_time"], item["end_time"], item["is_active"], item["sort_order"]),
                )
    except Exception:
        pass

    _SYSTEM_SETTINGS_SCHEMA_READY = True


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:
    ensure_system_settings_schema()
    sql = "SELECT id, process_name, is_active, sort_order, note, created_at, updated_at FROM process_options WHERE 1=1"
    params: list = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY sort_order, id"
    return query_df(sql, params)


def get_process_options() -> list[str]:
    global _PROCESS_OPTIONS_CACHE
    if _PROCESS_OPTIONS_CACHE:
        return list(_PROCESS_OPTIONS_CACHE)
    try:
        df = load_process_options_df(active_only=True)
        if df.empty:
            _PROCESS_OPTIONS_CACHE = DEFAULT_PROCESS_OPTIONS.copy()
        else:
            names = [str(x).strip() for x in df["process_name"].dropna().tolist() if str(x).strip()]
            _PROCESS_OPTIONS_CACHE = names or DEFAULT_PROCESS_OPTIONS.copy()
    except Exception:
        _PROCESS_OPTIONS_CACHE = DEFAULT_PROCESS_OPTIONS.copy()
    return list(_PROCESS_OPTIONS_CACHE)


def save_process_options_df(df: pd.DataFrame) -> int:
    ensure_system_settings_schema()
    if df is None:
        return 0
    now = _now()
    count = 0
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(r.get("process_name", "")).strip()
        if not name:
            continue
        active_raw = str(r.get("is_active", True)).strip().lower()
        is_active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
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
    _clear_settings_cache()
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
        _clear_settings_cache()
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
        active_raw = str(r.get("is_active", True)).strip().lower()
        is_active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
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
    _clear_settings_cache()
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
        _clear_settings_cache()
        write_log("DELETE_REST_PERIODS", f"刪除休息時間設定 {count} 筆", "rest_periods", level="WARN")
    return count
