# -*- coding: utf-8 -*-
"""V1.42 Audit/Login log helper.
Adds robust login/audit log persistence without depending on a single old table name.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
AUDIT_STATE_PATH = STATE_DIR / "spt_audit_log_state.json"
AUDIT_HISTORY_DIR = STATE_DIR / "audit_history"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_audit_tables() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
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
            idle_minutes INTEGER,
            session_id TEXT,
            source TEXT DEFAULT 'streamlit',
            created_at TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs(login_time)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(username)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_event ON login_logs(event_type)")
    conn.commit()
    conn.close()


def record_login_event(
    username: str,
    display_name: str = "",
    event_type: str = "LOGIN",
    result: str = "SUCCESS",
    message: str = "",
    module_code: str = "",
    session_id: str = "",
    idle_minutes: Optional[int] = None,
) -> None:
    if not username:
        return
    ensure_audit_tables()
    conn = _connect()
    cur = conn.cursor()
    now = _now()
    cur.execute(
        """
        INSERT INTO login_logs
        (username, display_name, event_type, result, message, module_code, login_time, logout_time,
         idle_minutes, session_id, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            display_name or username,
            event_type,
            result,
            message,
            module_code,
            now if event_type.upper() != "LOGOUT" else None,
            now if event_type.upper() == "LOGOUT" else None,
            idle_minutes,
            session_id,
            "streamlit",
            now,
        ),
    )
    conn.commit()
    conn.close()
    export_audit_logs_to_state()


def _session_username_from_streamlit() -> tuple[str, str]:
    try:
        import streamlit as st
    except Exception:
        return "", ""
    ss = st.session_state
    candidates = [
        "username", "login_username", "current_username", "auth_username",
        "logged_in_username", "user_name", "account", "login_account",
    ]
    for key in candidates:
        val = ss.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip(), val.strip()
    dict_candidates = ["user", "current_user", "auth_user", "login_user", "user_info"]
    for key in dict_candidates:
        val = ss.get(key)
        if isinstance(val, dict):
            username = str(val.get("username") or val.get("account") or val.get("user_name") or "").strip()
            display = str(val.get("display_name") or val.get("name") or username).strip()
            if username:
                return username, display or username
    return "", ""


def auto_record_current_session_login_once() -> None:
    """Called from theme_service wrappers. Records one LOGIN row per browser session/user."""
    try:
        import streamlit as st
    except Exception:
        return
    username, display = _session_username_from_streamlit()
    if not username:
        return
    if "_spt_session_id" not in st.session_state:
        st.session_state["_spt_session_id"] = str(uuid.uuid4())
    session_id = st.session_state.get("_spt_session_id", "")
    marker = f"{username}|{session_id}"
    if st.session_state.get("_spt_login_logged_marker") == marker:
        return
    record_login_event(
        username=username,
        display_name=display,
        event_type="LOGIN",
        result="SUCCESS",
        message="auto session login recorded",
        module_code="AUTO",
        session_id=session_id,
    )
    st.session_state["_spt_login_logged_marker"] = marker


def load_login_logs(limit: int = 1000, start_date: str = "", end_date: str = "", keyword: str = "") -> pd.DataFrame:
    ensure_audit_tables()
    conn = _connect()
    clauses: List[str] = []
    params: List[Any] = []
    if start_date:
        clauses.append("COALESCE(login_time, logout_time, created_at) >= ?")
        params.append(f"{start_date} 00:00:00")
    if end_date:
        clauses.append("COALESCE(login_time, logout_time, created_at) <= ?")
        params.append(f"{end_date} 23:59:59")
    if keyword:
        clauses.append("(username LIKE ? OR display_name LIKE ? OR event_type LIKE ? OR result LIKE ? OR message LIKE ? OR module_code LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw, kw, kw])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"""
        SELECT id, username, display_name, event_type, result, message, module_code,
               login_time, logout_time, idle_minutes, session_id, source, created_at
        FROM login_logs
        {where}
        ORDER BY id DESC
        LIMIT ?
    """
    params.append(int(limit))
    try:
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    return df


def clear_login_logs_by_date(start_date: str, end_date: str) -> int:
    ensure_audit_tables()
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM login_logs
        WHERE COALESCE(login_time, logout_time, created_at) >= ?
          AND COALESCE(login_time, logout_time, created_at) <= ?
        """,
        (f"{start_date} 00:00:00", f"{end_date} 23:59:59"),
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    export_audit_logs_to_state()
    return count


def export_audit_logs_to_state() -> Dict[str, Any]:
    ensure_audit_tables()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    df = load_login_logs(limit=200000)
    payload: Dict[str, Any] = {
        "exported_at": _now(),
        "table": "login_logs",
        "count": int(len(df)),
        "records": df.to_dict(orient="records"),
    }
    AUDIT_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hist = AUDIT_HISTORY_DIR / f"spt_audit_log_state_{stamp}.json"
    hist.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def restore_audit_logs_from_state(path: str | Path = AUDIT_STATE_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    ensure_audit_tables()
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM login_logs")
    for r in records:
        cur.execute(
            """
            INSERT INTO login_logs
            (id, username, display_name, event_type, result, message, module_code,
             login_time, logout_time, idle_minutes, session_id, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("id"), r.get("username"), r.get("display_name"), r.get("event_type"),
                r.get("result"), r.get("message"), r.get("module_code"), r.get("login_time"),
                r.get("logout_time"), r.get("idle_minutes"), r.get("session_id"),
                r.get("source", "streamlit"), r.get("created_at"),
            ),
        )
    conn.commit()
    conn.close()
    return len(records)


def audit_state_status() -> Dict[str, Any]:
    exists = AUDIT_STATE_PATH.exists()
    count = 0
    exported_at = ""
    if exists:
        try:
            payload = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8"))
            count = int(payload.get("count", 0))
            exported_at = str(payload.get("exported_at", ""))
        except Exception:
            pass
    return {
        "exists": exists,
        "path": str(AUDIT_STATE_PATH),
        "count": count,
        "exported_at": exported_at,
    }
