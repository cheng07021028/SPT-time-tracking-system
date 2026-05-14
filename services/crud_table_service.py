# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_tables() -> None:
    conn = get_conn()
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
    conn.commit()
    conn.close()

def log_action(action_type: str, target_table: str, message: str, detail: str = "") -> None:
    ensure_tables()
    conn = get_conn()
    conn.execute("""
        INSERT INTO system_logs
        (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (now_text(), "streamlit_user", action_type, target_table, "", message, detail, "INFO"))
    conn.commit()
    conn.close()

def _load(table: str, order_by: str = "id DESC") -> pd.DataFrame:
    ensure_tables()
    conn = get_conn()
    try:
        return pd.read_sql_query(f"SELECT * FROM {table} ORDER BY {order_by}", conn)
    finally:
        conn.close()

def load_work_orders() -> pd.DataFrame:
    df = _load("work_orders")
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    for c in cols:
        if c not in df.columns:
            df[c] = False if c == "is_active" else ""
    df = df[cols]
    df["is_active"] = df["is_active"].fillna(0).astype(bool)
    return df

def load_employees() -> pd.DataFrame:
    df = _load("employees")
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    for c in cols:
        if c not in df.columns:
            df[c] = False if c.startswith("is_") else ""
    df = df[cols]
    for c in ["is_active", "is_in_factory", "is_today_attendance"]:
        df[c] = df[c].fillna(0).astype(bool)
    return df

def _txt(v: Any) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip()

def _bool(v: Any) -> int:
    if isinstance(v, str):
        return 1 if v.strip().lower() in ("1", "true", "yes", "y", "是", "啟用", "在廠", "出勤", "v", "✓") else 0
    return 1 if bool(v) else 0

def _id(v: Any) -> int | None:
    if pd.isna(v) or v == "":
        return None
    try:
        i = int(float(v))
        return i if i > 0 else None
    except Exception:
        return None

def save_work_orders(df: pd.DataFrame) -> dict:
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    now = now_text()
    inserted = updated = deleted = skipped = 0
    for _, r in df.iterrows():
        rid = _id(r.get("id"))
        delete = _bool(r.get("_delete", False))
        wo = _txt(r.get("work_order"))
        if delete:
            if rid:
                cur.execute("DELETE FROM work_orders WHERE id=?", (rid,))
            elif wo:
                cur.execute("DELETE FROM work_orders WHERE work_order=?", (wo,))
            deleted += cur.rowcount
            continue
        if not wo:
            skipped += 1
            continue
        vals = (wo, _txt(r.get("part_no")), _txt(r.get("type_name")), _txt(r.get("assembly_location")),
                _txt(r.get("customer")), _txt(r.get("note")), _bool(r.get("is_active", True)), now)
        if rid:
            cur.execute("""
                UPDATE work_orders
                SET work_order=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, updated_at=?
                WHERE id=?
            """, vals + (rid,))
            updated += cur.rowcount
        else:
            cur.execute("""
                INSERT INTO work_orders
                (work_order, part_no, type_name, assembly_location, customer, note, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_order) DO UPDATE SET
                    part_no=excluded.part_no, type_name=excluded.type_name,
                    assembly_location=excluded.assembly_location, customer=excluded.customer,
                    note=excluded.note, is_active=excluded.is_active, updated_at=excluded.updated_at
            """, vals[:7] + (now, now))
            inserted += 1
    conn.commit()
    conn.close()
    log_action("SAVE_WORK_ORDERS", "work_orders", "儲存製令清單", f"inserted={inserted}, updated={updated}, deleted={deleted}, skipped={skipped}")
    return {"inserted": inserted, "updated": updated, "deleted": deleted, "skipped": skipped}

def save_employees(df: pd.DataFrame) -> dict:
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    now = now_text()
    inserted = updated = deleted = skipped = 0
    for _, r in df.iterrows():
        rid = _id(r.get("id"))
        delete = _bool(r.get("_delete", False))
        emp_id = _txt(r.get("employee_id"))
        emp_name = _txt(r.get("employee_name"))
        if delete:
            if rid:
                cur.execute("DELETE FROM employees WHERE id=?", (rid,))
            elif emp_id:
                cur.execute("DELETE FROM employees WHERE employee_id=?", (emp_id,))
            deleted += cur.rowcount
            continue
        if not emp_id or not emp_name:
            skipped += 1
            continue
        vals = (emp_id, emp_name, _txt(r.get("department")), _txt(r.get("title")),
                _bool(r.get("is_active", True)), _bool(r.get("is_in_factory", True)),
                _bool(r.get("is_today_attendance", True)), _txt(r.get("note")), now)
        if rid:
            cur.execute("""
                UPDATE employees
                SET employee_id=?, employee_name=?, department=?, title=?, is_active=?, is_in_factory=?,
                    is_today_attendance=?, note=?, updated_at=?
                WHERE id=?
            """, vals + (rid,))
            updated += cur.rowcount
        else:
            cur.execute("""
                INSERT INTO employees
                (employee_id, employee_name, department, title, is_active, is_in_factory, is_today_attendance, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id) DO UPDATE SET
                    employee_name=excluded.employee_name, department=excluded.department,
                    title=excluded.title, is_active=excluded.is_active,
                    is_in_factory=excluded.is_in_factory,
                    is_today_attendance=excluded.is_today_attendance,
                    note=excluded.note, updated_at=excluded.updated_at
            """, vals[:8] + (now, now))
            inserted += 1
    conn.commit()
    conn.close()
    log_action("SAVE_EMPLOYEES", "employees", "儲存人員名單", f"inserted={inserted}, updated={updated}, deleted={deleted}, skipped={skipped}")
    return {"inserted": inserted, "updated": updated, "deleted": deleted, "skipped": skipped}
