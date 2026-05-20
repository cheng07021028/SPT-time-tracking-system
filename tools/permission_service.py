# -*- coding: utf-8 -*-
"""
SPT Time Tracking - Permission Service V1.29
帳號總表、帳號級模組權限、登入紀錄清理、永久設定匯出輔助。
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import streamlit as st
except Exception:  # tools / batch scripts may import without Streamlit context
    st = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
_PERMISSION_SCHEMA_READY = False
_PERMISSION_CACHE_TTL_SECONDS = 300

MODULES: List[Dict[str, str]] = [
    {"module_code": "01", "module_name_zh": "工時紀錄", "module_name_en": "Time Recording"},
    {"module_code": "02", "module_name_zh": "歷史紀錄", "module_name_en": "History Records"},
    {"module_code": "03", "module_name_zh": "製令管理", "module_name_en": "Work Order Management"},
    {"module_code": "04", "module_name_zh": "人員名單", "module_name_en": "Employee Master"},
    {"module_code": "05", "module_name_zh": "製令工時分析", "module_name_en": "Work Order Time Analysis"},
    {"module_code": "06", "module_name_zh": "LOG查詢", "module_name_en": "Log Inquiry"},
    {"module_code": "07", "module_name_zh": "今日未紀錄名單", "module_name_en": "Missing Records Today"},
    {"module_code": "08", "module_name_zh": "人員每日工時", "module_name_en": "Daily Employee Hours"},
    {"module_code": "09", "module_name_zh": "資料永久保存與備份", "module_name_en": "Permanent Backup"},
    {"module_code": "10", "module_name_zh": "權限管理", "module_name_en": "Permission Management"},
    {"module_code": "11", "module_name_zh": "登入紀錄", "module_name_en": "Login Logs"},
]

ACTIONS: List[Tuple[str, str, str]] = [
    ("can_view", "可進入", "View"),
    ("can_create", "新增", "Create"),
    ("can_edit", "編輯", "Edit"),
    ("can_delete", "刪除", "Delete"),
    ("can_import", "匯入", "Import"),
    ("can_export", "匯出", "Export"),
    ("can_backup", "備份", "Backup"),
    ("can_restore", "還原", "Restore"),
    ("can_manage", "管理", "Manage"),
]

DEFAULT_USERS = [
    ("admin", "Admin@1234", "系統管理員", "Admin", "admin", 1),
    ("manager", "Manager@1234", "製造主管", "Manager", "manager", 1),
    ("leader", "Leader@1234", "現場幹部", "Leader", "leader", 1),
    ("operator", "Operator@1234", "作業人員", "Operator", "operator", 1),
    ("viewer", "Viewer@1234", "查詢者", "Viewer", "viewer", 1),
    ("auditor", "Auditor@1234", "稽核", "Auditor", "auditor", 1),
]

ROLE_PRESET = {
    "admin":    {"can_view": 1, "can_create": 1, "can_edit": 1, "can_delete": 1, "can_import": 1, "can_export": 1, "can_backup": 1, "can_restore": 1, "can_manage": 1},
    "manager":  {"can_view": 1, "can_create": 1, "can_edit": 1, "can_delete": 0, "can_import": 1, "can_export": 1, "can_backup": 0, "can_restore": 0, "can_manage": 0},
    "leader":   {"can_view": 1, "can_create": 1, "can_edit": 1, "can_delete": 0, "can_import": 0, "can_export": 1, "can_backup": 0, "can_restore": 0, "can_manage": 0},
    "operator": {"can_view": 0, "can_create": 0, "can_edit": 0, "can_delete": 0, "can_import": 0, "can_export": 0, "can_backup": 0, "can_restore": 0, "can_manage": 0},
    "viewer":   {"can_view": 1, "can_create": 0, "can_edit": 0, "can_delete": 0, "can_import": 0, "can_export": 1, "can_backup": 0, "can_restore": 0, "can_manage": 0},
    "auditor":  {"can_view": 1, "can_create": 0, "can_edit": 0, "can_delete": 0, "can_import": 0, "can_export": 1, "can_backup": 0, "can_restore": 0, "can_manage": 0},
}

ROLE_DESCRIPTIONS = {
    "admin": {
        "zh": "系統管理員",
        "en": "System Administrator",
        "desc": "最高權限。可管理帳號、權限、備份、還原、刪除、匯入匯出與所有模組。建議只給系統負責人。",
    },
    "manager": {
        "zh": "製造主管",
        "en": "Manufacturing Manager",
        "desc": "可查看與管理製造資料、製令、人員、歷史工時與分析報表。刪除與還原建議額外勾選才開放。",
    },
    "leader": {
        "zh": "現場幹部",
        "en": "Line Leader",
        "desc": "可管理現場當日作業、人員在廠/出勤狀態、今日未紀錄名單與人員每日工時。",
    },
    "operator": {
        "zh": "作業人員",
        "en": "Operator",
        "desc": "主要使用工時紀錄。建議只開放自己的紀錄、開始/暫停/下班/完工，不開放主檔與備份。",
    },
    "viewer": {
        "zh": "查詢者",
        "en": "Viewer",
        "desc": "只讀權限。可看授權報表，不可新增、編輯、刪除、匯入、備份或還原。",
    },
    "auditor": {
        "zh": "稽核",
        "en": "Auditor",
        "desc": "稽核查詢。建議開放歷史紀錄、LOG、登入紀錄與匯出，不允許修改資料。",
    },
}

def _cache_get(key: str):
    if st is None:
        return None
    try:
        return st.session_state.get(key)
    except Exception:
        return None


def _cache_set(key: str, value) -> None:
    if st is None:
        return
    try:
        st.session_state[key] = value
    except Exception:
        pass


def clear_permission_runtime_cache() -> None:
    if st is None:
        return
    try:
        for k in list(st.session_state.keys()):
            if k.startswith("_v132_perm_") or k.startswith("_spt_perm_cache_"):
                st.session_state.pop(k, None)
    except Exception:
        pass


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, salt, old_digest = password_hash.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        return hash_password(password, salt).split("$", 2)[2] == old_digest
    except Exception:
        return False


def init_permission_tables(force: bool = False) -> None:
    global _PERMISSION_SCHEMA_READY
    if _PERMISSION_SCHEMA_READY and not force:
        return
    conn = connect_db()
    cur = conn.cursor()
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

    n = cur.execute("SELECT COUNT(*) AS c FROM auth_users").fetchone()["c"]
    if n == 0:
        for username, pwd, name, email, role, active in DEFAULT_USERS:
            cur.execute("""
            INSERT INTO auth_users
            (username,password_hash,password_hint,display_name,email,role_code,is_active,created_at,updated_at,note)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (username, hash_password(pwd), "預設密碼，正式使用請修改", name, email, role, active, now_text(), now_text(), "V1.29 default account"))

    cur.execute("""
    INSERT OR IGNORE INTO auth_security_settings(setting_key, setting_value, note, updated_at)
    VALUES ('idle_timeout_minutes','15','閒置自動登出分鐘數 / Idle logout minutes',?)
    """, (now_text(),))

    conn.commit()
    conn.close()
    ensure_permissions_for_all_users(force=True)
    _PERMISSION_SCHEMA_READY = True


def get_users() -> List[dict]:
    init_permission_tables()
    import time
    cache = _cache_get("_v132_perm_users_cache")
    if cache and time.time() - float(cache.get("ts", 0)) < _PERMISSION_CACHE_TTL_SECONDS:
        return cache.get("data", [])
    conn = connect_db()
    rows = conn.execute("""
        SELECT id, username,
               '********' AS password_display,
               '' AS new_password,
               employee_id, display_name, email, role_code,
               is_active, force_password_change, last_login_at, note, created_at, updated_at
        FROM auth_users
        ORDER BY username
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    _cache_set("_v132_perm_users_cache", {"ts": time.time(), "data": data})
    return data


def save_users(rows: Iterable[dict]) -> dict:
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    saved = 0
    skipped = []
    for r in rows:
        username = str(r.get("username", "")).strip()
        if not username:
            continue
        display_name = str(r.get("display_name", "")).strip() or username
        role_code = str(r.get("role_code", "operator")).strip() or "operator"
        new_password = str(r.get("new_password", "")).strip()
        exists = cur.execute("SELECT username FROM auth_users WHERE username=?", (username,)).fetchone()
        if exists:
            params = [
                str(r.get("employee_id", "")).strip(), display_name, str(r.get("email", "")).strip(),
                role_code, int(bool(r.get("is_active", True))), int(bool(r.get("force_password_change", False))),
                str(r.get("note", "")).strip(), now_text(), username
            ]
            cur.execute("""
                UPDATE auth_users
                SET employee_id=?, display_name=?, email=?, role_code=?, is_active=?,
                    force_password_change=?, note=?, updated_at=?
                WHERE username=?
            """, params)
            if new_password:
                cur.execute("UPDATE auth_users SET password_hash=?, updated_at=? WHERE username=?", (hash_password(new_password), now_text(), username))
        else:
            if not new_password:
                skipped.append(f"{username} 未設定新密碼 / new password required")
                continue
            cur.execute("""
                INSERT INTO auth_users
                (username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                username, hash_password(new_password), "由權限管理頁建立", str(r.get("employee_id", "")).strip(),
                display_name, str(r.get("email", "")).strip(), role_code, int(bool(r.get("is_active", True))),
                int(bool(r.get("force_password_change", False))), str(r.get("note", "")).strip(), now_text(), now_text()
            ))
        saved += 1
    conn.commit()
    conn.close()
    ensure_permissions_for_all_users(force=True)
    clear_permission_runtime_cache()
    return {"saved": saved, "skipped": skipped}


def delete_users(usernames: Iterable[str]) -> int:
    init_permission_tables()
    usernames = [u for u in usernames if u and u != "admin"]
    if not usernames:
        return 0
    conn = connect_db()
    cur = conn.cursor()
    for u in usernames:
        cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (u,))
        cur.execute("DELETE FROM auth_users WHERE username=?", (u,))
    conn.commit()
    conn.close()
    clear_permission_runtime_cache()
    return len(usernames)


def ensure_permissions_for_all_users(force: bool = False) -> None:
    conn = connect_db()
    cur = conn.cursor()
    users = cur.execute("SELECT username, role_code FROM auth_users").fetchall()
    for u in users:
        role = u["role_code"] or "operator"
        for m in MODULES:
            preset = ROLE_PRESET.get(role, ROLE_PRESET["operator"]).copy()
            if role == "operator" and m["module_code"] in ("01", "02", "08"):
                preset["can_view"] = 1
                if m["module_code"] == "01":
                    preset["can_create"] = 1
                    preset["can_edit"] = 1
            if role == "leader" and m["module_code"] in ("01", "02", "04", "07", "08"):
                preset["can_view"] = 1
            if role == "auditor" and m["module_code"] in ("02", "06", "11"):
                preset["can_view"] = 1
            cur.execute("""
                INSERT OR IGNORE INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                u["username"], m["module_code"], m["module_name_zh"], m["module_name_en"],
                preset["can_view"], preset["can_create"], preset["can_edit"], preset["can_delete"],
                preset["can_import"], preset["can_export"], preset["can_backup"], preset["can_restore"], preset["can_manage"], now_text()
            ))
    conn.commit()
    conn.close()


def get_account_permissions() -> List[dict]:
    init_permission_tables()
    import time
    cache = _cache_get("_v132_perm_matrix_cache")
    if cache and time.time() - float(cache.get("ts", 0)) < _PERMISSION_CACHE_TTL_SECONDS:
        return cache.get("data", [])
    conn = connect_db()
    rows = conn.execute("""
        SELECT p.username, u.display_name, u.role_code, p.module_code, p.module_name_zh, p.module_name_en,
               p.can_view, p.can_create, p.can_edit, p.can_delete, p.can_import, p.can_export,
               p.can_backup, p.can_restore, p.can_manage, p.updated_at
        FROM auth_account_permissions p
        LEFT JOIN auth_users u ON u.username = p.username
        ORDER BY p.username, CAST(p.module_code AS INTEGER)
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    _cache_set("_v132_perm_matrix_cache", {"ts": time.time(), "data": data})
    return data


def save_account_permissions(rows: Iterable[dict]) -> int:
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    saved = 0
    for r in rows:
        username = str(r.get("username", "")).strip()
        module_code = str(r.get("module_code", "")).strip().zfill(2)
        if not username or not module_code:
            continue
        module_info = next((m for m in MODULES if m["module_code"] == module_code), None)
        if not module_info:
            module_info = {"module_name_zh": str(r.get("module_name_zh", "")), "module_name_en": str(r.get("module_name_en", ""))}
        vals = {k: int(bool(r.get(k, False))) for k, _, _ in ACTIONS}
        cur.execute("""
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
            username, module_code, module_info["module_name_zh"], module_info["module_name_en"],
            vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"],
            vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text()
        ))
        saved += 1
    conn.commit()
    conn.close()
    clear_permission_runtime_cache()
    return saved


def has_permission(username: str, module_code: str, action: str = "can_view") -> bool:
    init_permission_tables()
    conn = connect_db()
    row = conn.execute("""
        SELECT p.*, u.is_active FROM auth_account_permissions p
        JOIN auth_users u ON u.username = p.username
        WHERE p.username=? AND p.module_code=?
    """, (username, str(module_code).zfill(2))).fetchone()
    conn.close()
    if not row or not row["is_active"]:
        return False
    if row["can_manage"]:
        return True
    return bool(row[action]) if action in row.keys() else False


def get_security_settings() -> Dict[str, str]:
    init_permission_tables()
    conn = connect_db()
    rows = conn.execute("SELECT setting_key, setting_value FROM auth_security_settings").fetchall()
    conn.close()
    return {r["setting_key"]: r["setting_value"] for r in rows}


def save_security_settings(settings: Dict[str, str]) -> None:
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    for k, v in settings.items():
        cur.execute("""
            INSERT INTO auth_security_settings(setting_key, setting_value, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
        """, (k, str(v), now_text()))
    conn.commit()
    conn.close()
    clear_permission_runtime_cache()


def get_login_logs(start_date: str | None = None, end_date: str | None = None) -> List[dict]:
    init_permission_tables()
    conn = connect_db()
    sql = "SELECT * FROM auth_login_logs WHERE 1=1"
    params = []
    if start_date:
        sql += " AND date(event_time) >= date(?)"
        params.append(start_date)
    if end_date:
        sql += " AND date(event_time) <= date(?)"
        params.append(end_date)
    sql += " ORDER BY event_time DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_login_logs(start_date: str, end_date: str) -> int:
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM auth_login_logs WHERE date(event_time) >= date(?) AND date(event_time) <= date(?)", (start_date, end_date))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def add_login_log(username: str, event_type: str, result: str, message: str = "", module_code: str = "", module_name: str = "") -> None:
    init_permission_tables()
    conn = connect_db()
    display = ""
    row = conn.execute("SELECT display_name FROM auth_users WHERE username=?", (username,)).fetchone()
    if row:
        display = row["display_name"]
    conn.execute("""
        INSERT INTO auth_login_logs(username,display_name,event_time,event_type,result,module_code,module_name,message)
        VALUES (?,?,?,?,?,?,?,?)
    """, (username, display, now_text(), event_type, result, module_code, module_name, message))
    conn.commit()
    conn.close()


# Backward-compatible aliases for V1.28 code that may import these names.
init_auth_tables = init_permission_tables
check_permission = has_permission
