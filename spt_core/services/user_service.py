from __future__ import annotations

from typing import Any

from ..db import execute, fetch_all, fetch_one, transaction
from ..result import Result
from ..security import hash_password, verify_password
from ..utils import now_iso
from .log_service import append_log
from .login_event_service import append_login_event
from .permission_service import require_permission


def authenticate(username: str, password: str, session_id: str | None = None) -> Result:
    username = (username or "").strip()
    with transaction() as conn:
        user = fetch_one(conn, "SELECT * FROM users WHERE username=:username AND deleted_at IS NULL", {"username": username})
        if not user or not user.get("active"):
            append_login_event(conn, username=username, display_name=None, role=None, result="failed", session_id=session_id, error_message="user not found or inactive")
            return Result.failure("帳號不存在或已停用")
        if not verify_password(password, user["password_hash"]):
            append_login_event(conn, username=username, display_name=user.get("display_name"), role=user.get("role"), result="failed", session_id=session_id, error_message="invalid password")
            return Result.failure("密碼錯誤")
        append_login_event(conn, username=username, display_name=user.get("display_name"), role=user.get("role"), result="success", session_id=session_id)
        safe_user = {k: v for k, v in user.items() if k != "password_hash"}
        return Result.success("登入成功", data=safe_user)


def list_users(actor: dict) -> Result:
    perm = require_permission(actor, "permission.manage")
    if not perm.ok:
        return perm
    with transaction() as conn:
        rows = fetch_all(conn, "SELECT username, display_name, role, active, created_at, updated_at, deleted_at FROM users ORDER BY username")
    return Result.success(data=rows)


def create_user(actor: dict, username: str, display_name: str, password: str, role: str) -> Result:
    perm = require_permission(actor, "permission.manage")
    if not perm.ok:
        return perm
    username = username.strip()
    if not username or not password:
        return Result.failure("帳號與密碼不可空白")
    if role not in {"operator", "supervisor", "admin"}:
        return Result.failure("角色不正確")
    now = now_iso()
    with transaction() as conn:
        existing = fetch_one(conn, "SELECT username FROM users WHERE username=:username", {"username": username})
        if existing:
            return Result.failure("帳號已存在")
        row = {"username": username, "display_name": display_name.strip() or username, "password_hash": hash_password(password), "role": role, "created_at": now, "updated_at": now}
        execute(
            conn,
            """
            INSERT INTO users(username, display_name, password_hash, role, active, created_at, updated_at)
            VALUES(:username, :display_name, :password_hash, :role, 1, :created_at, :updated_at)
            """,
            row,
        )
        log_id = append_log(conn, actor=actor.get("username"), module="10_權限管理", action="create_user", target_type="user", target_id=username, after={k: v for k, v in row.items() if k != "password_hash"})
    return Result.success("使用者已新增", data={"username": username}, log_id=log_id)


def reset_password(actor: dict, username: str, new_password: str) -> Result:
    perm = require_permission(actor, "permission.manage")
    if not perm.ok:
        return perm
    if not new_password:
        return Result.failure("新密碼不可空白")
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT username, display_name, role, active FROM users WHERE username=:username", {"username": username})
        if not before:
            return Result.failure("帳號不存在")
        execute(conn, "UPDATE users SET password_hash=:password_hash, updated_at=:updated_at WHERE username=:username", {"password_hash": hash_password(new_password), "updated_at": now, "username": username})
        log_id = append_log(conn, actor=actor.get("username"), module="10_權限管理", action="reset_password", target_type="user", target_id=username, before=before, after={"username": username})
    return Result.success("密碼已重設", log_id=log_id)


def set_user_active(actor: dict, username: str, active: bool) -> Result:
    perm = require_permission(actor, "permission.manage")
    if not perm.ok:
        return perm
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT username, display_name, role, active FROM users WHERE username=:username", {"username": username})
        if not before:
            return Result.failure("帳號不存在")
        execute(conn, "UPDATE users SET active=:active, updated_at=:updated_at WHERE username=:username", {"active": 1 if active else 0, "updated_at": now, "username": username})
        after = fetch_one(conn, "SELECT username, display_name, role, active FROM users WHERE username=:username", {"username": username})
        log_id = append_log(conn, actor=actor.get("username"), module="10_權限管理", action="set_user_active", target_type="user", target_id=username, before=before, after=after)
    return Result.success("使用者狀態已更新", data=after, log_id=log_id)
