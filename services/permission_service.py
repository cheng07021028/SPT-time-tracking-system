# -*- coding: utf-8 -*-
"""
SPT Time Tracking - Permission Service V1.29
帳號總表、帳號級模組權限、登入紀錄清理、永久設定匯出輔助。
"""
from __future__ import annotations

import hashlib
import os
import json
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from services.timezone_service import now_text, now_stamp, today_text, today_date

try:
    import streamlit as st
except Exception:  # tools / batch scripts may import without Streamlit context
    st = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
_PERMISSION_SCHEMA_READY = False
_PERMISSION_CACHE_TTL_SECONDS = 300

# V97 guard: V96 direct-authority get_security_settings() uses this constant.
# It must always exist so 10｜權限管理 can open even if earlier patches are reordered.
DEFAULT_SECURITY_SETTINGS: Dict[str, str] = {
    "idle_timeout_minutes": "15",
    "ask_continue_after_record": "1",
}

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
    {"module_code": "12", "module_name_zh": "模組永久紀錄中心", "module_name_en": "Module Permanent Records"},
    {"module_code": "13", "module_name_zh": "系統設定", "module_name_en": "System Settings"},
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
    from services.timezone_service import now_text as _nt
    return _nt()


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


def _truthy(value, default: bool = False) -> bool:
    """Robust bool parser for Streamlit editors / Excel pasted text."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            return float(value) != 0
        except Exception:
            return default
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on", "啟用", "是", "可", "勾選", "checked"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off", "停用", "否", "不可", "未勾選", "unchecked", ""}:
        return False
    return default


def _auth_user_role(username: str) -> tuple[str, int]:
    try:
        conn = connect_db()
        row = conn.execute("SELECT role_code, is_active FROM auth_users WHERE username=?", (str(username or '').strip(),)).fetchone()
        conn.close()
        if row:
            return str(row["role_code"] or "").strip(), int(row["is_active"] or 0)
    except Exception:
        pass
    return "", 0


def _is_admin_account(username: str) -> bool:
    role, active = _auth_user_role(username)
    return bool(active) and role == "admin"


def _ensure_legacy_security_tables(cur) -> None:
    """Ensure legacy runtime login tables exist.

    V1.77：權限管理頁主要寫 auth_users，但登入服務曾只讀 security_users。
    這裡同步舊表，讓新舊模組都讀到同一批帳號。
    """
    cur.execute("""
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS security_user_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        role_code TEXT NOT NULL,
        created_at TEXT,
        UNIQUE(username, role_code)
    )
    """)


# ===== V1.78 permanent permission setting restore/export =====

def _json_load(path: Path) -> dict:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _permission_persistent_candidates() -> list[Path]:
    """Return newest-first permanent files that may contain auth tables.

    Streamlit Cloud does not persist SQLite.  Therefore account master,
    module permissions and security settings must be restored from JSON files
    committed/uploaded to GitHub.
    """
    root = PROJECT_ROOT
    candidates: list[Path] = []
    direct = [
        root / "data" / "persistent_state" / "spt_module_settings.json",
        root / "data" / "persistent_state" / "spt_permanent_state.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
    ]
    candidates.extend([p for p in direct if p.exists()])
    for pattern in [
        "data/persistent_state/history/spt_module_settings_*.json",
        "data/persistent_state/history/spt_permanent_state_*.json",
        "data/persistent_modules/10_permissions/history/10_permissions_settings_*.json",
        "data/persistent_modules/10_permissions/history/10_permissions_records_*.json",
    ]:
        candidates.extend(root.glob(pattern))
    # newest first, remove duplicates
    uniq: dict[str, Path] = {}
    for p in candidates:
        uniq[str(p)] = p
    return sorted(uniq.values(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)


def _tables_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("tables")
    if isinstance(raw, dict):
        return raw
    # Small security-only file created by _persist_security_settings_files.
    sec = payload.get("security_settings")
    if isinstance(sec, dict):
        return {"auth_security_settings": [
            {"setting_key": str(k), "setting_value": str(v), "note": "restored from permanent security file", "updated_at": now_text()}
            for k, v in sec.items()
        ]}
    return {}


def _insert_or_replace_rows(cur, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    info = cur.execute(f'PRAGMA table_info("{table}")').fetchall()
    cols = [str(r[1]) for r in info]
    if not cols:
        return 0
    insert_cols = [c for c in cols if c != "id"]
    count = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        data = {c: r.get(c) for c in insert_cols if c in r}
        if not data:
            continue
        keys = list(data.keys())
        placeholders = ",".join(["?"] * len(keys))
        update_cols = [c for c in keys if c not in ("username", "module_code", "setting_key")]
        if table == "auth_users" and "username" in keys:
            conflict = "username"
        elif table == "auth_account_permissions" and {"username", "module_code"}.issubset(keys):
            conflict = "username,module_code"
        elif table in ("auth_security_settings", "security_settings") and "setting_key" in keys:
            conflict = "setting_key"
        elif table == "security_users" and "username" in keys:
            conflict = "username"
        elif table == "security_user_roles" and {"username", "role_code"}.issubset(keys):
            conflict = "username,role_code"
        else:
            continue
        if update_cols:
            update_sql = ",".join([f'{c}=excluded.{c}' for c in update_cols])
            sql = f'INSERT INTO "{table}" ({",".join(keys)}) VALUES ({placeholders}) ON CONFLICT({conflict}) DO UPDATE SET {update_sql}'
        else:
            sql = f'INSERT OR IGNORE INTO "{table}" ({",".join(keys)}) VALUES ({placeholders})'
        cur.execute(sql, [data[k] for k in keys])
        count += 1
    return count


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:
    """Restore account/permission/security settings from permanent JSON.

    This is intentionally limited to permission-related tables.  It prevents
    GitHub/Streamlit updates from resetting the permission page to defaults.
    """
    conn = connect_db()
    cur = conn.cursor()
    _ensure_legacy_security_tables(cur)
    _ensure_security_setting_tables(cur)
    current_users = int(cur.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0] or 0)
    current_perms = int(cur.execute("SELECT COUNT(*) FROM auth_account_permissions").fetchone()[0] or 0)
    restored: dict[str, int] = {}
    source = ""
    try:
        for path in _permission_persistent_candidates():
            payload = _json_load(path)
            tables = _tables_from_payload(payload)
            if not tables:
                continue
            users = tables.get("auth_users", []) or []
            perms = tables.get("auth_account_permissions", []) or []
            settings = tables.get("auth_security_settings", []) or tables.get("security_settings", []) or []
            should_restore = force
            if users and len(users) >= current_users:
                # Restore when persistent file contains all default users or extra user accounts such as spt142.
                should_restore = True
            if perms and len(perms) >= current_perms:
                should_restore = True
            if settings:
                should_restore = True
            if not should_restore:
                continue
            for table in ("auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_user_roles", "security_settings"):
                rows = tables.get(table, []) or []
                if rows:
                    restored[table] = restored.get(table, 0) + _insert_or_replace_rows(cur, table, rows)
            # Keep security_settings synchronized if only auth_security_settings exists.
            if tables.get("auth_security_settings"):
                restored["security_settings"] = restored.get("security_settings", 0) + _insert_or_replace_rows(cur, "security_settings", tables.get("auth_security_settings", []))
            source = str(path)
            break
        conn.commit()
    finally:
        conn.close()
    if restored:
        # Avoid recursive init_permission_tables() while schema initialization is still running.
        # The caller runs sync_auth_users_to_runtime_security() immediately after init.
        if _PERMISSION_SCHEMA_READY:
            try:
                sync_auth_users_to_runtime_security()
            except Exception:
                pass
        clear_permission_runtime_cache()
    return {"ok": bool(restored), "source": source, "restored": restored}


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:
    """Export permission settings to local permanent JSON quickly.

    V2.35: Account-master save must not call GitHub upload immediately.
    GitHub Contents API can take many seconds, so this function now performs
    local permanent export only and marks the system as pending backup.  Page
    09 remains the place to manually upload to GitHub.
    """
    results: dict = {"ok": True, "reason": reason, "mode": "local_fast"}
    try:
        from services.auto_github_sync_service import export_all_local_permanent_files
        results["local_export"] = export_all_local_permanent_files(force=True, source=reason)
        results["ok"] = bool(results["local_export"].get("ok", True))
    except Exception as exc:
        results["ok"] = False
        results["local_export_error"] = str(exc)
    try:
        from services.db_service import mark_data_changed
        mark_data_changed("權限設定已變更，請到 09｜資料永久保存與備份手動備份到 GitHub。", "auth_users/auth_account_permissions")
        results["pending_backup"] = True
    except Exception as exc:
        results["pending_backup_error"] = str(exc)
    return results


def sync_auth_users_to_runtime_security(usernames: Iterable[str] | None = None) -> int:
    """Synchronize auth_users into security_users/security_user_roles.

    回傳同步帳號數。密碼 hash 直接同步，登入端 V1.77 已支援 auth_users 的 hash 格式。
    """
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    _ensure_legacy_security_tables(cur)
    params: list[str] = []
    where = ""
    if usernames:
        clean = [str(u).strip() for u in usernames if str(u).strip()]
        if clean:
            where = " WHERE username IN ({})".format(",".join(["?"] * len(clean)))
            params = clean
    rows = cur.execute("SELECT * FROM auth_users" + where, params).fetchall()
    count = 0
    for r in rows:
        username = str(r["username"]).strip()
        if not username:
            continue
        cur.execute("""
            INSERT INTO security_users
            (username,password_hash,employee_id,display_name,email,is_active,force_password_change,last_login_at,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                employee_id=excluded.employee_id,
                display_name=excluded.display_name,
                email=excluded.email,
                is_active=excluded.is_active,
                force_password_change=excluded.force_password_change,
                last_login_at=excluded.last_login_at,
                updated_at=excluded.updated_at
        """, (
            username, r["password_hash"], r["employee_id"], r["display_name"], r["email"],
            int(r["is_active"] or 0), int(r["force_password_change"] or 0), r["last_login_at"],
            r["created_at"] or now_text(), now_text(),
        ))
        role = str(r["role_code"] or "").strip()
        # auth_users.role_code is the authoritative single-role source.
        # Clear legacy role residues first to prevent displays such as admin, operator.
        cur.execute("DELETE FROM security_user_roles WHERE username=?", (username,))
        if role:
            cur.execute("INSERT OR IGNORE INTO security_user_roles(username, role_code, created_at) VALUES (?,?,?)", (username, role, now_text()))
        count += 1
    conn.commit()
    conn.close()
    clear_permission_runtime_cache()
    return count


def _ensure_auth_columns(cur, table: str, columns: dict[str, str]) -> None:
    try:
        existing = {str(row["name"]) for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        existing = set()
    for col, ddl in columns.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            except Exception:
                pass


def _migrate_permission_schema_columns(cur) -> None:
    _ensure_auth_columns(cur, "auth_users", {
        "password_hint": "TEXT",
        "employee_id": "TEXT",
        "display_name": "TEXT",
        "email": "TEXT",
        "role_code": "TEXT DEFAULT 'operator'",
        "is_active": "INTEGER DEFAULT 1",
        "force_password_change": "INTEGER DEFAULT 0",
        "last_login_at": "TEXT",
        "note": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    })
    _ensure_auth_columns(cur, "auth_account_permissions", {
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
    })
    _ensure_auth_columns(cur, "auth_security_settings", {
        "setting_value": "TEXT",
        "note": "TEXT",
        "updated_at": "TEXT",
    })
    _ensure_auth_columns(cur, "auth_login_logs", {
        "display_name": "TEXT",
        "event_time": "TEXT",
        "event_type": "TEXT",
        "result": "TEXT",
        "module_code": "TEXT",
        "module_name": "TEXT",
        "message": "TEXT",
        "ip_address": "TEXT",
        "user_agent": "TEXT",
    })


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

    _migrate_permission_schema_columns(cur)
    conn.commit()

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

    # V3.40: init must be lightweight. Do not restore permanent files or rebuild
    # all permissions during login/import. 10｜權限管理 may call force=True for
    # explicit maintenance; normal page entry must not spin forever.
    if force:
        try:
            restore_permission_settings_from_permanent_files(force=True)
        except Exception:
            pass
        ensure_permissions_for_all_users(force=True)
        try:
            sync_auth_users_to_runtime_security()
        except Exception:
            pass
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



def _role_preset_for_module(role: str, module_code: str) -> dict:
    """Return the effective default permission preset for a role/module.

    V2.06: account master role changes must immediately propagate to the
    account-module permission matrix.  Keep the same role exceptions used when
    initially seeding permission rows so the synchronized result matches the
    normal default for that role.
    """
    role = (role or "operator").strip() or "operator"
    module_code = str(module_code).zfill(2)
    preset = ROLE_PRESET.get(role, ROLE_PRESET["operator"]).copy()
    if role == "operator" and module_code in ("01", "02", "08"):
        preset["can_view"] = 1
        if module_code == "01":
            preset["can_create"] = 1
            preset["can_edit"] = 1
    if role == "leader" and module_code in ("01", "02", "04", "07", "08"):
        preset["can_view"] = 1
    if role == "auditor" and module_code in ("02", "06", "11"):
        preset["can_view"] = 1
    return preset


def sync_user_permissions_from_roles(usernames: Iterable[str], reason: str = "role_changed") -> int:
    """Overwrite selected users' module permissions from their current roles.

    This is intentionally different from ensure_permissions_for_all_users(),
    which only INSERT OR IGNOREs missing rows.  When an admin changes a user's
    role in the account master, the permission matrix must follow that new role
    immediately; otherwise the page shows a new role but still keeps the old
    module permissions.
    """
    init_permission_tables()
    target_users = sorted({str(u or "").strip() for u in usernames if str(u or "").strip()})
    if not target_users:
        return 0
    conn = connect_db()
    cur = conn.cursor()
    updated = 0
    for username in target_users:
        u = cur.execute("SELECT username, role_code FROM auth_users WHERE username=?", (username,)).fetchone()
        if not u:
            continue
        role = u["role_code"] or "operator"
        for m in MODULES:
            preset = _role_preset_for_module(role, m["module_code"])
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
                username, m["module_code"], m["module_name_zh"], m["module_name_en"],
                preset["can_view"], preset["can_create"], preset["can_edit"], preset["can_delete"],
                preset["can_import"], preset["can_export"], preset["can_backup"], preset["can_restore"], preset["can_manage"], now_text()
            ))
            updated += 1
    conn.commit()
    conn.close()
    clear_permission_runtime_cache()
    return updated

def save_users(rows: Iterable[dict]) -> dict:
    init_permission_tables()
    input_rows = list(rows)
    conn = connect_db()
    cur = conn.cursor()
    saved = 0
    skipped = []
    role_sync_users: list[str] = []
    saved_usernames: list[str] = []
    for r in input_rows:
        username = str(r.get("username", "")).strip()
        if not username:
            continue
        display_name = str(r.get("display_name", "")).strip() or username
        role_code = str(r.get("role_code", "operator")).strip() or "operator"
        new_password = str(r.get("new_password", "")).strip()
        exists = cur.execute("SELECT username, role_code FROM auth_users WHERE username=?", (username,)).fetchone()
        if exists:
            old_role = str(exists["role_code"] or "operator").strip() or "operator"
            params = [
                str(r.get("employee_id", "")).strip(), display_name, str(r.get("email", "")).strip(),
                role_code, int(_truthy(r.get("is_active", True), True)), int(_truthy(r.get("force_password_change", False), False)),
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
            if old_role != role_code:
                role_sync_users.append(username)
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
                display_name, str(r.get("email", "")).strip(), role_code, int(_truthy(r.get("is_active", True), True)),
                int(_truthy(r.get("force_password_change", False), False)), str(r.get("note", "")).strip(), now_text(), now_text()
            ))
            role_sync_users.append(username)
        saved += 1
        saved_usernames.append(username)
    conn.commit()
    conn.close()

    # First make sure missing module rows exist; then overwrite only the users
    # whose role was changed or newly created.  This keeps other users' manual
    # permission adjustments untouched while still making role changes effective.
    ensure_permissions_for_all_users(force=True)
    synced_permissions = 0
    if role_sync_users:
        synced_permissions = sync_user_permissions_from_roles(role_sync_users, reason="account_role_changed")
    try:
        sync_auth_users_to_runtime_security(saved_usernames)
    except Exception:
        pass
    clear_permission_runtime_cache()
    export_result = export_permission_settings_permanently("auth_users_saved")
    return {
        "saved": saved,
        "skipped": skipped,
        "role_synced_users": sorted(set(role_sync_users)),
        "synced_permissions": synced_permissions,
        "permanent_save": export_result,
    }


def delete_users(usernames: Iterable[str]) -> int:
    """Delete selected accounts and persist the deletion immediately.

    V3.48: Deletion is an intentional account-master write.  Older V3.41
    protection could treat a smaller user count as a reboot/default DB and
    restore the just-deleted account from JSON.  This function now returns the
    real deleted count and exports with the explicit auth_users_deleted reason,
    which the permanent export guard must allow.
    """
    init_permission_tables()
    cleaned: list[str] = []
    seen: set[str] = set()
    for u in usernames:
        name = str(u or "").strip()
        if not name or name.lower() == "admin" or name.lower() in seen:
            continue
        cleaned.append(name)
        seen.add(name.lower())
    if not cleaned:
        return 0
    conn = connect_db()
    cur = conn.cursor()
    deleted = 0
    for u in cleaned:
        cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (u,))
        cur.execute("DELETE FROM auth_users WHERE username=?", (u,))
        deleted += max(int(cur.rowcount or 0), 0)
        try:
            _ensure_legacy_security_tables(cur)
            cur.execute("DELETE FROM security_user_roles WHERE username=?", (u,))
            cur.execute("DELETE FROM security_users WHERE username=?", (u,))
        except Exception:
            pass
    conn.commit()
    conn.close()
    clear_permission_runtime_cache()
    try:
        export_permission_settings_permanently("auth_users_deleted")
    except Exception:
        pass
    return deleted


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
        vals = {k: int(_truthy(r.get(k, False), False)) for k, _, _ in ACTIONS}
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
    try:
        export_permission_settings_permanently("auth_account_permissions_saved")
    except Exception:
        pass
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
    if _is_admin_account(username):
        return True
    if row["can_manage"]:
        return True
    return bool(row[action]) if action in row.keys() else False


def _ensure_security_setting_tables(cur) -> None:
    """V1.64: keep both permission-page settings and runtime security settings in sync."""
    cur.execute("""
    CREATE TABLE IF NOT EXISTS auth_security_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        note TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS security_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        note TEXT,
        updated_at TEXT
    )
    """)


def _persist_security_settings_files(settings: Dict[str, str]) -> None:
    """V1.64: write a small permanent settings file so GitHub backup can keep security settings."""
    try:
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        state_dir = root / "data" / "persistent_state"
        mod_dir = root / "data" / "persistent_modules" / "10_permissions"
        hist_dir = mod_dir / "history"
        state_dir.mkdir(parents=True, exist_ok=True)
        mod_dir.mkdir(parents=True, exist_ok=True)
        hist_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "V1.64",
            "updated_at": now_text(),
            "security_settings": dict(settings),
        }
        (state_dir / "spt_security_settings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (mod_dir / "10_permissions_settings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (hist_dir / f"10_permissions_settings_{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_security_settings() -> Dict[str, str]:
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    _ensure_security_setting_tables(cur)
    result: Dict[str, str] = {}
    # Runtime table has priority because security_service reads it during every page load.
    for table in ("auth_security_settings", "security_settings"):
        try:
            rows = cur.execute(f"SELECT setting_key, setting_value FROM {table}").fetchall()
            for r in rows:
                result[str(r["setting_key"])] = str(r["setting_value"])
        except Exception:
            pass
    if "idle_timeout_minutes" not in result:
        result["idle_timeout_minutes"] = "15"
    if "ask_continue_after_record" not in result:
        result["ask_continue_after_record"] = "1"
    conn.close()
    return result


def save_security_settings(settings: Dict[str, str]) -> None:
    """Save security settings to both tables, session cache and permanent files.

    V1.64 fixes the old issue where 10｜權限管理 wrote auth_security_settings,
    but runtime idle logout read security_settings, so the value reverted to 15 minutes.
    """
    init_permission_tables()
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in settings.items()})

    conn = connect_db()
    cur = conn.cursor()
    _ensure_security_setting_tables(cur)
    for k, v in merged.items():
        for table in ("auth_security_settings", "security_settings"):
            cur.execute(f"""
                INSERT INTO {table}(setting_key, setting_value, note, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (k, str(v), "V1.64 synchronized security setting", now_text()))
    conn.commit()
    conn.close()

    # Update live Streamlit session immediately.
    if st is not None:
        try:
            idle = int(float(merged.get("idle_timeout_minutes", "15") or 15))
            st.session_state["_spt_idle_timeout_cache"] = {"minutes": max(1, idle), "ts": 0}
            st.session_state["spt_security_settings"] = dict(merged)
        except Exception:
            pass
    clear_permission_runtime_cache()
    _persist_security_settings_files(merged)
    try:
        from services.auto_github_sync_service import auto_sync_after_write
        auto_sync_after_write(source="security_settings_saved", force=True, archive=True)
    except Exception:
        pass


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
    # V1.37: 登入紀錄寫入後同步刷新本機永久 audit JSON。
    # 不在登入當下自動推 GitHub，避免登入頁變慢；第 09 或第 11 頁可一鍵上傳雲端。
    try:
        from services.persistence_service import safe_export_audit_after_write
        safe_export_audit_after_write()
    except Exception:
        pass


# Backward-compatible aliases for V1.28 code that may import these names.
init_auth_tables = init_permission_tables
check_permission = has_permission


# ===== V1.69 persistent security setting compatibility =====
_SECURITY_PERSISTENT_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_security_settings.json"
_SECURITY_MODULE_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json"

def _v169_load_persistent_security_settings() -> Dict[str, str]:
    """Load only real security settings from permanent JSON files.

    Some files such as spt_module_settings.json contain full module payloads
    (version/exported_at/tables/table_counts).  Older code treated the whole
    payload as settings, causing garbage keys to appear in security settings.
    """
    data: Dict[str, str] = {}
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

def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    """Read security settings with permanent JSON priority.

    This prevents idle_timeout_minutes from reverting to 15 after logout/redeploy.
    """
    init_permission_tables()
    result: Dict[str, str] = {
        "idle_timeout_minutes": "15",
        "ask_continue_after_record": "1",
    }
    conn = connect_db()
    cur = conn.cursor()
    _ensure_security_setting_tables(cur)
    for table in ("security_settings", "auth_security_settings"):
        try:
            rows = cur.execute(f"SELECT setting_key, setting_value FROM {table}").fetchall()
            for r in rows:
                result[str(r["setting_key"])] = str(r["setting_value"])
        except Exception:
            pass
    conn.close()
    # Permanent files are the source of truth across Cloud rebuilds.
    result.update(_v169_load_persistent_security_settings())
    return result

def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    init_permission_tables()
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in settings.items()})

    conn = connect_db()
    cur = conn.cursor()
    _ensure_security_setting_tables(cur)
    for k, v in merged.items():
        for table in ("auth_security_settings", "security_settings"):
            cur.execute(f"""
                INSERT INTO {table}(setting_key, setting_value, note, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (k, str(v), "V1.69 synchronized security setting", now_text()))
    conn.commit()
    conn.close()

    if st is not None:
        try:
            idle = int(float(merged.get("idle_timeout_minutes", "15") or 15))
            st.session_state["_spt_idle_timeout_cache"] = {"minutes": max(1, idle), "ts": 0}
            st.session_state["spt_security_settings"] = dict(merged)
        except Exception:
            pass
    clear_permission_runtime_cache()
    _persist_security_settings_files(merged)
    try:
        from services.auto_github_sync_service import auto_sync_after_write
        auto_sync_after_write(source="security_settings_saved_v169", force=True, archive=True)
    except Exception:
        pass


# ===== V1.99 permission/settings hardening =====
def _v199_security_setting_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [
        root / "data" / "config" / "security_settings.json",
        root / "data" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "security_settings.json",
    ]


def _v199_read_security_settings_from_files() -> Dict[str, str]:
    out: Dict[str, str] = {}
    allowed = {"idle_timeout_minutes", "ask_continue_after_record"}
    extra_idle_paths = [
        PROJECT_ROOT / "data" / "config" / "idle_timeout_settings.json",
        PROJECT_ROOT / "data" / "persistent_state" / "spt_idle_timeout_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "idle_timeout_settings.json",
    ]
    for path in _v199_security_setting_paths() + extra_idle_paths:
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
            if raw is None and isinstance(payload, dict) and payload.get("idle_timeout_minutes") is not None:
                raw = {"idle_timeout_minutes": payload.get("idle_timeout_minutes")}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if str(k) in allowed and v is not None:
                        out[str(k)] = str(v)
        except Exception:
            continue
    return out


def _v204_write_idle_timeout_files(minutes: int) -> None:
    payload = {
        "idle_timeout_minutes": int(minutes),
        "updated_at": now_text(),
        "note": "閒置自動登出分鐘數永久設定；GitHub 更新或 SQLite 重建後優先讀取此檔。",
    }
    paths = [
        PROJECT_ROOT / "data" / "config" / "idle_timeout_settings.json",
        PROJECT_ROOT / "data" / "persistent_state" / "spt_idle_timeout_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "idle_timeout_settings.json",
    ]
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _v199_write_security_settings_to_files(settings: Dict[str, str]) -> None:
    safe_settings = {
        "idle_timeout_minutes": str(settings.get("idle_timeout_minutes", "15") or "15"),
        "ask_continue_after_record": str(settings.get("ask_continue_after_record", "1") or "1"),
    }
    payload = {
        "version": "V1.99",
        "updated_at": now_text(),
        "security_settings": safe_settings,
    }
    for path in _v199_security_setting_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    """V1.99: Read idle/logout settings from DB plus permanent JSON.

    Permanent JSON is used as source of truth after Streamlit/GitHub rebuilds.
    This fixes the recurring issue where idle_timeout_minutes returned to 15.
    """
    init_permission_tables()
    result: Dict[str, str] = {
        "idle_timeout_minutes": "15",
        "ask_continue_after_record": "1",
    }
    try:
        conn = connect_db()
        cur = conn.cursor()
        _ensure_security_setting_tables(cur)
        # DB first, then permanent files override so GitHub-restored config wins.
        for table in ("security_settings", "auth_security_settings"):
            try:
                rows = cur.execute(f"SELECT setting_key, setting_value FROM {table}").fetchall()
                for r in rows:
                    if str(r["setting_key"]) in result and r["setting_value"] is not None:
                        result[str(r["setting_key"])] = str(r["setting_value"])
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    result.update(_v199_read_security_settings_from_files())
    return result


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    """V1.99: Save security settings to both DB tables and permanent files.

    The page can still upload to GitHub through 09｜資料永久保存與備份, but the
    local permanent JSON is created immediately on Apply.
    """
    init_permission_tables()
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in settings.items()})
    try:
        idle = max(1, int(float(merged.get("idle_timeout_minutes", "15") or 15)))
    except Exception:
        idle = 15
    merged["idle_timeout_minutes"] = str(idle)
    merged["ask_continue_after_record"] = "1" if str(merged.get("ask_continue_after_record", "1")) not in ("0", "False", "false") else "0"

    conn = connect_db()
    cur = conn.cursor()
    _ensure_security_setting_tables(cur)
    for k, v in merged.items():
        for table in ("auth_security_settings", "security_settings"):
            cur.execute(f"""
                INSERT INTO {table}(setting_key, setting_value, note, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
            """, (k, str(v), "V1.99 synchronized permanent security setting", now_text()))
    conn.commit()
    conn.close()

    _v199_write_security_settings_to_files(merged)
    _v204_write_idle_timeout_files(idle)
    try:
        _persist_security_settings_files(merged)
    except Exception:
        pass
    if st is not None:
        try:
            st.session_state["_spt_idle_timeout_cache"] = {"minutes": idle, "ts": 0}
            st.session_state["spt_security_settings"] = dict(merged)
        except Exception:
            pass
    clear_permission_runtime_cache()
    try:
        from services.db_service import mark_data_changed
        mark_data_changed("安全設定已更新，請到 09｜資料永久保存與備份 上傳 GitHub。", "security_settings_saved_v199")
    except Exception:
        pass


def reconcile_permission_matrix_for_current_modules() -> None:
    """V1.99: Ensure newly-added modules always appear in permission matrix.

    Existing deployed databases may not have rows for modules added later, such
    as 08_daily_hours or 13_system_settings.  This function safely inserts
    missing rows without overwriting existing user choices.
    """
    init_permission_tables()
    ensure_permissions_for_all_users(force=True)


# Keep wrappers at the very end so pages importing these names get the hardened versions.
_old_get_account_permissions_v199 = get_account_permissions

def get_account_permissions() -> List[dict]:  # type: ignore[override]
    reconcile_permission_matrix_for_current_modules()
    return _old_get_account_permissions_v199()


_old_has_permission_v199 = has_permission

def has_permission(username: str, module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    # Insert missing permission rows for newly-added modules before checking.
    try:
        reconcile_permission_matrix_for_current_modules()
    except Exception:
        pass
    return _old_has_permission_v199(username, module_code, action)

check_permission = has_permission

# ===== V2.41 startup/page-entry performance guard =====
# Earlier wrappers reconciled the full permission matrix on every permission check.
# After a module update this made page entry feel very slow because Streamlit
# reruns and pages call can_view/can_edit many times.  Reconcile only once per
# process/session unless explicitly forced by the permission-management page.
import time as _spt_perf_time
_RECONCILE_DONE_PROCESS_TS_V241 = 0.0
_RECONCILE_TTL_SECONDS_V241 = 600.0


def _v241_reconcile_recently_done() -> bool:
    now_ts = _spt_perf_time.time()
    try:
        if st is not None:
            stamp = float(st.session_state.get("_v241_permission_reconcile_ts", 0) or 0)
            if now_ts - stamp < _RECONCILE_TTL_SECONDS_V241:
                return True
    except Exception:
        pass
    try:
        global _RECONCILE_DONE_PROCESS_TS_V241
        if now_ts - float(_RECONCILE_DONE_PROCESS_TS_V241 or 0) < _RECONCILE_TTL_SECONDS_V241:
            return True
    except Exception:
        pass
    return False


def _v241_mark_reconcile_done() -> None:
    now_ts = _spt_perf_time.time()
    try:
        global _RECONCILE_DONE_PROCESS_TS_V241
        _RECONCILE_DONE_PROCESS_TS_V241 = now_ts
    except Exception:
        pass
    try:
        if st is not None:
            st.session_state["_v241_permission_reconcile_ts"] = now_ts
    except Exception:
        pass


def reconcile_permission_matrix_for_current_modules(force: bool = False) -> None:  # type: ignore[override]
    """Fast module-permission reconciliation.

    - Normal page entry: run at most once per process/session.
    - 10｜權限管理 saving account/role/module settings may call force=True.
    - Existing permissions are preserved because INSERT OR IGNORE is used by
      ensure_permissions_for_all_users().
    """
    if not force and _v241_reconcile_recently_done():
        return
    init_permission_tables()
    ensure_permissions_for_all_users(force=False)
    _v241_mark_reconcile_done()


# Override the V1.99 wrappers again so read-only page checks do not cause repeated DB writes.
def get_account_permissions() -> List[dict]:  # type: ignore[override]
    reconcile_permission_matrix_for_current_modules(force=False)
    return _old_get_account_permissions_v199()


def has_permission(username: str, module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    try:
        reconcile_permission_matrix_for_current_modules(force=False)
    except Exception:
        pass
    return _old_has_permission_v199(username, module_code, action)


check_permission = has_permission

# ===== V3.41 10｜權限管理永久檔防回原始設定守門 =====
# 重點：Reboot App 後 SQLite 若只剩預設帳號，不可覆蓋 data/persistent_modules 裡較完整的帳號主檔。
# 登入頁仍保持輕量，不在 import 時做 GitHub 或全量掃描。
_V341_DEFAULT_USERNAMES = {u[0] for u in DEFAULT_USERS}


def _v341_permission_candidate_paths() -> list[Path]:
    root = PROJECT_ROOT
    paths: list[Path] = []
    direct = [
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
        root / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        root / "data" / "persistent_modules" / "10_permissions" / "security_settings.json",
        root / "data" / "config" / "security_settings.json",
        root / "data" / "persistent_state" / "spt_security_settings.json",
        root / "data" / "persistent_state" / "spt_module_settings.json",
        root / "data" / "persistent_state" / "spt_permanent_state.json",
    ]
    paths.extend([p for p in direct if p.exists()])
    for pattern in [
        "data/persistent_modules/10_permissions/history/10_permissions_records_*.json",
        "data/persistent_modules/10_permissions/history/10_permissions_settings_*.json",
        "data/persistent_state/history/spt_module_settings_*.json",
        "data/persistent_state/history/spt_permanent_state_*.json",
    ]:
        paths.extend(root.glob(pattern))
    uniq: dict[str, Path] = {str(p): p for p in paths if p.exists()}
    return sorted(uniq.values(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)


def _v341_tables_from_payload(payload: dict) -> dict:
    tables = _tables_from_payload(payload)
    if tables:
        return tables
    if not isinstance(payload, dict):
        return {}
    out: dict = {}
    # Dedicated security_settings.json shape.
    sec = payload.get("security_settings") or payload.get("settings")
    if isinstance(sec, dict):
        out["auth_security_settings"] = [
            {"setting_key": str(k), "setting_value": str(v), "note": "V3.41 security json", "updated_at": payload.get("updated_at") or now_text()}
            for k, v in sec.items()
        ]
    return out


def _v341_permission_score(path: Path, tables: dict) -> tuple[int, int, int, int, float]:
    users = tables.get("auth_users", []) or []
    perms = tables.get("auth_account_permissions", []) or []
    settings = tables.get("auth_security_settings", []) or tables.get("security_settings", []) or []
    names = {str(u.get("username") or "").strip() for u in users if isinstance(u, dict)}
    non_default = len([n for n in names if n and n not in _V341_DEFAULT_USERNAMES])
    # 權重順序：帳號數、非預設帳號、權限矩陣、安全設定、時間。
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    return (len(names), non_default, len(perms), len(settings), mtime)


def _v341_best_permission_payload() -> tuple[Path | None, dict]:
    best_path: Path | None = None
    best_tables: dict = {}
    best_score = (-1, -1, -1, -1, -1.0)
    for p in _v341_permission_candidate_paths():
        payload = _json_load(p)
        tables = _v341_tables_from_payload(payload)
        if not tables:
            continue
        score = _v341_permission_score(p, tables)
        if score > best_score:
            best_path = p
            best_tables = tables
            best_score = score
    return best_path, best_tables


def _v341_current_auth_summary() -> dict:
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS auth_users(username TEXT UNIQUE)")
        rows = cur.execute("SELECT username FROM auth_users").fetchall()
        conn.close()
        names = {str(r["username"] or "").strip() for r in rows}
    except Exception:
        names = set()
    return {"count": len(names), "non_default": len([n for n in names if n and n not in _V341_DEFAULT_USERNAMES])}


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    """V3.41: restore 10 permissions from the richest local permanent JSON.

    不使用 GitHub 網路、不在登入頁自動呼叫；由 10/12/13 管理頁或 get_users 輕量觸發。
    """
    init_permission_tables()
    best_path, tables = _v341_best_permission_payload()
    if not best_path or not tables:
        return {"ok": False, "source": "", "restored": {}, "message": "找不到可用的 10_permissions 永久檔"}
    current = _v341_current_auth_summary()
    users = tables.get("auth_users", []) or []
    perms = tables.get("auth_account_permissions", []) or []
    settings = tables.get("auth_security_settings", []) or tables.get("security_settings", []) or []
    best_score = _v341_permission_score(best_path, tables)
    should_restore = force or current["count"] == 0 or current["count"] <= len(_V341_DEFAULT_USERNAMES) or best_score[1] > current["non_default"]
    # 即使帳號不需要還原，也允許安全設定回補，避免 idle_timeout 回預設。
    if not should_restore and not settings:
        return {"ok": False, "source": str(best_path), "restored": {}, "message": "目前帳號主檔不比永久檔少，略過還原"}
    restored: dict[str, int] = {}
    conn = connect_db(); cur = conn.cursor()
    try:
        _ensure_legacy_security_tables(cur)
        _ensure_security_setting_tables(cur)
        table_order = ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_settings"]
        for table in table_order:
            rows = tables.get(table, []) or []
            if rows and (should_restore or table in {"auth_security_settings", "security_settings"}):
                restored[table] = restored.get(table, 0) + _insert_or_replace_rows(cur, table, rows)
        if tables.get("auth_security_settings"):
            restored["security_settings"] = restored.get("security_settings", 0) + _insert_or_replace_rows(cur, "security_settings", tables.get("auth_security_settings", []))
        conn.commit()
    finally:
        conn.close()
    if restored:
        try:
            sync_auth_users_to_runtime_security()
        except Exception:
            pass
        clear_permission_runtime_cache()
    return {"ok": bool(restored), "source": str(best_path), "restored": restored, "current": current, "best_score": best_score}


_old_get_users_v341 = get_users

def get_users() -> List[dict]:  # type: ignore[override]
    # Page-level lightweight restore: only when DB appears default/empty; no GitHub calls.
    try:
        summary = _v341_current_auth_summary()
        if summary["count"] == 0 or summary["count"] <= len(_V341_DEFAULT_USERNAMES):
            best_path, tables = _v341_best_permission_payload()
            if best_path:
                score = _v341_permission_score(best_path, tables)
                # Reboot App can recreate the same number of default accounts.  Restore even
                # when counts are equal so changed passwords, disabled accounts, roles and
                # module permissions do not silently fall back to defaults.
                if score[0] >= summary["count"] and score[0] > 0:
                    restore_permission_settings_from_permanent_files(force=True)
    except Exception:
        pass
    return _old_get_users_v341()


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    """V3.48: export only 10_permissions local files with safe delete support.

    The default-only overwrite guard is kept for automatic/background exports,
    but it must not block intentional saves from 10｜權限管理.  Otherwise deleting
    an account can be reverted because the older, larger permanent JSON wins.
    """
    init_permission_tables()
    best_path, best_tables = _v341_best_permission_payload()
    current = _v341_current_auth_summary()
    intentional_reasons = {
        "auth_users_saved",
        "auth_users_deleted",
        "auth_account_permissions_saved",
        "security_settings_saved",
        "account_master_apply_save",
    }
    intentional_write = str(reason or "").strip() in intentional_reasons or str(reason or "").startswith(("manual_", "user_"))
    if (not intentional_write) and best_path and current["count"] <= len(_V341_DEFAULT_USERNAMES) and _v341_permission_score(best_path, best_tables)[0] > current["count"]:
        # DB is likely a Reboot default; restore instead of overwriting permanent data.
        return {"ok": False, "protected": True, "message": "已阻止預設帳號覆蓋較完整永久檔，並嘗試還原。", "restore": restore_permission_settings_from_permanent_files(force=True)}
    try:
        conn = connect_db(); cur = conn.cursor()
        tables: dict[str, list[dict]] = {}
        for table in ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_settings"]:
            try:
                rows = cur.execute(f'SELECT * FROM "{table}"').fetchall()
                tables[table] = [dict(r) for r in rows]
            except Exception:
                tables[table] = []
        conn.close()
        payload = {
            "version": "V3.41",
            "exported_at": now_text(),
            "reason": reason,
            "module_code": "10_permissions",
            "tables": tables,
            "table_counts": {k: len(v) for k, v in tables.items()},
        }
        base = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions"
        hist = base / "history"
        base.mkdir(parents=True, exist_ok=True); hist.mkdir(parents=True, exist_ok=True)
        for name in ["10_permissions_records.json", "10_permissions_settings.json"]:
            path = base / name
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
        hpath = hist / f"10_permissions_records_{now_stamp()}.json"
        hpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        try:
            from services.db_service import mark_data_changed
            mark_data_changed("10｜權限管理已建立本機永久檔；如需雲端備份請到 09 手動上傳 GitHub。", "10_permissions")
        except Exception:
            pass
        return {"ok": True, "mode": "local_10_permissions_only", "files": [str(base / "10_permissions_records.json"), str(base / "10_permissions_settings.json")], "table_counts": payload["table_counts"]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ===== V3.42 final permission hardening =====
# 管理員帳號必須能自由進入所有模組；文字/Excel 匯入的布林值也不可誤判。
_prev_v342_has_permission = has_permission

def has_permission(username: str, module_code: str, action: str = "can_view") -> bool:  # type: ignore[override]
    if _is_admin_account(username):
        return True
    return _prev_v342_has_permission(username, module_code, action)

check_permission = has_permission


# ===== V3.63 definitive 10-permission persistence =====
# 原因：舊版用「帳號越多越好」挑永久檔，刪除帳號後會選到舊 history，把刪掉的帳號救回來。
# V363 改為直接/latest 檔優先；使用者刪到只剩 1 個帳號也是有效設定。

def _v363_permission_direct_paths() -> list[Path]:
    direct = [
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        PROJECT_ROOT / "data" / "persistent_state" / "spt_module_settings.json",
    ]
    existing = [p for p in direct if p.exists() and p.stat().st_size > 0]
    if existing:
        return existing
    hist = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "history"
    if hist.exists():
        return sorted(hist.glob("10_permissions_records_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return []


def _v341_best_permission_payload() -> tuple[Path | None, dict]:  # type: ignore[override]
    for p in _v363_permission_direct_paths():
        payload = _json_load(p)
        tables = _v341_tables_from_payload(payload)
        if tables:
            return p, tables
    return None, {}


def _v363_upload_permission_files(reason: str) -> dict:
    try:
        from services.github_cloud_storage_service import github_config, upload_file_to_github
        if not github_config().get("token"):
            return {"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured"}
        uploads = []
        base = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions"
        for local, remote in [
            (base / "10_permissions_records.json", "data/persistent_modules/10_permissions/10_permissions_records.json"),
            (base / "10_permissions_settings.json", "data/persistent_modules/10_permissions/10_permissions_settings.json"),
            (PROJECT_ROOT / "data" / "persistent_state" / "spt_user_persistent_settings.json", "data/persistent_state/spt_user_persistent_settings.json"),
        ]:
            if local.exists() and local.stat().st_size > 0:
                uploads.append(upload_file_to_github(local, remote, f"SPT V363 permission settings {reason} {now_text()}"))
        return {"ok": all(bool(x.get("ok")) for x in uploads) if uploads else False, "uploads": uploads}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_prev_export_permission_settings_permanently_v363 = export_permission_settings_permanently

def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    res = _prev_export_permission_settings_permanently_v363(reason=reason)
    try:
        base = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json"
        payload = _json_load(base)
        if isinstance(payload, dict):
            from services.persistence_core_service import load_master_settings, save_master_settings
            master = load_master_settings()
            sec = master.get("permission_settings") if isinstance(master.get("permission_settings"), dict) else {}
            sec["10.permissions"] = payload
            master["permission_settings"] = sec
            save_master_settings(master, reason=f"v363_permission_{reason}")
    except Exception:
        pass
    try:
        res["github_upload"] = _v363_upload_permission_files(reason)
    except Exception:
        pass
    return res


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    init_permission_tables()
    best_path, tables = _v341_best_permission_payload()
    if not best_path or not tables:
        return {"ok": False, "source": "", "restored": {}, "message": "找不到可用的 10_permissions 永久檔"}
    restored: dict[str, int] = {}
    conn = connect_db(); cur = conn.cursor()
    try:
        _ensure_legacy_security_tables(cur)
        _ensure_security_setting_tables(cur)
        # Direct/latest permanent file is authoritative, including fewer users after deletion.
        if force or "auth_users" in tables:
            for table in ["auth_account_permissions", "auth_users", "security_users", "security_user_roles"]:
                try: cur.execute(f'DELETE FROM "{table}"')
                except Exception: pass
        for table in ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_settings", "security_user_roles"]:
            rows = tables.get(table, []) or []
            if rows:
                restored[table] = restored.get(table, 0) + _insert_or_replace_rows(cur, table, rows)
        if tables.get("auth_security_settings"):
            restored["security_settings"] = restored.get("security_settings", 0) + _insert_or_replace_rows(cur, "security_settings", tables.get("auth_security_settings", []))
        conn.commit()
    finally:
        conn.close()
    if restored:
        try: sync_auth_users_to_runtime_security()
        except Exception: pass
        clear_permission_runtime_cache()
    return {"ok": bool(restored), "source": str(best_path), "restored": restored, "mode": "v363_direct_latest_authoritative"}

# ===== V3.65 account delete and local-only persistence final override =====
# 原則：10｜權限管理只讀/寫直接永久檔；不掃 history、不做 GitHub、不用帳號數判斷還原。

def _v365_permission_payload_from_db(reason: str = 'permission_settings_saved') -> dict:
    conn = connect_db(); cur = conn.cursor()
    tables: dict[str, list[dict]] = {}
    for table in ['auth_users', 'auth_account_permissions', 'auth_security_settings', 'security_users', 'security_settings', 'security_user_roles']:
        try:
            rows = cur.execute(f'SELECT * FROM "{table}"').fetchall()
            tables[table] = [dict(r) for r in rows]
        except Exception:
            tables[table] = []
    conn.close()
    return {
        'version': 'V3.65',
        'exported_at': now_text(),
        'reason': reason,
        'module_code': '10_permissions',
        'tables': tables,
        'table_counts': {k: len(v) for k, v in tables.items()},
    }


def _v365_write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    tmp.replace(path)


def export_permission_settings_permanently(reason: str = 'permission_settings_saved') -> dict:  # type: ignore[override]
    """V3.65：本機輕量匯出，不連 GitHub、不掃 history、不觸發全域同步。"""
    init_permission_tables()
    payload = _v365_permission_payload_from_db(reason)
    base = PROJECT_ROOT / 'data' / 'persistent_modules' / '10_permissions'
    files = [base / '10_permissions_records.json', base / '10_permissions_settings.json']
    for p in files:
        _v365_write_json_atomic(p, payload)
    try:
        master_path = PROJECT_ROOT / 'data' / 'persistent_state' / 'spt_user_persistent_settings.json'
        master = _json_load(master_path)
        if not isinstance(master, dict):
            master = {}
        ps = master.get('permission_settings') if isinstance(master.get('permission_settings'), dict) else {}
        ps['10.permissions'] = payload
        master['permission_settings'] = ps
        master['updated_at'] = now_text()
        _v365_write_json_atomic(master_path, master)
        files.append(master_path)
    except Exception:
        pass
    clear_permission_runtime_cache()
    return {'ok': True, 'mode': 'v365_local_only', 'files': [str(p) for p in files], 'table_counts': payload.get('table_counts', {})}


def _v365_direct_permission_payload() -> tuple[Path | None, dict]:
    direct = [
        PROJECT_ROOT / 'data' / 'persistent_modules' / '10_permissions' / '10_permissions_records.json',
        PROJECT_ROOT / 'data' / 'persistent_modules' / '10_permissions' / '10_permissions_settings.json',
        PROJECT_ROOT / 'data' / 'persistent_state' / 'spt_user_persistent_settings.json',
    ]
    for p in direct:
        raw = _json_load(p)
        if not isinstance(raw, dict):
            continue
        if isinstance(raw.get('tables'), dict) and raw.get('tables', {}).get('auth_users'):
            return p, raw
        ps = raw.get('permission_settings')
        if isinstance(ps, dict):
            for v in ps.values():
                if isinstance(v, dict) and isinstance(v.get('tables'), dict) and v.get('tables', {}).get('auth_users'):
                    return p, v
    return None, {}


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    """V3.65：只從直接永久檔還原；不讀 history，避免刪除帳號又被舊檔救回。"""
    init_permission_tables()
    path, payload = _v365_direct_permission_payload()
    tables = payload.get('tables', {}) if isinstance(payload, dict) else {}
    if not path or not tables:
        return {'ok': False, 'source': '', 'restored': {}, 'message': '找不到直接永久檔'}
    restored: dict[str, int] = {}
    conn = connect_db(); cur = conn.cursor()
    try:
        _ensure_legacy_security_tables(cur)
        _ensure_security_setting_tables(cur)
        for table in ['auth_account_permissions', 'auth_users', 'security_user_roles', 'security_users']:
            try:
                cur.execute(f'DELETE FROM "{table}"')
            except Exception:
                pass
        for table in ['auth_users', 'auth_account_permissions', 'auth_security_settings', 'security_users', 'security_settings', 'security_user_roles']:
            rows = tables.get(table, []) or []
            if rows:
                restored[table] = restored.get(table, 0) + _insert_or_replace_rows(cur, table, rows)
        if tables.get('auth_security_settings'):
            restored['security_settings'] = restored.get('security_settings', 0) + _insert_or_replace_rows(cur, 'security_settings', tables.get('auth_security_settings', []))
        conn.commit()
    finally:
        conn.close()
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    clear_permission_runtime_cache()
    return {'ok': bool(restored), 'source': str(path), 'restored': restored, 'mode': 'v365_direct_only'}


def get_users() -> List[dict]:  # type: ignore[override]
    """V3.65：進入 10 頁時最多直接還原一次；不掃 history。"""
    init_permission_tables()
    if st is not None and not st.session_state.get('_v365_permission_direct_loaded'):
        try:
            restore_permission_settings_from_permanent_files(force=True)
        except Exception:
            pass
        try:
            st.session_state['_v365_permission_direct_loaded'] = True
        except Exception:
            pass
    conn = connect_db()
    rows = conn.execute('SELECT * FROM auth_users ORDER BY username').fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d['password_display'] = '********' if d.get('password_hash') else '未設定'
        d['new_password'] = ''
        out.append(d)
    return out


def delete_users(usernames: Iterable[str]) -> int:  # type: ignore[override]
    """V3.65：刪除帳號後立即以目前 DB 覆蓋直接永久檔；不再被 history 還原。"""
    init_permission_tables()
    cleaned: list[str] = []
    seen: set[str] = set()
    for u in usernames:
        name = str(u or '').strip()
        if not name or name.lower() == 'admin' or name.lower() in seen:
            continue
        cleaned.append(name); seen.add(name.lower())
    if not cleaned:
        return 0
    conn = connect_db(); cur = conn.cursor()
    deleted = 0
    try:
        _ensure_legacy_security_tables(cur)
        for u in cleaned:
            cur.execute('DELETE FROM auth_account_permissions WHERE username=?', (u,))
            cur.execute('DELETE FROM auth_users WHERE username=?', (u,))
            deleted += max(int(cur.rowcount or 0), 0)
            cur.execute('DELETE FROM security_user_roles WHERE username=?', (u,))
            cur.execute('DELETE FROM security_users WHERE username=?', (u,))
        conn.commit()
    finally:
        conn.close()
    clear_permission_runtime_cache()
    if st is not None:
        try:
            st.session_state['_v365_permission_direct_loaded'] = True
        except Exception:
            pass
    try:
        export_permission_settings_permanently('auth_users_deleted')
    except Exception:
        pass
    return deleted


# ===== V3.66 permission persistence: same direct-latest-file pattern as 03/04 =====
# 原則：10｜權限管理儲存帳號/權限後，直接寫入固定 latest JSON；
# Reboot/App 啟動時，若固定 latest JSON 存在，就以它為主，不掃 history、不用筆數比較、不跑 GitHub。

_V366_PERMISSION_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_permission_settings.json"
_V366_PERMISSION_MODULE_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json"
_V366_PERMISSION_SETTINGS_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json"
_V366_PERMISSION_RESTORE_RUNNING = False
_V366_PERMISSION_RESTORED_ONCE = False


def _v366_permission_read_json(path: Path) -> dict:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v366_permission_atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v366_permission_tables_payload(reason: str = "permission_saved") -> dict:
    init_permission_tables()
    conn = connect_db()
    try:
        tables: dict[str, list[dict]] = {}
        for table in [
            "auth_users",
            "auth_account_permissions",
            "auth_security_settings",
            "security_users",
            "security_user_roles",
            "security_settings",
        ]:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                tables[table] = [dict(r) for r in rows]
            except Exception:
                tables[table] = []
        return {
            "version": "V3.66-direct-permission-persistence",
            "exported_at": now_text(),
            "reason": reason,
            "module_key": "10_permissions",
            "module_name_zh": "權限管理",
            "module_name_en": "Permission Management",
            "description": "權限管理固定永久檔。模式比照 03/04：儲存直接寫 latest JSON，Reboot 直接讀 latest JSON，不掃 history、不用帳號數比較。",
            "tables": tables,
            "table_counts": {k: len(v) for k, v in tables.items()},
        }
    finally:
        conn.close()


def _v366_permission_direct_payload() -> dict:
    for path in [_V366_PERMISSION_MODULE_FILE, _V366_PERMISSION_STATE_FILE, _V366_PERMISSION_SETTINGS_FILE]:
        data = _v366_permission_read_json(path)
        tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
        if isinstance(tables, dict) and "auth_users" in tables:
            return data
    return {}


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    """Fast local direct export only; no GitHub, no export-all, no history scan."""
    payload = _v366_permission_tables_payload(reason)
    _v366_permission_atomic_write(_V366_PERMISSION_MODULE_FILE, payload)
    _v366_permission_atomic_write(_V366_PERMISSION_STATE_FILE, payload)
    # Keep settings file compatible with old 10 page / 09 backup center.
    _v366_permission_atomic_write(_V366_PERMISSION_SETTINGS_FILE, payload)
    try:
        from services.db_service import mark_data_changed
        mark_data_changed("10｜權限管理已變更，已寫入固定永久檔；如部署於 Streamlit Cloud，請用 09 備份到 GitHub。", "10_permissions_records")
    except Exception:
        pass
    return {"ok": True, "mode": "v366_direct", "reason": reason, "files": [str(_V366_PERMISSION_MODULE_FILE), str(_V366_PERMISSION_STATE_FILE), str(_V366_PERMISSION_SETTINGS_FILE)], "table_counts": payload.get("table_counts", {})}


def _v366_replace_table(cur, table: str, rows: list[dict]) -> int:
    if not isinstance(rows, list):
        rows = []
    info = cur.execute(f'PRAGMA table_info("{table}")').fetchall()
    cols = [str(r[1]) for r in info]
    if not cols:
        return 0
    insert_cols = [c for c in cols if c != "id"]
    cur.execute(f'DELETE FROM "{table}"')
    count = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        data = {c: r.get(c) for c in insert_cols if c in r}
        if not data:
            continue
        keys = list(data.keys())
        cur.execute(f'INSERT INTO "{table}" ({",".join(keys)}) VALUES ({",".join(["?"] * len(keys))})', [data[k] for k in keys])
        count += 1
    return count


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    """Direct restore from the fixed latest 10_permissions JSON only."""
    global _V366_PERMISSION_RESTORE_RUNNING
    if _V366_PERMISSION_RESTORE_RUNNING:
        return {"ok": False, "message": "restore already running"}
    payload = _v366_permission_direct_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    auth_rows = tables.get("auth_users") if isinstance(tables.get("auth_users"), list) else []
    # Avoid locking the app if a broken file has no accounts.
    if not auth_rows:
        return {"ok": False, "message": "no direct permission payload"}
    _V366_PERMISSION_RESTORE_RUNNING = True
    conn = connect_db()
    cur = conn.cursor()
    try:
        _ensure_legacy_security_tables(cur)
        _ensure_security_setting_tables(cur)
        restored: dict[str, int] = {}
        for table in ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_user_roles", "security_settings"]:
            try:
                restored[table] = _v366_replace_table(cur, table, tables.get(table, []) if isinstance(tables.get(table), list) else [])
            except Exception as exc:
                restored[f"{table}_error"] = str(exc)
        # Safety: if old payload lacks runtime security tables, rebuild them from auth_users after commit.
        conn.commit()
    finally:
        conn.close()
        _V366_PERMISSION_RESTORE_RUNNING = False
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    clear_permission_runtime_cache()
    return {"ok": True, "mode": "v366_direct", "source": str(_V366_PERMISSION_MODULE_FILE), "restored": restored}


_prev_v366_init_permission_tables = init_permission_tables

def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    """Initialize schema, then restore direct latest permission JSON exactly once."""
    global _V366_PERMISSION_RESTORED_ONCE, _PERMISSION_SCHEMA_READY
    _prev_v366_init_permission_tables(force=False)
    if force or not _V366_PERMISSION_RESTORED_ONCE:
        _V366_PERMISSION_RESTORED_ONCE = True
        try:
            restore_permission_settings_from_permanent_files(force=True)
        except Exception:
            pass
        _PERMISSION_SCHEMA_READY = True


# V3.66.1: export must not call the wrapped init_permission_tables(), otherwise a save may
# restore the previous JSON before it writes the new one. Use the pre-wrapper schema init only.
def _v366_permission_tables_payload(reason: str = "permission_saved") -> dict:  # type: ignore[override]
    try:
        _prev_v366_init_permission_tables(force=False)
    except Exception:
        pass
    conn = connect_db()
    try:
        tables: dict[str, list[dict]] = {}
        for table in [
            "auth_users",
            "auth_account_permissions",
            "auth_security_settings",
            "security_users",
            "security_user_roles",
            "security_settings",
        ]:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                tables[table] = [dict(r) for r in rows]
            except Exception:
                tables[table] = []
        return {
            "version": "V3.66.1-direct-permission-persistence",
            "exported_at": now_text(),
            "reason": reason,
            "module_key": "10_permissions",
            "module_name_zh": "權限管理",
            "module_name_en": "Permission Management",
            "description": "權限管理固定永久檔。模式比照 03/04：儲存直接寫 latest JSON，Reboot 直接讀 latest JSON，不掃 history、不用帳號數比較。",
            "tables": tables,
            "table_counts": {k: len(v) for k, v in tables.items()},
        }
    finally:
        conn.close()

# ===== V3.68 account deletion tombstone + latest-file authoritative restore =====
# 問題修正：刪除帳號後 Reboot 又恢復，多半是固定檔之間版本不同或舊 latest 檔先被讀取。
# V368 原則：
# 1) 儲存/刪除只寫固定 latest 檔，不掃 history、不跑 GitHub。
# 2) 還原時在固定檔中挑 exported_at 最新者，不用固定路徑優先權。
# 3) 刪除帳號會寫 tombstone；即使舊帳號檔被讀到，也不可把已刪帳號救回。
# 4) 若之後重新新增同名帳號，會自動從 tombstone 移除。

_V368_DELETED_MODULE_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "deleted_accounts.json"
_V368_DELETED_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_permission_deleted_accounts.json"


def _v368_json_load(path: Path) -> dict:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v368_atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v368_deleted_payload() -> dict:
    # 兩個固定檔以資料聯集為準。
    deleted: set[str] = set()
    latest = ""
    for p in [_V368_DELETED_MODULE_FILE, _V368_DELETED_STATE_FILE]:
        data = _v368_json_load(p)
        raw = data.get("deleted_usernames") if isinstance(data.get("deleted_usernames"), list) else []
        for u in raw:
            name = str(u or "").strip()
            if name and name.lower() != "admin":
                deleted.add(name)
        ts = str(data.get("updated_at") or "")
        if ts > latest:
            latest = ts
    return {"deleted_usernames": sorted(deleted, key=lambda x: x.lower()), "updated_at": latest}


def _v368_write_deleted_usernames(usernames: Iterable[str], mode: str = "add") -> None:
    current = set(_v368_deleted_payload().get("deleted_usernames", []))
    names = {str(u or "").strip() for u in usernames if str(u or "").strip() and str(u or "").strip().lower() != "admin"}
    if mode == "remove":
        current = {u for u in current if u.lower() not in {n.lower() for n in names}}
    else:
        by_lower = {u.lower(): u for u in current}
        for n in names:
            by_lower[n.lower()] = n
        current = set(by_lower.values())
    payload = {
        "version": "V3.68-deleted-account-tombstone",
        "updated_at": now_text(),
        "deleted_usernames": sorted(current, key=lambda x: x.lower()),
        "note": "帳號明確刪除紀錄；Reboot 還原權限固定檔時，會用此檔避免舊帳號被救回。重新新增同名帳號時會自動移除。",
    }
    _v368_atomic_write(_V368_DELETED_MODULE_FILE, payload)
    _v368_atomic_write(_V368_DELETED_STATE_FILE, payload)


def _v368_payload_score(path: Path, payload: dict) -> tuple[str, float, int]:
    ts = str(payload.get("exported_at") or payload.get("updated_at") or "")
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    users = tables.get("auth_users") if isinstance(tables.get("auth_users"), list) else []
    return (ts, mtime, len(users))


def _v368_permission_direct_candidates() -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for p in [_V366_PERMISSION_MODULE_FILE, _V366_PERMISSION_SETTINGS_FILE, _V366_PERMISSION_STATE_FILE]:
        data = _v368_json_load(p)
        if isinstance(data.get("tables"), dict) and "auth_users" in data.get("tables", {}):
            out.append((p, data))
            continue
        # 相容 master 格式：permission_settings 裡可能包多個 payload。
        ps = data.get("permission_settings") if isinstance(data.get("permission_settings"), dict) else {}
        for key, val in ps.items():
            if isinstance(val, dict) and isinstance(val.get("tables"), dict) and "auth_users" in val.get("tables", {}):
                out.append((p, val))
    return out


def _v366_permission_direct_payload() -> dict:  # type: ignore[override]
    """V3.68：固定檔中選 exported_at 最新者，並套用刪除 tombstone。"""
    candidates = _v368_permission_direct_candidates()
    if not candidates:
        return {}
    candidates = sorted(candidates, key=lambda x: _v368_payload_score(x[0], x[1]), reverse=True)
    payload = json.loads(json.dumps(candidates[0][1], ensure_ascii=False, default=str))
    deleted = {str(u or "").strip().lower() for u in _v368_deleted_payload().get("deleted_usernames", []) if str(u or "").strip()}
    if deleted and isinstance(payload.get("tables"), dict):
        tables = payload["tables"]
        def _filter(rows, user_fields=("username",)):
            if not isinstance(rows, list):
                return []
            kept = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                hit = False
                for f in user_fields:
                    name = str(r.get(f) or "").strip().lower()
                    if name and name in deleted:
                        hit = True
                        break
                if not hit:
                    kept.append(r)
            return kept
        tables["auth_users"] = _filter(tables.get("auth_users", []), ("username",))
        tables["auth_account_permissions"] = _filter(tables.get("auth_account_permissions", []), ("username",))
        tables["security_users"] = _filter(tables.get("security_users", []), ("username",))
        tables["security_user_roles"] = _filter(tables.get("security_user_roles", []), ("username",))
        payload["table_counts"] = {k: len(v) for k, v in tables.items() if isinstance(v, list)}
        payload["deleted_filter_applied"] = sorted(deleted)
    return payload


def _v368_permission_payload_from_db(reason: str = "permission_settings_saved") -> dict:
    # 只確保 schema，不觸發 v366/v368 restore。
    try:
        _prev_v366_init_permission_tables(force=False)
    except Exception:
        pass
    conn = connect_db()
    try:
        tables: dict[str, list[dict]] = {}
        for table in [
            "auth_users",
            "auth_account_permissions",
            "auth_security_settings",
            "security_users",
            "security_user_roles",
            "security_settings",
        ]:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                tables[table] = [dict(r) for r in rows]
            except Exception:
                tables[table] = []
        return {
            "version": "V3.68-direct-permission-persistence",
            "exported_at": now_text(),
            "reason": reason,
            "module_key": "10_permissions",
            "module_name_zh": "權限管理",
            "module_name_en": "Permission Management",
            "description": "帳號權限固定永久檔；刪除帳號以 tombstone 防止 Reboot 後被舊檔還原。",
            "tables": tables,
            "table_counts": {k: len(v) for k, v in tables.items()},
            "deleted_accounts": _v368_deleted_payload().get("deleted_usernames", []),
        }
    finally:
        conn.close()


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    """V3.68：固定檔直接覆蓋，不掃 history、不跑 GitHub、不觸發全域同步。"""
    payload = _v368_permission_payload_from_db(reason)
    for path in [_V366_PERMISSION_MODULE_FILE, _V366_PERMISSION_SETTINGS_FILE, _V366_PERMISSION_STATE_FILE]:
        _v368_atomic_write(path, payload)
    clear_permission_runtime_cache()
    return {
        "ok": True,
        "mode": "v368_direct_with_delete_tombstone",
        "reason": reason,
        "files": [str(_V366_PERMISSION_MODULE_FILE), str(_V366_PERMISSION_SETTINGS_FILE), str(_V366_PERMISSION_STATE_FILE)],
        "delete_tombstone_files": [str(_V368_DELETED_MODULE_FILE), str(_V368_DELETED_STATE_FILE)],
        "table_counts": payload.get("table_counts", {}),
    }


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    """V3.68：從最新固定檔還原，並套用刪除 tombstone。"""
    global _V366_PERMISSION_RESTORE_RUNNING
    if _V366_PERMISSION_RESTORE_RUNNING:
        return {"ok": False, "message": "restore already running"}
    payload = _v366_permission_direct_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    auth_rows = tables.get("auth_users") if isinstance(tables.get("auth_users"), list) else []
    if not isinstance(auth_rows, list):
        return {"ok": False, "message": "no direct permission payload"}
    _V366_PERMISSION_RESTORE_RUNNING = True
    try:
        try:
            _prev_v366_init_permission_tables(force=False)
        except Exception:
            pass
        conn = connect_db(); cur = conn.cursor()
        try:
            _ensure_legacy_security_tables(cur)
            _ensure_security_setting_tables(cur)
            restored: dict[str, int] = {}
            for table in ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_user_roles", "security_settings"]:
                try:
                    restored[table] = _v366_replace_table(cur, table, tables.get(table, []) if isinstance(tables.get(table), list) else [])
                except Exception as exc:
                    restored[f"{table}_error"] = str(exc)
            conn.commit()
        finally:
            conn.close()
        try:
            sync_auth_users_to_runtime_security()
        except Exception:
            pass
        clear_permission_runtime_cache()
        return {"ok": True, "mode": "v368_direct_latest_with_tombstone", "restored": restored, "deleted_accounts": _v368_deleted_payload().get("deleted_usernames", [])}
    finally:
        _V366_PERMISSION_RESTORE_RUNNING = False


_prev_save_users_v368 = save_users

def save_users(rows: Iterable[dict]) -> dict:  # type: ignore[override]
    """V3.68：新增/重新建立同名帳號時，移除刪除 tombstone。"""
    input_rows = list(rows)
    result = _prev_save_users_v368(input_rows)
    saved_names = [str(r.get("username") or "").strip() for r in input_rows if str(r.get("username") or "").strip()]
    if saved_names:
        try:
            _v368_write_deleted_usernames(saved_names, mode="remove")
            # 前一層 save_users 已 export 過；移除 tombstone 後再寫一次最新固定檔。
            export_permission_settings_permanently("auth_users_saved_v368")
        except Exception:
            pass
    return result


def delete_users(usernames: Iterable[str]) -> int:  # type: ignore[override]
    """V3.68：刪除帳號後立即寫固定檔與刪除 tombstone，Reboot 不可救回。"""
    try:
        _prev_v366_init_permission_tables(force=False)
    except Exception:
        pass
    cleaned: list[str] = []
    seen: set[str] = set()
    for u in usernames:
        name = str(u or "").strip()
        key = name.lower()
        if not name or key == "admin" or key in seen:
            continue
        cleaned.append(name)
        seen.add(key)
    if not cleaned:
        return 0
    conn = connect_db(); cur = conn.cursor()
    deleted = 0
    try:
        _ensure_legacy_security_tables(cur)
        for u in cleaned:
            cur.execute("DELETE FROM auth_account_permissions WHERE lower(username)=lower(?)", (u,))
            cur.execute("DELETE FROM auth_users WHERE lower(username)=lower(?)", (u,))
            deleted += max(int(cur.rowcount or 0), 0)
            cur.execute("DELETE FROM security_user_roles WHERE lower(username)=lower(?)", (u,))
            cur.execute("DELETE FROM security_users WHERE lower(username)=lower(?)", (u,))
        conn.commit()
    finally:
        conn.close()
    if deleted > 0:
        try:
            _v368_write_deleted_usernames(cleaned, mode="add")
        except Exception:
            pass
        try:
            export_permission_settings_permanently("auth_users_deleted_v368")
        except Exception:
            pass
    clear_permission_runtime_cache()
    if st is not None:
        try:
            st.session_state["_v365_permission_direct_loaded"] = True
            st.session_state["_v366_permission_delete_saved"] = now_text()
        except Exception:
            pass
    return deleted


# ===== V3.69 login safe mode: no restore during login/page bootstrap =====
# 問題：V366/V368 的 init_permission_tables() 在任何登入/權限查詢時會自動還原整包
# 10_permissions JSON 並同步 runtime tables。登入頁或首頁若多次觸發權限檢查，會像一直運算。
# 修正：初始化只做 schema/default，絕不自動 restore；只有 10｜權限管理 get_users()/手動 force 才還原。
try:
    _v369_schema_init_only = _prev_v366_init_permission_tables  # type: ignore[name-defined]
except Exception:
    _v369_schema_init_only = None


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    """V3.69: lightweight schema init only.

    - Normal login/page entry: no JSON restore, no runtime sync, no history scan.
    - 10｜權限管理 or maintenance can call force=True to restore direct latest files.
    """
    global _PERMISSION_SCHEMA_READY
    try:
        if _v369_schema_init_only is not None:
            _v369_schema_init_only(force=False)
        else:
            # Fallback to the original schema-ready behavior if this file is reorganized later.
            pass
    except Exception:
        pass
    _PERMISSION_SCHEMA_READY = True
    if force:
        try:
            restore_permission_settings_from_permanent_files(force=True)
        except Exception:
            pass

# Backward compatible aliases after final override.
init_auth_tables = init_permission_tables
check_permission = has_permission


# ===== V3.72 DIRECT LATEST PERMISSION SETTINGS LIKE 03/04 =====
# 目的：10｜權限管理改成跟 03｜製令管理、04｜人員名單一樣的固定 latest JSON 讀寫。
# - 儲存/刪除：直接寫 data/persistent_modules/10_permissions/10_permissions_records.json
# - Reboot：直接讀同一個 latest JSON
# - 不掃 history、不比帳號數、不用舊 master 檔救援、不跑 GitHub
# - 刪除後帳號數變少也是有效設定
_V372_PERMISSION_MODULE_DIR = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions"
_V372_PERMISSION_LATEST_FILE = _V372_PERMISSION_MODULE_DIR / "10_permissions_records.json"
_V372_PERMISSION_COMPAT_FILE = _V372_PERMISSION_MODULE_DIR / "10_permissions_settings.json"
_V372_PERMISSION_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_permission_settings.json"
_V372_PERMISSION_RESTORE_STATE_KEY = "_v372_permission_latest_restored"
try:
    _v372_schema_init_only = init_permission_tables  # type: ignore[name-defined]
except Exception:
    _v372_schema_init_only = None
try:
    _v372_prev_save_users = save_users  # type: ignore[name-defined]
except Exception:
    _v372_prev_save_users = None
try:
    _v372_prev_delete_users = delete_users  # type: ignore[name-defined]
except Exception:
    _v372_prev_delete_users = None
try:
    _v372_prev_save_account_permissions = save_account_permissions  # type: ignore[name-defined]
except Exception:
    _v372_prev_save_account_permissions = None


def _v372_read_json(path: Path) -> dict:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 2:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v372_atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v372_permission_read_latest() -> dict:
    for path in [_V372_PERMISSION_LATEST_FILE, _V372_PERMISSION_COMPAT_FILE, _V372_PERMISSION_STATE_FILE]:
        data = _v372_read_json(path)
        tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
        if isinstance(tables, dict) and "auth_users" in tables:
            return data
    return {}


def _v372_permission_schema_only() -> None:
    try:
        if _v372_schema_init_only is not None:
            _v372_schema_init_only(force=False)
    except TypeError:
        try:
            _v372_schema_init_only()  # type: ignore[misc]
        except Exception:
            pass
    except Exception:
        pass


def _v372_fetch_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _v372_permission_payload_from_db(reason: str = "permission_settings_saved") -> dict:
    _v372_permission_schema_only()
    conn = connect_db()
    try:
        tables = {
            "auth_users": _v372_fetch_table(conn, "auth_users"),
            "auth_account_permissions": _v372_fetch_table(conn, "auth_account_permissions"),
            "auth_security_settings": _v372_fetch_table(conn, "auth_security_settings"),
            "security_users": _v372_fetch_table(conn, "security_users"),
            "security_user_roles": _v372_fetch_table(conn, "security_user_roles"),
            "security_settings": _v372_fetch_table(conn, "security_settings"),
        }
    finally:
        conn.close()
    return {
        "version": "V3.72-direct-latest-like-03-04",
        "exported_at": now_text(),
        "reason": reason,
        "module_key": "10_permissions",
        "module_code": "10_permissions",
        "module_name_zh": "權限管理",
        "module_name_en": "Permission Management",
        "source": "permission_service_v372",
        "description": "10｜權限管理固定 latest JSON。模式比照 03/04：儲存寫 latest，Reboot 讀 same latest；刪除後帳號數變少也是有效設定。",
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items()},
        "counts": {k: len(v) for k, v in tables.items()},
    }


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    """V3.72：照 03/04 成功模式，固定 latest 檔直接覆蓋。"""
    payload = _v372_permission_payload_from_db(reason)
    for path in [_V372_PERMISSION_LATEST_FILE, _V372_PERMISSION_COMPAT_FILE, _V372_PERMISSION_STATE_FILE]:
        _v372_atomic_write(path, payload)
    clear_permission_runtime_cache()
    return {
        "ok": True,
        "mode": "v372_direct_latest_like_03_04",
        "reason": reason,
        "files": [str(_V372_PERMISSION_LATEST_FILE), str(_V372_PERMISSION_COMPAT_FILE), str(_V372_PERMISSION_STATE_FILE)],
        "table_counts": payload.get("table_counts", {}),
    }


def _v372_replace_table(cur: sqlite3.Cursor, table: str, rows: list[dict]) -> int:
    try:
        cur.execute(f'DELETE FROM "{table}"')
    except Exception:
        return 0
    if not rows:
        return 0
    count = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        clean = {str(k): v for k, v in r.items() if str(k).strip()}
        if not clean:
            continue
        cols = list(clean.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_sql = ",".join([f'"{c}"' for c in cols])
        try:
            cur.execute(f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', [clean[c] for c in cols])
            count += 1
        except Exception:
            continue
    return count


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    """V3.72：Reboot 後只讀固定 latest，不掃 history，不用帳號數猜測。"""
    payload = _v372_permission_read_latest()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or "auth_users" not in tables:
        return {"ok": False, "mode": "v372_direct_latest_like_03_04", "message": "no fixed latest permission file"}
    _v372_permission_schema_only()
    conn = connect_db(); cur = conn.cursor()
    restored: dict[str, int] = {}
    try:
        try:
            _ensure_legacy_security_tables(cur)
            _ensure_security_setting_tables(cur)
        except Exception:
            pass
        for table in ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_user_roles", "security_settings"]:
            rows = tables.get(table, []) if isinstance(tables.get(table), list) else []
            restored[table] = _v372_replace_table(cur, table, rows)
        conn.commit()
    finally:
        conn.close()
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    clear_permission_runtime_cache()
    if st is not None:
        try:
            st.session_state[_V372_PERMISSION_RESTORE_STATE_KEY] = True
        except Exception:
            pass
    return {"ok": True, "mode": "v372_direct_latest_like_03_04", "source": str(_V372_PERMISSION_LATEST_FILE), "restored": restored}


def _v372_restore_permission_once() -> None:
    if st is not None:
        try:
            if st.session_state.get(_V372_PERMISSION_RESTORE_STATE_KEY):
                return
        except Exception:
            pass
    if _v372_permission_read_latest():
        restore_permission_settings_from_permanent_files(force=True)
    if st is not None:
        try:
            st.session_state[_V372_PERMISSION_RESTORE_STATE_KEY] = True
        except Exception:
            pass


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    """V3.72：平常只建 schema；force=True 才從 latest 還原。登入頁不做重流程。"""
    _v372_permission_schema_only()
    if force:
        restore_permission_settings_from_permanent_files(force=True)


init_auth_tables = init_permission_tables


def get_users() -> List[dict]:  # type: ignore[override]
    """V3.72：10｜權限管理頁讀取帳號時，先從固定 latest 還原一次。"""
    _v372_restore_permission_once()
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT id, username,
                   '********' AS password_display,
                   '' AS new_password,
                   employee_id, display_name, email, role_code,
                   is_active, force_password_change, last_login_at, note, created_at, updated_at
            FROM auth_users
            ORDER BY username
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_users(rows: Iterable[dict]) -> dict:  # type: ignore[override]
    """V3.72：儲存後直接覆蓋固定 latest JSON，不讓舊檔/預設值回蓋。"""
    _v372_restore_permission_once()
    if _v372_prev_save_users is not None:
        result = _v372_prev_save_users(rows)
    else:
        result = {"saved": 0, "skipped": []}
    export_result = export_permission_settings_permanently("auth_users_saved_v372")
    if isinstance(result, dict):
        result["permanent_save"] = export_result
    return result


def delete_users(usernames: Iterable[str]) -> int:  # type: ignore[override]
    """V3.72：刪除後直接覆蓋固定 latest JSON；Reboot 不可從舊檔救回。"""
    _v372_restore_permission_once()
    if _v372_prev_delete_users is not None:
        deleted = int(_v372_prev_delete_users(usernames) or 0)
    else:
        deleted = 0
    export_permission_settings_permanently("auth_users_deleted_v372")
    return deleted


def save_account_permissions(rows: Iterable[dict]) -> int:  # type: ignore[override]
    _v372_restore_permission_once()
    if _v372_prev_save_account_permissions is not None:
        count = int(_v372_prev_save_account_permissions(rows) or 0)
    else:
        count = 0
    export_permission_settings_permanently("account_permissions_saved_v372")
    return count

# Backward compatible alias after final override.
check_permission = has_permission

# ===== V3.73 FINAL DIRECT-LATEST PERMISSION PATCH START =====
# Purpose: make 10｜權限管理 behave like 03｜製令管理 / 04｜人員名單.
# Rule:
#   1. Save/delete writes one fixed latest JSON directly.
#   2. Reboot/page load restores from the fixed latest JSON only when DB is empty/default-only.
#   3. No history scan, no GitHub, no previous layered save/delete wrappers.
_V373_PERMISSION_LATEST_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_records.json"
_V373_PERMISSION_COMPAT_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json"
_V373_PERMISSION_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_permission_settings.json"
_V373_PERMISSION_RESTORE_KEY = "_v373_permission_latest_restored"


def _v373_p_read_json(path: Path) -> dict:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 2:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v373_p_atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v373_p_latest_payload() -> dict:
    # Fixed latest is authoritative. Compat/state are only migration fallback when latest is absent.
    for path in [_V373_PERMISSION_LATEST_FILE, _V373_PERMISSION_COMPAT_FILE, _V373_PERMISSION_STATE_FILE]:
        data = _v373_p_read_json(path)
        tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
        if isinstance(tables, dict) and isinstance(tables.get("auth_users"), list):
            return data
    return {}


def _v373_p_schema_only() -> None:
    try:
        _v372_permission_schema_only()  # type: ignore[name-defined]
        return
    except Exception:
        pass
    try:
        if _v372_schema_init_only is not None:  # type: ignore[name-defined]
            _v372_schema_init_only(force=False)  # type: ignore[misc]
    except TypeError:
        try:
            _v372_schema_init_only()  # type: ignore[name-defined,misc]
        except Exception:
            pass
    except Exception:
        pass


def _v373_bool(v: Any, default: bool = False) -> int:
    try:
        return int(_truthy(v, default))  # type: ignore[name-defined]
    except Exception:
        if isinstance(v, str):
            s = v.strip().lower()
            if s in {"1", "true", "yes", "y", "on", "啟用", "是", "v", "✓"}:
                return 1
            if s in {"0", "false", "no", "n", "off", "停用", "否", ""}:
                return 0
        return 1 if bool(v) else 0


def _v373_fetch_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _v373_auth_users_state() -> tuple[int, bool]:
    """Return (count, default_only). default_only means DB was probably just seeded by app defaults."""
    _v373_p_schema_only()
    conn = connect_db()
    try:
        rows = conn.execute("SELECT username, role_code FROM auth_users").fetchall()
        users = [str(r["username"] or "").strip().lower() for r in rows]
        roles = {str(r["username"] or "").strip().lower(): str(r["role_code"] or "").strip().lower() for r in rows}
        count = len(users)
        default_only = (count == 0) or (count == 1 and users[0] == "admin" and roles.get("admin") == "admin")
        return count, default_only
    except Exception:
        return 0, True
    finally:
        conn.close()


def _v373_replace_table(cur: sqlite3.Cursor, table: str, rows: list[dict]) -> int:
    try:
        cur.execute(f'DELETE FROM "{table}"')
    except Exception:
        return 0
    count = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        clean = {str(k): v for k, v in row.items() if str(k).strip()}
        if not clean:
            continue
        cols = list(clean.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_sql = ",".join([f'"{c}"' for c in cols])
        try:
            cur.execute(f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', [clean[c] for c in cols])
            count += 1
        except Exception:
            continue
    return count


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    _v373_p_schema_only()
    payload = _v373_p_latest_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or not isinstance(tables.get("auth_users"), list):
        return {"ok": False, "mode": "v373_direct_latest_like_03_04", "message": "no fixed latest permission file"}
    if not force:
        _, default_only = _v373_auth_users_state()
        if not default_only:
            return {"ok": True, "mode": "v373_direct_latest_like_03_04", "skipped": True, "reason": "db_not_empty_like_03_04"}
    conn = connect_db(); cur = conn.cursor()
    restored: dict[str, int] = {}
    try:
        try:
            _ensure_legacy_security_tables(cur)
            _ensure_security_setting_tables(cur)
        except Exception:
            pass
        for table in ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_user_roles", "security_settings"]:
            rows = tables.get(table, []) if isinstance(tables.get(table), list) else []
            restored[table] = _v373_replace_table(cur, table, rows)
        conn.commit()
    finally:
        conn.close()
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    clear_permission_runtime_cache()
    if st is not None:
        try:
            st.session_state[_V373_PERMISSION_RESTORE_KEY] = True
        except Exception:
            pass
    return {"ok": True, "mode": "v373_direct_latest_like_03_04", "source": str(_V373_PERMISSION_LATEST_FILE), "restored": restored}


def _v373_restore_permission_once_if_needed() -> None:
    if st is not None:
        try:
            if st.session_state.get(_V373_PERMISSION_RESTORE_KEY):
                return
        except Exception:
            pass
    # Same spirit as 03/04: rescue DB only when it is empty/default-only.
    restore_permission_settings_from_permanent_files(force=False)
    if st is not None:
        try:
            st.session_state[_V373_PERMISSION_RESTORE_KEY] = True
        except Exception:
            pass


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    _v373_p_schema_only()
    if force:
        restore_permission_settings_from_permanent_files(force=True)


init_auth_tables = init_permission_tables


def _v373_permission_payload_from_db(reason: str = "permission_settings_saved") -> dict:
    _v373_p_schema_only()
    conn = connect_db()
    try:
        tables = {
            "auth_users": _v373_fetch_table(conn, "auth_users"),
            "auth_account_permissions": _v373_fetch_table(conn, "auth_account_permissions"),
            "auth_security_settings": _v373_fetch_table(conn, "auth_security_settings"),
            "security_users": _v373_fetch_table(conn, "security_users"),
            "security_user_roles": _v373_fetch_table(conn, "security_user_roles"),
            "security_settings": _v373_fetch_table(conn, "security_settings"),
        }
    finally:
        conn.close()
    return {
        "version": "V3.73-direct-latest-like-03-04-final",
        "exported_at": now_text(),
        "reason": reason,
        "module_key": "10_permissions",
        "module_code": "10_permissions",
        "module_name_zh": "權限管理",
        "module_name_en": "Permission Management",
        "source": "permission_service_v373",
        "description": "10 權限管理：比照 03/04，儲存寫固定 latest JSON；Reboot 僅在 DB 空白/預設時讀同一 latest JSON。",
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items()},
        "counts": {k: len(v) for k, v in tables.items()},
    }


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    payload = _v373_permission_payload_from_db(reason)
    for path in [_V373_PERMISSION_LATEST_FILE, _V373_PERMISSION_COMPAT_FILE, _V373_PERMISSION_STATE_FILE]:
        _v373_p_atomic_write(path, payload)
    clear_permission_runtime_cache()
    return {"ok": True, "mode": "v373_direct_latest_like_03_04_final", "files": [str(_V373_PERMISSION_LATEST_FILE), str(_V373_PERMISSION_COMPAT_FILE), str(_V373_PERMISSION_STATE_FILE)], "table_counts": payload.get("table_counts", {})}


def get_users() -> List[dict]:  # type: ignore[override]
    _v373_restore_permission_once_if_needed()
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT id, username,
                   '********' AS password_display,
                   '' AS new_password,
                   employee_id, display_name, email, role_code,
                   is_active, force_password_change, last_login_at, note, created_at, updated_at
            FROM auth_users
            ORDER BY username
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_users(rows: Iterable[dict]) -> dict:  # type: ignore[override]
    _v373_p_schema_only()
    input_rows = list(rows or [])
    conn = connect_db(); cur = conn.cursor()
    saved = 0; skipped: list[str] = []; role_sync_users: list[str] = []; saved_usernames: list[str] = []
    try:
        for r in input_rows:
            if not isinstance(r, dict):
                continue
            username = str(r.get("username", "")).strip()
            if not username:
                continue
            display_name = str(r.get("display_name", "")).strip() or username
            role_code = str(r.get("role_code", "operator")).strip() or "operator"
            new_password = str(r.get("new_password", "")).strip()
            exists = cur.execute("SELECT username, role_code FROM auth_users WHERE username=?", (username,)).fetchone()
            if exists:
                old_role = str(exists["role_code"] or "operator").strip() or "operator"
                cur.execute("""
                    UPDATE auth_users
                    SET employee_id=?, display_name=?, email=?, role_code=?, is_active=?,
                        force_password_change=?, note=?, updated_at=?
                    WHERE username=?
                """, (
                    str(r.get("employee_id", "")).strip(), display_name, str(r.get("email", "")).strip(),
                    role_code, _v373_bool(r.get("is_active", True), True), _v373_bool(r.get("force_password_change", False), False),
                    str(r.get("note", "")).strip(), now_text(), username,
                ))
                if new_password:
                    cur.execute("UPDATE auth_users SET password_hash=?, updated_at=? WHERE username=?", (hash_password(new_password), now_text(), username))
                if old_role != role_code:
                    role_sync_users.append(username)
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
                    display_name, str(r.get("email", "")).strip(), role_code, _v373_bool(r.get("is_active", True), True),
                    _v373_bool(r.get("force_password_change", False), False), str(r.get("note", "")).strip(), now_text(), now_text(),
                ))
                role_sync_users.append(username)
            saved += 1
            saved_usernames.append(username)
        conn.commit()
    finally:
        conn.close()
    try:
        ensure_permissions_for_all_users(force=True)
        if role_sync_users:
            sync_user_permissions_from_roles(role_sync_users, reason="account_role_changed")
        sync_auth_users_to_runtime_security(saved_usernames)
    except Exception:
        pass
    clear_permission_runtime_cache()
    export_result = export_permission_settings_permanently("auth_users_saved_v373")
    return {"saved": saved, "skipped": skipped, "role_synced_users": sorted(set(role_sync_users)), "permanent_save": export_result}


def delete_users(usernames: Iterable[str]) -> int:  # type: ignore[override]
    _v373_p_schema_only()
    targets = [str(u).strip() for u in (usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"]
    if not targets:
        return 0
    conn = connect_db(); cur = conn.cursor(); deleted = 0
    try:
        try:
            _ensure_legacy_security_tables(cur)
        except Exception:
            pass
        for u in targets:
            cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (u,))
            cur.execute("DELETE FROM auth_users WHERE username=?", (u,))
            deleted += max(int(cur.rowcount or 0), 0)
            try:
                cur.execute("DELETE FROM security_user_roles WHERE username=?", (u,))
                cur.execute("DELETE FROM security_users WHERE username=?", (u,))
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    clear_permission_runtime_cache()
    if deleted:
        export_permission_settings_permanently("auth_users_deleted_v373")
    return deleted


def save_account_permissions(rows: Iterable[dict]) -> int:  # type: ignore[override]
    _v373_p_schema_only()
    count = 0
    conn = connect_db(); cur = conn.cursor()
    try:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            username = str(r.get("username", "")).strip()
            module_code = str(r.get("module_code", "")).strip()
            if not username or not module_code:
                continue
            vals = {
                "can_view": _v373_bool(r.get("can_view", False)),
                "can_create": _v373_bool(r.get("can_create", False)),
                "can_edit": _v373_bool(r.get("can_edit", False)),
                "can_delete": _v373_bool(r.get("can_delete", False)),
                "can_import": _v373_bool(r.get("can_import", False)),
                "can_export": _v373_bool(r.get("can_export", False)),
                "can_backup": _v373_bool(r.get("can_backup", False)),
                "can_restore": _v373_bool(r.get("can_restore", False)),
                "can_manage": _v373_bool(r.get("can_manage", False)),
            }
            cur.execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username,module_code) DO UPDATE SET
                    module_name_zh=excluded.module_name_zh, module_name_en=excluded.module_name_en,
                    can_view=excluded.can_view, can_create=excluded.can_create, can_edit=excluded.can_edit,
                    can_delete=excluded.can_delete, can_import=excluded.can_import, can_export=excluded.can_export,
                    can_backup=excluded.can_backup, can_restore=excluded.can_restore, can_manage=excluded.can_manage,
                    updated_at=excluded.updated_at
            """, (
                username, module_code, str(r.get("module_name_zh", "")).strip(), str(r.get("module_name_en", "")).strip(),
                vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"],
                vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text(),
            ))
            count += 1
        conn.commit()
    finally:
        conn.close()
    clear_permission_runtime_cache()
    export_permission_settings_permanently("account_permissions_saved_v373")
    return count

check_permission = has_permission
# ===== V3.73 FINAL DIRECT-LATEST PERMISSION PATCH END =====


# ===== V57 RESTORE DEFAULT ACCOUNTS ONCE PATCH START =====
def restore_default_accounts_once_v57() -> dict:
    """補回原始六個預設帳號。只新增缺少帳號，不覆蓋既有帳號資料。"""
    _v373_p_schema_only()
    existing = {str(u.get("username", "")).strip().lower() for u in get_users() if isinstance(u, dict)}
    rows = []
    for username, pwd, display_name, email, role_code, active in DEFAULT_USERS:
        if str(username).strip().lower() in existing:
            continue
        rows.append({
            "username": username,
            "new_password": pwd,
            "employee_id": "",
            "display_name": display_name,
            "email": email,
            "role_code": role_code,
            "is_active": bool(active),
            "force_password_change": False,
            "note": "V57 restore default account only",
        })
    if not rows:
        return {"restored": 0, "usernames": []}
    result = save_users(rows)
    try:
        sync_user_permissions_from_roles([r["username"] for r in rows], reason="v57_restore_default_accounts")
    except Exception:
        pass
    clear_permission_runtime_cache()
    try:
        export_permission_settings_permanently("v57_restore_default_accounts")
    except Exception:
        pass
    return {"restored": int(result.get("saved", 0) or 0), "usernames": [r["username"] for r in rows]}
# ===== V57 RESTORE DEFAULT ACCOUNTS ONCE PATCH END =====


# ===== V91 SINGLE CANONICAL AUTHORITY PATCH START =====
# 目的：10. 權限管理只讀寫同一個正式權威檔，避免 Reboot App 後又被
# persistent_modules / persistent_state / history / SQLite 暫存或預設帳號覆蓋。
# 唯一權威檔：data/permanent_store/modules/10_permissions/records.json
from typing import Any as _V91Any

_V91_PERMISSION_AUTHORITY_FILE = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json"
_V91_PERMISSION_RESTORED = False
_V91_PERMISSION_RESTORE_SESSION_KEY = "_v91_permission_single_authority_restored"
_V91_AUTH_TABLES = [
    "auth_users",
    "auth_account_permissions",
    "auth_security_settings",
    "security_users",
    "security_user_roles",
    "security_settings",
]


def _v91_schema_only() -> None:
    """只建立/補齊權限相關 schema，不做任何舊檔還原。"""
    try:
        _v373_p_schema_only()  # type: ignore[name-defined]
        return
    except Exception:
        pass
    try:
        conn = connect_db(); cur = conn.cursor()
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
        CREATE TABLE IF NOT EXISTS auth_security_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            note TEXT,
            updated_at TEXT
        )
        """)
        try:
            _migrate_permission_schema_columns(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        try:
            _ensure_legacy_security_tables(cur)  # type: ignore[name-defined]
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        conn.commit(); conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _v91_read_json(path: Path) -> dict:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 2:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v91_atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # 寫入前驗證，避免半檔/壞檔成為權威檔。
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v91_bool(v: _V91Any, default: bool = False) -> int:
    try:
        return int(_truthy(v, default))  # type: ignore[name-defined]
    except Exception:
        pass
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "on", "啟用", "是", "v", "✓", "checked"}:
            return 1
        if s in {"0", "false", "no", "n", "off", "停用", "否", "", "none", "nan"}:
            return 0
    try:
        return 1 if bool(v) else 0
    except Exception:
        return 1 if default else 0


def _v91_fetch_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # id 是 SQLite 流水號，權威檔不依賴它；保留也可，但移除可避免跨環境衝突。
            d.pop("id", None)
            out.append(d)
        return out
    except Exception:
        return []


def _v91_payload_from_db(reason: str = "permission_saved") -> dict:
    _v91_schema_only()
    conn = connect_db()
    try:
        tables = {name: _v91_fetch_table(conn, name) for name in _V91_AUTH_TABLES}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {
        "version": "V91-single-canonical-permission-authority",
        "module_key": "10_permissions",
        "module_code": "10_permissions",
        "module_name_zh": "權限管理",
        "module_name_en": "Permission Management",
        "authority_file": "data/permanent_store/modules/10_permissions/records.json",
        "source": "permission_service_v91",
        "reason": reason,
        "exported_at": now_text(),
        "description": "10 權限管理唯一權威檔。讀寫都只使用此 records.json，不讀不寫 persistent_modules / persistent_state / history。",
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items()},
    }


def _v91_authority_payload() -> dict:
    data = _v91_read_json(_V91_PERMISSION_AUTHORITY_FILE)
    tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
    if isinstance(tables, dict) and isinstance(tables.get("auth_users"), list):
        return data
    return {}


def _v91_table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
    except Exception:
        return set()


def _v91_replace_table(cur: sqlite3.Cursor, table: str, rows: list[dict]) -> int:
    cols_available = _v91_table_columns(cur, table)
    if not cols_available:
        return 0
    try:
        cur.execute(f'DELETE FROM "{table}"')
    except Exception:
        return 0
    inserted = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        clean = {}
        for k, v in row.items():
            key = str(k).strip()
            if not key or key == "id" or key not in cols_available:
                continue
            clean[key] = v
        if not clean:
            continue
        col_sql = ",".join([f'"{c}"' for c in clean.keys()])
        placeholders = ",".join(["?"] * len(clean))
        try:
            cur.execute(f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', list(clean.values()))
            inserted += 1
        except Exception:
            continue
    return inserted


def _v91_restore_from_authority(force: bool = True) -> dict:
    """從唯一權威檔覆蓋 SQLite 快取。只讀 records.json。"""
    _v91_schema_only()
    payload = _v91_authority_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or not isinstance(tables.get("auth_users"), list):
        return {"ok": False, "mode": "v91_single_authority", "message": "authority_file_missing_or_invalid", "source": str(_V91_PERMISSION_AUTHORITY_FILE)}
    conn = connect_db(); cur = conn.cursor(); restored = {}
    try:
        try:
            _ensure_legacy_security_tables(cur)  # type: ignore[name-defined]
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for table in _V91_AUTH_TABLES:
            rows = tables.get(table, []) if isinstance(tables.get(table), list) else []
            restored[table] = _v91_replace_table(cur, table, rows)
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    clear_permission_runtime_cache()
    return {"ok": True, "mode": "v91_single_authority", "source": str(_V91_PERMISSION_AUTHORITY_FILE), "restored": restored}


def _v91_restore_once_if_needed() -> None:
    global _V91_PERMISSION_RESTORED
    if _V91_PERMISSION_RESTORED:
        return
    if st is not None:
        try:
            if st.session_state.get(_V91_PERMISSION_RESTORE_SESSION_KEY):
                _V91_PERMISSION_RESTORED = True
                return
        except Exception:
            pass
    # Reboot 後以權威檔為準；若權威檔不存在，不讀任何舊檔。
    _v91_restore_from_authority(force=True)
    _V91_PERMISSION_RESTORED = True
    if st is not None:
        try:
            st.session_state[_V91_PERMISSION_RESTORE_SESSION_KEY] = True
        except Exception:
            pass


def _v91_export_authority(reason: str = "permission_saved") -> dict:
    payload = _v91_payload_from_db(reason)
    # 防止暫時性 DB 異常把空帳號寫成權威檔；admin 應至少存在。
    auth_users = payload.get("tables", {}).get("auth_users", []) if isinstance(payload.get("tables"), dict) else []
    if not isinstance(auth_users, list) or len(auth_users) == 0:
        return {"ok": False, "mode": "v91_single_authority", "blocked": True, "message": "blocked_empty_auth_users", "file": str(_V91_PERMISSION_AUTHORITY_FILE)}
    _v91_atomic_write(_V91_PERMISSION_AUTHORITY_FILE, payload)
    clear_permission_runtime_cache()
    return {"ok": True, "mode": "v91_single_authority", "file": str(_V91_PERMISSION_AUTHORITY_FILE), "table_counts": payload.get("table_counts", {})}


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    """V91：只建 schema；Reboot/首次權限檢查時只從唯一權威檔還原。"""
    _v91_schema_only()
    if force:
        _v91_restore_from_authority(force=True)
    else:
        _v91_restore_once_if_needed()


init_auth_tables = init_permission_tables


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    """V91：保留舊函式名稱，但只讀唯一權威檔。"""
    return _v91_restore_from_authority(force=True)


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    """V91：保留舊函式名稱，但只寫唯一權威檔。"""
    return _v91_export_authority(reason)


def restore_default_accounts_once_v57() -> dict:  # type: ignore[override]
    """V91：禁止自動補回預設六帳號。10 頁仍會呼叫此函式，但它必須是 no-op。"""
    return {"restored": 0, "usernames": [], "mode": "v91_disabled_default_restore"}


def get_users() -> List[dict]:  # type: ignore[override]
    init_permission_tables(force=False)
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT id, username,
                   '********' AS password_display,
                   '' AS new_password,
                   employee_id, display_name, email, role_code,
                   is_active, force_password_change, last_login_at, note, created_at, updated_at
            FROM auth_users
            ORDER BY username
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def save_users(rows: Iterable[dict]) -> dict:  # type: ignore[override]
    init_permission_tables(force=False)
    input_rows = list(rows or [])
    conn = connect_db(); cur = conn.cursor()
    saved = 0; skipped: list[str] = []; role_sync_users: list[str] = []; saved_usernames: list[str] = []
    try:
        for r in input_rows:
            if not isinstance(r, dict):
                continue
            username = str(r.get("username", "")).strip()
            if not username:
                continue
            display_name = str(r.get("display_name") or r.get("姓名 / Display Name") or "").strip() or username
            role_code = str(r.get("role_code") or r.get("角色 / Role") or "operator").strip() or "operator"
            new_password = str(r.get("new_password") or r.get("密碼 / Password") or r.get("新密碼 / New Password") or "").strip()
            employee_id = str(r.get("employee_id") or r.get("工號 / Employee ID") or "").strip()
            email = str(r.get("email") or r.get("Email") or "").strip()
            note = str(r.get("note") or r.get("備註 / Note") or "").strip()
            is_active = _v91_bool(r.get("is_active", r.get("啟用 / Active", True)), True)
            force_change = _v91_bool(r.get("force_password_change", r.get("強制改密碼 / Force Change", False)), False)
            exists = cur.execute("SELECT username, role_code FROM auth_users WHERE username=?", (username,)).fetchone()
            if exists:
                old_role = str(exists["role_code"] or "operator").strip() or "operator"
                cur.execute("""
                    UPDATE auth_users
                    SET employee_id=?, display_name=?, email=?, role_code=?, is_active=?,
                        force_password_change=?, note=?, updated_at=?
                    WHERE username=?
                """, (employee_id, display_name, email, role_code, is_active, force_change, note, now_text(), username))
                if new_password:
                    cur.execute("UPDATE auth_users SET password_hash=?, password_hint=?, updated_at=? WHERE username=?", (hash_password(new_password), "由權限管理頁更新", now_text(), username))
                if old_role != role_code:
                    role_sync_users.append(username)
            else:
                if not new_password:
                    skipped.append(f"{username} 未設定新密碼 / new password required")
                    continue
                cur.execute("""
                    INSERT INTO auth_users
                    (username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,note,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (username, hash_password(new_password), "由權限管理頁建立", employee_id, display_name, email, role_code, is_active, force_change, note, now_text(), now_text()))
                role_sync_users.append(username)
            saved += 1
            saved_usernames.append(username)
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        ensure_permissions_for_all_users(force=True)
        if role_sync_users:
            sync_user_permissions_from_roles(role_sync_users, reason="v91_account_role_changed")
        if saved_usernames:
            sync_auth_users_to_runtime_security(saved_usernames)
    except Exception:
        pass
    clear_permission_runtime_cache()
    export_result = _v91_export_authority("auth_users_saved_v91")
    return {"saved": saved, "skipped": skipped, "role_synced_users": sorted(set(role_sync_users)), "permanent_save": export_result}


def delete_users(usernames: Iterable[str]) -> int:  # type: ignore[override]
    init_permission_tables(force=False)
    targets = []
    seen = set()
    for u in usernames or []:
        name = str(u or "").strip()
        if not name or name.lower() == "admin" or name.lower() in seen:
            continue
        seen.add(name.lower()); targets.append(name)
    if not targets:
        return 0
    conn = connect_db(); cur = conn.cursor(); deleted = 0
    try:
        try:
            _ensure_legacy_security_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for u in targets:
            existed = cur.execute("SELECT COUNT(*) AS c FROM auth_users WHERE username=?", (u,)).fetchone()
            existed_count = int(existed["c"] if existed is not None else 0)
            for sql in [
                "DELETE FROM auth_account_permissions WHERE username=?",
                "DELETE FROM security_user_roles WHERE username=?",
                "DELETE FROM security_users WHERE username=?",
                "DELETE FROM auth_users WHERE username=?",
            ]:
                try:
                    cur.execute(sql, (u,))
                except Exception:
                    pass
            deleted += existed_count
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    clear_permission_runtime_cache()
    if deleted:
        _v91_export_authority("auth_users_deleted_v91")
    return deleted


def save_account_permissions(rows: Iterable[dict]) -> int:  # type: ignore[override]
    init_permission_tables(force=False)
    conn = connect_db(); cur = conn.cursor(); count = 0
    try:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            username = str(r.get("username", "")).strip()
            module_code = str(r.get("module_code", "")).strip().zfill(2)
            if not username or not module_code:
                continue
            module_info = next((m for m in MODULES if m["module_code"] == module_code), None)
            module_name_zh = str(r.get("module_name_zh") or (module_info or {}).get("module_name_zh") or "").strip()
            module_name_en = str(r.get("module_name_en") or (module_info or {}).get("module_name_en") or "").strip()
            vals = {k: _v91_bool(r.get(k, False), False) for k, _, _ in ACTIONS}
            cur.execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username,module_code) DO UPDATE SET
                    module_name_zh=excluded.module_name_zh, module_name_en=excluded.module_name_en,
                    can_view=excluded.can_view, can_create=excluded.can_create, can_edit=excluded.can_edit,
                    can_delete=excluded.can_delete, can_import=excluded.can_import, can_export=excluded.can_export,
                    can_backup=excluded.can_backup, can_restore=excluded.can_restore, can_manage=excluded.can_manage,
                    updated_at=excluded.updated_at
            """, (username, module_code, module_name_zh, module_name_en,
                  vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text()))
            count += 1
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    clear_permission_runtime_cache()
    _v91_export_authority("account_permissions_saved_v91")
    return count


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    init_permission_tables(force=False)
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT p.username, u.display_name, u.role_code, p.module_code, p.module_name_zh, p.module_name_en,
                   p.can_view, p.can_create, p.can_edit, p.can_delete, p.can_import, p.can_export,
                   p.can_backup, p.can_restore, p.can_manage, p.updated_at
            FROM auth_account_permissions p
            LEFT JOIN auth_users u ON u.username = p.username
            ORDER BY p.username, CAST(p.module_code AS INTEGER)
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    init_permission_tables(force=False)
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    conn = connect_db(); cur = conn.cursor()
    try:
        try:
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for k, v in merged.items():
            cur.execute("""
                INSERT INTO auth_security_settings(setting_key, setting_value, note, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
            """, (str(k), str(v), "V91 single authority security setting", now_text()))
            try:
                cur.execute("""
                    INSERT INTO security_settings(setting_key, setting_value, note, updated_at)
                    VALUES (?,?,?,?)
                    ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
                """, (str(k), str(v), "V91 single authority security setting", now_text()))
            except Exception:
                pass
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    clear_permission_runtime_cache()
    _v91_export_authority("security_settings_saved_v91")


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    init_permission_tables(force=False)
    result: Dict[str, str] = {
        "idle_timeout_minutes": "15",
        "ask_continue_after_record": "1",
        "post_record_action": "ask_continue",
    }
    conn = connect_db(); cur = conn.cursor()
    try:
        try:
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for table in ["auth_security_settings", "security_settings"]:
            try:
                for r in cur.execute(f"SELECT setting_key, setting_value FROM {table}").fetchall():
                    result[str(r["setting_key"])] = str(r["setting_value"])
            except Exception:
                pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return result


check_permission = has_permission
# ===== V91 SINGLE CANONICAL AUTHORITY PATCH END =====


# ===== V94 STRICT PERMISSION SINGLE-AUTHORITY PATCH START =====
# 目的：10 權限管理真正只讀寫 data/permanent_store/modules/10_permissions/records.json。
# 刪除帳號會寫入 deleted_usernames tombstone，避免 Reboot / 舊 SQLite / 預設帳號機制把帳號救回。
from pathlib import Path as _V94Path
from typing import Iterable as _V94Iterable, Any as _V94Any
import json as _v94_json

_V94_PERMISSION_AUTHORITY_FILE = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json"
_V94_AUTH_TABLES = [
    "auth_users",
    "auth_account_permissions",
    "auth_security_settings",
    "security_users",
    "security_user_roles",
    "security_settings",
]


def _v94_read_permission_payload() -> dict:
    try:
        if _V94_PERMISSION_AUTHORITY_FILE.exists() and _V94_PERMISSION_AUTHORITY_FILE.stat().st_size > 2:
            data = _v94_json.loads(_V94_PERMISSION_AUTHORITY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v94_deleted_usernames(payload: dict | None = None) -> set[str]:
    payload = payload if isinstance(payload, dict) else _v94_read_permission_payload()
    raw = payload.get("deleted_usernames", [])
    if not isinstance(raw, list):
        raw = []
    return {str(x).strip().lower() for x in raw if str(x).strip() and str(x).strip().lower() != "admin"}


def _v94_write_permission_payload(payload: dict) -> None:
    _V94_PERMISSION_AUTHORITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _V94_PERMISSION_AUTHORITY_FILE.with_suffix(".json.tmp")
    tmp.write_text(_v94_json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _v94_json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(_V94_PERMISSION_AUTHORITY_FILE)


def _v94_filter_deleted_tables(tables: dict, deleted: set[str]) -> dict:
    if not isinstance(tables, dict):
        tables = {}
    deleted = {str(x).strip().lower() for x in deleted if str(x).strip().lower() != "admin"}
    out = {}
    for table, rows in tables.items():
        clean_rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            username = str(row.get("username") or row.get("帳號") or row.get("user") or "").strip().lower()
            if username and username in deleted:
                continue
            clean_rows.append(dict(row))
        out[str(table)] = clean_rows
    return out


def _v94_fetch_all_permission_tables() -> dict:
    _v91_schema_only() if "_v91_schema_only" in globals() else init_permission_tables(False)
    conn = connect_db()
    try:
        tables = {}
        for table in _V94_AUTH_TABLES:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                got = []
                for r in rows:
                    d = dict(r)
                    d.pop("id", None)
                    got.append(d)
                tables[table] = got
            except Exception:
                tables[table] = []
        return tables
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _v94_export_permission_authority(reason: str = "permission_saved_v94") -> dict:
    old_payload = _v94_read_permission_payload()
    deleted = _v94_deleted_usernames(old_payload)
    tables = _v94_filter_deleted_tables(_v94_fetch_all_permission_tables(), deleted)
    auth_users = tables.get("auth_users", [])
    if not isinstance(auth_users, list) or not auth_users:
        return {"ok": False, "blocked": True, "reason": "empty_auth_users", "file": str(_V94_PERMISSION_AUTHORITY_FILE)}
    payload = {
        "authority_schema": "SPT-10-Permissions-SingleAuthority-V94",
        "version": "V94-single-authority-with-delete-tombstone",
        "module_key": "10_permissions",
        "kind": "records",
        "authority_file": "data/permanent_store/modules/10_permissions/records.json",
        "reason": reason,
        "updated_at": now_text(),
        "deleted_usernames": sorted(deleted),
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items() if isinstance(v, list)},
    }
    _v94_write_permission_payload(payload)
    clear_permission_runtime_cache()
    return {"ok": True, "file": str(_V94_PERMISSION_AUTHORITY_FILE), "deleted_usernames": sorted(deleted), "table_counts": payload["table_counts"]}


def _v94_restore_permission_from_authority(force: bool = True) -> dict:
    _v91_schema_only() if "_v91_schema_only" in globals() else None
    payload = _v94_read_permission_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or not isinstance(tables.get("auth_users"), list):
        return {"ok": False, "message": "authority_file_missing_or_invalid", "file": str(_V94_PERMISSION_AUTHORITY_FILE)}
    deleted = _v94_deleted_usernames(payload)
    tables = _v94_filter_deleted_tables(tables, deleted)
    conn = connect_db(); cur = conn.cursor(); restored = {}
    try:
        try:
            _ensure_legacy_security_tables(cur)  # type: ignore[name-defined]
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
            _migrate_permission_schema_columns(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for table in _V94_AUTH_TABLES:
            try:
                cur.execute(f'DELETE FROM "{table}"')
            except Exception:
                pass
            cols = set()
            try:
                cols = {str(r[1]) for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
            except Exception:
                cols = set()
            inserted = 0
            for row in tables.get(table, []) if isinstance(tables.get(table, []), list) else []:
                clean = {str(k): v for k, v in dict(row).items() if str(k) in cols and str(k) != "id"}
                if not clean:
                    continue
                sql_cols = ",".join([f'"{c}"' for c in clean.keys()])
                placeholders = ",".join(["?"] * len(clean))
                try:
                    cur.execute(f'INSERT INTO "{table}" ({sql_cols}) VALUES ({placeholders})', list(clean.values()))
                    inserted += 1
                except Exception:
                    continue
            restored[table] = inserted
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    clear_permission_runtime_cache()
    # 權威檔若含已刪帳號，還原後立刻清洗寫回唯一檔，避免下次又救回。
    try:
        _v94_export_permission_authority("restore_cleaned_deleted_users_v94")
    except Exception:
        pass
    return {"ok": True, "mode": "v94_single_authority", "restored": restored, "deleted_usernames": sorted(deleted)}


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    _v91_schema_only() if "_v91_schema_only" in globals() else None
    # 權限資料每次進 10 頁/讀取權限時，都先用唯一權威檔校正 SQLite 快取；資料量小，成本低，可靠性優先。
    _v94_restore_permission_from_authority(force=True)

init_auth_tables = init_permission_tables


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    return _v94_restore_permission_from_authority(force=True)


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    return _v94_export_permission_authority(reason)


def restore_default_accounts_once_v57() -> dict:  # type: ignore[override]
    return {"restored": 0, "usernames": [], "mode": "v94_disabled_default_restore"}


def get_users() -> List[dict]:  # type: ignore[override]
    init_permission_tables(force=False)
    deleted = _v94_deleted_usernames()
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT id, username,
                   '********' AS password_display,
                   '' AS new_password,
                   employee_id, display_name, email, role_code,
                   is_active, force_password_change, last_login_at, note, created_at, updated_at
            FROM auth_users
            ORDER BY username
        """).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if str(d.get("username", "")).strip().lower() in deleted:
                continue
            out.append(d)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def save_users(rows: _V94Iterable[dict]) -> dict:  # type: ignore[override]
    # 一般匯入/貼上：只 upsert 帳號；不會讀寫舊檔。若明確匯入被刪帳號，視為重新建立，移除 tombstone。
    init_permission_tables(force=False)
    input_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    payload = _v94_read_permission_payload()
    deleted = _v94_deleted_usernames(payload)
    explicit_usernames = {str(r.get("username") or r.get("帳號 / Username") or "").strip().lower() for r in input_rows if str(r.get("username") or r.get("帳號 / Username") or "").strip()}
    deleted -= {u for u in explicit_usernames if u and u != "admin"}
    payload["deleted_usernames"] = sorted(deleted)
    if isinstance(payload.get("tables"), dict):
        _v94_write_permission_payload(payload)
    # 使用 V91 儲存邏輯的主體；若不可用則走原始函式。
    try:
        result = _v91_save_users_body(input_rows)  # type: ignore[name-defined]
    except Exception:
        result = None
    if not isinstance(result, dict):
        # 複製 V91 save_users 的安全 upsert 簡化版。
        saved = 0; skipped = []
        conn = connect_db(); cur = conn.cursor()
        try:
            for r in input_rows:
                username = str(r.get("username") or r.get("帳號 / Username") or "").strip()
                if not username:
                    continue
                display_name = str(r.get("display_name") or r.get("姓名 / Display Name") or username).strip()
                role_code = str(r.get("role_code") or r.get("角色 / Role") or "operator").strip() or "operator"
                new_password = str(r.get("new_password") or r.get("密碼 / Password") or "").strip()
                employee_id = str(r.get("employee_id") or r.get("工號 / Employee ID") or "").strip()
                email = str(r.get("email") or r.get("Email") or "").strip()
                note = str(r.get("note") or r.get("備註 / Note") or "").strip()
                is_active = _v91_bool(r.get("is_active", r.get("啟用 / Active", True)), True) if "_v91_bool" in globals() else int(bool(r.get("is_active", True)))
                force_change = _v91_bool(r.get("force_password_change", r.get("強制改密碼 / Force Change", False)), False) if "_v91_bool" in globals() else 0
                exists = cur.execute("SELECT username FROM auth_users WHERE username=?", (username,)).fetchone()
                if exists:
                    if new_password and new_password != "********":
                        cur.execute("UPDATE auth_users SET password_hash=?, password_hint=?, employee_id=?, display_name=?, email=?, role_code=?, is_active=?, force_password_change=?, note=?, updated_at=? WHERE username=?", (hash_password(new_password), "由權限管理頁更新", employee_id, display_name, email, role_code, is_active, force_change, note, now_text(), username))
                    else:
                        cur.execute("UPDATE auth_users SET employee_id=?, display_name=?, email=?, role_code=?, is_active=?, force_password_change=?, note=?, updated_at=? WHERE username=?", (employee_id, display_name, email, role_code, is_active, force_change, note, now_text(), username))
                else:
                    if not new_password or new_password == "********":
                        skipped.append(f"{username} 未設定新密碼 / new password required")
                        continue
                    cur.execute("INSERT INTO auth_users(username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (username, hash_password(new_password), "由權限管理頁建立", employee_id, display_name, email, role_code, is_active, force_change, note, now_text(), now_text()))
                saved += 1
            conn.commit()
        finally:
            try: conn.close()
            except Exception: pass
        result = {"saved": saved, "skipped": skipped}
    try:
        ensure_permissions_for_all_users(force=True)
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    export_result = _v94_export_permission_authority("save_users_v94")
    result["permanent_save"] = export_result
    return result


def save_account_master(rows: _V94Iterable[dict], delete_usernames: _V94Iterable[str] | None = None) -> dict:
    """10 頁帳號密碼總表專用：畫面上的帳號清單 + 刪除勾選 = 權威檔正式結果。"""
    init_permission_tables(force=False)
    delete_set = {str(u).strip().lower() for u in (delete_usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"}
    input_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    # 先把刪除帳號寫入 tombstone，避免後續任何舊資料把它救回。
    payload = _v94_read_permission_payload()
    deleted = _v94_deleted_usernames(payload) | delete_set
    payload["deleted_usernames"] = sorted(deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v94_filter_deleted_tables(payload.get("tables", {}), deleted)
        _v94_write_permission_payload(payload)
    # 先刪後存，避免 unique / runtime cache 混亂。
    conn = connect_db(); cur = conn.cursor(); deleted_count = 0
    try:
        for u in sorted(delete_set):
            try:
                existed = cur.execute("SELECT COUNT(*) AS c FROM auth_users WHERE lower(username)=?", (u,)).fetchone()
                deleted_count += int(existed["c"] if existed else 0)
            except Exception:
                pass
            for sql in [
                "DELETE FROM auth_account_permissions WHERE lower(username)=?",
                "DELETE FROM security_user_roles WHERE lower(username)=?",
                "DELETE FROM security_users WHERE lower(username)=?",
                "DELETE FROM auth_users WHERE lower(username)=?",
            ]:
                try: cur.execute(sql, (u,))
                except Exception: pass
        conn.commit()
    finally:
        try: conn.close()
        except Exception: pass
    filtered_rows = []
    for r in input_rows:
        u = str(r.get("username") or r.get("帳號 / Username") or "").strip().lower()
        if u and u not in deleted:
            filtered_rows.append(r)
    result = save_users(filtered_rows)
    # save_users 會把 explicit_usernames 從 tombstone 移除；帳號總表刪除不應移除，所以再寫回。
    payload = _v94_read_permission_payload()
    payload["deleted_usernames"] = sorted(_v94_deleted_usernames(payload) | deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v94_filter_deleted_tables(payload.get("tables", {}), set(payload["deleted_usernames"]))
    _v94_write_permission_payload(payload)
    _v94_restore_permission_from_authority(force=True)
    result["deleted"] = deleted_count
    result["deleted_usernames"] = sorted(deleted)
    result["permanent_save"] = _v94_export_permission_authority("save_account_master_v94")
    return result


def delete_users(usernames: _V94Iterable[str]) -> int:  # type: ignore[override]
    targets = {str(u).strip().lower() for u in (usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"}
    if not targets:
        return 0
    payload = _v94_read_permission_payload()
    deleted = _v94_deleted_usernames(payload) | targets
    payload["deleted_usernames"] = sorted(deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v94_filter_deleted_tables(payload.get("tables", {}), deleted)
        _v94_write_permission_payload(payload)
    conn = connect_db(); cur = conn.cursor(); count = 0
    try:
        for u in sorted(targets):
            try:
                existed = cur.execute("SELECT COUNT(*) AS c FROM auth_users WHERE lower(username)=?", (u,)).fetchone()
                count += int(existed["c"] if existed else 0)
            except Exception:
                pass
            for sql in [
                "DELETE FROM auth_account_permissions WHERE lower(username)=?",
                "DELETE FROM security_user_roles WHERE lower(username)=?",
                "DELETE FROM security_users WHERE lower(username)=?",
                "DELETE FROM auth_users WHERE lower(username)=?",
            ]:
                try: cur.execute(sql, (u,))
                except Exception: pass
        conn.commit()
    finally:
        try: conn.close()
        except Exception: pass
    _v94_export_permission_authority("delete_users_v94")
    _v94_restore_permission_from_authority(force=True)
    return int(count)


def save_account_permissions(rows: _V94Iterable[dict]) -> int:  # type: ignore[override]
    # 權限表儲存前先過濾已刪帳號，避免已刪帳號因權限列復活。
    deleted = _v94_deleted_usernames()
    safe_rows = [dict(r) for r in (rows or []) if isinstance(r, dict) and str(r.get("username", "")).strip().lower() not in deleted]
    # 使用 V91 權限儲存主體若仍可用，否則走下方簡化 upsert。
    init_permission_tables(force=False)
    conn = connect_db(); cur = conn.cursor(); count = 0
    try:
        for r in safe_rows:
            username = str(r.get("username", "")).strip()
            module_code = str(r.get("module_code", "")).strip().zfill(2)
            if not username or not module_code:
                continue
            module_info = next((m for m in MODULES if m["module_code"] == module_code), None)
            module_name_zh = str(r.get("module_name_zh") or (module_info or {}).get("module_name_zh") or "").strip()
            module_name_en = str(r.get("module_name_en") or (module_info or {}).get("module_name_en") or "").strip()
            vals = {k: (_v91_bool(r.get(k, False), False) if "_v91_bool" in globals() else int(bool(r.get(k, False)))) for k, _, _ in ACTIONS}
            cur.execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username,module_code) DO UPDATE SET
                    module_name_zh=excluded.module_name_zh, module_name_en=excluded.module_name_en,
                    can_view=excluded.can_view, can_create=excluded.can_create, can_edit=excluded.can_edit,
                    can_delete=excluded.can_delete, can_import=excluded.can_import, can_export=excluded.can_export,
                    can_backup=excluded.can_backup, can_restore=excluded.can_restore, can_manage=excluded.can_manage,
                    updated_at=excluded.updated_at
            """, (username, module_code, module_name_zh, module_name_en,
                  vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text()))
            count += 1
        conn.commit()
    finally:
        try: conn.close()
        except Exception: pass
    clear_permission_runtime_cache()
    _v94_export_permission_authority("save_account_permissions_v94")
    return count


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    init_permission_tables(force=False)
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    conn = connect_db(); cur = conn.cursor()
    try:
        try:
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for k, v in merged.items():
            cur.execute("""
                INSERT INTO auth_security_settings(setting_key, setting_value, note, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
            """, (str(k), str(v), "V94 single authority security setting", now_text()))
            try:
                cur.execute("""
                    INSERT INTO security_settings(setting_key, setting_value, note, updated_at)
                    VALUES (?,?,?,?)
                    ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
                """, (str(k), str(v), "V94 single authority security setting", now_text()))
            except Exception:
                pass
        conn.commit()
    finally:
        try: conn.close()
        except Exception: pass
    clear_permission_runtime_cache()
    _v94_export_permission_authority("save_security_settings_v94")

check_permission = has_permission
# ===== V94 STRICT PERMISSION SINGLE-AUTHORITY PATCH END =====


# ===== V95 PERMISSION SINGLE-AUTHORITY SPEED + DELETE-PERSIST HARD FIX START =====
# 目的：
# 1) 10. 權限管理只讀寫 data/permanent_store/modules/10_permissions/records.json。
# 2) Reboot App 後已刪帳號不得復活。
# 3) 進入 10 頁、勾選 checkbox、切換欄位，不再每次強制還原/重寫 SQLite，避免 2~3 分鐘卡頓。
# 4) 權限矩陣與安全設定也納入同一份權威檔。
import time as _v95_time

_V95_PERMISSION_AUTHORITY_FILE = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json"
_V95_AUTH_TABLES = list(dict.fromkeys([
    "auth_users",
    "auth_account_permissions",
    "auth_security_settings",
    "security_settings",
    "security_users",
    "security_user_roles",
]))
_V95_LAST_RESTORE_SIG = None
_V95_LAST_RESTORE_TS = 0.0
_V95_RESTORE_MIN_INTERVAL = 1.5


def _v95_now_text_safe() -> str:
    try:
        return now_text()
    except Exception:
        from datetime import datetime as _dt
        return _dt.now().strftime("%Y-%m-%d %H:%M:%S")


def _v95_authority_signature() -> tuple:
    try:
        stt = _V95_PERMISSION_AUTHORITY_FILE.stat()
        return (int(stt.st_mtime_ns), int(stt.st_size))
    except Exception:
        return (0, 0)


def _v95_json_read(path: _V94Path) -> dict:
    try:
        if path.exists() and path.stat().st_size > 2:
            data = _v94_json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v95_json_write(path: _V94Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = _v94_json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    # 沒變就不寫，避免每次操作都觸發檔案 mtime 更新與 Streamlit 重新部署/同步。
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
    except Exception:
        pass
    tmp.write_text(text, encoding="utf-8")
    _v94_json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v95_deleted_usernames(payload: dict | None = None) -> set[str]:
    payload = payload if isinstance(payload, dict) else _v95_json_read(_V95_PERMISSION_AUTHORITY_FILE)
    raw = payload.get("deleted_usernames", []) if isinstance(payload, dict) else []
    if not isinstance(raw, list):
        raw = []
    return {str(x).strip().lower() for x in raw if str(x).strip() and str(x).strip().lower() != "admin"}


def _v95_schema_only() -> None:
    try:
        _v91_schema_only()  # type: ignore[name-defined]
        return
    except Exception:
        pass
    try:
        _v83_prev_init_permission_tables(False)  # type: ignore[name-defined]
    except Exception:
        try:
            _v79_prev_init_permission_tables(False)  # type: ignore[name-defined]
        except Exception:
            pass


def _v95_filter_deleted_tables(tables: dict, deleted: set[str]) -> dict:
    if not isinstance(tables, dict):
        return {}
    deleted = {str(x).strip().lower() for x in deleted if str(x).strip().lower() != "admin"}
    out = {}
    for table, rows in tables.items():
        clean_rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            u = str(row.get("username") or row.get("帳號") or row.get("user") or "").strip().lower()
            if u and u in deleted:
                continue
            clean_rows.append(dict(row))
        out[str(table)] = clean_rows
    return out


def _v95_fetch_all_permission_tables() -> dict:
    _v95_schema_only()
    conn = connect_db()
    try:
        out = {}
        for table in _V95_AUTH_TABLES:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                got = []
                for r in rows:
                    d = dict(r)
                    d.pop("id", None)
                    got.append(d)
                out[table] = got
            except Exception:
                out[table] = []
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _v95_read_permission_payload() -> dict:
    payload = _v95_json_read(_V95_PERMISSION_AUTHORITY_FILE)
    # 相容 V94 舊檔：若缺 tables，回傳空；不讀其它舊路徑。
    if not isinstance(payload, dict):
        payload = {}
    return payload


def _v95_write_permission_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("authority_schema", "SPT-10-Permissions-SingleAuthority-V95")
    payload.setdefault("module_key", "10_permissions")
    payload.setdefault("kind", "records")
    payload["authority_file"] = "data/permanent_store/modules/10_permissions/records.json"
    payload["updated_at"] = _v95_now_text_safe()
    deleted = _v95_deleted_usernames(payload)
    tables = payload.get("tables", {}) if isinstance(payload.get("tables"), dict) else {}
    payload["tables"] = _v95_filter_deleted_tables(tables, deleted)
    payload["deleted_usernames"] = sorted(deleted)
    payload["table_counts"] = {k: len(v) for k, v in payload.get("tables", {}).items() if isinstance(v, list)}
    _v95_json_write(_V95_PERMISSION_AUTHORITY_FILE, payload)


def _v95_export_permission_authority(reason: str = "permission_saved_v95") -> dict:
    old = _v95_read_permission_payload()
    deleted = _v95_deleted_usernames(old)
    tables = _v95_filter_deleted_tables(_v95_fetch_all_permission_tables(), deleted)
    auth_users = tables.get("auth_users", [])
    # 防呆：DB 暫時異常時，不用空表覆蓋權威檔。
    if not isinstance(auth_users, list) or not auth_users:
        return {"ok": False, "blocked": True, "reason": "empty_auth_users", "file": str(_V95_PERMISSION_AUTHORITY_FILE)}
    payload = {
        "authority_schema": "SPT-10-Permissions-SingleAuthority-V95",
        "version": "V95-single-authority-fast-delete-tombstone",
        "module_key": "10_permissions",
        "kind": "records",
        "authority_file": "data/permanent_store/modules/10_permissions/records.json",
        "reason": reason,
        "updated_at": _v95_now_text_safe(),
        "deleted_usernames": sorted(deleted),
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items() if isinstance(v, list)},
    }
    _v95_write_permission_payload(payload)
    try:
        clear_permission_runtime_cache()
    except Exception:
        pass
    global _V95_LAST_RESTORE_SIG
    _V95_LAST_RESTORE_SIG = _v95_authority_signature()
    return {"ok": True, "file": str(_V95_PERMISSION_AUTHORITY_FILE), "table_counts": payload["table_counts"], "deleted_usernames": sorted(deleted)}


def _v95_restore_permission_from_authority(force: bool = False) -> dict:
    global _V95_LAST_RESTORE_SIG, _V95_LAST_RESTORE_TS
    _v95_schema_only()
    sig = _v95_authority_signature()
    now_ts = _v95_time.time()
    if not force and _V95_LAST_RESTORE_SIG == sig and (now_ts - float(_V95_LAST_RESTORE_TS or 0)) < _V95_RESTORE_MIN_INTERVAL:
        return {"ok": True, "skipped": True, "reason": "authority_already_restored", "sig": sig}
    payload = _v95_read_permission_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or not isinstance(tables.get("auth_users"), list):
        _V95_LAST_RESTORE_SIG = sig
        _V95_LAST_RESTORE_TS = now_ts
        return {"ok": False, "message": "authority_file_missing_or_invalid", "file": str(_V95_PERMISSION_AUTHORITY_FILE)}
    deleted = _v95_deleted_usernames(payload)
    tables = _v95_filter_deleted_tables(tables, deleted)
    conn = connect_db(); cur = conn.cursor(); restored = {}
    try:
        try:
            _ensure_legacy_security_tables(cur)  # type: ignore[name-defined]
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
            _migrate_permission_schema_columns(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        cur.execute("BEGIN")
        for table in _V95_AUTH_TABLES:
            rows = tables.get(table, []) if isinstance(tables.get(table, []), list) else []
            try:
                cur.execute(f'DELETE FROM "{table}"')
            except Exception:
                restored[table] = 0
                continue
            try:
                cols = {str(r[1]) for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
            except Exception:
                cols = set()
            inserted = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                clean = {str(k): v for k, v in row.items() if str(k) in cols and str(k) != "id"}
                if not clean:
                    continue
                sql_cols = ",".join([f'"{c}"' for c in clean.keys()])
                placeholders = ",".join(["?"] * len(clean))
                try:
                    cur.execute(f'INSERT INTO "{table}" ({sql_cols}) VALUES ({placeholders})', list(clean.values()))
                    inserted += 1
                except Exception:
                    continue
            restored[table] = inserted
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    try:
        clear_permission_runtime_cache()
    except Exception:
        pass
    _V95_LAST_RESTORE_SIG = sig
    _V95_LAST_RESTORE_TS = _v95_time.time()
    return {"ok": True, "mode": "v95_single_authority_cached_restore", "restored": restored, "deleted_usernames": sorted(deleted)}


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    _v95_restore_permission_from_authority(force=bool(force))

init_auth_tables = init_permission_tables


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    return _v95_restore_permission_from_authority(force=bool(force))


def export_permission_settings_permanently(reason: str = "permission_settings_saved") -> dict:  # type: ignore[override]
    return _v95_export_permission_authority(reason)


def restore_default_accounts_once_v57() -> dict:  # type: ignore[override]
    return {"restored": 0, "usernames": [], "mode": "v95_disabled_default_restore"}


def get_users() -> List[dict]:  # type: ignore[override]
    init_permission_tables(force=False)
    deleted = _v95_deleted_usernames()
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT id, username,
                   '********' AS password_display,
                   '' AS new_password,
                   employee_id, display_name, email, role_code,
                   is_active, force_password_change, last_login_at, note, created_at, updated_at
            FROM auth_users
            ORDER BY username
        """).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if str(d.get("username", "")).strip().lower() in deleted:
                continue
            out.append(d)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    init_permission_tables(force=False)
    deleted = _v95_deleted_usernames()
    conn = connect_db()
    try:
        rows = conn.execute("""
            SELECT p.username, u.display_name, u.role_code, p.module_code, p.module_name_zh, p.module_name_en,
                   p.can_view, p.can_create, p.can_edit, p.can_delete, p.can_import, p.can_export,
                   p.can_backup, p.can_restore, p.can_manage, p.updated_at
            FROM auth_account_permissions p
            LEFT JOIN auth_users u ON u.username = p.username
            ORDER BY p.username, CAST(p.module_code AS INTEGER)
        """).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if str(d.get("username", "")).strip().lower() in deleted:
                continue
            out.append(d)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    init_permission_tables(force=False)
    result: Dict[str, str] = {
        "idle_timeout_minutes": "15",
        "ask_continue_after_record": "1",
        "post_record_action": "ask_continue",
    }
    conn = connect_db(); cur = conn.cursor()
    try:
        try:
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for table in ["auth_security_settings", "security_settings"]:
            try:
                for r in cur.execute(f"SELECT setting_key, setting_value FROM {table}").fetchall():
                    result[str(r["setting_key"])] = str(r["setting_value"])
            except Exception:
                pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return result


def save_users(rows: _V94Iterable[dict]) -> dict:  # type: ignore[override]
    init_permission_tables(force=False)
    input_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    payload = _v95_read_permission_payload()
    deleted = _v95_deleted_usernames(payload)
    explicit = {str(r.get("username") or r.get("帳號 / Username") or "").strip().lower() for r in input_rows if str(r.get("username") or r.get("帳號 / Username") or "").strip()}
    # 明確匯入/新增代表重新建立該帳號，移除 tombstone；admin 不進 tombstone。
    deleted -= {u for u in explicit if u and u != "admin"}
    payload["deleted_usernames"] = sorted(deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v95_filter_deleted_tables(payload.get("tables", {}), deleted)
        _v95_write_permission_payload(payload)
    saved = 0; skipped = []
    conn = connect_db(); cur = conn.cursor()
    try:
        for r in input_rows:
            username = str(r.get("username") or r.get("帳號 / Username") or "").strip()
            if not username:
                continue
            display_name = str(r.get("display_name") or r.get("姓名 / Display Name") or username).strip()
            role_code = str(r.get("role_code") or r.get("角色 / Role") or "operator").strip() or "operator"
            new_password = str(r.get("new_password") or r.get("密碼 / Password") or "").strip()
            employee_id = str(r.get("employee_id") or r.get("工號 / Employee ID") or "").strip()
            email = str(r.get("email") or r.get("Email") or "").strip()
            note = str(r.get("note") or r.get("備註 / Note") or "").strip()
            is_active = int(_v91_bool(r.get("is_active", r.get("啟用 / Active", True)), True)) if "_v91_bool" in globals() else int(bool(r.get("is_active", True)))
            force_change = int(_v91_bool(r.get("force_password_change", r.get("強制改密碼 / Force Change", False)), False)) if "_v91_bool" in globals() else int(bool(r.get("force_password_change", False)))
            exists = cur.execute("SELECT username FROM auth_users WHERE username=?", (username,)).fetchone()
            if exists:
                if new_password and new_password != "********":
                    cur.execute("UPDATE auth_users SET password_hash=?, password_hint=?, employee_id=?, display_name=?, email=?, role_code=?, is_active=?, force_password_change=?, note=?, updated_at=? WHERE username=?", (hash_password(new_password), "由權限管理頁更新", employee_id, display_name, email, role_code, is_active, force_change, note, _v95_now_text_safe(), username))
                else:
                    cur.execute("UPDATE auth_users SET employee_id=?, display_name=?, email=?, role_code=?, is_active=?, force_password_change=?, note=?, updated_at=? WHERE username=?", (employee_id, display_name, email, role_code, is_active, force_change, note, _v95_now_text_safe(), username))
            else:
                if not new_password or new_password == "********":
                    skipped.append(f"{username} 未設定新密碼 / new password required")
                    continue
                cur.execute("INSERT INTO auth_users(username,password_hash,password_hint,employee_id,display_name,email,role_code,is_active,force_password_change,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (username, hash_password(new_password), "由權限管理頁建立", employee_id, display_name, email, role_code, is_active, force_change, note, _v95_now_text_safe(), _v95_now_text_safe()))
            saved += 1
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        ensure_permissions_for_all_users(force=True)
        sync_auth_users_to_runtime_security()
    except Exception:
        pass
    return {"saved": saved, "skipped": skipped, "permanent_save": _v95_export_permission_authority("save_users_v95")}


def save_account_master(rows: _V94Iterable[dict], delete_usernames: _V94Iterable[str] | None = None) -> dict:  # type: ignore[override]
    init_permission_tables(force=False)
    delete_set = {str(u).strip().lower() for u in (delete_usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"}
    input_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    payload = _v95_read_permission_payload()
    deleted = _v95_deleted_usernames(payload) | delete_set
    payload["deleted_usernames"] = sorted(deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v95_filter_deleted_tables(payload.get("tables", {}), deleted)
        _v95_write_permission_payload(payload)
    # 先刪除，再儲存保留列。
    conn = connect_db(); cur = conn.cursor(); deleted_count = 0
    try:
        for u in sorted(delete_set):
            try:
                existed = cur.execute("SELECT COUNT(*) AS c FROM auth_users WHERE lower(username)=?", (u,)).fetchone()
                deleted_count += int(existed["c"] if existed else 0)
            except Exception:
                pass
            for sql in [
                "DELETE FROM auth_account_permissions WHERE lower(username)=?",
                "DELETE FROM security_user_roles WHERE lower(username)=?",
                "DELETE FROM security_users WHERE lower(username)=?",
                "DELETE FROM auth_users WHERE lower(username)=?",
            ]:
                try:
                    cur.execute(sql, (u,))
                except Exception:
                    pass
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    filtered_rows = []
    for r in input_rows:
        u = str(r.get("username") or r.get("帳號 / Username") or "").strip().lower()
        if u and u not in deleted:
            filtered_rows.append(r)
    result = save_users(filtered_rows)
    # save_users 可能因明確列出帳號移除 tombstone；帳號總表刪除要保留 tombstone。
    payload = _v95_read_permission_payload()
    payload["deleted_usernames"] = sorted(_v95_deleted_usernames(payload) | deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v95_filter_deleted_tables(payload.get("tables", {}), set(payload["deleted_usernames"]))
    _v95_write_permission_payload(payload)
    result["deleted"] = deleted_count
    result["deleted_usernames"] = sorted(set(payload.get("deleted_usernames", [])))
    result["permanent_save"] = _v95_export_permission_authority("save_account_master_v95")
    return result


def delete_users(usernames: _V94Iterable[str]) -> int:  # type: ignore[override]
    targets = {str(u).strip().lower() for u in (usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"}
    if not targets:
        return 0
    payload = _v95_read_permission_payload()
    deleted = _v95_deleted_usernames(payload) | targets
    payload["deleted_usernames"] = sorted(deleted)
    if isinstance(payload.get("tables"), dict):
        payload["tables"] = _v95_filter_deleted_tables(payload.get("tables", {}), deleted)
        _v95_write_permission_payload(payload)
    conn = connect_db(); cur = conn.cursor(); count = 0
    try:
        for u in sorted(targets):
            try:
                existed = cur.execute("SELECT COUNT(*) AS c FROM auth_users WHERE lower(username)=?", (u,)).fetchone()
                count += int(existed["c"] if existed else 0)
            except Exception:
                pass
            for sql in [
                "DELETE FROM auth_account_permissions WHERE lower(username)=?",
                "DELETE FROM security_user_roles WHERE lower(username)=?",
                "DELETE FROM security_users WHERE lower(username)=?",
                "DELETE FROM auth_users WHERE lower(username)=?",
            ]:
                try:
                    cur.execute(sql, (u,))
                except Exception:
                    pass
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    _v95_export_permission_authority("delete_users_v95")
    return int(count)


def save_account_permissions(rows: _V94Iterable[dict]) -> int:  # type: ignore[override]
    init_permission_tables(force=False)
    deleted = _v95_deleted_usernames()
    safe_rows = [dict(r) for r in (rows or []) if isinstance(r, dict) and str(r.get("username", "")).strip().lower() not in deleted]
    conn = connect_db(); cur = conn.cursor(); count = 0
    try:
        for r in safe_rows:
            username = str(r.get("username", "")).strip()
            module_code = str(r.get("module_code", "")).strip().zfill(2)
            if not username or not module_code:
                continue
            module_info = next((m for m in MODULES if m["module_code"] == module_code), None)
            module_name_zh = str(r.get("module_name_zh") or (module_info or {}).get("module_name_zh") or "").strip()
            module_name_en = str(r.get("module_name_en") or (module_info or {}).get("module_name_en") or "").strip()
            vals = {k: (_v91_bool(r.get(k, False), False) if "_v91_bool" in globals() else int(bool(r.get(k, False)))) for k, _, _ in ACTIONS}
            cur.execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(username,module_code) DO UPDATE SET
                    module_name_zh=excluded.module_name_zh, module_name_en=excluded.module_name_en,
                    can_view=excluded.can_view, can_create=excluded.can_create, can_edit=excluded.can_edit,
                    can_delete=excluded.can_delete, can_import=excluded.can_import, can_export=excluded.can_export,
                    can_backup=excluded.can_backup, can_restore=excluded.can_restore, can_manage=excluded.can_manage,
                    updated_at=excluded.updated_at
            """, (username, module_code, module_name_zh, module_name_en,
                  vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], _v95_now_text_safe()))
            count += 1
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        clear_permission_runtime_cache()
    except Exception:
        pass
    _v95_export_permission_authority("save_account_permissions_v95")
    return count


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    init_permission_tables(force=False)
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    conn = connect_db(); cur = conn.cursor()
    try:
        try:
            _ensure_security_setting_tables(cur)  # type: ignore[name-defined]
        except Exception:
            pass
        for k, v in merged.items():
            cur.execute("""
                INSERT INTO auth_security_settings(setting_key, setting_value, note, updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
            """, (str(k), str(v), "V95 single authority security setting", _v95_now_text_safe()))
            try:
                cur.execute("""
                    INSERT INTO security_settings(setting_key, setting_value, note, updated_at)
                    VALUES (?,?,?,?)
                    ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at
                """, (str(k), str(v), "V95 single authority security setting", _v95_now_text_safe()))
            except Exception:
                pass
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        clear_permission_runtime_cache()
    except Exception:
        pass
    _v95_export_permission_authority("save_security_settings_v95")

# 重要：維持 check_permission 對 has_permission 的指向，登入與模組管制不改。
check_permission = has_permission
# ===== V95 PERMISSION SINGLE-AUTHORITY SPEED + DELETE-PERSIST HARD FIX END =====

# ===== V96 PERMISSION TRUE SINGLE-AUTHORITY DIRECT READ/WRITE + SPEED PATCH START =====
# 目的：10. 權限管理不再依賴 SQLite 還原流程作為畫面來源；讀、寫、刪除、權限矩陣、安全設定
# 都直接以 data/permanent_store/modules/10_permissions/records.json 為唯一權威檔。
# SQLite 僅作登入/相容快取，且只在存檔後 best-effort 同步，不再於進頁面或勾選時重建造成卡頓。
import os as _v96_os
import base64 as _v96_base64
import urllib.request as _v96_urllib_request
import urllib.parse as _v96_urllib_parse

_V96_PERMISSION_AUTHORITY_FILE = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json"
_V96_PERMISSION_REL_PATH = "data/permanent_store/modules/10_permissions/records.json"
_V96_AUTH_TABLES = ["auth_users", "auth_account_permissions", "auth_security_settings", "security_settings", "security_users", "security_user_roles"]


def _v96_st_secret(name: str, default: str = "") -> str:
    try:
        if st is not None:
            val = st.secrets.get(name, "")  # type: ignore[attr-defined]
            if val:
                return str(val).strip()
    except Exception:
        pass
    return _v96_os.environ.get(name, default).strip()


def _v96_github_cfg() -> dict:
    repo = _v96_st_secret("GITHUB_REPOSITORY", "")
    if not repo:
        owner = _v96_st_secret("GITHUB_REPO_OWNER", "")
        name = _v96_st_secret("GITHUB_REPO_NAME", "")
        if owner and name:
            repo = f"{owner}/{name}"
    if not repo:
        repo = "cheng07021028/SPT-time-tracking-system"
    return {
        "token": _v96_st_secret("GITHUB_TOKEN", ""),
        "repo": repo,
        "branch": _v96_st_secret("GITHUB_BRANCH", _v96_st_secret("GITHUB_REPO_BRANCH", "main")) or "main",
    }


def _v96_fast_github_put(rel_path: str, text: str, message: str) -> dict:
    cfg = _v96_github_cfg()
    if not cfg.get("token") or not cfg.get("repo"):
        return {"ok": False, "skipped": True, "reason": "missing_github_config"}
    api = f"https://api.github.com/repos/{cfg['repo']}/contents/{_v96_urllib_parse.quote(rel_path)}"
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "SPT-TimeTracking-V96",
    }
    sha = ""
    try:
        req = _v96_urllib_request.Request(api + f"?ref={_v96_urllib_parse.quote(cfg['branch'])}", headers=headers, method="GET")
        with _v96_urllib_request.urlopen(req, timeout=5) as resp:
            data = _v94_json.loads(resp.read().decode("utf-8"))
            sha = str(data.get("sha") or "")
            try:
                old_text = _v96_base64.b64decode(str(data.get("content", "")).encode("ascii")).decode("utf-8")
                if old_text == text:
                    return {"ok": True, "skipped": True, "reason": "unchanged", "path": rel_path}
            except Exception:
                pass
    except Exception:
        sha = ""
    body = {"message": message, "content": _v96_base64.b64encode(text.encode("utf-8")).decode("ascii"), "branch": cfg["branch"]}
    if sha:
        body["sha"] = sha
    try:
        req = _v96_urllib_request.Request(api, data=_v94_json.dumps(body).encode("utf-8"), headers=headers, method="PUT")
        with _v96_urllib_request.urlopen(req, timeout=8) as resp:
            got = _v94_json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "path": rel_path, "commit": (got.get("commit") or {}).get("sha", "")}
    except Exception as exc:
        return {"ok": False, "path": rel_path, "error": str(exc)[:300]}


def _v96_auth_payload() -> dict:
    try:
        if _V96_PERMISSION_AUTHORITY_FILE.exists() and _V96_PERMISSION_AUTHORITY_FILE.stat().st_size > 2:
            data = _v94_json.loads(_V96_PERMISSION_AUTHORITY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {
        "authority_schema": "SPT-10-Permissions-SingleAuthority-V96",
        "version": "V96-direct-authority",
        "module_key": "10_permissions",
        "kind": "records",
        "authority_file": _V96_PERMISSION_REL_PATH,
        "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text(),
        "deleted_usernames": [],
        "tables": {k: [] for k in _V96_AUTH_TABLES},
        "table_counts": {k: 0 for k in _V96_AUTH_TABLES},
    }


def _v96_deleted(payload: dict | None = None) -> set[str]:
    payload = payload if isinstance(payload, dict) else _v96_auth_payload()
    raw = payload.get("deleted_usernames", []) if isinstance(payload, dict) else []
    return {str(x).strip().lower() for x in raw if str(x).strip() and str(x).strip().lower() != "admin"}


def _v96_filter_deleted_tables(tables: dict, deleted: set[str]) -> dict:
    deleted = {str(x).strip().lower() for x in (deleted or set()) if str(x).strip().lower() != "admin"}
    out = {}
    for t in _V96_AUTH_TABLES:
        rows = tables.get(t, []) if isinstance(tables, dict) else []
        clean = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            u = str(r.get("username") or r.get("帳號") or r.get("帳號 / Username") or "").strip().lower()
            if u and u in deleted:
                continue
            x = dict(r)
            x.pop("id", None)
            clean.append(x)
        out[t] = clean
    return out


def _v96_write_payload(payload: dict, reason: str = "permission_v96_save", *, github: bool = True) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    deleted = _v96_deleted(payload)
    tables = _v96_filter_deleted_tables(tables, deleted)
    payload.update({
        "authority_schema": "SPT-10-Permissions-SingleAuthority-V96",
        "version": "V96-direct-authority",
        "module_key": "10_permissions",
        "kind": "records",
        "authority_file": _V96_PERMISSION_REL_PATH,
        "reason": reason,
        "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text(),
        "deleted_usernames": sorted(deleted),
        "tables": tables,
        "table_counts": {k: len(v) for k, v in tables.items() if isinstance(v, list)},
    })
    _V96_PERMISSION_AUTHORITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = _v94_json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    tmp = _V96_PERMISSION_AUTHORITY_FILE.with_suffix(".json.tmp")
    changed = True
    try:
        changed = (not _V96_PERMISSION_AUTHORITY_FILE.exists()) or (_V96_PERMISSION_AUTHORITY_FILE.read_text(encoding="utf-8") != text)
    except Exception:
        changed = True
    if changed:
        tmp.write_text(text, encoding="utf-8")
        _v94_json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(_V96_PERMISSION_AUTHORITY_FILE)
    gh = {"ok": True, "skipped": True, "reason": "unchanged_or_disabled"}
    if github and changed:
        gh = _v96_fast_github_put(_V96_PERMISSION_REL_PATH, text, f"SPT 10 permissions authority: {reason}")
    try:
        clear_permission_runtime_cache()
    except Exception:
        pass
    return {"ok": True, "changed": changed, "github": gh, "file": str(_V96_PERMISSION_AUTHORITY_FILE)}


def _v96_table(name: str) -> list[dict]:
    payload = _v96_auth_payload()
    deleted = _v96_deleted(payload)
    tables = _v96_filter_deleted_tables(payload.get("tables", {}), deleted)
    return [dict(r) for r in tables.get(name, [])]


def init_permission_tables(force: bool = False) -> None:  # type: ignore[override]
    # V96：進入 10 頁或勾選 checkbox 不再把權威檔整批灌回 SQLite，避免 1~3 分鐘卡頓。
    try:
        _v95_schema_only() if "_v95_schema_only" in globals() else None
    except Exception:
        pass

init_auth_tables = init_permission_tables


def restore_permission_settings_from_permanent_files(force: bool = False) -> dict:  # type: ignore[override]
    return {"ok": True, "mode": "v96_direct_authority_no_page_restore", "file": str(_V96_PERMISSION_AUTHORITY_FILE)}


def restore_default_accounts_once_v57() -> dict:  # type: ignore[override]
    return {"restored": 0, "usernames": [], "mode": "v96_disabled_default_restore"}


def get_users() -> List[dict]:  # type: ignore[override]
    rows = _v96_table("auth_users")
    out = []
    for r in rows:
        u = str(r.get("username") or "").strip()
        if not u:
            continue
        x = dict(r)
        x["username"] = u
        x.setdefault("password_display", "********" if x.get("password_hash") else "")
        x.setdefault("new_password", "")
        x.setdefault("role_code", "operator")
        x["is_active"] = 1 if _truthy(x.get("is_active", True), True) else 0
        x["force_password_change"] = 1 if _truthy(x.get("force_password_change", False), False) else 0
        out.append(x)
    return sorted(out, key=lambda x: (0 if x.get("username") == "admin" else 1, str(x.get("username", ""))))


def _v96_role_preset(role: str, module_code: str) -> dict:
    role = str(role or "operator").strip().lower() or "operator"
    preset = dict(ROLE_PRESET.get(role, ROLE_PRESET.get("operator", {})))
    if role == "operator" and module_code in ("01", "02", "08"):
        preset["can_view"] = 1
        if module_code == "01":
            preset["can_create"] = 1; preset["can_edit"] = 1
    if role == "leader" and module_code in ("01", "02", "04", "07", "08"):
        preset["can_view"] = 1
    if role == "auditor" and module_code in ("02", "06", "11"):
        preset["can_view"] = 1
    return {k: int(_truthy(v, False)) for k, v in preset.items()}


def _v96_default_permission_rows_for_user(username: str, role: str) -> list[dict]:
    rows = []
    for m in MODULES:
        vals = _v96_role_preset(role, str(m.get("module_code", "")).zfill(2))
        row = {
            "username": username,
            "module_code": str(m.get("module_code", "")).zfill(2),
            "module_name_zh": str(m.get("module_name_zh", "")),
            "module_name_en": str(m.get("module_name_en", "")),
            "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text(),
        }
        for k, _, _ in ACTIONS:
            row[k] = int(vals.get(k, 0))
        rows.append(row)
    return rows


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    payload = _v96_auth_payload()
    deleted = _v96_deleted(payload)
    tables = _v96_filter_deleted_tables(payload.get("tables", {}), deleted)
    users = {str(u.get("username") or "").strip(): dict(u) for u in tables.get("auth_users", []) if str(u.get("username") or "").strip()}
    rows = [dict(r) for r in tables.get("auth_account_permissions", [])]
    existing = {(str(r.get("username") or ""), str(r.get("module_code") or "").zfill(2)) for r in rows}
    for u, info in users.items():
        role = str(info.get("role_code") or "operator")
        for r in _v96_default_permission_rows_for_user(u, role):
            key = (r["username"], r["module_code"])
            if key not in existing:
                rows.append(r); existing.add(key)
    out = []
    for r in rows:
        u = str(r.get("username") or "").strip()
        if not u or u.lower() in deleted:
            continue
        user = users.get(u, {})
        x = dict(r)
        x["username"] = u
        x["display_name"] = user.get("display_name", x.get("display_name", ""))
        x["role_code"] = user.get("role_code", x.get("role_code", "operator"))
        x["module_code"] = str(x.get("module_code") or "").zfill(2)
        for m in MODULES:
            if str(m.get("module_code", "")).zfill(2) == x["module_code"]:
                x.setdefault("module_name_zh", m.get("module_name_zh", ""))
                x.setdefault("module_name_en", m.get("module_name_en", ""))
        for k, _, _ in ACTIONS:
            x[k] = int(_truthy(x.get(k, False), False))
        out.append(x)
    return sorted(out, key=lambda x: (str(x.get("username", "")), int(str(x.get("module_code") or "0") or 0)))


def _v96_normalize_user_row(r: dict, existing: dict | None = None) -> tuple[dict | None, str]:
    existing = existing or {}
    username = str(r.get("username") or r.get("帳號 / Username") or r.get("帳號") or "").strip()
    if not username:
        return None, "空白帳號略過"
    role = str(r.get("role_code") or r.get("角色 / Role") or existing.get("role_code") or "operator").strip() or "operator"
    new_password = str(r.get("new_password") or r.get("密碼 / Password") or r.get("新密碼 / New Password") or r.get("password") or "").strip()
    password_hash = str(existing.get("password_hash") or "")
    password_hint = str(existing.get("password_hint") or "")
    if new_password and new_password != "********":
        password_hash = hash_password(new_password)
        password_hint = "由權限管理頁更新"
    elif not password_hash:
        return None, f"{username} 未設定新密碼 / new password required"
    row = {
        "username": username,
        "password_hash": password_hash,
        "password_hint": password_hint,
        "employee_id": str(r.get("employee_id") or r.get("工號 / Employee ID") or existing.get("employee_id") or "").strip(),
        "display_name": str(r.get("display_name") or r.get("姓名 / Display Name") or existing.get("display_name") or username).strip(),
        "email": str(r.get("email") or r.get("Email") or existing.get("email") or "").strip(),
        "role_code": role,
        "is_active": 1 if _truthy(r.get("is_active", r.get("啟用 / Active", existing.get("is_active", True))), True) else 0,
        "force_password_change": 1 if _truthy(r.get("force_password_change", r.get("強制改密碼 / Force Change", existing.get("force_password_change", False))), False) else 0,
        "note": str(r.get("note") or r.get("備註 / Note") or existing.get("note") or "").strip(),
        "created_at": existing.get("created_at") or (_v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text()),
        "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text(),
    }
    return row, ""


def save_users(rows: _V94Iterable[dict]) -> dict:  # type: ignore[override]
    payload = _v96_auth_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {k: [] for k in _V96_AUTH_TABLES}
    deleted = _v96_deleted(payload)
    existing_users = {str(u.get("username") or "").strip().lower(): dict(u) for u in tables.get("auth_users", []) if str(u.get("username") or "").strip()}
    saved = 0; skipped = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        username_key = str(r.get("username") or r.get("帳號 / Username") or "").strip().lower()
        row, msg = _v96_normalize_user_row(r, existing_users.get(username_key))
        if not row:
            if msg:
                skipped.append(msg)
            continue
        uk = row["username"].lower()
        existing_users[uk] = row
        deleted.discard(uk)
        saved += 1
    tables["auth_users"] = list(existing_users.values())
    # 補足新帳號預設權限，但不覆蓋既有權限矩陣。
    perms = [dict(x) for x in tables.get("auth_account_permissions", []) if isinstance(x, dict)]
    perm_keys = {(str(p.get("username") or "").strip().lower(), str(p.get("module_code") or "").zfill(2)) for p in perms}
    for u in tables["auth_users"]:
        uk = str(u.get("username") or "").strip().lower()
        if not uk or uk in deleted:
            continue
        for p in _v96_default_permission_rows_for_user(str(u.get("username")), str(u.get("role_code") or "operator")):
            key = (str(p.get("username") or "").strip().lower(), str(p.get("module_code") or "").zfill(2))
            if key not in perm_keys:
                perms.append(p); perm_keys.add(key)
    tables["auth_account_permissions"] = perms
    payload["tables"] = tables
    payload["deleted_usernames"] = sorted(deleted)
    result = _v96_write_payload(payload, "save_users_v96", github=True)
    _v96_best_effort_restore_cache(payload)
    return {"saved": saved, "skipped": skipped, "permanent_save": result}


def save_account_master(rows: _V94Iterable[dict], delete_usernames: _V94Iterable[str] | None = None) -> dict:  # type: ignore[override]
    delete_set = {str(u).strip().lower() for u in (delete_usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"}
    payload = _v96_auth_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {k: [] for k in _V96_AUTH_TABLES}
    old_deleted = _v96_deleted(payload) | delete_set
    tables = _v96_filter_deleted_tables(tables, old_deleted)
    payload["tables"] = tables; payload["deleted_usernames"] = sorted(old_deleted)
    _v96_write_payload(payload, "save_account_master_pre_delete_v96", github=True)
    result = save_users([dict(r) for r in (rows or []) if isinstance(r, dict)])
    payload = _v96_auth_payload()
    deleted = _v96_deleted(payload) | delete_set
    payload["deleted_usernames"] = sorted(deleted)
    payload["tables"] = _v96_filter_deleted_tables(payload.get("tables", {}), deleted)
    final = _v96_write_payload(payload, "save_account_master_v96", github=True)
    _v96_best_effort_restore_cache(payload)
    result["deleted"] = len(delete_set)
    result["deleted_usernames"] = sorted(deleted)
    result["permanent_save"] = final
    return result


def delete_users(usernames: _V94Iterable[str]) -> int:  # type: ignore[override]
    targets = {str(u).strip().lower() for u in (usernames or []) if str(u).strip() and str(u).strip().lower() != "admin"}
    if not targets:
        return 0
    payload = _v96_auth_payload()
    deleted = _v96_deleted(payload) | targets
    payload["deleted_usernames"] = sorted(deleted)
    payload["tables"] = _v96_filter_deleted_tables(payload.get("tables", {}), deleted)
    result = _v96_write_payload(payload, "delete_users_v96", github=True)
    _v96_best_effort_restore_cache(payload)
    return len(targets)


def save_account_permissions(rows: _V94Iterable[dict]) -> int:  # type: ignore[override]
    payload = _v96_auth_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {k: [] for k in _V96_AUTH_TABLES}
    deleted = _v96_deleted(payload)
    clean = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        username = str(r.get("username") or "").strip()
        if not username or username.lower() in deleted:
            continue
        module_code = str(r.get("module_code") or "").strip().zfill(2)
        if not module_code:
            continue
        mod = next((m for m in MODULES if str(m.get("module_code", "")).zfill(2) == module_code), {})
        x = {
            "username": username,
            "module_code": module_code,
            "module_name_zh": str(r.get("module_name_zh") or mod.get("module_name_zh") or ""),
            "module_name_en": str(r.get("module_name_en") or mod.get("module_name_en") or ""),
            "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text(),
        }
        for k, _, _ in ACTIONS:
            x[k] = 1 if _truthy(r.get(k, False), False) else 0
        clean.append(x)
    tables["auth_account_permissions"] = clean
    payload["tables"] = tables
    _v96_write_payload(payload, "save_account_permissions_v96", github=True)
    _v96_best_effort_restore_cache(payload)
    return len(clean)


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    payload = _v96_auth_payload()
    rows = []
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    for t in ["auth_security_settings", "security_settings"]:
        rows.extend([dict(r) for r in tables.get(t, []) if isinstance(r, dict)])
    out = dict(DEFAULT_SECURITY_SETTINGS)
    for r in rows:
        k = str(r.get("setting_key") or "").strip()
        if k:
            out[k] = str(r.get("setting_value") or "")
    return out


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    payload = _v96_auth_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {k: [] for k in _V96_AUTH_TABLES}
    merged = get_security_settings(); merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    rows = [{"setting_key": k, "setting_value": v, "note": "V96 single authority security setting", "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text()} for k, v in merged.items()]
    tables["auth_security_settings"] = rows
    tables["security_settings"] = list(rows)
    payload["tables"] = tables
    _v96_write_payload(payload, "save_security_settings_v96", github=True)
    _v96_best_effort_restore_cache(payload)


def _v96_best_effort_restore_cache(payload: dict | None = None) -> None:
    # Best-effort 同步 SQLite 快取；失敗不影響權威檔，不在進頁面時執行。
    payload = payload if isinstance(payload, dict) else _v96_auth_payload()
    tables = _v96_filter_deleted_tables(payload.get("tables", {}), _v96_deleted(payload))
    try:
        _v95_schema_only() if "_v95_schema_only" in globals() else None
        conn = connect_db(); cur = conn.cursor()
        for table in _V96_AUTH_TABLES:
            try:
                cur.execute(f'DELETE FROM "{table}"')
            except Exception:
                continue
            try:
                cols = {str(r[1]) for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
            except Exception:
                cols = set()
            for row in tables.get(table, []):
                clean = {str(k): v for k, v in dict(row).items() if str(k) in cols and str(k) != "id"}
                if not clean:
                    continue
                sql_cols = ",".join([f'"{c}"' for c in clean.keys()])
                ph = ",".join(["?"] * len(clean))
                try:
                    cur.execute(f'INSERT INTO "{table}" ({sql_cols}) VALUES ({ph})', list(clean.values()))
                except Exception:
                    pass
        conn.commit(); conn.close()
    except Exception:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass

# 重要：維持 check_permission 對 has_permission 的指向，登入與模組管制不改。
check_permission = has_permission
# ===== V96 PERMISSION TRUE SINGLE-AUTHORITY DIRECT READ/WRITE + SPEED PATCH END =====

# ===== V97 PERMISSION SECURITY SETTINGS NAMEERROR GUARD START =====
# Fix: 10｜權限管理曾因 DEFAULT_SECURITY_SETTINGS 遺失而整頁 NameError。
# This final wrapper keeps security settings local-first and direct-authority based.
def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    payload = _v96_auth_payload() if "_v96_auth_payload" in globals() else {}
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    out = dict(DEFAULT_SECURITY_SETTINGS)
    for t in ["auth_security_settings", "security_settings"]:
        for r in tables.get(t, []) if isinstance(tables.get(t, []), list) else []:
            if not isinstance(r, dict):
                continue
            k = str(r.get("setting_key") or "").strip()
            if k:
                out[k] = str(r.get("setting_value") if r.get("setting_value") is not None else out.get(k, ""))
    return out


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    payload = _v96_auth_payload() if "_v96_auth_payload" in globals() else {}
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {k: [] for k in _V96_AUTH_TABLES}
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    try:
        idle = max(1, int(float(merged.get("idle_timeout_minutes", "15") or 15)))
    except Exception:
        idle = 15
    merged["idle_timeout_minutes"] = str(idle)
    merged["ask_continue_after_record"] = "0" if str(merged.get("ask_continue_after_record", "1")).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
    rows = [{
        "setting_key": k,
        "setting_value": v,
        "note": "V97 direct-authority security setting",
        "updated_at": _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text(),
    } for k, v in merged.items()]
    tables["auth_security_settings"] = rows
    tables["security_settings"] = list(rows)
    payload["tables"] = tables
    if "_v96_write_payload" in globals():
        _v96_write_payload(payload, "save_security_settings_v97", github=True)
        try:
            _v96_best_effort_restore_cache(payload)
        except Exception:
            pass
    if st is not None:
        try:
            st.session_state["_spt_idle_timeout_cache"] = {"minutes": idle, "ts": 0}
            st.session_state["spt_security_settings"] = dict(merged)
        except Exception:
            pass

check_permission = has_permission
# ===== V97 PERMISSION SECURITY SETTINGS NAMEERROR GUARD END =====


# ========================= V98 SECURITY SETTINGS WRITE-THROUGH ALIGNMENT =========================
# 10｜權限管理安全設定的畫面值、登入列顯示值、權威檔值必須一致。
_v98_prev_get_security_settings = get_security_settings
_v98_prev_save_security_settings = save_security_settings


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    out = dict(DEFAULT_SECURITY_SETTINGS)
    try:
        out.update(_v98_prev_get_security_settings())
    except Exception:
        pass
    # 讓 10 頁也吃 security_service 的 permanent_store 優先讀法，避免畫面與上方登入列不同。
    try:
        from services.security_service import get_idle_timeout_minutes as _get_idle
        out["idle_timeout_minutes"] = str(int(_get_idle()))
    except Exception:
        pass
    return out


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    try:
        idle = max(1, int(float(merged.get("idle_timeout_minutes", "15") or 15)))
    except Exception:
        idle = 15
    ask = "0" if str(merged.get("ask_continue_after_record", "1")).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
    merged["idle_timeout_minutes"] = str(idle)
    merged["ask_continue_after_record"] = ask
    try:
        _v98_prev_save_security_settings(merged)
    except Exception:
        # 不讓舊函式失敗阻斷新的權威寫入。
        pass
    try:
        from services.security_service import set_idle_timeout_minutes as _set_idle
        _set_idle(idle)
    except Exception:
        pass
    if st is not None:
        try:
            st.session_state["_spt_idle_timeout_cache"] = {"minutes": idle, "ts": 0}
            st.session_state["spt_security_settings"] = dict(merged)
        except Exception:
            pass

check_permission = has_permission
# ======================= END V98 SECURITY SETTINGS WRITE-THROUGH ALIGNMENT =======================

# ========================= V101 PERMISSION SECURITY + ACCOUNT SAFETY FIX =========================
# 修正目的：
# 1) 10｜權限管理安全設定儲存後仍跳回 15 分鐘。
# 2) 10｜權限管理停止編輯時若讀到空權威檔，帳號表不可被空表覆蓋。
# 3) get_users() 以 auth_users 為主，必要時相容 security_users，但尊重 deleted_usernames。

def _v101_truthy_value(v, default: bool = False) -> bool:
    try:
        return _truthy(v, default)  # type: ignore[name-defined]
    except Exception:
        if v is None:
            return default
        t = str(v).strip().lower()
        if t in {"1", "true", "yes", "y", "on", "是", "啟用", "active"}:
            return True
        if t in {"0", "false", "no", "n", "off", "否", "停用", "inactive", ""}:
            return False
        return default


def _v101_load_permission_tables() -> dict:
    try:
        from services.permanent_authority_service import load_tables as _pa_load_tables
        tables = _pa_load_tables("10_permissions", "records")
        return tables if isinstance(tables, dict) else {}
    except Exception:
        try:
            payload = _v96_auth_payload() if "_v96_auth_payload" in globals() else {}
            return payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        except Exception:
            return {}


def _v101_deleted_users(tables: dict | None = None) -> set[str]:
    try:
        payload = _v96_auth_payload() if "_v96_auth_payload" in globals() else {}
        return {str(x).strip().lower() for x in (payload.get("deleted_usernames") or []) if str(x).strip()}
    except Exception:
        return set()


def get_users() -> List[dict]:  # type: ignore[override]
    tables = _v101_load_permission_tables()
    deleted = _v101_deleted_users(tables)
    rows = [dict(r) for r in tables.get("auth_users", []) if isinstance(r, dict)]
    if not rows:
        rows = [dict(r) for r in tables.get("security_users", []) if isinstance(r, dict)]
    out: list[dict] = []
    for r in rows:
        u = str(r.get("username") or r.get("user_name") or "").strip()
        if not u or u.lower() in deleted:
            continue
        x = dict(r)
        x["username"] = u
        x.setdefault("password_display", "********" if x.get("password_hash") else "")
        x.setdefault("new_password", "")
        x.setdefault("role_code", x.get("role") or "operator")
        x["is_active"] = 1 if _v101_truthy_value(x.get("is_active", True), True) else 0
        x["force_password_change"] = 1 if _v101_truthy_value(x.get("force_password_change", False), False) else 0
        out.append(x)
    return sorted(out, key=lambda x: (0 if str(x.get("username", "")).lower() == "admin" else 1, str(x.get("username", "")).lower()))


def _v101_extract_setting_from_payload(payload: dict, key: str) -> str | None:
    try:
        if not isinstance(payload, dict):
            return None
        settings = payload.get("settings")
        if isinstance(settings, dict):
            if settings.get(key) not in (None, ""):
                return str(settings.get(key))
            sec = settings.get("security_settings")
            if isinstance(sec, dict) and sec.get(key) not in (None, ""):
                return str(sec.get(key))
        sec2 = payload.get("security_settings")
        if isinstance(sec2, dict) and sec2.get(key) not in (None, ""):
            return str(sec2.get(key))
        tables = payload.get("tables")
        if isinstance(tables, dict):
            for table_name in ("auth_security_settings", "security_settings"):
                for row in tables.get(table_name, []) if isinstance(tables.get(table_name), list) else []:
                    if isinstance(row, dict) and str(row.get("setting_key") or "").strip() == key:
                        if row.get("setting_value") not in (None, ""):
                            return str(row.get("setting_value"))
    except Exception:
        return None
    return None


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    out = dict(DEFAULT_SECURITY_SETTINGS)
    try:
        from services.permanent_authority_service import load_authority as _pa_load_authority
        # settings.json 是最高優先來源。
        sp = _pa_load_authority("10_permissions", "settings")
        rp = _pa_load_authority("10_permissions", "records")
        for key in ("idle_timeout_minutes", "ask_continue_after_record"):
            val = _v101_extract_setting_from_payload(sp, key)
            if val is None:
                val = _v101_extract_setting_from_payload(rp, key)
            if val not in (None, ""):
                out[key] = str(val)
    except Exception:
        pass
    try:
        from services.security_service import get_idle_timeout_minutes as _get_idle
        out["idle_timeout_minutes"] = str(int(_get_idle()))
    except Exception:
        pass
    out["ask_continue_after_record"] = "0" if str(out.get("ask_continue_after_record", "1")).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
    return out


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    merged = get_security_settings()
    merged.update({str(k): str(v) for k, v in (settings or {}).items()})
    try:
        idle = max(1, int(float(merged.get("idle_timeout_minutes", "15") or 15)))
    except Exception:
        idle = 15
    ask = "0" if str(merged.get("ask_continue_after_record", "1")).strip().lower() in {"0", "false", "no", "n", "否"} else "1"
    merged["idle_timeout_minutes"] = str(idle)
    merged["ask_continue_after_record"] = ask
    try:
        from services.security_service import set_idle_timeout_minutes as _set_idle
        _set_idle(idle)
    except Exception:
        pass
    try:
        from services.permanent_authority_service import load_tables as _pa_load_tables, save_authority as _pa_save_authority, save_settings as _pa_save_settings, force_upload_authority_file as _pa_force
        now = _v95_now_text_safe() if "_v95_now_text_safe" in globals() else now_text()
        _pa_save_settings("10_permissions", {
            "idle_timeout_minutes": str(idle),
            "ask_continue_after_record": ask,
            "security_settings": dict(merged),
            "updated_at": now,
        }, reason="v101_save_security_settings", github=True)
        tables = _pa_load_tables("10_permissions", "records")
        rows = [
            {"setting_key": "idle_timeout_minutes", "setting_value": str(idle), "note": "V101 permission page security setting", "updated_at": now},
            {"setting_key": "ask_continue_after_record", "setting_value": ask, "note": "V101 permission page security setting", "updated_at": now},
        ]
        tables["auth_security_settings"] = rows
        tables["security_settings"] = list(rows)
        _pa_save_authority("10_permissions", records=tables, reason="v101_save_security_settings_records", github=True)
        try:
            _pa_force("10_permissions", "settings", reason="v101_force_upload_security_settings")
            _pa_force("10_permissions", "records", reason="v101_force_upload_security_records")
        except Exception:
            pass
    except Exception:
        pass
    if st is not None:
        try:
            st.session_state["_spt_idle_timeout_cache"] = {"minutes": idle, "ts": 0}
            st.session_state["spt_security_settings"] = dict(merged)
        except Exception:
            pass

check_permission = has_permission
# ======================= END V101 PERMISSION SECURITY + ACCOUNT SAFETY FIX =======================

# ========================= V125 ACCOUNT MASTER PERMISSION RECONCILIATION =========================
# 目的：10｜權限管理「帳號密碼總表」儲存後，必須同步核對「帳號模組權限」。
# - 新增帳號 / 修改角色後，自動補齊每個帳號 01~13 權限列。
# - role operator 至少可進 01、02、08；01 可新增/編輯，避免現場帳號無法進工時紀錄。
# - 儲存權限時採 merge，不可因篩選畫面只顯示部分資料就覆蓋整張權限表。
# - Runtime 仍以 10_permissions/records.json 權威檔為準。
try:
    _v125_prev_save_users = save_users  # type: ignore[name-defined]
except Exception:
    _v125_prev_save_users = None
try:
    _v125_prev_save_account_master = save_account_master  # type: ignore[name-defined]
except Exception:
    _v125_prev_save_account_master = None
try:
    _v125_prev_save_account_permissions = save_account_permissions  # type: ignore[name-defined]
except Exception:
    _v125_prev_save_account_permissions = None
try:
    _v125_prev_get_account_permissions = get_account_permissions  # type: ignore[name-defined]
except Exception:
    _v125_prev_get_account_permissions = None

_V125_DEFAULT_PROTECTED_ACCOUNTS = {"admin", "manager", "leader", "operator", "viewer", "auditor"}


def _v125_bool(v, default: bool = False) -> bool:
    try:
        return bool(_truthy(v, default))  # type: ignore[name-defined]
    except Exception:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return float(v) != 0
        s = str(v).strip().lower()
        if s in {"1", "true", "yes", "y", "on", "是", "啟用", "active", "checked", "勾選"}:
            return True
        if s in {"0", "false", "no", "n", "off", "否", "停用", "inactive", "unchecked", ""}:
            return False
        return default


def _v125_now() -> str:
    try:
        return _v95_now_text_safe()  # type: ignore[name-defined]
    except Exception:
        return now_text()


def _v125_role_preset(role: str, module_code: str) -> dict:
    try:
        return dict(_v96_role_preset(role, module_code))  # type: ignore[name-defined]
    except Exception:
        role = str(role or "operator").strip().lower() or "operator"
        base = {k: 0 for k, _, _ in ACTIONS}
        if role == "admin":
            return {k: 1 for k in base}
        if role == "operator":
            if module_code in {"01", "02", "08"}:
                base["can_view"] = 1
            if module_code == "01":
                base["can_create"] = 1; base["can_edit"] = 1
        elif role == "leader":
            if module_code in {"01", "02", "04", "07", "08"}:
                base["can_view"] = 1; base["can_create"] = 1; base["can_edit"] = 1
        elif role == "manager":
            for k in ("can_view", "can_create", "can_edit", "can_import", "can_export"):
                base[k] = 1
        elif role == "viewer":
            base["can_view"] = 1; base["can_export"] = 1
        elif role == "auditor":
            if module_code in {"02", "06", "11", "12"}:
                base["can_view"] = 1; base["can_export"] = 1
        return base


def _v125_permission_payload() -> dict:
    try:
        return _v96_auth_payload()  # type: ignore[name-defined]
    except Exception:
        try:
            from services.permanent_authority_service import load_authority
            payload = load_authority("10_permissions", "records")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}


def _v125_write_permission_payload(payload: dict, reason: str) -> dict:
    try:
        return _v96_write_payload(payload, reason, github=True)  # type: ignore[name-defined]
    except Exception:
        try:
            from services.permanent_authority_service import save_authority
            tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
            return save_authority("10_permissions", records=tables, reason=reason, github=True)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}


def _v125_clean_username(row: dict) -> str:
    return str(row.get("username") or row.get("帳號") or row.get("帳號 / Username") or "").strip()


def _v125_normalize_module_no(v) -> str:
    s = str(v or "").strip()
    if s in {"01_time_record", "01_time_records"}: return "01"
    if s == "02_history": return "02"
    if s == "03_work_orders": return "03"
    if s == "04_employees": return "04"
    if s == "05_analysis": return "05"
    if s in {"06_logs", "06_system_logs"}: return "06"
    if s in {"07_missing", "07_missing_records"}: return "07"
    if s == "08_daily_hours": return "08"
    if s == "09_persistence": return "09"
    if s == "10_permissions": return "10"
    if s == "11_login_logs": return "11"
    if s == "12_module_persistence": return "12"
    if s == "13_system_settings": return "13"
    digits = "".join(ch for ch in s[:2] if ch.isdigit())
    return digits.zfill(2) if digits else s.zfill(2)


def reconcile_account_module_permissions_v125(*, reason: str = "v125_reconcile", write: bool = True) -> dict:
    payload = _v125_permission_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    users = [dict(r) for r in tables.get("auth_users", []) if isinstance(r, dict)]
    if not users and isinstance(tables.get("security_users"), list):
        users = [dict(r) for r in tables.get("security_users", []) if isinstance(r, dict)]
    deleted = set()
    try:
        deleted = set(_v96_deleted(payload))  # type: ignore[name-defined]
    except Exception:
        deleted = {str(x).strip().lower() for x in payload.get("deleted_usernames", []) if str(x).strip()}

    by_user: dict[str, dict] = {}
    for u in users:
        name = _v125_clean_username(u)
        if not name or name.lower() in deleted:
            continue
        x = dict(u)
        x["username"] = name
        role = str(x.get("role_code") or x.get("role") or x.get("角色") or "operator").strip().lower() or "operator"
        if role not in {"admin", "manager", "leader", "operator", "viewer", "auditor"}:
            role = "operator"
        x["role_code"] = role
        # 預設角色帳號不可停用；其他帳號保留使用者設定。
        if name.lower() in _V125_DEFAULT_PROTECTED_ACCOUNTS:
            x["is_active"] = 1
        else:
            x["is_active"] = 1 if _v125_bool(x.get("is_active", True), True) else 0
        by_user[name.lower()] = x

    existing_rows = [dict(r) for r in tables.get("auth_account_permissions", []) if isinstance(r, dict)]
    rows_by_key: dict[tuple[str, str], dict] = {}
    for r in existing_rows:
        username = _v125_clean_username(r)
        if not username or username.lower() in deleted or username.lower() not in by_user:
            continue
        module_no = _v125_normalize_module_no(r.get("module_code"))
        if not module_no or not module_no[:2].isdigit():
            continue
        key = (username.lower(), module_no)
        x = dict(r)
        x["username"] = by_user[username.lower()]["username"]
        x["module_code"] = module_no
        for m in MODULES:
            if str(m.get("module_code", "")).zfill(2) == module_no:
                x["module_name_zh"] = str(m.get("module_name_zh", x.get("module_name_zh", "")))
                x["module_name_en"] = str(m.get("module_name_en", x.get("module_name_en", "")))
                break
        for col, _, _ in ACTIONS:
            x[col] = 1 if _v125_bool(x.get(col, False), False) else 0
        rows_by_key[key] = x

    added = 0; upgraded = 0; normalized = 0
    now = _v125_now()
    for uname_lower, u in sorted(by_user.items(), key=lambda kv: kv[0]):
        username = str(u.get("username") or "").strip()
        role = str(u.get("role_code") or "operator").strip().lower() or "operator"
        for m in MODULES:
            module_no = str(m.get("module_code", "")).zfill(2)
            key = (uname_lower, module_no)
            base = _v125_role_preset(role, module_no)
            if key not in rows_by_key:
                row = {
                    "username": username,
                    "module_code": module_no,
                    "module_name_zh": str(m.get("module_name_zh", "")),
                    "module_name_en": str(m.get("module_name_en", "")),
                    "updated_at": now,
                }
                for col, _, _ in ACTIONS:
                    row[col] = int(base.get(col, 0))
                rows_by_key[key] = row
                added += 1
            else:
                row = rows_by_key[key]
                before = {col: int(row.get(col, 0) or 0) for col, _, _ in ACTIONS}
                row["username"] = username
                row["module_code"] = module_no
                row["module_name_zh"] = str(m.get("module_name_zh", row.get("module_name_zh", "")))
                row["module_name_en"] = str(m.get("module_name_en", row.get("module_name_en", "")))
                # role baseline is a minimum. Custom extra permissions remain untouched.
                for col, _, _ in ACTIONS:
                    row[col] = 1 if (int(row.get(col, 0) or 0) or int(base.get(col, 0) or 0)) else 0
                after = {col: int(row.get(col, 0) or 0) for col, _, _ in ACTIONS}
                if after != before:
                    upgraded += 1
                    row["updated_at"] = now
                else:
                    normalized += 1

    new_rows = [rows_by_key[k] for k in sorted(rows_by_key.keys(), key=lambda k: (k[0], int(k[1]) if str(k[1]).isdigit() else 999))]
    tables["auth_users"] = list(by_user.values())
    tables["auth_account_permissions"] = new_rows
    payload["tables"] = tables
    payload["deleted_usernames"] = sorted(deleted)
    result = {"ok": True, "added": added, "upgraded": upgraded, "normalized": normalized, "users": len(by_user), "permissions": len(new_rows), "written": False}
    if write:
        wr = _v125_write_permission_payload(payload, reason)
        result["write_result"] = wr
        result["written"] = bool(wr.get("ok", True))
        try:
            _v96_best_effort_restore_cache(payload)  # type: ignore[name-defined]
        except Exception:
            pass
        try:
            clear_permission_runtime_cache()
        except Exception:
            pass
        if st is not None:
            try:
                for k in list(st.session_state.keys()):
                    if str(k).startswith(("_spt_perm_cache_", "_v132_perm_", "_v125_perm_")):
                        st.session_state.pop(k, None)
            except Exception:
                pass
    return result


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    # Always show a repaired matrix without relying on SQLite stale cache.
    reconcile_account_module_permissions_v125(reason="v125_get_permissions_repair", write=True)
    payload = _v125_permission_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    users = {str(u.get("username") or "").strip().lower(): dict(u) for u in tables.get("auth_users", []) if isinstance(u, dict) and str(u.get("username") or "").strip()}
    deleted = set()
    try:
        deleted = set(_v96_deleted(payload))  # type: ignore[name-defined]
    except Exception:
        pass
    out = []
    for r in tables.get("auth_account_permissions", []) if isinstance(tables.get("auth_account_permissions"), list) else []:
        if not isinstance(r, dict):
            continue
        uname = _v125_clean_username(r)
        if not uname or uname.lower() in deleted:
            continue
        user = users.get(uname.lower(), {})
        x = dict(r)
        x["username"] = uname
        x["display_name"] = user.get("display_name", x.get("display_name", ""))
        x["role_code"] = user.get("role_code", x.get("role_code", "operator"))
        x["module_code"] = _v125_normalize_module_no(x.get("module_code"))
        for col, _, _ in ACTIONS:
            x[col] = 1 if _v125_bool(x.get(col, False), False) else 0
        out.append(x)
    return sorted(out, key=lambda x: (str(x.get("username", "")).lower(), int(str(x.get("module_code") or "0") or 0)))


def save_users(rows: Iterable[dict]) -> dict:  # type: ignore[override]
    res = _v125_prev_save_users(rows) if callable(_v125_prev_save_users) else {"saved": 0, "skipped": []}
    try:
        rec = reconcile_account_module_permissions_v125(reason="v125_save_users_reconcile", write=True)
        if isinstance(res, dict):
            res["permission_reconcile"] = rec
    except Exception as exc:
        if isinstance(res, dict):
            res["permission_reconcile_error"] = str(exc)[:300]
    return res


def save_account_master(rows: Iterable[dict], delete_usernames: Iterable[str] | None = None) -> dict:  # type: ignore[override]
    res = _v125_prev_save_account_master(rows, delete_usernames=delete_usernames) if callable(_v125_prev_save_account_master) else save_users(rows)
    try:
        rec = reconcile_account_module_permissions_v125(reason="v125_save_account_master_reconcile", write=True)
        if isinstance(res, dict):
            res["permission_reconcile"] = rec
    except Exception as exc:
        if isinstance(res, dict):
            res["permission_reconcile_error"] = str(exc)[:300]
    return res


def save_account_permissions(rows: Iterable[dict]) -> int:  # type: ignore[override]
    # Merge edited rows into the full authority matrix. Never replace the full table with a filtered view.
    payload = _v125_permission_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    existing = [dict(r) for r in tables.get("auth_account_permissions", []) if isinstance(r, dict)]
    by_key: dict[tuple[str, str], dict] = {}
    for r in existing:
        uname = _v125_clean_username(r)
        module_no = _v125_normalize_module_no(r.get("module_code"))
        if uname and module_no:
            by_key[(uname.lower(), module_no)] = dict(r)
    count = 0
    now = _v125_now()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        uname = _v125_clean_username(r)
        module_no = _v125_normalize_module_no(r.get("module_code"))
        if not uname or not module_no:
            continue
        x = dict(by_key.get((uname.lower(), module_no), {}))
        x.update({"username": uname, "module_code": module_no, "updated_at": now})
        for m in MODULES:
            if str(m.get("module_code", "")).zfill(2) == module_no:
                x["module_name_zh"] = str(r.get("module_name_zh") or m.get("module_name_zh") or "")
                x["module_name_en"] = str(r.get("module_name_en") or m.get("module_name_en") or "")
                break
        for col, _, _ in ACTIONS:
            x[col] = 1 if _v125_bool(r.get(col, x.get(col, False)), False) else 0
        by_key[(uname.lower(), module_no)] = x
        count += 1
    tables["auth_account_permissions"] = [by_key[k] for k in sorted(by_key.keys(), key=lambda k: (k[0], int(k[1]) if str(k[1]).isdigit() else 999))]
    payload["tables"] = tables
    _v125_write_permission_payload(payload, "v125_save_account_permissions_merge")
    reconcile_account_module_permissions_v125(reason="v125_save_account_permissions_reconcile", write=True)
    return count

check_permission = has_permission
# ======================= END V125 ACCOUNT MASTER PERMISSION RECONCILIATION =======================


# ===================== V153B REGISTER MODULE 14 DATA HEALTH PERMISSIONS =====================
# 目的：將「14. 資料健康檢查中心」正式加入 10. 權限管理。
# 原則：不覆蓋既有 01~13 權限設定；只補上 14 模組列。
# 安全預設：只有 admin 角色預設全開；其他角色預設全關，必須由 10 權限管理明確勾選。

_V153B_MODULE_14 = {"module_code": "14", "module_name_zh": "資料健康檢查中心", "module_name_en": "Data Health Center"}

def _v153b_register_module_14_in_memory() -> None:
    try:
        global MODULES
        if not any(str(m.get("module_code", "")).zfill(2) == "14" for m in MODULES):
            MODULES.append(dict(_V153B_MODULE_14))
        else:
            for m in MODULES:
                if str(m.get("module_code", "")).zfill(2) == "14":
                    m["module_code"] = "14"
                    m["module_name_zh"] = _V153B_MODULE_14["module_name_zh"]
                    m["module_name_en"] = _V153B_MODULE_14["module_name_en"]
    except Exception:
        pass

_v153b_register_module_14_in_memory()

try:
    _v153b_prev_role_preset_for_module = _role_preset_for_module
except Exception:
    _v153b_prev_role_preset_for_module = None

def _role_preset_for_module(role: str, module_code: str) -> dict:  # type: ignore[override]
    module_no = str(module_code or "").zfill(2)
    if module_no == "14":
        base = {k: 0 for k, _, _ in ACTIONS}
        if str(role or "").strip().lower() == "admin":
            return {k: 1 for k in base}
        return base
    if callable(_v153b_prev_role_preset_for_module):
        return dict(_v153b_prev_role_preset_for_module(role, module_code))
    return dict(ROLE_PRESET.get(str(role or "operator").strip().lower(), ROLE_PRESET.get("operator", {})))

try:
    _v153b_prev_v96_role_preset = _v96_role_preset  # type: ignore[name-defined]
except Exception:
    _v153b_prev_v96_role_preset = None

def _v96_role_preset(role: str, module_code: str) -> dict:  # type: ignore[override]
    module_no = str(module_code or "").zfill(2)
    if module_no == "14":
        base = {k: 0 for k, _, _ in ACTIONS}
        if str(role or "").strip().lower() == "admin":
            return {k: 1 for k in base}
        return base
    if callable(_v153b_prev_v96_role_preset):
        return dict(_v153b_prev_v96_role_preset(role, module_code))
    return _role_preset_for_module(role, module_no)

try:
    _v153b_prev_v125_role_preset = _v125_role_preset  # type: ignore[name-defined]
except Exception:
    _v153b_prev_v125_role_preset = None

def _v125_role_preset(role: str, module_code: str) -> dict:  # type: ignore[override]
    module_no = str(module_code or "").zfill(2)
    if module_no == "14":
        base = {k: 0 for k, _, _ in ACTIONS}
        if str(role or "").strip().lower() == "admin":
            return {k: 1 for k in base}
        return base
    if callable(_v153b_prev_v125_role_preset):
        return dict(_v153b_prev_v125_role_preset(role, module_code))
    return _role_preset_for_module(role, module_no)


def ensure_module_14_permission_rows(reason: str = "v153b_register_module_14", *, write: bool = True) -> dict:
    """Ensure 14｜資料健康檢查中心 appears in 10 權限管理 authority matrix.

    This function is additive only. Existing rows and existing 01~13 permissions
    are preserved. If a user already has a 14 row, it is not overwritten.
    """
    _v153b_register_module_14_in_memory()
    result = {"ok": True, "added": 0, "users": 0, "written": False, "reason": reason}
    try:
        payload = _v125_permission_payload() if "_v125_permission_payload" in globals() else {}
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        users = [dict(u) for u in tables.get("auth_users", []) if isinstance(u, dict) and str(u.get("username") or "").strip()]
        existing = [dict(r) for r in tables.get("auth_account_permissions", []) if isinstance(r, dict)]
        by_key = {}
        for r in existing:
            uname = str(r.get("username") or "").strip()
            module_no = str(r.get("module_code") or "").zfill(2)
            if uname and module_no:
                by_key[(uname.lower(), module_no)] = r
        now = now_text()
        for u in users:
            uname = str(u.get("username") or "").strip()
            if not uname:
                continue
            result["users"] += 1
            key = (uname.lower(), "14")
            if key in by_key:
                # Only normalize names; do not change permissions.
                by_key[key]["module_name_zh"] = _V153B_MODULE_14["module_name_zh"]
                by_key[key]["module_name_en"] = _V153B_MODULE_14["module_name_en"]
                continue
            role = str(u.get("role_code") or u.get("role") or "operator").strip().lower() or "operator"
            preset = _v125_role_preset(role, "14")
            row = {
                "username": uname,
                "module_code": "14",
                "module_name_zh": _V153B_MODULE_14["module_name_zh"],
                "module_name_en": _V153B_MODULE_14["module_name_en"],
                "updated_at": now,
            }
            for col, _, _ in ACTIONS:
                row[col] = int(preset.get(col, 0) or 0)
            by_key[key] = row
            result["added"] += 1
        if result["added"] and write:
            tables["auth_account_permissions"] = [by_key[k] for k in sorted(by_key.keys(), key=lambda k: (k[0], int(k[1]) if str(k[1]).isdigit() else 999))]
            payload["tables"] = tables
            if "_v125_write_permission_payload" in globals():
                wr = _v125_write_permission_payload(payload, reason)
                result["write_result"] = wr
                result["written"] = True
            else:
                result["written"] = False
        try:
            clear_permission_runtime_cache()
        except Exception:
            pass
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)[:500]
    return result

try:
    _v153b_prev_get_account_permissions = get_account_permissions
except Exception:
    _v153b_prev_get_account_permissions = None

def get_account_permissions() -> List[dict]:  # type: ignore[override]
    # Make 14 visible in 10 權限管理 without changing any existing 01~13 rows.
    ensure_module_14_permission_rows(reason="v153b_get_account_permissions_register", write=True)
    if callable(_v153b_prev_get_account_permissions):
        return _v153b_prev_get_account_permissions()
    return []

# Register once on import, best effort. No existing permissions are changed.
try:
    ensure_module_14_permission_rows(reason="v153b_import_register", write=True)
except Exception:
    pass
# =================== END V153B REGISTER MODULE 14 DATA HEALTH PERMISSIONS ===================

# ===================== V156 PERMISSION READ CACHE =====================
# 目的：各頁面每次 rerun 都會檢查權限，V156 將帳號/模組權限/安全設定以
# 權威檔 mtime 作為 signature 快取。儲存、刪除、套用權限後立即清除。
try:
    import copy as _v156_perm_copy
    from pathlib import Path as _V156Path
except Exception:
    _v156_perm_copy = None
    _V156Path = None

_V156_PERMISSION_CACHE: dict[tuple, tuple[tuple, object]] = {}


def _v156_perm_sig() -> tuple:
    try:
        from services.permanent_authority_service import canonical_path as _pa_path
        paths = [_pa_path('10_permissions', 'records'), _pa_path('10_permissions', 'settings')]
        out = []
        for p in paths:
            try:
                stt = p.stat(); out.append((str(p), int(stt.st_mtime_ns), int(stt.st_size)))
            except Exception:
                out.append((str(p), 0, -1))
        return tuple(out)
    except Exception:
        return ('permission-no-sig',)


def _v156_perm_copy_value(value):
    try:
        return _v156_perm_copy.deepcopy(value) if _v156_perm_copy is not None else value
    except Exception:
        return value


def _v156_perm_get(key: tuple):
    sig = _v156_perm_sig()
    got = _V156_PERMISSION_CACHE.get(key)
    if got and got[0] == sig:
        return _v156_perm_copy_value(got[1])
    return None


def _v156_perm_set(key: tuple, value) -> None:
    try:
        _V156_PERMISSION_CACHE[key] = (_v156_perm_sig(), _v156_perm_copy_value(value))
    except Exception:
        pass


def clear_permission_read_cache() -> None:
    try:
        _V156_PERMISSION_CACHE.clear()
    except Exception:
        pass


_v156_prev_get_users = get_users
_v156_prev_get_account_permissions = get_account_permissions
_v156_prev_get_security_settings = get_security_settings
_v156_prev_save_users = save_users
_v156_prev_save_account_permissions = save_account_permissions
_v156_prev_save_security_settings = save_security_settings
try:
    _v156_prev_save_account_master = save_account_master
except Exception:
    _v156_prev_save_account_master = None
try:
    _v156_prev_delete_users = delete_users
except Exception:
    _v156_prev_delete_users = None


def get_users() -> List[dict]:  # type: ignore[override]
    cached = _v156_perm_get(('users',))
    if isinstance(cached, list):
        return cached
    val = _v156_prev_get_users()
    _v156_perm_set(('users',), val)
    return _v156_perm_copy_value(val)


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    cached = _v156_perm_get(('account_permissions',))
    if isinstance(cached, list):
        return cached
    val = _v156_prev_get_account_permissions()
    _v156_perm_set(('account_permissions',), val)
    return _v156_perm_copy_value(val)


def get_security_settings() -> Dict[str, str]:  # type: ignore[override]
    cached = _v156_perm_get(('security_settings',))
    if isinstance(cached, dict):
        return cached
    val = _v156_prev_get_security_settings()
    _v156_perm_set(('security_settings',), val)
    return _v156_perm_copy_value(val)


def save_users(rows: Iterable[dict]) -> dict:  # type: ignore[override]
    res = _v156_prev_save_users(rows)
    clear_permission_read_cache()
    return res


def save_account_permissions(rows: Iterable[dict]) -> int:  # type: ignore[override]
    res = _v156_prev_save_account_permissions(rows)
    clear_permission_read_cache()
    return res


def save_security_settings(settings: Dict[str, str]) -> None:  # type: ignore[override]
    res = _v156_prev_save_security_settings(settings)
    clear_permission_read_cache()
    return res


if callable(_v156_prev_save_account_master):
    def save_account_master(rows: Iterable[dict], delete_usernames: Iterable[str] | None = None) -> dict:  # type: ignore[override]
        res = _v156_prev_save_account_master(rows, delete_usernames=delete_usernames)
        clear_permission_read_cache()
        return res

if callable(_v156_prev_delete_users):
    def delete_users(usernames: Iterable[str]) -> int:  # type: ignore[override]
        res = _v156_prev_delete_users(usernames)
        clear_permission_read_cache()
        return res
# =================== END V156 PERMISSION READ CACHE ===================
