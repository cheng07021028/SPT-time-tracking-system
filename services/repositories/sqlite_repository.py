# -*- coding: utf-8 -*-
"""SQLite adapter for V164 repository preparation.

The adapter delegates to services.db_service so existing schema repair, WAL,
timezone and cache-clearing behaviour remains unchanged.
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .base_repository import RepositoryHealth, RepositoryResult, Rows, clean_rows


class SQLiteRepository:
    """Thin adapter around services.db_service."""

    def __init__(self, table_name: str, *, name: str | None = None) -> None:
        self.table_name = str(table_name)
        self.name = name or f"sqlite:{self.table_name}"

    @staticmethod
    def _db():
        from services import db_service

        return db_service

    def query_df(self, sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
        return self._db().query_df(sql, tuple(params or ()))

    def query_one(self, sql: str, params: Iterable[Any] | None = None) -> dict[str, Any] | None:
        return self._db().query_one(sql, tuple(params or ()))

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> int:
        return int(self._db().execute(sql, tuple(params or ())) or 0)

    def table_exists(self) -> bool:
        row = self.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (self.table_name,),
        )
        return bool(row)

    def table_columns(self) -> list[str]:
        if not self.table_exists():
            return []
        try:
            df = self.query_df(f"PRAGMA table_info({self.table_name})")
            if "name" in df.columns:
                return [str(x) for x in df["name"].dropna().tolist()]
        except Exception:
            return []
        return []

    def count_rows(self) -> int:
        if not self.table_exists():
            return 0
        row = self.query_one(f"SELECT COUNT(*) AS cnt FROM {self.table_name}") or {}
        try:
            return int(row.get("cnt", 0) or 0)
        except Exception:
            return 0

    def list_rows(self, limit: int | None = 500) -> Rows:
        if not self.table_exists():
            return []
        safe_limit = int(limit or 0)
        sql = f"SELECT * FROM {self.table_name}"
        if safe_limit > 0:
            sql += f" LIMIT {safe_limit}"
        df = self.query_df(sql)
        return clean_rows(df.to_dict("records"))

    def health_check(self) -> RepositoryHealth:
        try:
            exists = self.table_exists()
            count = self.count_rows() if exists else 0
            columns = self.table_columns() if exists else []
            return RepositoryHealth(
                name=self.name,
                ok=exists,
                source="sqlite",
                message="OK" if exists else f"SQLite table not found: {self.table_name}",
                row_count=count,
                details={"table": self.table_name, "columns": columns[:80]},
            )
        except Exception as exc:
            return RepositoryHealth(
                name=self.name,
                ok=False,
                source="sqlite",
                message="SQLite health check failed",
                errors=[repr(exc)],
                details={"table": self.table_name},
            )

    def execute_many_transaction(
        self,
        operations: list[tuple[str, Iterable[Any]]],
        *,
        reason: str = "repository_transaction",
        mark_changed: bool = True,
    ) -> RepositoryResult:
        try:
            db = self._db()
            if hasattr(db, "execute_transaction"):
                ids = db.execute_transaction(
                    operations,
                    mark_changed=mark_changed,
                    reason=reason,
                    source_sql=reason,
                )
                return RepositoryResult(ok=True, message="transaction committed", rows=len(ids), data=ids)
            ids = []
            for sql, params in operations:
                ids.append(self.execute(sql, tuple(params or ())))
            return RepositoryResult(ok=True, message="operations committed", rows=len(ids), data=ids)
        except Exception as exc:
            return RepositoryResult(ok=False, message="transaction failed", errors=[repr(exc)])
