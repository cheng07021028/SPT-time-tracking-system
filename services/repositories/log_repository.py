# -*- coding: utf-8 -*-
"""V164 LOG repository facade."""
from __future__ import annotations

from typing import Any

import pandas as pd

from .base_repository import RepositoryHealth, Rows, clean_rows, trim_rows
from .json_authority_repository import AuthorityRepository
from .sqlite_repository import SQLiteRepository


class LogRepository:
    name = "logs"

    def __init__(self) -> None:
        self.sqlite = SQLiteRepository("system_logs", name="logs_sqlite")
        self.authority = AuthorityRepository("06_logs", "system_logs", name="06_logs_authority")

    def list_logs(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        level: str | None = None,
        limit: int | None = 500,
    ) -> pd.DataFrame:
        if self.sqlite.table_exists():
            where: list[str] = []
            params: list[Any] = []
            if start_date:
                where.append("substr(log_time, 1, 10) >= ?")
                params.append(start_date)
            if end_date:
                where.append("substr(log_time, 1, 10) <= ?")
                params.append(end_date)
            if level:
                where.append("level = ?")
                params.append(level)
            sql = "SELECT * FROM system_logs"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY log_time DESC"
            if limit and int(limit) > 0:
                sql += f" LIMIT {int(limit)}"
            return self.sqlite.query_df(sql, tuple(params))
        rows = self.authority.list_rows(limit=limit)
        return pd.DataFrame(rows)

    def list_rows(self, limit: int | None = 500) -> Rows:
        try:
            return clean_rows(self.list_logs(limit=limit).to_dict("records"))
        except Exception:
            return trim_rows(self.authority.list_rows(), limit)

    def health_check(self) -> RepositoryHealth:
        parts = [self.sqlite.health_check(), self.authority.health_check()]
        ok = any(p.ok for p in parts)
        total = sum(int(p.row_count or 0) for p in parts)
        return RepositoryHealth(
            name=self.name,
            ok=ok,
            source="facade",
            message="OK" if ok else "No log source is available",
            row_count=total,
            details={p.name: p.as_dict() for p in parts},
        )
