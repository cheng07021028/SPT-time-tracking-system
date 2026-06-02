# -*- coding: utf-8 -*-
"""Permission service backed by Neon/PostgreSQL single source of truth.

This file intentionally keeps the original UI/API names used by
pages/10_10. 權限管理.py and security_service.py, while moving all formal data
from local JSON/GitHub runtime files to the database tables:
  auth_users, auth_account_permissions, auth_security_settings,
  security_users, security_user_roles, security_settings, auth_login_logs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import hashlib
import hmac
import os

ACTIONS = [
    ("can_view", "可進入", "View"),
    ("can_create", "可新增", "Create"),
    ("can_edit", "可編輯", "Edit"),
    ("can_delete", "可刪除", "Delete"),
    ("can_import", "可匯入", "Import"),
    ("can_export", "可匯出", "Export"),
    ("can_backup", "可備份", "Backup"),
    ("can_restore", "可還原", "Restore"),
    ("can_manage", "可管理", "Manage"),
]
MODULES = [
    {"module_code":"01","module_name_zh":"工時紀錄","module_name_en":"Time Recording"},
    {"module_code":"02","module_name_zh":"歷史紀錄","module_name_en":"History"},
    {"module_code":"03","module_name_zh":"製令管理","module_name_en":"Work Orders"},
    {"module_code":"04","module_name_zh":"人員名單","module_name_en":"Employees"},
    {"module_code":"05","module_name_zh":"製令工時分析","module_name_en":"WO Time Analysis"},
    {"module_code":"06","module_name_zh":"LOG查詢","module_name_en":"Logs"},
    {"module_code":"07","module_name_zh":"今日未紀錄名單","module_name_en":"Missing Today"},
    {"module_code":"08","module_name_zh":"人員每日工時","module_name_en":"Daily Hours"},
    {"module_code":"09","module_name_zh":"資料永久保存與備份","module_name_en":"Backup"},
    {"module_code":"10","module_name_zh":"權限管理","module_name_en":"Permissions"},
    {"module_code":"11","module_name_zh":"登入紀錄","module_name_en":"Login Records"},
    {"module_code":"12","module_name_zh":"模組永久紀錄中心","module_name_en":"Persistence Center"},
    {"module_code":"13","module_name_zh":"系統設定","module_name_en":"System Settings"},
    {"module_code":"14","module_name_zh":"資料健康檢查中心","module_name_en":"Data Health"},
    {"module_code":"15","module_name_zh":"舊資料匯入到Neon","module_name_en":"Legacy Migration"},
    {"module_code":"98","module_name_zh":"權威檔診斷","module_name_en":"Authority Diagnostic"},
    {"module_code":"99","module_name_zh":"效能診斷","module_name_en":"Performance"},
]
ROLE_DESCRIPTIONS = {
    "admin": {"zh":"系統管理員", "en":"Administrator", "desc":"全部權限", "label":"系統管理員", "description":"全部權限"},
    "manager": {"zh":"主管", "en":"Manager", "desc":"管理與查詢", "label":"主管", "description":"管理與查詢"},
    "leader": {"zh":"現場幹部", "en":"Leader", "desc":"現場操作", "label":"現場幹部", "description":"現場操作"},
    "operator": {"zh":"作業人員", "en":"Operator", "desc":"工時操作", "label":"作業人員", "description":"工時操作"},
    "viewer": {"zh":"查詢者", "en":"Viewer", "desc":"只讀查詢", "label":"查詢者", "description":"只讀查詢"},
    "auditor": {"zh":"稽核", "en":"Auditor", "desc":"稽核查詢", "label":"稽核", "description":"稽核查詢"},
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    from services import db_service
    return db_service


def _ensure_schema() -> None:
    db = _db()
    db.ensure_database()
    # Extra compatibility columns. Additive only.
    try:
        if db.is_postgres_enabled():
            with db._v25_pg_connect() as conn:  # type: ignore[attr-defined]
                with conn.cursor() as cur:
                    for table in ("auth_users", "security_users"):
                        for col, ddl in (("deleted_at", "TEXT"), ("deleted_by", "TEXT"), ("delete_reason", "TEXT")):
                            try: cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
                            except Exception: pass
                    conn.commit()
        else:
            for table in ("auth_users", "security_users"):
                for col in ("deleted_at", "deleted_by", "delete_reason"):
                    try: db.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT", ())
                    except Exception: pass
    except Exception:
        pass


def _clean_username(v: Any) -> str:
    return str(v or "").strip()


def _norm_bool(v: Any, default: bool=True) -> int:
    if isinstance(v, bool): return 1 if v else 0
    t = str(v).strip().lower()
    if t in {"1","true","yes","y","啟用","是","active","on","checked"}: return 1
    if t in {"0","false","no","n","停用","否","inactive","off","unchecked"}: return 0
    return 1 if default else 0


def hash_password(password: str, salt: str|None=None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), str(salt).encode("utf-8"), 120000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    h = str(password_hash or "")
    try:
        if h.startswith("pbkdf2_sha256$"):
            _, salt, digest = h.split("$", 2)
            chk = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), 120000).hex()
            return hmac.compare_digest(chk, digest)
    except Exception:
        pass
    return False


def _module_no(code: Any) -> str:
    s = str(code or "").strip()
    mapping = {
        "01_time_record":"01","01_time_records":"01","02_history":"02","03_work_orders":"03","04_employees":"04",
        "05_analysis":"05","05_work_order_time_analysis":"05","06_logs":"06","06_log_query":"06","07_missing":"07",
        "07_missing_today":"07","08_daily_hours":"08","08_employee_daily_hours":"08","09_persistence":"09","09_backup_restore":"09",
        "10_permissions":"10","11_login_logs":"11","11_login_records":"11","12_module_persistence":"12","12_module_persistence_center":"12",
        "13_system_settings":"13","14_data_health":"14","15_legacy_migration":"15","98_authority_diagnostic":"98","99_speed_diagnostic":"99",
    }
    if s in mapping: return mapping[s]
    return s[:2] if len(s) >= 2 and s[:2].isdigit() else s


def _role_defaults(role: str, module: str) -> dict[str,int]:
    role = str(role or "operator").lower()
    module = _module_no(module)
    if role == "admin": return {a[0]: 1 for a in ACTIONS}
    if role == "viewer": return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_export":1}
    if role == "operator": return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_create":1, "can_edit":1}
    if role in {"manager","leader"}: return {**{a[0]:1 for a in ACTIONS}, "can_manage": 1 if role=="manager" else 0}
    if role == "auditor": return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_export":1}
    return {**{a[0]:0 for a in ACTIONS}, "can_view":1}


def _module_meta(code: str) -> dict[str, str]:
    code = _module_no(code)
    return next((m for m in MODULES if m["module_code"] == code), {"module_code": code, "module_name_zh": code, "module_name_en": code})


def _log(action: str, msg: str = "", target: str = "auth") -> None:
    try:
        _db().execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, 'SYSTEM', ?, ?, '', ?, '', 'INFO')",
            (now_text(), action, target, msg),
        )
    except Exception:
        pass


def _sync_legacy_security_user(username: str, row: dict[str, Any]) -> None:
    try:
        db = _db()
        db.execute(
            """
            INSERT INTO security_users(username, password_hash, employee_id, display_name, email, is_active, force_password_change, last_login_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                employee_id=EXCLUDED.employee_id,
                display_name=EXCLUDED.display_name,
                email=EXCLUDED.email,
                is_active=EXCLUDED.is_active,
                force_password_change=EXCLUDED.force_password_change,
                last_login_at=EXCLUDED.last_login_at,
                updated_at=EXCLUDED.updated_at
            """,
            (
                username, row.get("password_hash",""), row.get("employee_id",""), row.get("display_name", username), row.get("email",""),
                _norm_bool(row.get("is_active",1), True), _norm_bool(row.get("force_password_change",0), False), row.get("last_login_at",""), row.get("created_at") or now_text(), row.get("updated_at") or now_text(),
            ),
        )
        role = str(row.get("role_code") or "operator")
        db.execute(
            "INSERT INTO security_user_roles(username, role_code, created_at) VALUES (?, ?, ?) ON CONFLICT(username, role_code) DO NOTHING",
            (username, role, now_text()),
        )
    except Exception:
        pass


def _ensure_permissions_for_user(username: str, role: str) -> None:
    db = _db()
    for m in MODULES:
        code = m["module_code"]
        defaults = _role_defaults(role, code)
        db.execute(
            """
            INSERT INTO auth_account_permissions(username, module_code, module_name_zh, module_name_en,
                can_view, can_create, can_edit, can_delete, can_import, can_export, can_backup, can_restore, can_manage, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, module_code) DO NOTHING
            """,
            (username, code, m["module_name_zh"], m["module_name_en"], defaults["can_view"], defaults["can_create"], defaults["can_edit"], defaults["can_delete"], defaults["can_import"], defaults["can_export"], defaults["can_backup"], defaults["can_restore"], defaults["can_manage"], now_text()),
        )


def init_permission_tables(force: bool=False) -> dict:
    _ensure_schema()
    db = _db()
    row = db.query_one("SELECT COUNT(*) AS c FROM auth_users") or {}
    if force or int(row.get("c") or 0) == 0:
        admin_hash = hash_password("Admin@1234")
        db.execute(
            """
            INSERT INTO auth_users(username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active, force_password_change, note, created_at, updated_at)
            VALUES ('admin', ?, '', '', '系統管理員', '', 'admin', 1, 0, 'default admin', ?, ?)
            ON CONFLICT(username) DO NOTHING
            """,
            (admin_hash, now_text(), now_text()),
        )
    users = get_users()
    for u in users:
        username = str(u.get("username") or "")
        _sync_legacy_security_user(username, u)
        _ensure_permissions_for_user(username, str(u.get("role_code") or "operator"))
    _log("INIT_PERMISSION_TABLES", f"users={len(users)}")
    return {"ok": True, "backend": "neon" if db.is_postgres_enabled() else "sqlite"}


def restore_default_accounts_once_v57(): return {"ok": True, "skipped": True, "backend": "database"}
def restore_permission_settings_from_permanent_files(force: bool=False): return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL"}
def export_permission_settings_permanently(reason: str="manual"): return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL", "reason": reason}

def reconcile_permission_matrix_for_current_modules(force: bool=False):
    init_permission_tables(force=False)
    return {"ok": True, "authority": "Neon/PostgreSQL"}


def get_users() -> list[dict[str,Any]]:
    _ensure_schema()
    df = _db().query_df(
        """
        SELECT username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active,
               force_password_change, last_login_at, note, created_at, updated_at
        FROM auth_users
        WHERE COALESCE(deleted_at, '') = ''
        ORDER BY lower(username)
        """
    )
    if df is None or df.empty: return []
    out = []
    for r in df.to_dict("records"):
        row = dict(r)
        row["password_display"] = "********" if row.get("password_hash") else ""
        row.setdefault("new_password", "")
        out.append(row)
    return out


def save_users(rows: list[dict[str,Any]]) -> dict:
    _ensure_schema()
    db = _db()
    saved = 0
    skipped: list[str] = []
    for src in rows or []:
        username = _clean_username(src.get("username") or src.get("帳號 / Username"))
        if not username:
            continue
        old = db.query_one("SELECT * FROM auth_users WHERE lower(username)=lower(?)", (username,)) or {}
        new_pwd = str(src.get("new_password") or src.get("password") or src.get("密碼 / Password") or src.get("新密碼 / New Password") or "").strip()
        if new_pwd and set(new_pwd) != {"*"}:
            password_hash = hash_password(new_pwd)
        else:
            password_hash = str(old.get("password_hash") or "") or hash_password("Admin@1234" if username.lower()=="admin" else username)
        row = {
            "username": username,
            "password_hash": password_hash,
            "password_hint": str(src.get("password_hint") or old.get("password_hint") or ""),
            "employee_id": str(src.get("employee_id") or src.get("工號 / Employee ID") or old.get("employee_id") or ""),
            "display_name": str(src.get("display_name") or src.get("姓名 / Display Name") or old.get("display_name") or username),
            "email": str(src.get("email") or src.get("Email") or old.get("email") or ""),
            "role_code": str(src.get("role_code") or src.get("角色 / Role") or old.get("role_code") or "operator"),
            "is_active": _norm_bool(src.get("is_active", src.get("啟用 / Active", old.get("is_active", 1))), True),
            "force_password_change": _norm_bool(src.get("force_password_change", src.get("強制改密碼 / Force Change", old.get("force_password_change", 0))), False),
            "last_login_at": str(old.get("last_login_at") or ""),
            "note": str(src.get("note") or src.get("備註 / Note") or old.get("note") or ""),
            "created_at": str(old.get("created_at") or now_text()),
            "updated_at": now_text(),
        }
        db.execute(
            """
            INSERT INTO auth_users(username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active,
                force_password_change, last_login_at, note, created_at, updated_at, deleted_at, deleted_by, delete_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '')
            ON CONFLICT(username) DO UPDATE SET
                password_hash=EXCLUDED.password_hash,
                password_hint=EXCLUDED.password_hint,
                employee_id=EXCLUDED.employee_id,
                display_name=EXCLUDED.display_name,
                email=EXCLUDED.email,
                role_code=EXCLUDED.role_code,
                is_active=EXCLUDED.is_active,
                force_password_change=EXCLUDED.force_password_change,
                note=EXCLUDED.note,
                updated_at=EXCLUDED.updated_at,
                deleted_at='', deleted_by='', delete_reason=''
            """,
            tuple(row[k] for k in ["username","password_hash","password_hint","employee_id","display_name","email","role_code","is_active","force_password_change","last_login_at","note","created_at","updated_at"]),
        )
        _sync_legacy_security_user(username, row)
        _ensure_permissions_for_user(username, row["role_code"])
        saved += 1
    _log("SAVE_USERS", f"saved={saved}")
    return {"ok": True, "saved": saved, "skipped": skipped, "backend": "Neon/PostgreSQL"}


def save_account_master(rows: list[dict[str,Any]], delete_usernames: list[str]|None=None) -> dict:
    res = save_users(rows or [])
    deleted = delete_users(delete_usernames or []) if delete_usernames else 0
    res["deleted"] = deleted
    return res


def delete_users(usernames: list[str]) -> int:
    _ensure_schema()
    db = _db()
    deleted = 0
    for raw in usernames or []:
        username = _clean_username(raw)
        if not username or username.lower() == "admin":
            continue
        db.execute("DELETE FROM auth_account_permissions WHERE lower(username)=lower(?)", (username,))
        db.execute("DELETE FROM security_user_roles WHERE lower(username)=lower(?)", (username,))
        db.execute("UPDATE auth_users SET deleted_at=?, deleted_by='admin', delete_reason='delete_users', is_active=0, updated_at=? WHERE lower(username)=lower(?)", (now_text(), now_text(), username))
        db.execute("UPDATE security_users SET deleted_at=?, deleted_by='admin', delete_reason='delete_users', is_active=0, updated_at=? WHERE lower(username)=lower(?)", (now_text(), now_text(), username))
        deleted += 1
    _log("DELETE_USERS", f"deleted={deleted}")
    return deleted


def get_account_permissions() -> list[dict[str,Any]]:
    _ensure_schema()
    for u in get_users():
        _ensure_permissions_for_user(str(u.get("username") or ""), str(u.get("role_code") or "operator"))
    df = _db().query_df(
        """
        SELECT p.username, COALESCE(u.display_name, p.username) AS display_name, COALESCE(u.role_code, '') AS role_code,
               p.module_code, p.module_name_zh, p.module_name_en,
               p.can_view, p.can_create, p.can_edit, p.can_delete, p.can_import, p.can_export, p.can_backup, p.can_restore, p.can_manage,
               p.updated_at
        FROM auth_account_permissions p
        LEFT JOIN auth_users u ON u.username = p.username
        WHERE COALESCE(u.deleted_at, '') = '' OR u.username IS NULL
        ORDER BY lower(p.username), p.module_code
        """
    )
    return df.to_dict("records") if df is not None and not df.empty else []


def save_account_permissions(rows: list[dict[str,Any]]) -> dict:
    _ensure_schema()
    db = _db()
    saved = 0
    for src in rows or []:
        username = _clean_username(src.get("username") or src.get("帳號 / Username"))
        code = _module_no(src.get("module_code") or src.get("模組代碼 / Module") or src.get("Module") or src.get("module"))
        if not username or not code:
            continue
        meta = _module_meta(code)
        vals = {a[0]: _norm_bool(src.get(a[0], src.get(a[0].replace("can_", ""), 0)), False) for a in ACTIONS}
        db.execute(
            """
            INSERT INTO auth_account_permissions(username, module_code, module_name_zh, module_name_en,
                can_view, can_create, can_edit, can_delete, can_import, can_export, can_backup, can_restore, can_manage, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, module_code) DO UPDATE SET
                module_name_zh=EXCLUDED.module_name_zh,
                module_name_en=EXCLUDED.module_name_en,
                can_view=EXCLUDED.can_view,
                can_create=EXCLUDED.can_create,
                can_edit=EXCLUDED.can_edit,
                can_delete=EXCLUDED.can_delete,
                can_import=EXCLUDED.can_import,
                can_export=EXCLUDED.can_export,
                can_backup=EXCLUDED.can_backup,
                can_restore=EXCLUDED.can_restore,
                can_manage=EXCLUDED.can_manage,
                updated_at=EXCLUDED.updated_at
            """,
            (username, code, meta["module_name_zh"], meta["module_name_en"], vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text()),
        )
        saved += 1
    _log("SAVE_ACCOUNT_PERMISSIONS", f"saved={saved}")
    return {"ok": True, "saved": saved, "backend": "Neon/PostgreSQL"}


def has_permission(username: str, module_code: str, action: str="can_view") -> bool:
    uname = _clean_username(username)
    code = _module_no(module_code)
    act = str(action or "can_view")
    if uname.lower() == "admin": return True
    _ensure_schema()
    user = _db().query_one("SELECT * FROM auth_users WHERE lower(username)=lower(?) AND COALESCE(deleted_at,'')=''", (uname,))
    if not user or not _norm_bool(user.get("is_active", 1), True): return False
    row = _db().query_one("SELECT * FROM auth_account_permissions WHERE lower(username)=lower(?) AND module_code=?", (uname, code))
    if row and act in row:
        return bool(_norm_bool(row.get(act), False))
    return bool(_role_defaults(str(user.get("role_code") or "operator"), code).get(act, 0))


def get_security_settings() -> dict[str,Any]:
    _ensure_schema()
    df = _db().query_df("SELECT setting_key, setting_value FROM auth_security_settings")
    out: dict[str, Any] = {}
    if df is not None and not df.empty:
        for r in df.to_dict("records"):
            out[str(r.get("setting_key"))] = r.get("setting_value")
    out.setdefault("idle_timeout_minutes", out.get("idle_auto_logout_minutes", 15))
    out.setdefault("idle_auto_logout_minutes", out.get("idle_timeout_minutes", 15))
    out.setdefault("ask_continue_after_record", 1)
    return out


def save_security_settings(settings: dict[str,Any]) -> dict:
    _ensure_schema()
    cur = get_security_settings(); cur.update(settings or {})
    minutes = cur.get("idle_timeout_minutes", cur.get("idle_auto_logout_minutes", 15))
    try: cur["idle_timeout_minutes"] = int(float(minutes or 15))
    except Exception: cur["idle_timeout_minutes"] = 15
    cur["idle_auto_logout_minutes"] = cur["idle_timeout_minutes"]
    db = _db()
    saved = 0
    for k, v in cur.items():
        db.execute(
            """
            INSERT INTO auth_security_settings(setting_key, setting_value, note, updated_at)
            VALUES (?, ?, '', ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value, updated_at=EXCLUDED.updated_at
            """,
            (str(k), str(v), now_text()),
        )
        try:
            db.execute(
                """
                INSERT INTO security_settings(setting_key, setting_value, note, updated_at)
                VALUES (?, ?, '', ?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value, updated_at=EXCLUDED.updated_at
                """,
                (str(k), str(v), now_text()),
            )
        except Exception:
            pass
        saved += 1
    _log("SAVE_SECURITY_SETTINGS", f"saved={saved}")
    return {"ok": True, "saved": saved, "backend": "Neon/PostgreSQL"}


def add_login_log(username: str, event_type: str, result: str, message: str="", module_code: str="", module_name: str="") -> None:
    _ensure_schema()
    try:
        _db().execute(
            "INSERT INTO auth_login_logs(username, display_name, event_time, event_type, result, module_code, module_name, message, ip_address, user_agent) VALUES (?, '', ?, ?, ?, ?, ?, ?, '', '')",
            (username, now_text(), event_type, result, module_code, module_name, message),
        )
    except Exception:
        pass


def get_login_logs(start_date: str|None=None, end_date: str|None=None) -> list[dict[str,Any]]:
    _ensure_schema()
    where = ["COALESCE(deleted_at,'')=''"]
    params: list[Any] = []
    if start_date:
        where.append("substr(COALESCE(event_time, ''),1,10) >= ?"); params.append(start_date)
    if end_date:
        where.append("substr(COALESCE(event_time, ''),1,10) <= ?"); params.append(end_date)
    sql = "SELECT * FROM auth_login_logs WHERE " + " AND ".join(where) + " ORDER BY id DESC"
    df = _db().query_df(sql, tuple(params))
    return df.to_dict("records") if df is not None and not df.empty else []


def delete_login_logs(start_date: str, end_date: str) -> int:
    _ensure_schema()
    before = len(get_login_logs(start_date, end_date))
    _db().execute(
        "UPDATE auth_login_logs SET deleted_at=?, deleted_by='admin', delete_reason='clear_login_logs' WHERE substr(COALESCE(event_time,''),1,10) >= ? AND substr(COALESCE(event_time,''),1,10) <= ? AND COALESCE(deleted_at,'')=''",
        (now_text(), start_date, end_date),
    )
    return before


def connect_db():
    # Compatibility only. New authority is db_service/Neon.
    return _db().get_connection()

def clear_permission_runtime_cache(): return None
def sync_auth_users_to_runtime_security(usernames=None):
    for u in get_users():
        if usernames and str(u.get("username")) not in set(map(str, usernames)): continue
        _sync_legacy_security_user(str(u.get("username")), u)
    return {"ok": True, "backend": "Neon/PostgreSQL"}
def permission_recovery_diagnostic(): return {"ok": True, "authority": "Neon/PostgreSQL", "users": len(get_users())}
def permission_password_emergency_recovery(): return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL"}
def force_restore_admin_password_v30017_4():
    return save_users([{"username":"admin","new_password":"Admin@1234","display_name":"系統管理員","role_code":"admin","is_active":1}])
