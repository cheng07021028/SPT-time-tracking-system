# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spt_core.db import backend, execute, fetch_all, fetch_one, init_db, transaction
from spt_core.security import hash_password
from spt_core.utils import json_dumps, now_iso

ROLE_MAP = {
    "admin": "admin",
    "administrator": "admin",
    "manager": "supervisor",
    "leader": "supervisor",
    "supervisor": "supervisor",
    "auditor": "supervisor",
    "viewer": "operator",
    "operator": "operator",
    "user": "operator",
}

STATUS_MAP = {
    "作業中": "active",
    "進行中": "active",
    "active": "active",
    "完工": "completed",
    "下班": "completed",
    "completed": "completed",
    "暫停": "paused",
    "paused": "paused",
    "刪除": "deleted",
    "deleted": "deleted",
}

LEGACY_DB_TABLES = ["auth_users", "auth_account_permissions", "auth_login_logs", "system_logs", "spt_module_authority"]


def stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]}"


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def pick(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return default


def truthy(value: Any, default: bool = False) -> int:
    if value is None or value == "":
        return 1 if default else 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "y", "on", "啟用", "是"} else 0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def to_isoish(value: Any, date_part: str = "") -> str:
    text = clean_text(value)
    if text:
        return text.replace(" ", "T", 1)
    if date_part:
        return f"{date_part}T00:00:00"
    return now_iso()


def process_code(name: str) -> str:
    text = clean_text(name, "未分類")
    return text.upper().replace(" ", "_")[:80] or "UNCATEGORIZED"


def table_exists(conn, table_name: str) -> bool:
    if backend() == "postgres":
        row = fetch_one(
            conn,
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name=:table_name
            """,
            {"table_name": table_name},
        )
        return bool(row)
    row = fetch_one(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name", {"table_name": table_name})
    return bool(row)


def table_columns(conn, table_name: str) -> set[str]:
    if backend() == "postgres":
        rows = fetch_all(
            conn,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:table_name
            """,
            {"table_name": table_name},
        )
        return {str(r["column_name"]) for r in rows}
    rows = fetch_all(conn, f"PRAGMA table_info({table_name})")
    return {str(r["name"]) for r in rows}


def select_all_if_exists(conn, table_name: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table_name):
        return []
    return fetch_all(conn, f"SELECT * FROM {table_name}")


def upsert(conn, table: str, pk: str, row: dict[str, Any]) -> None:
    row = {k: v for k, v in row.items() if k}
    if not row:
        return
    keys = list(row.keys())
    cols = ", ".join(keys)
    vals = ", ".join(f":{k}" for k in keys)
    updates = ", ".join(f"{k}=excluded.{k}" for k in keys if k != pk)
    if not updates:
        execute(conn, f"INSERT OR IGNORE INTO {table}({cols}) VALUES({vals})", row)
        return
    execute(conn, f"INSERT INTO {table}({cols}) VALUES({vals}) ON CONFLICT({pk}) DO UPDATE SET {updates}", row)


def ensure_process(conn, code: str, name: str) -> None:
    if fetch_one(conn, "SELECT process_code FROM processes WHERE process_code=:code", {"code": code}):
        return
    now = now_iso()
    upsert(
        conn,
        "processes",
        "process_code",
        {
            "process_code": code,
            "process_name": name or code,
            "sort_order": 999,
            "active": 1,
            "allow_parallel": 1,
            "allow_group_average": 1,
            "standard_minutes": 0,
            "created_at": now,
            "updated_at": now,
        },
    )


def ensure_employee(conn, employee_id: str, employee_name: str) -> None:
    if not employee_id or fetch_one(conn, "SELECT employee_id FROM employees WHERE employee_id=:employee_id", {"employee_id": employee_id}):
        return
    now = now_iso()
    upsert(
        conn,
        "employees",
        "employee_id",
        {
            "employee_id": employee_id,
            "employee_name": employee_name or employee_id,
            "active": 1,
            "is_in_factory": 1,
            "is_today_attendance": 1,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        },
    )


def ensure_work_order(conn, work_order_no: str) -> None:
    if not work_order_no or fetch_one(conn, "SELECT work_order_no FROM work_orders WHERE work_order_no=:work_order_no", {"work_order_no": work_order_no}):
        return
    now = now_iso()
    upsert(
        conn,
        "work_orders",
        "work_order_no",
        {
            "work_order_no": work_order_no,
            "status": "open",
            "active": 1,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        },
    )


def resolve_legacy_root(path_text: str) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    raw = Path(path_text).expanduser().resolve()
    temp = None
    if raw.is_file() and raw.suffix.lower() == ".zip":
        temp = tempfile.TemporaryDirectory(prefix="spt_legacy_")
        with zipfile.ZipFile(raw, "r") as zf:
            zf.extractall(temp.name)
        base = Path(temp.name)
    else:
        base = raw
    candidates = [base, base / "SPT-time-tracking-system-main", base / "data" / "permanent_store"]
    for candidate in candidates:
        if (candidate / "data" / "permanent_store" / "modules").exists():
            return candidate / "data" / "permanent_store", temp
        if (candidate / "modules").exists():
            return candidate, temp
    raise FileNotFoundError("找不到 legacy data/permanent_store/modules，請指定舊專案根目錄或舊 ZIP。")


def load_module_records(ps_root: Path, module_key: str) -> dict[str, Any]:
    path = ps_root / "modules" / module_key / "records.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_table(ps_root: Path, module_key: str, table_name: str) -> list[dict[str, Any]]:
    data = load_module_records(ps_root, module_key)
    rows = data.get("tables", {}).get(table_name, [])
    return rows if isinstance(rows, list) else []


def import_permanent_store(conn, ps_root: Path) -> dict[str, int]:
    summary = {"employees": 0, "work_orders": 0, "users": 0, "account_permissions": 0, "processes": 0, "rest_periods": 0, "time_records": 0, "legacy_logs": 0, "system_settings": 0}
    now = now_iso()

    for row in load_table(ps_root, "04_employees", "employees"):
        employee_id = clean_text(pick(row, "employee_id", "id"))
        if not employee_id:
            continue
        upsert(conn, "employees", "employee_id", {
            "employee_id": employee_id,
            "employee_name": clean_text(pick(row, "employee_name", "name"), employee_id),
            "department": clean_text(pick(row, "department")),
            "team": clean_text(pick(row, "team")),
            "role": clean_text(pick(row, "role", "title")),
            "title": clean_text(pick(row, "title")),
            "active": truthy(pick(row, "active", "is_active"), True),
            "is_in_factory": truthy(pick(row, "is_in_factory"), True),
            "is_today_attendance": truthy(pick(row, "is_today_attendance"), True),
            "permission_group": clean_text(pick(row, "permission_group")),
            "note": clean_text(pick(row, "note")),
            "created_at": to_isoish(pick(row, "created_at")),
            "updated_at": to_isoish(pick(row, "updated_at")),
            "deleted_at": clean_text(pick(row, "deleted_at")) or None,
            "deleted_by": clean_text(pick(row, "deleted_by")),
            "version": 1,
        })
        summary["employees"] += 1

    for row in load_table(ps_root, "03_work_orders", "work_orders"):
        work_order_no = clean_text(pick(row, "work_order", "work_order_no", "id"))
        if not work_order_no:
            continue
        active = truthy(pick(row, "active", "is_active"), True)
        upsert(conn, "work_orders", "work_order_no", {
            "work_order_no": work_order_no,
            "model": clean_text(pick(row, "model", "part_no")),
            "product_name": clean_text(pick(row, "product_name", "type_name")),
            "part_no": clean_text(pick(row, "part_no")),
            "type_name": clean_text(pick(row, "type_name")),
            "assembly_location": clean_text(pick(row, "assembly_location")),
            "customer": clean_text(pick(row, "customer")),
            "note": clean_text(pick(row, "note")),
            "planned_qty": safe_float(pick(row, "planned_qty")),
            "completed_qty": safe_float(pick(row, "completed_qty")),
            "status": clean_text(pick(row, "status"), "open" if active else "closed"),
            "process_flow": clean_text(pick(row, "process_flow")),
            "active": active,
            "created_at": to_isoish(pick(row, "created_at")),
            "updated_at": to_isoish(pick(row, "updated_at")),
            "deleted_at": clean_text(pick(row, "deleted_at")) or None,
            "deleted_by": clean_text(pick(row, "deleted_by")),
            "version": 1,
        })
        summary["work_orders"] += 1

    for row in load_table(ps_root, "10_permissions", "auth_users"):
        username = clean_text(pick(row, "username", "account"))
        password_hash = clean_text(pick(row, "password_hash"))
        password = clean_text(pick(row, "password"))
        if not username or not (password_hash or password):
            continue
        role = ROLE_MAP.get(clean_text(pick(row, "role_code", "role"), "operator").lower(), "operator")
        upsert(conn, "users", "username", {
            "username": username,
            "display_name": clean_text(pick(row, "display_name", "name"), username),
            "password_hash": password_hash or hash_password(password),
            "role": role,
            "employee_id": clean_text(pick(row, "employee_id")),
            "email": clean_text(pick(row, "email")),
            "active": truthy(pick(row, "active", "is_active"), True),
            "force_password_change": truthy(pick(row, "force_password_change"), False),
            "password_hint": clean_text(pick(row, "password_hint")),
            "last_login_at": clean_text(pick(row, "last_login_at")) or None,
            "note": clean_text(pick(row, "note")),
            "created_at": to_isoish(pick(row, "created_at")),
            "updated_at": to_isoish(pick(row, "updated_at")),
            "deleted_at": None,
        })
        summary["users"] += 1

    for row in load_table(ps_root, "10_permissions", "auth_account_permissions"):
        username = clean_text(pick(row, "username"))
        module_code = clean_text(pick(row, "module_code"))
        if not username or not module_code:
            continue
        upsert(conn, "account_permissions", "permission_id", {
            "permission_id": f"{username}|{module_code}",
            "username": username,
            "module_code": module_code,
            "module_name_zh": clean_text(pick(row, "module_name_zh")),
            "module_name_en": clean_text(pick(row, "module_name_en")),
            "can_view": truthy(pick(row, "can_view")),
            "can_create": truthy(pick(row, "can_create")),
            "can_edit": truthy(pick(row, "can_edit")),
            "can_delete": truthy(pick(row, "can_delete")),
            "can_import": truthy(pick(row, "can_import")),
            "can_export": truthy(pick(row, "can_export")),
            "can_backup": truthy(pick(row, "can_backup")),
            "can_restore": truthy(pick(row, "can_restore")),
            "can_manage": truthy(pick(row, "can_manage")),
            "updated_at": to_isoish(pick(row, "updated_at")),
        })
        summary["account_permissions"] += 1

    for row in load_table(ps_root, "13_system_settings", "process_options"):
        name = clean_text(pick(row, "process_name", "name"))
        if not name:
            continue
        code = process_code(name)
        upsert(conn, "processes", "process_code", {
            "process_code": code,
            "process_name": name,
            "process_category": clean_text(pick(row, "category_name", "process_category")),
            "sort_order": int(safe_float(pick(row, "sort_order"))),
            "active": truthy(pick(row, "active", "is_active"), True),
            "allow_parallel": 1,
            "allow_group_average": 1,
            "standard_minutes": safe_float(pick(row, "standard_minutes")),
            "note": clean_text(pick(row, "note")),
            "created_at": to_isoish(pick(row, "created_at")),
            "updated_at": to_isoish(pick(row, "updated_at")),
        })
        summary["processes"] += 1

    for row in load_table(ps_root, "13_system_settings", "rest_periods"):
        rid = clean_text(pick(row, "rest_period_id", "id")) or stable_id("rest", row)
        upsert(conn, "rest_periods", "rest_period_id", {
            "rest_period_id": rid,
            "name": clean_text(pick(row, "name"), rid),
            "start_time": clean_text(pick(row, "start_time"), "00:00"),
            "end_time": clean_text(pick(row, "end_time"), "00:00"),
            "active": truthy(pick(row, "active", "is_active"), True),
            "sort_order": int(safe_float(pick(row, "sort_order"))),
            "created_at": now,
            "updated_at": now,
        })
        summary["rest_periods"] += 1

    for module_key in ["01_time_records", "02_history"]:
        for row in load_table(ps_root, module_key, "time_records"):
            rid = clean_text(pick(row, "record_key", "record_id", "id"))
            if not rid:
                continue
            status = STATUS_MAP.get(clean_text(pick(row, "status")), "completed" if clean_text(pick(row, "end_time", "end_timestamp")) else "active")
            if truthy(pick(row, "is_deleted"), False) or clean_text(pick(row, "deleted_at")):
                status = "deleted"
            process_name = clean_text(pick(row, "process_name"), "未分類")
            pcode = clean_text(pick(row, "process_code")) or process_code(process_name)
            employee_id = clean_text(pick(row, "employee_id"))
            employee_name = clean_text(pick(row, "employee_name"), employee_id)
            work_order_no = clean_text(pick(row, "work_order_no", "work_order"), "未指定")
            ensure_employee(conn, employee_id, employee_name)
            ensure_work_order(conn, work_order_no)
            ensure_process(conn, pcode, process_name)
            start_time = to_isoish(pick(row, "start_time", "start_timestamp"), clean_text(pick(row, "start_date")))
            end_raw = clean_text(pick(row, "end_time", "end_timestamp"))
            work_minutes = safe_float(pick(row, "work_minutes")) or safe_float(pick(row, "work_hours")) * 60.0
            upsert(conn, "time_records", "record_id", {
                "record_id": rid,
                "legacy_id": clean_text(pick(row, "id")),
                "record_key": clean_text(pick(row, "record_key")),
                "work_date": clean_text(pick(row, "work_date", "start_date")) or start_time[:10],
                "employee_id": employee_id,
                "employee_name": employee_name,
                "work_order_no": work_order_no,
                "part_no": clean_text(pick(row, "part_no")),
                "type_name": clean_text(pick(row, "type_name")),
                "assembly_location": clean_text(pick(row, "assembly_location")),
                "process_code": pcode,
                "process_name": process_name,
                "start_action": clean_text(pick(row, "start_action")),
                "end_action": clean_text(pick(row, "end_action")),
                "start_time": start_time,
                "end_time": to_isoish(end_raw) if end_raw else None,
                "start_date": clean_text(pick(row, "start_date")),
                "end_date": clean_text(pick(row, "end_date")),
                "status": status,
                "group_key": clean_text(pick(row, "group_key")) or f"{employee_id}|{pcode}|{start_time[:16]}",
                "raw_minutes": work_minutes,
                "work_minutes": work_minutes,
                "average_minutes": safe_float(pick(row, "average_minutes"), work_minutes),
                "work_hours_hms": clean_text(pick(row, "work_hours_hms")),
                "pause_reason": clean_text(pick(row, "pause_reason")),
                "remark": clean_text(pick(row, "remark", "note")),
                "source": "legacy_permanent_store",
                "created_by": clean_text(pick(row, "created_by"), "legacy_migration"),
                "created_at": to_isoish(pick(row, "created_at")),
                "updated_by": clean_text(pick(row, "updated_by"), "legacy_migration"),
                "updated_at": to_isoish(pick(row, "updated_at")),
                "deleted_at": to_isoish(pick(row, "deleted_at")) if clean_text(pick(row, "deleted_at")) else None,
                "deleted_by": clean_text(pick(row, "deleted_by")),
                "delete_reason": clean_text(pick(row, "delete_reason")),
                "version": 1,
            })
            summary["time_records"] += 1

    log_file = ps_root / "modules" / "06_log_query" / "records.jsonl"
    if log_file.exists():
        for raw in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                row = {"raw": raw}
            upsert(conn, "operation_logs", "log_id", {
                "log_id": clean_text(pick(row, "log_id", "authority_event_id")) or stable_id("legacy_log", row),
                "timestamp": to_isoish(pick(row, "timestamp", "log_time", "created_at", "authority_written_at")),
                "actor": clean_text(pick(row, "actor", "user_name", "username")),
                "module": clean_text(pick(row, "module", "authority_module_key"), "legacy_log"),
                "action": clean_text(pick(row, "action", "action_type"), "legacy_log"),
                "target_type": clean_text(pick(row, "target_type", "target_table")),
                "target_id": clean_text(pick(row, "target_id")),
                "before_value": None,
                "after_value": json_dumps(row),
                "result": clean_text(pick(row, "result", "level"), "INFO"),
                "error_message": clean_text(pick(row, "error_message", "message")),
                "request_id": clean_text(pick(row, "request_id")),
                "app_version": "legacy_migration",
            })
            summary["legacy_logs"] += 1

    for source in [ps_root / "config" / "system_settings.json", ps_root / "system" / "security_settings.json", ps_root / "modules" / "13_system_settings" / "records.json"]:
        if not source.exists():
            continue
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = "legacy." + source.relative_to(ps_root).as_posix().replace("/", ".")
        upsert(conn, "system_settings", "setting_key", {"setting_key": key, "setting_value": json_dumps(payload), "updated_at": now, "updated_by": "legacy_migration"})
        summary["system_settings"] += 1

    return summary


def import_same_database_legacy_tables(conn) -> dict[str, int]:
    summary = {name: 0 for name in LEGACY_DB_TABLES}
    now = now_iso()

    for row in select_all_if_exists(conn, "auth_users"):
        username = clean_text(pick(row, "username", "account"))
        password_hash = clean_text(pick(row, "password_hash"))
        password = clean_text(pick(row, "password"))
        if not username or not (password_hash or password):
            continue
        role = ROLE_MAP.get(clean_text(pick(row, "role_code", "role"), "operator").lower(), "operator")
        upsert(conn, "users", "username", {
            "username": username,
            "display_name": clean_text(pick(row, "display_name", "name"), username),
            "password_hash": password_hash or hash_password(password),
            "role": role,
            "employee_id": clean_text(pick(row, "employee_id")),
            "email": clean_text(pick(row, "email")),
            "active": truthy(pick(row, "active", "is_active"), True),
            "force_password_change": truthy(pick(row, "force_password_change"), False),
            "password_hint": clean_text(pick(row, "password_hint")),
            "last_login_at": clean_text(pick(row, "last_login_at")) or None,
            "note": clean_text(pick(row, "note")),
            "created_at": to_isoish(pick(row, "created_at")),
            "updated_at": to_isoish(pick(row, "updated_at")),
            "deleted_at": clean_text(pick(row, "deleted_at")) or None,
        })
        summary["auth_users"] += 1

    for row in select_all_if_exists(conn, "auth_account_permissions"):
        username = clean_text(pick(row, "username"))
        module_code = clean_text(pick(row, "module_code", "module_key"))
        if not username or not module_code:
            continue
        upsert(conn, "account_permissions", "permission_id", {
            "permission_id": clean_text(pick(row, "permission_id")) or f"{username}|{module_code}",
            "username": username,
            "module_code": module_code,
            "module_name_zh": clean_text(pick(row, "module_name_zh", "module_name")),
            "module_name_en": clean_text(pick(row, "module_name_en")),
            "can_view": truthy(pick(row, "can_view")),
            "can_create": truthy(pick(row, "can_create")),
            "can_edit": truthy(pick(row, "can_edit")),
            "can_delete": truthy(pick(row, "can_delete")),
            "can_import": truthy(pick(row, "can_import")),
            "can_export": truthy(pick(row, "can_export")),
            "can_backup": truthy(pick(row, "can_backup")),
            "can_restore": truthy(pick(row, "can_restore")),
            "can_manage": truthy(pick(row, "can_manage")),
            "updated_at": to_isoish(pick(row, "updated_at")),
        })
        summary["auth_account_permissions"] += 1

    for row in select_all_if_exists(conn, "auth_login_logs"):
        upsert(conn, "login_events", "login_event_id", {
            "login_event_id": clean_text(pick(row, "login_event_id", "id")) or stable_id("login", row),
            "timestamp": to_isoish(pick(row, "timestamp", "login_time", "created_at")),
            "username": clean_text(pick(row, "username")),
            "display_name": clean_text(pick(row, "display_name")),
            "role": ROLE_MAP.get(clean_text(pick(row, "role"), "operator").lower(), clean_text(pick(row, "role"), "operator")),
            "login_result": clean_text(pick(row, "login_result", "result", "status"), "unknown"),
            "session_id": clean_text(pick(row, "session_id")),
            "error_message": clean_text(pick(row, "error_message", "message")),
            "logout_time": clean_text(pick(row, "logout_time")) or None,
        })
        summary["auth_login_logs"] += 1

    for row in select_all_if_exists(conn, "system_logs"):
        upsert(conn, "operation_logs", "log_id", {
            "log_id": clean_text(pick(row, "log_id", "id")) or stable_id("syslog", row),
            "timestamp": to_isoish(pick(row, "timestamp", "created_at", "log_time")),
            "actor": clean_text(pick(row, "actor", "username", "user_name")),
            "module": clean_text(pick(row, "module", "module_key"), "legacy_system_log"),
            "action": clean_text(pick(row, "action", "action_type"), "legacy_log"),
            "target_type": clean_text(pick(row, "target_type", "target_table")),
            "target_id": clean_text(pick(row, "target_id")),
            "before_value": clean_text(pick(row, "before_value")) or None,
            "after_value": clean_text(pick(row, "after_value")) or json_dumps(row),
            "result": clean_text(pick(row, "result", "level"), "INFO"),
            "error_message": clean_text(pick(row, "error_message", "message")),
            "request_id": clean_text(pick(row, "request_id")),
            "app_version": clean_text(pick(row, "app_version"), "legacy_migration"),
        })
        summary["system_logs"] += 1

    for row in select_all_if_exists(conn, "spt_module_authority"):
        module_key = clean_text(pick(row, "module_key", "module", "authority_module_key"), "legacy")
        kind = clean_text(pick(row, "kind", "record_kind", "table_name"), "legacy")
        record_key = clean_text(pick(row, "record_key", "target_id", "id"))
        payload = pick(row, "payload", "payload_json", "data_json", default=None)
        if not payload:
            payload = json_dumps(row)
        upsert(conn, "module_authority", "authority_id", {
            "authority_id": clean_text(pick(row, "authority_id", "id")) or stable_id("auth", row),
            "module_key": module_key,
            "kind": kind,
            "record_key": record_key,
            "payload": payload if isinstance(payload, str) else json_dumps(payload),
            "updated_at": to_isoish(pick(row, "updated_at", "authority_written_at", "created_at")),
            "updated_by": clean_text(pick(row, "updated_by", "actor", "user_name"), "legacy_migration"),
            "deleted_at": clean_text(pick(row, "deleted_at")) or None,
        })
        summary["spt_module_authority"] += 1

    if any(summary.values()):
        upsert(conn, "operation_logs", "log_id", {
            "log_id": stable_id("migration", {"same_database": summary, "at": now}),
            "timestamp": now,
            "actor": "legacy_migration",
            "module": "migration",
            "action": "import_same_database_legacy_tables",
            "target_type": "database",
            "target_id": "same_database",
            "before_value": None,
            "after_value": json_dumps(summary),
            "result": "success",
            "error_message": None,
            "request_id": None,
            "app_version": "clean_architecture",
        })
    return summary


def migrate(legacy_path: str | None = None, same_database: bool = True, dry_run: bool = False) -> dict[str, Any]:
    init_db()
    temp = None
    dry_run_result: dict[str, Any] | None = None
    try:
        with transaction() as conn:
            result: dict[str, Any] = {"same_database": {}, "permanent_store": {}}
            if same_database:
                result["same_database"] = import_same_database_legacy_tables(conn)
            if legacy_path:
                ps_root, temp = resolve_legacy_root(legacy_path)
                result["permanent_store"] = import_permanent_store(conn, ps_root)
            upsert(conn, "operation_logs", "log_id", {
                "log_id": stable_id("migration", {"result": result, "at": now_iso()}),
                "timestamp": now_iso(),
                "actor": "legacy_migration",
                "module": "migration",
                "action": "migrate_legacy_to_clean",
                "target_type": "database",
                "target_id": "clean_schema",
                "before_value": None,
                "after_value": json_dumps(result),
                "result": "dry_run" if dry_run else "success",
                "error_message": None,
                "request_id": None,
                "app_version": "clean_architecture",
            })
            if dry_run:
                dry_run_result = result
                raise RuntimeError("DRY_RUN_ROLLBACK")
        return result
    except RuntimeError as exc:
        if str(exc) == "DRY_RUN_ROLLBACK":
            return {"dry_run": True, "rolled_back": True, "planned_summary": dry_run_result or {}}
        raise
    finally:
        if temp is not None:
            temp.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy SPT data into the clean Neon/PostgreSQL schema.")
    parser.add_argument("--legacy-path", help="舊專案根目錄或舊 ZIP；會匯入 data/permanent_store/modules。")
    parser.add_argument("--same-database", action="store_true", help="同一個 DATABASE_URL 內若存在舊表，匯入 auth_users/system_logs 等舊表。")
    parser.add_argument("--skip-same-database", action="store_true", help="不要掃描同 DB 舊表。")
    parser.add_argument("--dry-run", action="store_true", help="測試流程但 rollback。")
    args = parser.parse_args()
    same_db = args.same_database or not args.skip_same_database
    result = migrate(args.legacy_path, same_database=same_db, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
