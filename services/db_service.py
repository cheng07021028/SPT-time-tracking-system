# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.39 - DB Service with Page Switch Speed Guard

重點：
1. 自動建立 SQLite schema，包含工時主資料、UI設定、權限管理資料表。
2. Streamlit Cloud 更新/重啟後，如果 SQLite 不存在或主資料為 0，會自動從 GitHub data/permanent_store/persistent_state 還原。
3. 寫入資料後自動刷新永久 JSON；若已設定 GitHub Token，會嘗試同步 latest JSON 到 GitHub。
4. 嚴格避免「空資料庫」覆蓋 GitHub 上既有永久資料。
5. 登入/權限/安全紀錄類 SQL 不觸發 GitHub 還原與雲端同步，避免登入頁緩慢。
"""
from __future__ import annotations

import json
import os
import sqlite3
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "data" / "permanent_store" / "database"
DB_PATH = DB_DIR / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state"
PENDING_BACKUP_MARKER = STATE_DIR / ".pending_backup.json"

_SCHEMA_READY = False
_RESTORE_CHECKED = False
_LAST_CLOUD_SYNC_TS = 0.0
# GitHub API upload is useful but slow; keep it throttled heavily. Manual backup remains available on page 09.
_CLOUD_SYNC_INTERVAL_SEC = 180.0

# Lightweight in-process SELECT cache. Streamlit reruns the script frequently; this prevents
# repeated SQL reads while switching tabs/pages. Cache is cleared after any write.
_QUERY_CACHE: dict[tuple[str, tuple[Any, ...]], tuple[float, pd.DataFrame]] = {}
_QUERY_CACHE_TTL_SEC = 10.0
_QUERY_CACHE_MAX_ITEMS = 120


AUTH_SECURITY_SQL_MARKERS = (
    " auth_", " security_", "auth_users", "auth_account_permissions", "auth_login_logs",
    "auth_security_settings", "security_users", "security_roles", "security_user_roles",
    "security_module_permissions", "security_settings", "security_login_logs",
)

BUSINESS_SQL_MARKERS = (
    "work_orders", "employees", "time_records", "rest_periods",
    "table_column_settings", "table_sort_settings", "system_settings", "process_options",
)


def _normalise_sql(sql: str) -> str:
    return " " + " ".join(str(sql or "").lower().replace('\n', ' ').split()) + " "


def _is_auth_or_security_sql(sql: str) -> bool:
    low = _normalise_sql(sql)
    return any(marker in low for marker in AUTH_SECURITY_SQL_MARKERS)


def _is_business_sql(sql: str) -> bool:
    low = _normalise_sql(sql)
    return any(marker in low for marker in BUSINESS_SQL_MARKERS)


def _should_run_data_guard(sql: str | None = None) -> bool:
    """Return False for login / permission / security SQL.

    登入頁慢的主因是每次帳號驗證、登入紀錄、權限表查詢都觸發
    GitHub permanent JSON 檢查與同步。安全資料表不需要啟動資料還原，
    因此直接跳過。
    """
    if not sql:
        return True
    if _is_auth_or_security_sql(sql) and not _is_business_sql(sql):
        return False
    return True


def _should_after_write_sync(sql: str | None = None) -> bool:
    """Return True for writes that should mark business data as changed.

    V1.90: normal writes no longer export the whole permanent JSON or upload GitHub
    immediately.  They only set a tiny pending-backup marker, so deleting one row
    does not spend 10-20 seconds doing cloud persistence work.
    """
    if not sql:
        return True
    low = _normalise_sql(sql)
    if low.startswith((" create ", " pragma ", " select ", " with ")):
        return False
    # Logs are high-frequency audit writes; they must never trigger permanent export.
    if " system_logs " in low or " auth_login_logs " in low or " security_login_logs " in low:
        return False
    if _is_auth_or_security_sql(sql) and not _is_business_sql(sql):
        return False
    return True


def _now() -> str:
    return now_text()


def _open_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # Connection-level pragmas: reduce locking and speed up read-heavy Streamlit reruns.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-20000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn


def _is_select_sql(sql: str | None) -> bool:
    low = _normalise_sql(sql or "")
    return low.startswith(" select ") or low.startswith(" with ")


def _query_cache_key(sql: str, params: Iterable[Any] | None) -> tuple[str, tuple[Any, ...]]:
    return (" ".join(str(sql or "").split()), tuple(params or ()))


def clear_query_cache() -> None:
    """Clear read cache after writes or manual refresh."""
    try:
        _QUERY_CACHE.clear()
    except Exception:
        pass


# ===== V3.53 schema migration guard =====
def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(str(r[1]) == column_name for r in rows)
    except Exception:
        return False


def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    """Add a missing column to an existing SQLite table.

    SQLite CREATE TABLE IF NOT EXISTS does not upgrade older tables.  Several
    Streamlit Cloud deployments keep the old app.db across code updates, so a
    page can fail with pandas.errors.DatabaseError when code queries new columns
    such as employees.is_active / is_in_factory.  This migration is intentionally
    small and idempotent; it never drops tables and never rewrites user data.
    """
    try:
        if not _column_exists(conn, table_name, column_name):
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
    except Exception:
        # Never block app startup.  The actual query will still surface a clear
        # error if the DB file is not writable or the table is corrupted.
        pass


def _migrate_existing_schema(conn: sqlite3.Connection) -> None:
    """Upgrade existing DB tables that were created by older app versions."""
    migrations = {
        "work_orders": [
            ("work_order", "TEXT"),
            ("part_no", "TEXT"),
            ("type_name", "TEXT"),
            ("assembly_location", "TEXT"),
            ("customer", "TEXT"),
            ("note", "TEXT"),
            ("is_active", "INTEGER DEFAULT 1"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "employees": [
            ("employee_id", "TEXT"),
            ("employee_name", "TEXT"),
            ("department", "TEXT"),
            ("title", "TEXT"),
            ("is_active", "INTEGER DEFAULT 1"),
            ("is_in_factory", "INTEGER DEFAULT 1"),
            ("is_today_attendance", "INTEGER DEFAULT 1"),
            ("note", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "time_records": [
            ("record_key", "TEXT"),
            ("status", "TEXT"),
            ("work_order", "TEXT"),
            ("part_no", "TEXT"),
            ("type_name", "TEXT"),
            ("process_name", "TEXT"),
            ("employee_id", "TEXT"),
            ("employee_name", "TEXT"),
            ("start_action", "TEXT"),
            ("start_timestamp", "TEXT"),
            ("end_action", "TEXT"),
            ("end_timestamp", "TEXT"),
            ("remark", "TEXT"),
            ("start_date", "TEXT"),
            ("start_time", "TEXT"),
            ("end_date", "TEXT"),
            ("end_time", "TEXT"),
            ("work_hours", "REAL DEFAULT 0"),
            ("assembly_location", "TEXT"),
            ("group_key", "TEXT"),
            ("is_group_work", "INTEGER DEFAULT 0"),
            ("source", "TEXT DEFAULT 'streamlit'"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "process_options": [
            ("process_name", "TEXT"),
            ("is_active", "INTEGER DEFAULT 1"),
            ("sort_order", "INTEGER DEFAULT 0"),
            ("note", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "rest_periods": [
            ("name", "TEXT"),
            ("start_time", "TEXT"),
            ("end_time", "TEXT"),
            ("is_active", "INTEGER DEFAULT 1"),
            ("sort_order", "INTEGER DEFAULT 0"),
        ],
        "system_settings": [
            ("setting_key", "TEXT"),
            ("setting_value", "TEXT"),
            ("note", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "table_column_settings": [
            ("page_key", "TEXT"),
            ("table_key", "TEXT"),
            ("column_key", "TEXT"),
            ("column_width", "INTEGER"),
            ("sort_order", "INTEGER"),
            ("updated_at", "TEXT"),
        ],
        "table_sort_settings": [
            ("page_key", "TEXT"),
            ("table_key", "TEXT"),
            ("sort_column", "TEXT"),
            ("sort_ascending", "INTEGER DEFAULT 1"),
            ("updated_at", "TEXT"),
        ],
        "auth_users": [
            ("username", "TEXT"),
            ("password_hash", "TEXT"),
            ("password_hint", "TEXT"),
            ("employee_id", "TEXT"),
            ("display_name", "TEXT"),
            ("email", "TEXT"),
            ("role_code", "TEXT DEFAULT 'operator'"),
            ("is_active", "INTEGER DEFAULT 1"),
            ("force_password_change", "INTEGER DEFAULT 0"),
            ("last_login_at", "TEXT"),
            ("note", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "auth_account_permissions": [
            ("username", "TEXT"),
            ("module_code", "TEXT"),
            ("module_name_zh", "TEXT"),
            ("module_name_en", "TEXT"),
            ("can_view", "INTEGER DEFAULT 0"),
            ("can_create", "INTEGER DEFAULT 0"),
            ("can_edit", "INTEGER DEFAULT 0"),
            ("can_delete", "INTEGER DEFAULT 0"),
            ("can_import", "INTEGER DEFAULT 0"),
            ("can_export", "INTEGER DEFAULT 0"),
            ("can_backup", "INTEGER DEFAULT 0"),
            ("can_restore", "INTEGER DEFAULT 0"),
            ("can_manage", "INTEGER DEFAULT 0"),
            ("updated_at", "TEXT"),
        ],
        "auth_login_logs": [
            ("username", "TEXT"),
            ("display_name", "TEXT"),
            ("event_time", "TEXT"),
            ("event_type", "TEXT"),
            ("result", "TEXT"),
            ("module_code", "TEXT"),
            ("module_name", "TEXT"),
            ("message", "TEXT"),
            ("ip_address", "TEXT"),
            ("user_agent", "TEXT"),
        ],
        "auth_security_settings": [
            ("setting_key", "TEXT"),
            ("setting_value", "TEXT"),
            ("note", "TEXT"),
            ("updated_at", "TEXT"),
        ],
    }
    for table_name, columns in migrations.items():
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if not exists:
                continue
            for column_name, definition in columns:
                _add_column_if_missing(conn, table_name, column_name, definition)
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass


def _init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # 製令主檔
    cur.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_order TEXT UNIQUE NOT NULL,
        part_no TEXT,
        type_name TEXT,
        assembly_location TEXT,
        customer TEXT,
        note TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # 人員名單
    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT UNIQUE NOT NULL,
        employee_name TEXT NOT NULL,
        department TEXT,
        title TEXT,
        is_active INTEGER DEFAULT 1,
        is_in_factory INTEGER DEFAULT 1,
        is_today_attendance INTEGER DEFAULT 1,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # 工時紀錄
    cur.execute("""
    CREATE TABLE IF NOT EXISTS time_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_key TEXT UNIQUE,
        status TEXT,
        work_order TEXT,
        part_no TEXT,
        type_name TEXT,
        process_name TEXT,
        employee_id TEXT,
        employee_name TEXT,
        start_action TEXT,
        start_timestamp TEXT,
        end_action TEXT,
        end_timestamp TEXT,
        remark TEXT,
        start_date TEXT,
        start_time TEXT,
        end_date TEXT,
        end_time TEXT,
        work_hours REAL DEFAULT 0,
        assembly_location TEXT,
        group_key TEXT,
        is_group_work INTEGER DEFAULT 0,
        source TEXT DEFAULT 'streamlit',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # LOG
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_time TEXT,
        user_name TEXT,
        action_type TEXT,
        target_table TEXT,
        target_id TEXT,
        message TEXT,
        detail TEXT,
        level TEXT DEFAULT 'INFO'
    )
    """)

    # 休息時間設定
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rest_periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0
    )
    """)

    # 工段名稱設定：供 01 工時紀錄下拉選單使用，避免寫死在程式內。
    cur.execute("""
    CREATE TABLE IF NOT EXISTS process_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        process_name TEXT UNIQUE NOT NULL,
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # 系統設定
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        note TEXT,
        updated_at TEXT
    )
    """)

    # 表格欄寬/排序設定
    cur.execute("""
    CREATE TABLE IF NOT EXISTS table_column_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_key TEXT,
        table_key TEXT,
        column_key TEXT,
        column_width INTEGER,
        sort_order INTEGER,
        updated_at TEXT,
        UNIQUE(page_key, table_key, column_key)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS table_sort_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_key TEXT,
        table_key TEXT,
        sort_column TEXT,
        sort_ascending INTEGER DEFAULT 1,
        updated_at TEXT,
        UNIQUE(page_key, table_key)
    )
    """)

    # 權限管理資料表：放在 db_service 內建立，確保 GitHub JSON 還原時表已存在。
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auth_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        password_hint TEXT,
        employee_id TEXT,
        display_name TEXT,
        email TEXT,
        role_code TEXT DEFAULT 'operator',
        is_active INTEGER DEFAULT 1,
        force_password_change INTEGER DEFAULT 0,
        last_login_at TEXT,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auth_account_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        module_code TEXT NOT NULL,
        module_name_zh TEXT,
        module_name_en TEXT,
        can_view INTEGER DEFAULT 0,
        can_create INTEGER DEFAULT 0,
        can_edit INTEGER DEFAULT 0,
        can_delete INTEGER DEFAULT 0,
        can_import INTEGER DEFAULT 0,
        can_export INTEGER DEFAULT 0,
        can_backup INTEGER DEFAULT 0,
        can_restore INTEGER DEFAULT 0,
        can_manage INTEGER DEFAULT 0,
        updated_at TEXT,
        UNIQUE(username, module_code)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auth_login_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        display_name TEXT,
        event_time TEXT,
        event_type TEXT,
        result TEXT,
        module_code TEXT,
        module_name TEXT,
        message TEXT,
        ip_address TEXT,
        user_agent TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auth_security_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        note TEXT,
        updated_at TEXT
    )
    """)

    # V3.53: CREATE TABLE IF NOT EXISTS does not add missing columns to old DB files.
    # Run an idempotent migration before default inserts and SELECT queries.
    _migrate_existing_schema(conn)

    now = _now()

    default_rests = [
        (1, "上午休息", "10:30", "10:45", 1),
        (2, "午休", "12:00", "13:00", 2),
        (3, "下午休息", "15:00", "15:15", 3),
        (4, "晚餐休息", "18:00", "18:30", 4),
        (5, "晚上休息", "20:00", "20:15", 5),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO rest_periods (id, name, start_time, end_time, is_active, sort_order)
        VALUES (?, ?, ?, ?, 1, ?)
    """, default_rests)

    default_processes = [
        "前置鈑金", "LP改造", "骨架組立", "配電", "模組", "水平", "S.T.", "清潔", "收機", "包機",
        "Packing", "異常", "設變", "重工", "教育訓練", "IPQC", "其他",
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
        VALUES (?, 1, ?, '系統預設工段，可於 13 系統設定修改', ?, ?)
    """, [(name, idx, now, now) for idx, name in enumerate(default_processes, start=1)])

    settings = [
        ("company_name", "超慧科技", "公司名稱"),
        ("system_name", "製造部智慧工時紀錄系統", "系統名稱"),
        ("standard_work_start", "09:00", "標準上班時間"),
        ("standard_work_end", "18:00", "標準下班時間"),
        ("daily_expected_hours_min", "7.0", "每日最低合理工時"),
        ("daily_expected_hours_max", "7.5", "每日最高合理工時"),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO system_settings (setting_key, setting_value, note, updated_at)
        VALUES (?, ?, ?, ?)
    """, [(k, v, n, now) for k, v, n in settings])

    cur.execute("""
    INSERT OR IGNORE INTO auth_security_settings(setting_key, setting_value, note, updated_at)
    VALUES ('idle_timeout_minutes','15','閒置自動登出分鐘數 / Idle logout minutes',?)
    """, (now,))

    cur.execute("""
        INSERT INTO system_logs (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        SELECT ?, 'SYSTEM', 'AUTO_INIT_DATABASE', 'ALL', '', '自動初始化資料庫完成', ?, 'INFO'
        WHERE NOT EXISTS (SELECT 1 FROM system_logs WHERE action_type='AUTO_INIT_DATABASE')
    """, (now, str(DB_PATH)))


    # 常用查詢索引：避免切換模組時歷史/人員/製令查詢變慢。
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_work_orders_order ON work_orders(work_order)",
        "CREATE INDEX IF NOT EXISTS idx_work_orders_active ON work_orders(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_employees_empid ON employees(employee_id)",
        "CREATE INDEX IF NOT EXISTS idx_employees_active_factory ON employees(is_active, is_in_factory, is_today_attendance)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_emp_date ON time_records(employee_id, start_date)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_work_order ON time_records(work_order)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_status ON time_records(status)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_start_date ON time_records(start_date)",
        "CREATE INDEX IF NOT EXISTS idx_auth_users_username ON auth_users(username)",
        "CREATE INDEX IF NOT EXISTS idx_auth_perm_user_module ON auth_account_permissions(username, module_code)",
        "CREATE INDEX IF NOT EXISTS idx_auth_login_logs_time ON auth_login_logs(event_time)",
        "CREATE INDEX IF NOT EXISTS idx_security_users_username ON security_users(username)",
        "CREATE INDEX IF NOT EXISTS idx_security_login_logs_time ON security_login_logs(login_time, created_at)",
    ]:
        try:
            cur.execute(idx_sql)
        except Exception:
            pass
    conn.commit()



# ===== V3.54 database self-repair guard =====
def _is_repairable_database_error(exc: Exception) -> bool:
    """Detect SQLite errors that can be repaired by schema migration/recreate.

    Streamlit Cloud sometimes keeps an old/empty DB file after file moves.  The
    visible error becomes pandas.errors.DatabaseError on pages such as 01 工時紀錄,
    while the actual cause is usually "no such table", "no such column", or a
    damaged SQLite file.  This guard lets the app repair once instead of crashing.
    """
    msg = str(exc or "").lower()
    keywords = (
        "no such table",
        "no such column",
        "has no column named",
        "database disk image is malformed",
        "file is not a database",
        "unable to open database file",
        "readonly database",
        "attempt to write a readonly database",
    )
    return any(k in msg for k in keywords)


def _backup_broken_database(reason: str = "") -> Path | None:
    """Move a corrupted DB aside before recreating schema.

    This is only used for damaged/non-SQLite files.  Normal schema migrations do
    not move the DB and never drop user data.
    """
    try:
        if not DB_PATH.exists():
            return None
        backup_dir = DB_DIR / "broken_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = backup_dir / f"spt_time_tracking_broken_{stamp}.db"
        shutil.move(str(DB_PATH), str(target))
        return target
    except Exception:
        return None


def _repair_database_after_error(exc: Exception, *, destructive_if_corrupted: bool = True) -> dict[str, Any]:
    """Repair DB after a query/execute failure, then caller may retry once."""
    global _SCHEMA_READY, _RESTORE_CHECKED
    msg = str(exc or "")
    low = msg.lower()
    result: dict[str, Any] = {"ok": False, "message": msg, "backup_path": ""}
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        if destructive_if_corrupted and (
            "database disk image is malformed" in low or "file is not a database" in low
        ):
            backup = _backup_broken_database(msg)
            result["backup_path"] = str(backup or "")

        _SCHEMA_READY = False
        _RESTORE_CHECKED = False
        with _open_connection() as conn:
            _init_schema(conn)
        _SCHEMA_READY = True

        # Try to rescue business data from the canonical permanent JSON after a
        # recreated/empty database.  Failures here must not block app startup.
        try:
            ensure_data_guard_restore(force=True)
        except Exception:
            pass
        result["ok"] = True
        result["message"] = "SQLite schema repaired and data guard executed."
    except Exception as repair_exc:
        result["ok"] = False
        result["message"] = f"repair failed: {repair_exc}; original: {msg}"
    return result

def ensure_database() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        with _open_connection() as conn:
            _init_schema(conn)
    except Exception as exc:
        if _is_repairable_database_error(exc):
            repaired = _repair_database_after_error(exc)
            if not repaired.get("ok"):
                raise
        else:
            raise
    # V3.02: 01/02 share time_records. If DB was recreated empty after a module update,
    # restore from canonical/legacy module JSON, local backups, or external backups.
    try:
        from services.time_records_guard_service import rescue_time_records_if_empty
        rescue_time_records_if_empty(trigger="ensure_database")
    except Exception:
        pass
    _SCHEMA_READY = True


def database_business_row_count() -> int:
    ensure_database()
    tables = ["work_orders", "employees", "time_records"]
    total = 0
    with _open_connection() as conn:
        for table in tables:
            try:
                total += int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except Exception:
                pass
    return total


def ensure_data_guard_restore(force: bool = False) -> dict[str, Any]:
    """啟動/查詢前資料防消失還原。

    force=False 時每個 process 僅檢查一次；force=True 可由第 09 頁手動再次執行。
    """
    global _RESTORE_CHECKED
    if _RESTORE_CHECKED and not force:
        return {"ok": True, "skipped": True, "message": "已檢查過自動還原。"}

    ensure_database()

    # V1.39 speed guard:
    # If business data already exists locally, never call GitHub on normal page entry.
    # Network calls were the main reason every module felt slow after permissions/persistence were added.
    if not force:
        try:
            if database_business_row_count() > 0:
                _RESTORE_CHECKED = True
                return {"ok": True, "skipped": True, "message": "本機主資料已存在，略過 GitHub 自動還原檢查。"}
        except Exception:
            pass

    results: list[dict[str, Any]] = []

    # 1) 先從 GitHub 下載 latest JSON，這對 Streamlit Cloud 最重要，但只在 DB 空白或手動 force 時執行。
    try:
        from services.github_cloud_storage_service import restore_from_github_if_database_empty
        res = restore_from_github_if_database_empty(force=force)
        results.append({"step": "github_cloud_restore", **(res if isinstance(res, dict) else {"result": str(res)})})
        if isinstance(res, dict) and res.get("ok") and not res.get("skipped"):
            _RESTORE_CHECKED = True
            return {"ok": True, "message": "已從 GitHub 永久檔自動還原。", "results": results}
    except Exception as exc:
        results.append({"step": "github_cloud_restore", "ok": False, "message": str(exc)})

    # 2) 再從本機 persistent_state / persistent_backups 還原。
    try:
        from services.persistence_service import auto_restore_if_database_empty
        res = auto_restore_if_database_empty(force=force)
        results.append({"step": "local_persistent_restore", **(res if isinstance(res, dict) else {"result": str(res)})})
        try:
            from services.time_records_guard_service import rescue_time_records_if_empty
            rescue = rescue_time_records_if_empty(trigger="ensure_data_guard_restore")
            results.append({"step": "time_records_guard_rescue", **(rescue if isinstance(rescue, dict) else {"result": str(rescue)})})
        except Exception as exc:
            results.append({"step": "time_records_guard_rescue", "ok": False, "message": str(exc)})
        _RESTORE_CHECKED = True
        return {"ok": bool(isinstance(res, dict) and res.get("ok")), "message": "自動還原檢查完成。", "results": results}
    except Exception as exc:
        results.append({"step": "local_persistent_restore", "ok": False, "message": str(exc)})

    _RESTORE_CHECKED = True
    return {"ok": False, "message": "自動還原未完成。", "results": results}


def get_connection() -> sqlite3.Connection:
    ensure_database()
    ensure_data_guard_restore()
    return _open_connection()


def _auto_export_after_write_enabled() -> bool:
    """Durability switch.

    Default is ON because Streamlit Cloud local files are disposable after Reboot.
    Every real write must refresh data/permanent_store latest JSON and, when
    GITHUB_TOKEN is configured, upload it to GitHub. Set
    SPT_AUTO_EXPORT_AFTER_WRITE=0 only for temporary offline debugging.
    """
    val = str(os.environ.get("SPT_AUTO_EXPORT_AFTER_WRITE", "1")).strip().lower()
    return val not in {"0", "false", "no", "off", "disable", "disabled"}


def mark_data_changed(reason: str = "資料已變更，待備份", source_sql: str | None = None) -> None:
    """Create a tiny marker that page 09 can show as 'pending backup'."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        old: dict[str, Any] = {}
        if PENDING_BACKUP_MARKER.exists():
            try:
                old = json.loads(PENDING_BACKUP_MARKER.read_text(encoding="utf-8")) or {}
            except Exception:
                old = {}
        payload = {
            "pending": True,
            "reason": reason,
            "updated_at": _now(),
            "first_pending_at": old.get("first_pending_at") or _now(),
            "change_count": int(old.get("change_count") or 0) + 1,
            "source_sql": (source_sql or "")[:300],
        }
        PENDING_BACKUP_MARKER.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def clear_pending_backup_marker() -> None:
    try:
        PENDING_BACKUP_MARKER.unlink(missing_ok=True)
    except Exception:
        pass


def pending_backup_status() -> dict[str, Any]:
    try:
        if not PENDING_BACKUP_MARKER.exists():
            return {"pending": False, "message": "目前沒有待備份變更。"}
        data = json.loads(PENDING_BACKUP_MARKER.read_text(encoding="utf-8")) or {}
        data.setdefault("pending", True)
        return data
    except Exception as exc:
        return {"pending": False, "message": str(exc)}


def flush_pending_permanent_state(upload_github: bool = False) -> dict[str, Any]:
    """Manual backup helper: export latest JSON, optionally upload to GitHub."""
    result: dict[str, Any] = {"ok": False, "steps": []}
    try:
        from services.persistence_service import safe_export_after_write
        export_res = safe_export_after_write()
        result["steps"].append({"step": "export_permanent_state", **(export_res if isinstance(export_res, dict) else {"result": str(export_res)})})
        ok = bool(isinstance(export_res, dict) and not export_res.get("skipped") and export_res.get("business_row_count", 1) != 0)
        result["ok"] = ok or bool(isinstance(export_res, dict) and export_res.get("version"))
    except Exception as exc:
        result["steps"].append({"step": "export_permanent_state", "ok": False, "message": str(exc)})
        result["ok"] = False

    if upload_github:
        try:
            from services.github_cloud_storage_service import upload_existing_permanent_files
            upload_res = upload_existing_permanent_files(archive=True)
            result["steps"].append({"step": "upload_github", **(upload_res if isinstance(upload_res, dict) else {"result": str(upload_res)})})
            result["ok"] = bool(result.get("ok")) and bool(isinstance(upload_res, dict) and upload_res.get("ok"))
        except Exception as exc:
            result["steps"].append({"step": "upload_github", "ok": False, "message": str(exc)})
            result["ok"] = False

    if result.get("ok"):
        clear_pending_backup_marker()
        result["message"] = "永久備份已完成，待備份標記已清除。"
    else:
        result.setdefault("message", "永久備份未完成，請查看 steps。")
    return result


def _after_write(sql: str | None = None) -> None:
    """V1.90 fast write path.

    Previous versions exported the full permanent JSON and could also upload to
    GitHub after ordinary DELETE/UPDATE operations.  That made deleting one time
    record take 20 seconds.  Now ordinary writes only clear the SELECT cache and
    mark a small 'pending backup' flag.  Page 09 / manual backup performs the
    heavy persistence work.
    """
    global _LAST_CLOUD_SYNC_TS
    clear_query_cache()
    mark_data_changed("資料已變更，請到 09｜資料永久保存與備份執行備份。", sql)

    if not _auto_export_after_write_enabled():
        return

    # Durable write-through mode. This refreshes the single permanent store and,
    # when GITHUB_TOKEN is configured, uploads latest JSON to GitHub. The called
    # service has its own throttle to avoid excessive API calls.
    now_ts = time.time()
    if now_ts - _LAST_CLOUD_SYNC_TS < _CLOUD_SYNC_INTERVAL_SEC:
        return
    try:
        from services.auto_github_sync_service import auto_sync_after_write
        auto_sync_after_write(source="db_service_write", force=False, archive=False)
        _LAST_CLOUD_SYNC_TS = now_ts
    except Exception:
        try:
            from services.persistence_service import safe_export_after_write
            safe_export_after_write()
            _LAST_CLOUD_SYNC_TS = now_ts
        except Exception:
            pass


def execute(sql: str, params: Iterable[Any] | None = None) -> int:
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    try:
        with _open_connection() as conn:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            last_id = cur.lastrowid
    except Exception as exc:
        if not _is_repairable_database_error(exc):
            raise
        repaired = _repair_database_after_error(exc)
        if not repaired.get("ok"):
            raise
        with _open_connection() as conn:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            last_id = cur.lastrowid
    clear_query_cache()
    if _should_after_write_sync(sql):
        _after_write(sql)
    return int(last_id or 0)


def executemany(sql: str, rows: list[Iterable[Any]]) -> None:
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    try:
        with _open_connection() as conn:
            conn.executemany(sql, rows)
            conn.commit()
    except Exception as exc:
        if not _is_repairable_database_error(exc):
            raise
        repaired = _repair_database_after_error(exc)
        if not repaired.get("ok"):
            raise
        with _open_connection() as conn:
            conn.executemany(sql, rows)
            conn.commit()
    clear_query_cache()
    if _should_after_write_sync(sql):
        _after_write(sql)


def query_df(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()

    cacheable = _is_select_sql(sql)
    key = _query_cache_key(sql, params)
    now_ts = time.time()
    if cacheable:
        cached = _QUERY_CACHE.get(key)
        if cached and now_ts - cached[0] <= _QUERY_CACHE_TTL_SEC:
            return cached[1].copy()

    try:
        with _open_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=tuple(params))
    except Exception as exc:
        if not _is_repairable_database_error(exc):
            raise
        repaired = _repair_database_after_error(exc)
        if not repaired.get("ok"):
            raise
        # Retry once after schema repair / data rescue.
        with _open_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=tuple(params))

    if cacheable:
        try:
            if len(_QUERY_CACHE) >= _QUERY_CACHE_MAX_ITEMS:
                oldest = min(_QUERY_CACHE.items(), key=lambda kv: kv[1][0])[0]
                _QUERY_CACHE.pop(oldest, None)
            _QUERY_CACHE[key] = (now_ts, df.copy())
        except Exception:
            pass
    return df


def query_one(sql: str, params: Iterable[Any] | None = None) -> dict | None:
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    with _open_connection() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None


# ===== V7 read/save speed patch =====
# 不改路徑、不改資料表、不改功能；只減少 Streamlit rerun 造成的重複 SELECT 與 SQLite 開銷。
try:
    _QUERY_CACHE_TTL_SEC = max(float(globals().get("_QUERY_CACHE_TTL_SEC", 10.0)), 45.0)
    _QUERY_CACHE_MAX_ITEMS = max(int(globals().get("_QUERY_CACHE_MAX_ITEMS", 120)), 300)
except Exception:
    pass

_QUERY_ONE_CACHE: dict[tuple[str, tuple[Any, ...]], tuple[float, dict | None]] = {}


def _v7_cache_get_df(key: tuple[str, tuple[Any, ...]], now_ts: float):
    try:
        cached = _QUERY_CACHE.get(key)
        if cached and now_ts - cached[0] <= _QUERY_CACHE_TTL_SEC:
            # shallow copy is enough for pandas display flows and much faster on large tables.
            return cached[1].copy(deep=False)
    except Exception:
        pass
    return None


def _v7_cache_put_df(key: tuple[str, tuple[Any, ...]], now_ts: float, df: pd.DataFrame) -> None:
    try:
        if len(_QUERY_CACHE) >= _QUERY_CACHE_MAX_ITEMS:
            oldest = min(_QUERY_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _QUERY_CACHE.pop(oldest, None)
        _QUERY_CACHE[key] = (now_ts, df.copy(deep=False))
    except Exception:
        pass


def clear_query_cache() -> None:  # type: ignore[override]
    try:
        _QUERY_CACHE.clear()
    except Exception:
        pass
    try:
        _QUERY_ONE_CACHE.clear()
    except Exception:
        pass


def query_df(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:  # type: ignore[override]
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    cacheable = _is_select_sql(sql)
    key = _query_cache_key(sql, params)
    now_ts = time.time()
    if cacheable:
        hit = _v7_cache_get_df(key, now_ts)
        if hit is not None:
            return hit
    try:
        with _open_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=tuple(params))
    except Exception as exc:
        # Keep V4 self-repair behavior if present.
        try:
            _repair_database_after_error(exc)
            with _open_connection() as conn:
                df = pd.read_sql_query(sql, conn, params=tuple(params))
        except Exception:
            raise exc
    if cacheable:
        _v7_cache_put_df(key, now_ts, df)
    return df


def query_one(sql: str, params: Iterable[Any] | None = None) -> dict | None:  # type: ignore[override]
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    cacheable = _is_select_sql(sql)
    key = _query_cache_key(sql, params)
    now_ts = time.time()
    if cacheable:
        cached = _QUERY_ONE_CACHE.get(key)
        if cached and now_ts - cached[0] <= _QUERY_CACHE_TTL_SEC:
            return dict(cached[1]) if isinstance(cached[1], dict) else None
    with _open_connection() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        out = dict(row) if row else None
    if cacheable:
        try:
            if len(_QUERY_ONE_CACHE) >= _QUERY_CACHE_MAX_ITEMS:
                oldest = min(_QUERY_ONE_CACHE.items(), key=lambda kv: kv[1][0])[0]
                _QUERY_ONE_CACHE.pop(oldest, None)
            _QUERY_ONE_CACHE[key] = (now_ts, dict(out) if isinstance(out, dict) else None)
        except Exception:
            pass
    return out


def _open_connection() -> sqlite3.Connection:  # type: ignore[override]
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=12000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        # WAL improves read/write concurrency on Streamlit reruns. Ignore if filesystem does not support it.
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn

# ===== V9 STARTUP SPEED PATCH: suppress write-through during internal restore/seed =====
# 目的：開啟 01/13/10 等頁面時，系統可能會執行「從 permanent_store 還原到 SQLite」的內部補表動作。
# 這些動作不是使用者手動儲存，不應觸發 GitHub write-through，否則開頁會卡 1~3 分鐘以上。
from contextlib import contextmanager as _v9_contextmanager

_V9_SUPPRESS_AFTER_WRITE_DEPTH = 0
_V9_SUPPRESS_AFTER_WRITE_REASON = ""

@_v9_contextmanager
def suspend_after_write_sync(reason: str = "internal_restore"):
    """Temporarily disable expensive after-write export/GitHub sync.

    Use only for internal restore/schema/seed flows. User-initiated saves still use
    the normal durable path, so permanent-store behavior is not weakened.
    """
    global _V9_SUPPRESS_AFTER_WRITE_DEPTH, _V9_SUPPRESS_AFTER_WRITE_REASON
    _V9_SUPPRESS_AFTER_WRITE_DEPTH += 1
    old_reason = _V9_SUPPRESS_AFTER_WRITE_REASON
    _V9_SUPPRESS_AFTER_WRITE_REASON = str(reason or "internal_restore")
    try:
        yield
    finally:
        _V9_SUPPRESS_AFTER_WRITE_DEPTH = max(0, _V9_SUPPRESS_AFTER_WRITE_DEPTH - 1)
        _V9_SUPPRESS_AFTER_WRITE_REASON = old_reason


def is_after_write_sync_suspended() -> bool:
    try:
        return int(_V9_SUPPRESS_AFTER_WRITE_DEPTH) > 0
    except Exception:
        return False


def execute(sql: str, params: Iterable[Any] | None = None) -> int:  # type: ignore[override]
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    try:
        with _open_connection() as conn:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            last_id = cur.lastrowid
    except Exception as exc:
        if not _is_repairable_database_error(exc):
            raise
        repaired = _repair_database_after_error(exc)
        if not repaired.get("ok"):
            raise
        with _open_connection() as conn:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            last_id = cur.lastrowid
    clear_query_cache()
    if _should_after_write_sync(sql) and not is_after_write_sync_suspended():
        _after_write(sql)
    return int(last_id or 0)


def executemany(sql: str, rows: list[Iterable[Any]]) -> None:  # type: ignore[override]
    ensure_database()
    if _should_run_data_guard(sql):
        ensure_data_guard_restore()
    try:
        with _open_connection() as conn:
            conn.executemany(sql, rows)
            conn.commit()
    except Exception as exc:
        if not _is_repairable_database_error(exc):
            raise
        repaired = _repair_database_after_error(exc)
        if not repaired.get("ok"):
            raise
        with _open_connection() as conn:
            conn.executemany(sql, rows)
            conn.commit()
    clear_query_cache()
    if _should_after_write_sync(sql) and not is_after_write_sync_suspended():
        _after_write(sql)
# ===== V9 STARTUP SPEED PATCH END =====


# ===== V16 FAST BOOTSTRAP + TRANSACTION HOTFIX =====
# 目的：
# 1) 修正 V14 time_record_service 匯入 execute_transaction 時的 ImportError。
# 2) 01 工時紀錄按下確認/開始/結束時改用單一 SQLite transaction，避免每一筆 SQL 都重跑永久保存流程。
# 3) 各模組讀取時不再重複進入昂貴資料防護流程；正式還原仍保留於第一次啟動、DB 空白、或手動 force 時。

_V16_FAST_READ_GUARD_READY = False


def _v16_is_read_sql(sql: str | None) -> bool:
    try:
        return _normalise_sql(sql or '').strip().startswith('select')
    except Exception:
        return False


def _v16_should_skip_guard_for_fast_read(sql: str | None) -> bool:
    """Skip expensive restore checks for normal SELECT after schema is ready.

    This does not change any save path.  If DB is missing/corrupted, ensure_database()
    still repairs it.  If user manually triggers restore/backup pages, those flows still
    call force=True routines directly.
    """
    if not _v16_is_read_sql(sql):
        return False
    try:
        if not DB_PATH.exists() or DB_PATH.stat().st_size <= 0:
            return False
    except Exception:
        return False
    # Once schema was initialized in this Python process, do not re-enter data guard
    # for ordinary reads.  This is the major source of slow page switching.
    return bool(globals().get('_SCHEMA_READY')) or bool(globals().get('_RESTORE_CHECKED'))


# keep previous functions for fallback
_v16_prev_query_df = query_df
_v16_prev_query_one = query_one


def query_df(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:  # type: ignore[override]
    ensure_database()
    if (not _v16_should_skip_guard_for_fast_read(sql)) and _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    cacheable = _is_select_sql(sql)
    key = _query_cache_key(sql, params)
    now_ts = time.time()
    if cacheable:
        hit = _v7_cache_get_df(key, now_ts) if '_v7_cache_get_df' in globals() else None
        if hit is not None:
            return hit
    try:
        with _open_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=tuple(params))
    except Exception as exc:
        try:
            _repair_database_after_error(exc)
            with _open_connection() as conn:
                df = pd.read_sql_query(sql, conn, params=tuple(params))
        except Exception:
            raise exc
    if cacheable:
        try:
            if '_v7_cache_put_df' in globals():
                _v7_cache_put_df(key, now_ts, df)
        except Exception:
            pass
    return df


def query_one(sql: str, params: Iterable[Any] | None = None) -> dict | None:  # type: ignore[override]
    ensure_database()
    if (not _v16_should_skip_guard_for_fast_read(sql)) and _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()
    cacheable = _is_select_sql(sql)
    key = _query_cache_key(sql, params)
    now_ts = time.time()
    if cacheable:
        try:
            cached = _QUERY_ONE_CACHE.get(key)
            if cached and now_ts - cached[0] <= _QUERY_CACHE_TTL_SEC:
                return dict(cached[1]) if isinstance(cached[1], dict) else None
        except Exception:
            pass
    with _open_connection() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        out = dict(row) if row else None
    if cacheable:
        try:
            if len(_QUERY_ONE_CACHE) >= _QUERY_CACHE_MAX_ITEMS:
                oldest = min(_QUERY_ONE_CACHE.items(), key=lambda kv: kv[1][0])[0]
                _QUERY_ONE_CACHE.pop(oldest, None)
            _QUERY_ONE_CACHE[key] = (now_ts, dict(out) if isinstance(out, dict) else None)
        except Exception:
            pass
    return out


def execute_transaction(
    operations: list[tuple[str, Iterable[Any]]] | tuple[tuple[str, Iterable[Any]], ...],
    mark_changed: bool = True,
    reason: str = '資料已變更，待備份',
    source_sql: str = 'BATCH_TRANSACTION',
) -> list[int]:
    """Run many SQL writes in one SQLite transaction and one persistence cycle.

    operations item format: (sql, params).  It returns lastrowid for each statement so
    callers can identify inserted records.  This preserves behavior while avoiding
    the previous slow pattern: execute() -> export -> GitHub check per SQL statement.
    """
    ensure_database()
    if operations is None:
        operations = []
    ids: list[int] = []
    if not operations:
        return ids
    try:
        with _open_connection() as conn:
            cur = conn.cursor()
            for item in operations:
                if not item:
                    ids.append(0)
                    continue
                sql = item[0]
                params = item[1] if len(item) > 1 and item[1] is not None else ()
                cur.execute(sql, tuple(params))
                ids.append(int(cur.lastrowid or 0))
            conn.commit()
    except Exception as exc:
        if not _is_repairable_database_error(exc):
            raise
        repaired = _repair_database_after_error(exc)
        if not repaired.get('ok'):
            raise
        with _open_connection() as conn:
            cur = conn.cursor()
            ids = []
            for item in operations:
                sql = item[0]
                params = item[1] if len(item) > 1 and item[1] is not None else ()
                cur.execute(sql, tuple(params))
                ids.append(int(cur.lastrowid or 0))
            conn.commit()
    clear_query_cache()
    if mark_changed:
        try:
            mark_data_changed(reason=reason, source_sql=source_sql)
        except Exception:
            pass
        # One lightweight export/sync attempt for the whole transaction, not per SQL.
        try:
            if not is_after_write_sync_suspended() and _auto_export_after_write_enabled():
                _after_write(source_sql)
        except Exception:
            pass
    return ids
# ===== V16 FAST BOOTSTRAP + TRANSACTION HOTFIX END =====

# ===== V23 QUERY_ONE DB ERROR HOTFIX =====
# Streamlit Cloud can keep an older/corrupted SQLite file after deployments.  Earlier
# query_df/execute paths already repaired and retried, but the latest query_one override
# still executed SELECT directly and could crash pages such as 01. 工時紀錄 when checking
# active records.  This final override gives query_one the same repair/retry behavior.
_v23_prev_query_one = query_one


def _v23_is_retryable_query_one_error(exc: Exception) -> bool:
    msg = str(exc or '').lower()
    retry_keywords = (
        'no such table',
        'no such column',
        'database disk image is malformed',
        'file is not a database',
        'unable to open database file',
        'database is locked',
        'database schema has changed',
        'readonly database',
        'attempt to write a readonly database',
    )
    return isinstance(exc, (sqlite3.DatabaseError, sqlite3.OperationalError)) or any(k in msg for k in retry_keywords)


def query_one(sql: str, params: Iterable[Any] | None = None) -> dict | None:  # type: ignore[override]
    """Return one row with SQLite self-repair/retry.

    This preserves the existing cache and guard behavior, but prevents single-row reads
    from bypassing the DB repair path.  It is intentionally read-only and does not change
    any persistence path, GitHub write-through behavior, or UI logic.
    """
    ensure_database()
    if (not _v16_should_skip_guard_for_fast_read(sql)) and _should_run_data_guard(sql):
        ensure_data_guard_restore()
    if params is None:
        params = ()

    cacheable = _is_select_sql(sql)
    key = _query_cache_key(sql, params)
    now_ts = time.time()
    if cacheable:
        try:
            cached = _QUERY_ONE_CACHE.get(key)
            if cached and now_ts - cached[0] <= _QUERY_CACHE_TTL_SEC:
                return dict(cached[1]) if isinstance(cached[1], dict) else None
        except Exception:
            pass

    def _run_once() -> dict | None:
        with _open_connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    try:
        out = _run_once()
    except Exception as exc:
        if not _v23_is_retryable_query_one_error(exc):
            raise
        # Locked DB usually resolves after a short wait; corrupted/missing schema needs repair.
        try:
            time.sleep(0.15)
            out = _run_once()
        except Exception:
            repaired = _repair_database_after_error(exc)
            if not repaired.get('ok'):
                raise exc
            clear_query_cache()
            out = _run_once()

    if cacheable:
        try:
            if len(_QUERY_ONE_CACHE) >= _QUERY_CACHE_MAX_ITEMS:
                oldest = min(_QUERY_ONE_CACHE.items(), key=lambda kv: kv[1][0])[0]
                _QUERY_ONE_CACHE.pop(oldest, None)
            _QUERY_ONE_CACHE[key] = (now_ts, dict(out) if isinstance(out, dict) else None)
        except Exception:
            pass
    return out
# ===== END V23 QUERY_ONE DB ERROR HOTFIX =====


# ===== V24 LIGHTWEIGHT SYSTEM LOG AUDIT FOR ALL DB WRITES =====
# 目的：06.LOG查詢需要能看到各模組實際資料異動。此處只做輕量記錄，不改原寫入路徑。
import re as _v24_re
import getpass as _v24_getpass

_v24_prev_execute = execute
_v24_prev_executemany = executemany
_v24_prev_execute_transaction = execute_transaction


def _v24_sql_action_and_table(sql: str | None) -> tuple[str, str]:
    text = str(sql or '').strip()
    low = text.lower()
    if not text:
        return '', ''
    if low.startswith('insert'):
        m = _v24_re.search(r'insert\s+(?:or\s+\w+\s+)?into\s+([\w_]+)', low, _v24_re.I)
        return 'INSERT', (m.group(1) if m else '')
    if low.startswith('update'):
        m = _v24_re.search(r'update\s+([\w_]+)', low, _v24_re.I)
        return 'UPDATE', (m.group(1) if m else '')
    if low.startswith('delete'):
        m = _v24_re.search(r'delete\s+from\s+([\w_]+)', low, _v24_re.I)
        return 'DELETE', (m.group(1) if m else '')
    if low.startswith('replace'):
        m = _v24_re.search(r'replace\s+into\s+([\w_]+)', low, _v24_re.I)
        return 'REPLACE', (m.group(1) if m else '')
    return '', ''


def _v24_should_audit_sql(sql: str | None) -> bool:
    action, table = _v24_sql_action_and_table(sql)
    if action not in {'INSERT','UPDATE','DELETE','REPLACE'}:
        return False
    if table in {'system_logs', 'login_logs', 'security_login_logs', 'auth_login_logs', 'sqlite_sequence'}:
        return False
    # schema/init/repair 類 SQL 不進 LOG，避免洗版與遞迴。
    low = str(sql or '').lower()
    if low.startswith(('create ', 'alter ', 'drop ', 'pragma ')):
        return False
    return True




def _v24_current_audit_user() -> str:
    """Return Streamlit authenticated account for 06 LOG查詢.

    The OS account on Streamlit Cloud is usually appuser/adminuser, which is not
    useful for audit.  Prefer the login account stored by security_service.
    """
    try:
        import streamlit as _v24_st
        ss = getattr(_v24_st, 'session_state', {})
        for key in ('auth_username', 'auth_user', 'username', 'current_username', 'login_username'):
            value = str(ss.get(key, '') or '').strip()
            if value and value.lower() not in {'none', 'nan', 'null'}:
                return value
        for key in ('current_user', 'user', 'auth_user_info'):
            obj = ss.get(key)
            if isinstance(obj, dict):
                for sub_key in ('username', 'account', 'user', 'name'):
                    value = str(obj.get(sub_key, '') or '').strip()
                    if value and value.lower() not in {'none', 'nan', 'null'}:
                        return value
    except Exception:
        pass
    try:
        return _v24_getpass.getuser()
    except Exception:
        return 'system'


def _v24_audit_sql(sql: str | None, params: object = None, detail_prefix: str = '') -> None:
    if not _v24_should_audit_sql(sql):
        return
    action, table = _v24_sql_action_and_table(sql)
    user_name = _v24_current_audit_user()
    try:
        message = f'{action} {table}'.strip()
        detail = (detail_prefix + ' ' + str(sql or '')[:900]).strip()
        with _open_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now_text(), user_name, action, table, '', message, detail, 'INFO'),
            )
            conn.commit()
    except Exception:
        pass


def execute(sql: str, params: Iterable[Any] | None = None) -> int:  # type: ignore[override]
    result = _v24_prev_execute(sql, params)
    _v24_audit_sql(sql, params)
    return result


def executemany(sql: str, rows: list[Iterable[Any]]) -> None:  # type: ignore[override]
    _v24_prev_executemany(sql, rows)
    try:
        count = len(rows or [])
    except Exception:
        count = 0
    _v24_audit_sql(sql, None, detail_prefix=f'batch_rows={count};')


def execute_transaction(
    operations: list[tuple[str, Iterable[Any]]] | tuple[tuple[str, Iterable[Any]], ...],
    mark_changed: bool = True,
    reason: str = '資料已變更，待備份',
    source_sql: str = 'BATCH_TRANSACTION',
) -> list[int]:  # type: ignore[override]
    ids = _v24_prev_execute_transaction(operations, mark_changed=mark_changed, reason=reason, source_sql=source_sql)
    audited_tables: set[tuple[str, str]] = set()
    try:
        for item in operations or []:
            sql = item[0] if item else ''
            action, table = _v24_sql_action_and_table(sql)
            key = (action, table)
            if key not in audited_tables:
                _v24_audit_sql(sql, None, detail_prefix=f'transaction={source_sql};')
                audited_tables.add(key)
    except Exception:
        pass
    return ids
# ===== END V24 LIGHTWEIGHT SYSTEM LOG AUDIT FOR ALL DB WRITES =====


# ===================== V167 NO-BLOCKING WRITE SYNC FINAL OVERRIDE =====================
# 目的：50 人同時記錄時，任何一般寫入不得同步等待 GitHub / 大型 JSON 匯出。
# 寫入後只清除快取與建立待備份標記；09 備份中心或明確環境變數才執行同步。
try:
    _v167_prev_after_write = _after_write
except Exception:
    _v167_prev_after_write = None


def _auto_export_after_write_enabled() -> bool:  # type: ignore[override]
    """Default OFF for runtime writes.

    設為 SPT_SYNC_AFTER_WRITE=1 或 SPT_AUTO_EXPORT_AFTER_WRITE=1 才允許舊版同步路徑。
    預設關閉可避免開始/結束工時卡在 GitHub API 或大型 JSON 匯出。
    """
    val = str(os.environ.get("SPT_SYNC_AFTER_WRITE", os.environ.get("SPT_AUTO_EXPORT_AFTER_WRITE", "0"))).strip().lower()
    return val in {"1", "true", "yes", "on", "enable", "enabled"}


def _after_write(sql: str | None = None) -> None:  # type: ignore[override]
    clear_query_cache()
    try:
        mark_data_changed("資料已變更，已加入待備份佇列；正式備份請由 09/14 或排程執行。", sql)
    except Exception:
        pass
    if not _auto_export_after_write_enabled():
        return
    # 明確打開同步時才沿用舊同步流程；仍保留舊函式相容。
    try:
        if callable(_v167_prev_after_write):
            _v167_prev_after_write(sql)
    except Exception:
        pass
# =================== END V167 NO-BLOCKING WRITE SYNC FINAL OVERRIDE ===================
