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


def _ensure_sqlite_columns(table: str, columns: dict[str, str]) -> None:
    """Add newly introduced columns when Streamlit/GitHub keeps an older SQLite table.

    SQLite CREATE TABLE IF NOT EXISTS does not upgrade existing tables, so older
    deployments can miss can_backup/can_restore/can_manage and crash during
    default permission seeding.
    """
    try:
        existing_df = query_df(f"PRAGMA table_info({table})")
        existing = set(existing_df["name"].astype(str).tolist()) if not existing_df.empty else set()
    except Exception:
        existing = set()
    for col, ddl in columns.items():
        if col not in existing:
            try:
                execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            except Exception:
                # Ignore duplicate-column race conditions on Streamlit reruns.
                pass


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

    # V1.78: login and page permission checks must see the permanent
    # account/permission settings after GitHub/Streamlit rebuilds.
    # SQLite is runtime-only, so restore auth_users/auth_account_permissions
    # from data/persistent_state before authentication continues.
    try:
        from services.permission_service import restore_permission_settings_from_permanent_files
        restore_permission_settings_from_permanent_files(force=False)
    except Exception:
        pass

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

    for m in MODULES:
        for role_code, _, _ in ROLES:
            p = _role_perm_template(role_code, m["module_code"])
            execute("""
                INSERT OR IGNORE INTO security_module_permissions
                (role_code, module_code, module_no, module_name, module_name_en,
                 can_view, can_create, can_edit, can_delete, can_import, can_export,
                 can_backup, can_restore, can_manage, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                role_code, m["module_code"], m["module_no"], m["module_name"], m["module_name_en"],
                p["can_view"], p["can_create"], p["can_edit"], p["can_delete"], p["can_import"], p["can_export"],
                p["can_backup"], p["can_restore"], p["can_manage"], now,
            ))

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


def get_current_user() -> dict[str, Any] | None:
    if not st.session_state.get("auth_logged_in"):
        return None
    return {
        "username": st.session_state.get("auth_username", ""),
        "display_name": st.session_state.get("auth_display_name", ""),
        "roles": st.session_state.get("auth_roles", []),
    }


def _auth_user_row(username: str) -> dict[str, Any] | None:
    """Read the V1.29+ account master row used by 10｜權限管理."""
    try:
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

    roles = _user_roles(username)
    # 若帳號來自 auth_users，角色存在 role_code，不一定已同步到 security_user_roles。
    auth_role = str(row.get("role_code", "") or "").strip()
    if auth_role and auth_role not in roles:
        roles.append(auth_role)

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

    if "admin" in roles:
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
    roles = ", ".join(user.get("roles", [])) or "未設定角色"
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


# ===== V2.43 default idle timeout policy =====
# Company requirement: the built-in default idle logout is 1 minute.  Existing
# permanent files are preserved unless they contain the old unmodified default 15.
def _v243_seed_idle_timeout_one_minute() -> None:
    # V3.32: Disabled.  This legacy startup seed was the real cause of
    # 「Reboot App 後閒置自動登出又變成 1 分鐘」.
    # It overwrote missing files and even user-saved 15-minute settings with 1.
    # Security settings must only change when the user presses Apply in 10｜權限管理.
    return None

# V3.32: do not run any startup seed that changes user settings.


# ===== V3.32 idle timeout no-reset final override =====
def _v332_read_idle_timeout_from_files() -> int | None:
    """Read the newest valid idle-timeout file without treating 15 as old default.

    Earlier V2.43 logic changed 15 to 1 during import.  This final reader uses
    all known permanent paths and picks the newest valid value, so stale files do
    not override the latest user-applied setting.
    """
    candidates: list[tuple[float, int, str]] = []
    for path in _v208_idle_timeout_paths():
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            minutes = _v208_extract_idle_timeout(payload)
            if minutes is None or int(minutes) < 1:
                continue
            candidates.append((float(path.stat().st_mtime), int(minutes), str(path)))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return int(candidates[0][1])


def get_idle_timeout_minutes() -> int:  # type: ignore[override]
    """V3.32: Final no-reset source-of-truth reader for idle auto logout minutes."""
    try:
        cache = st.session_state.get("_spt_idle_timeout_cache")
        if cache:
            minutes = int(float(cache.get("minutes", 0)))
            if minutes >= 1:
                return minutes
    except Exception:
        pass

    minutes = _v332_read_idle_timeout_from_files()
    if minutes is None:
        try:
            ensure_security_schema()
            db_candidates: list[int] = []
            for table in ("auth_security_settings", "security_settings"):
                row = query_one(f"SELECT setting_value FROM {table} WHERE setting_key='idle_timeout_minutes'")
                if row and row.get("setting_value") not in (None, ""):
                    val = int(float(row.get("setting_value")))
                    if val >= 1:
                        db_candidates.append(val)
            if db_candidates:
                minutes = db_candidates[0]
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
    """V3.32: Save idle timeout to DB + all permanent JSON paths, without startup reset."""
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
