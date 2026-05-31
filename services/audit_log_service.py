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
PERMANENT_STORE_DIR = PROJECT_ROOT / "data" / "permanent_store"
DB_PATH = PERMANENT_STORE_DIR / "database" / "spt_time_tracking.db"
PERSISTENT_STATE_DIR = PERMANENT_STORE_DIR / "persistent_state"
AUDIT_HISTORY_DIR = PERSISTENT_STATE_DIR / "audit_history"
AUDIT_STATE_PATH = PERSISTENT_STATE_DIR / "spt_audit_log_state.json"
MODULE_DIR = PERMANENT_STORE_DIR / "persistent_modules" / "11_login_logs"
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



# ===== V74 LOGIN-ONLY NORMALIZATION / BAD ROW GUARD =====
# Page 11 is an audit page.  It must display only authentication/session events,
# never time-record/work-order rows that accidentally entered a generic log table.
_LOGIN_EVENT_TYPES = {
    "LOGIN", "LOGOUT", "AUTO_LOGOUT", "POST_RECORD_LOGOUT",
    "SESSION_TIMEOUT", "ACCESS_DENIED", "PERMISSION_DENIED",
    "LOGIN_FAIL", "AUTH_FAIL", "PASSWORD_CHANGE", "PASSWORD_RESET",
}
_LOGIN_RESULT_VALUES = {"SUCCESS", "FAIL", "FAILED", "DENIED", "ERROR", "WARNING", "INFO", "OK"}
_BAD_LOGIN_ROW_MARKERS = {
    "work_order", "part_no", "process_name", "start_time", "end_time",
    "record_key", "employee_id", "work_hours", "duration_hours",
}


def _txt(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _norm_token(value: Any) -> str:
    s = _txt(value).upper().strip()
    s = s.replace("-", "_").replace(" ", "_")
    return s


def _normalise_event_type(value: Any) -> str:
    s = _norm_token(value)
    aliases = {
        "LOG_IN": "LOGIN",
        "SIGN_IN": "LOGIN",
        "LOGIN_SUCCESS": "LOGIN",
        "登入": "LOGIN",
        "登入成功": "LOGIN",
        "LOGIN_FAILED": "LOGIN_FAIL",
        "LOGIN_FAILURE": "LOGIN_FAIL",
        "登入失敗": "LOGIN_FAIL",
        "LOG_OUT": "LOGOUT",
        "SIGN_OUT": "LOGOUT",
        "登出": "LOGOUT",
        "IDLE_LOGOUT": "AUTO_LOGOUT",
        "閒置登出": "AUTO_LOGOUT",
        "權限不足": "ACCESS_DENIED",
        "拒絕存取": "ACCESS_DENIED",
    }
    return aliases.get(s, s)


def _normalise_result(value: Any) -> str:
    s = _norm_token(value)
    aliases = {
        "成功": "SUCCESS",
        "OKAY": "SUCCESS",
        "PASS": "SUCCESS",
        "PASSED": "SUCCESS",
        "失敗": "FAIL",
        "FAILED": "FAIL",
        "FAILURE": "FAIL",
        "錯誤": "ERROR",
        "拒絕": "DENIED",
    }
    return aliases.get(s, s)


def _looks_like_time_record_payload(row: Dict[str, Any]) -> bool:
    keys = {str(k).lower() for k in (row or {}).keys()}
    if keys & _BAD_LOGIN_ROW_MARKERS:
        return True
    # Some corrupted rows were shifted into login columns:
    # username=record_key, event_type=part no, result=model, message=name.
    username = _txt(row.get("username"))
    event = _txt(row.get("event_type"))
    result = _txt(row.get("result"))
    if "|" in username:
        return True
    if event and (event.startswith("4TR") or event.startswith("9M") or event.startswith("25M") or event.startswith("26M")):
        return True
    if result and any(x in result.upper() for x in ("PORT", "EFEM", "SORTER", "RSC", "NTB")):
        return True
    return False


def _canonical_login_row(source: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a clean login/session log row, or None for non-login garbage."""
    if not isinstance(row, dict):
        return None
    d = dict(row)
    if _looks_like_time_record_payload(d):
        return None

    event_type = _normalise_event_type(d.get("event_type") or d.get("event") or d.get("action"))
    result = _normalise_result(d.get("result") or d.get("status") or "SUCCESS")
    username = _txt(d.get("username") or d.get("user_name") or d.get("account") or d.get("帳號"))
    display_name = _txt(d.get("display_name") or d.get("name") or d.get("display") or d.get("姓名"))
    module_code = _txt(d.get("module_code") or d.get("module") or d.get("module_name") or d.get("模組"))
    message = _txt(d.get("message") or d.get("msg") or d.get("note") or d.get("訊息"))
    login_time = _txt(d.get("login_time") or d.get("event_time") or d.get("login_at") or d.get("created_at") or d.get("log_time"))
    logout_time = _txt(d.get("logout_time") or d.get("logout_at"))
    created_at = _txt(d.get("created_at") or d.get("event_time") or d.get("login_time") or d.get("login_at") or d.get("log_time"))

    if not username or len(username) > 80 or "|" in username:
        return None
    if not event_type or event_type not in _LOGIN_EVENT_TYPES:
        return None
    if result and result not in _LOGIN_RESULT_VALUES:
        return None
    if not (login_time or created_at or logout_time):
        return None

    idle_minutes = d.get("idle_minutes")
    if idle_minutes in (None, "") and d.get("idle_seconds") not in (None, ""):
        try:
            idle_minutes = round(float(d.get("idle_seconds")) / 60, 2)
        except Exception:
            idle_minutes = None

    return {
        "id": d.get("id"),
        "source": source or _txt(d.get("source")) or "login_logs",
        "username": username,
        "display_name": display_name,
        "event_type": event_type,
        "result": result or "SUCCESS",
        "message": message,
        "module_code": module_code,
        "login_time": login_time or created_at or logout_time,
        "logout_time": logout_time,
        "idle_minutes": idle_minutes,
        "ip_address": _txt(d.get("ip_address") or d.get("ip") or ""),
        "user_agent": _txt(d.get("user_agent") or d.get("device") or ""),
        "created_at": created_at or login_time or logout_time,
    }


def _valid_login_rows(source: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        clean = _canonical_login_row(source, r)
        if clean is not None:
            out.append(clean)
    return out


def _auth_login_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Read 10.Permission auth_login_logs as the primary login source when present."""
    if not _table_exists(conn, "auth_login_logs"):
        return []
    rows = conn.execute("SELECT * FROM auth_login_logs ORDER BY id DESC").fetchall()
    return _valid_login_rows("auth_login_logs", [dict(r) for r in rows])


def _prune_invalid_primary_login_rows() -> int:
    """Delete only clearly invalid rows from login_logs, then export clean state.

    This protects Page 11 from old generic table dumps without touching real
    security_login_logs/auth_login_logs rows.
    """
    removed = 0
    try:
        conn = get_connection()
        if not _table_exists(conn, "login_logs"):
            conn.close()
            return 0
        rows = conn.execute("SELECT rowid AS _rowid_, * FROM login_logs").fetchall()
        bad_ids = []
        for r in rows:
            d = dict(r)
            clean = _canonical_login_row("login_logs", d)
            if clean is None:
                bad_ids.append(d.get("_rowid_"))
        if bad_ids:
            conn.executemany("DELETE FROM login_logs WHERE rowid=?", [(x,) for x in bad_ids])
            removed = len(bad_ids)
            conn.commit()
        conn.close()
    except Exception:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass
    return removed
# ===== V74 LOGIN-ONLY NORMALIZATION / BAD ROW GUARD END =====


def _security_login_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Read legacy security_login_logs rows if that table exists."""
    if not _table_exists(conn, "security_login_logs"):
        return []
    rows = conn.execute("SELECT * FROM security_login_logs ORDER BY id DESC").fetchall()
    return _valid_login_rows("security_login_logs", [dict(r) for r in rows])


def _primary_login_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    ensure_login_logs_table()
    rows = conn.execute("SELECT * FROM login_logs ORDER BY id DESC").fetchall()
    return _valid_login_rows("login_logs", [dict(r) for r in rows])


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
    # Clean only obviously bad rows that entered login_logs from non-login tables.
    _prune_invalid_primary_login_rows()
    conn = get_connection()
    records = _primary_login_rows(conn)
    if include_legacy:
        # Include both current security_service table and older permission_service table.
        records.extend(_security_login_rows(conn))
        records.extend(_auth_login_rows(conn))
    conn.close()
    records = _merge_record_sets(records)
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
        if total:
            result_s = logs.get("result", "").astype(str).str.upper()
            success = int(result_s.isin(["SUCCESS", "OK", "INFO"]).sum())
        else:
            success = 0
        return {"records": total, "success": success, "failed": total - success}
    total = len(logs)
    success = sum(1 for r in logs if _normalise_result(r.get("result")) in {"SUCCESS", "OK", "INFO"})
    return {"records": total, "success": success, "failed": total - success}

login_log_stats = get_login_log_stats


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:
    """Delete login logs by date range and make the cleared state authoritative.

    V17 修正：部分資料表日期欄位格式不一致時，date(COALESCE(...)) 可能比對不到，
    造成畫面顯示清除成功但實際 rowcount=0。這裡會依各表可用欄位建立較寬鬆
    條件，並在清除後立即覆寫 latest 記憶檔，避免 Reboot 又從舊檔還原。
    """
    ensure_login_logs_table()
    conn = get_connection()
    cur = conn.cursor()
    deleted = 0

    def _cols(table: str) -> set[str]:
        try:
            return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    table_date_cols = {
        "login_logs": ["login_time", "created_at", "logout_time"],
        "security_login_logs": ["login_time", "created_at", "logout_time"],
        "auth_login_logs": ["login_at", "login_time", "created_at"],
    }
    for table, wanted_cols in table_date_cols.items():
        try:
            if table != "login_logs" and not _table_exists(conn, table):
                continue
            cols = [c for c in wanted_cols if c in _cols(table)]
            if not cols:
                continue
            exprs = [f"date(substr(COALESCE({c}, ''), 1, 10)) BETWEEN date(?) AND date(?)" for c in cols]
            where_sql = " OR ".join(exprs)
            params: list[str] = []
            for _ in cols:
                params.extend([str(start_date), str(end_date)])
            cur.execute(f"DELETE FROM {table} WHERE {where_sql}", tuple(params))
            deleted += int(cur.rowcount if cur.rowcount is not None else 0)
        except Exception:
            continue
    conn.commit()
    conn.close()
    try:
        export_audit_logs_to_permanent_file(create_history=True, merge_existing=False)
        try:
            from services.permanent_write_through_service import github_write_through_files
            github_write_through_files([AUDIT_STATE_PATH, MODULE_RECORDS_PATH, MODULE_SETTINGS_PATH], source="v17_clear_login_logs", force=True)
        except Exception:
            pass
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


def _login_record_key(r: Dict[str, Any]) -> str:
    """Stable de-dup key for login/audit records across DB and JSON backups."""
    return "|".join([
        str(r.get("source") or ""),
        str(r.get("username") or ""),
        str(r.get("event_type") or ""),
        str(r.get("result") or ""),
        str(r.get("login_time") or r.get("created_at") or ""),
        str(r.get("module_code") or ""),
        str(r.get("message") or ""),
    ])


def _normalise_backup_row(table_name: str, row: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(row or {})
    if table_name in {"security_login_logs", "auth_login_logs"}:
        idle_seconds = d.get("idle_seconds")
        try:
            idle_minutes = round(float(idle_seconds) / 60, 2) if idle_seconds not in (None, "") else d.get("idle_minutes")
        except Exception:
            idle_minutes = d.get("idle_minutes")
        return {
            "id": f"S{d.get('id')}" if table_name == "security_login_logs" and d.get("id") is not None else d.get("id"),
            "source": table_name,
            "username": d.get("username") or d.get("user_name"),
            "display_name": d.get("display_name") or d.get("name"),
            "event_type": d.get("event_type") or d.get("event") or "LOGIN",
            "result": d.get("result") or "SUCCESS",
            "message": d.get("message") or "",
            "module_code": d.get("module_code") or d.get("module") or "",
            "login_time": d.get("login_time") or d.get("created_at") or d.get("log_time"),
            "logout_time": d.get("logout_time"),
            "idle_minutes": idle_minutes,
            "ip_address": d.get("ip_address") or "",
            "user_agent": d.get("user_agent") or "",
            "created_at": d.get("created_at") or d.get("login_time") or d.get("log_time"),
        }
    d.setdefault("source", table_name or "login_logs")
    return d


def _extract_login_records_from_payload(payload: Any) -> List[Dict[str, Any]]:
    """Support every historical permanent format used by this project.

    Older exports used top-level records; module-persistence exports used
    tables.login_logs / tables.security_login_logs.  Page 11 must recover from
    all formats after Reboot App, otherwise it looks like login logs disappeared.
    """
    if not isinstance(payload, dict):
        return []
    out: List[Dict[str, Any]] = []
    top_records = payload.get("records")
    if isinstance(top_records, list):
        out.extend(_normalise_backup_row("login_logs", r) for r in top_records if isinstance(r, dict))
    tables = payload.get("tables")
    if isinstance(tables, dict):
        for table_name in ("login_logs", "security_login_logs", "auth_login_logs"):
            rows = tables.get(table_name, [])
            if isinstance(rows, list):
                out.extend(_normalise_backup_row(table_name, r) for r in rows if isinstance(r, dict))
    # de-duplicate while preserving chronological content, and discard any
    # records that are not real login/session events.
    merged: Dict[str, Dict[str, Any]] = {}
    for r in out:
        clean = _canonical_login_row(str(r.get("source") or "login_logs"), r)
        if clean is None:
            continue
        key = _login_record_key(clean)
        if key.strip("|"):
            merged[key] = clean
    return list(merged.values())


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _permanent_candidate_paths() -> List[Path]:
    """Return login-log permanent candidates in authority order.

    V17: do not let old history files with more rows override the latest file.
    Clear Login Logs must stay cleared after Reboot, so the current latest JSON
    is the authority.  History is only a fallback when latest files are missing.
    """
    paths: List[Path] = [AUDIT_STATE_PATH, MODULE_RECORDS_PATH]
    if not any(p.exists() and p.stat().st_size > 2 for p in paths):
        paths.extend(sorted(AUDIT_HISTORY_DIR.glob("spt_audit_log_state_*.json"), reverse=True)[:3])
        paths.extend(sorted((MODULE_DIR / "history").glob("11_login_logs_records_*.json"), reverse=True)[:3])
    seen = set()
    unique = []
    for x in paths:
        sx = str(x)
        if sx not in seen:
            seen.add(sx)
            unique.append(x)
    return unique


def _payload_timestamp(payload: Any, path: Path) -> str:
    if isinstance(payload, dict):
        for k in ("exported_at", "updated_at", "created_at"):
            v = payload.get(k)
            if v:
                return str(v)
    try:
        return str(path.stat().st_mtime)
    except Exception:
        return ""


def _best_permanent_records() -> tuple[List[Dict[str, Any]], str]:
    """Pick the newest authority file, not the biggest old backup.

    The previous count-based selection caused deleted login logs to come back
    because an older history backup had more rows than the newly-cleared latest file.
    """
    best: List[Dict[str, Any]] = []
    best_path = ""
    best_ts = ""
    for path in _permanent_candidate_paths():
        payload = _read_json_file(path)
        records = _extract_login_records_from_payload(payload)
        ts = _payload_timestamp(payload, path)
        if records or path.exists():
            if not best_path or ts >= best_ts:
                best = records
                best_path = str(path)
                best_ts = ts
    return best, best_path


def _merge_record_sets(*sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for rows in sets:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            key = _login_record_key(r)
            if key.strip("|"):
                merged[key] = r
    rows = list(merged.values())
    rows.sort(key=lambda r: str(r.get("login_time") or r.get("created_at") or ""), reverse=True)
    return rows


def _db_login_count(include_legacy: bool = True) -> int:
    try:
        logs = load_login_logs(limit=100000, include_legacy=include_legacy)
        return int(len(logs))
    except Exception:
        return 0


def restore_audit_logs_from_permanent_file(path: Optional[str] = None, merge: bool = False) -> Dict[str, Any]:
    _ensure_dirs()
    ensure_login_logs_table()
    if path:
        src = Path(path)
        records = _extract_login_records_from_payload(_read_json_file(src))
    else:
        records, best_path = _best_permanent_records()
        src = Path(best_path) if best_path else AUDIT_STATE_PATH
    if not records:
        return {"ok": False, "message": f"找不到可還原的登入紀錄永久檔：{src}", "count": 0}

    conn = get_connection()
    cur = conn.cursor()
    existing_keys = set()
    if merge:
        for r in _primary_login_rows(conn):
            existing_keys.add(_login_record_key(r))
    else:
        cur.execute("DELETE FROM login_logs")
    inserted = 0
    for r in records:
        if merge and _login_record_key(r) in existing_keys:
            continue
        # Do not preserve ids during merge; SQLite will assign a safe id.
        rid = r.get("id") if not merge else None
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
        inserted += 1
    conn.commit()
    conn.close()
    return {"ok": True, "message": "登入紀錄已從永久檔還原", "count": inserted, "source_count": len(records), "path": str(src)}


def _auto_restore_if_db_lacks_permanent_records() -> Dict[str, Any]:
    """Restore/merge when Streamlit Cloud reboot leaves SQLite with fewer logs.

    This is the real protection: login itself writes a new row after reboot, so DB is
    not always zero.  We compare counts and merge if permanent JSON has more.
    """
    try:
        db_count = _db_login_count(include_legacy=True)
        permanent_records, src = _best_permanent_records()
        if permanent_records and len(permanent_records) > db_count:
            res = restore_audit_logs_from_permanent_file(src, merge=True)
            res["auto_restored"] = True
            return res
        return {"ok": True, "auto_restored": False, "db_count": db_count, "permanent_count": len(permanent_records), "path": src}
    except Exception as exc:
        return {"ok": False, "auto_restored": False, "message": str(exc)}


def export_audit_logs_to_permanent_file(create_history: bool = True, merge_existing: bool = True) -> Dict[str, Any]:
    _ensure_dirs()
    ensure_login_logs_table()
    db_records = _to_records(load_login_logs(limit=100000, include_legacy=True))
    existing_records, _src = _best_permanent_records()
    # Normal login writes merge with existing records.  Clear/delete operations must
    # be able to overwrite the latest file with fewer rows, otherwise deleted logs
    # come back after Reboot App.
    records = _merge_record_sets(existing_records, db_records) if merge_existing else db_records
    payload = {
        "version": "V1.50",
        "exported_at": _now(),
        "source": "audit_log_service",
        "module_key": "11_login_logs",
        "module_code": "11_login_logs",
        "module_name_zh": "登入紀錄",
        "module_name_en": "Login Logs",
        "table": "login_logs",
        "count": len(records),
        "records": records,
        "tables": {"login_logs": records},
        "table_counts": {"login_logs": len(records)},
    }
    tmp_state = AUDIT_STATE_PATH.with_suffix(".tmp")
    tmp_module = MODULE_RECORDS_PATH.with_suffix(".tmp")
    tmp_state.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_module.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_state.replace(AUDIT_STATE_PATH)
    tmp_module.replace(MODULE_RECORDS_PATH)
    MODULE_SETTINGS_PATH.write_text(json.dumps({
        "version": "V1.50", "exported_at": _now(), "module": "11_login_logs",
        "settings": {"source_tables": ["login_logs", "security_login_logs", "auth_login_logs"], "auto_github_upload_on_login": False}
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
        (AUDIT_STATE_PATH, "data/permanent_store/persistent_state/spt_audit_log_state.json"),
        (MODULE_RECORDS_PATH, "data/permanent_store/persistent_modules/11_login_logs/11_login_logs_records.json"),
        (MODULE_SETTINGS_PATH, "data/permanent_store/persistent_modules/11_login_logs/11_login_logs_settings.json"),
    ]
    hist_files = sorted(AUDIT_HISTORY_DIR.glob("spt_audit_log_state_*.json"))
    if hist_files:
        targets.append((hist_files[-1], f"data/permanent_store/persistent_state/audit_history/{hist_files[-1].name}"))
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
    records, best_path = _best_permanent_records()
    path = Path(best_path) if best_path else AUDIT_STATE_PATH
    payload = _read_json_file(path)
    return {
        "exists": bool(best_path),
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "count": len(records),
        "exported_at": str(payload.get("exported_at", "")) if isinstance(payload, dict) else "",
        "db_count": _db_login_count(include_legacy=True),
    }


audit_permanent_status = get_audit_permanent_status
get_audit_state_status = get_audit_permanent_status
login_log_state_status = get_audit_permanent_status
get_login_log_permanent_status = get_audit_permanent_status


def bootstrap_audit_log_service() -> Dict[str, Any]:
    ensure_login_logs_table()
    _ensure_dirs()
    removed = _prune_invalid_primary_login_rows()
    restore_res = _auto_restore_if_db_lacks_permanent_records()
    if removed:
        try:
            export_audit_logs_to_permanent_file(create_history=False, merge_existing=False)
        except Exception:
            pass
    return {"ok": True, "message": "audit_log_service ready", "count": count_login_logs(include_legacy=True), "restore": restore_res, "removed_invalid_login_rows": removed}


# ===== V16 ROBUST LOGIN LOG DELETE =====
def _v16_parse_date(value: Any):
    """Parse common Taiwan/SQLite datetime strings into date()."""
    if value in (None, ''):
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace('T', ' ').replace('/', '-').replace('.', '-')
    # Remove timezone suffix conservatively for date parsing.
    if '+' in s:
        s = s.split('+', 1)[0].strip()
    if s.endswith('Z'):
        s = s[:-1]
    candidates = [
        s[:10],
        s.split(' ')[0],
        s,
    ]
    for c in candidates:
        for fmt in ('%Y-%m-%d', '%Y%m%d'):
            try:
                return datetime.strptime(c, fmt).date()
            except Exception:
                pass
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def _v16_row_log_date(row: Dict[str, Any]):
    for key in ('login_time', 'login_at', 'created_at', 'log_time', 'event_time', 'timestamp'):
        d = _v16_parse_date(row.get(key))
        if d is not None:
            return d
    return None


def _v16_export_audit_logs_from_db_only(create_history: bool = True) -> Dict[str, Any]:
    """Export current DB state only.

    Used after deletion.  The normal export intentionally merges old permanent records
    to protect against accidental data loss after reboot; that behavior is wrong after
    an explicit Clear Login Logs action because it resurrects deleted rows.
    """
    _ensure_dirs()
    ensure_login_logs_table()
    db_records = _to_records(load_login_logs(limit=100000, include_legacy=True))
    payload = {
        'version': 'V1.60-delete-aware',
        'exported_at': _now(),
        'source': 'audit_log_service.delete_aware',
        'module_key': '11_login_logs',
        'module_code': '11_login_logs',
        'module_name_zh': '登入紀錄',
        'module_name_en': 'Login Logs',
        'table': 'login_logs',
        'count': len(db_records),
        'records': db_records,
        'tables': {'login_logs': db_records},
        'table_counts': {'login_logs': len(db_records)},
    }
    AUDIT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODULE_RECORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path in (AUDIT_STATE_PATH, MODULE_RECORDS_PATH):
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        tmp.replace(path)
    MODULE_SETTINGS_PATH.write_text(json.dumps({
        'version': 'V1.60-delete-aware',
        'exported_at': _now(),
        'module': '11_login_logs',
        'settings': {'source_tables': ['login_logs', 'security_login_logs', 'auth_login_logs'], 'delete_aware': True},
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    hist = ''
    if create_history:
        ts = _now_file()
        hist_path = AUDIT_HISTORY_DIR / f'spt_audit_log_state_{ts}.json'
        hist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        module_hist = MODULE_DIR / 'history' / f'11_login_logs_records_{ts}.json'
        module_hist.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        hist = str(hist_path)
    return {'ok': True, 'message': '登入紀錄永久檔已依刪除後 DB 狀態更新', 'count': len(db_records), 'path': str(AUDIT_STATE_PATH), 'history_path': hist}


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:  # type: ignore[override]
    """Delete login logs by Python date parsing, then export DB-only state.

    Fixes no-op deletes caused by SQLite date() not parsing strings like
    2026/05/20 08:00:00 and prevents deleted rows from being merged back from
    permanent JSON on the next Reboot App.
    """
    ensure_login_logs_table()
    start_d = _v16_parse_date(start_date)
    end_d = _v16_parse_date(end_date)
    if start_d is None or end_d is None:
        return 0
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    conn = get_connection()
    cur = conn.cursor()
    deleted = 0
    for table in ('login_logs', 'security_login_logs', 'auth_login_logs'):
        try:
            if not _table_exists(conn, table):
                continue
            rows = conn.execute(f'SELECT rowid AS _rowid_, * FROM {table}').fetchall()
            rowids = []
            for r in rows:
                d = dict(r)
                rd = _v16_row_log_date(d)
                if rd is not None and start_d <= rd <= end_d:
                    rowids.append(d.get('_rowid_'))
            if rowids:
                cur.executemany(f'DELETE FROM {table} WHERE rowid=?', [(x,) for x in rowids])
                deleted += len(rowids)
        except Exception:
            continue
    conn.commit()
    conn.close()

    try:
        _v16_export_audit_logs_from_db_only(create_history=True)
        try:
            from services.permanent_write_through_service import github_write_through_files
            github_write_through_files([AUDIT_STATE_PATH, MODULE_RECORDS_PATH, MODULE_SETTINGS_PATH], source='v16_clear_login_logs_delete_aware')
        except Exception:
            pass
    except Exception:
        pass
    return int(deleted)


clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_login_logs_by_date = delete_login_logs_by_date_range
clear_login_logs = delete_login_logs_by_date_range
clear_audit_logs_by_date = delete_login_logs_by_date_range
# ===== V16 ROBUST LOGIN LOG DELETE END =====

# ===== V97 LOGIN LOG SINGLE-AUTHORITY DELETE-PERSIST FIX START =====
# 目的：11｜登入紀錄刪除後不可再從舊 persistent_state / history 復活。
# 新增同專案權威檔：data/permanent_store/modules/11_login_logs/records.json。
# 讀取順序固定：canonical latest -> legacy latest；history 只在 latest 全部不存在時才 fallback。

_V97_LOGIN_AUTHORITY_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "records.json"
_v97_prev_export_audit_logs_to_permanent_file = export_audit_logs_to_permanent_file
_v97_prev_delete_login_logs_by_date_range = delete_login_logs_by_date_range


def _v97_write_login_authority(records: List[Dict[str, Any]], reason: str = "login_logs_v97") -> None:
    try:
        from services.permanent_authority_service import save_authority
        clean = _merge_record_sets(_valid_login_rows("v97_authority", records or []))
        save_authority("11_login_logs", records={"login_logs": clean}, reason=reason, github=True)
    except Exception:
        try:
            payload = {
                "authority_schema": "SPT-PermanentAuthority-V97",
                "module_key": "11_login_logs",
                "kind": "records",
                "reason": reason,
                "updated_at": _now(),
                "tables": {"login_logs": records or []},
                "table_counts": {"login_logs": len(records or [])},
            }
            _V97_LOGIN_AUTHORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _V97_LOGIN_AUTHORITY_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(_V97_LOGIN_AUTHORITY_PATH)
        except Exception:
            pass


def _v97_read_login_authority_records() -> List[Dict[str, Any]]:
    try:
        if not _V97_LOGIN_AUTHORITY_PATH.exists() or _V97_LOGIN_AUTHORITY_PATH.stat().st_size <= 2:
            return []
        payload = _read_json_file(_V97_LOGIN_AUTHORITY_PATH)
        rows: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
            for t in ("login_logs", "security_login_logs", "auth_login_logs"):
                rows.extend([dict(r) for r in tables.get(t, []) if isinstance(r, dict)])
            if not rows:
                rows.extend(_extract_login_records_from_payload(payload))
        return _merge_record_sets(_valid_login_rows("v97_canonical", rows))
    except Exception:
        return []


def _permanent_candidate_paths() -> List[Path]:  # type: ignore[override]
    latest: List[Path] = [_V97_LOGIN_AUTHORITY_PATH, AUDIT_STATE_PATH, MODULE_RECORDS_PATH]
    existing_latest = [p for p in latest if p.exists() and p.stat().st_size > 2]
    paths: List[Path] = list(existing_latest)
    if not existing_latest:
        paths.extend(sorted(AUDIT_HISTORY_DIR.glob("spt_audit_log_state_*.json"), reverse=True)[:3])
        paths.extend(sorted((MODULE_DIR / "history").glob("11_login_logs_records_*.json"), reverse=True)[:3])
    seen: set[str] = set(); unique: List[Path] = []
    for p in paths:
        sp = str(p)
        if sp not in seen:
            seen.add(sp); unique.append(p)
    return unique


def _best_permanent_records() -> tuple[List[Dict[str, Any]], str]:  # type: ignore[override]
    canonical = _v97_read_login_authority_records()
    if _V97_LOGIN_AUTHORITY_PATH.exists():
        return canonical, str(_V97_LOGIN_AUTHORITY_PATH)
    best: List[Dict[str, Any]] = []
    best_path = ""; best_ts = ""
    for path in _permanent_candidate_paths():
        payload = _read_json_file(path)
        records = _extract_login_records_from_payload(payload)
        ts = _payload_timestamp(payload, path)
        if records or path.exists():
            if not best_path or ts >= best_ts:
                best = records; best_path = str(path); best_ts = ts
    return best, best_path


def export_audit_logs_to_permanent_file(create_history: bool = True, merge_existing: bool = True) -> Dict[str, Any]:  # type: ignore[override]
    # 先沿用原本匯出邏輯，確保 legacy latest 檔仍保持相容；再額外寫 canonical 權威檔。
    res = _v97_prev_export_audit_logs_to_permanent_file(create_history=create_history, merge_existing=merge_existing)
    try:
        records = _to_records(load_login_logs(limit=100000, include_legacy=True))
        if merge_existing:
            old_records, _ = _best_permanent_records()
            records = _merge_record_sets(old_records, records)
        _v97_write_login_authority(records, "export_login_logs_v97_merge" if merge_existing else "export_login_logs_v97_db_only")
        res["v97_authority_file"] = str(_V97_LOGIN_AUTHORITY_PATH)
        res["v97_authority_count"] = len(records)
    except Exception as exc:
        res["v97_authority_error"] = str(exc)[:300]
    return res


def _v97_export_login_logs_from_db_only(create_history: bool = True) -> Dict[str, Any]:
    # 刪除後必須只以目前 DB 狀態覆寫，不得 merge 舊永久檔。
    res = _v16_export_audit_logs_from_db_only(create_history=create_history) if "_v16_export_audit_logs_from_db_only" in globals() else {"ok": True}
    records = _to_records(load_login_logs(limit=100000, include_legacy=True))
    _v97_write_login_authority(records, "delete_login_logs_v97_db_only_authority")
    res["v97_authority_file"] = str(_V97_LOGIN_AUTHORITY_PATH)
    res["v97_authority_count"] = len(records)
    return res


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:  # type: ignore[override]
    deleted = int(_v97_prev_delete_login_logs_by_date_range(start_date, end_date) or 0)
    try:
        _v97_export_login_logs_from_db_only(create_history=True)
    except Exception:
        pass
    return deleted


clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_login_logs_by_date = delete_login_logs_by_date_range
clear_login_logs = delete_login_logs_by_date_range
clear_audit_logs_by_date = delete_login_logs_by_date_range
restore_login_logs_from_permanent_file = restore_audit_logs_from_permanent_file
restore_audit_logs_from_state = restore_audit_logs_from_permanent_file
# ===== V97 LOGIN LOG SINGLE-AUTHORITY DELETE-PERSIST FIX END =====


# ===== V103 LOGIN LOG CANONICAL DELETE + DISPLAY FIX START =====
# 目的：11｜登入紀錄的「清除」必須直接修改正式權威檔，不能只刪 SQLite / 舊 persistent 檔。
# 修正重點：
# 1. load_login_logs 會合併 canonical authority + SQLite current rows，避免頁面看起來沒讀權威檔。
# 2. delete_login_logs_by_date_range 會先從所有來源彙整，再依日期範圍過濾，最後用剩餘資料覆寫 canonical。
# 3. 刪到 0 筆時也會寫入空權威檔，避免 Reboot App 從舊 history / persistent_modules 復活。
# 4. 仍保留舊 AUDIT_STATE_PATH / MODULE_RECORDS_PATH 相容寫入，但 canonical records.json 是唯一判準。

_V103_LOGIN_AUTHORITY_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "records.json"
_v103_prev_load_login_logs = load_login_logs
_v103_prev_get_login_log_stats = get_login_log_stats
_v103_prev_get_audit_permanent_status = get_audit_permanent_status


def _v103_parse_row_date(row: Dict[str, Any]):
    try:
        return _v16_row_log_date(row) if "_v16_row_log_date" in globals() else None
    except Exception:
        return None


def _v103_record_key(row: Dict[str, Any]) -> str:
    return "|".join([
        _txt(row.get("username")),
        _normalise_event_type(row.get("event_type")),
        _normalise_result(row.get("result")),
        _txt(row.get("login_time") or row.get("created_at") or row.get("logout_time")),
        _txt(row.get("module_code")),
        _txt(row.get("message")),
    ])


def _v103_merge_login_rows(*sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for rows in sets:
        for row in _valid_login_rows("v103_merge", rows or []):
            key = _v103_record_key(row)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _v103_read_authority_login_records() -> List[Dict[str, Any]]:
    """Read canonical records.json first; fall back to V97 helper if present."""
    rows: List[Dict[str, Any]] = []
    try:
        from services.permanent_authority_service import load_authority
        payload = load_authority("11_login_logs", "records")
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        for table in ("login_logs", "auth_login_logs", "security_login_logs"):
            vals = tables.get(table, [])
            if isinstance(vals, list):
                rows.extend([dict(x) for x in vals if isinstance(x, dict)])
    except Exception:
        pass
    try:
        if not rows and "_v97_read_login_authority_records" in globals():
            rows.extend(_v97_read_login_authority_records())  # type: ignore[name-defined]
    except Exception:
        pass
    try:
        if not rows and _V103_LOGIN_AUTHORITY_PATH.exists():
            payload = _read_json_file(_V103_LOGIN_AUTHORITY_PATH)
            rows.extend(_extract_login_records_from_payload(payload))
    except Exception:
        pass
    return _v103_merge_login_rows(rows)


def _v103_db_login_records(include_legacy: bool = True) -> List[Dict[str, Any]]:
    ensure_login_logs_table()
    try:
        _prune_invalid_primary_login_rows()
    except Exception:
        pass
    conn = get_connection()
    try:
        records = _primary_login_rows(conn)
        if include_legacy:
            records.extend(_security_login_rows(conn))
            records.extend(_auth_login_rows(conn))
        return _v103_merge_login_rows(records)
    finally:
        conn.close()


def _v103_all_current_login_records(include_legacy: bool = True) -> List[Dict[str, Any]]:
    authority_rows = _v103_read_authority_login_records()
    db_rows = _v103_db_login_records(include_legacy=include_legacy)
    return _v103_merge_login_rows(authority_rows, db_rows)


def _v103_write_legacy_login_files(records: List[Dict[str, Any]], reason: str) -> None:
    """Write old permanent files too, only for compatibility. Canonical remains source of truth."""
    _ensure_dirs()
    clean = _v103_merge_login_rows(records or [])
    payload = {
        "version": "V103-canonical-login-logs",
        "authority_schema": "SPT-PermanentAuthority-V103-CompatibilityMirror",
        "exported_at": _now(),
        "updated_at": _now(),
        "source": reason,
        "module_key": "11_login_logs",
        "module_code": "11_login_logs",
        "module_name_zh": "登入紀錄",
        "module_name_en": "Login Logs",
        "table": "login_logs",
        "count": len(clean),
        "records": clean,
        "tables": {"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
        "table_counts": {"login_logs": len(clean), "auth_login_logs": 0, "security_login_logs": 0},
        "empty_authoritative": len(clean) == 0,
    }
    for path in (AUDIT_STATE_PATH, MODULE_RECORDS_PATH):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass
    try:
        MODULE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODULE_SETTINGS_PATH.write_text(json.dumps({
            "version": "V103-canonical-login-logs",
            "exported_at": _now(),
            "module": "11_login_logs",
            "settings": {"source_tables": ["login_logs"], "canonical_authority": str(_V103_LOGIN_AUTHORITY_PATH)},
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _v103_write_authority_login_records(records: List[Dict[str, Any]], reason: str = "v103_login_logs") -> Dict[str, Any]:
    clean = _v103_merge_login_rows(records or [])
    result: Dict[str, Any] = {"ok": True, "count": len(clean), "files": [], "github": []}
    try:
        from services.permanent_authority_service import save_authority, canonical_path
        result = save_authority(
            "11_login_logs",
            records={"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
            reason=reason,
            github=True,
        )
        result["count"] = len(clean)
        result["canonical_path"] = str(canonical_path("11_login_logs", "records"))
    except Exception as exc:
        result = {"ok": False, "count": len(clean), "error": str(exc)[:300], "files": [str(_V103_LOGIN_AUTHORITY_PATH)]}
        try:
            payload = {
                "authority_schema": "SPT-PermanentAuthority-V103",
                "module_key": "11_login_logs",
                "kind": "records",
                "updated_at": _now(),
                "exported_at": _now(),
                "reason": reason,
                "empty_authoritative": len(clean) == 0,
                "tables": {"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
                "table_counts": {"login_logs": len(clean), "auth_login_logs": 0, "security_login_logs": 0},
            }
            _V103_LOGIN_AUTHORITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _V103_LOGIN_AUTHORITY_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(_V103_LOGIN_AUTHORITY_PATH)
            result["ok"] = True
        except Exception as exc2:
            result["fallback_error"] = str(exc2)[:300]
    _v103_write_legacy_login_files(clean, reason)
    try:
        from services.permanent_write_through_service import github_write_through_files
        github_write_through_files([_V103_LOGIN_AUTHORITY_PATH, AUDIT_STATE_PATH, MODULE_RECORDS_PATH, MODULE_SETTINGS_PATH], source=reason, force=True)
    except Exception:
        pass
    return result


def _v103_replace_db_with_login_records(records: List[Dict[str, Any]]) -> None:
    """Make SQLite cache match canonical state; legacy login tables are cleared to stop resurrection."""
    ensure_login_logs_table()
    clean = _v103_merge_login_rows(records or [])
    conn = get_connection()
    cur = conn.cursor()
    try:
        for table in ("login_logs", "security_login_logs", "auth_login_logs"):
            try:
                if table == "login_logs" or _table_exists(conn, table):
                    cur.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        for r in clean:
            cur.execute("""
            INSERT INTO login_logs (
                username, display_name, event_type, result, message, module_code,
                login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r.get("username"), r.get("display_name"), r.get("event_type"), r.get("result"),
                r.get("message"), r.get("module_code"), r.get("login_time"), r.get("logout_time"),
                r.get("idle_minutes"), r.get("ip_address"), r.get("user_agent"), r.get("created_at"),
            ))
        conn.commit()
    finally:
        conn.close()


def load_login_logs(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "",
                    limit: int = 1000, event_types: Optional[List[str]] = None,
                    results: Optional[List[str]] = None, include_legacy: bool = True, **kwargs: Any):  # type: ignore[override]
    # V103: page 11 must visibly read canonical authority, then merge same-session SQLite rows.
    records = _v103_all_current_login_records(include_legacy=include_legacy)
    records = _filter_records(records, start_date, end_date, keyword, event_types, results)
    records.sort(key=lambda r: str(r.get("login_time") or r.get("created_at") or ""), reverse=True)
    if limit:
        records = records[:int(limit)]
    if pd is not None:
        return pd.DataFrame(records)
    return records


def get_login_log_stats(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "") -> Dict[str, int]:  # type: ignore[override]
    logs = load_login_logs(start_date=start_date, end_date=end_date, keyword=keyword, limit=100000)
    if pd is not None and hasattr(logs, "empty"):
        total = int(len(logs))
        if total:
            result_s = logs.get("result", "").astype(str).str.upper()
            success = int(result_s.isin(["SUCCESS", "OK", "INFO"]).sum())
        else:
            success = 0
        return {"records": total, "success": success, "failed": total - success}
    total = len(logs)
    success = sum(1 for r in logs if _normalise_result(r.get("result")) in {"SUCCESS", "OK", "INFO"})
    return {"records": total, "success": success, "failed": total - success}


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:  # type: ignore[override]
    start_d = _v16_parse_date(start_date) if "_v16_parse_date" in globals() else None
    end_d = _v16_parse_date(end_date) if "_v16_parse_date" in globals() else None
    if start_d is None or end_d is None:
        return 0
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    before = _v103_all_current_login_records(include_legacy=True)
    remaining: List[Dict[str, Any]] = []
    deleted = 0
    for row in before:
        rd = _v103_parse_row_date(row)
        if rd is not None and start_d <= rd <= end_d:
            deleted += 1
        else:
            remaining.append(row)
    remaining = _v103_merge_login_rows(remaining)

    # The selected range is authoritative even when deleted == 0; this still rewrites
    # canonical from the current non-deleted set and clears legacy tables.
    _v103_replace_db_with_login_records(remaining)
    _v103_write_authority_login_records(remaining, reason="v103_clear_login_logs_date_range")
    return int(deleted)


def get_audit_permanent_status() -> Dict[str, Any]:  # type: ignore[override]
    records = _v103_read_authority_login_records()
    path = _V103_LOGIN_AUTHORITY_PATH
    payload = _read_json_file(path) if path.exists() else {}
    return {
        "exists": path.exists(),
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "count": len(records),
        "exported_at": str(payload.get("exported_at") or payload.get("updated_at") or "") if isinstance(payload, dict) else "",
        "db_count": len(_v103_db_login_records(include_legacy=True)),
        "authority_schema": str(payload.get("authority_schema", "")) if isinstance(payload, dict) else "",
    }


clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_login_logs_by_date = delete_login_logs_by_date_range
clear_login_logs = delete_login_logs_by_date_range
clear_audit_logs_by_date = delete_login_logs_by_date_range
get_login_logs = load_login_logs
query_login_logs = load_login_logs
load_audit_logs = load_login_logs
login_log_stats = get_login_log_stats
audit_permanent_status = get_audit_permanent_status
get_audit_state_status = get_audit_permanent_status
login_log_state_status = get_audit_permanent_status
get_login_log_permanent_status = get_audit_permanent_status
# ===== V103 LOGIN LOG CANONICAL DELETE + DISPLAY FIX END =====


# ===== V104 LOGIN LOG DATE CLEAR AUTHORITY HARDENING START =====
# 修正重點：
# 1) 11｜登入紀錄清除時，畫面查詢與刪除必須使用同一套日期解析；支援 2026/05/22、2026-05-22、含時間字串。
# 2) 清除後 canonical records.json、legacy json、SQLite cache 三者同步成同一份剩餘資料。
# 3) 即使刪除 0 筆也會重新寫權威檔，讓畫面可確認已執行權威檔讀寫。

def _v104_parse_any_date(value: Any):
    if value in (None, ""):
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("/", "-").replace(".", "-")
    if "+" in s:
        s = s.split("+", 1)[0].strip()
    if s.endswith("Z"):
        s = s[:-1].strip()
    candidates = []
    try:
        candidates.append(s[:10])
    except Exception:
        pass
    try:
        candidates.append(s.split(" ", 1)[0])
    except Exception:
        pass
    candidates.append(s)
    for c in candidates:
        c = str(c or "").strip()
        if not c:
            continue
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(c, fmt).date()
            except Exception:
                pass
        try:
            return datetime.fromisoformat(c).date()
        except Exception:
            pass
    return None


def _v104_row_log_date(row: Dict[str, Any]):
    for key in ("login_time", "login_at", "created_at", "log_time", "event_time", "timestamp", "logout_time"):
        d = _v104_parse_any_date(row.get(key))
        if d is not None:
            return d
    return None


def _filter_records(records: List[Dict[str, Any]], start_date: Optional[str], end_date: Optional[str], keyword: str,
                    event_types: Optional[List[str]], results: Optional[List[str]]) -> List[Dict[str, Any]]:  # type: ignore[override]
    """V104: Query display uses robust date parsing; no slash/hyphen string-compare mismatch."""
    start_d = _v104_parse_any_date(start_date) if start_date else None
    end_d = _v104_parse_any_date(end_date) if end_date else None
    if start_d is not None and end_d is not None and end_d < start_d:
        start_d, end_d = end_d, start_d
    kw = (keyword or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for r in records or []:
        rd = _v104_row_log_date(r)
        if start_d is not None and rd is not None and rd < start_d:
            continue
        if end_d is not None and rd is not None and rd > end_d:
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


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:  # type: ignore[override]
    start_d = _v104_parse_any_date(start_date)
    end_d = _v104_parse_any_date(end_date)
    if start_d is None or end_d is None:
        return 0
    if end_d < start_d:
        start_d, end_d = end_d, start_d
    try:
        before = _v103_all_current_login_records(include_legacy=True) if "_v103_all_current_login_records" in globals() else _to_records(load_login_logs(limit=100000, include_legacy=True))
    except Exception:
        before = []
    remaining: List[Dict[str, Any]] = []
    deleted = 0
    for row in before or []:
        rd = _v104_row_log_date(row)
        if rd is not None and start_d <= rd <= end_d:
            deleted += 1
        else:
            remaining.append(row)
    try:
        remaining = _v103_merge_login_rows(remaining) if "_v103_merge_login_rows" in globals() else _merge_record_sets(remaining)
    except Exception:
        pass
    # 全面對齊：SQLite cache、canonical 權威檔、legacy 相容檔都覆寫成 remaining。
    try:
        if "_v103_replace_db_with_login_records" in globals():
            _v103_replace_db_with_login_records(remaining)
    except Exception:
        pass
    try:
        if "_v103_write_authority_login_records" in globals():
            _v103_write_authority_login_records(remaining, reason="v104_clear_login_logs_date_range_authority_hardened")
        elif "_v97_write_login_authority" in globals():
            _v97_write_login_authority(remaining, "v104_clear_login_logs_date_range_authority_hardened")
    except Exception:
        pass
    return int(deleted)


clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_login_logs_by_date = delete_login_logs_by_date_range
clear_login_logs = delete_login_logs_by_date_range
clear_audit_logs_by_date = delete_login_logs_by_date_range
# ===== V104 LOGIN LOG DATE CLEAR AUTHORITY HARDENING END =====


# ===================== V106 LOGIN LOG DELETE TOMBSTONE AUTHORITY FIX =====================
# 目的：11｜登入紀錄刪除後不可再從 SQLite cache、auth_login_logs、security_login_logs、
#       persistent_modules 或舊 history 復活。
# 做法：
# 1) 清除時除了覆寫 canonical records.json，也建立 delete_state.json tombstone。
# 2) 之後 load / stats / export 會先套用 tombstone，舊列即使從 legacy cache 回來也會被擋掉。
# 3) tombstone 以 record key 為主，不會擋住刪除後新登入產生的新時間列。

_V106_LOGIN_DELETE_STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "delete_state.json"
try:
    _v106_prev_load_login_logs = load_login_logs
    _v106_prev_get_login_log_stats = get_login_log_stats
    _v106_prev_delete_login_logs_by_date_range = delete_login_logs_by_date_range
except Exception:
    pass


def _v106_read_delete_state() -> Dict[str, Any]:
    try:
        if _V106_LOGIN_DELETE_STATE_PATH.exists() and _V106_LOGIN_DELETE_STATE_PATH.stat().st_size > 0:
            data = json.loads(_V106_LOGIN_DELETE_STATE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _v106_write_delete_state(state: Dict[str, Any]) -> None:
    try:
        state = dict(state or {})
        state.setdefault("authority_schema", "SPT-LoginLogsDeleteState-V106")
        state["updated_at"] = _now()
        _V106_LOGIN_DELETE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _V106_LOGIN_DELETE_STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(_V106_LOGIN_DELETE_STATE_PATH)
        try:
            from services.permanent_authority_service import github_put_file
            github_put_file(_V106_LOGIN_DELETE_STATE_PATH, _V106_LOGIN_DELETE_STATE_PATH.read_text(encoding="utf-8"), "SPT authority 11_login_logs delete_state: v106")
        except Exception:
            pass
    except Exception:
        pass


def _v106_tombstone_keys() -> set[str]:
    state = _v106_read_delete_state()
    keys = state.get("deleted_keys", [])
    if not isinstance(keys, list):
        keys = []
    return {str(k) for k in keys if str(k).strip()}


def _v106_apply_delete_tombstone(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = _v106_tombstone_keys()
    if not keys:
        return records or []
    out: List[Dict[str, Any]] = []
    for row in records or []:
        try:
            k = _v103_record_key(row) if "_v103_record_key" in globals() else _login_record_key(row)
        except Exception:
            k = "|".join(str(row.get(x, "")) for x in ("username", "event_type", "result", "login_time", "created_at", "module_code", "message"))
        if k not in keys:
            out.append(row)
    return out


def _v106_all_raw_current_login_records(include_legacy: bool = True) -> List[Dict[str, Any]]:
    # 讀取所有目前來源，但不套 tombstone，供刪除計算使用。
    rows: List[Dict[str, Any]] = []
    try:
        if "_v103_read_authority_login_records" in globals():
            rows.extend(_v103_read_authority_login_records())
    except Exception:
        pass
    try:
        if "_v103_db_login_records" in globals():
            rows.extend(_v103_db_login_records(include_legacy=include_legacy))
    except Exception:
        pass
    try:
        if not rows and callable(globals().get("_v103_prev_load_login_logs")):
            prev = _v103_prev_load_login_logs(limit=100000, include_legacy=include_legacy)  # type: ignore[name-defined]
            rows.extend(_to_records(prev))
    except Exception:
        pass
    try:
        return _v103_merge_login_rows(rows) if "_v103_merge_login_rows" in globals() else _merge_record_sets(rows)
    except Exception:
        return rows


def _v106_write_login_authority_hard(records: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    clean = _v106_apply_delete_tombstone(records or [])
    try:
        clean = _v103_merge_login_rows(clean) if "_v103_merge_login_rows" in globals() else _merge_record_sets(clean)
    except Exception:
        pass
    try:
        if "_v103_replace_db_with_login_records" in globals():
            _v103_replace_db_with_login_records(clean)
    except Exception:
        pass
    res: Dict[str, Any] = {"ok": True, "count": len(clean)}
    try:
        if "_v103_write_authority_login_records" in globals():
            res = _v103_write_authority_login_records(clean, reason=reason)
        elif "_v97_write_login_authority" in globals():
            _v97_write_login_authority(clean, reason)
    except Exception as exc:
        res = {"ok": False, "error": str(exc)[:300], "count": len(clean)}
    return res


def load_login_logs(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "",
                    limit: int = 1000, event_types: Optional[List[str]] = None,
                    results: Optional[List[str]] = None, include_legacy: bool = True, **kwargs: Any):  # type: ignore[override]
    records = _v106_all_raw_current_login_records(include_legacy=include_legacy)
    records = _v106_apply_delete_tombstone(records)
    records = _filter_records(records, start_date, end_date, keyword, event_types, results)
    records.sort(key=lambda r: str(r.get("login_time") or r.get("created_at") or ""), reverse=True)
    if limit:
        records = records[:int(limit)]
    if pd is not None:
        return pd.DataFrame(records)
    return records


def get_login_log_stats(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "") -> Dict[str, int]:  # type: ignore[override]
    logs = load_login_logs(start_date=start_date, end_date=end_date, keyword=keyword, limit=100000)
    if pd is not None and hasattr(logs, "empty"):
        total = int(len(logs))
        success = 0
        if total:
            result_s = logs.get("result", "").astype(str).str.upper()
            success = int(result_s.isin(["SUCCESS", "OK", "INFO"]).sum())
        return {"records": total, "success": success, "failed": total - success}
    total = len(logs)
    success = sum(1 for r in logs if _normalise_result(r.get("result")) in {"SUCCESS", "OK", "INFO"})
    return {"records": total, "success": success, "failed": total - success}


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:  # type: ignore[override]
    start_d = _v104_parse_any_date(start_date) if "_v104_parse_any_date" in globals() else None
    end_d = _v104_parse_any_date(end_date) if "_v104_parse_any_date" in globals() else None
    if start_d is None or end_d is None:
        return 0
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    before = _v106_all_raw_current_login_records(include_legacy=True)
    old_state = _v106_read_delete_state()
    deleted_keys = set(str(k) for k in old_state.get("deleted_keys", []) if str(k).strip()) if isinstance(old_state.get("deleted_keys", []), list) else set()
    remaining: List[Dict[str, Any]] = []
    deleted = 0
    deleted_rows_preview: List[Dict[str, Any]] = []
    for row in before or []:
        rd = _v104_row_log_date(row) if "_v104_row_log_date" in globals() else None
        try:
            k = _v103_record_key(row) if "_v103_record_key" in globals() else _login_record_key(row)
        except Exception:
            k = "|".join(str(row.get(x, "")) for x in ("username", "event_type", "result", "login_time", "created_at", "module_code", "message"))
        if rd is not None and start_d <= rd <= end_d:
            deleted += 1
            deleted_keys.add(str(k))
            if len(deleted_rows_preview) < 30:
                deleted_rows_preview.append({
                    "username": row.get("username"),
                    "event_type": row.get("event_type"),
                    "result": row.get("result"),
                    "login_time": row.get("login_time") or row.get("created_at"),
                    "key": str(k),
                })
        else:
            remaining.append(row)
    try:
        remaining = _v103_merge_login_rows(remaining) if "_v103_merge_login_rows" in globals() else _merge_record_sets(remaining)
    except Exception:
        pass

    state = dict(old_state or {})
    ranges = state.get("delete_ranges", []) if isinstance(state.get("delete_ranges"), list) else []
    ranges.append({
        "start_date": str(start_d),
        "end_date": str(end_d),
        "deleted_at": _now(),
        "deleted_count": deleted,
    })
    state.update({
        "authority_schema": "SPT-LoginLogsDeleteState-V106",
        "module_key": "11_login_logs",
        "updated_at": _now(),
        "delete_ranges": ranges[-80:],
        "deleted_keys": sorted(deleted_keys)[-50000:],
        "last_deleted_count": deleted,
        "last_deleted_rows_preview": deleted_rows_preview,
    })
    _v106_write_delete_state(state)
    _v106_write_login_authority_hard(remaining, reason="v106_clear_login_logs_tombstone_authority")
    return int(deleted)


def get_audit_permanent_status() -> Dict[str, Any]:  # type: ignore[override]
    records = _v106_apply_delete_tombstone(_v103_read_authority_login_records() if "_v103_read_authority_login_records" in globals() else [])
    path = _V103_LOGIN_AUTHORITY_PATH if "_V103_LOGIN_AUTHORITY_PATH" in globals() else _V97_LOGIN_AUTHORITY_PATH
    payload = _read_json_file(path) if path.exists() else {}
    delete_state = _v106_read_delete_state()
    return {
        "exists": path.exists(),
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "count": len(records),
        "exported_at": str(payload.get("exported_at") or payload.get("updated_at") or "") if isinstance(payload, dict) else "",
        "db_count": len(_v106_apply_delete_tombstone(_v103_db_login_records(include_legacy=True))) if "_v103_db_login_records" in globals() else 0,
        "authority_schema": str(payload.get("authority_schema", "")) if isinstance(payload, dict) else "",
        "delete_state_path": str(_V106_LOGIN_DELETE_STATE_PATH),
        "delete_state_exists": _V106_LOGIN_DELETE_STATE_PATH.exists(),
        "deleted_keys": len(delete_state.get("deleted_keys", []) or []),
        "last_deleted_count": int(delete_state.get("last_deleted_count", 0) or 0),
    }


def export_audit_logs_to_permanent_file(create_history: bool = True, merge_existing: bool = True) -> Dict[str, Any]:  # type: ignore[override]
    records = _to_records(load_login_logs(limit=100000, include_legacy=True))
    return _v106_write_login_authority_hard(records, reason="v106_export_login_logs_tombstone_filtered")


clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_login_logs_by_date = delete_login_logs_by_date_range
clear_login_logs = delete_login_logs_by_date_range
clear_audit_logs_by_date = delete_login_logs_by_date_range
get_login_logs = load_login_logs
query_login_logs = load_login_logs
load_audit_logs = load_login_logs
login_log_stats = get_login_log_stats
audit_permanent_status = get_audit_permanent_status
get_audit_state_status = get_audit_permanent_status
login_log_state_status = get_audit_permanent_status
get_login_log_permanent_status = get_audit_permanent_status
# =================== END V106 LOGIN LOG DELETE TOMBSTONE AUTHORITY FIX ===================


# ===================== V115 LOGIN LOG EVENT WRITE-THROUGH FIX =====================
# 目的：11｜登入紀錄必須在登入 / 登出 / 權限不足 / 強制改密碼等事件發生當下
#       立即寫入正式 canonical 權威檔，不可只停留在 SQLite 或舊 legacy 表。
# 重點：
# 1) security_service.log_security_event 會呼叫本 record_login_log。
# 2) 本函式先寫 login_logs SQLite cache，再以目前 Page 11 可見資料覆寫
#    data/permanent_store/modules/11_login_logs/records.json。
# 3) 刪除 tombstone 仍保留；已刪除舊列不會因 legacy cache 回來而復活。
# 4) aliases 全部重新指向 V115，避免舊版函式被呼叫。

try:
    _v115_prev_record_login_log = record_login_log
except Exception:  # pragma: no cover
    _v115_prev_record_login_log = None


def _v115_float_idle_minutes(idle_minutes: Any = None, idle_seconds: Any = None):
    if idle_minutes not in (None, ""):
        try:
            return round(float(idle_minutes), 4)
        except Exception:
            return None
    if idle_seconds not in (None, ""):
        try:
            return round(float(idle_seconds) / 60.0, 4)
        except Exception:
            return None
    return None


def _v115_insert_login_log_sqlite(row: Dict[str, Any]) -> int:
    ensure_login_logs_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO login_logs (
        username, display_name, event_type, result, message, module_code,
        login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row.get("username") or "",
        row.get("display_name") or "",
        _normalise_event_type(row.get("event_type") or "LOGIN"),
        _normalise_result(row.get("result") or "SUCCESS"),
        row.get("message") or "",
        row.get("module_code") or "",
        row.get("login_time") or row.get("created_at") or _now(),
        row.get("logout_time") or "",
        _v115_float_idle_minutes(row.get("idle_minutes"), row.get("idle_seconds")),
        row.get("ip_address") or "",
        row.get("user_agent") or "streamlit",
        row.get("created_at") or row.get("login_time") or _now(),
    ))
    new_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return new_id


def _v115_current_visible_records_with_extra(extra: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        # V106 load_login_logs already applies tombstone and merges canonical + SQLite.
        rows.extend(_to_records(load_login_logs(limit=100000, include_legacy=True)))
    except Exception:
        try:
            if "_v106_all_raw_current_login_records" in globals():
                rows.extend(_v106_all_raw_current_login_records(include_legacy=True))  # type: ignore[name-defined]
        except Exception:
            pass
    if extra:
        rows.append(dict(extra))
    try:
        rows = _v106_apply_delete_tombstone(rows) if "_v106_apply_delete_tombstone" in globals() else rows  # type: ignore[name-defined]
    except Exception:
        pass
    try:
        rows = _v103_merge_login_rows(rows) if "_v103_merge_login_rows" in globals() else _merge_record_sets(rows)  # type: ignore[name-defined]
    except Exception:
        rows = _merge_record_sets(rows)
    return rows


def _v115_write_login_authority_from_rows(rows: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    clean = _valid_login_rows("v115_authority", rows or [])
    try:
        clean = _v103_merge_login_rows(clean) if "_v103_merge_login_rows" in globals() else _merge_record_sets(clean)  # type: ignore[name-defined]
    except Exception:
        pass
    # Keep SQLite cache aligned with canonical, but never let legacy tables be the final authority.
    try:
        if "_v103_replace_db_with_login_records" in globals():
            _v103_replace_db_with_login_records(clean)  # type: ignore[name-defined]
    except Exception:
        pass
    # Write the single canonical authority file. This is the file Streamlit Cloud must keep after Reboot.
    try:
        from services.permanent_authority_service import save_authority, canonical_path
        res = save_authority(
            "11_login_logs",
            records={"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
            reason=reason,
            github=True,
        )
        res["count"] = len(clean)
        res["canonical_path"] = str(canonical_path("11_login_logs", "records"))
        return res
    except Exception as exc:
        # Local fallback so Page 11 still displays the authoritative file path and count.
        try:
            path = _V103_LOGIN_AUTHORITY_PATH if "_V103_LOGIN_AUTHORITY_PATH" in globals() else _V97_LOGIN_AUTHORITY_PATH
        except Exception:
            path = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "records.json"
        payload = {
            "authority_schema": "SPT-PermanentAuthority-V115-LoginWriteThrough",
            "module_key": "11_login_logs",
            "kind": "records",
            "updated_at": _now(),
            "exported_at": _now(),
            "reason": reason,
            "empty_authoritative": len(clean) == 0,
            "tables": {"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
            "table_counts": {"login_logs": len(clean), "auth_login_logs": 0, "security_login_logs": 0},
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
            return {"ok": True, "count": len(clean), "canonical_path": str(path), "fallback": True, "error": str(exc)[:300]}
        except Exception as exc2:
            return {"ok": False, "count": len(clean), "error": str(exc)[:300], "fallback_error": str(exc2)[:300]}


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
    user_agent: str = "streamlit",
    **kwargs: Any,
) -> int:  # type: ignore[override]
    event_time = login_time or kwargs.get("event_time") or kwargs.get("created_at") or _now()
    norm_event = _normalise_event_type(event_type or "LOGIN")
    row = {
        "username": username or "",
        "display_name": display_name or "",
        "event_type": norm_event,
        "result": _normalise_result(result or "SUCCESS"),
        "message": message or "",
        "module_code": module_code or "",
        # Page 11 uses login_time as the main event time column; keep it populated for all event types.
        "login_time": event_time,
        "logout_time": logout_time or (event_time if norm_event in {"LOGOUT", "AUTO_LOGOUT", "POST_RECORD_LOGOUT", "SESSION_TIMEOUT"} else ""),
        "idle_minutes": _v115_float_idle_minutes(idle_minutes, kwargs.get("idle_seconds")),
        "ip_address": ip_address or "",
        "user_agent": user_agent or "streamlit",
        "created_at": kwargs.get("created_at") or event_time,
        "source": "login_logs",
    }
    clean = _canonical_login_row("login_logs", row)
    if clean is None:
        return 0
    new_id = _v115_insert_login_log_sqlite(clean)
    clean["id"] = new_id
    rows = _v115_current_visible_records_with_extra(clean)
    _v115_write_login_authority_from_rows(rows, reason="v115_login_event_write_through")
    return int(new_id)


# Keep all historical aliases pointing to the final write-through implementation.
write_login_log = record_login_log
add_login_log = record_login_log
append_login_log = record_login_log
write_audit_log = record_login_log
record_audit_log = record_login_log
log_login_event = record_login_log
save_login_log = record_login_log
# =================== END V115 LOGIN LOG EVENT WRITE-THROUGH FIX ===================

# ===================== V135 LOGIN LOG AUTHORITY + DELETE-RANGE HARD FIX =====================
# 目的：
# 1) 11. 登入紀錄清除後，不可再從 SQLite 舊表、auth_login_logs、security_login_logs、
#    persistent_modules 舊檔或歷史備份復活。
# 2) 刪除不只記錄 deleted_keys，也記錄日期範圍 + 刪除時間 deleted_at。
#    舊資料只要事件日期落在已清除範圍，且事件時間早於清除時間，就會被擋掉；
#    清除後的新登入仍可正常顯示。
# 3) Page 11 顯示與統計都使用同一套 tombstone 過濾後的 canonical 合併資料。
# 4) 寫入事件時先過濾舊復活資料，再寫回 11_login_logs canonical 權威檔。

try:
    _v135_prev_load_login_logs = load_login_logs
except Exception:
    _v135_prev_load_login_logs = None
try:
    _v135_prev_get_login_log_stats = get_login_log_stats
except Exception:
    _v135_prev_get_login_log_stats = None
try:
    _v135_prev_delete_login_logs_by_date_range = delete_login_logs_by_date_range
except Exception:
    _v135_prev_delete_login_logs_by_date_range = None
try:
    _v135_prev_record_login_log = record_login_log
except Exception:
    _v135_prev_record_login_log = None


def _v135_parse_dt(value: Any):
    """Parse login event datetime for delete-range tombstone comparison."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("/", "-").replace(".", "-")
    if "+" in s:
        s = s.split("+", 1)[0].strip()
    if s.endswith("Z"):
        s = s[:-1].strip()
    candidates = [s, s[:19], s[:16], s[:10]]
    for c in candidates:
        c = str(c or "").strip()
        if not c:
            continue
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(c, fmt)
            except Exception:
                pass
        try:
            return datetime.fromisoformat(c)
        except Exception:
            pass
    return None


def _v135_row_event_datetime(row: Dict[str, Any]):
    for key in ("login_time", "event_time", "created_at", "log_time", "timestamp", "logout_time", "login_at"):
        dt = _v135_parse_dt((row or {}).get(key))
        if dt is not None:
            return dt
    return None


def _v135_record_key(row: Dict[str, Any]) -> str:
    try:
        if "_v103_record_key" in globals():
            return _v103_record_key(row)
    except Exception:
        pass
    try:
        return _login_record_key(row)
    except Exception:
        return "|".join(str((row or {}).get(x, "")) for x in ("username", "event_type", "result", "login_time", "created_at", "module_code", "message"))


def _v135_read_delete_state() -> Dict[str, Any]:
    try:
        if "_v106_read_delete_state" in globals():
            st = _v106_read_delete_state()
            return dict(st) if isinstance(st, dict) else {}
    except Exception:
        pass
    try:
        if _V106_LOGIN_DELETE_STATE_PATH.exists():
            data = json.loads(_V106_LOGIN_DELETE_STATE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _v135_write_delete_state(state: Dict[str, Any]) -> None:
    try:
        if "_v106_write_delete_state" in globals():
            _v106_write_delete_state(state)
            return
    except Exception:
        pass
    try:
        state = dict(state or {})
        state.setdefault("authority_schema", "SPT-LoginLogsDeleteState-V135")
        state["updated_at"] = _now()
        _V106_LOGIN_DELETE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _V106_LOGIN_DELETE_STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(_V106_LOGIN_DELETE_STATE_PATH)
    except Exception:
        pass


def _v135_row_is_deleted_by_state(row: Dict[str, Any], state: Dict[str, Any] | None = None) -> bool:
    state = state if isinstance(state, dict) else _v135_read_delete_state()
    key = _v135_record_key(row)
    deleted_keys = state.get("deleted_keys", [])
    if isinstance(deleted_keys, list) and key in {str(x) for x in deleted_keys}:
        return True

    event_dt = _v135_row_event_datetime(row)
    if event_dt is None:
        return False
    event_date = event_dt.date()
    ranges = state.get("delete_ranges", [])
    if not isinstance(ranges, list):
        return False
    for rg in ranges:
        if not isinstance(rg, dict):
            continue
        sd = _v104_parse_any_date(rg.get("start_date")) if "_v104_parse_any_date" in globals() else None
        ed = _v104_parse_any_date(rg.get("end_date")) if "_v104_parse_any_date" in globals() else None
        if sd is None or ed is None:
            continue
        if ed < sd:
            sd, ed = ed, sd
        if not (sd <= event_date <= ed):
            continue
        deleted_at = _v135_parse_dt(rg.get("deleted_at")) or _v135_parse_dt(state.get("updated_at"))
        # 清除後新登入不要被同日期 tombstone 擋掉；舊資料才擋。
        if deleted_at is None or event_dt <= deleted_at:
            return True
    return False


def _v135_filter_deleted_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    state = _v135_read_delete_state()
    out: List[Dict[str, Any]] = []
    for row in records or []:
        if not isinstance(row, dict):
            continue
        if _v135_row_is_deleted_by_state(row, state):
            continue
        out.append(row)
    try:
        return _v103_merge_login_rows(out) if "_v103_merge_login_rows" in globals() else _merge_record_sets(out)
    except Exception:
        return out


# Override V106 tombstone function so all older helpers automatically inherit range-based blocking.
def _v106_apply_delete_tombstone(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:  # type: ignore[override]
    return _v135_filter_deleted_records(records or [])


def _v135_raw_records_from_all_sources(include_legacy: bool = True) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        if "_v103_read_authority_login_records" in globals():
            rows.extend(_v103_read_authority_login_records())
    except Exception:
        pass
    try:
        if "_v103_db_login_records" in globals():
            rows.extend(_v103_db_login_records(include_legacy=include_legacy))
    except Exception:
        pass
    if not rows:
        try:
            if callable(_v135_prev_load_login_logs):
                rows.extend(_to_records(_v135_prev_load_login_logs(limit=100000, include_legacy=include_legacy)))
        except Exception:
            pass
    try:
        return _v103_merge_login_rows(rows) if "_v103_merge_login_rows" in globals() else _merge_record_sets(rows)
    except Exception:
        return rows


def _v135_write_authority_and_cache(records: List[Dict[str, Any]], reason: str = "v135_login_authority", *, github: bool = True) -> Dict[str, Any]:
    clean = _v135_filter_deleted_records(_valid_login_rows("v135", records or []))
    # SQLite cache 必須跟 tombstone 後的權威檔一致；legacy 表清空，避免 reboot 復活。
    try:
        if "_v103_replace_db_with_login_records" in globals():
            _v103_replace_db_with_login_records(clean)
    except Exception:
        pass
    res: Dict[str, Any] = {"ok": True, "count": len(clean)}
    try:
        from services.permanent_authority_service import save_authority, canonical_path
        res = save_authority(
            "11_login_logs",
            records={"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
            reason=reason,
            github=bool(github),
        )
        res["count"] = len(clean)
        res["canonical_path"] = str(canonical_path("11_login_logs", "records"))
    except Exception as exc:
        res = {"ok": False, "count": len(clean), "error": str(exc)[:300]}
        try:
            path = _V103_LOGIN_AUTHORITY_PATH if "_V103_LOGIN_AUTHORITY_PATH" in globals() else PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "records.json"
            payload = {
                "authority_schema": "SPT-PermanentAuthority-V135-LoginLogs",
                "module_key": "11_login_logs",
                "kind": "records",
                "updated_at": _now(),
                "exported_at": _now(),
                "reason": reason,
                "empty_authoritative": len(clean) == 0,
                "tables": {"login_logs": clean, "auth_login_logs": [], "security_login_logs": []},
                "table_counts": {"login_logs": len(clean), "auth_login_logs": 0, "security_login_logs": 0},
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
            res["ok"] = True
            res["canonical_path"] = str(path)
        except Exception as exc2:
            res["fallback_error"] = str(exc2)[:300]
    # 相容舊路徑，但內容只能是 tombstone 後乾淨資料。
    try:
        if "_v103_write_legacy_login_files" in globals():
            _v103_write_legacy_login_files(clean, reason)
    except Exception:
        pass
    return res


def load_login_logs(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "",
                    limit: int = 1000, event_types: Optional[List[str]] = None,
                    results: Optional[List[str]] = None, include_legacy: bool = True, **kwargs: Any):  # type: ignore[override]
    records = _v135_filter_deleted_records(_v135_raw_records_from_all_sources(include_legacy=include_legacy))
    records = _filter_records(records, start_date, end_date, keyword, event_types, results)
    records.sort(key=lambda r: str(r.get("login_time") or r.get("created_at") or r.get("logout_time") or ""), reverse=True)
    if limit:
        records = records[:int(limit)]
    if pd is not None:
        return pd.DataFrame(records)
    return records


def get_login_log_stats(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "") -> Dict[str, int]:  # type: ignore[override]
    logs = load_login_logs(start_date=start_date, end_date=end_date, keyword=keyword, limit=100000)
    if pd is not None and hasattr(logs, "empty"):
        total = int(len(logs))
        success = 0
        if total:
            result_s = logs.get("result", "").astype(str).str.upper()
            success = int(result_s.isin(["SUCCESS", "OK", "INFO"]).sum())
        return {"records": total, "success": success, "failed": total - success}
    total = len(logs)
    success = sum(1 for r in logs if _normalise_result(r.get("result")) in {"SUCCESS", "OK", "INFO"})
    return {"records": total, "success": success, "failed": total - success}


def delete_login_logs_by_date_range(start_date: str, end_date: str) -> int:  # type: ignore[override]
    start_d = _v104_parse_any_date(start_date) if "_v104_parse_any_date" in globals() else None
    end_d = _v104_parse_any_date(end_date) if "_v104_parse_any_date" in globals() else None
    if start_d is None or end_d is None:
        return 0
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    now_deleted_at = _now()
    before = _v135_raw_records_from_all_sources(include_legacy=True)
    remaining: List[Dict[str, Any]] = []
    deleted = 0
    state = _v135_read_delete_state()
    deleted_keys = set(str(k) for k in state.get("deleted_keys", []) if str(k).strip()) if isinstance(state.get("deleted_keys", []), list) else set()
    preview: List[Dict[str, Any]] = []
    for row in before or []:
        rd = _v104_row_log_date(row) if "_v104_row_log_date" in globals() else None
        if rd is not None and start_d <= rd <= end_d:
            deleted += 1
            deleted_keys.add(_v135_record_key(row))
            if len(preview) < 30:
                preview.append({
                    "username": row.get("username"),
                    "event_type": row.get("event_type"),
                    "result": row.get("result"),
                    "login_time": row.get("login_time") or row.get("created_at"),
                    "key": _v135_record_key(row),
                })
        else:
            remaining.append(row)

    ranges = state.get("delete_ranges", []) if isinstance(state.get("delete_ranges"), list) else []
    ranges.append({
        "start_date": str(start_d),
        "end_date": str(end_d),
        "deleted_at": now_deleted_at,
        "deleted_count": deleted,
        "mode": "date_range_before_deleted_at_v135",
    })
    state.update({
        "authority_schema": "SPT-LoginLogsDeleteState-V135",
        "module_key": "11_login_logs",
        "updated_at": now_deleted_at,
        "delete_ranges": ranges[-200:],
        "deleted_keys": sorted({str(k) for k in deleted_keys if str(k).strip()})[-100000:],
        "last_deleted_count": deleted,
        "last_deleted_rows_preview": preview,
    })
    _v135_write_delete_state(state)
    # 寫權威檔時會再次套用 range tombstone，確保同日期舊資料不會被 DB/legacy 帶回。
    _v135_write_authority_and_cache(remaining, reason="v135_clear_login_logs_authority_range_tombstone", github=True)
    return int(deleted)


def export_audit_logs_to_permanent_file(create_history: bool = True, merge_existing: bool = True) -> Dict[str, Any]:  # type: ignore[override]
    # 永久匯出只能匯出 tombstone 後目前可見資料，不得 merge 舊 history。
    records = _to_records(load_login_logs(limit=100000, include_legacy=True))
    return _v135_write_authority_and_cache(records, reason="v135_export_login_logs_authority", github=True)


def restore_audit_logs_from_permanent_file(*args: Any, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
    # 還原也必須尊重 delete_state，不能把已清除範圍從舊檔還原。
    records = _v135_filter_deleted_records(_v135_raw_records_from_all_sources(include_legacy=True))
    _v135_write_authority_and_cache(records, reason="v135_restore_login_logs_tombstone_safe", github=True)
    return {"ok": True, "message": f"已依 V135 權威檔與刪除狀態還原登入紀錄，共 {len(records)} 筆。", "count": len(records)}


def get_audit_permanent_status() -> Dict[str, Any]:  # type: ignore[override]
    records = _v135_filter_deleted_records(_v103_read_authority_login_records() if "_v103_read_authority_login_records" in globals() else [])
    path = _V103_LOGIN_AUTHORITY_PATH if "_V103_LOGIN_AUTHORITY_PATH" in globals() else PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "records.json"
    payload = _read_json_file(path) if path.exists() else {}
    delete_state = _v135_read_delete_state()
    return {
        "exists": path.exists(),
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "count": len(records),
        "exported_at": str(payload.get("exported_at") or payload.get("updated_at") or "") if isinstance(payload, dict) else "",
        "db_count": len(_v135_filter_deleted_records(_v103_db_login_records(include_legacy=True))) if "_v103_db_login_records" in globals() else 0,
        "authority_schema": str(payload.get("authority_schema", "")) if isinstance(payload, dict) else "",
        "delete_state_path": str(_V106_LOGIN_DELETE_STATE_PATH),
        "delete_state_exists": _V106_LOGIN_DELETE_STATE_PATH.exists(),
        "deleted_keys": len(delete_state.get("deleted_keys", []) or []),
        "delete_ranges": len(delete_state.get("delete_ranges", []) or []),
        "last_deleted_count": int(delete_state.get("last_deleted_count", 0) or 0),
    }


# Keep aliases pinned to V135 implementations.
clear_login_logs_by_date_range = delete_login_logs_by_date_range
delete_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_audit_logs_by_date_range = delete_login_logs_by_date_range
clear_login_logs_by_date = delete_login_logs_by_date_range
clear_login_logs = delete_login_logs_by_date_range
clear_audit_logs_by_date = delete_login_logs_by_date_range
get_login_logs = load_login_logs
query_login_logs = load_login_logs
load_audit_logs = load_login_logs
login_log_stats = get_login_log_stats
audit_permanent_status = get_audit_permanent_status
get_audit_state_status = get_audit_permanent_status
login_log_state_status = get_audit_permanent_status
get_login_log_permanent_status = get_audit_permanent_status
restore_login_logs_from_permanent_file = restore_audit_logs_from_permanent_file
restore_login_logs_from_state = restore_audit_logs_from_permanent_file
# =================== END V135 LOGIN LOG AUTHORITY + DELETE-RANGE HARD FIX ===================


# ===================== V254 FAST LOGIN AUDIT WRITE =====================
# Problem: record_login_log originally inserted a row, then synchronously called
# export_audit_logs_to_permanent_file().  Later V135 overrode that export to read up to
# 100000 login rows and save authority with github=True.  That made every successful
# login wait for a large authority/GitHub path, commonly around 15 seconds.
# Fix: login/logout/security events stay durable in SQLite immediately, and the
# canonical 11_login_logs authority refresh is queued in a daemon thread with github=False.
# UI/CSS/table/button behavior is untouched.
import threading as _v254_threading
import time as _v254_time

_V254_LOGIN_EXPORT_STATE = {"running": False, "last_run_ts": 0.0, "last_error": ""}
_V254_LOGIN_EXPORT_LOCK = _v254_threading.RLock()
_V254_LOGIN_EXPORT_MIN_SECONDS = 10.0


def _v254_refresh_login_authority_worker(reason: str = "v254_fast_login_audit") -> None:
    with _V254_LOGIN_EXPORT_LOCK:
        if _V254_LOGIN_EXPORT_STATE.get("running"):
            return
        _V254_LOGIN_EXPORT_STATE["running"] = True
    try:
        now_ts = _v254_time.time()
        last_ts = float(_V254_LOGIN_EXPORT_STATE.get("last_run_ts") or 0.0)
        if last_ts and now_ts - last_ts < _V254_LOGIN_EXPORT_MIN_SECONDS:
            return
        records = []
        try:
            records = _to_records(load_login_logs(limit=100000, include_legacy=True))
        except TypeError:
            records = _to_records(load_login_logs())
        if "_v135_write_authority_and_cache" in globals():
            _v135_write_authority_and_cache(records, reason=reason, github=False)  # type: ignore[name-defined]
        else:
            try:
                payload = {
                    "authority_schema": "SPT-PermanentAuthority-V254-FastLogin",
                    "module_key": "11_login_logs",
                    "kind": "records",
                    "updated_at": _now(),
                    "tables": {"login_logs": records, "auth_login_logs": [], "security_login_logs": []},
                    "records": records,
                    "count": len(records),
                }
                for path in (AUDIT_STATE_PATH, MODULE_RECORDS_PATH):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    tmp.replace(path)
            except Exception:
                pass
        _V254_LOGIN_EXPORT_STATE["last_run_ts"] = _v254_time.time()
        _V254_LOGIN_EXPORT_STATE["last_error"] = ""
    except Exception as exc:
        _V254_LOGIN_EXPORT_STATE["last_error"] = str(exc)[:500]
    finally:
        with _V254_LOGIN_EXPORT_LOCK:
            _V254_LOGIN_EXPORT_STATE["running"] = False


def _v254_queue_login_authority_refresh(reason: str = "v254_fast_login_audit") -> None:
    try:
        if _V254_LOGIN_EXPORT_STATE.get("running"):
            return
        t = _v254_threading.Thread(
            target=_v254_refresh_login_authority_worker,
            args=(reason,),
            name="SPT-V254-LoginAuditAuthorityRefresh",
            daemon=True,
        )
        t.start()
    except Exception:
        pass


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
) -> int:  # type: ignore[override]
    """V254: durable immediate SQLite insert; non-blocking authority refresh."""
    try:
        ensure_login_logs_table()
    except Exception:
        pass
    login_time = login_time or _now()
    created_at = kwargs.get("created_at") or _now()
    new_id = 0
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO login_logs (
            username, display_name, event_type, result, message, module_code,
            login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, display_name, event_type, result, message, module_code,
              login_time, logout_time, idle_minutes, ip_address, user_agent, created_at))
        new_id = int(cur.lastrowid or 0)
        conn.commit()
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    _v254_queue_login_authority_refresh("v254_login_audit_async_refresh")
    return new_id


write_login_log = record_login_log
add_login_log = record_login_log
append_login_log = record_login_log
write_audit_log = record_login_log
record_audit_log = record_login_log
log_login_event = record_login_log
save_login_log = record_login_log
# =================== END V254 FAST LOGIN AUDIT WRITE ===================
