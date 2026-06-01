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
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from services.db_service import execute, query_df, query_one

PBKDF2_ITERATIONS = 180_000
DEFAULT_IDLE_MINUTES = 15

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
]

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
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
    if not stored_hash:
        return False
    try:
        algo, iter_s, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def ensure_security_schema() -> None:
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
    seed_security_defaults()


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
                INSERT INTO security_users
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


def get_idle_timeout_minutes() -> int:
    ensure_security_schema()
    row = query_one("SELECT setting_value FROM security_settings WHERE setting_key='idle_timeout_minutes'")
    try:
        minutes = int(float(row["setting_value"])) if row else DEFAULT_IDLE_MINUTES
    except Exception:
        minutes = DEFAULT_IDLE_MINUTES
    return max(1, minutes)


def set_idle_timeout_minutes(minutes: int) -> None:
    ensure_security_schema()
    minutes = max(1, int(minutes))
    execute("""
        INSERT INTO security_settings (setting_key, setting_value, note, updated_at)
        VALUES ('idle_timeout_minutes', ?, '閒置多久自動登出，單位分鐘', ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            note=excluded.note,
            updated_at=excluded.updated_at
    """, (str(minutes), _now()))


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


def authenticate(username: str, password: str) -> tuple[bool, str]:
    ensure_security_schema()
    username = (username or "").strip()
    row = query_one("SELECT * FROM security_users WHERE username=?", (username,))
    if not row:
        log_security_event(username, "LOGIN", "FAIL", "帳號不存在")
        return False, "帳號或密碼錯誤。"
    if not int(row.get("is_active", 0)):
        log_security_event(username, "LOGIN", "FAIL", "帳號停用")
        return False, "帳號已停用。"
    if not verify_password(password, row.get("password_hash")):
        log_security_event(username, "LOGIN", "FAIL", "密碼錯誤")
        return False, "帳號或密碼錯誤。"

    roles = _user_roles(username)
    st.session_state["auth_logged_in"] = True
    st.session_state["auth_username"] = username
    st.session_state["auth_display_name"] = row.get("display_name") or username
    st.session_state["auth_employee_id"] = row.get("employee_id") or ""
    st.session_state["auth_roles"] = roles
    now_ts = time.time()
    st.session_state["auth_login_ts"] = now_ts
    st.session_state["auth_last_activity_ts"] = now_ts
    execute("UPDATE security_users SET last_login_at=?, updated_at=? WHERE username=?", (_now(), _now(), username))
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
    for k in list(st.session_state.keys()):
        if k.startswith("auth_") or k.startswith("post_record_"):
            del st.session_state[k]


def check_permission(module_code: str, action: str = "can_view") -> bool:
    ensure_security_schema()
    user = get_current_user()
    if not user:
        return False
    roles = user.get("roles", [])
    if "admin" in roles:
        return True
    if action not in PERMISSION_COLUMNS:
        action = "can_view"
    if not roles:
        return False
    placeholders = ",".join(["?"] * len(roles))
    sql = f"""
        SELECT MAX({action}) AS allowed
        FROM security_module_permissions
        WHERE module_code=? AND role_code IN ({placeholders})
    """
    row = query_one(sql, tuple([module_code] + roles))
    return bool(row and int(row.get("allowed") or 0) == 1)


def render_login_form() -> None:
    st.markdown("### 登入系統 / Login")
    st.caption("請使用個人帳號登入。預設管理員：admin / Admin@1234，上線後請立即改密碼。")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("帳號 / Username")
        password = st.text_input("密碼 / Password", type="password")
        submitted = st.form_submit_button("登入 / Login", use_container_width=True)
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
    c1, c2, c3 = st.columns([2, 2, 1])
    c1.caption(f"登入帳號：{user['display_name']}（{user['username']}）")
    c2.caption(f"角色：{roles}｜閒置自動登出：{get_idle_timeout_minutes()} 分鐘")
    if c3.button("登出 / Logout", use_container_width=True, key=f"logout_{module_code}"):
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


def mark_activity() -> None:
    st.session_state["auth_last_activity_ts"] = time.time()


def trigger_post_record_continue_prompt(message: str = "工時紀錄已完成") -> None:
    st.session_state["post_record_prompt"] = True
    st.session_state["post_record_message"] = message


def render_post_record_continue_prompt() -> None:
    if not st.session_state.get("post_record_prompt"):
        return

    def _content() -> None:
        st.success(st.session_state.get("post_record_message", "工時紀錄已完成"))
        st.markdown("### 是否繼續記錄下一筆工時？")
        c1, c2 = st.columns(2)
        if c1.button("是，繼續記錄 / Continue", use_container_width=True, key="post_continue_yes"):
            st.session_state["post_record_prompt"] = False
            mark_activity()
            st.rerun()
        if c2.button("否，登出帳號 / Logout", use_container_width=True, key="post_continue_no"):
            logout("完成工時後選擇不繼續記錄，自動登出")
            st.rerun()

    if hasattr(st, "dialog"):
        @st.dialog("工時紀錄完成 / Record Completed")
        def _dialog():
            _content()
        _dialog()
    else:
        st.warning("工時紀錄完成，請選擇是否繼續記錄。")
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
