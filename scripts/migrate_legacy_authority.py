from __future__ import annotations

import argparse
import json
import sys
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from typing import Any

from spt_core.db import execute, fetch_one, init_db, transaction
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


def truthy(v: Any, default: bool = False) -> int:
    if v is None or v == "":
        return 1 if default else 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return 1 if v else 0
    s = str(v).strip().lower()
    return 1 if s in {"1", "true", "yes", "y", "啟用", "是", "on"} else 0


def clean_text(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def dt(v: Any) -> str:
    return clean_text(v) or now_iso()


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def sql_id(prefix: str, value: Any) -> str:
    s = clean_text(value)
    if not s:
        s = now_iso()
    return f"{prefix}_{abs(hash(s))}"


def process_code(name: str) -> str:
    name = clean_text(name, "未分類")
    # Keep Chinese process names readable while making a stable primary key.
    return name.upper().replace(" ", "_")[:80]


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

    candidates = [
        base,
        base / "SPT-time-tracking-system-main",
        base / "data" / "permanent_store",
    ]
    for c in candidates:
        if (c / "data" / "permanent_store" / "modules").exists():
            return c, temp
        if (c / "modules").exists():
            return c, temp
    raise FileNotFoundError("找不到 legacy data/permanent_store/modules，請指定舊專案根目錄或舊 ZIP。")


def permanent_store_root(root: Path) -> Path:
    if (root / "data" / "permanent_store").exists():
        return root / "data" / "permanent_store"
    if (root / "modules").exists():
        return root
    raise FileNotFoundError("找不到 data/permanent_store")


def load_module_records(ps_root: Path, module_key: str) -> dict[str, Any]:
    p = ps_root / "modules" / module_key / "records.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_table(ps_root: Path, module_key: str, table_name: str) -> list[dict[str, Any]]:
    data = load_module_records(ps_root, module_key)
    rows = data.get("tables", {}).get(table_name, [])
    return rows if isinstance(rows, list) else []


def upsert(conn, table: str, pk: str, row: dict[str, Any]) -> None:
    keys = list(row.keys())
    insert_cols = ", ".join(keys)
    insert_vals = ", ".join(f":{k}" for k in keys)
    update_cols = ", ".join(f"{k}=excluded.{k}" for k in keys if k != pk)
    execute(
        conn,
        f"""
        INSERT INTO {table}({insert_cols}) VALUES({insert_vals})
        ON CONFLICT({pk}) DO UPDATE SET {update_cols}
        """,
        row,
    )


def import_employees(conn, ps_root: Path) -> int:
    count = 0
    for r in load_table(ps_root, "04_employees", "employees"):
        employee_id = clean_text(r.get("employee_id")) or clean_text(r.get("id"))
        if not employee_id:
            continue
        row = {
            "employee_id": employee_id,
            "employee_name": clean_text(r.get("employee_name"), employee_id),
            "department": clean_text(r.get("department")),
            "team": clean_text(r.get("team")),
            "role": clean_text(r.get("title")),
            "title": clean_text(r.get("title")),
            "active": truthy(r.get("is_active"), True),
            "is_in_factory": truthy(r.get("is_in_factory"), True),
            "is_today_attendance": truthy(r.get("is_today_attendance"), True),
            "permission_group": clean_text(r.get("permission_group")),
            "note": clean_text(r.get("note")),
            "created_at": dt(r.get("created_at")),
            "updated_at": dt(r.get("updated_at")),
            "deleted_at": clean_text(r.get("deleted_at")) or None,
            "deleted_by": clean_text(r.get("deleted_by")),
            "version": 1,
        }
        upsert(conn, "employees", "employee_id", row)
        count += 1
    return count


def import_work_orders(conn, ps_root: Path) -> int:
    count = 0
    for r in load_table(ps_root, "03_work_orders", "work_orders"):
        work_order_no = clean_text(r.get("work_order")) or clean_text(r.get("work_order_no")) or clean_text(r.get("id"))
        if not work_order_no:
            continue
        active = truthy(r.get("is_active"), True)
        row = {
            "work_order_no": work_order_no,
            "model": clean_text(r.get("part_no")),
            "product_name": clean_text(r.get("type_name")),
            "part_no": clean_text(r.get("part_no")),
            "type_name": clean_text(r.get("type_name")),
            "assembly_location": clean_text(r.get("assembly_location")),
            "customer": clean_text(r.get("customer")),
            "note": clean_text(r.get("note")),
            "planned_qty": safe_float(r.get("planned_qty")),
            "completed_qty": safe_float(r.get("completed_qty")),
            "status": "open" if active else "closed",
            "process_flow": clean_text(r.get("process_flow")),
            "active": active,
            "created_at": dt(r.get("created_at")),
            "updated_at": dt(r.get("updated_at")),
            "deleted_at": clean_text(r.get("deleted_at")) or None,
            "deleted_by": clean_text(r.get("deleted_by")),
            "version": 1,
        }
        upsert(conn, "work_orders", "work_order_no", row)
        count += 1
    return count


def import_processes_and_rest(conn, ps_root: Path) -> tuple[int, int, int]:
    p_count = 0
    categories = 0
    seen = set()
    for r in load_table(ps_root, "13_system_settings", "process_options"):
        name = clean_text(r.get("process_name"))
        if not name:
            continue
        code = process_code(name)
        if code in seen:
            continue
        seen.add(code)
        row = {
            "process_code": code,
            "process_name": name,
            "process_category": clean_text(r.get("category_name")),
            "sort_order": int(safe_float(r.get("sort_order"))),
            "active": truthy(r.get("is_active"), True),
            "allow_parallel": 1,
            "allow_group_average": 1,
            "standard_minutes": safe_float(r.get("standard_minutes")),
            "note": clean_text(r.get("note")),
            "created_at": dt(r.get("created_at")),
            "updated_at": dt(r.get("updated_at")),
        }
        upsert(conn, "processes", "process_code", row)
        p_count += 1

    for r in load_table(ps_root, "13_system_settings", "process_categories"):
        key = "process_category." + clean_text(r.get("category_name"), str(r.get("id")))
        if not key.endswith("."):
            upsert(conn, "system_settings", "setting_key", {
                "setting_key": key,
                "setting_value": json_dumps(r),
                "updated_at": dt(r.get("updated_at")),
                "updated_by": "legacy_migration",
            })
            categories += 1

    rest_count = 0
    for r in load_table(ps_root, "13_system_settings", "rest_periods"):
        rid = clean_text(r.get("id")) or sql_id("rest", r)
        row = {
            "rest_period_id": rid,
            "name": clean_text(r.get("name"), rid),
            "start_time": clean_text(r.get("start_time"), "00:00"),
            "end_time": clean_text(r.get("end_time"), "00:00"),
            "active": truthy(r.get("is_active"), True),
            "sort_order": int(safe_float(r.get("sort_order"))),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        upsert(conn, "rest_periods", "rest_period_id", row)
        rest_count += 1
    return p_count, categories, rest_count


def import_users_and_permissions(conn, ps_root: Path) -> tuple[int, int]:
    count = 0
    for r in load_table(ps_root, "10_permissions", "auth_users"):
        username = clean_text(r.get("username"))
        password_hash = clean_text(r.get("password_hash"))
        if not username or not password_hash:
            continue
        role = ROLE_MAP.get(clean_text(r.get("role_code")).lower(), "operator")
        row = {
            "username": username,
            "display_name": clean_text(r.get("display_name"), username),
            "password_hash": password_hash,
            "role": role,
            "employee_id": clean_text(r.get("employee_id")),
            "email": clean_text(r.get("email")),
            "active": truthy(r.get("is_active"), True),
            "force_password_change": truthy(r.get("force_password_change"), False),
            "password_hint": clean_text(r.get("password_hint")),
            "last_login_at": clean_text(r.get("last_login_at")) or None,
            "note": clean_text(r.get("note")),
            "created_at": dt(r.get("created_at")),
            "updated_at": dt(r.get("updated_at")),
            "deleted_at": None,
        }
        upsert(conn, "users", "username", row)
        count += 1

    p_count = 0
    for r in load_table(ps_root, "10_permissions", "auth_account_permissions"):
        username = clean_text(r.get("username"))
        module_code = clean_text(r.get("module_code"))
        if not username or not module_code:
            continue
        row = {
            "permission_id": f"{username}|{module_code}",
            "username": username,
            "module_code": module_code,
            "module_name_zh": clean_text(r.get("module_name_zh")),
            "module_name_en": clean_text(r.get("module_name_en")),
            "can_view": truthy(r.get("can_view")),
            "can_create": truthy(r.get("can_create")),
            "can_edit": truthy(r.get("can_edit")),
            "can_delete": truthy(r.get("can_delete")),
            "can_import": truthy(r.get("can_import")),
            "can_export": truthy(r.get("can_export")),
            "can_backup": truthy(r.get("can_backup")),
            "can_restore": truthy(r.get("can_restore")),
            "can_manage": truthy(r.get("can_manage")),
            "updated_at": dt(r.get("updated_at")),
        }
        upsert(conn, "account_permissions", "permission_id", row)
        p_count += 1
    return count, p_count


def to_isoish(ts: str, date_part: str = "") -> str:
    ts = clean_text(ts)
    if ts:
        return ts.replace(" ", "T", 1)
    if date_part:
        return f"{date_part}T00:00:00"
    return now_iso()


def import_time_records(conn, ps_root: Path) -> int:
    rows = []
    seen = set()
    for module_key in ["01_time_records", "02_history"]:
        for r in load_table(ps_root, module_key, "time_records"):
            rid = clean_text(r.get("id")) or clean_text(r.get("record_key"))
            if not rid:
                continue
            if rid in seen:
                continue
            seen.add(rid)
            rows.append(r)

    count = 0
    for r in rows:
        legacy_status = clean_text(r.get("status"))
        status = STATUS_MAP.get(legacy_status, "completed" if clean_text(r.get("end_timestamp")) else "active")
        is_deleted = truthy(r.get("is_deleted"), False) or bool(clean_text(r.get("deleted_at")))
        if is_deleted:
            status = "deleted"
        work_hours = safe_float(r.get("work_hours"))
        work_minutes = work_hours * 60.0 if work_hours else safe_float(r.get("work_minutes"))
        start_ts = to_isoish(r.get("start_timestamp"), clean_text(r.get("start_date")))
        end_ts_raw = clean_text(r.get("end_timestamp"))
        process_name = clean_text(r.get("process_name"), "未分類")
        row = {
            "record_id": clean_text(r.get("record_key")) or f"legacy_{clean_text(r.get('id'))}",
            "legacy_id": clean_text(r.get("id")),
            "record_key": clean_text(r.get("record_key")),
            "work_date": clean_text(r.get("start_date")) or start_ts[:10],
            "employee_id": clean_text(r.get("employee_id")),
            "employee_name": clean_text(r.get("employee_name")),
            "work_order_no": clean_text(r.get("work_order")) or "未指定",
            "part_no": clean_text(r.get("part_no")),
            "type_name": clean_text(r.get("type_name")),
            "assembly_location": clean_text(r.get("assembly_location")),
            "process_code": process_code(process_name),
            "process_name": process_name,
            "start_action": clean_text(r.get("start_action")),
            "end_action": clean_text(r.get("end_action")),
            "start_time": start_ts,
            "end_time": to_isoish(end_ts_raw) if end_ts_raw else None,
            "start_date": clean_text(r.get("start_date")),
            "end_date": clean_text(r.get("end_date")),
            "status": status,
            "group_key": clean_text(r.get("group_key")) or f"{clean_text(r.get('employee_id'))}|{process_name}|{clean_text(r.get('start_date'))}",
            "raw_minutes": work_minutes,
            "work_minutes": work_minutes,
            "average_minutes": work_minutes,
            "work_hours_hms": clean_text(r.get("work_hours_hms")),
            "pause_reason": legacy_status if legacy_status == "暫停" else "",
            "remark": clean_text(r.get("remark")),
            "source": clean_text(r.get("source")) or "legacy_migration",
            "created_by": "legacy_migration",
            "created_at": to_isoish(r.get("created_at")),
            "updated_by": "legacy_migration",
            "updated_at": to_isoish(r.get("updated_at")),
            "deleted_at": to_isoish(r.get("deleted_at")) if clean_text(r.get("deleted_at")) else None,
            "deleted_by": clean_text(r.get("deleted_by")),
            "delete_reason": clean_text(r.get("delete_reason")),
            "version": 1,
        }
        upsert(conn, "time_records", "record_id", row)
        if row["deleted_at"]:
            upsert(conn, "delete_events", "delete_event_id", {
                "delete_event_id": f"time_records|{row['record_id']}",
                "target_table": "time_records",
                "target_id": row["record_id"],
                "deleted_by": row["deleted_by"] or "legacy_migration",
                "deleted_at": row["deleted_at"],
                "reason": row["delete_reason"] or "legacy imported deleted record",
                "before_snapshot": json_dumps(r),
            })
        count += 1
    return count


def import_legacy_logs(conn, ps_root: Path) -> int:
    count = 0
    p = ps_root / "modules" / "06_log_query" / "records.jsonl"
    if p.exists():
        for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                r = json.loads(raw)
            except Exception:
                continue
            log_id = clean_text(r.get("authority_event_id")) or sql_id("legacy_log", raw)
            row = {
                "log_id": log_id,
                "timestamp": to_isoish(r.get("log_time") or r.get("authority_written_at")),
                "actor": clean_text(r.get("user_name")),
                "module": clean_text(r.get("authority_module_key"), "legacy_log"),
                "action": clean_text(r.get("action_type"), "legacy_log"),
                "target_type": clean_text(r.get("target_table")),
                "target_id": clean_text(r.get("target_id")),
                "before_value": None,
                "after_value": json_dumps(r),
                "result": clean_text(r.get("level"), "INFO"),
                "error_message": clean_text(r.get("message")),
                "request_id": None,
                "app_version": "legacy_v260602",
            }
            upsert(conn, "operation_logs", "log_id", row)
            count += 1
    return count


def import_system_settings(conn, ps_root: Path) -> int:
    count = 0
    for source in [
        ps_root / "config" / "system_settings.json",
        ps_root / "system" / "security_settings.json",
        ps_root / "modules" / "13_system_settings" / "records.json",
    ]:
        if not source.exists():
            continue
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = "legacy." + source.relative_to(ps_root).as_posix().replace("/", ".")
        upsert(conn, "system_settings", "setting_key", {
            "setting_key": key,
            "setting_value": json_dumps(data),
            "updated_at": now_iso(),
            "updated_by": "legacy_migration",
        })
        count += 1
    return count


def migrate(legacy_path: str, dry_run: bool = False) -> dict[str, int]:
    root, temp = resolve_legacy_root(legacy_path)
    try:
        ps_root = permanent_store_root(root)
        init_db()
        with transaction() as conn:
            summary = {
                "employees": import_employees(conn, ps_root),
                "work_orders": import_work_orders(conn, ps_root),
                "time_records": import_time_records(conn, ps_root),
                "users": 0,
                "account_permissions": 0,
                "processes": 0,
                "process_categories": 0,
                "rest_periods": 0,
                "legacy_logs": import_legacy_logs(conn, ps_root),
                "system_settings": import_system_settings(conn, ps_root),
            }
            u, ap = import_users_and_permissions(conn, ps_root)
            p, pc, rp = import_processes_and_rest(conn, ps_root)
            summary.update({"users": u, "account_permissions": ap, "processes": p, "process_categories": pc, "rest_periods": rp})
            execute(conn, "INSERT INTO operation_logs(log_id, timestamp, actor, module, action, target_type, target_id, before_value, after_value, result, error_message, request_id, app_version) VALUES(:log_id,:timestamp,:actor,:module,:action,:target_type,:target_id,:before_value,:after_value,:result,:error_message,:request_id,:app_version)", {
                "log_id": f"migration_{now_iso()}",
                "timestamp": now_iso(),
                "actor": "legacy_migration",
                "module": "migration",
                "action": "import_legacy_authority",
                "target_type": "database",
                "target_id": "neon",
                "before_value": None,
                "after_value": json_dumps(summary),
                "result": "success",
                "error_message": None,
                "request_id": None,
                "app_version": "clean_v2",
            })
            if dry_run:
                raise RuntimeError("DRY_RUN_ROLLBACK")
        return summary
    except RuntimeError as exc:
        if str(exc) == "DRY_RUN_ROLLBACK":
            return {"dry_run": 1}
        raise
    finally:
        if temp is not None:
            temp.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy SPT permanent_store data into the clean Neon/PostgreSQL schema.")
    parser.add_argument("legacy_path", help="舊專案根目錄或舊專案 ZIP，例如 SPT-time-tracking-system-main.zip")
    parser.add_argument("--dry-run", action="store_true", help="建立 schema 後測試讀取，但交易會 rollback。")
    args = parser.parse_args()
    summary = migrate(args.legacy_path, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
