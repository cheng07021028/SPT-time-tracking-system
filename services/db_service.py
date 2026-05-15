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

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "data" / "database"
DB_PATH = DB_DIR / "spt_time_tracking.db"

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
    "table_column_settings", "table_sort_settings", "system_settings",
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
    """Only business/settings writes refresh permanent files.

    登入成功/失敗紀錄很頻繁，不應每次都重新匯出 JSON 或上傳 GitHub。
    """
    if not sql:
        return True
    if _is_auth_or_security_sql(sql) and not _is_business_sql(sql):
        return False
    ddl_prefixes = (" create ", " pragma ")
    low = _normalise_sql(sql)
    if any(low.startswith(prefix) for prefix in ddl_prefixes):
        return False
    return True


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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

    now = _now()
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


def _after_write() -> None:
    """寫入後刷新永久檔；若已設定 Token，節流上傳 latest 到 GitHub。"""
    global _LAST_CLOUD_SYNC_TS
    try:
        from services.persistence_service import safe_export_after_write
        safe_export_after_write()
    except Exception:
        pass

    # GitHub API 上傳可能較慢，採簡易節流，避免同一秒大量寫入造成 API 過多請求。
    now_ts = time.time()
    if now_ts - _LAST_CLOUD_SYNC_TS < _CLOUD_SYNC_INTERVAL_SEC:
        return
    try:
        from services.github_cloud_storage_service import github_config, upload_existing_permanent_files
        if github_config().get("token"):
            upload_existing_permanent_files(archive=False)
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
        _after_write()
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
        _after_write()


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
