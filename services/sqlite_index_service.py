# -*- coding: utf-8 -*-
"""V172 SQLite performance index service.

Purpose
-------
Install idempotent SQLite indexes for high-frequency read paths without changing
business logic, UI rendering, Streamlit widgets, or time-record write semantics.

Safety rules
------------
* Only CREATE INDEX IF NOT EXISTS / PRAGMA optimize.
* Never DROP, DELETE, UPDATE, INSERT business rows, or re-number IDs.
* Skip missing tables/columns to remain compatible with older deployments.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class IndexSpec:
    name: str
    table: str
    columns: tuple[str, ...]
    reason: str


INDEX_SPECS: tuple[IndexSpec, ...] = (
    # 01 / 02 core time-record paths
    IndexSpec("idx_v172_time_records_record_key", "time_records", ("record_key",), "record_key exact lookup / repair merge"),
    IndexSpec("idx_v172_time_records_emp_date_status", "time_records", ("employee_id", "start_date", "status"), "01 active/today employee records"),
    IndexSpec("idx_v172_time_records_emp_status_start", "time_records", ("employee_id", "status", "start_timestamp"), "active work by employee and status"),
    IndexSpec("idx_v172_time_records_date_status", "time_records", ("start_date", "status"), "daily summaries and open/closed counts"),
    IndexSpec("idx_v172_time_records_work_process", "time_records", ("work_order", "process_name"), "work order + process analysis"),
    IndexSpec("idx_v172_time_records_work_date", "time_records", ("work_order", "start_date"), "history filters by work order/date"),
    IndexSpec("idx_v172_time_records_process_date", "time_records", ("process_name", "start_date"), "process filters and analysis"),
    IndexSpec("idx_v172_time_records_group_key", "time_records", ("group_key",), "group-work averaging lookup"),
    IndexSpec("idx_v172_time_records_end_date", "time_records", ("end_date",), "closed history filters"),
    IndexSpec("idx_v172_time_records_updated", "time_records", ("updated_at",), "recent sync/repair checks"),

    # 03 / 04 master data option lists
    IndexSpec("idx_v172_work_orders_active_order", "work_orders", ("is_active", "work_order"), "01 work-order option list"),
    IndexSpec("idx_v172_work_orders_part", "work_orders", ("part_no",), "P/N filter"),
    IndexSpec("idx_v172_work_orders_type", "work_orders", ("type_name",), "model/type filter"),
    IndexSpec("idx_v172_work_orders_assembly", "work_orders", ("assembly_location",), "assembly-location filter"),
    IndexSpec("idx_v172_employees_active_emp", "employees", ("is_active", "employee_id"), "employee option list"),
    IndexSpec("idx_v172_employees_name", "employees", ("employee_name",), "employee name search"),
    IndexSpec("idx_v172_employees_dept", "employees", ("department",), "department filter"),
    IndexSpec("idx_v172_employees_attendance", "employees", ("is_today_attendance", "is_active", "employee_id"), "07/08 attendance and no-record checks"),
    IndexSpec("idx_v172_process_options_active_sort", "process_options", ("is_active", "sort_order", "process_name"), "process dropdown list"),

    # 06 LOG and login logs
    IndexSpec("idx_v172_system_logs_time", "system_logs", ("log_time",), "06 LOG date range"),
    IndexSpec("idx_v172_system_logs_user_time", "system_logs", ("user_name", "log_time"), "06 LOG user/date range"),
    IndexSpec("idx_v172_system_logs_action_time", "system_logs", ("action_type", "log_time"), "06 LOG action/date range"),
    IndexSpec("idx_v172_system_logs_target", "system_logs", ("target_table", "target_id"), "audit target lookup"),
    IndexSpec("idx_v172_system_logs_level_time", "system_logs", ("level", "log_time"), "error/warning filters"),
    IndexSpec("idx_v172_auth_login_logs_user_time", "auth_login_logs", ("username", "event_time"), "11 login record user/date"),
    IndexSpec("idx_v172_auth_login_logs_type_time", "auth_login_logs", ("event_type", "event_time"), "11 login event filters"),
    IndexSpec("idx_v172_security_login_logs_user_time", "security_login_logs", ("username", "login_time"), "security login user/date"),
    IndexSpec("idx_v172_security_login_logs_event_time", "security_login_logs", ("event_type", "login_time"), "security login event filters"),
    IndexSpec("idx_v172_login_logs_user_time", "login_logs", ("username", "login_time"), "legacy login record user/date"),

    # permissions / settings
    IndexSpec("idx_v172_auth_users_role_active", "auth_users", ("role_code", "is_active"), "login and permission filtering"),
    IndexSpec("idx_v172_auth_perm_module_user", "auth_account_permissions", ("module_code", "username"), "module permission checks"),
    IndexSpec("idx_v172_security_roles_code", "security_roles", ("role_code",), "role lookup"),
    IndexSpec("idx_v172_security_user_roles_user", "security_user_roles", ("username", "role_code"), "role lookup by user"),
    IndexSpec("idx_v172_security_module_perm_module", "security_module_permissions", ("module_code", "role_code"), "permission lookup by module"),
    IndexSpec("idx_v172_table_column_page_table", "table_column_settings", ("page_key", "table_key", "sort_order"), "column settings load"),
    IndexSpec("idx_v172_table_sort_page_table", "table_sort_settings", ("page_key", "table_key"), "sort settings load"),

    # event journal / outbox if V152 exists
    IndexSpec("idx_v172_tr_events_record_time", "time_record_events", ("record_key", "event_time"), "event replay by record"),
    IndexSpec("idx_v172_tr_events_emp_type_time", "time_record_events", ("employee_id", "event_type", "event_time"), "event audit by employee/action"),
    IndexSpec("idx_v172_tr_events_work_time", "time_record_events", ("work_order", "event_time"), "event audit by work order"),
    IndexSpec("idx_v172_tr_outbox_status_updated", "time_record_outbox", ("status", "updated_at"), "background sync queue"),

    # 13 system settings extra tables if present
    IndexSpec("idx_v172_app_settings_key", "app_settings", ("setting_key",), "app settings lookup"),
    IndexSpec("idx_v172_rest_periods_active_sort", "rest_periods", ("is_active", "sort_order"), "rest period calculation list"),
    IndexSpec("idx_v172_process_model_active_sort", "process_model_options", ("is_active", "sort_order"), "system setting model options"),
    IndexSpec("idx_v172_process_category_active_sort", "process_category_options", ("is_active", "sort_order"), "system setting category options"),
    IndexSpec("idx_v172_process_categories_active_sort", "process_categories", ("is_active", "sort_order"), "system setting category list"),
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return {str(row[1]) for row in rows}
    except Exception:
        return set()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? LIMIT 1",
            (index_name,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _create_index_sql(spec: IndexSpec) -> str:
    cols = ", ".join(_quote_ident(c) for c in spec.columns)
    return f"CREATE INDEX IF NOT EXISTS {_quote_ident(spec.name)} ON {_quote_ident(spec.table)} ({cols})"


def apply_sqlite_performance_indexes(
    conn_or_path: sqlite3.Connection | str | Path,
    *,
    run_optimize: bool = True,
) -> dict[str, Any]:
    """Create V172 indexes safely and idempotently.

    Accepts either an open sqlite3 connection or a DB path. When a connection is
    supplied, the caller owns it; this function does not close it.
    """
    started = time.perf_counter()
    own_conn = False
    if isinstance(conn_or_path, sqlite3.Connection):
        conn = conn_or_path
    else:
        path = Path(conn_or_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30)
        own_conn = True
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        for spec in INDEX_SPECS:
            item = asdict(spec)
            try:
                if not _table_exists(conn, spec.table):
                    skipped.append({**item, "reason_skipped": "table_missing"})
                    continue
                cols = _table_columns(conn, spec.table)
                missing = [c for c in spec.columns if c not in cols]
                if missing:
                    skipped.append({**item, "reason_skipped": "column_missing", "missing_columns": missing})
                    continue
                existed_before = _index_exists(conn, spec.name)
                conn.execute(_create_index_sql(spec))
                if not existed_before:
                    created.append(item)
                else:
                    skipped.append({**item, "reason_skipped": "already_exists"})
            except Exception as exc:
                errors.append({**item, "error": str(exc)[:500]})
        try:
            conn.commit()
        except Exception:
            pass
        if run_optimize:
            try:
                conn.execute("PRAGMA optimize")
            except Exception:
                pass
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "ok": not errors,
        "version": "V172",
        "elapsed_ms": elapsed_ms,
        "created_count": len(created),
        "already_or_skipped_count": len(skipped),
        "error_count": len(errors),
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


def collect_sqlite_index_status(conn_or_path: sqlite3.Connection | str | Path) -> dict[str, Any]:
    """Return V172 index installation status without changing data."""
    own_conn = False
    if isinstance(conn_or_path, sqlite3.Connection):
        conn = conn_or_path
    else:
        conn = sqlite3.connect(Path(conn_or_path), timeout=30)
        own_conn = True
    installed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    incompatible: list[dict[str, Any]] = []
    try:
        for spec in INDEX_SPECS:
            item = asdict(spec)
            if not _table_exists(conn, spec.table):
                incompatible.append({**item, "reason": "table_missing"})
                continue
            cols = _table_columns(conn, spec.table)
            missing_cols = [c for c in spec.columns if c not in cols]
            if missing_cols:
                incompatible.append({**item, "reason": "column_missing", "missing_columns": missing_cols})
                continue
            if _index_exists(conn, spec.name):
                installed.append(item)
            else:
                missing.append(item)
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass
    return {
        "ok": not missing,
        "version": "V172",
        "spec_count": len(INDEX_SPECS),
        "installed_count": len(installed),
        "missing_count": len(missing),
        "incompatible_count": len(incompatible),
        "installed": installed,
        "missing": missing,
        "incompatible": incompatible,
    }
