from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from .config import AUTHORITY_DIR, CAPACITY_WORKBOOK, ORG_WORKBOOK
from .excel_parser import bootstrap_authority_from_excel
from .persistent_store import load_authority_df, save_authority_df
from .schema_service import DEFAULT_SCHEMAS

REQUIRED_TABLES = [
    "employees",
    "dispatch",
    "schedule",
    "standard_hours",
    "work_calendar",
    "capacity_summary_excel",
    "capacity_adjustments",
    "users",
    "role_permissions",
    "module_notes",
]


@st.cache_data(ttl=600, show_spinner=False)
def read_authority_table(name: str, modified_time: float | None = None) -> pd.DataFrame:
    # modified_time 是 cache bust key，不直接使用。
    return load_authority_df(name)


def _mtime_for_table(name: str) -> float | None:
    path = AUTHORITY_DIR / f"{name}.json"
    return path.stat().st_mtime if path.exists() else None


def load_table(name: str) -> pd.DataFrame:
    return read_authority_table(name, _mtime_for_table(name))


def _ensure_empty_authority_tables() -> dict[str, int]:
    created: dict[str, int] = {}
    for name, columns in DEFAULT_SCHEMAS.items():
        path = AUTHORITY_DIR / f"{name}.json"
        if not path.exists():
            save_authority_df(name, pd.DataFrame(columns=columns), user="auto_schema")
            created[name] = 0
    return created


def ensure_bootstrap() -> dict[str, int] | None:
    missing_core = [name for name in ["employees", "dispatch", "schedule", "standard_hours", "work_calendar", "capacity_summary_excel"] if not (AUTHORITY_DIR / f"{name}.json").exists()]
    result: dict[str, int] = {}
    if missing_core and ORG_WORKBOOK.exists() and CAPACITY_WORKBOOK.exists():
        result.update(bootstrap_authority_from_excel())
    result.update(_ensure_empty_authority_tables())
    return result or None


def load_all_tables() -> dict[str, pd.DataFrame]:
    ensure_bootstrap()
    return {name: load_table(name) for name in REQUIRED_TABLES}


def clear_data_cache() -> None:
    read_authority_table.clear()


def source_file_status() -> pd.DataFrame:
    files = [ORG_WORKBOOK, CAPACITY_WORKBOOK]
    rows: list[dict[str, Any]] = []
    for path in files:
        rows.append({
            "檔名": path.name,
            "存在": path.exists(),
            "大小KB": round(path.stat().st_size / 1024, 1) if path.exists() else 0,
            "路徑": str(path),
        })
    return pd.DataFrame(rows)
