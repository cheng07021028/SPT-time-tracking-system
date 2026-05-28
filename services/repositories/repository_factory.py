# -*- coding: utf-8 -*-
"""Factory for V164 repositories."""
from __future__ import annotations

from typing import Any

from .base_repository import RepositoryHealth
from .log_repository import LogRepository
from .permission_repository import PermissionRepository
from .settings_repository import SettingsRepository
from .time_record_repository import TimeRecordRepository


_REPOSITORY_CLASSES = {
    "time_records": TimeRecordRepository,
    "logs": LogRepository,
    "permissions": PermissionRepository,
    "settings": SettingsRepository,
}


def get_repository(name: str):
    key = str(name or "").strip().lower()
    if key not in _REPOSITORY_CLASSES:
        raise KeyError(f"unknown repository: {name}")
    return _REPOSITORY_CLASSES[key]()


def get_time_record_repository() -> TimeRecordRepository:
    return TimeRecordRepository()


def get_log_repository() -> LogRepository:
    return LogRepository()


def get_permission_repository() -> PermissionRepository:
    return PermissionRepository()


def get_settings_repository() -> SettingsRepository:
    return SettingsRepository()


def repository_health_report() -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in _REPOSITORY_CLASSES:
        try:
            health: RepositoryHealth = get_repository(name).health_check()
            report[name] = health.as_dict()
        except Exception as exc:
            report[name] = {
                "name": name,
                "ok": False,
                "source": "factory",
                "message": "repository health check failed",
                "errors": [repr(exc)],
            }
    report["overall_ok"] = all(bool(v.get("ok")) for k, v in report.items() if isinstance(v, dict))
    return report
