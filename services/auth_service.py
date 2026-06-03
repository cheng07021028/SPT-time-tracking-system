# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import streamlit as st

from services.app_config import ACTIONS, MODULES
from services.permanent_store import load_system, save_system, append_jsonl, system_path, now_str


def _hash_password(password: str) -> str:
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def _default_users() -> list[dict[str, Any]]:
    return [{
        "帳號": "admin",
        "password_hash": _hash_password("admin123"),
        "姓名": "系統管理員",
        "角色": "admin",
        "啟用": True,
        "備註": "首次登入後請立即修改密碼",
    }]


def load_users() -> list[dict[str, Any]]:
    users = load_system("users.json", _default_users())
    if not isinstance(users, list) or not users:
        users = _default_users()
        save_system("users.json", users)
    return users


def save_users(users: list[dict[str, Any]]) -> None:
    clean = []
    for u in users:
        if not str(u.get("帳號", "")).strip():
            continue
        row = dict(u)
        if row.get("密碼") and str(row.get("密碼")) != "********":
            row["password_hash"] = _hash_password(str(row.pop("密碼")))
        else:
            row.pop("密碼", None)
        clean.append(row)
    if not any(str(u.get("角色")) == "admin" and bool(u.get("啟用", True)) for u in clean):
        clean.insert(0, _default_users()[0])
    save_system("users.json", clean)


def default_permissions() -> dict[str, Any]:
    perms: dict[str, Any] = {}
    for m in MODULES:
        perms[m.key] = {a: True for a in ACTIONS}
    return {"admin": perms}


def load_permissions() -> dict[str, Any]:
    data = load_system("permissions.json", default_permissions())
    return data if isinstance(data, dict) else default_permissions()


def save_permissions(perms: dict[str, Any]) -> None:
    save_system("permissions.json", perms)


def load_security_settings() -> dict[str, Any]:
    data = load_system("security_settings.json", {"idle_timeout_minutes": 60, "login_required": True})
    return data if isinstance(data, dict) else {"idle_timeout_minutes": 60, "login_required": True}


def save_security_settings(data: dict[str, Any]) -> None:
    save_system("security_settings.json", data)


def log_login(username: str, result: str, message: str = "") -> None:
    append_jsonl(system_path("login_logs.jsonl"), {"時間": now_str(), "帳號": username, "結果": result, "訊息": message})


def authenticate(username: str, password: str) -> bool:
    for u in load_users():
        if str(u.get("帳號", "")).strip() == username and bool(u.get("啟用", True)):
            ok = u.get("password_hash") == _hash_password(password)
            log_login(username, "成功" if ok else "失敗", "password check")
            if ok:
                st.session_state["auth_user"] = username
                st.session_state["auth_role"] = str(u.get("角色", "viewer"))
                st.session_state["auth_name"] = str(u.get("姓名", username))
                st.session_state["last_active_at"] = datetime.now().isoformat()
            return ok
    log_login(username, "失敗", "user not found or inactive")
    return False


def current_user() -> str:
    return str(st.session_state.get("auth_user") or "")


def current_role() -> str:
    return str(st.session_state.get("auth_role") or "viewer")


def is_admin() -> bool:
    return current_role() == "admin"


def logout() -> None:
    user = current_user()
    if user:
        log_login(user, "登出", "manual logout")
    for k in ["auth_user", "auth_role", "auth_name", "last_active_at"]:
        st.session_state.pop(k, None)


def check_permission(module_key: str, action: str = "view") -> bool:
    if not current_user():
        return False
    if is_admin():
        return True
    perms = load_permissions()
    role = current_role()
    role_perm = perms.get(role, {}) if isinstance(perms, dict) else {}
    mod_perm = role_perm.get(module_key, {}) if isinstance(role_perm, dict) else {}
    return bool(mod_perm.get(action, False))


def require_login() -> None:
    if current_user():
        return
    st.title("超慧科技製造部｜智慧工時紀錄系統")
    st.caption("Clean Architecture｜單一路徑永久保存版")
    with st.form("login_form"):
        username = st.text_input("帳號", value="admin")
        password = st.text_input("密碼", type="password")
        submitted = st.form_submit_button("登入")
    st.info("乾淨版預設管理員：admin / admin123。正式使用前請到 10 權限管理修改密碼。")
    if submitted:
        if authenticate(username.strip(), password):
            st.rerun()
        st.error("帳號或密碼錯誤，或帳號已停用。")
    st.stop()


def require_module(module_key: str, action: str = "view") -> None:
    require_login()
    if not check_permission(module_key, action):
        log_login(current_user(), "權限不足", f"{module_key}:{action}")
        st.error("目前帳號沒有此模組權限，請聯絡系統管理員。")
        st.stop()

# ===== V257 SPEED DIAGNOSTIC WRAPPERS｜2026-05-31 =====
# Timing only. No authentication behavior changes.
try:
    from services.spt_speed_diagnostic_service import wrap as _v257_diag_wrap
    if "load_users" in globals():
        load_users = _v257_diag_wrap(load_users, category="login", name="auth.load_users", threshold_ms=100.0)  # type: ignore[assignment]
    if "log_login" in globals():
        log_login = _v257_diag_wrap(log_login, category="login", name="auth.log_login", threshold_ms=100.0)  # type: ignore[assignment]
    if "authenticate" in globals():
        authenticate = _v257_diag_wrap(authenticate, category="login", name="auth.authenticate", threshold_ms=200.0)  # type: ignore[assignment]
except Exception:
    pass
# ===== END V257 SPEED DIAGNOSTIC WRAPPERS =====
