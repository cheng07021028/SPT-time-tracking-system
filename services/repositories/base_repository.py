# -*- coding: utf-8 -*-
"""V164 repository base contracts.

This module is intentionally small and side-effect free.  It prepares the
project for a future PostgreSQL / SQL Server backend without changing the
current SQLite + authority JSON + event journal workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable


Row = dict[str, Any]
Rows = list[Row]


@dataclass(slots=True)
class RepositoryResult:
    """Small, serialisable operation result used by repository adapters."""

    ok: bool
    message: str = ""
    rows: int = 0
    data: Any = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "rows": self.rows,
            "data": self.data,
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class RepositoryHealth:
    """Read-only health status for a repository adapter."""

    name: str
    ok: bool
    source: str
    message: str = ""
    row_count: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "source": self.source,
            "message": self.message,
            "row_count": self.row_count,
            "details": dict(self.details),
            "errors": list(self.errors),
        }


@runtime_checkable
class ReadRepository(Protocol):
    """Minimal read contract for future DB-backed repositories."""

    name: str

    def list_rows(self, limit: int | None = None) -> Rows:
        ...

    def health_check(self) -> RepositoryHealth:
        ...


@runtime_checkable
class WriteRepository(ReadRepository, Protocol):
    """Optional write contract.  V164 keeps writes explicit and opt-in."""

    def save_rows(self, rows: Iterable[Row], *, reason: str = "repository_save", github: bool = False) -> RepositoryResult:
        ...


def clean_row(row: Any) -> Row:
    """Return a JSON-safe shallow copy of a row-like object."""
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)  # pandas Series / sqlite Row / mapping-like objects
    except Exception:
        return {}


def clean_rows(rows: Iterable[Any] | None) -> Rows:
    """Normalise any iterable of rows into list[dict]."""
    out: Rows = []
    for row in rows or []:
        r = clean_row(row)
        if r:
            out.append(r)
    return out


def trim_rows(rows: Rows, limit: int | None = None) -> Rows:
    if limit is None or int(limit) <= 0:
        return list(rows)
    return list(rows)[: int(limit)]
