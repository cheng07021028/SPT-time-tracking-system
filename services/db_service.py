# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.39 - DB Service with Page Switch Speed Guard

重點：
1. 自動建立 SQLite schema，包含工時主資料、UI設定、權限管理資料表。
2. Streamlit Cloud 更新/重啟後，如果 SQLite 不存在或主資料為 0，會自動從 GitHub data/persistent_state 還原。
3. 寫入資料後自動刷新永久 JSON；若已設定 GitHub Token，會嘗試同步 latest JSON 到 GitHub。
4. 嚴格避免「空資料庫」覆蓋 GitHub 上既有永久資料。
5. 登入/權限/安全紀錄類 SQL 不觸發 GitHub 還原與雲端同步，避免登入頁緩慢。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "data" / "database"
DB_PATH = DB_DIR / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
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
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    # Connection-level pragmas: reduce locking and speed up read-heavy Streamlit reruns.
    try:
        conn.execute("PRAGMA busy_timeout=8000")
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


def ensure_database() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _open_connection() as conn:
        _init_schema(conn)
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
    """Optional compatibility switch.

    Default is OFF because automatic GitHub/permanent JSON export after every
    delete/update was the main cause of 20-second operations.  If a deployment
    explicitly needs the old behavior, set SPT_AUTO_EXPORT_AFTER_WRITE=1.
    """
    return str(os.environ.get("SPT_AUTO_EXPORT_AFTER_WRITE", "")).strip().lower() in {"1", "true", "yes", "on"}


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

    # Compatibility mode only: export/upload is throttled and opt-in.
    now_ts = time.time()
    if now_ts - _LAST_CLOUD_SYNC_TS < _CLOUD_SYNC_INTERVAL_SEC:
        return
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
