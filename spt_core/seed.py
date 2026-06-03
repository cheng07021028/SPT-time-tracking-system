from __future__ import annotations

import os

from .db import execute, fetch_one
from .security import hash_password
from .utils import json_dumps, now_iso


def _insert_setting(conn, key: str, value, updated_by: str = "system") -> None:
    existing = fetch_one(conn, "SELECT setting_key FROM system_settings WHERE setting_key=:key", {"key": key})
    if existing:
        return
    execute(
        conn,
        """
        INSERT INTO system_settings(setting_key, setting_value, updated_at, updated_by)
        VALUES(:key, :value, :updated_at, :updated_by)
        """,
        {"key": key, "value": json_dumps(value), "updated_at": now_iso(), "updated_by": updated_by},
    )


def _insert_process(conn, code: str, name: str, sort: int) -> None:
    existing = fetch_one(conn, "SELECT process_code FROM processes WHERE process_code=:code", {"code": code})
    if existing:
        return
    execute(
        conn,
        """
        INSERT INTO processes(process_code, process_name, sort_order, active, allow_parallel, allow_group_average, standard_minutes, created_at, updated_at)
        VALUES(:code, :name, :sort_order, 1, 1, 1, 0, :created_at, :updated_at)
        """,
        {"code": code, "name": name, "sort_order": sort, "created_at": now_iso(), "updated_at": now_iso()},
    )


def seed_minimum_data(conn) -> None:
    now = now_iso()
    admin_username = os.getenv("SPT_ADMIN_USERNAME", "admin") or "admin"
    admin_password = os.getenv("SPT_ADMIN_PASSWORD", "admin123") or "admin123"
    existing = fetch_one(conn, "SELECT username FROM users WHERE username=:username", {"username": admin_username})
    if not existing:
        execute(
            conn,
            """
            INSERT INTO users(username, display_name, password_hash, role, active, created_at, updated_at)
            VALUES(:username, :display_name, :password_hash, 'admin', 1, :created_at, :updated_at)
            """,
            {
                "username": admin_username,
                "display_name": "系統管理員",
                "password_hash": hash_password(admin_password),
                "created_at": now,
                "updated_at": now,
            },
        )

    _insert_setting(conn, "timezone", os.getenv("SPT_TIMEZONE", "Asia/Taipei"))
    _insert_setting(conn, "enable_group_average", True)
    _insert_setting(conn, "auto_pause_different_group", True)
    _insert_setting(conn, "break_windows", [{"start": "12:00", "end": "13:00", "name": "午休"}])
    _insert_setting(conn, "default_query_limit", 500)

    _insert_process(conn, "DEW", "DEW 同步作業", 10)
    _insert_process(conn, "ASM", "組裝", 20)
    _insert_process(conn, "TEST", "測試", 30)
    _insert_process(conn, "PACK", "包裝", 40)
    _insert_process(conn, "REWORK", "返工", 50)
