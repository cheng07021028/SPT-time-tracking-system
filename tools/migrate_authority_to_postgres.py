# -*- coding: utf-8 -*-
"""Import permanent authority JSON into PostgreSQL.

Usage:
    set DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB
    python tools/migrate_authority_to_postgres.py

The app keeps SQLite as a fallback when DATABASE_URL is absent.  This script is
only needed once when moving existing data to PostgreSQL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.db_service import ensure_database, execute, is_postgres_enabled, query_df, query_one

MODULE_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"

IMPORT_PLAN: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("03_work_orders", "work_orders", "work_orders", ("work_order",)),
    ("04_employees", "employees", "employees", ("employee_id",)),
    ("01_time_records", "time_records", "time_records", ("record_key",)),
    ("02_history", "time_records", "time_records", ("record_key",)),
    ("06_logs", "system_logs", "system_logs", ("id",)),
    ("10_permissions", "auth_users", "auth_users", ("username",)),
    ("10_permissions", "auth_account_permissions", "auth_account_permissions", ("username", "module_code")),
    ("10_permissions", "auth_security_settings", "auth_security_settings", ("setting_key",)),
    ("10_permissions", "security_settings", "security_settings", ("setting_key",)),
    ("10_permissions", "security_users", "security_users", ("username",)),
    ("10_permissions", "security_user_roles", "security_user_roles", ("username", "role_code")),
    ("13_system_settings", "process_categories", "process_categories", ("category_name",)),
    ("13_system_settings", "process_category_options", "process_category_options", ("category_name", "process_name")),
    ("13_system_settings", "process_options", "process_options", ("process_name",)),
    ("13_system_settings", "rest_periods", "rest_periods", ("id",)),
    ("13_system_settings", "app_settings", "app_settings", ("setting_key",)),
]


def _load_rows(module_key: str, table_name: str) -> list[dict[str, Any]]:
    path = MODULE_ROOT / module_key / "records.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(r) for r in payload if isinstance(r, dict)]
    tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
    rows = tables.get(table_name, [])
    return [dict(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _table_columns(table_name: str) -> list[str]:
    df = query_df(f"PRAGMA table_info({table_name})")
    if df is None or df.empty or "name" not in df.columns:
        return []
    return [str(x) for x in df["name"].tolist()]


def _clean_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "nan", "nat", "null", "<na>"}:
        return None
    return value


def _coerce_row(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in columns:
        if col not in row:
            continue
        value = _clean_value(row.get(col))
        if col == "id" and value is not None:
            try:
                value = int(float(str(value)))
            except Exception:
                value = None
        if col in {"is_active", "is_in_factory", "is_today_attendance", "is_group_work", "sort_order"} and value is not None:
            text = str(value).strip().lower()
            if text in {"true", "yes", "y", "是", "啟用"}:
                value = 1
            elif text in {"false", "no", "n", "否", "停用"}:
                value = 0
            else:
                try:
                    value = int(float(text))
                except Exception:
                    value = 0
        if col == "work_hours" and value is not None:
            try:
                value = float(value)
            except Exception:
                value = 0.0
        if value is not None:
            out[col] = value
    return out


def _choose_conflict(row: dict[str, Any], preferred: tuple[str, ...]) -> tuple[str, ...]:
    if preferred and all(str(row.get(c, "")).strip() for c in preferred):
        return preferred
    if row.get("id") is not None:
        return ("id",)
    return preferred


def _upsert_rows(table_name: str, rows: list[dict[str, Any]], conflict_cols: tuple[str, ...]) -> int:
    columns = _table_columns(table_name)
    if not columns:
        raise RuntimeError(f"PostgreSQL table not found or has no columns: {table_name}")
    count = 0
    for raw in rows:
        row = _coerce_row(raw, columns)
        conflict = _choose_conflict(row, conflict_cols)
        if not row or not conflict or not all(c in row for c in conflict):
            continue
        cols = [c for c in columns if c in row]
        placeholders = ", ".join(["?"] * len(cols))
        col_sql = ", ".join(cols)
        update_cols = [c for c in cols if c not in conflict]
        if update_cols:
            update_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
            sql = f"INSERT INTO {table_name} ({col_sql}) VALUES ({placeholders}) ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {update_sql}"
        else:
            sql = f"INSERT INTO {table_name} ({col_sql}) VALUES ({placeholders}) ON CONFLICT ({', '.join(conflict)}) DO NOTHING"
        execute(sql, tuple(row.get(c) for c in cols))
        count += 1
    return count


def _sync_identity(table_name: str) -> None:
    try:
        query_one(
            f"""
            SELECT setval(pg_get_serial_sequence('{table_name}', 'id'),
                          GREATEST(COALESCE((SELECT MAX(id) FROM {table_name}), 1), 1),
                          true) AS seq
            """
        )
    except Exception:
        pass


def main() -> int:
    if not is_postgres_enabled():
        print("DATABASE_URL / POSTGRES_URL is not configured; PostgreSQL migration skipped.")
        return 2
    ensure_database()
    totals: dict[str, int] = {}
    for module_key, source_table, target_table, conflict in IMPORT_PLAN:
        rows = _load_rows(module_key, source_table)
        if not rows:
            continue
        n = _upsert_rows(target_table, rows, conflict)
        totals[target_table] = totals.get(target_table, 0) + n
        _sync_identity(target_table)
        print(f"{module_key}.{source_table} -> {target_table}: {n}")
    print("Migration complete.")
    for table, count in sorted(totals.items()):
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
