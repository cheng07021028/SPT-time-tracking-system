from __future__ import annotations

from .db import backend, execute, fetch_all


# Clean V2 schema.
# PostgreSQL / Neon is the production single source of truth.
# SQLite remains available only for local demo and automated tests.
SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'operator',
        employee_id TEXT,
        email TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        force_password_change INTEGER NOT NULL DEFAULT 0,
        password_hint TEXT,
        last_login_at TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS employees (
        employee_id TEXT PRIMARY KEY,
        employee_name TEXT NOT NULL,
        department TEXT,
        team TEXT,
        role TEXT,
        title TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        is_in_factory INTEGER NOT NULL DEFAULT 1,
        is_today_attendance INTEGER NOT NULL DEFAULT 1,
        permission_group TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT,
        deleted_by TEXT,
        version INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_orders (
        work_order_no TEXT PRIMARY KEY,
        model TEXT,
        product_name TEXT,
        part_no TEXT,
        type_name TEXT,
        assembly_location TEXT,
        customer TEXT,
        note TEXT,
        planned_qty REAL DEFAULT 0,
        completed_qty REAL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open',
        process_flow TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT,
        deleted_by TEXT,
        version INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processes (
        process_code TEXT PRIMARY KEY,
        process_name TEXT NOT NULL,
        process_category TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        allow_parallel INTEGER NOT NULL DEFAULT 1,
        allow_group_average INTEGER NOT NULL DEFAULT 1,
        standard_minutes REAL DEFAULT 0,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rest_periods (
        rest_period_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS time_records (
        record_id TEXT PRIMARY KEY,
        legacy_id TEXT,
        record_key TEXT,
        work_date TEXT NOT NULL,
        employee_id TEXT NOT NULL,
        employee_name TEXT NOT NULL,
        work_order_no TEXT NOT NULL,
        part_no TEXT,
        type_name TEXT,
        assembly_location TEXT,
        process_code TEXT NOT NULL,
        process_name TEXT NOT NULL,
        start_action TEXT,
        end_action TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT,
        start_date TEXT,
        end_date TEXT,
        status TEXT NOT NULL,
        group_key TEXT NOT NULL,
        raw_minutes REAL DEFAULT 0,
        work_minutes REAL DEFAULT 0,
        average_minutes REAL DEFAULT 0,
        work_hours_hms TEXT,
        pause_reason TEXT,
        remark TEXT,
        source TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL,
        deleted_at TEXT,
        deleted_by TEXT,
        delete_reason TEXT,
        version INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operation_logs (
        log_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        actor TEXT,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        before_value TEXT,
        after_value TEXT,
        result TEXT NOT NULL,
        error_message TEXT,
        request_id TEXT,
        app_version TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS login_events (
        login_event_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        username TEXT,
        display_name TEXT,
        role TEXT,
        login_result TEXT NOT NULL,
        session_id TEXT,
        error_message TEXT,
        logout_time TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS delete_events (
        delete_event_id TEXT PRIMARY KEY,
        target_table TEXT NOT NULL,
        target_id TEXT NOT NULL,
        deleted_by TEXT NOT NULL,
        deleted_at TEXT NOT NULL,
        reason TEXT,
        before_snapshot TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_permissions (
        permission_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        module_code TEXT NOT NULL,
        module_name_zh TEXT,
        module_name_en TEXT,
        can_view INTEGER NOT NULL DEFAULT 0,
        can_create INTEGER NOT NULL DEFAULT 0,
        can_edit INTEGER NOT NULL DEFAULT 0,
        can_delete INTEGER NOT NULL DEFAULT 0,
        can_import INTEGER NOT NULL DEFAULT 0,
        can_export INTEGER NOT NULL DEFAULT 0,
        can_backup INTEGER NOT NULL DEFAULT 0,
        can_restore INTEGER NOT NULL DEFAULT 0,
        can_manage INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        idempotency_key TEXT PRIMARY KEY,
        module TEXT NOT NULL,
        action TEXT NOT NULL,
        target_id TEXT,
        created_at TEXT NOT NULL,
        result_ref TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_jobs (
        sync_job_id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        payload TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS module_authority (
        authority_id TEXT PRIMARY KEY,
        module_key TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'record',
        record_key TEXT,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT,
        deleted_at TEXT
    )
    """,
]

# Existing Neon databases created by old builds may already contain some tables,
# so CREATE TABLE IF NOT EXISTS will not add new columns.  Additive migrations are
# intentionally kept here so app startup can safely upgrade old schema versions
# before seed data or indexes run.  Definitions are nullable/defaulted to avoid
# breaking tables that already contain data.
MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "username": "TEXT",
        "display_name": "TEXT",
        "password_hash": "TEXT",
        "role": "TEXT DEFAULT 'operator'",
        "employee_id": "TEXT",
        "email": "TEXT",
        "active": "INTEGER DEFAULT 1",
        "force_password_change": "INTEGER DEFAULT 0",
        "password_hint": "TEXT",
        "last_login_at": "TEXT",
        "note": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "deleted_at": "TEXT",
    },
    "employees": {
        "employee_id": "TEXT",
        "employee_name": "TEXT",
        "department": "TEXT",
        "team": "TEXT",
        "role": "TEXT",
        "title": "TEXT",
        "active": "INTEGER DEFAULT 1",
        "is_in_factory": "INTEGER DEFAULT 1",
        "is_today_attendance": "INTEGER DEFAULT 1",
        "permission_group": "TEXT",
        "note": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "deleted_at": "TEXT",
        "deleted_by": "TEXT",
        "version": "INTEGER DEFAULT 1",
    },
    "work_orders": {
        "work_order_no": "TEXT",
        "model": "TEXT",
        "product_name": "TEXT",
        "part_no": "TEXT",
        "type_name": "TEXT",
        "assembly_location": "TEXT",
        "customer": "TEXT",
        "note": "TEXT",
        "planned_qty": "REAL DEFAULT 0",
        "completed_qty": "REAL DEFAULT 0",
        "status": "TEXT DEFAULT 'open'",
        "process_flow": "TEXT",
        "active": "INTEGER DEFAULT 1",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "deleted_at": "TEXT",
        "deleted_by": "TEXT",
        "version": "INTEGER DEFAULT 1",
    },
    "processes": {
        "process_code": "TEXT",
        "process_name": "TEXT",
        "process_category": "TEXT",
        "sort_order": "INTEGER DEFAULT 0",
        "active": "INTEGER DEFAULT 1",
        "allow_parallel": "INTEGER DEFAULT 1",
        "allow_group_average": "INTEGER DEFAULT 1",
        "standard_minutes": "REAL DEFAULT 0",
        "note": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
    "rest_periods": {
        "rest_period_id": "TEXT",
        "name": "TEXT",
        "start_time": "TEXT",
        "end_time": "TEXT",
        "active": "INTEGER DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
    "system_settings": {
        "setting_key": "TEXT",
        "setting_value": "TEXT",
        "updated_at": "TEXT",
        "updated_by": "TEXT",
    },
    "time_records": {
        "record_id": "TEXT",
        "legacy_id": "TEXT",
        "record_key": "TEXT",
        "work_date": "TEXT",
        "employee_id": "TEXT",
        "employee_name": "TEXT",
        "work_order_no": "TEXT",
        "part_no": "TEXT",
        "type_name": "TEXT",
        "assembly_location": "TEXT",
        "process_code": "TEXT",
        "process_name": "TEXT",
        "start_action": "TEXT",
        "end_action": "TEXT",
        "start_time": "TEXT",
        "end_time": "TEXT",
        "start_date": "TEXT",
        "end_date": "TEXT",
        "status": "TEXT",
        "group_key": "TEXT",
        "raw_minutes": "REAL DEFAULT 0",
        "work_minutes": "REAL DEFAULT 0",
        "average_minutes": "REAL DEFAULT 0",
        "work_hours_hms": "TEXT",
        "pause_reason": "TEXT",
        "remark": "TEXT",
        "source": "TEXT",
        "created_by": "TEXT",
        "created_at": "TEXT",
        "updated_by": "TEXT",
        "updated_at": "TEXT",
        "deleted_at": "TEXT",
        "deleted_by": "TEXT",
        "delete_reason": "TEXT",
        "version": "INTEGER DEFAULT 1",
    },
    "operation_logs": {
        "log_id": "TEXT",
        "timestamp": "TEXT",
        "actor": "TEXT",
        "module": "TEXT",
        "action": "TEXT",
        "target_type": "TEXT",
        "target_id": "TEXT",
        "before_value": "TEXT",
        "after_value": "TEXT",
        "result": "TEXT",
        "error_message": "TEXT",
        "request_id": "TEXT",
        "app_version": "TEXT",
    },
    "login_events": {
        "login_event_id": "TEXT",
        "timestamp": "TEXT",
        "username": "TEXT",
        "display_name": "TEXT",
        "role": "TEXT",
        "login_result": "TEXT",
        "session_id": "TEXT",
        "error_message": "TEXT",
        "logout_time": "TEXT",
    },
    "delete_events": {
        "delete_event_id": "TEXT",
        "target_table": "TEXT",
        "target_id": "TEXT",
        "deleted_by": "TEXT",
        "deleted_at": "TEXT",
        "reason": "TEXT",
        "before_snapshot": "TEXT",
    },
    "account_permissions": {
        "permission_id": "TEXT",
        "username": "TEXT",
        "module_code": "TEXT",
        "module_name_zh": "TEXT",
        "module_name_en": "TEXT",
        "can_view": "INTEGER DEFAULT 0",
        "can_create": "INTEGER DEFAULT 0",
        "can_edit": "INTEGER DEFAULT 0",
        "can_delete": "INTEGER DEFAULT 0",
        "can_import": "INTEGER DEFAULT 0",
        "can_export": "INTEGER DEFAULT 0",
        "can_backup": "INTEGER DEFAULT 0",
        "can_restore": "INTEGER DEFAULT 0",
        "can_manage": "INTEGER DEFAULT 0",
        "updated_at": "TEXT",
    },
    "idempotency_keys": {
        "idempotency_key": "TEXT",
        "module": "TEXT",
        "action": "TEXT",
        "target_id": "TEXT",
        "created_at": "TEXT",
        "result_ref": "TEXT",
    },
    "sync_jobs": {
        "sync_job_id": "TEXT",
        "job_type": "TEXT",
        "payload": "TEXT",
        "status": "TEXT DEFAULT 'pending'",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "error_message": "TEXT",
    },
    "module_authority": {
        "authority_id": "TEXT",
        "module_key": "TEXT",
        "kind": "TEXT DEFAULT 'record'",
        "record_key": "TEXT",
        "payload": "TEXT",
        "updated_at": "TEXT",
        "updated_by": "TEXT",
        "deleted_at": "TEXT",
    },
}

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
    "CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(active)",
    "CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status)",
    "CREATE INDEX IF NOT EXISTS idx_processes_category ON processes(process_category)",
    "CREATE INDEX IF NOT EXISTS idx_time_records_work_date ON time_records(work_date)",
    "CREATE INDEX IF NOT EXISTS idx_time_records_employee_status ON time_records(employee_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_time_records_work_order ON time_records(work_order_no)",
    "CREATE INDEX IF NOT EXISTS idx_time_records_process ON time_records(process_code)",
    "CREATE INDEX IF NOT EXISTS idx_time_records_group_key ON time_records(group_key)",
    "CREATE INDEX IF NOT EXISTS idx_time_records_deleted_at ON time_records(deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON operation_logs(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_logs_module ON operation_logs(module)",
    "CREATE INDEX IF NOT EXISTS idx_login_events_timestamp ON login_events(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_delete_events_target ON delete_events(target_table, target_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_permissions_user ON account_permissions(username)",
    "CREATE INDEX IF NOT EXISTS idx_module_authority_module_kind ON module_authority(module_key, kind)",
    "CREATE INDEX IF NOT EXISTS idx_module_authority_record_key ON module_authority(record_key)",
]


def _sqlite_existing_columns(conn, table_name: str) -> set[str]:
    rows = fetch_all(conn, f"PRAGMA table_info({table_name})")
    return {str(row.get("name")) for row in rows}


def _postgres_existing_columns(conn, table_name: str) -> set[str]:
    rows = fetch_all(
        conn,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
        """,
        {"table_name": table_name},
    )
    return {str(row.get("column_name")) for row in rows}


def _existing_columns(conn, table_name: str) -> set[str]:
    if backend() == "postgres":
        return _postgres_existing_columns(conn, table_name)
    return _sqlite_existing_columns(conn, table_name)


def _apply_additive_migrations(conn) -> None:
    for table_name, columns in MIGRATION_COLUMNS.items():
        existing = _existing_columns(conn, table_name)
        for column_name, column_type in columns.items():
            if column_name in existing:
                continue
            if backend() == "postgres":
                execute(conn, f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
            else:
                execute(conn, f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def create_schema(conn) -> None:
    for sql in SCHEMA_SQL:
        execute(conn, sql)
    _apply_additive_migrations(conn)
    for sql in INDEX_SQL:
        execute(conn, sql)
