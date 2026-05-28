# -*- coding: utf-8 -*-
"""Authority JSON adapter for V164 repository preparation."""
from __future__ import annotations

from typing import Any, Iterable

from .base_repository import RepositoryHealth, RepositoryResult, Rows, clean_rows, trim_rows


class AuthorityRepository:
    """Thin adapter around services.permanent_authority_service.

    Writes are explicit and keep github=False by default in this V164 layer so
    repository smoke tests never trigger slow cloud uploads by accident.
    """

    def __init__(self, module_key: str, table_name: str, *, name: str | None = None) -> None:
        self.module_key = str(module_key)
        self.table_name = str(table_name)
        self.name = name or f"authority:{self.module_key}:{self.table_name}"

    @staticmethod
    def _svc():
        from services import permanent_authority_service

        return permanent_authority_service

    def load_tables(self) -> dict[str, Rows]:
        tables = self._svc().load_tables(self.module_key, kind="records")
        return {str(k): clean_rows(v) for k, v in (tables or {}).items()}

    def list_rows(self, limit: int | None = None) -> Rows:
        rows = self.load_tables().get(self.table_name, [])
        return trim_rows(rows, limit)

    def save_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        reason: str = "v164_repository_save",
        github: bool = False,
    ) -> RepositoryResult:
        try:
            tables = self.load_tables()
            cleaned = clean_rows(rows)
            tables[self.table_name] = cleaned
            result = self._svc().save_authority(self.module_key, records=tables, reason=reason, github=github)
            return RepositoryResult(
                ok=bool(result.get("ok", True)) if isinstance(result, dict) else True,
                message="authority rows saved",
                rows=len(cleaned),
                data=result,
            )
        except Exception as exc:
            return RepositoryResult(ok=False, message="authority save failed", errors=[repr(exc)])

    def load_settings(self) -> dict[str, Any]:
        try:
            settings = self._svc().load_settings(self.module_key)
            return settings if isinstance(settings, dict) else {}
        except Exception:
            return {}

    def save_settings(
        self,
        settings: dict[str, Any],
        *,
        reason: str = "v164_repository_save_settings",
        github: bool = False,
    ) -> RepositoryResult:
        try:
            result = self._svc().save_settings(self.module_key, dict(settings or {}), reason=reason, github=github)
            return RepositoryResult(ok=True, message="authority settings saved", rows=1, data=result)
        except Exception as exc:
            return RepositoryResult(ok=False, message="authority settings save failed", errors=[repr(exc)])

    def health_check(self) -> RepositoryHealth:
        try:
            tables = self.load_tables()
            rows = tables.get(self.table_name, [])
            return RepositoryHealth(
                name=self.name,
                ok=True,
                source="authority_json",
                message="OK",
                row_count=len(rows),
                details={
                    "module_key": self.module_key,
                    "table_name": self.table_name,
                    "available_tables": sorted(tables.keys()),
                },
            )
        except Exception as exc:
            return RepositoryHealth(
                name=self.name,
                ok=False,
                source="authority_json",
                message="authority health check failed",
                errors=[repr(exc)],
                details={"module_key": self.module_key, "table_name": self.table_name},
            )
