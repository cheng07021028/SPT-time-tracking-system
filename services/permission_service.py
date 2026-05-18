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
            from services.persistence_guard_service import safe_load_json
            data = safe_load_json(path, {}, allow_default_when_missing=True)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        if path.exists():
            raise RuntimeError(f"Permission persistent JSON read failed; default reset blocked: {path} | {exc}") from exc
    return {}


def _spt_safe_write_json(path: Path, payload: Any) -> None:
    try:
        from services.persistence_guard_service import atomic_save_json
        atomic_save_json(path, payload, backup_existing=True)
    except Exception:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(path)


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
    # Include external backups configured in 13｜系統設定. Without this,
    # permission restore may say no backup exists even when external backups exist.
    try:
        from services.persistence_guard_service import list_all_persistent_backups
        for backup in list_all_persistent_backups(include_external=True):
            for rel in [
                "data/persistent_state/spt_module_settings.json",
                "data/persistent_state/spt_permanent_state.json",
                "data/persistent_modules/10_permissions/10_permissions_settings.json",
                "data/persistent_modules/10_permissions/10_permissions_records.json",
                "data/persistent_state/spt_security_settings.json",
            ]:
                p = backup / rel
                if p.exists() and p.stat().st_size > 0:
                    candidates.append(p)
    except Exception:
        pass
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

    # V1.78: after schema/default seed, immediately restore account master,
    # account permissions and security settings from permanent JSON files.
    # This prevents GitHub/Streamlit rebuilds from reverting settings to defaults.
    try:
        restore_permission_settings_from_permanent_files(force=False)
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
                display_name, str(r.get("email", "")).strip(), role_code, int(bool(r.get("is_active", True))),
                int(bool(r.get("force_password_change", False))), str(r.get("note", "")).strip(), now_text(), now_text()
            ))
            role_sync_users.append(username)
        saved += 1
        saved_usernames.append(username)
    conn.commit()
    conn.close()

    # V2.93：帳號清單編輯是角色唯一來源。
    # 即使角色文字看似沒有變，也可能已存在舊權限矩陣/舊 runtime 角色殘留，
    # 所以儲存的帳號一律重建權限與 runtime 角色，不再只處理 role_sync_users。
    ensure_permissions_for_all_users(force=True)
    synced_permissions = 0
    if saved_usernames:
        synced_permissions = sync_user_permissions_from_roles(saved_usernames, reason="account_master_saved_authoritative")
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
    init_permission_tables()
    usernames = [u for u in usernames if u and u != "admin"]
    if not usernames:
        return 0
    conn = connect_db()
    cur = conn.cursor()
    for u in usernames:
        cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (u,))
        cur.execute("DELETE FROM auth_users WHERE username=?", (u,))
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
        _spt_safe_write_json(state_dir / "spt_security_settings.json", payload)
        _spt_safe_write_json(mod_dir / "10_permissions_settings.json", payload)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _spt_safe_write_json(hist_dir / f"10_permissions_settings_{stamp}.json", payload)
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
            payload = _json_load(path)
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
            payload = _json_load(path)
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
            _spt_safe_write_json(path, payload)
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
            _spt_safe_write_json(path, payload)
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


# ===== V2.92 ACCOUNT MASTER AUTHORITATIVE PERMISSION SYNC START =====
def _v292_clean_usernames(usernames: Iterable[str] | None = None) -> list[str]:
    try:
        if usernames is None:
            conn = connect_db()
            rows = conn.execute("SELECT username FROM auth_users ORDER BY username").fetchall()
            conn.close()
            return [str(r["username"]).strip() for r in rows if str(r["username"]).strip()]
        return sorted({str(u or "").strip() for u in usernames if str(u or "").strip()})
    except Exception:
        return []


def _v292_clear_all_permission_caches() -> None:
    clear_permission_runtime_cache()
    if st is None:
        return
    try:
        for k in list(st.session_state.keys()):
            if (
                k.startswith("_v132_perm_")
                or k.startswith("_spt_perm_cache_")
                or k in {"auth_roles", "role", "roles"}
            ):
                st.session_state.pop(k, None)
    except Exception:
        pass


def sync_user_permissions_from_roles(usernames: Iterable[str], reason: str = "role_changed") -> int:  # type: ignore[override]
    """V2.92 authoritative role -> Account Module Permissions sync.

    Account Master is the single source of role.  When a user's role is saved,
    remove that user's old module-permission rows and rebuild them from the
    current auth_users.role_code.  This prevents the old mixed state such as
    login bar showing "admin, operator" while Account Master says "operator".
    """
    init_permission_tables()
    target_users = _v292_clean_usernames(usernames)
    if not target_users:
        return 0
    conn = connect_db()
    cur = conn.cursor()
    updated = 0
    _ensure_legacy_security_tables(cur)
    for username in target_users:
        u = cur.execute("SELECT username, role_code FROM auth_users WHERE username=?", (username,)).fetchone()
        if not u:
            cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (username,))
            cur.execute("DELETE FROM security_user_roles WHERE username=?", (username,))
            continue
        role = str(u["role_code"] or "operator").strip() or "operator"
        # Remove stale module rows first so the matrix cannot keep old-role residue.
        cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (username,))
        cur.execute("DELETE FROM security_user_roles WHERE username=?", (username,))
        cur.execute("INSERT OR IGNORE INTO security_user_roles(username, role_code, created_at) VALUES (?,?,?)", (username, role, now_text()))
        for m in MODULES:
            preset = _role_preset_for_module(role, m["module_code"])
            cur.execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                username, m["module_code"], m["module_name_zh"], m["module_name_en"],
                preset["can_view"], preset["can_create"], preset["can_edit"], preset["can_delete"],
                preset["can_import"], preset["can_export"], preset["can_backup"], preset["can_restore"], preset["can_manage"], now_text()
            ))
            updated += 1
    conn.commit()
    conn.close()
    _v292_clear_all_permission_caches()
    return updated


def reconcile_account_master_permissions_authoritative(usernames: Iterable[str] | None = None, reason: str = "account_master_authoritative") -> int:
    """Public helper used by 10｜權限管理 after Account Master save."""
    target = _v292_clean_usernames(usernames)
    if not target:
        return 0
    return sync_user_permissions_from_roles(target, reason=reason)


def sync_auth_users_to_runtime_security(usernames: Iterable[str] | None = None) -> int:  # type: ignore[override]
    """V2.92 runtime login-role sync with stale-role cleanup."""
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    _ensure_legacy_security_tables(cur)
    target = _v292_clean_usernames(usernames)
    params: list[str] = []
    where = ""
    if target:
        where = " WHERE username IN ({})".format(",".join(["?"] * len(target)))
        params = target
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
        role = str(r["role_code"] or "operator").strip() or "operator"
        cur.execute("DELETE FROM security_user_roles WHERE username=?", (username,))
        cur.execute("INSERT INTO security_user_roles(username, role_code, created_at) VALUES (?,?,?)", (username, role, now_text()))
        count += 1
    conn.commit()
    conn.close()
    _v292_clear_all_permission_caches()
    return count


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    """Always display permission matrix role from Account Master, never stale rows."""
    reconcile_permission_matrix_for_current_modules(force=False)
    import time
    cache = _cache_get("_v132_perm_matrix_cache")
    if cache and time.time() - float(cache.get("ts", 0)) < _PERMISSION_CACHE_TTL_SECONDS:
        return cache.get("data", [])
    conn = connect_db()
    rows = conn.execute("""
        SELECT p.username,
               COALESCE(u.display_name, p.username) AS display_name,
               COALESCE(u.role_code, 'operator') AS role_code,
               p.module_code, p.module_name_zh, p.module_name_en,
               p.can_view, p.can_create, p.can_edit, p.can_delete, p.can_import, p.can_export,
               p.can_backup, p.can_restore, p.can_manage, p.updated_at
        FROM auth_account_permissions p
        INNER JOIN auth_users u ON u.username = p.username
        ORDER BY p.username, CAST(p.module_code AS INTEGER)
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    _cache_set("_v132_perm_matrix_cache", {"ts": time.time(), "data": data})
    return data
# ===== V2.92 ACCOUNT MASTER AUTHORITATIVE PERMISSION SYNC END =====


# ===== V2.93 AUTHORITATIVE ACCOUNT ROLE CLEANUP START =====
def _v293_clear_all_permission_caches() -> None:
    try:
        clear_permission_runtime_cache()
    except Exception:
        pass
    if st is None:
        return
    try:
        for k in list(st.session_state.keys()):
            if (
                k.startswith("_v132_perm_")
                or k.startswith("_spt_perm_cache_")
                or k.startswith("v235_permission_editor_")
                or k in {"auth_roles", "role", "roles"}
            ):
                st.session_state.pop(k, None)
    except Exception:
        pass


def _v293_clean_usernames(usernames: Iterable[str] | None = None) -> list[str]:
    try:
        if usernames is None:
            conn = connect_db()
            rows = conn.execute("SELECT username FROM auth_users ORDER BY username").fetchall()
            conn.close()
            return [str(r["username"]).strip() for r in rows if str(r["username"]).strip()]
        return sorted({str(u or "").strip() for u in usernames if str(u or "").strip()})
    except Exception:
        return []


def sync_user_permissions_from_roles(usernames: Iterable[str], reason: str = "role_changed") -> int:  # type: ignore[override]
    """V2.93 Account Master is the only role source.

    For every target username, remove old module-permission rows and old runtime
    role rows, then rebuild from auth_users.role_code. This removes stale states
    like admin/operator being shown together after Account Master says operator.
    """
    init_permission_tables()
    target_users = _v293_clean_usernames(usernames)
    if not target_users:
        return 0
    conn = connect_db()
    cur = conn.cursor()
    updated = 0
    try:
        _ensure_legacy_security_tables(cur)
    except Exception:
        pass
    for username in target_users:
        u = cur.execute("SELECT username, role_code FROM auth_users WHERE username=?", (username,)).fetchone()
        cur.execute("DELETE FROM auth_account_permissions WHERE username=?", (username,))
        try:
            cur.execute("DELETE FROM security_user_roles WHERE username=?", (username,))
        except Exception:
            pass
        if not u:
            continue
        role = str(u["role_code"] or "operator").strip() or "operator"
        try:
            cur.execute("INSERT INTO security_user_roles(username, role_code, created_at) VALUES (?,?,?)", (username, role, now_text()))
        except Exception:
            pass
        for m in MODULES:
            preset = _role_preset_for_module(role, m["module_code"])
            cur.execute("""
                INSERT INTO auth_account_permissions
                (username,module_code,module_name_zh,module_name_en,can_view,can_create,can_edit,can_delete,can_import,can_export,can_backup,can_restore,can_manage,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                username, m["module_code"], m["module_name_zh"], m["module_name_en"],
                preset["can_view"], preset["can_create"], preset["can_edit"], preset["can_delete"],
                preset["can_import"], preset["can_export"], preset["can_backup"], preset["can_restore"], preset["can_manage"], now_text()
            ))
            updated += 1
    conn.commit()
    conn.close()
    _v293_clear_all_permission_caches()
    return updated


def reconcile_account_master_permissions_authoritative(usernames: Iterable[str] | None = None, reason: str = "account_master_authoritative") -> int:  # type: ignore[override]
    target = _v293_clean_usernames(usernames)
    if not target:
        return 0
    return sync_user_permissions_from_roles(target, reason=reason)


def sync_auth_users_to_runtime_security(usernames: Iterable[str] | None = None) -> int:  # type: ignore[override]
    """V2.93 runtime login table follows auth_users exactly; no role append residue."""
    init_permission_tables()
    conn = connect_db()
    cur = conn.cursor()
    try:
        _ensure_legacy_security_tables(cur)
    except Exception:
        pass
    target = _v293_clean_usernames(usernames)
    params: list[str] = []
    where = ""
    if target:
        where = " WHERE username IN ({})".format(",".join(["?"] * len(target)))
        params = target
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
        role = str(r["role_code"] or "operator").strip() or "operator"
        try:
            cur.execute("DELETE FROM security_user_roles WHERE username=?", (username,))
            cur.execute("INSERT INTO security_user_roles(username, role_code, created_at) VALUES (?,?,?)", (username, role, now_text()))
        except Exception:
            pass
        count += 1
    conn.commit()
    conn.close()
    _v293_clear_all_permission_caches()
    return count


def get_account_permissions() -> List[dict]:  # type: ignore[override]
    """Permission matrix display always joins role from Account Master."""
    init_permission_tables()
    try:
        reconcile_permission_matrix_for_current_modules(force=False)
    except Exception:
        pass
    import time
    cache = _cache_get("_v132_perm_matrix_cache")
    if cache and time.time() - float(cache.get("ts", 0)) < _PERMISSION_CACHE_TTL_SECONDS:
        return cache.get("data", [])
    conn = connect_db()
    rows = conn.execute("""
        SELECT p.username,
               COALESCE(u.display_name, p.username) AS display_name,
               COALESCE(u.role_code, 'operator') AS role_code,
               p.module_code, p.module_name_zh, p.module_name_en,
               p.can_view, p.can_create, p.can_edit, p.can_delete, p.can_import, p.can_export,
               p.can_backup, p.can_restore, p.can_manage, p.updated_at
        FROM auth_account_permissions p
        INNER JOIN auth_users u ON u.username = p.username
        ORDER BY p.username, CAST(p.module_code AS INTEGER)
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    _cache_set("_v132_perm_matrix_cache", {"ts": time.time(), "data": data})
    return data
# ===== V2.93 AUTHORITATIVE ACCOUNT ROLE CLEANUP END =====
