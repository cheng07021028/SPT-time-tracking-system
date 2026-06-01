# -*- coding: utf-8 -*-
"""V164 system settings repository facade."""
from __future__ import annotations

from typing import Any

from .base_repository import RepositoryHealth, RepositoryResult, Rows, clean_rows, trim_rows
from .json_authority_repository import AuthorityRepository
from .sqlite_repository import SQLiteRepository


class SettingsRepository:
    name = "settings"

    def __init__(self) -> None:
        self.process_sqlite = SQLiteRepository("process_options", name="settings_process_options_sqlite")
        self.rest_sqlite = SQLiteRepository("rest_periods", name="settings_rest_periods_sqlite")
        self.authority = AuthorityRepository("13_system_settings", "process_options", name="13_system_settings_authority")

    def list_process_options(self, limit: int | None = 1000) -> Rows:
        if self.process_sqlite.table_exists():
            return self.process_sqlite.list_rows(limit=limit)
        tables = self.authority.load_tables()
        for table_name in ("process_options", "process_category_options"):
            if table_name in tables:
                return trim_rows(clean_rows(tables.get(table_name, [])), limit)
        return []

    def list_rest_periods(self, limit: int | None = 1000) -> Rows:
        if self.rest_sqlite.table_exists():
            return self.rest_sqlite.list_rows(limit=limit)
        tables = self.authority.load_tables()
        return trim_rows(clean_rows(tables.get("rest_periods", [])), limit)

    def load_settings(self) -> dict[str, Any]:
        return self.authority.load_settings()

    def save_settings(
        self,
        settings: dict[str, Any],
        *,
        reason: str = "v164_settings_repository_save",
        github: bool = False,
    ) -> RepositoryResult:
        return self.authority.save_settings(settings, reason=reason, github=github)

    def health_check(self) -> RepositoryHealth:
        parts = [self.process_sqlite.health_check(), self.rest_sqlite.health_check(), self.authority.health_check()]
        process_rows = self.list_process_options(limit=0)
        rest_rows = self.list_rest_periods(limit=0)
        ok = any(p.ok for p in parts)
        return RepositoryHealth(
            name=self.name,
            ok=ok,
            source="facade",
            message="OK" if ok else "No settings source is available",
            row_count=len(process_rows) + len(rest_rows),
            details={
                "process_option_count": len(process_rows),
                "rest_period_count": len(rest_rows),
                "sources": {p.name: p.as_dict() for p in parts},
            },
        )
