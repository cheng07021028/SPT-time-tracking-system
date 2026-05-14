# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - SQLite DB Service

V1.1 修正重點：
1. Streamlit Cloud / 新電腦第一次啟動時，自動建立資料庫與資料表。
2. 避免尚未執行 tools/init_database.py 時，各頁面查詢出現 pandas.errors.DatabaseError。
3. query_df / query_one / execute 全部先確保 schema 存在。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Any
from datetime import datetime

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "data" / "database"
DB_PATH = DB_DIR / "spt_time_tracking.db"

_SCHEMA_READY = False


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _open_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_order TEXT UNIQUE NOT NULL,
        part_no TEXT,
        type_name TEXT,
        assembly_location TEXT,
        customer TEXT,
        note TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT UNIQUE NOT NULL,
        employee_name TEXT NOT NULL,
        department TEXT,
        title TEXT,
        is_active INTEGER DEFAULT 1,
        is_in_factory INTEGER DEFAULT 1,
        is_today_attendance INTEGER DEFAULT 1,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS time_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_key TEXT UNIQUE,
        status TEXT,
        work_order TEXT,
        part_no TEXT,
        type_name TEXT,
        process_name TEXT,
        employee_id TEXT,
        employee_name TEXT,
        start_action TEXT,
        start_timestamp TEXT,
        end_action TEXT,
        end_timestamp TEXT,
        remark TEXT,
        start_date TEXT,
        start_time TEXT,
        end_date TEXT,
        end_time TEXT,
        work_hours REAL DEFAULT 0,
        assembly_location TEXT,
        group_key TEXT,
        is_group_work INTEGER DEFAULT 0,
        source TEXT DEFAULT 'streamlit',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_time TEXT,
        user_name TEXT,
        action_type TEXT,
        target_table TEXT,
        target_id TEXT,
        message TEXT,
        detail TEXT,
        level TEXT DEFAULT 'INFO'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rest_periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        note TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS table_ui_settings (
        table_key TEXT PRIMARY KEY,
        widths_json TEXT,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    default_rests = [
        (1, "上午休息", "10:30", "10:45", 1),
        (2, "午休", "12:00", "13:00", 2),
        (3, "下午休息", "15:00", "15:15", 3),
        (4, "晚餐休息", "18:00", "18:30", 4),
        (5, "晚上休息", "20:00", "20:15", 5),
    ]
    cur.executemany(
        """
        INSERT OR IGNORE INTO rest_periods
        (id, name, start_time, end_time, is_active, sort_order)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        default_rests,
    )

    now = _now()
    settings = [
        ("company_name", "超慧科技", "公司名稱"),
        ("system_name", "製造部智慧工時紀錄系統", "系統名稱"),
        ("standard_work_start", "09:00", "標準上班時間"),
        ("standard_work_end", "18:00", "標準下班時間"),
        ("daily_expected_hours_min", "7.0", "每日最低合理工時"),
        ("daily_expected_hours_max", "7.5", "每日最高合理工時"),
    ]
    cur.executemany(
        """
        INSERT OR IGNORE INTO system_settings
        (setting_key, setting_value, note, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        [(k, v, n, now) for k, v, n in settings],
    )

    cur.execute(
        """
        INSERT INTO system_logs
        (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        SELECT ?, 'SYSTEM', 'AUTO_INIT_DATABASE', 'ALL', '', '自動初始化資料庫完成', ?, 'INFO'
        WHERE NOT EXISTS (
            SELECT 1 FROM system_logs WHERE action_type='AUTO_INIT_DATABASE'
        )
        """,
        (now, str(DB_PATH)),
    )

    conn.commit()


def ensure_database() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _open_connection() as conn:
        _init_schema(conn)
    _SCHEMA_READY = True


def get_connection() -> sqlite3.Connection:
    ensure_database()
    return _open_connection()


def execute(sql: str, params: Iterable[Any] | None = None) -> int:
    ensure_database()
    if params is None:
        params = ()
    with _open_connection() as conn:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.lastrowid


def executemany(sql: str, rows: list[Iterable[Any]]) -> None:
    ensure_database()
    with _open_connection() as conn:
        conn.executemany(sql, rows)
        conn.commit()


def query_df(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
    ensure_database()
    if params is None:
        params = ()
    with _open_connection() as conn:
        return pd.read_sql_query(sql, conn, params=tuple(params))


def query_one(sql: str, params: Iterable[Any] | None = None) -> dict | None:
    ensure_database()
    if params is None:
        params = ()
    with _open_connection() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None
