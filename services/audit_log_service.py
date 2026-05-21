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
