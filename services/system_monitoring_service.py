# -*- coding: utf-8 -*-
"""V166 system monitoring dashboard service.

Read-only monitoring layer for the data health center.  This module intentionally
DOES NOT write, recalculate, delete, flush queues, or change production storage.
It summarizes existing SQLite / authority JSON / event-journal / backup status
so administrators can see operational risk quickly without entering every page.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERM_ROOT = PROJECT_ROOT / "data" / "permanent_store"
MODULES_ROOT = PERM_ROOT / "modules"
PERSISTENT_MODULES_ROOT = PERM_ROOT / "persistent_modules"
SQLITE_PATHS = [
    PERM_ROOT / "database" / "spt_time_tracking.db",
    PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db",
]

ACTIVE_STATUSES = {"", "作業中", "開始", "START", "START_WORK", "WORKING", "RUNNING", "ACTIVE"}
TERMINAL_STATUSES = {"下班", "暫停", "完工", "已結束", "結束", "FINISH", "FINISH_WORK", "OFF_DUTY", "PAUSE_WORK", "DONE", "CLOSED"}
START_ACTIONS = {"START_WORK", "開始作業 / START_WORK", "開始作業", "START", "INSERT"}
END_ACTION_KEYWORDS = ("FINISH", "OFF_DUTY", "PAUSE", "END", "下班", "暫停", "完工", "結束")
ERROR_KEYWORDS = ("ERROR", "EXCEPTION", "TRACEBACK", "DATABASE", "SQLITE", "WRITE", "寫入", "失敗", "錯誤")


def _now_dt() -> datetime:
    try:
        from services.timezone_service import now_dt
        val = now_dt()
        if isinstance(val, datetime):
            return val.replace(tzinfo=None)
    except Exception:
        pass
    try:
        from services.timezone_service import now_text
        parsed = _parse_dt(now_text())
        if parsed:
            return parsed
    except Exception:
        pass
    return datetime.now()


def _now_text() -> str:
    try:
        from services.timezone_service import now_text
        return str(now_text())
    except Exception:
        return _now_dt().strftime("%Y-%m-%d %H:%M:%S")


def _today_text() -> str:
    try:
        from services.timezone_service import today_text
        return str(today_text()).replace("/", "-")
    except Exception:
        return _now_dt().strftime("%Y-%m-%d")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    text = text.replace("T", " ").replace("/", "-")
    if "+" in text:
        text = text.split("+", 1)[0].strip()
    if text.endswith("Z"):
        text = text[:-1].strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text[:26], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _date_part(value: Any) -> str:
    dt = _parse_dt(value)
    if dt:
        return dt.strftime("%Y-%m-%d")
    text = str(value or "").strip().replace("/", "-")
    return text[:10] if len(text) >= 10 else ""


def _read_json(path: Path) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _extract_records(payload: Any, preferred_tables: Iterable[str] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("records", "data", "rows", "items"):
        val = payload.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    tables = payload.get("tables")
    if isinstance(tables, dict):
        for table in preferred_tables:
            val = tables.get(table)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
        for val in tables.values():
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    return []


def _authority_records(module_key: str, preferred_tables: Iterable[str] = ()) -> list[dict[str, Any]]:
    paths = [
        MODULES_ROOT / module_key / "records.json",
        PERSISTENT_MODULES_ROOT / module_key / f"{module_key}_records.json",
    ]
    # Legacy naming from early builds.
    if module_key == "01_time_records":
        paths.append(PERSISTENT_MODULES_ROOT / "01_time_record" / "01_time_record_records.json")
    for path in paths:
        records = _extract_records(_read_json(path), preferred_tables)
        if records:
            return records
    return []


def _sqlite_path() -> Path | None:
    for path in SQLITE_PATHS:
        if path.exists():
            return path
    return None


def _sqlite_query(table: str, limit: int = 0) -> list[dict[str, Any]]:
    path = _sqlite_path()
    if not path:
        return []
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            sql = f"SELECT * FROM {table}"
            if limit and limit > 0:
                sql += f" LIMIT {int(limit)}"
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _row_get(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in row and row.get(key) is not None:
            text = str(row.get(key)).strip()
            if text and text.lower() not in {"nan", "none", "nat"}:
                return text
    return ""


def _record_key(row: dict[str, Any]) -> str:
    return _row_get(row, "record_key", "紀錄鍵 / Record Key", "Record Key")


def _employee_id(row: dict[str, Any]) -> str:
    emp = _row_get(row, "employee_id", "工號 / Employee ID", "工號", "Employee ID", "username")
    if emp:
        return emp
    rk = _record_key(row)
    return rk.split("|", 1)[0].strip() if "|" in rk else ""


def _employee_name(row: dict[str, Any]) -> str:
    return _row_get(row, "employee_name", "姓名 / Name", "姓名", "Employee Name", "display_name")


def _work_order(row: dict[str, Any]) -> str:
    return _row_get(row, "work_order", "製令 / Work Order", "製令", "Work Order")


def _process_name(row: dict[str, Any]) -> str:
    return _row_get(row, "process_name", "工段 / Process", "製程 / Process", "工段", "製程", "Process")


def _status(row: dict[str, Any]) -> str:
    return _row_get(row, "status", "狀態 / Status", "狀態", "Status")


def _start_ts(row: dict[str, Any]) -> str:
    ts = _row_get(row, "start_timestamp", "開始時間戳 / Start Timestamp", "Start Timestamp", "開始時間")
    if ts:
        return ts
    d = _row_get(row, "start_date", "work_date", "日期 / Date", "開始日期", "工作日期")
    t = _row_get(row, "start_time", "開始時間 / Start Time", "Start Time")
    return f"{d} {t}".strip()


def _end_ts(row: dict[str, Any]) -> str:
    return _row_get(row, "end_timestamp", "結束時間戳 / End Timestamp", "End Timestamp", "結束時間")


def _row_work_date(row: dict[str, Any]) -> str:
    d = _row_get(row, "start_date", "work_date", "日期 / Date", "開始日期", "工作日期")
    if d:
        return _date_part(d)
    return _date_part(_start_ts(row))


def _dedupe_key(row: dict[str, Any]) -> str:
    rk = _record_key(row)
    if rk:
        return "rk:" + rk
    return "biz:" + "|".join([_employee_id(row), _employee_name(row), _work_order(row), _process_name(row), _start_ts(row)])


def _is_active_time_record(row: dict[str, Any]) -> bool:
    st = _status(row).strip().upper()
    if _end_ts(row):
        return False
    if st in {s.upper() for s in TERMINAL_STATUSES}:
        return False
    if st in {s.upper() for s in ACTIVE_STATUSES}:
        return True
    # Treat missing status + no end timestamp as active only if it has a start timestamp.
    return bool(_start_ts(row)) and not st


def _collect_time_records() -> tuple[list[dict[str, Any]], dict[str, int]]:
    source_counts: dict[str, int] = {}
    merged: dict[str, dict[str, Any]] = {}

    sources = [
        ("01_authority", _authority_records("01_time_records", ["time_records"])),
        ("02_authority", _authority_records("02_history", ["time_records", "history"])),
        ("sqlite", _sqlite_query("time_records")),
    ]
    for source, rows in sources:
        source_counts[source] = len(rows)
        for row in rows:
            key = _dedupe_key(row)
            current = dict(row)
            current["_monitor_source"] = source
            # Prefer terminal rows over active rows for the same key; this prevents false active counts.
            if key not in merged:
                merged[key] = current
            else:
                old = merged[key]
                if _end_ts(current) and not _end_ts(old):
                    merged[key] = current
                elif _status(current) in TERMINAL_STATUSES and _status(old) not in TERMINAL_STATUSES:
                    merged[key] = current
    return list(merged.values()), source_counts


def _collect_logs() -> tuple[list[dict[str, Any]], dict[str, int]]:
    sources = [
        ("06_authority", _authority_records("06_logs", ["system_logs", "logs"])),
        ("sqlite_system_logs", _sqlite_query("system_logs")),
        ("sqlite_logs", _sqlite_query("logs")),
    ]
    merged: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for source, rows in sources:
        counts[source] = len(rows)
        for row in rows:
            key = str(row.get("id", "")) + "|" + _row_get(row, "log_time", "created_at", "timestamp") + "|" + _row_get(row, "action_type", "action", "event_type")
            if key not in merged:
                item = dict(row)
                item["_monitor_source"] = source
                merged[key] = item
    return list(merged.values()), counts


def _collect_login_logs() -> tuple[list[dict[str, Any]], dict[str, int]]:
    sources = [
        ("11_authority", _authority_records("11_login_logs", ["login_logs", "auth_login_logs", "security_login_logs"])),
        ("sqlite_auth_login_logs", _sqlite_query("auth_login_logs")),
        ("sqlite_security_login_logs", _sqlite_query("security_login_logs")),
    ]
    merged: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for source, rows in sources:
        counts[source] = len(rows)
        for row in rows:
            key = str(row.get("id", "")) + "|" + _row_get(row, "username", "user_name") + "|" + _row_get(row, "login_time", "created_at", "event_time")
            if key not in merged:
                item = dict(row)
                item["_monitor_source"] = source
                merged[key] = item
    return list(merged.values()), counts


def _log_time(row: dict[str, Any]) -> datetime | None:
    return _parse_dt(_row_get(row, "log_time", "created_at", "timestamp", "event_time", "login_time"))


def _action_type(row: dict[str, Any]) -> str:
    return _row_get(row, "action_type", "action", "event_type", "type").upper()


def _is_log_today(row: dict[str, Any], work_date: str) -> bool:
    dt = _log_time(row)
    if dt:
        return dt.strftime("%Y-%m-%d") == work_date
    return _date_part(_row_get(row, "log_time", "created_at", "timestamp", "event_time", "login_time")) == work_date


def _login_time(row: dict[str, Any]) -> datetime | None:
    return _parse_dt(_row_get(row, "login_time", "created_at", "event_time", "log_time"))


def _is_login_event(row: dict[str, Any]) -> bool:
    ev = _row_get(row, "event_type", "action_type", "action").upper()
    return "LOGIN" in ev and "LOGOUT" not in ev and str(row.get("result", "")).upper() in {"", "SUCCESS", "OK"}


def _is_logout_event(row: dict[str, Any]) -> bool:
    ev = _row_get(row, "event_type", "action_type", "action").upper()
    return "LOGOUT" in ev


def _active_user_estimate(login_logs: list[dict[str, Any]], minutes: int = 30) -> dict[str, Any]:
    cutoff = _now_dt() - timedelta(minutes=minutes)
    last_event: dict[str, dict[str, Any]] = {}
    recent_events = 0
    for row in login_logs:
        user = _row_get(row, "username", "user_name", "employee_id")
        if not user:
            continue
        t = _login_time(row)
        if not t:
            continue
        if t >= cutoff:
            recent_events += 1
        old_t = _login_time(last_event.get(user, {})) if user in last_event else None
        if old_t is None or t >= old_t:
            last_event[user] = row
    active_rows = []
    for user, row in last_event.items():
        t = _login_time(row)
        if not t or t < cutoff:
            continue
        if _is_logout_event(row):
            continue
        if _is_login_event(row) or not _is_logout_event(row):
            active_rows.append({
                "帳號": user,
                "姓名": _row_get(row, "display_name", "employee_name", "user_name"),
                "最後事件": _row_get(row, "event_type", "action_type"),
                "最後時間": t.strftime("%Y-%m-%d %H:%M:%S"),
                "來源": row.get("_monitor_source", ""),
            })
    active_rows.sort(key=lambda r: r.get("最後時間", ""), reverse=True)
    return {
        "window_minutes": minutes,
        "active_user_estimate": len(active_rows),
        "recent_login_events": recent_events,
        "rows": active_rows[:200],
    }


def _backup_summary() -> dict[str, Any]:
    try:
        from services.backup_queue_status_service import collect_backup_queue_status
        status = collect_backup_queue_status()
        summary = status.get("summary", {}) if isinstance(status.get("summary"), dict) else {}
        return {
            "level": status.get("level", "UNKNOWN"),
            "checked_at": status.get("checked_at", ""),
            "authority_pending": _safe_int(summary.get("authority_pending")),
            "event_pending": _safe_int(summary.get("event_pending")),
            "log_pending": bool(summary.get("log_pending")),
            "log_write_count_since_sync": _safe_int(summary.get("log_write_count_since_sync")),
            "missing_key_files": _safe_int(summary.get("missing_key_files")),
            "error_count": _safe_int(summary.get("error_count")),
            "raw": status,
        }
    except Exception as exc:
        return {"level": "ERROR", "error_count": 1, "last_error": str(exc)[:500], "raw": {}}


def _last_backup_info() -> dict[str, Any]:
    candidates: list[Path] = []
    roots = [PERM_ROOT / "backups", PERM_ROOT / "_backups", PROJECT_ROOT / "backups", PROJECT_ROOT / "reports"]
    for root in roots:
        try:
            if root.exists():
                candidates.extend([p for p in root.rglob("*.zip") if p.is_file()])
        except Exception:
            continue
    if not candidates:
        return {"exists": False, "path": "", "modified_at": "", "size_mb": 0.0}
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    return {
        "exists": True,
        "path": str(latest.relative_to(PROJECT_ROOT)) if latest.is_relative_to(PROJECT_ROOT) else str(latest),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
    }


def _sqlite_info() -> dict[str, Any]:
    path = _sqlite_path()
    if not path:
        return {"exists": False, "path": "", "size_mb": 0.0, "modified_at": "", "wal_exists": False, "shm_exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path),
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "wal_exists": path.with_suffix(path.suffix + "-wal").exists(),
        "shm_exists": path.with_suffix(path.suffix + "-shm").exists(),
    }


def _integrity_summary(start_date: str, end_date: str, include: bool) -> dict[str, Any]:
    if not include:
        return {"included": False, "abnormal_count": None, "critical_count": None, "auto_repairable_count": None, "log_start_missing_count": None, "error": ""}
    try:
        from services.time_record_integrity_service import audit_time_record_integrity
        res = audit_time_record_integrity(start_date=start_date, end_date=end_date)
        rows = res.get("issues", []) if isinstance(res, dict) else []
        if isinstance(rows, pd.DataFrame):
            rows_list = rows.to_dict("records")
        elif isinstance(rows, list):
            rows_list = [r for r in rows if isinstance(r, dict)]
        else:
            rows_list = []
        critical = [r for r in rows_list if str(r.get("severity", r.get("嚴重度", ""))).upper() == "CRITICAL"]
        repairable = [r for r in rows_list if str(r.get("auto_repairable", r.get("可自動修復", ""))).upper() in {"YES", "TRUE", "1"}]
        log_missing = [r for r in rows_list if "LOG_START_MISSING" in str(r.get("category", r.get("類別", ""))).upper()]
        return {
            "included": True,
            "abnormal_count": len(rows_list),
            "critical_count": len(critical),
            "auto_repairable_count": len(repairable),
            "log_start_missing_count": len(log_missing),
            "error": "",
        }
    except Exception as exc:
        return {"included": True, "abnormal_count": None, "critical_count": None, "auto_repairable_count": None, "log_start_missing_count": None, "error": str(exc)[:500]}


def collect_system_monitoring_snapshot(
    *,
    work_date: str | None = None,
    active_user_window_minutes: int = 30,
    include_integrity_audit: bool = False,
    integrity_start_date: str | None = None,
    integrity_end_date: str | None = None,
) -> dict[str, Any]:
    """Collect a read-only operational monitoring snapshot."""
    date_text = (work_date or _today_text()).replace("/", "-")[:10]
    rows, source_counts = _collect_time_records()
    logs, log_source_counts = _collect_logs()
    login_logs, login_source_counts = _collect_login_logs()
    now = _now_dt()

    today_records = [r for r in rows if _row_work_date(r) == date_text]
    active_records = [r for r in rows if _is_active_time_record(r)]
    active_today = [r for r in active_records if _row_work_date(r) == date_text]

    long_12: list[dict[str, Any]] = []
    long_16: list[dict[str, Any]] = []
    active_preview: list[dict[str, Any]] = []
    for row in active_records:
        start_dt = _parse_dt(_start_ts(row))
        age_hours = round((now - start_dt).total_seconds() / 3600, 2) if start_dt else None
        item = {
            "工號": _employee_id(row),
            "姓名": _employee_name(row),
            "製令": _work_order(row),
            "工段": _process_name(row),
            "開始時間": _start_ts(row),
            "已作業小時": age_hours,
            "狀態": _status(row),
            "Record Key": _record_key(row),
            "來源": row.get("_monitor_source", ""),
        }
        active_preview.append(item)
        if age_hours is not None and age_hours >= 12:
            long_12.append(item)
        if age_hours is not None and age_hours >= 16:
            long_16.append(item)

    today_logs = [l for l in logs if _is_log_today(l, date_text)]
    start_logs = [l for l in today_logs if any(k in _action_type(l) for k in ("START", "INSERT"))]
    end_logs = [l for l in today_logs if any(k in _action_type(l) for k in END_ACTION_KEYWORDS)]
    error_logs = []
    db_error_logs = []
    for l in today_logs:
        combined = " ".join(str(l.get(k, "")) for k in ("level", "action_type", "message", "detail", "error"))
        up = combined.upper()
        if any(k in up for k in ERROR_KEYWORDS) or str(l.get("level", "")).upper() in {"ERROR", "CRITICAL"}:
            error_logs.append(l)
        if any(k in up for k in ("DATABASE", "SQLITE", "DB", "WRITE", "寫入")) and any(k in up for k in ("ERROR", "失敗", "錯誤", "EXCEPTION")):
            db_error_logs.append(l)

    active_users = _active_user_estimate(login_logs, active_user_window_minutes)
    backup = _backup_summary()
    integrity = _integrity_summary(
        integrity_start_date or date_text,
        integrity_end_date or date_text,
        bool(include_integrity_audit),
    )
    last_backup = _last_backup_info()
    sqlite_info = _sqlite_info()

    risk_score = 0
    warnings: list[str] = []
    if len(long_16):
        risk_score += 30
        warnings.append(f"有 {len(long_16)} 筆作業中超過 16 小時。")
    elif len(long_12):
        risk_score += 15
        warnings.append(f"有 {len(long_12)} 筆作業中超過 12 小時。")
    if backup.get("level") == "ERROR":
        risk_score += 25
        warnings.append("備份佇列狀態為 ERROR。")
    elif backup.get("level") == "WARN":
        risk_score += 10
        warnings.append("備份佇列仍有待補送項目。")
    if len(db_error_logs):
        risk_score += 25
        warnings.append(f"今日疑似資料庫/寫入錯誤 {len(db_error_logs)} 筆。")
    elif len(error_logs):
        risk_score += 10
        warnings.append(f"今日 ERROR/異常 LOG {len(error_logs)} 筆。")
    if integrity.get("included") and integrity.get("critical_count"):
        risk_score += 30
        warnings.append(f"資料健康檢查重大異常 {integrity.get('critical_count')} 筆。")
    if not sqlite_info.get("exists"):
        risk_score += 20
        warnings.append("SQLite 主資料庫不存在；請確認部署資料夾與權威檔。")
    if not warnings:
        warnings.append("目前快速監控未發現高風險警示。")
    level = "OK" if risk_score == 0 else "WARN" if risk_score < 50 else "CRITICAL"

    source_rows = []
    for k, v in source_counts.items():
        source_rows.append({"類別": "time_records", "來源": k, "筆數": v})
    for k, v in log_source_counts.items():
        source_rows.append({"類別": "system_logs", "來源": k, "筆數": v})
    for k, v in login_source_counts.items():
        source_rows.append({"類別": "login_logs", "來源": k, "筆數": v})

    today_process_counter = Counter(_process_name(r) or "未填工段" for r in today_records)
    process_rows = [{"工段": k, "今日工時紀錄筆數": v} for k, v in today_process_counter.most_common(20)]

    metrics = {
        "active_user_estimate": active_users["active_user_estimate"],
        "today_start_logs": len(start_logs),
        "today_end_logs": len(end_logs),
        "today_time_records": len(today_records),
        "active_work_total": len(active_records),
        "active_work_today": len(active_today),
        "active_over_12h": len(long_12),
        "active_over_16h": len(long_16),
        "backup_authority_pending": _safe_int(backup.get("authority_pending")),
        "backup_event_pending": _safe_int(backup.get("event_pending")),
        "backup_log_pending": bool(backup.get("log_pending")),
        "today_error_logs": len(error_logs),
        "today_db_write_error_logs": len(db_error_logs),
        "integrity_critical": integrity.get("critical_count"),
        "integrity_abnormal": integrity.get("abnormal_count"),
        "log_start_missing_count": integrity.get("log_start_missing_count"),
    }

    summary_rows = [
        {"項目": "線上人數估算", "數值": metrics["active_user_estimate"], "狀態": "INFO", "說明": f"近 {active_user_window_minutes} 分鐘登入/活動估算，非精準連線數。"},
        {"項目": "今日開始作業 LOG", "數值": metrics["today_start_logs"], "狀態": "INFO", "說明": "今日 START/INSERT 類 LOG 筆數。"},
        {"項目": "今日結束/暫停/下班 LOG", "數值": metrics["today_end_logs"], "狀態": "INFO", "說明": "今日 FINISH/OFF_DUTY/PAUSE 類 LOG 筆數。"},
        {"項目": "今日工時紀錄", "數值": metrics["today_time_records"], "狀態": "INFO", "說明": "01/02/SQLite 合併去重後今日紀錄。"},
        {"項目": "目前未結束作業", "數值": metrics["active_work_total"], "狀態": "WARN" if metrics["active_work_total"] else "OK", "說明": "無 end_timestamp 且非終止狀態。"},
        {"項目": "作業中超過 12 小時", "數值": metrics["active_over_12h"], "狀態": "WARN" if metrics["active_over_12h"] else "OK", "說明": "建議主管確認是否忘記下班/暫停。"},
        {"項目": "作業中超過 16 小時", "數值": metrics["active_over_16h"], "狀態": "CRITICAL" if metrics["active_over_16h"] else "OK", "說明": "高風險，可能造成假作業中。"},
        {"項目": "GitHub 權威檔待上傳", "數值": metrics["backup_authority_pending"], "狀態": "WARN" if metrics["backup_authority_pending"] else "OK", "說明": "GitHub 只作背景備份，不作即時交易資料庫。"},
        {"項目": "工時事件待上傳", "數值": metrics["backup_event_pending"], "狀態": "WARN" if metrics["backup_event_pending"] else "OK", "說明": "V152 event journal 備份佇列。"},
        {"項目": "今日錯誤 LOG", "數值": metrics["today_error_logs"], "狀態": "WARN" if metrics["today_error_logs"] else "OK", "說明": "今日 ERROR/CRITICAL/例外關鍵字。"},
        {"項目": "今日疑似 DB/寫入錯誤", "數值": metrics["today_db_write_error_logs"], "狀態": "CRITICAL" if metrics["today_db_write_error_logs"] else "OK", "說明": "關鍵字含 SQLite/DB/Database/寫入失敗。"},
    ]
    if integrity.get("included"):
        summary_rows.extend([
            {"項目": "資料健康重大異常", "數值": integrity.get("critical_count"), "狀態": "CRITICAL" if integrity.get("critical_count") else "OK", "說明": "來自 audit_time_record_integrity。"},
            {"項目": "LOG 有但工時缺失", "數值": integrity.get("log_start_missing_count"), "狀態": "WARN" if integrity.get("log_start_missing_count") else "OK", "說明": "可搭配 V164B 待補還原。"},
        ])

    return {
        "version": "V166_system_monitoring_dashboard",
        "checked_at": _now_text(),
        "work_date": date_text,
        "level": level,
        "risk_score": min(risk_score, 100),
        "warnings": warnings,
        "metrics": metrics,
        "summary_rows": summary_rows,
        "source_rows": source_rows,
        "active_work_preview_rows": sorted(active_preview, key=lambda r: str(r.get("開始時間", "")), reverse=True)[:300],
        "long_active_over_12h_rows": sorted(long_12, key=lambda r: float(r.get("已作業小時") or 0), reverse=True)[:300],
        "active_users_rows": active_users.get("rows", []),
        "process_rows": process_rows,
        "backup_summary": backup,
        "last_backup": last_backup,
        "sqlite_info": sqlite_info,
        "integrity_summary": integrity,
        "production_write_path_changed": False,
        "read_only": True,
    }


def monitoring_summary_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = snapshot.get("summary_rows") if isinstance(snapshot, dict) else []
    return rows if isinstance(rows, list) else []


def export_monitoring_excel_bytes(snapshot: dict[str, Any]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(monitoring_summary_rows(snapshot)).to_excel(writer, index=False, sheet_name="summary")
        pd.DataFrame(snapshot.get("active_work_preview_rows", [])).to_excel(writer, index=False, sheet_name="active_work")
        pd.DataFrame(snapshot.get("long_active_over_12h_rows", [])).to_excel(writer, index=False, sheet_name="long_active")
        pd.DataFrame(snapshot.get("active_users_rows", [])).to_excel(writer, index=False, sheet_name="active_users")
        pd.DataFrame(snapshot.get("process_rows", [])).to_excel(writer, index=False, sheet_name="process")
        pd.DataFrame(snapshot.get("source_rows", [])).to_excel(writer, index=False, sheet_name="sources")
        meta_rows = [
            {"key": "version", "value": snapshot.get("version", "")},
            {"key": "checked_at", "value": snapshot.get("checked_at", "")},
            {"key": "work_date", "value": snapshot.get("work_date", "")},
            {"key": "level", "value": snapshot.get("level", "")},
            {"key": "risk_score", "value": snapshot.get("risk_score", "")},
            {"key": "read_only", "value": snapshot.get("read_only", "")},
            {"key": "production_write_path_changed", "value": snapshot.get("production_write_path_changed", "")},
            {"key": "warnings", "value": " | ".join(snapshot.get("warnings", []))},
            {"key": "sqlite_info", "value": json.dumps(snapshot.get("sqlite_info", {}), ensure_ascii=False)},
            {"key": "last_backup", "value": json.dumps(snapshot.get("last_backup", {}), ensure_ascii=False)},
            {"key": "integrity_summary", "value": json.dumps(snapshot.get("integrity_summary", {}), ensure_ascii=False)},
        ]
        pd.DataFrame(meta_rows).to_excel(writer, index=False, sheet_name="meta")
    return output.getvalue()
