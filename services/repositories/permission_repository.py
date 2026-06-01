# -*- coding: utf-8 -*-
"""V164 permission repository facade.

This layer only centralises access to permission data.  It does not change the
existing rule that module 10 is admin-only.
"""
from __future__ import annotations

from typing import Any

from .base_repository import RepositoryHealth, Rows, clean_rows, trim_rows
from .json_authority_repository import AuthorityRepository
from .sqlite_repository import SQLiteRepository


class PermissionRepository:
    name = "permissions"

    def __init__(self) -> None:
        self.users_sqlite = SQLiteRepository("auth_users", name="permissions_auth_users_sqlite")
        self.permission_sqlite = SQLiteRepository("auth_account_permissions", name="permissions_auth_account_permissions_sqlite")
        self.authority = AuthorityRepository("10_permissions", "auth_users", name="10_permissions_authority")

    def list_users(self, limit: int | None = 500) -> Rows:
        if self.users_sqlite.table_exists():
            return self.users_sqlite.list_rows(limit=limit)
        return self.authority.list_rows(limit=limit)

    def list_permissions(self, limit: int | None = 1000) -> Rows:
        if self.permission_sqlite.table_exists():
            return self.permission_sqlite.list_rows(limit=limit)
        tables = self.authority.load_tables()
        for table_name in ("auth_account_permissions", "security_module_permissions", "module_permissions"):
            if table_name in tables:
                return trim_rows(clean_rows(tables.get(table_name, [])), limit)
        return []

    def load_settings(self) -> dict[str, Any]:
        return self.authority.load_settings()

    @staticmethod
    def is_admin_user(row: dict[str, Any]) -> bool:
        username = str(row.get("username") or row.get("account") or row.get("帳號") or "").strip().lower()
        role = str(row.get("role_code") or row.get("role") or row.get("角色") or "").strip().lower()
        return username == "admin" or role == "admin"

    def health_check(self) -> RepositoryHealth:
        parts = [self.users_sqlite.health_check(), self.permission_sqlite.health_check(), self.authority.health_check()]
        users = self.list_users(limit=0)
        admin_count = sum(1 for row in users if self.is_admin_user(row))
        ok = any(p.ok for p in parts)
        return RepositoryHealth(
            name=self.name,
            ok=ok,
            source="facade",
            message="OK" if ok else "No permission source is available",
            row_count=len(users),
            details={
                "admin_user_count": admin_count,
                "sources": {p.name: p.as_dict() for p in parts},
            },
        )
