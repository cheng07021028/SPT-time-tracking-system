# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "data" / "permanent_store" / "database"
DB_PATH = DB_DIR / "spt_time_tracking.db"


def connect_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    conn = connect_db()
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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    default_rests = [
        (1, "上午休息", "10:30", "10:45", 1),
        (2, "午休", "12:00", "13:00", 2),
        (3, "下午休息", "15:00", "15:15", 3),
        (4, "晚餐休息", "18:00", "18:30", 4),
        (5, "晚上休息", "20:00", "20:15", 5),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO rest_periods(id, name, start_time, end_time, is_active, sort_order) VALUES (?, ?, ?, ?, 1, ?)",
        default_rests,
    )
    settings = [
        ("company_name", "超慧科技", "公司名稱", now),
        ("system_name", "製造部智慧工時紀錄系統", "系統名稱", now),
        ("standard_work_start", "09:00", "標準上班時間", now),
        ("standard_work_end", "18:00", "標準下班時間", now),
        ("daily_expected_hours_min", "7.0", "每日最低合理工時", now),
        ("daily_expected_hours_max", "7.5", "每日最高合理工時", now),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO system_settings(setting_key, setting_value, note, updated_at) VALUES (?, ?, ?, ?)",
        settings,
    )
    cur.execute("""
    INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (now, "SYSTEM", "INIT_DATABASE", "ALL", "", "初始化資料庫完成", str(DB_PATH), "INFO"))
    conn.commit()
    conn.close()
    print("============================================")
    print("SPT Time Tracking System Database Initialized")
    print(f"DB Path: {DB_PATH}")
    print("============================================")


if __name__ == "__main__":
    init_database()
