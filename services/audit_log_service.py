# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Audit/Login Log Service V1.43
Independent persistent audit logs that survive module updates.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
AUDIT_STATE = PROJECT_ROOT / "data" / "persistent_state" / "spt_audit_log_state.json"
AUDIT_HISTORY_DIR = PROJECT_ROOT / "data" / "persistent_state" / "audit_history"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_login_logs_table() -> None:
    with connect_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            display_name TEXT,
            event_type TEXT,
            result TEXT,
            message TEXT,
            module_code TEXT,
            login_time TEXT,
            logout_time TEXT,
            idle_minutes REAL,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs(login_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_result ON login_logs(result)")
        conn.commit()


def write_login_log(
    username: str,
    display_name: str = "",
    event_type: str = "LOGIN",
    result: str = "SUCCESS",
    message: str = "",
    module_code: str = "",
    idle_minutes: Optional[float] = None,
    ip_address: str = "",
    user_agent: str = "",
    sync_permanent: bool = True,
) -> None:
    ensure_login_logs_table()
    now = _now()
    with connect_db() as conn:
        conn.execute("""
        INSERT INTO login_logs
        (username, display_name, event_type, result, message, module_code, login_time, logout_time,
         idle_minutes, ip_address, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            username, display_name, event_type, result, message, module_code,
            now if event_type.upper() != "LOGOUT" else None,
            now if event_type.upper() == "LOGOUT" else None,
            idle_minutes, ip_address, user_agent, now
        ))
        conn.commit()
    if sync_permanent:
        export_audit_logs(write_history=False)


def read_login_logs(limit: int = 1000, start_date: str = "", end_date: str = "", keyword: str = "") -> List[Dict[str, Any]]:
    ensure_login_logs_table()
    sql = "SELECT * FROM login_logs WHERE 1=1"
    params: List[Any] = []
    if start_date:
        sql += " AND COALESCE(login_time, logout_time, created_at) >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        sql += " AND COALESCE(login_time, logout_time, created_at) <= ?"
        params.append(end_date + " 23:59:59")
    if keyword:
        like = f"%{keyword}%"
        sql += " AND (username LIKE ? OR display_name LIKE ? OR event_type LIKE ? OR result LIKE ? OR message LIKE ? OR module_code LIKE ?)"
        params.extend([like] * 6)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with connect_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def export_audit_logs(write_history: bool = True) -> Dict[str, Any]:
    ensure_login_logs_table()
    rows = read_login_logs(limit=100000)
    payload = {
        "schema_version": "1.43",
        "exported_at": _now(),
        "table": "login_logs",
        "count": len(rows),
        "rows": rows,
    }
    AUDIT_STATE.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if write_history:
        AUDIT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        (AUDIT_HISTORY_DIR / f"spt_audit_log_state_{_stamp()}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    return payload


def restore_audit_logs() -> Dict[str, Any]:
    ensure_login_logs_table()
    if not AUDIT_STATE.exists():
        return {"ok": False, "message": "audit permanent file not found", "count": 0}
    payload = json.loads(AUDIT_STATE.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    with connect_db() as conn:
        conn.execute("DELETE FROM login_logs")
        for r in rows:
            conn.execute("""
            INSERT INTO login_logs
            (username, display_name, event_type, result, message, module_code, login_time, logout_time,
             idle_minutes, ip_address, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r.get("username"), r.get("display_name"), r.get("event_type"), r.get("result"),
                r.get("message"), r.get("module_code"), r.get("login_time"), r.get("logout_time"),
                r.get("idle_minutes"), r.get("ip_address"), r.get("user_agent"), r.get("created_at")
            ))
        conn.commit()
    return {"ok": True, "message": "restored", "count": len(rows)}


def clear_login_logs_by_date(start_date: str, end_date: str) -> int:
    ensure_login_logs_table()
    with connect_db() as conn:
        cur = conn.execute(
            """DELETE FROM login_logs
               WHERE COALESCE(login_time, logout_time, created_at) >= ?
                 AND COALESCE(login_time, logout_time, created_at) <= ?""",
            (start_date + " 00:00:00", end_date + " 23:59:59")
        )
        conn.commit()
        count = cur.rowcount or 0
    export_audit_logs(write_history=True)
    return count
