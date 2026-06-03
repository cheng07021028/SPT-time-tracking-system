# -*- coding: utf-8 -*-
"""SPT V164 repository preparation layer.

This package introduces repository facades without switching the live app away
from the existing services.  Current production writes still flow through the
same SQLite, permanent authority JSON, event journal, row shard and daily-close
guard logic.
"""
from __future__ import annotations

from .base_repository import RepositoryHealth, RepositoryResult
from .repository_factory import (
    get_log_repository,
    get_permission_repository,
    get_repository,
    get_settings_repository,
    get_time_record_repository,
    repository_health_report,
)

__all__ = [
    "RepositoryHealth",
    "RepositoryResult",
    "get_repository",
    "get_time_record_repository",
    "get_log_repository",
    "get_permission_repository",
    "get_settings_repository",
    "repository_health_report",
]
