# -*- coding: utf-8 -*-
"""V164 repository configuration.

No runtime migration is performed here.  These mappings describe the existing
authority module keys and SQLite tables so later versions can swap the storage
engine behind a stable service boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"
SQLITE_DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
LEGACY_SQLITE_DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
DEFAULT_PREVIEW_LIMIT = 500


@dataclass(frozen=True, slots=True)
class RepositoryMapping:
    name: str
    module_key: str
    table_name: str
    sqlite_table: str
    description: str


REPOSITORY_MAPPINGS: dict[str, RepositoryMapping] = {
    "time_records": RepositoryMapping(
        name="time_records",
        module_key="02_history",
        table_name="time_records",
        sqlite_table="time_records",
        description="01/02 工時資料；正式交易仍由 time_record_service 控制。",
    ),
    "logs": RepositoryMapping(
        name="logs",
        module_key="06_logs",
        table_name="system_logs",
        sqlite_table="system_logs",
        description="06 LOG 查詢資料；高頻 LOG 仍維持批次 / 背景同步。",
    ),
    "permissions": RepositoryMapping(
        name="permissions",
        module_key="10_permissions",
        table_name="auth_users",
        sqlite_table="auth_users",
        description="10 權限管理資料；admin 限制仍由既有 security/permission service 判斷。",
    ),
    "settings": RepositoryMapping(
        name="settings",
        module_key="13_system_settings",
        table_name="process_options",
        sqlite_table="process_options",
        description="13 系統設定資料；設定永久保存仍走既有權威檔。",
    ),
}


def mapping_for(name: str) -> RepositoryMapping:
    key = str(name or "").strip().lower()
    if key not in REPOSITORY_MAPPINGS:
        raise KeyError(f"unknown repository mapping: {name}")
    return REPOSITORY_MAPPINGS[key]
