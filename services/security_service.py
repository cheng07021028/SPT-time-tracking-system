# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.28 - Security / Permission Service

功能：
1. 帳號登入 / 登出。
2. 密碼雜湊保存，不存明碼。
3. 角色與模組權限矩陣。
4. 閒置逾時自動登出。
5. 工時記錄完成後詢問是否繼續，否則登出。
6. 登入、登出、權限不足與安全事件 LOG。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
import json
from html import escape
from typing import Any

import pandas as pd

from services.timezone_service import now_text, now_stamp, today_text, today_date
import streamlit as st
import streamlit.components.v1 as components

from services.db_service import execute, query_df, query_one

# Project root must be defined before persistent security file paths are built.
# Streamlit Cloud imports this module during app startup, so missing PROJECT_ROOT
# causes the whole app to fail before login.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
IDLE_TIMEOUT_FILES = [
    PROJECT_ROOT / "data" / "config" / "idle_timeout_settings.json",
    PROJECT_ROOT / "data" / "persistent_state" / "spt_idle_timeout_settings.json",
    PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "idle_timeout_settings.json",
]

PBKDF2_ITERATIONS = 180_000
DEFAULT_IDLE_MINUTES = 15
_PERMISSION_CACHE_TTL_SECONDS = 300
_SECURITY_SCHEMA_READY = False

PERMISSION_COLUMNS = [
    "can_view", "can_create", "can_edit", "can_delete", "can_import", "can_export",
    "can_backup", "can_restore", "can_manage",
]

MODULES = [
    {"module_code": "01_time_record", "module_no": "01", "module_name": "工時紀錄", "module_name_en": "Time Record"},
    {"module_code": "02_history", "module_no": "02", "module_name": "歷史紀錄", "module_name_en": "History"},
    {"module_code": "03_work_orders", "module_no": "03", "module_name": "製令管理", "module_name_en": "Work Orders"},
    {"module_code": "04_employees", "module_no": "04", "module_name": "人員名單", "module_name_en": "Employees"},
    {"module_code": "05_analysis", "module_no": "05", "module_name": "製令工時分析", "module_name_en": "Analysis"},
    {"module_code": "06_logs", "module_no": "06", "module_name": "LOG查詢", "module_name_en": "Logs"},
    {"module_code": "07_missing", "module_no": "07", "module_name": "今日未紀錄名單", "module_name_en": "Missing Today"},
    {"module_code": "08_daily_hours", "module_no": "08", "module_name": "人員每日工時", "module_name_en": "Daily Hours"},
    {"module_code": "09_persistence", "module_no": "09", "module_name": "資料永久保存與備份", "module_name_en": "Persistence"},
    {"module_code": "10_permissions", "module_no": "10", "module_name": "權限管理", "module_name_en": "Permissions"},
    {"module_code": "11_login_logs", "module_no": "11", "module_name": "登入紀錄", "module_name_en": "Login Logs"},
    {"module_code": "12_module_persistence", "module_no": "12", "module_name": "模組永久紀錄中心", "module_name_en": "Module Permanent Records"},
    {"module_code": "13_system_settings", "module_no": "13", "module_name": "系統設定", "module_name_en": "System Settings"},
]

MODULE_CODE_TO_NO = {m["module_code"]: m["module_no"] for m in MODULES}
MODULE_NO_TO_CODE = {m["module_no"]: m["module_code"] for m in MODULES}

ROLES = [
    ("admin", "系統管理員", "System Admin"),
    ("manager", "製造主管", "Manufacturing Manager"),
    ("leader", "現場幹部", "Line Leader"),
    ("operator", "作業人員", "Operator"),
    ("viewer", "查詢者", "Viewer"),
    ("auditor", "稽核", "Auditor"),
]

DEFAULT_USERS = [
    ("admin", "Admin@1234", "系統管理員", "admin"),
    ("manager", "Manager@1234", "製造主管", "manager"),
    ("leader", "Leader@1234", "現場幹部", "leader"),
    ("operator", "Operator@1234", "作業人員", "operator"),
    ("viewer", "Viewer@1234", "查詢者", "viewer"),
    ("auditor", "Auditor@1234", "稽核", "auditor"),
]


def _now() -> str:
    return now_text()


def _bool(value: Any) -> int:
    return 1 if bool(value) else 0


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Verify both runtime security hashes and permission-page account hashes.

    V1.77 修正：
    - services.security_service 使用格式：pbkdf2_sha256$iterations$salt_base64$hash_base64
    - services.permission_service 使用格式：pbkdf2_sha256$salt_hex_text$hash_hex

    舊版登入只認第一種格式，導致在「10｜權限管理」建立/修改的帳號
    例如 spt142 會一直顯示帳號或密碼錯誤。
    """
    if not stored_hash:
        return False
    try:
        parts = str(stored_hash).split("$")
        if len(parts) == 4:
            algo, iter_s, salt_b64, hash_b64 = parts
            if algo != "pbkdf2_sha256":
                return False
            iterations = int(iter_s)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(hash_b64.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        if len(parts) == 3:
            algo, salt_text, digest_hex = parts
            if algo != "pbkdf2_sha256":
                return False
            actual_hex = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt_text.encode("utf-8"),
                120000,
            ).hex()
            return hmac.compare_digest(actual_hex, digest_hex)
    except Exception:
        return False
    return False


def _security_db_path() -> Path:
    """Return the active SQLite path used by db_service without importing internals at runtime."""
    try:
        from services import db_service as _db
        return Path(getattr(_db, "DB_PATH"))
    except Exception:
        return Path(__file__).resolve().parents[1] / "data" / "database" / "spt_time_tracking.db"


def _security_direct_connect() -> sqlite3.Connection:
    db_path = _security_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=20)
    try:
        conn.execute("PRAGMA busy_timeout=12000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def _table_columns_direct(table: str) -> set[str]:
    """Read SQLite columns directly to avoid db_service/query_df recursion during login."""
    try:
        with _security_direct_connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(r[1]) for r in rows}
    except Exception:
        return set()


def _ensure_sqlite_columns(table: str, columns: dict[str, str]) -> None:
    """Add newly introduced columns when Streamlit/GitHub keeps an older SQLite table.

    V6 hotfix:
    db_service.execute()/query_df can themselves call schema checks during login.  The
    previous migration used those wrappers and could silently fail, then seed_security_defaults
    inserted can_backup/can_restore/can_manage into an older table and crashed the app.
    This migration uses a direct sqlite connection and commits before seeding.
    """
    existing = _table_columns_direct(table)
    if not existing:
        return
    with _security_direct_connect() as conn:
        for col, ddl in columns.items():
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    existing.add(col)
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        # Keep login alive; seed uses adaptive columns below.
                        pass
                except Exception:
                    pass
        try:
            conn.commit()
        except Exception:
            pass


def _insert_or_ignore_adaptive(table: str, values: dict[str, object], required: tuple[str, ...] = ()) -> None:
    """INSERT OR IGNORE using only columns that truly exist in the live DB.

    This prevents Streamlit Cloud from going down when an older SQLite file is kept in
    GitHub/permanent storage and is missing newer columns. Missing optional columns are
    ignored for this run; _ensure_sqlite_columns will add them when SQLite allows it.
    """
    cols = _table_columns_direct(table)
    if not cols or any(c not in cols for c in required):
        return
    usable = [c for c in values.keys() if c in cols]
    if not usable:
        return
    placeholders = ", ".join(["?"] * len(usable))
    sql = f"INSERT OR IGNORE INTO {table} ({', '.join(usable)}) VALUES ({placeholders})"
    params = tuple(values[c] for c in usable)
    execute(sql, params)


def _seed_security_permission_adaptive(role_code: str, module: dict, perm: dict[str, int], now: str) -> None:
    _insert_or_ignore_adaptive(
        "security_module_permissions",
        {
            "role_code": role_code,
            "module_code": module["module_code"],
            "module_no": module["module_no"],
            "module_name": module["module_name"],
            "module_name_en": module["module_name_en"],
            "can_view": perm.get("can_view", 0),
            "can_create": perm.get("can_create", 0),
            "can_edit": perm.get("can_edit", 0),
            "can_delete": perm.get("can_delete", 0),
            "can_import": perm.get("can_import", 0),
            "can_export": perm.get("can_export", 0),
            "can_backup": perm.get("can_backup", 0),
            "can_restore": perm.get("can_restore", 0),
            "can_manage": perm.get("can_manage", 0),
            "updated_at": now,
        },
        required=("role_code", "module_code"),
    )


def _migrate_security_schema_columns() -> None:
    _ensure_sqlite_columns("security_users", {
        "employee_id": "TEXT",
        "display_name": "TEXT",
        "email": "TEXT",
        "is_active": "INTEGER DEFAULT 1",
        "force_password_change": "INTEGER DEFAULT 0",
        "last_login_at": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    })
    _ensure_sqlite_columns("security_roles", {
        "role_name_en": "TEXT",
        "description": "TEXT",
        "is_system_role": "INTEGER DEFAULT 1",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    })
    _ensure_sqlite_columns("security_module_permissions", {
        "module_no": "TEXT",
        "module_name": "TEXT",
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
    })
    _ensure_sqlite_columns("security_settings", {
        "setting_value": "TEXT",
        "note": "TEXT",
        "updated_at": "TEXT",
    })
    _ensure_sqlite_columns("security_login_logs", {
        "display_name": "TEXT",
        "event_type": "TEXT",
        "result": "TEXT",
        "message": "TEXT",
        "module_code": "TEXT",
        "login_time": "TEXT",
        "logout_time": "TEXT",
        "idle_seconds": "INTEGER",
        "user_agent": "TEXT",
        "created_at": "TEXT",
    })


def ensure_security_schema(force: bool = False) -> None:
    global _SECURITY_SCHEMA_READY
    if _SECURITY_SCHEMA_READY and not force:
        return
    execute("""
    CREATE TABLE IF NOT EXISTS security_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        employee_id TEXT,
        display_name TEXT,
        email TEXT,
        is_active INTEGER DEFAULT 1,
        force_password_change INTEGER DEFAULT 0,
        last_login_at TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    execute("""
    CREATE TABLE IF NOT EXISTS security_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_code TEXT UNIQUE NOT NULL,
        role_name TEXT NOT NULL,
        role_name_en TEXT,
        description TEXT,
        is_system_role INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    execute("""
    CREATE TABLE IF NOT EXISTS security_user_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        role_code TEXT NOT NULL,
        created_at TEXT,
        UNIQUE(username, role_code)
    )
    """)
    execute("""
    CREATE TABLE IF NOT EXISTS security_module_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_code TEXT NOT NULL,
        module_code TEXT NOT NULL,
        module_no TEXT,
        module_name TEXT,
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
        UNIQUE(role_code, module_code)
    )
    """)
    execute("""
    CREATE TABLE IF NOT EXISTS security_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        note TEXT,
        updated_at TEXT
    )
    """)
    execute("""
    CREATE TABLE IF NOT EXISTS security_login_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        display_name TEXT,
        event_type TEXT,
        result TEXT,
        message TEXT,
        module_code TEXT,
        login_time TEXT,
        logout_time TEXT,
        idle_seconds INTEGER,
        user_agent TEXT,
        created_at TEXT
    )
    """)
    _migrate_security_schema_columns()
    seed_security_defaults()

    # V3.40: login page must stay lightweight.
    # Do NOT import permission_service or restore full permission matrices here;
    # that can scan permanent files / DB and make the login page spin forever.
    # auth_users are restored lazily only after a user submits credentials.
    _SECURITY_SCHEMA_READY = True


def _role_perm_template(role_code: str, module_code: str) -> dict[str, int]:
    all_true = {c: 1 for c in PERMISSION_COLUMNS}
    none = {c: 0 for c in PERMISSION_COLUMNS}
    view_only = {**none, "can_view": 1}

    if role_code == "admin":
        return all_true

    if role_code == "manager":
        p = view_only.copy()
        p.update({"can_edit": 1, "can_export": 1})
        if module_code in ["03_work_orders", "04_employees"]:
            p.update({"can_create": 1, "can_import": 1})
        if module_code == "09_persistence":
            p.update({"can_backup": 1})
        if module_code in ["10_permissions"]:
            return none
        return p

    if role_code == "leader":
        if module_code == "01_time_record":
            return {**none, "can_view": 1, "can_create": 1, "can_edit": 1}
        if module_code in ["02_history", "04_employees", "07_missing", "08_daily_hours"]:
            return {**view_only, "can_edit": 1 if module_code == "04_employees" else 0, "can_export": 1}
        if module_code in ["03_work_orders", "05_analysis"]:
            return view_only
        return none

    if role_code == "operator":
        if module_code == "01_time_record":
            return {**none, "can_view": 1, "can_create": 1, "can_edit": 1}
        if module_code in ["02_history", "08_daily_hours"]:
            return view_only
        return none

    if role_code == "viewer":
        if module_code in ["05_analysis", "07_missing", "08_daily_hours"]:
            return view_only
        return none

    if role_code == "auditor":
        if module_code in ["02_history", "06_logs", "11_login_logs"]:
            return {**view_only, "can_export": 1}
        return none

    return none


def seed_security_defaults() -> None:
    now = _now()
    for role_code, role_name, role_en in ROLES:
        execute("""
            INSERT OR IGNORE INTO security_roles
            (role_code, role_name, role_name_en, description, is_system_role, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (role_code, role_name, role_en, role_en, now, now))

    # V6: older SQLite files may not yet contain can_backup/can_restore/can_manage.
    # Seed with adaptive columns so login/home never crashes during Reboot App.
    _migrate_security_schema_columns()
    for m in MODULES:
        for role_code, _, _ in ROLES:
            p = _role_perm_template(role_code, m["module_code"])
            _seed_security_permission_adaptive(role_code, m, p, now)

    for username, password, display_name, role_code in DEFAULT_USERS:
        existing = query_one("SELECT username FROM security_users WHERE username=?", (username,))
        if not existing:
            execute("""
                INSERT OR IGNORE INTO security_users
                (username, password_hash, display_name, is_active, force_password_change, created_at, updated_at)
                VALUES (?, ?, ?, 1, 1, ?, ?)
            """, (username, hash_password(password), display_name, now, now))
        execute("""
            INSERT OR IGNORE INTO security_user_roles (username, role_code, created_at)
            VALUES (?, ?, ?)
        """, (username, role_code, now))

    execute("""
        INSERT OR IGNORE INTO security_settings (setting_key, setting_value, note, updated_at)
        VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
    """, (str(DEFAULT_IDLE_MINUTES), now))



def _read_idle_timeout_from_files() -> int | None:
    """Read idle timeout from permanent JSON files first.

    SQLite on Streamlit Cloud can be rebuilt after GitHub deploy.  These JSON
    files are committed as permanent settings, so the configured value will not
    fall back to 15 minutes after update/relogin.
    """
    for path in IDLE_TIMEOUT_FILES:
        try:
            if not path.exists() or path.stat().st_size <= 0:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("idle_timeout_minutes") or data.get("setting_value")
            if raw not in (None, ""):
                return max(1, int(float(raw)))
        except Exception:
            continue
    return None


def _write_idle_timeout_files(minutes: int) -> None:
    payload = {
        "idle_timeout_minutes": int(minutes),
        "updated_at": _now(),
        "note": "閒置自動登出分鐘數永久設定；GitHub 更新或 SQLite 重建後優先讀取此檔。",
    }
    for path in IDLE_TIMEOUT_FILES:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

def get_idle_timeout_minutes() -> int:
    """讀取閒置登出設定，優先讀永久 JSON，再回退 SQLite。"""
    cache = st.session_state.get("_spt_idle_timeout_cache")
    now_ts = time.time()
    if cache and now_ts - float(cache.get("ts", 0)) < _PERMISSION_CACHE_TTL_SECONDS:
        return int(cache.get("minutes", DEFAULT_IDLE_MINUTES))
    ensure_security_schema()
    minutes = _read_idle_timeout_from_files()
    if minutes is None:
        minutes = DEFAULT_IDLE_MINUTES
        for table in ("auth_security_settings", "security_settings"):
            try:
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    minutes = int(float(row["setting_value"]))
                    break
            except Exception:
                pass
    minutes = max(1, int(minutes))
    st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": now_ts}
    return minutes

def set_idle_timeout_minutes(minutes: int) -> None:
    """Write idle timeout to both runtime and permission tables."""
    ensure_security_schema()
    minutes = max(1, int(minutes))
    for table in ("security_settings", "auth_security_settings"):
        try:
            execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    note TEXT,
                    updated_at TEXT
                )
            """)
            execute(f"""
                INSERT INTO {table} (setting_key, setting_value, note, updated_at)
                VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (str(minutes), _now()))
        except Exception:
            pass
    _write_idle_timeout_files(minutes)
    st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": 0}


def log_security_event(username: str | None, event_type: str, result: str, message: str = "", module_code: str = "", idle_seconds: int | None = None) -> None:
    try:
        execute("""
            INSERT INTO security_login_logs
            (username, display_name, event_type, result, message, module_code, login_time, logout_time, idle_seconds, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            username or "",
            st.session_state.get("auth_display_name", ""),
            event_type,
            result,
            message,
            module_code,
            _now() if event_type == "LOGIN" else None,
            _now() if event_type in ["LOGOUT", "AUTO_LOGOUT", "POST_RECORD_LOGOUT"] else None,
            idle_seconds,
            "streamlit",
            _now(),
        ))
    except Exception:
        pass


def _user_roles(username: str) -> list[str]:
    df = query_df("SELECT role_code FROM security_user_roles WHERE username=?", (username,))
    if df.empty:
        return []
    return df["role_code"].dropna().astype(str).tolist()



def _ensure_auth_users_schema_lightweight() -> None:
    """Create only auth tables needed by login; no full permission rebuild."""
    try:
        execute("""
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
        execute("""
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
    except Exception:
        pass


_AUTH_LIGHT_RESTORE_DONE = False


def _best_local_auth_tables() -> dict[str, list[dict[str, Any]]]:
    """Find the richest local 10_permissions permanent JSON without GitHub/network."""
    candidates: list[Path] = []
    base = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions"
    for name in ("10_permissions_records.json", "10_permissions_settings.json", "security_settings.json"):
        candidates.append(base / name)
    hist = base / "history"
    try:
        candidates.extend(sorted(hist.glob("10_permissions_records_*.json"), reverse=True))
        candidates.extend(sorted(hist.glob("10_permissions_settings_*.json"), reverse=True))
    except Exception:
        pass
    best: dict[str, list[dict[str, Any]]] = {}
    best_score = -1
    for path in candidates:
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
            users = tables.get("auth_users", []) if isinstance(tables, dict) else []
            perms = tables.get("auth_account_permissions", []) if isinstance(tables, dict) else []
            if not isinstance(users, list):
                users = []
            if not isinstance(perms, list):
                perms = []
            non_default = [u for u in users if str(u.get("note", "")).find("default account") < 0]
            score = len(users) * 1000 + len(non_default) * 100 + len(perms)
            if users and score > best_score:
                best_score = score
                best = {"auth_users": users, "auth_account_permissions": perms}
        except Exception:
            continue
    return best


def _restore_auth_users_lightweight_if_needed(username: str = "") -> None:
    """Lazy local restore for login only; no GitHub, no full module reconciliation."""
    global _AUTH_LIGHT_RESTORE_DONE
    if _AUTH_LIGHT_RESTORE_DONE:
        return
    _AUTH_LIGHT_RESTORE_DONE = True
    _ensure_auth_users_schema_lightweight()
    try:
        count_row = query_one("SELECT COUNT(*) AS c FROM auth_users") or {}
        count = int(count_row.get("c", 0) or 0)
        if count > 6:
            return
    except Exception:
        count = 0
    tables = _best_local_auth_tables()
    users = tables.get("auth_users", [])
    perms = tables.get("auth_account_permissions", [])
    if not users:
        return
    try:
        for u in users:
            if not isinstance(u, dict) or not str(u.get("username", "")).strip():
                continue
            execute("""
                INSERT INTO auth_users
                (username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,last_login_at,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash=excluded.password_hash,
                    password_hint=excluded.password_hint,
                    employee_id=excluded.employee_id,
                    display_name=excluded.display_name,
                    email=excluded.email,
                    role_code=excluded.role_code,
                    is_active=excluded.is_active,
                    force_password_change=excluded.force_password_change,
                    last_login_at=excluded.last_login_at,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (
                str(u.get("username", "")).strip(),
                str(u.get("password_hash", "") or ""),
                str(u.get("password_hint", "") or ""),
                str(u.get("employee_id", "") or ""),
                str(u.get("display_name", "") or u.get("username", "")),
                str(u.get("email", "") or ""),
                str(u.get("role_code", "operator") or "operator"),
                int(u.get("is_active", 1) or 0),
                int(u.get("force_password_change", 0) or 0),
                str(u.get("last_login_at", "") or ""),
                str(u.get("note", "") or ""),
                str(u.get("created_at", "") or _now()),
                str(u.get("updated_at", "") or _now()),
            ))
        for r in perms:
            if not isinstance(r, dict) or not str(r.get("username", "")).strip():
                continue
            execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username,module_code) DO UPDATE SET
                    module_name_zh=excluded.module_name_zh,
                    module_name_en=excluded.module_name_en,
                    can_view=excluded.can_view,
                    can_create=excluded.can_create,
                    can_edit=excluded.can_edit,
                    can_delete=excluded.can_delete,
                    can_import=excluded.can_import,
                    can_export=excluded.can_export,
                    can_backup=excluded.can_backup,
                    can_restore=excluded.can_restore,
                    can_manage=excluded.can_manage,
                    updated_at=excluded.updated_at
            """, (
                str(r.get("username", "")).strip(),
                str(r.get("module_code", "") or ""),
                str(r.get("module_name_zh", "") or ""),
                str(r.get("module_name_en", "") or ""),
                int(r.get("can_view", 0) or 0),
                int(r.get("can_create", 0) or 0),
                int(r.get("can_edit", 0) or 0),
                int(r.get("can_delete", 0) or 0),
                int(r.get("can_import", 0) or 0),
                int(r.get("can_export", 0) or 0),
                int(r.get("can_backup", 0) or 0),
                int(r.get("can_restore", 0) or 0),
                int(r.get("can_manage", 0) or 0),
                str(r.get("updated_at", "") or _now()),
            ))
    except Exception:
        pass


def _auth_role_for_username(username: str) -> str:
    """Return the authoritative single role from auth_users.

    10｜權限管理的帳號主檔 auth_users.role_code 是唯一角色來源。
    舊版 security_user_roles 只保留相容用途，不可讓舊角色與新角色合併成
    admin, operator，也不可讓 admin 顯示未設定角色。
    """
    try:
        _restore_auth_users_lightweight_if_needed(username)
        row = query_one("SELECT role_code FROM auth_users WHERE username=? AND COALESCE(is_active, 0)=1", (username,))
        role = str((row or {}).get("role_code", "") or "").strip()
        return role
    except Exception:
        return ""


def _single_authoritative_roles(username: str, fallback_row: dict[str, Any] | None = None) -> list[str]:
    role = _auth_role_for_username(username)
    if not role and fallback_row:
        role = str(fallback_row.get("role_code", "") or "").strip()
    if not role:
        legacy = _user_roles(username)
        role = str(legacy[0]).strip() if legacy else ""
    return [role] if role else []


def _is_admin_user(username: str | None = None, roles: list[str] | None = None) -> bool:
    username = username or st.session_state.get("auth_username", "")
    clean_roles = [str(r).strip() for r in (roles or st.session_state.get("auth_roles", []) or []) if str(r).strip()]
    if "admin" in clean_roles:
        return True
    return _auth_role_for_username(str(username)) == "admin"


def _repair_session_role_from_account_master() -> list[str]:
    username = st.session_state.get("auth_username", "")
    if not username:
        return []
    roles = _single_authoritative_roles(username)
    if roles:
        st.session_state["auth_roles"] = roles
    return roles


def get_current_user() -> dict[str, Any] | None:
    if not st.session_state.get("auth_logged_in"):
        return None
    roles = st.session_state.get("auth_roles", []) or []
    if not roles:
        roles = _repair_session_role_from_account_master()
    return {
        "username": st.session_state.get("auth_username", ""),
        "display_name": st.session_state.get("auth_display_name", ""),
        "roles": roles,
    }


def _auth_user_row(username: str) -> dict[str, Any] | None:
    """Read the V1.29+ account master row used by 10｜權限管理."""
    try:
        _restore_auth_users_lightweight_if_needed(username)
        return query_one("SELECT * FROM auth_users WHERE username=?", (username,))
    except Exception:
        return None


def _sync_auth_user_to_security_runtime(auth_row: dict[str, Any]) -> None:
    """Keep legacy security_users/security_user_roles in sync for older pages.

    登入以 auth_users 為優先來源，但同步回舊表可讓舊版查詢頁、登入紀錄
    或未改到的模組仍能讀到同一個帳號，避免雙帳號表再次分裂。
    """
    try:
        username = str(auth_row.get("username", "")).strip()
        if not username:
            return
        now = _now()
        execute("""
            INSERT INTO security_users
            (username, password_hash, employee_id, display_name, email, is_active, force_password_change, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                employee_id=excluded.employee_id,
                display_name=excluded.display_name,
                email=excluded.email,
                is_active=excluded.is_active,
                force_password_change=excluded.force_password_change,
                updated_at=excluded.updated_at
        """, (
            username,
            auth_row.get("password_hash") or "",
            auth_row.get("employee_id") or "",
            auth_row.get("display_name") or username,
            auth_row.get("email") or "",
            int(auth_row.get("is_active", 1) or 0),
            int(auth_row.get("force_password_change", 0) or 0),
            now,
            now,
        ))
        role_code = str(auth_row.get("role_code", "") or "").strip()
        # auth_users.role_code is authoritative; clear old legacy roles first to avoid admin, operator residues.
        execute("DELETE FROM security_user_roles WHERE username=?", (username,))
        if role_code:
            execute("INSERT OR IGNORE INTO security_user_roles (username, role_code, created_at) VALUES (?, ?, ?)", (username, role_code, now))
    except Exception:
        pass


def authenticate(username: str, password: str) -> tuple[bool, str]:
    ensure_security_schema()
    username = (username or "").strip()

    # V1.77：優先讀取「10｜權限管理」使用的 auth_users。
    # 舊版登入只讀 security_users，導致 spt142 這類在權限管理建立的帳號無法登入。
    auth_row = _auth_user_row(username)
    row = auth_row or query_one("SELECT * FROM security_users WHERE username=?", (username,))

    if not row:
        log_security_event(username, "LOGIN", "FAIL", "帳號不存在")
        return False, "帳號或密碼錯誤。"
    if not int(row.get("is_active", 0)):
        log_security_event(username, "LOGIN", "FAIL", "帳號停用")
        return False, "帳號已停用。"
    if not verify_password(password, row.get("password_hash")):
        log_security_event(username, "LOGIN", "FAIL", "密碼錯誤")
        return False, "帳號或密碼錯誤。"

    if auth_row:
        _sync_auth_user_to_security_runtime(auth_row)

    roles = _single_authoritative_roles(username, row)

    st.session_state["auth_logged_in"] = True
    st.session_state["auth_username"] = username
    st.session_state["auth_display_name"] = row.get("display_name") or username
    st.session_state["auth_employee_id"] = row.get("employee_id") or ""
    st.session_state["auth_roles"] = roles
    clear_permission_cache(username)
    _load_permission_cache(username, roles, force=True)
    now_ts = time.time()
    st.session_state["auth_login_ts"] = now_ts
    st.session_state["auth_last_activity_ts"] = now_ts
    if auth_row:
        try:
            execute("UPDATE auth_users SET last_login_at=?, updated_at=? WHERE username=?", (_now(), _now(), username))
        except Exception:
            pass
    try:
        execute("UPDATE security_users SET last_login_at=?, updated_at=? WHERE username=?", (_now(), _now(), username))
    except Exception:
        pass
    log_security_event(username, "LOGIN", "SUCCESS", f"roles={','.join(roles)}")
    return True, "登入成功。"


def logout(reason: str = "使用者登出") -> None:
    username = st.session_state.get("auth_username", "")
    event_type = "LOGOUT"
    if "閒置" in reason:
        event_type = "AUTO_LOGOUT"
    if "完成工時" in reason:
        event_type = "POST_RECORD_LOGOUT"
    log_security_event(username, event_type, "SUCCESS", reason)
    clear_permission_cache(username)
    for k in list(st.session_state.keys()):
        if k.startswith("auth_") or k.startswith("post_record_") or k.startswith("_spt_idle_timeout_cache"):
            del st.session_state[k]


def _load_permission_cache(username: str, roles: list[str], force: bool = False) -> dict[str, dict[str, bool]]:
    """一次載入目前帳號所有模組權限，避免每個模組 / 按鈕都查 SQL。

    優先使用 V1.29 帳號級 auth_account_permissions；若尚未設定，回退到 V1.28 role-based security_module_permissions。
    """
    cache_key = f"_spt_perm_cache_{username}"
    now_ts = time.time()
    cached = st.session_state.get(cache_key)
    if cached and not force and now_ts - float(cached.get("ts", 0)) < _PERMISSION_CACHE_TTL_SECONDS:
        return cached.get("data", {})

    ensure_security_schema()
    data: dict[str, dict[str, bool]] = {}

    if _is_admin_user(username, roles):
        for m in MODULES:
            data[m["module_code"]] = {c: True for c in PERMISSION_COLUMNS}
        st.session_state[cache_key] = {"ts": now_ts, "data": data}
        return data

    # V1.29 帳號級權限表：module_code 為 01, 02...，需映射成 01_time_record...
    try:
        df_account = query_df("""
            SELECT p.*
            FROM auth_account_permissions p
            JOIN auth_users u ON u.username = p.username
            WHERE p.username=? AND COALESCE(u.is_active, 0)=1
        """, (username,))
    except Exception:
        df_account = pd.DataFrame()

    if not df_account.empty:
        for _, r in df_account.iterrows():
            no = str(r.get("module_code", "")).zfill(2)
            code = MODULE_NO_TO_CODE.get(no, no)
            row = {c: bool(int(r.get(c, 0) or 0)) for c in PERMISSION_COLUMNS}
            if row.get("can_manage"):
                row = {c: True for c in PERMISSION_COLUMNS}
            data[code] = row
        st.session_state[cache_key] = {"ts": now_ts, "data": data}
        return data

    # V1.28 角色權限表 fallback
    if roles:
        placeholders = ",".join(["?"] * len(roles))
        try:
            df_role = query_df(f"""
                SELECT module_code,
                       MAX(can_view) AS can_view, MAX(can_create) AS can_create, MAX(can_edit) AS can_edit,
                       MAX(can_delete) AS can_delete, MAX(can_import) AS can_import, MAX(can_export) AS can_export,
                       MAX(can_backup) AS can_backup, MAX(can_restore) AS can_restore, MAX(can_manage) AS can_manage
                FROM security_module_permissions
                WHERE role_code IN ({placeholders})
                GROUP BY module_code
            """, tuple(roles))
        except Exception:
            df_role = pd.DataFrame()
        for _, r in df_role.iterrows():
            code = str(r.get("module_code", ""))
            row = {c: bool(int(r.get(c, 0) or 0)) for c in PERMISSION_COLUMNS}
            if row.get("can_manage"):
                row = {c: True for c in PERMISSION_COLUMNS}
            data[code] = row

    st.session_state[cache_key] = {"ts": now_ts, "data": data}
    return data


def clear_permission_cache(username: str | None = None) -> None:
    """權限儲存後可呼叫；也會在登入/登出時自動清掉。"""
    keys = list(st.session_state.keys())
    for k in keys:
        if k.startswith("_spt_perm_cache_") and (username is None or k.endswith(str(username))):
            st.session_state.pop(k, None)


def check_permission(module_code: str, action: str = "can_view") -> bool:
    user = get_current_user()
    if not user:
        return False
    roles = user.get("roles", [])
    if _is_admin_user(user.get("username", ""), roles):
        return True
    if action not in PERMISSION_COLUMNS:
        action = "can_view"
    perms = _load_permission_cache(user["username"], roles)
    row = perms.get(module_code) or perms.get(MODULE_CODE_TO_NO.get(module_code, module_code), {})
    if row.get("can_manage"):
        return True
    return bool(row.get(action, False))


def render_login_form() -> None:
    """Render a premium welcome login page without changing authentication logic."""
    logo_b64 = ""
    for _p in [PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png", PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png"]:
        try:
            if _p.exists():
                logo_b64 = base64.b64encode(_p.read_bytes()).decode("utf-8")
                break
        except Exception:
            pass
    logo_html = f'<div class="spt-login-logo"><img src="data:image/png;base64,{logo_b64}" /></div>' if logo_b64 else '<div class="spt-login-logo spt-login-logo-text">SUPER PLUS TECH</div>'
    st.markdown(
        """
<style>
/* ===== V2.25 Premium Welcome Login Page - Larger Bright Typography ===== */
[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
.block-container {
  max-width: 1180px !important;
  padding-top: 3.1rem !important;
}
.spt-welcome-shell {
  position: relative;
  overflow: hidden;
  border-radius: 30px;
  padding: 1px;
  background:
    linear-gradient(135deg, rgba(96, 239, 255, .95), rgba(60, 100, 255, .42), rgba(255, 255, 255, .12));
  box-shadow:
    0 0 42px rgba(0, 213, 255, .28),
    0 24px 80px rgba(0, 0, 0, .42);
  margin-bottom: 1.1rem;
}
.spt-welcome-panel {
  position: relative;
  border-radius: 29px;
  padding: 34px 36px;
  background:
    radial-gradient(circle at 14% 14%, rgba(73, 231, 255, .30), transparent 34%),
    radial-gradient(circle at 92% 18%, rgba(111, 95, 255, .24), transparent 32%),
    linear-gradient(145deg, rgba(6, 18, 36, .96), rgba(9, 29, 56, .92));
  border: 1px solid rgba(157, 236, 255, .25);
}
.spt-welcome-panel::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(132, 232, 255, .055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(132, 232, 255, .055) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: linear-gradient(90deg, rgba(0,0,0,.85), rgba(0,0,0,.18));
  pointer-events: none;
}
.spt-welcome-panel::after {
  content: "";
  position: absolute;
  width: 260px;
  height: 260px;
  right: -80px;
  top: -80px;
  border: 1px solid rgba(148, 238, 255, .22);
  border-radius: 999px;
  box-shadow: inset 0 0 32px rgba(0, 218, 255, .16), 0 0 48px rgba(0, 218, 255, .15);
  animation: spt_login_orbit 5.6s ease-in-out infinite alternate;
}
@keyframes spt_login_orbit {
  from { transform: translate(0,0) scale(.96); opacity: .52; }
  to { transform: translate(-18px,18px) scale(1.04); opacity: .92; }
}
.spt-login-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(330px, .78fr);
  gap: 28px;
  align-items: stretch;
}
.spt-brand-kicker {
  display: inline-flex;
  gap: 10px;
  align-items: center;
  padding: 8px 13px;
  border: 1px solid rgba(148, 238, 255, .38);
  border-radius: 999px;
  color: #bff7ff;
  background: rgba(5, 25, 47, .64);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .16em;
  text-transform: uppercase;
  box-shadow: 0 0 24px rgba(0, 217, 255, .18);
}
.spt-login-logo {
  width: 260px;
  max-width: 70%;
  padding: 10px 18px;
  margin: 18px 0 10px 0;
  border-radius: 18px;
  background: rgba(255,255,255,.96);
  box-shadow: 0 0 24px rgba(93,238,255,.34), 0 18px 42px rgba(0,0,0,.30);
}
.spt-login-logo img { width: 100%; display: block; height: auto; }
.spt-login-logo-text { color: #061423; font-weight: 1000; letter-spacing: .14em; }
.spt-brand-dot {
  width: 9px;
  height: 9px;
  border-radius: 99px;
  background: #6ff3ff;
  box-shadow: 0 0 16px #6ff3ff, 0 0 30px rgba(111,243,255,.58);
  animation: spt_login_pulse 1.8s ease-in-out infinite;
}
@keyframes spt_login_pulse {
  0%,100% { transform: scale(.78); opacity:.55; }
  50% { transform: scale(1.2); opacity:1; }
}
.spt-login-title {
  margin: 22px 0 6px 0;
  color: #f4fdff;
  font-size: clamp(42px, 5.8vw, 74px);
  line-height: 1.02;
  font-weight: 950;
  letter-spacing: -.035em;
  text-shadow: 0 0 18px rgba(255,255,255,.42), 0 0 34px rgba(95, 229, 255, .48);
}
.spt-login-subtitle {
  margin-top: 14px;
  max-width: 680px;
  color: rgba(220, 249, 255, .88);
  font-size: 21px;
  line-height: 1.72;
  font-weight: 780;
}
.spt-login-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 28px;
}
.spt-login-metric {
  border: 1px solid rgba(147, 231, 255, .24);
  border-radius: 18px;
  padding: 14px 16px;
  background: linear-gradient(180deg, rgba(255,255,255,.10), rgba(255,255,255,.035));
  box-shadow: inset 0 0 18px rgba(124, 230, 255, .07);
}
.spt-login-metric b {
  display: block;
  color: #ffffff;
  font-size: 22px;
  line-height: 1;
}
.spt-login-metric span {
  display: block;
  margin-top: 8px;
  color: rgba(209, 246, 255, .72);
  font-size: 12px;
  letter-spacing: .08em;
}
.spt-form-card {
  border-radius: 24px;
  padding: 24px 24px 22px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.16), rgba(255,255,255,.065));
  border: 1px solid rgba(181, 242, 255, .32);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.18),
    0 18px 44px rgba(0,0,0,.30),
    0 0 30px rgba(0, 221, 255, .10);
  backdrop-filter: blur(14px);
}
.spt-form-title {
  color: #f7feff;
  font-size: 33px;
  font-weight: 950;
  line-height: 1.2;
  margin-bottom: 4px;
}
.spt-form-caption {
  color: rgba(219, 249, 255, .72);
  font-size: 16px;
  line-height: 1.65;
  margin-bottom: 16px;
}
.spt-login-note {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 16px;
  color: rgba(233, 252, 255, .76);
  background: rgba(4, 19, 36, .52);
  border: 1px solid rgba(155, 233, 255, .16);
  font-size: 15px;
  line-height: 1.7;
}
/* Login-only Streamlit widgets */
div[data-testid="stForm"] {
  border: 0 !important;
  background: transparent !important;
  padding: 0 !important;
}
div[data-testid="stForm"] label p,
div[data-testid="stTextInput"] label p {
  color: #effdff !important;
  font-weight: 950 !important;
  letter-spacing: .065em !important;
  font-size: 17px !important;
  text-shadow: 0 0 14px rgba(90, 235, 255, .36) !important;
}
div[data-testid="stForm"] input,
div[data-testid="stTextInput"] input,
div[data-baseweb="input"] input {
  background: linear-gradient(180deg, rgba(16, 29, 63, .98), rgba(7, 18, 42, .98)) !important;
  color: #f3feff !important;
  -webkit-text-fill-color: #f3feff !important;
  caret-color: #66f6ff !important;
  border: 1px solid rgba(125, 238, 255, .92) !important;
  border-radius: 15px !important;
  min-height: 54px !important;
  font-size: 20px !important;
  font-weight: 900 !important;
  letter-spacing: .035em !important;
  text-shadow: 0 0 10px rgba(105, 236, 255, .25) !important;
  box-shadow: inset 0 0 18px rgba(90, 238, 255, .10), 0 0 0 1px rgba(111, 236, 255, .12), 0 10px 28px rgba(0,0,0,.22) !important;
}
div[data-testid="stForm"] input::placeholder,
div[data-testid="stTextInput"] input::placeholder,
div[data-baseweb="input"] input::placeholder {
  color: rgba(225, 250, 255, .62) !important;
  -webkit-text-fill-color: rgba(225, 250, 255, .62) !important;
}
div[data-testid="stForm"] input:focus,
div[data-testid="stTextInput"] input:focus,
div[data-baseweb="input"] input:focus {
  border-color: #62f5ff !important;
  box-shadow: inset 0 0 20px rgba(90, 238, 255, .16), 0 0 0 3px rgba(84, 236, 255, .26), 0 0 34px rgba(84,236,255,.34) !important;
}
div[data-testid="stForm"] button[kind="primary"],
div[data-testid="stForm"] button {
  min-height: 56px !important;
  border-radius: 16px !important;
  border: 1px solid rgba(150, 245, 255, .88) !important;
  background: linear-gradient(135deg, #eaffff, #88efff 45%, #b7c7ff) !important;
  color: #031523 !important;
  font-size: 18px !important;
  font-weight: 950 !important;
  letter-spacing: .08em !important;
  box-shadow: 0 0 28px rgba(75, 235, 255, .36), 0 12px 32px rgba(0,0,0,.24) !important;
  transition: transform .16s ease, box-shadow .16s ease !important;
}
div[data-testid="stForm"] button:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 0 34px rgba(75, 235, 255, .48), 0 16px 38px rgba(0,0,0,.28) !important;
}

/* V2.29 login input typed text final override: force bright typed text for all Streamlit/BaseWeb input layers. */
section[data-testid="stSidebar"] input,
html body div[data-testid="stForm"] div[data-testid="stTextInput"] input,
html body div[data-testid="stTextInput"] input,
html body div[data-baseweb="input"] input,
html body input[type="text"],
html body input[type="password"] {
  background: linear-gradient(180deg, rgba(16, 29, 63, .98), rgba(7, 18, 42, .98)) !important;
  background-color: rgba(10, 22, 52, .98) !important;
  color: #f7feff !important;
  -webkit-text-fill-color: #f7feff !important;
  caret-color: #66f6ff !important;
  opacity: 1 !important;
  text-shadow: 0 0 12px rgba(108, 244, 255, .45) !important;
  font-size: 20px !important;
  font-weight: 950 !important;
}
html body div[data-testid="stForm"] div[data-baseweb="input"],
html body div[data-testid="stTextInput"] div[data-baseweb="input"],
html body div[data-baseweb="input"],
html body div[data-testid="stForm"] div[data-baseweb="base-input"],
html body div[data-testid="stTextInput"] div[data-baseweb="base-input"],
html body div[data-baseweb="base-input"] {
  background: linear-gradient(180deg, rgba(16, 29, 63, .98), rgba(7, 18, 42, .98)) !important;
  background-color: rgba(10, 22, 52, .98) !important;
  color: #f7feff !important;
  -webkit-text-fill-color: #f7feff !important;
}
html body div[data-testid="stForm"] input::placeholder,
html body div[data-testid="stTextInput"] input::placeholder,
html body input::placeholder {
  color: rgba(226, 252, 255, .78) !important;
  -webkit-text-fill-color: rgba(226, 252, 255, .78) !important;
  opacity: 1 !important;
}
html body div[data-testid="stForm"] input:autofill,
html body div[data-testid="stTextInput"] input:autofill,
html body div[data-baseweb="input"] input:autofill,
html body input[type="text"]:autofill,
html body input[type="password"]:autofill,
html body div[data-testid="stForm"] input:-webkit-autofill,
html body div[data-testid="stTextInput"] input:-webkit-autofill,
html body div[data-baseweb="input"] input:-webkit-autofill,
html body input[type="text"]:-webkit-autofill,
html body input[type="password"]:-webkit-autofill,
html body div[data-testid="stForm"] input:-webkit-autofill:hover,
html body div[data-testid="stTextInput"] input:-webkit-autofill:hover,
html body div[data-baseweb="input"] input:-webkit-autofill:hover,
html body div[data-testid="stForm"] input:-webkit-autofill:focus,
html body div[data-testid="stTextInput"] input:-webkit-autofill:focus,
html body div[data-baseweb="input"] input:-webkit-autofill:focus {
  -webkit-text-fill-color: #f7feff !important;
  color: #f7feff !important;
  caret-color: #66f6ff !important;
  transition: background-color 999999s ease-in-out 0s !important;
  box-shadow: inset 0 0 0 1000px rgba(10, 22, 52, .98), 0 0 0 2px rgba(97, 244, 255, .40) !important;
}
/* Keep labels bright without overriding the actual input value back to dark. */
html body div[data-testid="stTextInput"] label *,
html body div[data-testid="stForm"] label * {
  color: #f2feff !important;
  -webkit-text-fill-color: #f2feff !important;
}

@media (max-width: 900px) {
  .spt-login-grid { grid-template-columns: 1fr; }
  .spt-login-metrics { grid-template-columns: 1fr; }
  .spt-welcome-panel { padding: 24px 18px; }
}
</style>
<div class="spt-welcome-shell">
  <div class="spt-welcome-panel">
    <div class="spt-login-grid">
      <div>
        <div class="spt-brand-kicker"><span class="spt-brand-dot"></span>SPT Manufacturing Intelligence</div>
        {logo_html}
        <div class="spt-login-title">歡迎來到<br>超慧科技製造部<br>工時紀錄系統</div>
        <div class="spt-login-subtitle">
          以權限控管、即時工時、歷史追溯與永久備份為核心，打造製造現場可稽核、可分析、可持續升級的智慧工時管理平台。
        </div>
        <div class="spt-login-metrics">
          <div class="spt-login-metric"><b>13</b><span>CORE MODULES</span></div>
          <div class="spt-login-metric"><b>24H</b><span>TIME TRACE</span></div>
          <div class="spt-login-metric"><b>∞</b><span>PERSISTENCE</span></div>
        </div>
      </div>
      <div class="spt-form-card">
        <div class="spt-form-title">⛨ 安全登入</div>
        <div class="spt-form-caption">請輸入個人帳號密碼。系統將依帳號權限載入可操作模組。</div>
""".replace("{logo_html}", logo_html),
        unsafe_allow_html=True,
    )
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("帳號 / Username", placeholder="請輸入帳號")
        password = st.text_input("密碼 / Password", type="password", placeholder="請輸入密碼")
        submitted = st.form_submit_button("⛨ 進入系統 / Secure Login", use_container_width=True)
    st.markdown(
        """
        <div class="spt-login-note">
          ▣ 登入後會自動套用模組權限與閒置登出設定。<br>
          ⧉ 所有重要異動將保留操作紀錄，便於後續稽核與追蹤。
        </div>
      </div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if submitted:
        ok, msg = authenticate(username, password)
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)


def render_idle_watchdog() -> None:
    seconds = get_idle_timeout_minutes() * 60
    # 前端偵測無滑鼠/鍵盤活動後重新整理，後端在下一次 rerun 時判斷並登出。
    components.html(
        f"""
<script>
(function() {{
  const idleMs = {seconds * 1000};
  let timer = null;
  function resetTimer() {{
    if (timer) clearTimeout(timer);
    timer = setTimeout(function() {{
      try {{ window.parent.location.reload(); }} catch(e) {{ window.location.reload(); }}
    }}, idleMs + 3000);
  }}
  ['mousemove','mousedown','keydown','scroll','touchstart','click'].forEach(function(evt) {{
    window.parent.document.addEventListener(evt, resetTimer, true);
  }});
  resetTimer();
}})();
</script>
""",
        height=0,
        width=0,
    )


def _check_idle_timeout() -> None:
    if not st.session_state.get("auth_logged_in"):
        return
    timeout = get_idle_timeout_minutes() * 60
    now_ts = time.time()
    last_ts = float(st.session_state.get("auth_last_activity_ts", now_ts))
    idle_seconds = int(now_ts - last_ts)
    if idle_seconds > timeout:
        logout(f"閒置超過 {int(timeout/60)} 分鐘，自動登出")
        log_security_event(st.session_state.get("auth_username", ""), "AUTO_LOGOUT", "SUCCESS", "閒置自動登出", idle_seconds=idle_seconds)
        st.warning("帳號已因閒置逾時自動登出，請重新登入。")
        render_login_form()
        st.stop()
    st.session_state["auth_last_activity_ts"] = now_ts


def render_user_bar(module_code: str = "") -> None:
    user = get_current_user()
    if not user:
        return
    render_idle_watchdog()
    roles_list = user.get("roles", []) or _repair_session_role_from_account_master()
    roles = ", ".join(roles_list) or "未設定角色"
    display_name = escape(str(user.get("display_name") or user.get("username") or ""))
    username = escape(str(user.get("username") or ""))
    role_text = escape(str(roles))
    idle = int(get_idle_timeout_minutes())

    c1, c2, c3 = st.columns([2.2, 2.2, 1.0])
    with c1:
        st.markdown(
            f"""
<div class="spt-login-pill spt-login-pill-user">
  <div class="spt-login-label">登入帳號 / Login</div>
  <div class="spt-login-value">{display_name} <span>({username})</span></div>
</div>
""",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
<div class="spt-login-pill spt-login-pill-role">
  <div class="spt-login-label">角色 / Idle</div>
  <div class="spt-login-value">{role_text} <span>｜閒置自動登出：{idle} 分鐘</span></div>
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        if st.button("登出 / Logout", use_container_width=True, key=f"logout_{module_code}"):
            logout("使用者手動登出")
            st.rerun()


def require_login(module_code: str = "") -> None:
    ensure_security_schema()
    if not st.session_state.get("auth_logged_in"):
        render_login_form()
        st.stop()
    _check_idle_timeout()
    render_user_bar(module_code)


def require_module_access(module_code: str, action: str = "can_view") -> None:
    require_login(module_code)
    if not check_permission(module_code, action):
        log_security_event(st.session_state.get("auth_username", ""), "PERMISSION_DENIED", "FAIL", f"{module_code}:{action}", module_code)
        st.error("權限不足：你的帳號未被授權使用此模組或功能。")
        st.stop()


def require_permission(module_code: str, action: str = "can_view") -> None:
    """Backward-compatible alias for older pages.

    Some pages imported require_permission while newer pages use
    require_module_access.  Keep both names so permission guarding never
    silently falls back to unprotected access.
    """
    return require_module_access(module_code, action)


def mark_activity() -> None:
    st.session_state["auth_last_activity_ts"] = time.time()


def trigger_post_record_continue_prompt(message: str = "工時紀錄已完成", title: str = "工時紀錄完成") -> None:
    st.session_state["post_record_prompt"] = True
    st.session_state["post_record_message"] = message
    st.session_state["post_record_title"] = title


def render_post_record_continue_prompt() -> None:
    if not st.session_state.get("post_record_prompt"):
        return

    def _content() -> None:
        st.success(st.session_state.get("post_record_message", "工時紀錄已完成"))
        st.markdown("### 是否繼續操作下一筆工時紀錄？")
        st.caption("若選擇不繼續，系統會立即登出目前帳號，避免其他人冒用此帳號記錄工時。")
        c1, c2 = st.columns(2)
        if c1.button("是，繼續記錄 / Continue", use_container_width=True, key="post_continue_yes"):
            st.session_state["post_record_prompt"] = False
            mark_activity()
            st.rerun()
        if c2.button("否，登出帳號 / Logout", use_container_width=True, key="post_continue_no"):
            logout("完成工時後選擇不繼續記錄，自動登出")
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog(f"{st.session_state.get('post_record_title', '工時紀錄完成')} / Record Notice")
        def _dialog():
            _content()
        _dialog()
    else:
        st.warning("工時紀錄已處理，請選擇是否繼續操作下一筆紀錄。")
        _content()


def users_df() -> pd.DataFrame:
    ensure_security_schema()
    users = query_df("SELECT id, username, employee_id, display_name, email, is_active, force_password_change, last_login_at, created_at, updated_at FROM security_users ORDER BY username")
    roles = query_df("SELECT username, role_code FROM security_user_roles ORDER BY username, role_code")
    if not users.empty:
        users["roles"] = users["username"].map(lambda u: ",".join(roles.loc[roles["username"] == u, "role_code"].tolist()) if not roles.empty else "")
    return users


def roles_df() -> pd.DataFrame:
    ensure_security_schema()
    return query_df("SELECT role_code, role_name, role_name_en, description, is_system_role FROM security_roles ORDER BY id")


def permissions_df() -> pd.DataFrame:
    ensure_security_schema()
    return query_df("""
        SELECT role_code, module_no, module_code, module_name, module_name_en,
               can_view, can_create, can_edit, can_delete, can_import, can_export,
               can_backup, can_restore, can_manage, updated_at
        FROM security_module_permissions
        ORDER BY role_code, module_no
    """)


def save_permissions(df: pd.DataFrame) -> None:
    ensure_security_schema()
    now = _now()
    for _, r in df.iterrows():
        role_code = str(r.get("role_code", "")).strip()
        module_code = str(r.get("module_code", "")).strip()
        if not role_code or not module_code:
            continue
        vals = [_bool(r.get(c, 0)) for c in PERMISSION_COLUMNS]
        execute(f"""
            UPDATE security_module_permissions
            SET {', '.join([c+'=?' for c in PERMISSION_COLUMNS])}, updated_at=?
            WHERE role_code=? AND module_code=?
        """, tuple(vals + [now, role_code, module_code]))


def create_or_update_user(username: str, display_name: str, password: str = "", employee_id: str = "", email: str = "", is_active: bool = True, roles: list[str] | None = None) -> None:
    ensure_security_schema()
    username = username.strip()
    if not username:
        raise ValueError("帳號不可空白")
    now = _now()
    existing = query_one("SELECT username FROM security_users WHERE username=?", (username,))
    if existing:
        if password:
            execute("""
                UPDATE security_users
                SET password_hash=?, employee_id=?, display_name=?, email=?, is_active=?, updated_at=?
                WHERE username=?
            """, (hash_password(password), employee_id, display_name, email, _bool(is_active), now, username))
        else:
            execute("""
                UPDATE security_users
                SET employee_id=?, display_name=?, email=?, is_active=?, updated_at=?
                WHERE username=?
            """, (employee_id, display_name, email, _bool(is_active), now, username))
    else:
        if not password:
            password = "ChangeMe@1234"
        execute("""
            INSERT INTO security_users
            (username, password_hash, employee_id, display_name, email, is_active, force_password_change, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (username, hash_password(password), employee_id, display_name or username, email, _bool(is_active), now, now))
    if roles is not None:
        execute("DELETE FROM security_user_roles WHERE username=?", (username,))
        for role_code in roles:
            if role_code:
                execute("INSERT OR IGNORE INTO security_user_roles (username, role_code, created_at) VALUES (?, ?, ?)", (username, role_code, now))


def login_logs_df(limit: int = 1000) -> pd.DataFrame:
    ensure_security_schema()
    return query_df("SELECT * FROM security_login_logs ORDER BY id DESC LIMIT ?", (int(limit),))


# ===== V1.69 persistent security settings override =====
_SECURITY_PERSISTENT_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_security_settings.json"
_SECURITY_MODULE_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json"

def _v169_load_persistent_security_settings() -> dict[str, str]:
    """Load only real security settings from permanent JSON files.

    Some files such as spt_module_settings.json contain full module payloads
    (version/exported_at/tables/table_counts).  Older code treated the whole
    payload as settings, causing garbage keys to appear in security settings.
    """
    data: dict[str, str] = {}
    for path in (_SECURITY_PERSISTENT_FILE, _SECURITY_MODULE_FILE):
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("security_settings")
            if raw is None and isinstance(payload.get("tables"), dict):
                rows = payload.get("tables", {}).get("auth_security_settings") or payload.get("tables", {}).get("security_settings") or []
                if isinstance(rows, list):
                    raw = {str(r.get("setting_key")): str(r.get("setting_value")) for r in rows if isinstance(r, dict) and r.get("setting_key")}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if v is not None and str(k) in {"idle_timeout_minutes", "ask_continue_after_record"}:
                        data[str(k)] = str(v)
        except Exception:
            continue
    return data

def _v169_write_persistent_security_settings(settings: dict[str, str]) -> None:
    try:
        now = _now()
        payload = {"version": "V1.69", "updated_at": now, "security_settings": dict(settings)}
        for path in (_SECURITY_PERSISTENT_FILE, _SECURITY_MODULE_FILE):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_idle_timeout_minutes() -> int:  # type: ignore[override]
    """Read idle timeout from session, DB and permanent JSON.

    Priority: current session cache -> permanent JSON -> DB -> default.
    Permanent JSON is used so logout/redeploy does not revert to 15 minutes.
    """
    try:
        cache = st.session_state.get("_spt_idle_timeout_cache")
        now_ts = time.time()
        if cache and now_ts - float(cache.get("ts", 0)) < 60:
            return max(1, int(cache.get("minutes", DEFAULT_IDLE_MINUTES)))
    except Exception:
        pass

    ensure_security_schema()
    minutes = DEFAULT_IDLE_MINUTES
    file_settings = _v169_load_persistent_security_settings()
    if file_settings.get("idle_timeout_minutes") not in (None, ""):
        try:
            minutes = int(float(file_settings["idle_timeout_minutes"]))
        except Exception:
            minutes = DEFAULT_IDLE_MINUTES
    else:
        for table in ("auth_security_settings", "security_settings"):
            try:
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    minutes = int(float(row["setting_value"]))
                    break
            except Exception:
                pass
    minutes = max(1, int(minutes))
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
    except Exception:
        pass
    return minutes

def set_idle_timeout_minutes(minutes: int) -> None:  # type: ignore[override]
    """Write idle timeout to runtime DB and permanent JSON."""
    ensure_security_schema()
    minutes = max(1, int(minutes))
    settings = _v169_load_persistent_security_settings()
    settings["idle_timeout_minutes"] = str(minutes)
    for table in ("security_settings", "auth_security_settings"):
        try:
            execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    note TEXT,
                    updated_at TEXT
                )
            """)
            execute(f"""
                INSERT INTO {table} (setting_key, setting_value, note, updated_at)
                VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (str(minutes), _now()))
        except Exception:
            pass
    _v169_write_persistent_security_settings(settings)
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
        st.session_state["spt_security_settings"] = dict(settings)
    except Exception:
        pass


# ===== V1.99 idle setting permanence + permission reconciliation =====
def _v199_security_setting_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [
        root / "data" / "config" / "security_settings.json",
        root / "data" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "security_settings.json",
    ]


def _v169_load_persistent_security_settings() -> dict[str, str]:  # type: ignore[override]
    data: dict[str, str] = {}
    allowed = {"idle_timeout_minutes", "ask_continue_after_record"}
    for path in _v199_security_setting_paths():
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("security_settings") if isinstance(payload, dict) else None
            if raw is None and isinstance(payload, dict):
                raw = payload.get("settings")
            if raw is None and isinstance(payload, dict) and isinstance(payload.get("tables"), dict):
                rows = payload.get("tables", {}).get("auth_security_settings") or payload.get("tables", {}).get("security_settings") or []
                if isinstance(rows, list):
                    raw = {str(r.get("setting_key")): str(r.get("setting_value")) for r in rows if isinstance(r, dict) and r.get("setting_key")}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if str(k) in allowed and v is not None:
                        data[str(k)] = str(v)
        except Exception:
            continue
    return data


def _v169_write_persistent_security_settings(settings: dict[str, str]) -> None:  # type: ignore[override]
    safe = {
        "idle_timeout_minutes": str(settings.get("idle_timeout_minutes", DEFAULT_IDLE_MINUTES) or DEFAULT_IDLE_MINUTES),
        "ask_continue_after_record": str(settings.get("ask_continue_after_record", "1") or "1"),
    }
    payload = {"version": "V1.99", "updated_at": _now(), "security_settings": safe}
    for path in _v199_security_setting_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def get_idle_timeout_minutes() -> int:  # type: ignore[override]
    """V1.99: idle timeout priority = session cache -> permanent JSON -> DB -> default."""
    try:
        cache = st.session_state.get("_spt_idle_timeout_cache")
        now_ts = time.time()
        if cache and now_ts - float(cache.get("ts", 0)) < 60:
            return max(1, int(cache.get("minutes", DEFAULT_IDLE_MINUTES)))
    except Exception:
        pass

    ensure_security_schema()
    minutes = DEFAULT_IDLE_MINUTES
    file_settings = _v169_load_persistent_security_settings()
    if file_settings.get("idle_timeout_minutes") not in (None, ""):
        try:
            minutes = int(float(file_settings["idle_timeout_minutes"]))
        except Exception:
            minutes = DEFAULT_IDLE_MINUTES
    else:
        for table in ("auth_security_settings", "security_settings"):
            try:
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    minutes = int(float(row["setting_value"]))
                    break
            except Exception:
                pass
    minutes = max(1, int(minutes))
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
    except Exception:
        pass
    return minutes


def set_idle_timeout_minutes(minutes: int) -> None:  # type: ignore[override]
    """V1.99: write idle timeout to DB and permanent JSON files."""
    ensure_security_schema()
    minutes = max(1, int(minutes))
    settings = _v169_load_persistent_security_settings()
    settings["idle_timeout_minutes"] = str(minutes)
    settings.setdefault("ask_continue_after_record", "1")
    for table in ("security_settings", "auth_security_settings"):
        try:
            execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    note TEXT,
                    updated_at TEXT
                )
            """)
            execute(f"""
                INSERT INTO {table} (setting_key, setting_value, note, updated_at)
                VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (str(minutes), _now()))
        except Exception:
            pass
    _v169_write_persistent_security_settings(settings)
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
        st.session_state["spt_security_settings"] = dict(settings)
    except Exception:
        pass


_old_check_permission_v199 = check_permission

def check_permission(module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    """V1.99: check permission after ensuring newly-added modules have rows."""
    try:
        from services.permission_service import reconcile_permission_matrix_for_current_modules
        reconcile_permission_matrix_for_current_modules()
        # Permission rows may have been inserted; avoid stale negative cache.
        clear_permission_cache(st.session_state.get("auth_username"))
    except Exception:
        pass
    return _old_check_permission_v199(module_code, action)

# ===== V2.08 idle timeout permanent-file final override =====
def _v208_idle_timeout_paths() -> list[Path]:
    """All permanent locations used by 10｜權限管理 for idle timeout.

    V2.08 fix: the login/user bar was still reading only old security_settings
    files in some deployments, so it fell back to 15 after login/redeploy even
    when 10｜權限管理 had saved a new value.  These paths are now the single
    source chain for display, watchdog and logout logic.
    """
    root = Path(__file__).resolve().parents[1]
    return [
        root / "data" / "config" / "idle_timeout_settings.json",
        root / "data" / "persistent_state" / "spt_idle_timeout_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "idle_timeout_settings.json",
        root / "data" / "config" / "security_settings.json",
        root / "data" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "security_settings.json",
    ]


def _v208_extract_idle_timeout(payload: Any) -> int | None:
    """Extract idle_timeout_minutes from any old/new persistent JSON shape."""
    try:
        if not isinstance(payload, dict):
            return None
        candidates: list[Any] = []
        candidates.append(payload.get("idle_timeout_minutes"))
        if isinstance(payload.get("security_settings"), dict):
            candidates.append(payload["security_settings"].get("idle_timeout_minutes"))
        if isinstance(payload.get("settings"), dict):
            candidates.append(payload["settings"].get("idle_timeout_minutes"))
        if isinstance(payload.get("tables"), dict):
            for table_name in ("auth_security_settings", "security_settings"):
                rows = payload.get("tables", {}).get(table_name) or []
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict) and str(row.get("setting_key")) == "idle_timeout_minutes":
                            candidates.append(row.get("setting_value"))
        for value in candidates:
            if value in (None, ""):
                continue
            minutes = int(float(value))
            if minutes >= 1:
                return minutes
    except Exception:
        return None
    return None


def _v208_read_idle_timeout_from_files() -> int | None:
    for path in _v208_idle_timeout_paths():
        try:
            if not path.exists():
                continue
            minutes = _v208_extract_idle_timeout(json.loads(path.read_text(encoding="utf-8")))
            if minutes is not None:
                return minutes
        except Exception:
            continue
    return None


def _v208_write_idle_timeout_files(minutes: int) -> None:
    minutes = max(1, int(minutes))
    idle_payload = {
        "version": "V2.08",
        "idle_timeout_minutes": minutes,
        "updated_at": _now(),
        "note": "閒置自動登出分鐘數永久設定。登入列、閒置監控、10 權限管理皆以此設定為準。",
    }
    security_payload = {
        "version": "V2.08",
        "updated_at": _now(),
        "security_settings": {
            "idle_timeout_minutes": str(minutes),
            "ask_continue_after_record": "1",
        },
    }
    for path in _v208_idle_timeout_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.name == "idle_timeout_settings.json" or path.name == "spt_idle_timeout_settings.json":
                payload = idle_payload
            else:
                # Preserve ask_continue_after_record when possible.
                try:
                    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                    old_settings = old.get("security_settings") if isinstance(old, dict) else None
                    if isinstance(old_settings, dict) and old_settings.get("ask_continue_after_record") is not None:
                        security_payload["security_settings"]["ask_continue_after_record"] = str(old_settings.get("ask_continue_after_record"))
                except Exception:
                    pass
                payload = security_payload
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def get_idle_timeout_minutes() -> int:  # type: ignore[override]
    """V2.08 final source-of-truth reader for idle auto logout minutes."""
    try:
        cache = st.session_state.get("_spt_idle_timeout_cache")
        if cache:
            minutes = int(float(cache.get("minutes", 0)))
            # cache ts=0 means just saved; still trust it in this session.
            if minutes >= 1:
                return minutes
    except Exception:
        pass

    minutes = _v208_read_idle_timeout_from_files()
    if minutes is None:
        try:
            ensure_security_schema()
            for table in ("auth_security_settings", "security_settings"):
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    minutes = int(float(row.get("setting_value")))
                    break
        except Exception:
            minutes = None
    if minutes is None:
        minutes = DEFAULT_IDLE_MINUTES
    minutes = max(1, int(minutes))
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
    except Exception:
        pass
    return minutes


def set_idle_timeout_minutes(minutes: int) -> None:  # type: ignore[override]
    """V2.08 final writer: DB + all permanent JSON paths + session cache."""
    minutes = max(1, int(minutes))
    try:
        ensure_security_schema()
        for table in ("auth_security_settings", "security_settings"):
            execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    note TEXT,
                    updated_at TEXT
                )
            """)
            execute(f"""
                INSERT INTO {table} (setting_key, setting_value, note, updated_at)
                VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (str(minutes), _now()))
    except Exception:
        pass
    _v208_write_idle_timeout_files(minutes)
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
        settings = st.session_state.get("spt_security_settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["idle_timeout_minutes"] = str(minutes)
        st.session_state["spt_security_settings"] = settings
    except Exception:
        pass

# ===== V2.41 startup/page-entry performance guard =====
# V1.99 added automatic permission reconciliation inside every check_permission().
# That is safe but expensive: home/sidebar and module pages call permissions many
# times, so after updating files every page could spend seconds doing INSERT OR
# IGNORE loops.  Keep the safety check, but only reconcile occasionally.
_SECURITY_RECONCILE_DONE_TS_V241 = 0.0
_SECURITY_RECONCILE_TTL_SECONDS_V241 = 600.0


def _v241_security_reconcile_once() -> None:
    global _SECURITY_RECONCILE_DONE_TS_V241
    now_ts = time.time()
    try:
        ss_ts = float(st.session_state.get("_v241_security_reconcile_ts", 0) or 0)
        if now_ts - ss_ts < _SECURITY_RECONCILE_TTL_SECONDS_V241:
            return
    except Exception:
        pass
    try:
        if now_ts - float(_SECURITY_RECONCILE_DONE_TS_V241 or 0) < _SECURITY_RECONCILE_TTL_SECONDS_V241:
            return
    except Exception:
        pass
    try:
        from services.permission_service import reconcile_permission_matrix_for_current_modules
        reconcile_permission_matrix_for_current_modules(force=False)
    except Exception:
        pass
    try:
        _SECURITY_RECONCILE_DONE_TS_V241 = now_ts
        st.session_state["_v241_security_reconcile_ts"] = now_ts
    except Exception:
        pass


# Replace the previous override with a faster version that still preserves the
# original permission-cache behavior.
def check_permission(module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    try:
        _v241_security_reconcile_once()
    except Exception:
        pass
    return _old_check_permission_v199(module_code, action)


# ===== V3.40 login-page no-side-effect policy =====
# Do not mutate idle timeout during import/Reboot. The value must come from
# permanent JSON/DB, and DEFAULT_IDLE_MINUTES is only a read fallback.
def _v243_seed_idle_timeout_one_minute() -> None:
    return

# ===== V3.65 login safe no-network final override =====
# 目的：登入後不可再卡在大量永久檔掃描、GitHub 同步、權限矩陣重建。
# 原則：登入只讀 SQLite auth_users；只有 auth_users 完全空時，才從「直接永久檔」輕量還原一次。

_AUTH_LIGHT_RESTORE_DONE = False

def _v365_permission_direct_payloads() -> list[dict]:
    payloads: list[dict] = []
    paths = [
        PROJECT_ROOT / 'data' / 'persistent_modules' / '10_permissions' / '10_permissions_records.json',
        PROJECT_ROOT / 'data' / 'persistent_modules' / '10_permissions' / '10_permissions_settings.json',
        PROJECT_ROOT / 'data' / 'persistent_state' / 'spt_user_persistent_settings.json',
        PROJECT_ROOT / 'data' / 'persistent_state' / 'spt_module_settings.json',
    ]
    for p in paths:
        try:
            if not p.exists() or p.stat().st_size <= 0:
                continue
            raw = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                continue
            if isinstance(raw.get('tables'), dict):
                payloads.append(raw)
            ps = raw.get('permission_settings')
            if isinstance(ps, dict):
                for v in ps.values():
                    if isinstance(v, dict) and isinstance(v.get('tables'), dict):
                        payloads.append(v)
        except Exception:
            continue
    return payloads


def _v365_first_auth_tables() -> dict[str, list[dict[str, Any]]]:
    for payload in _v365_permission_direct_payloads():
        tables = payload.get('tables', {}) if isinstance(payload, dict) else {}
        if not isinstance(tables, dict):
            continue
        users = tables.get('auth_users', []) or []
        perms = tables.get('auth_account_permissions', []) or []
        if isinstance(users, list) and users:
            return {
                'auth_users': [u for u in users if isinstance(u, dict)],
                'auth_account_permissions': [r for r in perms if isinstance(r, dict)],
            }
    return {'auth_users': [], 'auth_account_permissions': []}


def _restore_auth_users_lightweight_if_needed(username: str = '') -> None:  # type: ignore[override]
    """V3.65：登入安全版。只在 auth_users 完全空時讀直接永久檔；不掃 history、不連 GitHub。"""
    global _AUTH_LIGHT_RESTORE_DONE
    if _AUTH_LIGHT_RESTORE_DONE:
        return
    _AUTH_LIGHT_RESTORE_DONE = True
    _ensure_auth_users_schema_lightweight()
    try:
        row = query_one('SELECT COUNT(*) AS c FROM auth_users') or {}
        if int(row.get('c', 0) or 0) > 0:
            return
    except Exception:
        pass
    tables = _v365_first_auth_tables()
    users = tables.get('auth_users', [])
    perms = tables.get('auth_account_permissions', [])
    if not users:
        return
    try:
        for u in users:
            name = str(u.get('username', '') or '').strip()
            if not name:
                continue
            execute('''
                INSERT OR REPLACE INTO auth_users
                (username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,last_login_at,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                name,
                str(u.get('password_hash', '') or ''),
                str(u.get('password_hint', '') or ''),
                str(u.get('employee_id', '') or ''),
                str(u.get('display_name', '') or name),
                str(u.get('email', '') or ''),
                str(u.get('role_code', 'operator') or 'operator'),
                int(u.get('is_active', 1) or 0),
                int(u.get('force_password_change', 0) or 0),
                str(u.get('last_login_at', '') or ''),
                str(u.get('note', '') or ''),
                str(u.get('created_at', '') or _now()),
                str(u.get('updated_at', '') or _now()),
            ))
        for r in perms:
            name = str(r.get('username', '') or '').strip()
            module = str(r.get('module_code', '') or '').strip()
            if not name or not module:
                continue
            execute('''
                INSERT OR REPLACE INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                name, module,
                str(r.get('module_name_zh', '') or ''),
                str(r.get('module_name_en', '') or ''),
                int(r.get('can_view', 0) or 0), int(r.get('can_create', 0) or 0),
                int(r.get('can_edit', 0) or 0), int(r.get('can_delete', 0) or 0),
                int(r.get('can_import', 0) or 0), int(r.get('can_export', 0) or 0),
                int(r.get('can_backup', 0) or 0), int(r.get('can_restore', 0) or 0),
                int(r.get('can_manage', 0) or 0), str(r.get('updated_at', '') or _now()),
            ))
    except Exception:
        pass


def authenticate(username: str, password: str) -> tuple[bool, str]:  # type: ignore[override]
    """V3.65：登入只做必要查詢，不預載全權限、不掃 history、不做 GitHub。"""
    ensure_security_schema()
    username = (username or '').strip()
    _restore_auth_users_lightweight_if_needed(username)
    auth_row = query_one('SELECT * FROM auth_users WHERE username=?', (username,))
    row = auth_row or query_one('SELECT * FROM security_users WHERE username=?', (username,))
    if not row:
        log_security_event(username, 'LOGIN', 'FAIL', '帳號不存在')
        return False, '帳號或密碼錯誤。'
    if not int(row.get('is_active', 0) or 0):
        log_security_event(username, 'LOGIN', 'FAIL', '帳號停用')
        return False, '帳號已停用。'
    if not verify_password(password, row.get('password_hash')):
        log_security_event(username, 'LOGIN', 'FAIL', '密碼錯誤')
        return False, '帳號或密碼錯誤。'
    role = str((auth_row or row).get('role_code', '') or '').strip()
    if not role:
        role = 'admin' if username.lower() == 'admin' else 'operator'
    st.session_state['auth_logged_in'] = True
    st.session_state['auth_username'] = username
    st.session_state['auth_display_name'] = row.get('display_name') or username
    st.session_state['auth_employee_id'] = row.get('employee_id') or ''
    st.session_state['auth_roles'] = [role]
    st.session_state['auth_login_ts'] = time.time()
    st.session_state['auth_last_activity_ts'] = time.time()
    try:
        execute('UPDATE auth_users SET last_login_at=?, updated_at=? WHERE username=?', (_now(), _now(), username))
    except Exception:
        pass
    try:
        execute('UPDATE security_users SET last_login_at=?, updated_at=? WHERE username=?', (_now(), _now(), username))
    except Exception:
        pass
    log_security_event(username, 'LOGIN', 'SUCCESS', f'role={role}')
    return True, '登入成功。'


def _v365_load_permission_cache(username: str) -> dict[str, dict[str, bool]]:
    cache_key = f'_spt_perm_cache_{username}'
    cached = st.session_state.get(cache_key)
    now_ts = time.time()
    if cached and now_ts - float(cached.get('ts', 0) or 0) < _PERMISSION_CACHE_TTL_SECONDS:
        return cached.get('data', {})
    data: dict[str, dict[str, bool]] = {}
    roles = st.session_state.get('auth_roles', []) or []
    if 'admin' in roles or _is_admin_user(username, roles):
        for m in MODULES:
            data[m['module_code']] = {c: True for c in PERMISSION_COLUMNS}
        st.session_state[cache_key] = {'ts': now_ts, 'data': data}
        return data
    try:
        df = query_df('''
            SELECT p.* FROM auth_account_permissions p
            JOIN auth_users u ON u.username=p.username
            WHERE p.username=? AND COALESCE(u.is_active,0)=1
        ''', (username,))
        if not df.empty:
            for _, r in df.iterrows():
                no = str(r.get('module_code', '')).zfill(2)
                code = MODULE_NO_TO_CODE.get(no, no)
                row = {c: bool(int(r.get(c, 0) or 0)) for c in PERMISSION_COLUMNS}
                if row.get('can_manage'):
                    row = {c: True for c in PERMISSION_COLUMNS}
                data[code] = row
    except Exception:
        data = {}
    st.session_state[cache_key] = {'ts': now_ts, 'data': data}
    return data


def check_permission(module_code: str, action: str = 'can_view') -> bool:  # type: ignore[override]
    """V3.65：首頁/側邊模組權限查詢不得做 reconcile 或大量寫入。"""
    if not st.session_state.get('auth_logged_in'):
        return False
    username = str(st.session_state.get('auth_username', '') or '')
    roles = st.session_state.get('auth_roles', []) or []
    if 'admin' in roles:
        return True
    data = _v365_load_permission_cache(username)
    row = data.get(module_code) or data.get(MODULE_NO_TO_CODE.get(str(module_code).zfill(2), str(module_code))) or {}
    return bool(row.get(action, False))


def require_module_access(module_code: str, action: str = 'can_view') -> None:  # type: ignore[override]
    require_login(module_code)
    if not check_permission(module_code, action):
        log_security_event(st.session_state.get('auth_username', ''), 'PERMISSION_DENIED', 'FAIL', f'{module_code}:{action}', module_code)
        st.error('權限不足：你的帳號未被授權使用此模組或功能。')
        st.stop()

require_permission = require_module_access

# ===== V3.69 login safe mode: direct-account restore only, no history scan =====
# 03/04 能穩定，是因為只讀固定 latest 檔。登入也改成同樣模式：只讀 10_permissions 固定檔，
# 不掃 history、不比誰資料多、不碰 GitHub，避免登入畫面一直運算。
_V369_DELETED_ACCOUNT_FILES = [
    PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "deleted_accounts.json",
    PROJECT_ROOT / "data" / "persistent_state" / "spt_permission_deleted_accounts.json",
]


def _v369_read_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v369_deleted_accounts() -> set[str]:
    deleted: set[str] = set()
    for p in _V369_DELETED_ACCOUNT_FILES:
        data = _v369_read_json_file(p)
        raw = data.get("deleted_usernames") if isinstance(data.get("deleted_usernames"), list) else []
        for u in raw:
            name = str(u or "").strip().lower()
            if name and name != "admin":
                deleted.add(name)
    return deleted


def _v369_extract_tables(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}
    tables = payload.get("tables")
    if isinstance(tables, dict) and isinstance(tables.get("auth_users"), list):
        return tables  # type: ignore[return-value]
    ps = payload.get("permission_settings")
    if isinstance(ps, dict):
        for v in ps.values():
            if isinstance(v, dict) and isinstance(v.get("tables"), dict) and isinstance(v.get("tables", {}).get("auth_users"), list):
                return v.get("tables", {})  # type: ignore[return-value]
    return {}


def _best_local_auth_tables() -> dict[str, list[dict[str, Any]]]:  # type: ignore[override]
    """V3.69: direct latest auth restore for login only.

    Reads only fixed files written by 10｜權限管理 V366+.
    No history, no GitHub, no broad persistence scan.
    """
    candidates = [
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        PROJECT_ROOT / "data" / "persistent_state" / "spt_permission_settings.json",
        PROJECT_ROOT / "data" / "persistent_state" / "spt_user_persistent_settings.json",
    ]
    best_tables: dict[str, list[dict[str, Any]]] = {}
    best_stamp = ""
    best_mtime = -1.0
    for path in candidates:
        payload = _v369_read_json_file(path)
        tables = _v369_extract_tables(payload)
        users = tables.get("auth_users", []) if isinstance(tables, dict) else []
        if not isinstance(users, list) or not users:
            continue
        stamp = str(payload.get("exported_at") or payload.get("updated_at") or "")
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = 0.0
        if (stamp, mtime) >= (best_stamp, best_mtime):
            best_stamp, best_mtime = stamp, mtime
            best_tables = {
                "auth_users": list(users),
                "auth_account_permissions": list(tables.get("auth_account_permissions", []) or []),
            }
    deleted = _v369_deleted_accounts()
    if deleted and best_tables:
        best_tables["auth_users"] = [r for r in best_tables.get("auth_users", []) if str(r.get("username", "")).strip().lower() not in deleted]
        best_tables["auth_account_permissions"] = [r for r in best_tables.get("auth_account_permissions", []) if str(r.get("username", "")).strip().lower() not in deleted]
    return best_tables


def _restore_auth_users_lightweight_if_needed(username: str = "") -> None:  # type: ignore[override]
    """V3.69: lazy login restore, direct files only.

    It runs once per process, inserts/updates only auth_users and auth_account_permissions,
    and never calls permission_service, GitHub, history scan, or full matrix rebuild.
    """
    global _AUTH_LIGHT_RESTORE_DONE
    if _AUTH_LIGHT_RESTORE_DONE:
        return
    _AUTH_LIGHT_RESTORE_DONE = True
    _ensure_auth_users_schema_lightweight()
    try:
        row = query_one("SELECT COUNT(*) AS c FROM auth_users") or {}
        count = int(row.get("c", 0) or 0)
        # If DB already has non-default account records, avoid any restore during login.
        if count > 6:
            return
    except Exception:
        pass
    tables = _best_local_auth_tables()
    users = tables.get("auth_users", [])
    perms = tables.get("auth_account_permissions", [])
    if not users:
        return
    try:
        for u in users:
            if not isinstance(u, dict):
                continue
            uname = str(u.get("username", "")).strip()
            if not uname:
                continue
            execute("""
                INSERT INTO auth_users
                (username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,last_login_at,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash=excluded.password_hash,
                    password_hint=excluded.password_hint,
                    employee_id=excluded.employee_id,
                    display_name=excluded.display_name,
                    email=excluded.email,
                    role_code=excluded.role_code,
                    is_active=excluded.is_active,
                    force_password_change=excluded.force_password_change,
                    last_login_at=excluded.last_login_at,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (
                uname,
                str(u.get("password_hash", "") or ""),
                str(u.get("password_hint", "") or ""),
                str(u.get("employee_id", "") or ""),
                str(u.get("display_name", "") or uname),
                str(u.get("email", "") or ""),
                str(u.get("role_code", "operator") or "operator"),
                int(u.get("is_active", 1) or 0),
                int(u.get("force_password_change", 0) or 0),
                str(u.get("last_login_at", "") or ""),
                str(u.get("note", "") or ""),
                str(u.get("created_at", "") or _now()),
                str(u.get("updated_at", "") or _now()),
            ))
        for r in perms:
            if not isinstance(r, dict):
                continue
            uname = str(r.get("username", "")).strip()
            module_code = str(r.get("module_code", "")).strip()
            if not uname or not module_code:
                continue
            execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username,module_code) DO UPDATE SET
                    module_name_zh=excluded.module_name_zh,
                    module_name_en=excluded.module_name_en,
                    can_view=excluded.can_view,
                    can_create=excluded.can_create,
                    can_edit=excluded.can_edit,
                    can_delete=excluded.can_delete,
                    can_import=excluded.can_import,
                    can_export=excluded.can_export,
                    can_backup=excluded.can_backup,
                    can_restore=excluded.can_restore,
                    can_manage=excluded.can_manage,
                    updated_at=excluded.updated_at
            """, (
                uname, module_code,
                str(r.get("module_name_zh", "") or ""),
                str(r.get("module_name_en", "") or ""),
                int(r.get("can_view", 0) or 0),
                int(r.get("can_create", 0) or 0),
                int(r.get("can_edit", 0) or 0),
                int(r.get("can_delete", 0) or 0),
                int(r.get("can_import", 0) or 0),
                int(r.get("can_export", 0) or 0),
                int(r.get("can_backup", 0) or 0),
                int(r.get("can_restore", 0) or 0),
                int(r.get("can_manage", 0) or 0),
                str(r.get("updated_at", "") or _now()),
            ))
    except Exception:
        pass


# ======================= V86 01 FAST PROMPT STOP =======================
# 目的：01 工時紀錄完成後顯示「是否繼續」對話框時，立即停止背景頁面繼續渲染。
# 避免使用者點「繼續」時，背景還在重建今日紀錄/管理員表格造成卡住。
try:
    _v86_prev_render_post_record_continue_prompt = render_post_record_continue_prompt
except Exception:
    _v86_prev_render_post_record_continue_prompt = None


def render_post_record_continue_prompt() -> None:  # type: ignore[override]
    if not st.session_state.get("post_record_prompt"):
        return
    if callable(_v86_prev_render_post_record_continue_prompt):
        _v86_prev_render_post_record_continue_prompt()
    else:
        st.success(st.session_state.get("post_record_message", "工時紀錄已完成"))
        c1, c2 = st.columns(2)
        if c1.button("是，繼續記錄 / Continue", use_container_width=True, key="post_continue_yes_v86"):
            st.session_state["post_record_prompt"] = False
            mark_activity()
            st.rerun()
        if c2.button("否，登出帳號 / Logout", use_container_width=True, key="post_continue_no_v86"):
            logout("完成工時後選擇不繼續記錄，自動登出")
            st.rerun()
    # 關鍵：對話框顯示後停止本次頁面渲染，不再往下跑 01 表格與管理員維護區。
    st.stop()
# ===================== END V86 01 FAST PROMPT STOP =====================

# ========================= V98 IDLE TIMEOUT SINGLE AUTHORITY FIX =========================
# 修正目的：
# - 10｜權限管理安全設定已寫入 data/permanent_store/modules/10_permissions/records.json，
#   但登入列仍可能優先讀舊 data/persistent_state / data/config，導致畫面顯示 15 分鐘。
# - 本段將登入列、閒置監控、10 權限管理安全設定統一到 permanent_store 優先。

def _v98_idle_timeout_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [
        root / "data" / "permanent_store" / "config" / "idle_timeout_settings.json",
        root / "data" / "permanent_store" / "persistent_state" / "spt_idle_timeout_settings.json",
        root / "data" / "permanent_store" / "config" / "security_settings.json",
        root / "data" / "permanent_store" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "permanent_store" / "modules" / "10_permissions" / "settings.json",
        root / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json",
        # Legacy read compatibility only; these are lower priority and should not override permanent_store.
        root / "data" / "config" / "idle_timeout_settings.json",
        root / "data" / "persistent_state" / "spt_idle_timeout_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "idle_timeout_settings.json",
        root / "data" / "config" / "security_settings.json",
        root / "data" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "security_settings.json",
    ]


def _v98_extract_idle_timeout(payload: Any) -> int | None:
    try:
        if not isinstance(payload, dict):
            return None
        candidates: list[Any] = [payload.get("idle_timeout_minutes")]
        for key in ("security_settings", "settings"):
            obj = payload.get(key)
            if isinstance(obj, dict):
                candidates.append(obj.get("idle_timeout_minutes"))
                nested = obj.get("security_settings")
                if isinstance(nested, dict):
                    candidates.append(nested.get("idle_timeout_minutes"))
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        for table_name in ("auth_security_settings", "security_settings"):
            rows = tables.get(table_name) if isinstance(tables, dict) else []
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and str(row.get("setting_key") or "").strip() == "idle_timeout_minutes":
                        candidates.append(row.get("setting_value"))
        for v in candidates:
            if v in (None, ""):
                continue
            minutes = int(float(v))
            if minutes >= 1:
                return minutes
    except Exception:
        return None
    return None


def _v98_read_idle_timeout_from_files() -> int | None:
    for path in _v98_idle_timeout_paths():
        try:
            if not path.exists() or path.stat().st_size <= 0:
                continue
            minutes = _v98_extract_idle_timeout(json.loads(path.read_text(encoding="utf-8")))
            if minutes is not None:
                return minutes
        except Exception:
            continue
    return None


def _v98_write_idle_timeout_files(minutes: int, ask_continue_after_record: str = "1") -> None:
    minutes = max(1, int(minutes))
    ask = "0" if str(ask_continue_after_record).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
    idle_payload = {
        "version": "V98",
        "idle_timeout_minutes": minutes,
        "updated_at": _now(),
        "note": "閒置自動登出分鐘數永久設定。10 權限管理、登入列、閒置監控皆以 permanent_store 為優先權威來源。",
    }
    security_payload = {
        "version": "V98",
        "updated_at": _now(),
        "security_settings": {
            "idle_timeout_minutes": str(minutes),
            "ask_continue_after_record": ask,
        },
    }
    for path in _v98_idle_timeout_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.name in {"idle_timeout_settings.json", "spt_idle_timeout_settings.json"}:
                payload = idle_payload
            else:
                payload = security_payload
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def get_idle_timeout_minutes() -> int:  # type: ignore[override]
    """V98 final reader: permanent_store first, then DB, then safe default."""
    try:
        cache = st.session_state.get("_spt_idle_timeout_cache")
        if cache:
            minutes = int(float(cache.get("minutes", 0)))
            if minutes >= 1:
                return minutes
    except Exception:
        pass

    minutes = _v98_read_idle_timeout_from_files()
    if minutes is None:
        try:
            from services.permission_service import get_security_settings as _perm_security_settings
            sec = _perm_security_settings()
            if sec.get("idle_timeout_minutes") not in (None, ""):
                minutes = int(float(sec.get("idle_timeout_minutes")))
        except Exception:
            minutes = None
    if minutes is None:
        try:
            ensure_security_schema()
            for table in ("auth_security_settings", "security_settings"):
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    minutes = int(float(row.get("setting_value")))
                    break
        except Exception:
            minutes = None
    if minutes is None:
        minutes = DEFAULT_IDLE_MINUTES
    minutes = max(1, int(minutes))
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
    except Exception:
        pass
    return minutes


def set_idle_timeout_minutes(minutes: int) -> None:  # type: ignore[override]
    """V98 final writer: DB + permanent_store files + 10_permissions authority + session cache."""
    minutes = max(1, int(minutes))
    ask = "1"
    try:
        ss = st.session_state.get("spt_security_settings", {})
        if isinstance(ss, dict) and ss.get("ask_continue_after_record") is not None:
            ask = str(ss.get("ask_continue_after_record"))
    except Exception:
        pass
    try:
        ensure_security_schema()
        for table in ("auth_security_settings", "security_settings"):
            execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    note TEXT,
                    updated_at TEXT
                )
            """)
            execute(f"""
                INSERT INTO {table} (setting_key, setting_value, note, updated_at)
                VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (str(minutes), _now()))
    except Exception:
        pass

    _v98_write_idle_timeout_files(minutes, ask)

    # 同步 10_permissions 權威檔，避免 Reboot 後 10 頁與登入列讀不同來源。
    try:
        from services.permanent_authority_service import load_tables as _pa_load_tables, save_authority as _pa_save_authority
        tables = _pa_load_tables("10_permissions", "records")
        rows = [
            {"setting_key": "idle_timeout_minutes", "setting_value": str(minutes), "note": "V98 single authority idle timeout", "updated_at": _now()},
            {"setting_key": "ask_continue_after_record", "setting_value": "0" if str(ask).strip().lower() in {"0", "false", "no", "n", "否"} else "1", "note": "V98 single authority post-record prompt", "updated_at": _now()},
        ]
        tables["auth_security_settings"] = rows
        tables["security_settings"] = list(rows)
        _pa_save_authority("10_permissions", records=tables, reason="set_idle_timeout_minutes_v98", github=True)
    except Exception:
        pass

    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
        settings = st.session_state.get("spt_security_settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["idle_timeout_minutes"] = str(minutes)
        settings["ask_continue_after_record"] = "0" if str(ask).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
        st.session_state["spt_security_settings"] = settings
    except Exception:
        pass
# ======================= END V98 IDLE TIMEOUT SINGLE AUTHORITY FIX =======================

# ========================= V101 IDLE TIMEOUT CANONICAL SETTINGS FIX =========================
# 修正目的：
# 1) 10｜權限管理設定 3 分鐘後，Reboot / 重新登入仍跳回 15 分鐘。
# 2) 統一以 data/permanent_store/modules/10_permissions/settings.json 為最高優先權威來源，
#    records.json 與舊 idle_timeout_settings.json 僅作相容備援。
# 3) set_idle_timeout_minutes() 同步寫 settings.json + records.json + legacy files + SQLite cache。

def _v101_pa_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _v101_extract_idle(payload: Any) -> int | None:
    try:
        if not isinstance(payload, dict):
            return None
        candidates: list[Any] = []
        candidates.append(payload.get("idle_timeout_minutes"))
        settings = payload.get("settings")
        if isinstance(settings, dict):
            candidates.append(settings.get("idle_timeout_minutes"))
            sec = settings.get("security_settings")
            if isinstance(sec, dict):
                candidates.append(sec.get("idle_timeout_minutes"))
        sec = payload.get("security_settings")
        if isinstance(sec, dict):
            candidates.append(sec.get("idle_timeout_minutes"))
        tables = payload.get("tables")
        if isinstance(tables, dict):
            for table_name in ("auth_security_settings", "security_settings"):
                rows = tables.get(table_name)
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict) and str(row.get("setting_key") or "").strip() == "idle_timeout_minutes":
                            candidates.append(row.get("setting_value"))
        for value in candidates:
            if value in (None, ""):
                continue
            minutes = int(float(str(value).strip()))
            if minutes >= 1:
                return minutes
    except Exception:
        return None
    return None


def _v101_idle_authority_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [
        root / "data" / "permanent_store" / "modules" / "10_permissions" / "settings.json",
        root / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json",
        root / "data" / "permanent_store" / "config" / "idle_timeout_settings.json",
        root / "data" / "permanent_store" / "persistent_state" / "spt_idle_timeout_settings.json",
        root / "data" / "permanent_store" / "config" / "security_settings.json",
        root / "data" / "permanent_store" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "config" / "idle_timeout_settings.json",
        root / "data" / "persistent_state" / "spt_idle_timeout_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "idle_timeout_settings.json",
    ]


def _v101_read_idle_from_authority_files() -> int | None:
    for path in _v101_idle_authority_paths():
        minutes = _v101_extract_idle(_v101_pa_json(path))
        if minutes is not None:
            return minutes
    return None


def get_idle_timeout_minutes() -> int:  # type: ignore[override]
    """V101 final reader: canonical settings.json first, then records/legacy/DB, then default."""
    try:
        cache = st.session_state.get("_spt_idle_timeout_cache")
        if isinstance(cache, dict):
            minutes = int(float(cache.get("minutes", 0)))
            if minutes >= 1:
                return minutes
    except Exception:
        pass

    minutes = _v101_read_idle_from_authority_files()
    if minutes is None:
        try:
            ensure_security_schema()
            for table in ("auth_security_settings", "security_settings"):
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    minutes = int(float(row.get("setting_value")))
                    break
        except Exception:
            minutes = None
    if minutes is None:
        minutes = DEFAULT_IDLE_MINUTES
    minutes = max(1, int(minutes))
    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
    except Exception:
        pass
    return minutes


def set_idle_timeout_minutes(minutes: int) -> None:  # type: ignore[override]
    """V101 final writer: settings.json + records.json + DB + legacy mirrors."""
    minutes = max(1, int(minutes))
    ask = "1"
    try:
        ss = st.session_state.get("spt_security_settings", {})
        if isinstance(ss, dict) and ss.get("ask_continue_after_record") is not None:
            ask = str(ss.get("ask_continue_after_record"))
    except Exception:
        pass
    ask = "0" if str(ask).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
    now = _now()

    # SQLite cache for runtime compatibility.
    try:
        ensure_security_schema()
        for table in ("auth_security_settings", "security_settings"):
            execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    note TEXT,
                    updated_at TEXT
                )
            """)
            for key, value, note in [
                ("idle_timeout_minutes", str(minutes), "V101 canonical idle timeout minutes"),
                ("ask_continue_after_record", ask, "V101 canonical post-record prompt"),
            ]:
                execute(f"""
                    INSERT INTO {table} (setting_key, setting_value, note, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value=excluded.setting_value,
                        note=excluded.note,
                        updated_at=excluded.updated_at
                """, (key, value, note, now))
    except Exception:
        pass

    # Legacy mirror files for older code paths.
    try:
        _v98_write_idle_timeout_files(minutes, ask)  # type: ignore[name-defined]
    except Exception:
        pass

    # Permanent authority canonical files.
    try:
        from services.permanent_authority_service import load_tables as _pa_load_tables, save_authority as _pa_save_authority, save_settings as _pa_save_settings, force_upload_authority_file as _pa_force
        settings_payload = {
            "idle_timeout_minutes": str(minutes),
            "ask_continue_after_record": ask,
            "security_settings": {
                "idle_timeout_minutes": str(minutes),
                "ask_continue_after_record": ask,
            },
            "updated_at": now,
        }
        _pa_save_settings("10_permissions", settings_payload, reason="v101_idle_timeout_settings", github=True)
        tables = _pa_load_tables("10_permissions", "records")
        rows = [
            {"setting_key": "idle_timeout_minutes", "setting_value": str(minutes), "note": "V101 canonical idle timeout", "updated_at": now},
            {"setting_key": "ask_continue_after_record", "setting_value": ask, "note": "V101 canonical post-record prompt", "updated_at": now},
        ]
        tables["auth_security_settings"] = rows
        tables["security_settings"] = list(rows)
        _pa_save_authority("10_permissions", records=tables, reason="v101_idle_timeout_records", github=True)
        try:
            _pa_force("10_permissions", "settings", reason="v101_force_upload_idle_settings")
            _pa_force("10_permissions", "records", reason="v101_force_upload_idle_records")
        except Exception:
            pass
    except Exception:
        pass

    try:
        st.session_state["_spt_idle_timeout_cache"] = {"minutes": minutes, "ts": time.time()}
        settings = st.session_state.get("spt_security_settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings["idle_timeout_minutes"] = str(minutes)
        settings["ask_continue_after_record"] = ask
        st.session_state["spt_security_settings"] = settings
    except Exception:
        pass
# ======================= END V101 IDLE TIMEOUT CANONICAL SETTINGS FIX =======================

# ========================= V105 CANONICAL LOGIN AUTHORITY FIX =========================
# 修正目的：
# 1) 使用者帳號/密碼已在 10｜權限管理權威檔內，但登入仍顯示「帳號或密碼錯誤」。
# 2) 登入不可只看 SQLite 快取；必須優先讀 data/permanent_store/modules/10_permissions/records.json。
# 3) 相容 10 匯入表格的明碼欄位（密碼 / Password、密碼、password），成功後同步到 SQLite 快取供權限判斷。

_V105_PERMISSION_RECORD_CANDIDATES = [
    PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json",
    PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
]


def _v105_truthy(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    t = str(v).strip().lower()
    if t in {"1", "true", "yes", "y", "on", "是", "啟用", "active", "啟用 / active"}:
        return True
    if t in {"0", "false", "no", "n", "off", "否", "停用", "inactive", ""}:
        return False
    return default


def _v105_extract_tables_from_payload(payload: dict) -> dict[str, list[dict]]:
    if not isinstance(payload, dict):
        return {}
    tables = payload.get("tables")
    if isinstance(tables, dict):
        return {str(k): [dict(r) for r in v if isinstance(r, dict)] for k, v in tables.items() if isinstance(v, list)}
    for key in ("records", "data", "rows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return {"auth_users": [dict(r) for r in rows if isinstance(r, dict)]}
    return {}


def _v105_load_permission_authority_tables() -> dict[str, list[dict]]:
    try:
        from services.permanent_authority_service import load_tables as _pa_load_tables
        tables = _pa_load_tables("10_permissions", "records")
        if isinstance(tables, dict) and (tables.get("auth_users") or tables.get("security_users")):
            return {str(k): [dict(r) for r in v if isinstance(r, dict)] for k, v in tables.items() if isinstance(v, list)}
    except Exception:
        pass
    for p in _V105_PERMISSION_RECORD_CANDIDATES:
        try:
            if p.exists():
                payload = json.loads(p.read_text(encoding="utf-8"))
                tables = _v105_extract_tables_from_payload(payload)
                if tables.get("auth_users") or tables.get("security_users"):
                    return tables
        except Exception:
            continue
    return {}


def _v105_find_authority_user(username: str) -> tuple[dict | None, dict[str, list[dict]]]:
    uname = str(username or "").strip().lower()
    if not uname:
        return None, {}
    tables = _v105_load_permission_authority_tables()
    for table_name in ("auth_users", "security_users"):
        for row in tables.get(table_name, []) or []:
            if str(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or "").strip().lower() == uname:
                r = dict(row)
                r["username"] = str(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or username).strip()
                return r, tables
    return None, tables


def _v105_plain_password_candidates(row: dict) -> list[str]:
    keys = [
        "password", "Password", "密碼", "密碼 / Password", "密碼 / password",
        "new_password", "New Password", "新密碼", "新密碼 / New Password",
        "password_plain", "plain_password",
    ]
    out: list[str] = []
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s or s == "********" or s.startswith("pbkdf2_sha256$"):
            continue
        out.append(s)
    return out


def _v105_verify_password_against_authority_row(password: str, row: dict) -> bool:
    pwd = str(password or "")
    for k in ("password_hash", "hash", "passwordHash", "密碼雜湊"):
        h = str(row.get(k) or "").strip()
        if h and verify_password(pwd, h):
            return True
    for plain in _v105_plain_password_candidates(row):
        try:
            if hmac.compare_digest(plain, pwd):
                return True
        except Exception:
            if plain == pwd:
                return True
    return False


def _v105_role_from_user(row: dict) -> str:
    role = str(row.get("role_code") or row.get("role") or row.get("角色") or row.get("角色 / Role") or "").strip().lower()
    return role or ("admin" if str(row.get("username") or "").strip().lower() == "admin" else "operator")


def _v105_build_hash_if_needed(password: str, row: dict) -> str:
    current = str(row.get("password_hash") or "").strip()
    if current:
        return current
    for plain in _v105_plain_password_candidates(row):
        if plain == str(password or ""):
            return hash_password(plain)
    return current


def _v105_sync_authority_login_cache(user_row: dict, tables: dict[str, list[dict]], password: str = "") -> None:
    """Keep SQLite cache aligned after successful canonical login; best effort only."""
    try:
        ensure_security_schema()
        uname = str(user_row.get("username") or "").strip()
        if not uname:
            return
        now = _now()
        pwd_hash = _v105_build_hash_if_needed(password, user_row)
        role = _v105_role_from_user(user_row)
        employee_id = str(user_row.get("employee_id") or user_row.get("工號") or user_row.get("工號 / Employee ID") or "").strip()
        display_name = str(user_row.get("display_name") or user_row.get("姓名") or user_row.get("姓名 / Display Name") or uname).strip()
        email = str(user_row.get("email") or user_row.get("Email") or "").strip()
        is_active = 1 if _v105_truthy(user_row.get("is_active", user_row.get("啟用", user_row.get("啟用 / Active", True))), True) else 0
        force_change = 1 if _v105_truthy(user_row.get("force_password_change", user_row.get("強制改密碼", user_row.get("強制改密碼 / Force Change", False))), False) else 0
        note = str(user_row.get("note") or user_row.get("備註") or user_row.get("備註 / Note") or "").strip()
        execute("""
            INSERT INTO auth_users
            (username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,last_login_at,note,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                employee_id=excluded.employee_id,
                display_name=excluded.display_name,
                email=excluded.email,
                role_code=excluded.role_code,
                is_active=excluded.is_active,
                force_password_change=excluded.force_password_change,
                last_login_at=excluded.last_login_at,
                note=excluded.note,
                updated_at=excluded.updated_at
        """, (uname, pwd_hash, "V105 canonical authority login cache", employee_id, display_name, email, role, is_active, force_change, now, note, user_row.get("created_at") or now, now))
        try:
            execute("DELETE FROM auth_account_permissions WHERE lower(username)=lower(?)", (uname,))
        except Exception:
            pass
        for p in tables.get("auth_account_permissions", []) or []:
            if str(p.get("username") or "").strip().lower() != uname.lower():
                continue
            module_code = str(p.get("module_code") or "").strip().zfill(2)
            if not module_code:
                continue
            execute("""
                INSERT OR REPLACE INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uname, module_code,
                str(p.get("module_name_zh") or ""), str(p.get("module_name_en") or ""),
                1 if _v105_truthy(p.get("can_view", False), False) else 0,
                1 if _v105_truthy(p.get("can_create", False), False) else 0,
                1 if _v105_truthy(p.get("can_edit", False), False) else 0,
                1 if _v105_truthy(p.get("can_delete", False), False) else 0,
                1 if _v105_truthy(p.get("can_import", False), False) else 0,
                1 if _v105_truthy(p.get("can_export", False), False) else 0,
                1 if _v105_truthy(p.get("can_backup", False), False) else 0,
                1 if _v105_truthy(p.get("can_restore", False), False) else 0,
                1 if _v105_truthy(p.get("can_manage", False), False) else 0,
                now,
            ))
    except Exception:
        pass


def authenticate(username: str, password: str) -> tuple[bool, str]:  # type: ignore[override]
    """V105: login reads 10_permissions canonical authority before SQLite cache."""
    ensure_security_schema()
    username = (username or "").strip()
    if not username:
        return False, "帳號或密碼錯誤。"
    auth_user, auth_tables = _v105_find_authority_user(username)
    row = auth_user
    source = "authority"
    if row is None:
        row = query_one("SELECT * FROM auth_users WHERE lower(username)=lower(?)", (username.lower(),)) or query_one("SELECT * FROM security_users WHERE lower(username)=lower(?)", (username.lower(),))
        source = "sqlite"
    if not row:
        log_security_event(username, "LOGIN", "FAIL", "帳號不存在")
        return False, "帳號或密碼錯誤。"
    if not _v105_truthy(row.get("is_active", row.get("啟用", row.get("啟用 / Active", True))), True):
        log_security_event(username, "LOGIN", "FAIL", "帳號停用")
        return False, "帳號已停用。"
    ok = _v105_verify_password_against_authority_row(password, row) if source == "authority" else verify_password(password, row.get("password_hash"))
    if not ok:
        if source != "authority":
            auth_user, auth_tables = _v105_find_authority_user(username)
            if auth_user and _v105_truthy(auth_user.get("is_active", True), True) and _v105_verify_password_against_authority_row(password, auth_user):
                row = auth_user
                source = "authority"
                ok = True
        if not ok:
            log_security_event(username, "LOGIN", "FAIL", "密碼錯誤")
            return False, "帳號或密碼錯誤。"
    uname = str(row.get("username") or username).strip()
    role = _v105_role_from_user(row)
    if source == "authority":
        _v105_sync_authority_login_cache(row, auth_tables, password)
    st.session_state["auth_logged_in"] = True
    st.session_state["auth_username"] = uname
    st.session_state["auth_display_name"] = str(row.get("display_name") or row.get("姓名") or row.get("姓名 / Display Name") or uname)
    st.session_state["auth_employee_id"] = str(row.get("employee_id") or row.get("工號") or row.get("工號 / Employee ID") or "")
    st.session_state["auth_roles"] = [role]
    st.session_state["auth_login_ts"] = time.time()
    st.session_state["auth_last_activity_ts"] = time.time()
    try:
        clear_permission_cache(uname)
    except Exception:
        pass
    try:
        execute("UPDATE auth_users SET last_login_at=?, updated_at=? WHERE lower(username)=lower(?)", (_now(), _now(), uname.lower()))
    except Exception:
        pass
    try:
        execute("UPDATE security_users SET last_login_at=?, updated_at=? WHERE lower(username)=lower(?)", (_now(), _now(), uname.lower()))
    except Exception:
        pass
    log_security_event(uname, "LOGIN", "SUCCESS", f"role={role};source={source}")
    return True, "登入成功。"

# ======================= END V105 CANONICAL LOGIN AUTHORITY FIX =======================


# ===================== V106 FORCE PASSWORD CHANGE AUTHORITY UI FIX =====================
# 修正：10｜權限管理勾選「強制改密碼」後，登入必須進入改密碼畫面，
#       新密碼需寫回 10_permissions canonical 權威檔與 SQLite cache。

_V106_PERMISSION_MODULE = "10_permissions"


def _v106_row_bool(row: dict, *keys: str, default: bool = False) -> bool:
    for k in keys:
        if k in row:
            return _v105_truthy(row.get(k), default) if "_v105_truthy" in globals() else bool(row.get(k))
    return default


def _v106_force_password_change_from_row(row: dict | None) -> bool:
    if not row:
        return False
    return _v106_row_bool(
        row,
        "force_password_change",
        "強制改密碼",
        "強制改密碼 / Force Change",
        "force_change",
        "must_change_password",
        default=False,
    )


def _v106_current_authority_user(username: str) -> tuple[dict | None, dict[str, list[dict]]]:
    try:
        if "_v105_find_authority_user" in globals():
            return _v105_find_authority_user(username)
    except Exception:
        pass
    return None, {}


def _v106_update_password_in_authority(username: str, new_password: str) -> dict[str, Any]:
    uname = str(username or "").strip()
    if not uname:
        return {"ok": False, "error": "missing_username"}
    now = _now()
    pwd_hash = hash_password(str(new_password or ""))
    try:
        from services.permanent_authority_service import load_tables, save_authority
        tables = load_tables(_V106_PERMISSION_MODULE, "records")
        if not isinstance(tables, dict):
            tables = {}
    except Exception:
        tables = {}
    changed = 0
    for table_name in ("auth_users", "security_users"):
        rows = tables.get(table_name, [])
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if str(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or "").strip().lower() == uname.lower():
                row["username"] = str(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or uname).strip()
                row["password_hash"] = pwd_hash
                row["password_display"] = "********"
                row["new_password"] = ""
                row["password"] = ""
                row["密碼"] = ""
                row["密碼 / Password"] = ""
                row["新密碼"] = ""
                row["新密碼 / New Password"] = ""
                row["force_password_change"] = 0
                row["強制改密碼"] = False
                row["強制改密碼 / Force Change"] = False
                row["updated_at"] = now
                changed += 1
        tables[table_name] = rows
    if changed <= 0:
        # SQLite fallback row existed but canonical row did not. Create/repair auth_users authority row.
        role = "operator"
        display_name = uname
        employee_id = ""
        email = ""
        try:
            r = query_one("SELECT * FROM auth_users WHERE lower(username)=lower(?)", (uname.lower(),)) or {}
            role = str(r.get("role_code") or role)
            display_name = str(r.get("display_name") or display_name)
            employee_id = str(r.get("employee_id") or "")
            email = str(r.get("email") or "")
        except Exception:
            pass
        rows = tables.get("auth_users", []) if isinstance(tables.get("auth_users"), list) else []
        rows.append({
            "username": uname,
            "password_hash": pwd_hash,
            "password_display": "********",
            "employee_id": employee_id,
            "display_name": display_name,
            "email": email,
            "role_code": role,
            "is_active": 1,
            "force_password_change": 0,
            "note": "V106 force password change authority repair",
            "created_at": now,
            "updated_at": now,
        })
        tables["auth_users"] = rows
        changed = 1
    try:
        from services.permanent_authority_service import save_authority
        res = save_authority(_V106_PERMISSION_MODULE, records=tables, reason="v106_force_password_change", github=True)
    except Exception as exc:
        res = {"ok": False, "error": str(exc)[:300]}
    try:
        ensure_security_schema()
        execute("UPDATE auth_users SET password_hash=?, force_password_change=0, updated_at=? WHERE lower(username)=lower(?)", (pwd_hash, now, uname.lower()))
    except Exception:
        pass
    try:
        execute("UPDATE security_users SET password_hash=?, force_password_change=0, updated_at=? WHERE lower(username)=lower(?)", (pwd_hash, now, uname.lower()))
    except Exception:
        pass
    try:
        clear_permission_cache(uname)
    except Exception:
        pass
    return {"ok": bool(res.get("ok", True)), "changed": changed, "authority": res}


try:
    _v106_prev_authenticate = authenticate
except Exception:
    _v106_prev_authenticate = None


def authenticate(username: str, password: str) -> tuple[bool, str]:  # type: ignore[override]
    ok, msg = _v106_prev_authenticate(username, password) if callable(_v106_prev_authenticate) else (False, "帳號或密碼錯誤。")
    if ok:
        uname = str(st.session_state.get("auth_username") or username or "").strip()
        row, _tables = _v106_current_authority_user(uname)
        force_change = _v106_force_password_change_from_row(row)
        if not force_change:
            try:
                dbrow = query_one("SELECT force_password_change FROM auth_users WHERE lower(username)=lower(?)", (uname.lower(),)) or query_one("SELECT force_password_change FROM security_users WHERE lower(username)=lower(?)", (uname.lower(),))
                force_change = _v106_force_password_change_from_row(dict(dbrow or {}))
            except Exception:
                pass
        st.session_state["auth_force_password_change"] = bool(force_change)
        if force_change:
            st.session_state["auth_force_password_change_username"] = uname
            return True, "登入成功，請先變更密碼。"
    return ok, msg


def _v106_render_force_password_change() -> None:
    uname = str(st.session_state.get("auth_username") or st.session_state.get("auth_force_password_change_username") or "").strip()
    st.markdown("### 🔐 首次登入 / 強制變更密碼")
    st.warning("此帳號已被 10｜權限管理設定為『強制改密碼』。完成變更前不能進入其他模組。")
    with st.form("v106_force_password_change_form", clear_on_submit=False):
        new_pwd = st.text_input("新密碼 / New Password", type="password")
        confirm_pwd = st.text_input("確認新密碼 / Confirm New Password", type="password")
        submitted = st.form_submit_button("儲存新密碼並繼續 / Save Password and Continue", type="primary", use_container_width=True)
    if submitted:
        if not new_pwd or not confirm_pwd:
            st.error("請輸入新密碼並再次確認。")
            st.stop()
        if new_pwd != confirm_pwd:
            st.error("兩次輸入的新密碼不一致。")
            st.stop()
        if len(new_pwd) < 4:
            st.error("新密碼長度至少 4 碼。")
            st.stop()
        if new_pwd.strip().lower() == uname.lower():
            st.error("新密碼不可與帳號相同。")
            st.stop()
        res = _v106_update_password_in_authority(uname, new_pwd)
        if res.get("ok"):
            st.session_state["auth_force_password_change"] = False
            st.session_state.pop("auth_force_password_change_username", None)
            log_security_event(uname, "PASSWORD_CHANGE", "SUCCESS", "force_password_change_completed", "10_permissions")
            st.success("密碼已更新並寫入權威檔。")
            st.rerun()
        else:
            st.error(f"密碼更新失敗，尚未寫入權威檔：{res.get('error') or res}")
            st.stop()
    st.stop()


try:
    _v106_prev_require_login = require_login
except Exception:
    _v106_prev_require_login = None


def require_login(module_code: str = "") -> None:  # type: ignore[override]
    ensure_security_schema()
    if not st.session_state.get("auth_logged_in"):
        render_login_form()
        st.stop()
    _check_idle_timeout()
    if st.session_state.get("auth_force_password_change"):
        _v106_render_force_password_change()
    render_user_bar(module_code)


def require_module_access(module_code: str, action: str = "can_view") -> None:  # type: ignore[override]
    require_login(module_code)
    if not check_permission(module_code, action):
        log_security_event(st.session_state.get("auth_username", ""), "PERMISSION_DENIED", "FAIL", f"{module_code}:{action}", module_code)
        st.error("權限不足：你的帳號未被授權使用此模組或功能。")
        st.stop()


require_permission = require_module_access
# =================== END V106 FORCE PASSWORD CHANGE AUTHORITY UI FIX ===================

# ========================= V125 RUNTIME PERMISSION AUTHORITY CHECK =========================
# 目的：實際進入 01~13 模組時，直接讀 10_permissions/records.json 權威檔。
# 避免 SQLite / session_state 舊快取造成「10 權限頁設定正確，但實際模組權限不足」。
_V125_PERMISSION_FILE = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json"
_V125_PERMISSION_CACHE: dict[str, Any] = {"mtime": 0.0, "tables": {}}
_V125_MODULE_ALIASES = {
    "01": "01", "01_time_record": "01", "01_time_records": "01",
    "02": "02", "02_history": "02",
    "03": "03", "03_work_orders": "03",
    "04": "04", "04_employees": "04",
    "05": "05", "05_analysis": "05",
    "06": "06", "06_logs": "06", "06_system_logs": "06",
    "07": "07", "07_missing": "07", "07_missing_records": "07",
    "08": "08", "08_daily_hours": "08",
    "09": "09", "09_persistence": "09",
    "10": "10", "10_permissions": "10",
    "11": "11", "11_login_logs": "11",
    "12": "12", "12_module_persistence": "12",
    "13": "13", "13_system_settings": "13",
}
_V125_ACTION_ALIASES = {
    "view": "can_view", "read": "can_view", "can_view": "can_view",
    "create": "can_create", "add": "can_create", "new": "can_create", "can_create": "can_create",
    "edit": "can_edit", "update": "can_edit", "finish": "can_edit", "can_edit": "can_edit",
    "delete": "can_delete", "remove": "can_delete", "can_delete": "can_delete",
    "import": "can_import", "can_import": "can_import",
    "export": "can_export", "download": "can_export", "can_export": "can_export",
    "backup": "can_backup", "can_backup": "can_backup",
    "restore": "can_restore", "can_restore": "can_restore",
    "manage": "can_manage", "admin": "can_manage", "can_manage": "can_manage",
}


def _v125_truthy(v, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        try:
            return float(v) != 0
        except Exception:
            return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on", "是", "啟用", "active", "checked", "勾選"}:
        return True
    if s in {"0", "false", "no", "n", "off", "否", "停用", "inactive", "unchecked", ""}:
        return False
    return default


def _v125_module_no(code: str) -> str:
    s = str(code or "").strip()
    if s in _V125_MODULE_ALIASES:
        return _V125_MODULE_ALIASES[s]
    if s in MODULE_CODE_TO_NO:
        return MODULE_CODE_TO_NO[s]
    if len(s) >= 2 and s[:2].isdigit():
        return s[:2]
    return s.zfill(2)


def _v125_action(action: str) -> str:
    s = str(action or "can_view").strip()
    return _V125_ACTION_ALIASES.get(s, s if s in PERMISSION_COLUMNS else "can_view")


def _v125_role_default(role: str, module_no: str) -> dict[str, bool]:
    role = str(role or "operator").strip().lower() or "operator"
    row = {c: False for c in PERMISSION_COLUMNS}
    if role == "admin":
        return {c: True for c in PERMISSION_COLUMNS}
    if role == "manager":
        for c in ("can_view", "can_create", "can_edit", "can_import", "can_export"):
            row[c] = True
    elif role == "leader":
        if module_no in {"01", "02", "04", "07", "08"}:
            row["can_view"] = True; row["can_create"] = True; row["can_edit"] = True; row["can_export"] = True
    elif role == "operator":
        if module_no in {"01", "02", "08"}:
            row["can_view"] = True
        if module_no == "01":
            row["can_create"] = True; row["can_edit"] = True
    elif role == "viewer":
        row["can_view"] = True; row["can_export"] = True
    elif role == "auditor":
        if module_no in {"02", "06", "11", "12"}:
            row["can_view"] = True; row["can_export"] = True
    return row


def _v125_load_permission_tables() -> dict[str, list[dict[str, Any]]]:
    try:
        mtime = _V125_PERMISSION_FILE.stat().st_mtime if _V125_PERMISSION_FILE.exists() else 0.0
    except Exception:
        mtime = 0.0
    if _V125_PERMISSION_CACHE.get("mtime") == mtime and isinstance(_V125_PERMISSION_CACHE.get("tables"), dict):
        return _V125_PERMISSION_CACHE.get("tables", {})  # type: ignore[return-value]
    tables: dict[str, list[dict[str, Any]]] = {}
    try:
        if _V125_PERMISSION_FILE.exists() and _V125_PERMISSION_FILE.stat().st_size > 2:
            payload = json.loads(_V125_PERMISSION_FILE.read_text(encoding="utf-8"))
            raw = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
            tables = {str(k): [dict(x) for x in v if isinstance(x, dict)] for k, v in raw.items() if isinstance(v, list)}
    except Exception:
        tables = {}
    _V125_PERMISSION_CACHE["mtime"] = mtime
    _V125_PERMISSION_CACHE["tables"] = tables
    return tables


def clear_permission_cache(username: str | None = None) -> None:  # type: ignore[override]
    _V125_PERMISSION_CACHE["mtime"] = -1.0
    _V125_PERMISSION_CACHE["tables"] = {}
    try:
        for k in list(st.session_state.keys()):
            if str(k).startswith(("_spt_perm_cache_", "_v132_perm_", "_v125_perm_")):
                st.session_state.pop(k, None)
    except Exception:
        pass


def _v125_current_user_role(username: str, tables: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any] | None, str, bool]:
    uname = str(username or "").strip().lower()
    for table in ("auth_users", "security_users"):
        for row in tables.get(table, []) or []:
            u = str(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or "").strip().lower()
            if u == uname:
                role = str(row.get("role_code") or row.get("role") or row.get("角色") or "operator").strip().lower() or "operator"
                active = _v125_truthy(row.get("is_active", row.get("啟用", row.get("啟用 / Active", True))), True)
                return row, role, active
    roles = st.session_state.get("auth_roles", []) or []
    role = str(roles[0] if roles else ("admin" if uname == "admin" else "operator")).strip().lower() or "operator"
    return None, role, True


def check_permission(module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    if not st.session_state.get("auth_logged_in"):
        return False
    username = str(st.session_state.get("auth_username", "") or "").strip()
    if not username:
        return False
    tables = _v125_load_permission_tables()
    user_row, role, active = _v125_current_user_role(username, tables)
    if username.lower() == "admin" or role == "admin" or "admin" in [str(x).lower() for x in (st.session_state.get("auth_roles", []) or [])]:
        return True
    if not active:
        return False
    module_no = _v125_module_no(module_code)
    act = _v125_action(action)
    # Prefer explicit account-module permission from 10 權限管理 authority file.
    for row in tables.get("auth_account_permissions", []) or []:
        u = str(row.get("username") or "").strip().lower()
        if u != username.lower():
            continue
        r_module = _v125_module_no(str(row.get("module_code") or ""))
        if r_module != module_no:
            continue
        if _v125_truthy(row.get("can_manage", False), False):
            return True
        return _v125_truthy(row.get(act, False), False)
    # Missing row fallback: role baseline, so operator can still enter 01/02 if matrix is incomplete.
    return bool(_v125_role_default(role, module_no).get(act, False))


def require_module_access(module_code: str, action: str = "can_view") -> None:  # type: ignore[override]
    require_login(module_code)
    if not check_permission(module_code, action):
        log_security_event(st.session_state.get("auth_username", ""), "PERMISSION_DENIED", "FAIL", f"{module_code}:{action}", module_code)
        st.error("權限不足：你的帳號未被授權使用此模組或功能。")
        st.stop()

require_permission = require_module_access
# ======================= END V125 RUNTIME PERMISSION AUTHORITY CHECK =======================


# ===================== V126 ONLINE USERS RESTORE + SESSION DISPLAY ALIGNMENT =====================
# 修正：V123/V125 若覆蓋 security_service，會把 V122 的 get_online_users 移除，造成
# pages/11_11. 登入紀錄.py 匯入失敗。此段補回在線人員 API，並每次 render_user_bar
# 校正舊版 username/current_user 鍵，避免多人同時使用時顯示到別人的帳號。
import uuid as _v126_uuid
import threading as _v126_threading

_V126_ONLINE_LOCK = _v126_threading.RLock()
_V126_ONLINE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_logs" / "online_users.json"
_V126_HEARTBEAT_MIN_SECONDS = 15


def _v126_now_ts() -> float:
    try:
        return time.time()
    except Exception:
        return 0.0


def _v126_session_id() -> str:
    sid = str(st.session_state.get("auth_session_id") or "").strip()
    if not sid:
        sid = _v126_uuid.uuid4().hex
        st.session_state["auth_session_id"] = sid
    return sid


def _v126_read_online_payload() -> dict[str, Any]:
    try:
        if _V126_ONLINE_PATH.exists() and _V126_ONLINE_PATH.stat().st_size > 0:
            data = json.loads(_V126_ONLINE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("sessions", {})
                return data
    except Exception:
        pass
    return {"version": "V126", "updated_at": _now(), "sessions": {}}


def _v126_write_online_payload(payload: dict[str, Any]) -> None:
    try:
        payload = dict(payload or {})
        payload["version"] = "V126"
        payload["updated_at"] = _now()
        _V126_ONLINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _V126_ONLINE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(_V126_ONLINE_PATH)
    except Exception:
        pass


def _v126_normalize_identity_session_keys() -> None:
    if not st.session_state.get("auth_logged_in"):
        return
    username = str(st.session_state.get("auth_username") or "").strip()
    display_name = str(st.session_state.get("auth_display_name") or username).strip()
    employee_id = str(st.session_state.get("auth_employee_id") or "").strip()
    roles = st.session_state.get("auth_roles", []) or []
    if not isinstance(roles, list):
        roles = [str(roles)]
    if username:
        st.session_state["username"] = username
        st.session_state["current_username"] = username
        st.session_state["login_username"] = username
        st.session_state["auth_user"] = username
        st.session_state["display_name"] = display_name
        st.session_state["current_user"] = {
            "username": username,
            "display_name": display_name,
            "employee_id": employee_id,
            "roles": list(roles),
        }


def update_online_user(module_code: str = "", event: str = "heartbeat") -> None:
    if not st.session_state.get("auth_logged_in"):
        return
    username = str(st.session_state.get("auth_username") or "").strip()
    if not username:
        return
    sid = _v126_session_id()
    now_ts = _v126_now_ts()
    # Heartbeat 降頻；切換模組、登入、登出仍會立即寫入。
    last_hb = float(st.session_state.get("_v126_online_last_write_ts", 0) or 0)
    last_mod = str(st.session_state.get("_v126_online_last_module", "") or "")
    if event == "heartbeat" and last_hb and now_ts - last_hb < _V126_HEARTBEAT_MIN_SECONDS and last_mod == str(module_code or ""):
        return
    roles = st.session_state.get("auth_roles", []) or []
    role_text = ",".join(roles) if isinstance(roles, list) else str(roles)
    with _V126_ONLINE_LOCK:
        payload = _v126_read_online_payload()
        sessions = payload.get("sessions") if isinstance(payload.get("sessions"), dict) else {}
        # 清除 24 小時以上的離線/stale session，避免在線清單膨脹。
        for old_sid, old_row in list(sessions.items()):
            try:
                if str(old_row.get("status") or "") != "online" and now_ts - float(old_row.get("last_seen_ts", 0) or 0) > 86400:
                    sessions.pop(old_sid, None)
            except Exception:
                pass
        old = sessions.get(sid, {}) if isinstance(sessions.get(sid), dict) else {}
        login_time = old.get("login_time") or st.session_state.get("auth_login_time_text") or _now()
        sessions[sid] = {
            "session_id": sid,
            "username": username,
            "display_name": str(st.session_state.get("auth_display_name") or username),
            "employee_id": str(st.session_state.get("auth_employee_id") or ""),
            "roles": role_text,
            "module_code": module_code or old.get("module_code", ""),
            "login_time": login_time,
            "last_seen": _now(),
            "last_seen_ts": now_ts,
            "idle_seconds": int(now_ts - float(st.session_state.get("auth_last_activity_ts", now_ts) or now_ts)),
            "status": "online",
            "event": event,
        }
        payload["sessions"] = sessions
        _v126_write_online_payload(payload)
        st.session_state["_v126_online_last_write_ts"] = now_ts
        st.session_state["_v126_online_last_module"] = str(module_code or "")


def mark_online_user_offline(reason: str = "logout") -> None:
    sid = str(st.session_state.get("auth_session_id") or "").strip()
    if not sid:
        return
    with _V126_ONLINE_LOCK:
        payload = _v126_read_online_payload()
        sessions = payload.get("sessions") if isinstance(payload.get("sessions"), dict) else {}
        row = sessions.get(sid)
        if isinstance(row, dict):
            row["status"] = "offline"
            row["logout_time"] = _now()
            row["last_seen"] = _now()
            row["last_seen_ts"] = _v126_now_ts()
            row["event"] = reason
            sessions[sid] = row
            payload["sessions"] = sessions
            _v126_write_online_payload(payload)


def get_online_users(stale_minutes: int | None = None) -> pd.DataFrame:
    try:
        stale = int(stale_minutes) if stale_minutes else max(int(get_idle_timeout_minutes()) * 2, 30)
    except Exception:
        stale = 30
    now_ts = _v126_now_ts()
    payload = _v126_read_online_payload()
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), dict) else {}
    rows: list[dict[str, Any]] = []
    changed = False
    for sid, row in list(sessions.items()):
        if not isinstance(row, dict):
            continue
        last_ts = float(row.get("last_seen_ts", 0) or 0)
        age_min = (now_ts - last_ts) / 60 if last_ts else 999999
        status = str(row.get("status") or "online")
        if status == "online" and age_min <= stale:
            rows.append({
                "帳號 / Username": row.get("username", ""),
                "姓名 / Name": row.get("display_name", ""),
                "工號 / Employee ID": row.get("employee_id", ""),
                "角色 / Roles": row.get("roles", ""),
                "目前模組 / Current Module": row.get("module_code", ""),
                "登入時間 / Login Time": row.get("login_time", ""),
                "最後活動 / Last Seen": row.get("last_seen", ""),
                "閒置秒數 / Idle Seconds": int(row.get("idle_seconds", 0) or 0),
                "Session ID": str(row.get("session_id", sid))[:12],
            })
        elif status == "online" and age_min > stale:
            row["status"] = "stale"
            row["event"] = "stale_timeout"
            sessions[sid] = row
            changed = True
    if changed:
        payload["sessions"] = sessions
        _v126_write_online_payload(payload)
    return pd.DataFrame(rows)


try:
    _v126_prev_authenticate = authenticate
except Exception:
    _v126_prev_authenticate = None


def authenticate(username: str, password: str) -> tuple[bool, str]:  # type: ignore[override]
    # 同一瀏覽器切換帳號時，清掉上一個人的舊身份鍵，避免顯示到前一位登入者。
    if st.session_state.get("auth_username") and str(st.session_state.get("auth_username")) != str(username or "").strip():
        try:
            mark_online_user_offline("switch_account")
        except Exception:
            pass
        for k in list(st.session_state.keys()):
            if k.startswith("auth_") or k.startswith("_spt_perm_cache_") or k in {"username", "current_username", "login_username", "auth_user", "current_user", "display_name"}:
                st.session_state.pop(k, None)
    ok, msg = _v126_prev_authenticate(username, password) if callable(_v126_prev_authenticate) else (False, "帳號或密碼錯誤。")
    if ok:
        st.session_state["auth_session_id"] = _v126_uuid.uuid4().hex
        st.session_state["auth_login_time_text"] = _now()
        _v126_normalize_identity_session_keys()
        update_online_user("login", "login")
    return ok, msg


try:
    _v126_prev_logout = logout
except Exception:
    _v126_prev_logout = None


def logout(reason: str = "使用者登出") -> None:  # type: ignore[override]
    # V133：登出前先盡量補送 01/02 工時權威檔，降低人員按完開始/結束後
    # 立刻登出、網路慢導致 GitHub 背景發布未完成的資料遺失風險。
    try:
        from services.time_record_service import flush_time_record_authority_upload_now
        flush_time_record_authority_upload_now("logout_v133_time_authority_flush")
    except Exception:
        pass
    try:
        mark_online_user_offline(reason)
    except Exception:
        pass
    if callable(_v126_prev_logout):
        _v126_prev_logout(reason)
    else:
        for k in list(st.session_state.keys()):
            if k.startswith("auth_"):
                del st.session_state[k]


try:
    _v126_prev_render_user_bar = render_user_bar
except Exception:
    _v126_prev_render_user_bar = None


def render_user_bar(module_code: str = "") -> None:  # type: ignore[override]
    _v126_normalize_identity_session_keys()
    try:
        update_online_user(module_code or "", "heartbeat")
    except Exception:
        pass
    if callable(_v126_prev_render_user_bar):
        return _v126_prev_render_user_bar(module_code)

# =================== END V126 ONLINE USERS RESTORE + SESSION DISPLAY ALIGNMENT ===================

# ===================== V132 LOGIN PERSONNEL AUTHORITY WRITE-THROUGH FIX =====================
# 修正：登入/登出/權限不足等安全事件原本只穩定寫到 security_login_logs，
#       11｜登入紀錄主要讀 login_logs + canonical records.json，因此會看起來
#       「沒有確實執行登入人員紀錄」或只在進入 11 頁時才補一筆。
# 重點：保留原 SQLite security_login_logs 相容寫入，額外立即寫入
#       services.audit_log_service.record_login_log，該函式會同步 canonical 權威檔。
try:
    _v132_prev_log_security_event = log_security_event
except Exception:  # pragma: no cover
    _v132_prev_log_security_event = None


def _v132_txt(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in {"none", "nan", "nat"}:
        return ""
    return s


def _v132_resolve_login_identity(username: str = "") -> dict[str, str]:
    """Resolve display_name / employee_id from current session first, then 10權限權威檔, then SQLite.

    This prevents 11 login log rows from showing empty or wrong display_name when the event is
    written before/after session state changes, and keeps failure events safe.
    """
    uname = _v132_txt(username or st.session_state.get("auth_username") or st.session_state.get("username"))
    display = _v132_txt(st.session_state.get("auth_display_name") or st.session_state.get("display_name"))
    employee_id = _v132_txt(st.session_state.get("auth_employee_id"))
    roles = st.session_state.get("auth_roles", []) if "st" in globals() else []
    if isinstance(roles, list):
        role_text = ",".join([_v132_txt(x) for x in roles if _v132_txt(x)])
    else:
        role_text = _v132_txt(roles)

    if uname and (not display or not employee_id or not role_text):
        # Prefer the 10_permissions canonical authority used by 權限管理.
        try:
            from services.permanent_authority_service import load_authority
            payload = load_authority("10_permissions", "records")
            tables = payload.get("tables") if isinstance(payload, dict) and isinstance(payload.get("tables"), dict) else {}
            candidate_tables = [
                tables.get("users"), tables.get("auth_users"), tables.get("account_master"),
                tables.get("accounts"), tables.get("帳號清單"), tables.get("帳號密碼總表"),
            ]
            for rows in candidate_tables:
                if not isinstance(rows, list):
                    continue
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    ru = _v132_txt(r.get("username") or r.get("帳號") or r.get("帳號 / Username") or r.get("user"))
                    if ru and ru.lower() == uname.lower():
                        display = display or _v132_txt(r.get("display_name") or r.get("姓名") or r.get("姓名 / Display Name") or r.get("name"))
                        employee_id = employee_id or _v132_txt(r.get("employee_id") or r.get("工號") or r.get("工號 / Employee ID"))
                        role_text = role_text or _v132_txt(r.get("role_code") or r.get("角色") or r.get("角色 / Role") or r.get("role"))
                        raise StopIteration
        except StopIteration:
            pass
        except Exception:
            pass

    if uname and (not display or not employee_id or not role_text):
        # SQLite fallback only; do not let it override current session/canonical data.
        try:
            row = query_one("SELECT username, display_name, employee_id, role_code FROM auth_users WHERE lower(username)=lower(?)", (uname,)) or \
                  query_one("SELECT username, display_name, employee_id, role_code FROM security_users WHERE lower(username)=lower(?)", (uname,))
            if row:
                display = display or _v132_txt(row.get("display_name"))
                employee_id = employee_id or _v132_txt(row.get("employee_id"))
                role_text = role_text or _v132_txt(row.get("role_code"))
        except Exception:
            pass
    return {
        "username": uname,
        "display_name": display or uname,
        "employee_id": employee_id,
        "roles": role_text,
    }


def log_security_event(username: str | None, event_type: str, result: str, message: str = "", module_code: str = "", idle_seconds: int | None = None) -> None:  # type: ignore[override]
    """Write security event to both legacy security_login_logs and canonical 11_login_logs.

    11｜登入紀錄 uses login_logs/canonical authority.  The legacy function only wrote
    security_login_logs, which caused missing or delayed rows.  This final override keeps
    compatibility while making the login record immediately visible and persistent.
    """
    identity = _v132_resolve_login_identity(username or "")
    uname = identity.get("username") or _v132_txt(username)
    norm_event = _v132_txt(event_type or "LOGIN").upper()
    norm_result = _v132_txt(result or "SUCCESS").upper()
    msg = _v132_txt(message)
    if identity.get("employee_id") and "employee_id=" not in msg:
        msg = (msg + "; " if msg else "") + f"employee_id={identity.get('employee_id')}"
    if identity.get("roles") and "role=" not in msg and "roles=" not in msg:
        msg = (msg + "; " if msg else "") + f"roles={identity.get('roles')}"

    # 1) Keep existing security_login_logs behavior for compatibility.
    try:
        if callable(_v132_prev_log_security_event):
            _v132_prev_log_security_event(uname, norm_event, norm_result, msg, module_code, idle_seconds)
    except Exception:
        pass

    # 2) Write-through to Page 11 canonical authority immediately.
    try:
        from services.audit_log_service import record_login_log
        event_time = _now()
        record_login_log(
            username=uname,
            display_name=identity.get("display_name") or uname,
            event_type=norm_event,
            result=norm_result,
            message=msg,
            module_code=module_code or ("LOGIN" if norm_event == "LOGIN" else ""),
            login_time=event_time,
            logout_time=event_time if norm_event in {"LOGOUT", "AUTO_LOGOUT", "POST_RECORD_LOGOUT", "SESSION_TIMEOUT"} else "",
            idle_seconds=idle_seconds,
            user_agent="streamlit",
            employee_id=identity.get("employee_id", ""),
            roles=identity.get("roles", ""),
        )
        # Avoid duplicate auto_record_session_login when the user later opens page 11.
        if norm_event == "LOGIN" and norm_result in {"SUCCESS", "OK", "INFO"} and uname:
            try:
                st.session_state[f"_spt_login_recorded_{uname}"] = True
            except Exception:
                pass
    except Exception:
        # Never block login because audit write failed.
        pass

# =================== END V132 LOGIN PERSONNEL AUTHORITY WRITE-THROUGH FIX ===================

# ===================== V142 HARD GUARD FOR 10 PERMISSION MANAGEMENT =====================
# 問題修正：10｜權限管理是權限來源本體，不能只依賴一般 can_view/can_manage 快取或舊 session。
# 曾出現 operator 帳號仍可進入 10 權限管理，原因可能是：
# - session_state / SQLite / 舊權限快取殘留；
# - 權限表缺帳號列時 fallback 到角色預設；
# - 權限檔與登入帳號來源不同步；
# - Streamlit rerun 後頁面只靠一般 module permission 判斷。
# V142：10 權限管理採用「權威帳號角色」硬性判斷，只允許 role_code=admin 或 username=admin。
#       不再讓 operator / leader / manager / viewer / auditor 因快取、can_view、can_manage 舊值誤入。

try:
    _v142_prev_check_permission = check_permission
except Exception:  # pragma: no cover
    _v142_prev_check_permission = None
try:
    _v142_prev_require_module_access = require_module_access
except Exception:  # pragma: no cover
    _v142_prev_require_module_access = None

_V142_PERMISSION_MODULE_NOS = {"10"}


def _v142_clean_text(value) -> str:
    try:
        if value is None:
            return ""
        s = str(value).strip()
        if s.lower() in {"none", "nan", "nat", "null", "<na>"}:
            return ""
        return s
    except Exception:
        return ""


def _v142_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    try:
        if isinstance(value, (int, float)):
            return float(value) != 0
    except Exception:
        pass
    s = _v142_clean_text(value).lower()
    if s in {"1", "true", "t", "yes", "y", "on", "啟用", "是", "active", "checked", "勾選"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off", "停用", "否", "inactive", "unchecked", ""}:
        return False
    return default


def _v142_module_no(module_code: str) -> str:
    try:
        if "_v125_module_no" in globals():
            return _v125_module_no(module_code)  # type: ignore[name-defined]
    except Exception:
        pass
    s = _v142_clean_text(module_code)
    aliases = {
        "10_permissions": "10", "permissions": "10", "permission": "10",
        "權限管理": "10", "10": "10",
    }
    if s in aliases:
        return aliases[s]
    if len(s) >= 2 and s[:2].isdigit():
        return s[:2]
    return s.zfill(2)


def _v142_load_permission_tables_direct() -> dict:
    """Read 10_permissions authority records directly, bypassing runtime permission cache."""
    paths = []
    try:
        paths.append(PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json")
        paths.append(PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_records.json")
        paths.append(PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json")
    except Exception:
        return {}
    for p in paths:
        try:
            if p.exists() and p.stat().st_size > 2:
                payload = json.loads(p.read_text(encoding="utf-8"))
                tables = payload.get("tables") if isinstance(payload, dict) and isinstance(payload.get("tables"), dict) else {}
                if tables:
                    return tables
        except Exception:
            continue
    return {}


def _v142_authoritative_user_role(username: str) -> tuple[str, bool]:
    """Return (role_code, active) from the authority account master, then SQLite fallback.

    This intentionally does NOT trust st.session_state['auth_roles'] for module 10,
    because session/cache leftovers are exactly what can let the wrong user into 10.
    """
    uname = _v142_clean_text(username).lower()
    if not uname:
        return "", False

    tables = _v142_load_permission_tables_direct()
    for table_name in ("auth_users", "security_users", "users", "account_master", "accounts"):
        rows = tables.get(table_name, []) if isinstance(tables, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            ru = _v142_clean_text(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or row.get("user")).lower()
            if ru != uname:
                continue
            role = _v142_clean_text(row.get("role_code") or row.get("role") or row.get("角色") or row.get("角色 / Role")).lower()
            active = _v142_bool(row.get("is_active", row.get("啟用", row.get("啟用 / Active", True))), True)
            return role or "operator", bool(active)

    # SQLite fallback only if authority file does not contain the account.
    # Still never trusts session role for 10 權限管理.
    try:
        row = query_one("SELECT role_code, is_active FROM auth_users WHERE lower(username)=lower(?)", (uname,)) or {}
        if row:
            return _v142_clean_text(row.get("role_code")).lower() or "operator", _v142_bool(row.get("is_active"), False)
    except Exception:
        pass
    try:
        row = query_one("SELECT role_code, is_active FROM security_users WHERE lower(username)=lower(?)", (uname,)) or {}
        if row:
            return _v142_clean_text(row.get("role_code")).lower() or "operator", _v142_bool(row.get("is_active"), False)
    except Exception:
        pass

    # Fail closed for all non-admin accounts.  For emergency bootstrap, the literal
    # admin login remains allowed after successful login.
    if uname == "admin":
        return "admin", True
    return "", False


def _v142_is_permission_management_admin(username: str | None = None) -> bool:
    uname = _v142_clean_text(username or st.session_state.get("auth_username", "")).lower()
    if not uname:
        return False
    role, active = _v142_authoritative_user_role(uname)
    if not active:
        return False
    return bool(uname == "admin" or role == "admin")


def check_permission(module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    module_no = _v142_module_no(module_code)
    if module_no in _V142_PERMISSION_MODULE_NOS:
        # 10 權限管理：硬性只允許權威帳號角色 admin。
        return _v142_is_permission_management_admin(st.session_state.get("auth_username", ""))
    if callable(_v142_prev_check_permission):
        return bool(_v142_prev_check_permission(module_code, action))
    return False


def require_module_access(module_code: str, action: str = "can_view") -> None:  # type: ignore[override]
    require_login(module_code)
    module_no = _v142_module_no(module_code)
    if module_no in _V142_PERMISSION_MODULE_NOS and not _v142_is_permission_management_admin(st.session_state.get("auth_username", "")):
        try:
            log_security_event(st.session_state.get("auth_username", ""), "PERMISSION_DENIED", "FAIL", f"V142 hard deny {module_code}:{action}; role must be admin", module_code)
        except Exception:
            pass
        st.error("權限不足：10. 權限管理只允許系統管理員（admin 角色）進入。")
        st.stop()
    if not check_permission(module_code, action):
        try:
            log_security_event(st.session_state.get("auth_username", ""), "PERMISSION_DENIED", "FAIL", f"{module_code}:{action}", module_code)
        except Exception:
            pass
        st.error("權限不足：你的帳號未被授權使用此模組或功能。")
        st.stop()


require_permission = require_module_access
# =================== END V142 HARD GUARD FOR 10 PERMISSION MANAGEMENT ===================
