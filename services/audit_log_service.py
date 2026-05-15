# -*- coding: utf-8 -*-
"""V1.44 Audit / Login Log Compatibility Service.
Fixes ImportError for pages/11_11. 登入紀錄.py after V1.43.
Keeps old function names compatible and avoids GitHub/network work during import/login.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_file() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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


# old names compatibility
ensure_audit_log_table = ensure_login_logs_table
ensure_audit_tables = ensure_login_logs_table
init_audit_log_table = ensure_login_logs_table
init_login_logs = ensure_login_logs_table


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
    """Insert one login/audit event. No GitHub upload here, to keep login fast."""
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
    """Record LOGIN once per Streamlit session when possible."""
    if not username:
        return
    try:
        import streamlit as st
        key = f"_spt_login_recorded_{username}"
        if st.session_state.get(key):
            return
        record_login_log(username=username, display_name=display_name, event_type="LOGIN",
                         result="SUCCESS", message=f"roles={roles}" if roles else kwargs.get("message", ""),
                         module_code=kwargs.get("module_code", ""))
        st.session_state[key] = True
    except Exception:
        try:
            record_login_log(username=username, display_name=display_name, event_type="LOGIN",
                             result="SUCCESS", message=f"roles={roles}" if roles else "")
        except Exception:
            pass


record_session_login_once = auto_record_session_login
ensure_session_login_recorded = auto_record_session_login


def load_login_logs(start_date: Optional[str] = None, end_date: Optional[str] = None, keyword: str = "",
                    limit: int = 1000, event_types: Optional[List[str]] = None,
                    results: Optional[List[str]] = None, **kwargs: Any):
    ensure_login_logs_table()
    sql = "SELECT * FROM login_logs WHERE 1=1"
    params: List[Any] = []
    if start_date:
        sql += " AND date(COALESCE(login_time, created_at)) >= date(?)"
        params.append(str(start_date))
    if end_date:
        sql += " AND date(COALESCE(login_time, created_at)) <= date(?)"
        params.append(str(end_date))
    if keyword:
        kw = f"%{keyword}%"
        sql += " AND (username LIKE ? OR display_name LIKE ? OR message LIKE ? OR module_code LIKE ?)"
        params += [kw, kw, kw, kw]
    if event_types:
        ph = ",".join(["?"] * len(event_types))
        sql += f" AND event_type IN ({ph})"
        params += list(event_types)
    if results:
        ph = ",".join(["?"] * len(results))
        sql += f" AND result IN ({ph})"
        params += list(results)
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    conn = get_connection()
    if pd is not None:
        df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        return df
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


get_login_logs = load_login_logs
query_login_logs = load_login_logs
load_audit_logs = load_login_logs


def count_login_logs() -> int:
    ensure_login_logs_table()
    conn = get_connection()
    n = int(conn.execute("SELECT COUNT(*) FROM login_logs").fetchone()[0])
    conn.close()
    return n


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


def _to_records(obj: Any) -> List[Dict[str, Any]]:
    if pd is not None and hasattr(obj, "to_dict"):
        return obj.to_dict(orient="records")
    return obj if isinstance(obj, list) else []


def export_audit_logs_to_permanent_file(create_history: bool = True) -> Dict[str, Any]:
    _ensure_dirs()
    ensure_login_logs_table()
    records = _to_records(load_login_logs(limit=100000))
    payload = {
        "version": "V1.44",
        "exported_at": _now(),
        "table": "login_logs",
        "count": len(records),
        "records": records,
    }
    AUDIT_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MODULE_RECORDS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MODULE_SETTINGS_PATH.write_text(json.dumps({
        "version": "V1.44", "exported_at": _now(), "module": "11_login_logs",
        "settings": {"auto_github_upload_on_login": False, "retention_policy": "manual date range cleanup"}
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
        cur.execute("""
        INSERT INTO login_logs (
            id, username, display_name, event_type, result, message, module_code,
            login_time, logout_time, idle_minutes, ip_address, user_agent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (r.get("id"), r.get("username"), r.get("display_name"), r.get("event_type"),
              r.get("result"), r.get("message"), r.get("module_code"), r.get("login_time"),
              r.get("logout_time"), r.get("idle_minutes"), r.get("ip_address"), r.get("user_agent"), r.get("created_at")))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "登入紀錄已從永久檔還原", "count": len(records), "path": str(src)}


restore_login_logs_from_permanent_file = restore_audit_logs_from_permanent_file
restore_audit_logs = restore_audit_logs_from_permanent_file


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
get_login_log_permanent_status = get_audit_permanent_status


def bootstrap_audit_log_service() -> Dict[str, Any]:
    ensure_login_logs_table()
    _ensure_dirs()
    if count_login_logs() == 0:
        record_login_log(username="SYSTEM", display_name="系統", event_type="BOOTSTRAP", result="SUCCESS", message="Audit log service initialized", module_code="11_login_logs")
    return {"ok": True, "message": "audit_log_service ready", "count": count_login_logs()}

# ===== V1.46 compatibility aliases for older/newer pages =====
# Some page versions import these names directly. Keep all aliases to avoid ImportError.
audit_state_status = get_audit_permanent_status
get_audit_state_status = get_audit_permanent_status
login_log_state_status = get_audit_permanent_status

export_audit_logs_to_state = export_audit_logs_to_permanent_file
create_audit_logs_state = export_audit_logs_to_permanent_file
build_audit_logs_state = export_audit_logs_to_permanent_file
export_login_logs_to_state = export_audit_logs_to_permanent_file

restore_audit_logs_from_state = restore_audit_logs_from_permanent_file
restore_login_logs_from_state = restore_audit_logs_from_permanent_file

# Older page versions used clear_login_logs_by_date(start_date, end_date)
def clear_login_logs_by_date(start_date: str, end_date: str, **kwargs: Any) -> int:
    return delete_login_logs_by_date_range(start_date, end_date)

# Extra common aliases
clear_login_logs = clear_login_logs_by_date
clear_audit_logs_by_date = clear_login_logs_by_date
upload_audit_logs_to_github_cloud = upload_audit_logs_to_github
upload_audit_logs_to_state_github = upload_audit_logs_to_github

# Optional no-op fallback used by some versions to avoid login page slowdown.
def maybe_record_session_login(*args: Any, **kwargs: Any) -> None:
    return auto_record_session_login(*args, **kwargs)
