# -*- coding: utf-8 -*-
"""V33 fast Neon permission service.

Keeps the old page API used by pages/10_10. 權限管理.py, but removes the
expensive page-entry reconciliation that made 10 and other modules spin.
Formal authority remains Neon/PostgreSQL through services.db_service.
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
ACTION_COLS = [a[0] for a in ACTIONS]
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

_SCHEMA_READY = False
_MATRIX_CACHE: dict[str, Any] = {"users_ts": 0.0, "users": None, "perms_ts": 0.0, "perms": None, "security_ts": 0.0, "security": None}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    from services import db_service
    return db_service


def _module_no(code: Any) -> str:
    s = str(code or "").strip()
    mapping = {
        "01_time_record":"01","01_time_records":"01","02_history":"02","03_work_orders":"03","04_employees":"04",
        "05_analysis":"05","05_work_order_time_analysis":"05","06_logs":"06","06_log_query":"06","07_missing":"07",
        "07_missing_today":"07","08_daily_hours":"08","08_employee_daily_hours":"08","09_persistence":"09","09_backup_restore":"09",
        "10_permissions":"10","11_login_logs":"11","11_login_records":"11","12_module_persistence":"12","12_module_persistence_center":"12",
        "13_system_settings":"13","14_data_health":"14","15_legacy_migration":"15","98_authority_diagnostic":"98","99_speed_diagnostic":"99",
    }
    if s in mapping:
        return mapping[s]
    return s[:2] if len(s) >= 2 and s[:2].isdigit() else s


def _module_meta(code: str) -> dict[str, str]:
    code = _module_no(code)
    return next((m for m in MODULES if m["module_code"] == code), {"module_code": code, "module_name_zh": code, "module_name_en": code})


def _norm_bool(v: Any, default: bool=True) -> int:
    if isinstance(v, bool):
        return 1 if v else 0
    if v is None:
        return 1 if default else 0
    t = str(v).strip().lower()
    if t in {"1","true","yes","y","啟用","是","active","on","checked","勾選"}:
        return 1
    if t in {"0","false","no","n","停用","否","inactive","off","unchecked","取消"}:
        return 0
    return 1 if default else 0


def hash_password(password: str, salt: str|None=None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), str(salt).encode("utf-8"), 120000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    h = str(password_hash or "")
    try:
        if h.startswith("pbkdf2_sha256$"):
            parts = h.split("$")
            if len(parts) == 3:
                _, salt, digest = parts
                chk = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), 120000).hex()
                return hmac.compare_digest(chk, digest)
    except Exception:
        pass
    return False


def _role_defaults(role: str, module: str) -> dict[str,int]:
    role = str(role or "operator").lower()
    module = _module_no(module)
    if role == "admin":
        return {a[0]: 1 for a in ACTIONS}
    if role == "viewer":
        return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_export":1}
    if role == "operator":
        return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_create":1, "can_edit":1}
    if role in {"manager","leader"}:
        return {**{a[0]:1 for a in ACTIONS}, "can_manage": 1 if role=="manager" else 0}
    if role == "auditor":
        return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_export":1}
    return {**{a[0]:0 for a in ACTIONS}, "can_view":1}


def _clear_cache() -> None:
    _MATRIX_CACHE.update({"users_ts": 0.0, "users": None, "perms_ts": 0.0, "perms": None, "security_ts": 0.0, "security": None})
    try:
        _db().clear_query_cache()
    except Exception:
        pass


def _log(action: str, msg: str = "", target: str = "auth") -> None:
    try:
        _db().execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, 'SYSTEM', ?, ?, '', ?, '', 'INFO')",
            (now_text(), action, target, str(msg)[:1000]),
        )
    except Exception:
        pass


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    db = _db()
    db.ensure_database()
    # Only lightweight additive auth schema. No matrix rebuild here.
    statements = [
        """CREATE TABLE IF NOT EXISTS auth_users (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY,
            username TEXT,
            password_hash TEXT,
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
            updated_at TEXT,
            deleted_at TEXT,
            deleted_by TEXT,
            delete_reason TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS auth_account_permissions (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY,
            username TEXT,
            module_code TEXT,
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
            updated_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS auth_security_settings (
            setting_key TEXT,
            setting_value TEXT,
            note TEXT,
            updated_at TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_v33_perm_users_username ON auth_users(lower(username))",
        "CREATE INDEX IF NOT EXISTS idx_v33_perm_matrix_user_module ON auth_account_permissions(lower(username), module_code)",
        "CREATE INDEX IF NOT EXISTS idx_v33_perm_settings_key ON auth_security_settings(setting_key)",
    ]
    for sql in statements:
        try:
            db.execute(sql, ())
        except Exception:
            pass
    # Seed admin only if account table is empty/missing admin.
    try:
        row = db.query_one("SELECT username FROM auth_users WHERE lower(username)=lower(?) AND COALESCE(deleted_at,'')='' LIMIT 1", ("admin",))
        if not row:
            db.execute(
                """
                INSERT INTO auth_users(username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active, force_password_change, note, created_at, updated_at, deleted_at, deleted_by, delete_reason)
                VALUES (?, ?, '', '', '系統管理員', '', 'admin', 1, 0, 'default admin', ?, ?, '', '', '')
                """,
                ("admin", hash_password("Admin@1234"), now_text(), now_text()),
            )
    except Exception:
        pass
    _SCHEMA_READY = True


def init_permission_tables(force: bool=False) -> dict:
    _ensure_schema()
    # V33: no per-page all-user/all-module rebuild. Missing matrix rows are generated in memory.
    return {"ok": True, "backend": "Neon/PostgreSQL", "fastpath": True}


def restore_default_accounts_once_v57():
    return {"ok": True, "skipped": True, "backend": "Neon/PostgreSQL"}

def restore_permission_settings_from_permanent_files(force: bool=False):
    return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL"}

def export_permission_settings_permanently(reason: str="manual"):
    return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL", "reason": reason}

def reconcile_permission_matrix_for_current_modules(force: bool=False):
    _ensure_schema()
    return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL", "fastpath": True}


def get_users() -> list[dict[str,Any]]:
    _ensure_schema()
    import time
    now_ts = time.time()
    cached = _MATRIX_CACHE.get("users")
    if cached is not None and now_ts - float(_MATRIX_CACHE.get("users_ts") or 0) < 300:
        return [dict(r) for r in cached]
    df = _db().query_df(
        """
        SELECT username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active,
               force_password_change, last_login_at, note, created_at, updated_at
        FROM auth_users
        WHERE COALESCE(deleted_at, '') = ''
        ORDER BY lower(username)
        """
    )
    if df is None or df.empty:
        rows: list[dict[str, Any]] = []
    else:
        rows = []
        for r in df.to_dict("records"):
            row = dict(r)
            row["password_display"] = "********" if row.get("password_hash") else ""
            row.setdefault("new_password", "")
            rows.append(row)
    _MATRIX_CACHE["users"] = [dict(r) for r in rows]
    _MATRIX_CACHE["users_ts"] = now_ts
    return rows


def _insert_or_update_auth_user(row: dict[str, Any]) -> None:
    db = _db()
    username = str(row.get("username") or "").strip()
    if not username:
        return
    updated = db.execute(
        """
        UPDATE auth_users SET
            password_hash=?, password_hint=?, employee_id=?, display_name=?, email=?, role_code=?, is_active=?,
            force_password_change=?, note=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
        WHERE lower(username)=lower(?)
        """,
        (row["password_hash"], row["password_hint"], row["employee_id"], row["display_name"], row["email"], row["role_code"], row["is_active"], row["force_password_change"], row["note"], row["updated_at"], username),
    )
    if int(updated or 0) <= 0:
        db.execute(
            """
            INSERT INTO auth_users(username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active,
                force_password_change, last_login_at, note, created_at, updated_at, deleted_at, deleted_by, delete_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '')
            """,
            (username, row["password_hash"], row["password_hint"], row["employee_id"], row["display_name"], row["email"], row["role_code"], row["is_active"], row["force_password_change"], row.get("last_login_at", ""), row["note"], row["created_at"], row["updated_at"]),
        )


def _sync_legacy_security_user(username: str, row: dict[str, Any]) -> None:
    # Compatibility for old login tables, still stored in Neon when PostgreSQL is enabled.
    try:
        db = _db()
        updated = db.execute(
            """
            UPDATE security_users SET password_hash=?, employee_id=?, display_name=?, email=?, is_active=?,
                force_password_change=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
            WHERE lower(username)=lower(?)
            """,
            (row.get("password_hash",""), row.get("employee_id",""), row.get("display_name", username), row.get("email",""), row.get("is_active",1), row.get("force_password_change",0), now_text(), username),
        )
        if int(updated or 0) <= 0:
            db.execute(
                """
                INSERT INTO security_users(username, password_hash, employee_id, display_name, email, is_active, force_password_change, last_login_at, created_at, updated_at, deleted_at, deleted_by, delete_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '')
                """,
                (username, row.get("password_hash",""), row.get("employee_id",""), row.get("display_name", username), row.get("email",""), row.get("is_active",1), row.get("force_password_change",0), row.get("last_login_at",""), row.get("created_at") or now_text(), now_text()),
            )
        db.execute("DELETE FROM security_user_roles WHERE lower(username)=lower(?)", (username,))
        db.execute("INSERT INTO security_user_roles(username, role_code, created_at) VALUES (?, ?, ?)", (username, str(row.get("role_code") or "operator"), now_text()))
    except Exception:
        pass



def _sync_legacy_security_users_batch(rows: list[dict[str, Any]]) -> None:
    """Batch compatibility mirror update for security_users/security_user_roles.

    Paste/Excel direct-save can submit many accounts.  The old code called
    _sync_legacy_security_user() for every changed row, which can generate 4 Neon
    statements per account outside the main transaction.  Keep the same mirror
    behavior, but run it in one transaction and fall back to the old per-row path
    only when a deployment has missing/older legacy tables.
    """
    clean_rows = [dict(r) for r in (rows or []) if str(r.get("username") or "").strip()]
    if not clean_rows:
        return
    ops: list[tuple[str, tuple[Any, ...]]] = []
    t = now_text()
    for row in clean_rows:
        username = str(row.get("username") or "").strip()
        if not username:
            continue
        common_update = (
            row.get("password_hash", ""),
            row.get("employee_id", ""),
            row.get("display_name", username),
            row.get("email", ""),
            row.get("is_active", 1),
            row.get("force_password_change", 0),
            t,
            username,
        )
        ops.append((
            """
            UPDATE security_users SET password_hash=?, employee_id=?, display_name=?, email=?, is_active=?,
                force_password_change=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
            WHERE lower(username)=lower(?)
            """,
            common_update,
        ))
        ops.append((
            """
            INSERT INTO security_users(username, password_hash, employee_id, display_name, email, is_active, force_password_change, last_login_at, created_at, updated_at, deleted_at, deleted_by, delete_reason)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ''
            WHERE NOT EXISTS (SELECT 1 FROM security_users WHERE lower(username)=lower(?) LIMIT 1)
            """,
            (
                username,
                row.get("password_hash", ""),
                row.get("employee_id", ""),
                row.get("display_name", username),
                row.get("email", ""),
                row.get("is_active", 1),
                row.get("force_password_change", 0),
                row.get("last_login_at", ""),
                row.get("created_at") or t,
                t,
                username,
            ),
        ))
        ops.append(("DELETE FROM security_user_roles WHERE lower(username)=lower(?)", (username,)))
        ops.append((
            "INSERT INTO security_user_roles(username, role_code, created_at) VALUES (?, ?, ?)",
            (username, str(row.get("role_code") or "operator"), t),
        ))
    if not ops:
        return
    try:
        _db().execute_transaction(ops, mark_changed=True, reason="sync_legacy_security_users_batch", source_sql="SYNC_LEGACY_SECURITY_USERS_BATCH")
    except Exception:
        for row in clean_rows:
            try:
                _sync_legacy_security_user(str(row.get("username") or ""), row)
            except Exception:
                pass




def _value_from_src(src: dict[str, Any], key: str, display_key: str, old: dict[str, Any], default: Any = "") -> Any:
    """Read an account field without treating an explicit blank edit as missing.

    The old V300.22 code used ``src.get(field) or old.get(field)``.  That made
    blank edits impossible to save: if an admin cleared employee_id/email/note,
    the service silently restored the old value and the Account Editor appeared
    to revert after rerun.  Presence of a key now means the user submitted that
    value, even when it is an empty string.
    """
    if key in src:
        return src.get(key)
    if display_key and display_key in src:
        return src.get(display_key)
    if key in old:
        return old.get(key)
    return default

def _user_row_changed(old: dict[str, Any], row: dict[str, Any], password_changed: bool) -> bool:
    if not old:
        return True
    if password_changed:
        return True
    checks = [
        ("employee_id", ""),
        ("display_name", ""),
        ("email", ""),
        ("role_code", "operator"),
        ("note", ""),
    ]
    for key, default in checks:
        if str(old.get(key) or default).strip() != str(row.get(key) or default).strip():
            return True
    if _norm_bool(old.get("is_active", 1), True) != _norm_bool(row.get("is_active", 1), True):
        return True
    if _norm_bool(old.get("force_password_change", 0), False) != _norm_bool(row.get("force_password_change", 0), False):
        return True
    return False


def _fetch_existing_users_by_username(usernames: list[str]) -> dict[str, dict[str, Any]]:
    keys = sorted({str(u or "").strip().lower() for u in usernames if str(u or "").strip()})
    if not keys:
        return {}
    placeholders = ",".join(["?"] * len(keys))
    df = _db().query_df(
        f"SELECT * FROM auth_users WHERE lower(username) IN ({placeholders})",
        tuple(keys),
    )
    if df is None or df.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in df.to_dict("records"):
        uname = str(r.get("username") or "").strip().lower()
        if uname:
            out[uname] = dict(r)
    return out


def _auth_user_upsert_ops(row: dict[str, Any]) -> list[tuple[str, tuple[Any, ...]]]:
    username = str(row.get("username") or "").strip()
    if not username:
        return []
    return [
        (
            """
            UPDATE auth_users SET
                password_hash=?, password_hint=?, employee_id=?, display_name=?, email=?, role_code=?, is_active=?,
                force_password_change=?, note=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
            WHERE lower(username)=lower(?)
            """,
            (row["password_hash"], row["password_hint"], row["employee_id"], row["display_name"], row["email"], row["role_code"], row["is_active"], row["force_password_change"], row["note"], row["updated_at"], username),
        ),
        (
            """
            INSERT INTO auth_users(username, password_hash, password_hint, employee_id, display_name, email, role_code, is_active,
                force_password_change, last_login_at, note, created_at, updated_at, deleted_at, deleted_by, delete_reason)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ''
            WHERE NOT EXISTS (SELECT 1 FROM auth_users WHERE lower(username)=lower(?) LIMIT 1)
            """,
            (username, row["password_hash"], row["password_hint"], row["employee_id"], row["display_name"], row["email"], row["role_code"], row["is_active"], row["force_password_change"], row.get("last_login_at", ""), row["note"], row["created_at"], row["updated_at"], username),
        ),
    ]


def save_users(rows: list[dict[str,Any]]) -> dict:
    # V300.48：Account Editor 會先在頁面端過濾出真正有異動的列。
    # 沒有異動時不要為了 no-op 仍執行 _ensure_schema() / SELECT / cache clear，
    # 否則「套用並儲存帳號密碼總表」看起來會長時間運轉。
    input_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    if not input_rows:
        return {"ok": True, "saved": 0, "skipped_unchanged": 0, "skipped": [], "backend": "Neon/PostgreSQL", "batch_fastpath": True, "no_op": True}
    _ensure_schema()
    # V300.35：Account Editor / Excel / Paste 可能一次送出多筆帳號。
    # 舊版每筆帳號都先 SELECT 舊值，再 UPDATE/INSERT，500 筆可能造成 500+ 次 Neon SELECT。
    # 現在先一次讀出本批帳號的現有資料，再只把有異動的列批次寫入 transaction。
    usernames = [str(r.get("username") or r.get("帳號 / Username") or "").strip() for r in input_rows]
    existing_by_user = _fetch_existing_users_by_username(usernames)
    changed_rows: list[dict[str, Any]] = []
    saved = 0
    skipped_unchanged = 0
    skipped: list[str] = []
    for src in input_rows:
        username = str(src.get("username") or src.get("帳號 / Username") or "").strip()
        if not username:
            continue
        old = existing_by_user.get(username.lower(), {}) or {}
        new_pwd = str(src.get("new_password") or src.get("password") or src.get("密碼 / Password") or src.get("新密碼 / New Password") or "").strip()
        password_changed = bool(new_pwd and set(new_pwd) != {"*"})
        if password_changed:
            password_hash = hash_password(new_pwd)
        else:
            password_hash = str(old.get("password_hash") or "") or hash_password("Admin@1234" if username.lower()=="admin" else username)
        employee_id = str(_value_from_src(src, "employee_id", "工號 / Employee ID", old, "") or "").strip()
        display_name = str(_value_from_src(src, "display_name", "姓名 / Display Name", old, username) or "").strip() or username
        email = str(_value_from_src(src, "email", "Email", old, "") or "").strip()
        role_code = str(_value_from_src(src, "role_code", "角色 / Role", old, "operator") or "operator").strip() or "operator"
        note = str(_value_from_src(src, "note", "備註 / Note", old, "") or "").strip()
        row = {
            "username": username,
            "password_hash": password_hash,
            "password_hint": str(_value_from_src(src, "password_hint", "", old, "") or ""),
            "employee_id": employee_id,
            "display_name": display_name,
            "email": email,
            "role_code": role_code,
            "is_active": _norm_bool(src.get("is_active", src.get("啟用 / Active", old.get("is_active", 1))), True),
            "force_password_change": _norm_bool(src.get("force_password_change", src.get("強制改密碼 / Force Change", old.get("force_password_change", 0))), False),
            "last_login_at": str(old.get("last_login_at") or ""),
            "note": note,
            "created_at": str(old.get("created_at") or now_text()),
            "updated_at": now_text(),
        }
        if not _user_row_changed(old, row, password_changed=password_changed):
            skipped_unchanged += 1
            continue
        changed_rows.append(row)
    ops: list[tuple[str, tuple[Any, ...]]] = []
    for row in changed_rows:
        ops.extend(_auth_user_upsert_ops(row))
    if ops:
        try:
            _db().execute_transaction(ops, mark_changed=True, reason="save_users", source_sql="SAVE_USERS")
            saved = len(changed_rows)
        except Exception:
            # Safety fallback: keep the old per-row path if a deployment has an unusual DB adapter.
            saved = 0
            for row in changed_rows:
                try:
                    _insert_or_update_auth_user(row)
                    saved += 1
                except Exception as exc:
                    skipped.append(f"{row.get('username')}: {exc}")
    # Legacy security tables are compatibility mirrors only.  Sync after authority
    # writes succeed.  V300.46 batches the mirror sync so Paste/Excel direct-save
    # does not run several extra Neon statements per account outside one transaction.
    _sync_legacy_security_users_batch(changed_rows)
    if saved or skipped:
        _clear_cache()
        _log("SAVE_USERS", f"saved={saved}; unchanged={skipped_unchanged}; skipped={len(skipped)}")
    return {"ok": True, "saved": saved, "skipped_unchanged": skipped_unchanged, "skipped": skipped, "backend": "Neon/PostgreSQL", "batch_fastpath": True}


def save_account_master(rows: list[dict[str,Any]], delete_usernames: list[str]|None=None) -> dict:
    # V300.48：支援頁面端 delta-save。只有刪除、沒有帳號列異動時，
    # 不再先呼叫 save_users([]) 觸發任何不必要的 schema/cache 路徑。
    if rows:
        res = save_users(rows or [])
    else:
        res = {"ok": True, "saved": 0, "skipped_unchanged": 0, "skipped": [], "backend": "Neon/PostgreSQL", "batch_fastpath": True, "no_op": True}
    deleted = delete_users(delete_usernames or []) if delete_usernames else 0
    res["deleted"] = deleted
    return res


def delete_users(usernames: list[str]) -> int:
    _ensure_schema()
    deleted = 0
    ops: list[tuple[str, tuple[Any, ...]]] = []
    for raw in usernames or []:
        username = str(raw or "").strip()
        if not username or username.lower() == "admin":
            continue
        t = now_text()
        ops.extend([
            ("DELETE FROM auth_account_permissions WHERE lower(username)=lower(?)", (username,)),
            ("DELETE FROM security_user_roles WHERE lower(username)=lower(?)", (username,)),
            ("UPDATE auth_users SET deleted_at=?, deleted_by='admin', delete_reason='delete_users', is_active=0, updated_at=? WHERE lower(username)=lower(?)", (t, t, username)),
            ("UPDATE security_users SET deleted_at=?, deleted_by='admin', delete_reason='delete_users', is_active=0, updated_at=? WHERE lower(username)=lower(?)", (t, t, username)),
        ])
        deleted += 1
    if ops:
        try:
            _db().execute_transaction(ops, mark_changed=True, reason="delete_users", source_sql="DELETE_USERS")
        except Exception:
            for sql, params in ops:
                try:
                    _db().execute(sql, params)
                except Exception:
                    pass
    _clear_cache()
    _log("DELETE_USERS", f"deleted={deleted}")
    return deleted


def get_account_permissions() -> list[dict[str,Any]]:
    _ensure_schema()
    import time
    now_ts = time.time()
    cached = _MATRIX_CACHE.get("perms")
    if cached is not None and now_ts - float(_MATRIX_CACHE.get("perms_ts") or 0) < 300:
        return [dict(r) for r in cached]
    users = get_users()
    df = _db().query_df(
        """
        SELECT username, module_code, module_name_zh, module_name_en,
               can_view, can_create, can_edit, can_delete, can_import, can_export, can_backup, can_restore, can_manage,
               updated_at
        FROM auth_account_permissions
        ORDER BY lower(username), module_code
        """
    )
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if df is not None and not df.empty:
        for r in df.to_dict("records"):
            existing[(str(r.get("username") or "").lower(), _module_no(r.get("module_code")))] = dict(r)
    rows: list[dict[str, Any]] = []
    for u in users:
        username = str(u.get("username") or "")
        role = str(u.get("role_code") or "operator")
        for m in MODULES:
            code = m["module_code"]
            base = existing.get((username.lower(), code))
            if base is None:
                defaults = _role_defaults(role, code)
                base = {
                    "username": username,
                    "module_code": code,
                    "module_name_zh": m["module_name_zh"],
                    "module_name_en": m["module_name_en"],
                    **defaults,
                    "updated_at": "",
                }
            row = dict(base)
            row["display_name"] = u.get("display_name") or username
            row["role_code"] = role
            row["module_code"] = code
            row.setdefault("module_name_zh", m["module_name_zh"])
            row.setdefault("module_name_en", m["module_name_en"])
            for c in ACTION_COLS:
                row[c] = bool(_norm_bool(row.get(c), False))
            rows.append(row)
    _MATRIX_CACHE["perms"] = [dict(r) for r in rows]
    _MATRIX_CACHE["perms_ts"] = now_ts
    return rows


def save_account_permissions(rows: list[dict[str,Any]]) -> dict:
    _ensure_schema()
    # V104：確認後才寫入，且只寫有變更的權限列。
    # V300.35：只讀本次送出的帳號/模組既有權限，不再每次儲存都 SELECT 全矩陣。
    normalized_rows: list[tuple[str, str, dict[str, Any]]] = []
    for src in rows or []:
        if not isinstance(src, dict):
            continue
        username = str(src.get("username") or src.get("帳號 / Username") or "").strip()
        code = _module_no(src.get("module_code") or src.get("模組代碼 / Module") or src.get("Module") or src.get("module"))
        if username and code:
            normalized_rows.append((username, code, src))
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    if normalized_rows:
        users = sorted({u.lower() for u, _, _ in normalized_rows})
        codes = sorted({c for _, c, _ in normalized_rows})
        user_ph = ",".join(["?"] * len(users))
        code_ph = ",".join(["?"] * len(codes))
        existing_df = _db().query_df(
            f"""
            SELECT username, module_code, can_view, can_create, can_edit, can_delete, can_import, can_export, can_backup, can_restore, can_manage
            FROM auth_account_permissions
            WHERE lower(username) IN ({user_ph}) AND module_code IN ({code_ph})
            """,
            tuple(users + codes),
        )
        if existing_df is not None and not existing_df.empty:
            for r in existing_df.to_dict("records"):
                existing[(str(r.get("username") or "").lower(), _module_no(r.get("module_code")))] = dict(r)
    ops: list[tuple[str, tuple[Any, ...]]] = []
    saved = 0
    skipped_unchanged = 0
    for username, code, src in normalized_rows:
        meta = _module_meta(code)
        vals = {a[0]: _norm_bool(src.get(a[0], 0), False) for a in ACTIONS}
        old = existing.get((username.lower(), code))
        changed = False
        if old is not None:
            for key in ACTION_COLS:
                if _norm_bool(old.get(key), False) != vals[key]:
                    changed = True
                    break
        else:
            # V300.22：使用者在 10｜帳號模組權限按下「套用並儲存」時，
            # 畫面上的矩陣必須成為 Neon/PostgreSQL 的永久紀錄。
            # 舊版若值剛好等於角色預設就不建立實體列，會讓設定仍停留在「隱含預設」，
            # 之後角色預設或帳號角色異動時可能看起來像沒有永久保存。
            # 因此：不存在的列一律 INSERT；已存在且未變更的列才略過，避免重複 UPDATE。
            changed = True
        if not changed:
            skipped_unchanged += 1
            continue
        params_common = (meta["module_name_zh"], meta["module_name_en"], vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text(), username, code)
        ops.append((
            """
            UPDATE auth_account_permissions SET module_name_zh=?, module_name_en=?, can_view=?, can_create=?, can_edit=?, can_delete=?, can_import=?, can_export=?, can_backup=?, can_restore=?, can_manage=?, updated_at=?
            WHERE lower(username)=lower(?) AND module_code=?
            """,
            params_common,
        ))
        ops.append((
            """
            INSERT INTO auth_account_permissions(username, module_code, module_name_zh, module_name_en, can_view, can_create, can_edit, can_delete, can_import, can_export, can_backup, can_restore, can_manage, updated_at)
            SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,?
            WHERE NOT EXISTS (SELECT 1 FROM auth_account_permissions WHERE lower(username)=lower(?) AND module_code=? LIMIT 1)
            """,
            (username, code, meta["module_name_zh"], meta["module_name_en"], vals["can_view"], vals["can_create"], vals["can_edit"], vals["can_delete"], vals["can_import"], vals["can_export"], vals["can_backup"], vals["can_restore"], vals["can_manage"], now_text(), username, code),
        ))
        saved += 1
    if ops:
        try:
            _db().execute_transaction(ops, mark_changed=True, reason="save_account_permissions", source_sql="SAVE_ACCOUNT_PERMISSIONS")
        except Exception:
            for sql, params in ops:
                try:
                    _db().execute(sql, params)
                except Exception:
                    pass
    if saved:
        _clear_cache()
        _log("SAVE_ACCOUNT_PERMISSIONS", f"saved={saved}; unchanged={skipped_unchanged}")
    return {"ok": True, "saved": saved, "skipped_unchanged": skipped_unchanged, "backend": "Neon/PostgreSQL"}


def has_permission(username: str, module_code: str, action: str="can_view") -> bool:
    uname = str(username or "").strip()
    code = _module_no(module_code)
    act = str(action or "can_view")
    if not uname:
        return False
    if uname.lower() == "admin":
        return True
    if act not in ACTION_COLS:
        act = "can_view"
    _ensure_schema()
    user = _db().query_one("SELECT * FROM auth_users WHERE lower(username)=lower(?) AND COALESCE(deleted_at,'')='' LIMIT 1", (uname,))
    if not user or not _norm_bool(user.get("is_active", 1), True):
        return False
    row = _db().query_one("SELECT * FROM auth_account_permissions WHERE lower(username)=lower(?) AND module_code=? LIMIT 1", (uname, code))
    if row and act in row:
        if _norm_bool(row.get("can_manage"), False):
            return True
        return bool(_norm_bool(row.get(act), False))
    return bool(_role_defaults(str(user.get("role_code") or "operator"), code).get(act, 0))


def get_security_settings() -> dict[str,Any]:
    _ensure_schema()
    import time
    now_ts = time.time()
    cached = _MATRIX_CACHE.get("security")
    if isinstance(cached, dict) and now_ts - float(_MATRIX_CACHE.get("security_ts") or 0) < 300:
        return dict(cached)
    df = _db().query_df("SELECT setting_key, setting_value FROM auth_security_settings")
    out: dict[str, Any] = {}
    if df is not None and not df.empty:
        for r in df.to_dict("records"):
            out[str(r.get("setting_key"))] = r.get("setting_value")
    out.setdefault("idle_timeout_minutes", out.get("idle_auto_logout_minutes", 15))
    out.setdefault("idle_auto_logout_minutes", out.get("idle_timeout_minutes", 15))
    out.setdefault("ask_continue_after_record", 1)
    _MATRIX_CACHE["security"] = dict(out)
    _MATRIX_CACHE["security_ts"] = now_ts
    return out


def save_security_settings(settings: dict[str,Any]) -> dict:
    _ensure_schema()
    old = get_security_settings()
    cur = dict(old)
    cur.update(settings or {})
    minutes = cur.get("idle_timeout_minutes", cur.get("idle_auto_logout_minutes", 15))
    try:
        cur["idle_timeout_minutes"] = int(float(minutes or 15))
    except Exception:
        cur["idle_timeout_minutes"] = 15
    cur["idle_auto_logout_minutes"] = cur["idle_timeout_minutes"]
    # V104：只寫入有變更的安全設定，避免每次按套用都重複 UPDATE/INSERT 所有設定。
    changed_keys = []
    for k, v in cur.items():
        if str(old.get(k, "")) != str(v):
            changed_keys.append(str(k))
    if not changed_keys:
        return {"ok": True, "saved": 0, "skipped_unchanged": len(cur), "backend": "Neon/PostgreSQL"}
    ops: list[tuple[str, tuple[Any, ...]]] = []
    for k in changed_keys:
        v = cur.get(k, "")
        ops.append(("UPDATE auth_security_settings SET setting_value=?, updated_at=? WHERE setting_key=?", (str(v), now_text(), str(k))))
        ops.append(("INSERT INTO auth_security_settings(setting_key, setting_value, note, updated_at) SELECT ?, ?, '', ? WHERE NOT EXISTS (SELECT 1 FROM auth_security_settings WHERE setting_key=? LIMIT 1)", (str(k), str(v), now_text(), str(k))))
        # 舊 security_settings 僅做登入流程相容 mirror，不再作獨立權威。
        ops.append(("UPDATE security_settings SET setting_value=?, updated_at=? WHERE setting_key=?", (str(v), now_text(), str(k))))
        ops.append(("INSERT INTO security_settings(setting_key, setting_value, note, updated_at) SELECT ?, ?, '', ? WHERE NOT EXISTS (SELECT 1 FROM security_settings WHERE setting_key=? LIMIT 1)", (str(k), str(v), now_text(), str(k))))
    try:
        _db().execute_transaction(ops, mark_changed=True, reason="save_security_settings", source_sql="SAVE_SECURITY_SETTINGS")
    except Exception:
        for sql, params in ops:
            try:
                _db().execute(sql, params)
            except Exception:
                pass
    _clear_cache()
    _log("SAVE_SECURITY_SETTINGS", f"saved={len(changed_keys)}")
    return {"ok": True, "saved": len(changed_keys), "skipped_unchanged": len(cur) - len(changed_keys), "backend": "Neon/PostgreSQL"}


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
    sql = "SELECT * FROM auth_login_logs WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 1000"
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
    return _db().get_connection()

def clear_permission_runtime_cache():
    _clear_cache()
    return None

def sync_auth_users_to_runtime_security(usernames=None):
    if usernames is None:
        users = get_users()
    else:
        user_set = {str(u) for u in usernames}
        users = [u for u in get_users() if str(u.get("username")) in user_set]
    for u in users:
        _sync_legacy_security_user(str(u.get("username")), u)
    return {"ok": True, "backend": "Neon/PostgreSQL", "count": len(users)}

def permission_recovery_diagnostic():
    return {"ok": True, "authority": "Neon/PostgreSQL", "users": len(get_users()), "fastpath": True}

def permission_password_emergency_recovery():
    return {"ok": True, "skipped": True, "authority": "Neon/PostgreSQL"}

def force_restore_admin_password_v30017_4():
    return save_users([{"username":"admin","new_password":"Admin@1234","display_name":"系統管理員","role_code":"admin","is_active":1}])

