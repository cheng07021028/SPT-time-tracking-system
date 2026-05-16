# -*- coding: utf-8 -*-
"""SPT Time Tracking - Audit/Login log service V1.49.

Fixes:
- Login records showing 0 because some versions wrote to security_login_logs
  while page 11 read login_logs.
- Keeps aliases used by older pages to prevent ImportError.
- Writes independent permanent files for login logs without requiring GitHub on import.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.timezone_service import now_text, now_stamp, today_text, today_date

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
PERSISTENT_STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
AUDIT_HISTORY_DIR = PERSISTENT_STATE_DIR / "audit_history"
AUDIT_STATE_PATH = PERSISTENT_STATE_DIR / "spt_audit_log_state.json"
MODULE_DIR = PROJECT_ROOT / "data" / "persistent_modules" / "11_login_logs"
MODULE_RECORDS_PATH = MODULE_DIR / "11_login_logs_records.json"
MODULE_SETTINGS_PATH = MODULE_DIR / "11_login_logs_settings.json"
MODULE_AUDIT_PATH = MODULE_DIR / "11_login_logs_audit.jsonl"


def _now() -> str:
    return now_text()


def _now_file() -> str:
    return now_stamp()


def _ensure_dirs() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERSISTENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    MODULE_DIR.mkdir(parents=True, exist_ok=True)
    (MODULE_DIR / "history").mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def ensure_login_logs_table() -> None:
    _ensure_dirs()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs(login_time)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_user ON login_logs(username)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_event ON login_logs(event_type)")
    conn.commit()
    conn.close()


ensure_audit_log_table = ensure_login_logs_table
ensure_audit_tables = ensure_login_logs_table
init_audit_log_table = ensure_login_logs_table
init_login_logs = ensure_login_logs_table


def _security_login_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Read legacy security_login_logs rows if that table exists."""
    if not _table_exists(conn, "security_login_logs"):
        return []
    rows = conn.execute("SELECT * FROM security_login_logs ORDER BY id DESC").fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        idle_seconds = d.get("idle_seconds")
        try:
            idle_minutes = round(float(idle_seconds) / 60, 2) if idle_seconds not in (None, "") else None
        except Exception:
            idle_minutes = None
        out.append({
            "id": f"S{d.get('id')}",
            "source": "security_login_logs",
            "username": d.get("username"),
            "display_name": d.get("display_name"),
            "event_type": d.get("event_type"),
            "result": d.get("result"),
            "message": d.get("message"),
            "module_code": d.get("module_code"),
            "login_time": d.get("login_time") or d.get("created_at"),
            "logout_time": d.get("logout_time"),
            "idle_minutes": idle_minutes,
            "ip_address": "",
            "user_agent": d.get("user_agent"),
            "created_at": d.get("created_at"),
        })
    return out


def _primary_login_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    ensure_login_logs_table()
    rows = conn.execute("SELECT * FROM login_logs ORDER BY id DESC").fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["source"] = "login_logs"
        out.append(d)
    return out


def record_login_log(
    username: str = "",
    display_name: str = "",
    event_type: str = "LOGIN",
    result: str = "SUCCESS",
    message: str = "",
    module_code: str = "",
    login_time: Optional[str] = None,
    logout_time: Optional[str] = None,
    idle_minutes: Optional[float] = None,
    ip_address: str = "",
    user_agent: str = "",
    **kwargs: Any,
) -> int:
    """Insert one audit event into login_logs. Lightweight: no GitHub upload here."""
    ensure_login_logs_table()
    login_time = login_time or _now()
    created_at = kwargs.get("created_at") or _now()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO login_logs (
        username, display_name, event_type, result, message, module_code,
        login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, display_name, event_type, result, message, module_code,
          login_time, logout_time, idle_minutes, ip_address, user_agent, created_at))
    new_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    try:
        export_audit_logs_to_permanent_file(create_history=False)
    except Exception:
        pass
    return new_id


write_login_log = record_login_log
add_login_log = record_login_log
append_login_log = record_login_log
write_audit_log = record_login_log
record_audit_log = record_login_log
log_login_event = record_login_log
save_login_log = record_login_log


def auto_record_session_login(username: str = "", display_name: str = "", roles: str = "", **kwargs: Any) -> None:
    if not username:
        return
    try:
        import streamlit as st
        key = f"_spt_login_recorded_{username}"
        if st.session_state.get(key):
            return
        record_login_log(username=username, display_name=display_name, event_type="LOGIN", result="SUCCESS",
                         message=f"roles={roles}" if roles else kwargs.get("message", ""),
                         module_code=kwargs.get("module_code", "LOGIN"))
        st.session_state[key] = True
    except Exception:
        try:
            record_login_log(username=username, display_name=display_name, event_type="LOGIN", result="SUCCESS",
                             message=f"roles={roles}" if roles else "", module_code="LOGIN")
        except Exception:
            pass


record_session_login_once = auto_record_session_login
ensure_session_login_recorded = auto_record_session_login
maybe_record_session_login = auto_record_session_login


def migrate_security_login_logs_to_login_logs() -> int:
    """Copy legacy security_login_logs rows into login_logs if not already copied."""
    ensure_login_logs_table()
    conn = get_connection()
    if not _table_exists(conn, "security_login_logs"):
        conn.close()
        return 0
    legacy = conn.execute("SELECT * FROM security_login_logs ORDER BY id ASC").fetchall()
    inserted = 0
    cur = conn.cursor()
    for r in legacy:
        d = dict(r)
        marker = f"legacy_security_login_logs_id={d.get('id')}"
        exists = conn.execute("SELECT 1 FROM login_logs WHERE message LIKE ? LIMIT 1", (f"%{marker}%",)).fetchone()
        if exists:
            continue
        msg = (d.get("message") or "") + (" | " if d.get("message") else "") + marker
        idle_seconds = d.get("idle_seconds")
        try:
            idle_minutes = round(float(idle_seconds) / 60, 2) if idle_seconds not in (None, "") else None
        except Exception:
            idle_minutes = None
        cur.execute("""
        INSERT INTO login_logs (
            username, display_name, event_type, result, message, module_code,
            login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (d.get("username"), d.get("display_name"), d.get("event_type"), d.get("result"), msg,
              d.get("module_code"), d.get("login_time") or d.get("created_at"), d.get("logout_time"),
              idle_minutes, "", d.get("user_agent"), d.get("created_at") or d.get("login_time") or _now()))
        inserted += 1
    conn.commit()
    conn.close()
    if inserted:
        try:
            export_audit_logs_to_permanent_file(create_history=True)
        except Exception:
            pass
    return inserted


def _filter_records(records: List[Dict[str, Any]], start_date: Optional[str], end_date: Optional[str], keyword: str,
                    event_types: Optional[List[str]], results: Optional[List[str]]) -> List[Dict[str, Any]]:
    def get_date(r: Dict[str, Any]) -> str:
        return str(r.get("login_time") or r.get("created_at") or "")[:10]
    out = []
    kw = (keyword or "").strip().lower()
    for r in records:
        d = get_date(r)
        if start_date and d and d < str(start_date):
            continue
        if end_date and d and d > str(end_date):
            continue
        if event_types and r.get("event_type") not in event_types:
            continue
        if results and r.get("result") not in results:
            continue
        if kw:
            blob = " ".join(str(v) for v in r.values()).lower()
            if kw not in blob:
                continue
        out.append(r)
    return out


def load_login_logs(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "",
                    limit: int = 1000, event_types: Optional[List[str]] = None,
                    results: Optional[List[str]] = None, include_legacy: bool = True, **kwargs: Any):
    ensure_login_logs_table()
    conn = get_connection()
    records = _primary_login_rows(conn)
    if include_legacy:
        # include legacy security_login_logs in search even before migration
        records.extend(_security_login_rows(conn))
    conn.close()
    records = _filter_records(records, start_date, end_date, keyword, event_types, results)
    records.sort(key=lambda r: str(r.get("login_time") or r.get("created_at") or ""), reverse=True)
    if limit:
        records = records[:int(limit)]
    if pd is not None:
        return pd.DataFrame(records)
    return records


get_login_logs = load_login_logs
query_login_logs = load_login_logs
load_audit_logs = load_login_logs


def count_login_logs(include_legacy: bool = True) -> int:
    logs = load_login_logs(limit=100000, include_legacy=include_legacy)
    return int(len(logs))


def get_login_log_stats(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "") -> Dict[str, int]:
    logs = load_login_logs(start_date=start_date, end_date=end_date, keyword=keyword, limit=100000)
    if pd is not None and hasattr(logs, "empty"):
        total = int(len(logs))
        success = int((logs.get("result", "") == "SUCCESS").sum()) if total else 0
        return {"records": total, "success": success, "failed": total - success}
    total = len(logs)
    success = sum(1 for r in logs if r.get("result") == "SUCCESS")
    return {"records": total, "success": success, "failed": total - success}


login_log_stats = get_login_log_stats


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:
    ensure_login_logs_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM login_logs
        WHERE date(COALESCE(login_time, created_at)) >= date(?)
          AND date(COALESCE(login_time, created_at)) <= date(?)
    """, (str(start_date), str(end_date)))
    deleted = int(cur.rowcount if cur.rowcount is not None else 0)
    if _table_exists(conn, "security_login_logs"):
        cur.execute("""
            DELETE FROM security_login_logs
            WHERE date(COALESCE(login_time, created_at)) >= date(?)
              AND date(COALESCE(login_time, created_at)) <= date(?)
        """, (str(start_date), str(end_date)))
        deleted += int(cur.rowcount if cur.rowcount is not None else 0)
    conn.commit()
    conn.close()
    try:
        export_audit_logs_to_permanent_file(create_history=True)
    except Exception:
        pass
    return deleted


clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range


def clear_login_logs_by_date(start_date: str, end_date: str, **kwargs: Any) -> int:
    return delete_login_logs_by_date_range(start_date, end_date)


clear_login_logs = clear_login_logs_by_date
clear_audit_logs_by_date = clear_login_logs_by_date


def _to_records(obj: Any) -> List[Dict[str, Any]]:
    if pd is not None and hasattr(obj, "to_dict"):
        return obj.to_dict(orient="records")
    return obj if isinstance(obj, list) else []


def export_audit_logs_to_permanent_file(create_history: bool = True) -> Dict[str, Any]:
    _ensure_dirs()
    ensure_login_logs_table()
    records = _to_records(load_login_logs(limit=100000, include_legacy=True))
    payload = {"version": "V1.49", "exported_at": _now(), "table": "login_logs", "count": len(records), "records": records}
    AUDIT_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MODULE_RECORDS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MODULE_SETTINGS_PATH.write_text(json.dumps({
        "version": "V1.49", "exported_at": _now(), "module": "11_login_logs",
        "settings": {"source_tables": ["login_logs", "security_login_logs"], "auto_github_upload_on_login": False}
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    hist = ""
    if create_history:
        ts = _now_file()
        hist_path = AUDIT_HISTORY_DIR / f"spt_audit_log_state_{ts}.json"
        hist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        module_hist = MODULE_DIR / "history" / f"11_login_logs_records_{ts}.json"
        module_hist.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        hist = str(hist_path)
    return {"ok": True, "message": "登入紀錄永久檔已建立", "count": len(records), "path": str(AUDIT_STATE_PATH), "history_path": hist}


build_audit_permanent_file = export_audit_logs_to_permanent_file
create_audit_permanent_file = export_audit_logs_to_permanent_file
create_login_log_permanent_file = export_audit_logs_to_permanent_file
build_login_log_permanent_file = export_audit_logs_to_permanent_file
save_audit_logs_to_permanent_file = export_audit_logs_to_permanent_file
export_audit_logs_to_state = export_audit_logs_to_permanent_file
create_audit_logs_state = export_audit_logs_to_permanent_file
build_audit_logs_state = export_audit_logs_to_permanent_file
export_login_logs_to_state = export_audit_logs_to_permanent_file


def restore_audit_logs_from_permanent_file(path: Optional[str] = None) -> Dict[str, Any]:
    _ensure_dirs()
    ensure_login_logs_table()
    src = Path(path) if path else AUDIT_STATE_PATH
    if not src.exists() and MODULE_RECORDS_PATH.exists():
        src = MODULE_RECORDS_PATH
    if not src.exists():
        return {"ok": False, "message": f"找不到登入紀錄永久檔：{src}", "count": 0}
    payload = json.loads(src.read_text(encoding="utf-8"))
    records = payload.get("records", []) if isinstance(payload, dict) else []
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM login_logs")
    for r in records:
        # skip legacy string id rows when restoring into integer pk
        rid = r.get("id")
        if not isinstance(rid, int):
            rid = None
        cur.execute("""
        INSERT INTO login_logs (
            id, username, display_name, event_type, result, message, module_code,
            login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (rid, r.get("username"), r.get("display_name"), r.get("event_type"),
              r.get("result"), r.get("message"), r.get("module_code"), r.get("login_time"),
              r.get("logout_time"), r.get("idle_minutes"), r.get("ip_address"), r.get("user_agent"), r.get("created_at")))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "登入紀錄已從永久檔還原", "count": len(records), "path": str(src)}


restore_login_logs_from_permanent_file = restore_audit_logs_from_permanent_file
restore_audit_logs = restore_audit_logs_from_permanent_file
restore_audit_logs_from_state = restore_audit_logs_from_permanent_file
restore_login_logs_from_state = restore_audit_logs_from_permanent_file


def upload_audit_logs_to_github() -> Dict[str, Any]:
    export_result = export_audit_logs_to_permanent_file(create_history=True)
    try:
        from services.github_cloud_storage_service import upload_file_to_github
    except Exception as exc:
        return {"ok": False, "message": f"GitHub 上傳服務不可用：{exc}", "export": export_result}
    uploads = []
    targets = [
        (AUDIT_STATE_PATH, "data/persistent_state/spt_audit_log_state.json"),
        (MODULE_RECORDS_PATH, "data/persistent_modules/11_login_logs/11_login_logs_records.json"),
        (MODULE_SETTINGS_PATH, "data/persistent_modules/11_login_logs/11_login_logs_settings.json"),
    ]
    hist_files = sorted(AUDIT_HISTORY_DIR.glob("spt_audit_log_state_*.json"))
    if hist_files:
        targets.append((hist_files[-1], f"data/persistent_state/audit_history/{hist_files[-1].name}"))
    ok_all = True
    for local_path, remote_path in targets:
        try:
            res = upload_file_to_github(str(local_path), remote_path)
        except Exception as exc:
            res = {"ok": False, "message": str(exc)}
        ok_all = ok_all and bool(res.get("ok"))
        uploads.append({"local": str(local_path), "remote": remote_path, "result": res})
    return {"ok": ok_all, "message": "登入紀錄 GitHub 上傳完成" if ok_all else "登入紀錄 GitHub 上傳有失敗項目", "uploads": uploads, "export": export_result}


upload_login_logs_to_github = upload_audit_logs_to_github
upload_audit_logs_to_github_cloud = upload_audit_logs_to_github
upload_audit_logs_to_state_github = upload_audit_logs_to_github


def get_audit_permanent_status() -> Dict[str, Any]:
    _ensure_dirs()
    exists = AUDIT_STATE_PATH.exists()
    count = 0
    exported_at = ""
    if exists:
        try:
            payload = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8"))
            count = int(payload.get("count", len(payload.get("records", []))))
            exported_at = str(payload.get("exported_at", ""))
        except Exception:
            pass
    return {"exists": exists, "path": str(AUDIT_STATE_PATH), "size": AUDIT_STATE_PATH.stat().st_size if exists else 0, "count": count, "exported_at": exported_at}


audit_permanent_status = get_audit_permanent_status
get_audit_state_status = get_audit_permanent_status
login_log_state_status = get_audit_permanent_status
get_login_log_permanent_status = get_audit_permanent_status


def bootstrap_audit_log_service() -> Dict[str, Any]:
    ensure_login_logs_table()
    _ensure_dirs()
    # Do not fabricate records unless DB is completely empty and page wants status.
    return {"ok": True, "message": "audit_log_service ready", "count": count_login_logs(include_legacy=True)}
