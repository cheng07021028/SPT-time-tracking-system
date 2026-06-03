# -*- coding: utf-8 -*-
"""One-time legacy data importer for the original SPT UI on Neon.

This module intentionally imports data from a user-uploaded old project ZIP or
local legacy project folder into the current Neon/PostgreSQL database used by
services.db_service. It does not commit old company data to GitHub.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from services.db_service import ensure_database, is_postgres_enabled

LEGACY_TABLES = [
    "work_orders",
    "employees",
    "time_records",
    "system_logs",
    "rest_periods",
    "process_options",
    "system_settings",
    "table_column_settings",
    "table_sort_settings",
    "auth_users",
    "auth_account_permissions",
    "auth_login_logs",
    "auth_security_settings",
    "app_settings",
    "process_categories",
    "process_category_options",
    "process_model_options",
    "security_users",
    "security_roles",
    "security_user_roles",
    "security_module_permissions",
    "security_settings",
    "security_login_logs",
    "time_record_transaction_guard",
    "time_record_delete_tombstones",
]

CONFLICT_KEYS = {
    "work_orders": ("work_order",),
    "employees": ("employee_id",),
    "time_records": ("record_key",),
    "rest_periods": ("id",),
    "process_options": ("process_name",),
    "system_settings": ("setting_key",),
    "table_column_settings": ("page_key", "table_key", "column_key"),
    "table_sort_settings": ("page_key", "table_key"),
    "auth_users": ("username",),
    "auth_account_permissions": ("username", "module_code"),
    "auth_security_settings": ("setting_key",),
    "app_settings": ("setting_key",),
    "process_categories": ("category_name",),
    "process_category_options": ("category_name", "process_name"),
    "process_model_options": ("model_name",),
    "security_users": ("username",),
    "security_roles": ("role_code",),
    "security_user_roles": ("username", "role_code"),
    "security_module_permissions": ("role_code", "module_code"),
    "security_settings": ("setting_key",),
    "time_record_transaction_guard": ("op_key",),
}


def _pg_dsn() -> str:
    from services import db_service as _db
    fn = getattr(_db, "_v25_postgres_dsn", None)
    if callable(fn):
        return str(fn() or "")
    for key in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL", "NEON_DATABASE_URL", "DB_URL"):
        val = os.environ.get(key)
        if val:
            return str(val)
    return ""


def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row
    dsn = _pg_dsn()
    if not dsn:
        raise RuntimeError("找不到 DATABASE_URL / Neon 連線字串。請先在 Streamlit Secrets 設定。")
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=15)


def _clean(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.hex()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip() if isinstance(value, str) else value
    if isinstance(text, str) and text.lower() in {"", "none", "nan", "nat", "null", "<na>"}:
        return None
    return text


def _extract_source(source_path: str | Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.is_dir():
        return path, None
    tmp = tempfile.TemporaryDirectory(prefix="spt_legacy_import_")
    root = Path(tmp.name)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            zf.extractall(root)
        return root, tmp
    raise ValueError("請上傳舊專案 ZIP，或指定舊專案資料夾。")


def _find_legacy_db(root: Path) -> Path | None:
    candidates = list(root.rglob("spt_time_tracking.db"))
    if not candidates:
        candidates = list(root.rglob("*.db"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: ("permanent_store" not in str(p), len(str(p))))
    return candidates[0]


def _sqlite_tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(r[0]) for r in rows}


def _sqlite_read_rows(db_path: Path, table: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        except Exception:
            return []
    return [dict(r) for r in rows]


def _pg_columns(cur, table: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return [str(r.get("column_name")) for r in cur.fetchall()]


def _normalize_aliases(table: str, row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    if table == "work_orders":
        if not r.get("work_order") and r.get("work_order_no"):
            r["work_order"] = r.get("work_order_no")
        if not r.get("work_order_no") and r.get("work_order"):
            r["work_order_no"] = r.get("work_order")
        if r.get("is_active") is None and r.get("active") is not None:
            r["is_active"] = r.get("active")
        if r.get("active") is None and r.get("is_active") is not None:
            r["active"] = r.get("is_active")
    elif table == "employees":
        if r.get("is_active") is None and r.get("active") is not None:
            r["is_active"] = r.get("active")
        if r.get("active") is None and r.get("is_active") is not None:
            r["active"] = r.get("is_active")
    elif table == "time_records":
        if not r.get("work_order") and r.get("work_order_no"):
            r["work_order"] = r.get("work_order_no")
        if not r.get("work_order_no") and r.get("work_order"):
            r["work_order_no"] = r.get("work_order")
        if not r.get("process_code") and r.get("process_name"):
            r["process_code"] = r.get("process_name")
        if not r.get("process_name") and r.get("process_code"):
            r["process_name"] = r.get("process_code")
        if not r.get("start_timestamp"):
            d = r.get("start_date") or r.get("work_date") or ""
            t = r.get("start_time") or "00:00:00"
            r["start_timestamp"] = f"{d} {t}".strip() if d else None
        if not r.get("end_timestamp") and r.get("end_time"):
            d = r.get("end_date") or r.get("start_date") or r.get("work_date") or ""
            r["end_timestamp"] = f"{d} {r.get('end_time')}".strip() if d else None
        if r.get("work_hours") is None:
            minutes = r.get("work_minutes") or r.get("raw_minutes") or r.get("average_minutes")
            try:
                r["work_hours"] = float(minutes) / 60.0 if minutes is not None else 0.0
            except Exception:
                r["work_hours"] = 0.0
    return r


def _upsert_rows(cur, table: str, rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    columns = _pg_columns(cur, table)
    if not columns:
        return 0, len(rows)
    conflict = CONFLICT_KEYS.get(table, ())
    inserted = 0
    skipped = 0
    for raw in rows:
        row = _normalize_aliases(table, raw)
        clean = {c: _clean(row.get(c)) for c in columns if c in row}
        clean = {k: v for k, v in clean.items() if v is not None}
        if not clean:
            skipped += 1
            continue
        cols = list(clean.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        values = tuple(clean[c] for c in cols)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        usable_conflict = tuple(c for c in conflict if c in cols and clean.get(c) is not None)
        if usable_conflict:
            update_cols = [c for c in cols if c not in usable_conflict]
            if update_cols:
                set_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
                sql += f" ON CONFLICT ({', '.join(usable_conflict)}) DO UPDATE SET {set_sql}"
            else:
                sql += f" ON CONFLICT ({', '.join(usable_conflict)}) DO NOTHING"
        else:
            sql += " ON CONFLICT DO NOTHING"
        try:
            cur.execute("SAVEPOINT spt_import_row")
            cur.execute(sql, values)
            cur.execute("RELEASE SAVEPOINT spt_import_row")
            inserted += 1
        except Exception:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT spt_import_row")
                cur.execute("RELEASE SAVEPOINT spt_import_row")
            except Exception:
                pass
            skipped += 1
    return inserted, skipped


def _json_module_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Fallback import from permanent_store/modules records.json if no SQLite DB exists."""
    base = root
    matches = list(root.rglob("data/permanent_store/modules"))
    if matches:
        base = matches[0]
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in LEGACY_TABLES}
    plan = [
        ("03_work_orders", "work_orders"),
        ("04_employees", "employees"),
        ("01_time_records", "time_records"),
        ("02_history", "time_records"),
        ("06_logs", "system_logs"),
        ("10_permissions", "auth_users"),
        ("10_permissions", "auth_account_permissions"),
        ("10_permissions", "auth_security_settings"),
        ("11_login_logs", "security_login_logs"),
        ("13_system_settings", "process_options"),
        ("13_system_settings", "rest_periods"),
    ]
    for module, table in plan:
        path = base / module / "records.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = []
        if isinstance(payload, list):
            rows = [x for x in payload if isinstance(x, dict)]
        elif isinstance(payload, dict):
            tables = payload.get("tables") or {}
            if isinstance(tables, dict) and isinstance(tables.get(table), list):
                rows = [x for x in tables.get(table, []) if isinstance(x, dict)]
        out.setdefault(table, []).extend(rows)
    return out


def migrate_legacy_source_to_neon(source_path: str | Path) -> dict[str, Any]:
    if not is_postgres_enabled():
        raise RuntimeError("目前不是 Neon/PostgreSQL 模式。請先設定 DATABASE_URL。")
    ensure_database()
    root, tmp = _extract_source(source_path)
    try:
        db_path = _find_legacy_db(root)
        per_table: dict[str, dict[str, int]] = {}
        with _pg_connect() as conn:
            with conn.cursor() as cur:
                if db_path:
                    available = _sqlite_tables(db_path)
                    for table in LEGACY_TABLES:
                        if table not in available:
                            continue
                        rows = _sqlite_read_rows(db_path, table)
                        inserted, skipped = _upsert_rows(cur, table, rows)
                        per_table[table] = {"read": len(rows), "imported_or_updated": inserted, "skipped": skipped}
                else:
                    rows_by_table = _json_module_rows(root)
                    for table, rows in rows_by_table.items():
                        inserted, skipped = _upsert_rows(cur, table, rows)
                        if rows:
                            per_table[table] = {"read": len(rows), "imported_or_updated": inserted, "skipped": skipped}
            conn.commit()
        return {
            "ok": True,
            "source": str(source_path),
            "sqlite_db_found": str(db_path) if db_path else "",
            "tables": per_table,
            "total_read": sum(x.get("read", 0) for x in per_table.values()),
            "total_imported_or_updated": sum(x.get("imported_or_updated", 0) for x in per_table.values()),
            "total_skipped": sum(x.get("skipped", 0) for x in per_table.values()),
        }
    finally:
        if tmp is not None:
            tmp.cleanup()


def save_uploaded_zip_and_migrate(uploaded_file) -> dict[str, Any]:
    suffix = ".zip"
    with tempfile.NamedTemporaryFile(prefix="spt_legacy_upload_", suffix=suffix, delete=False) as f:
        f.write(uploaded_file.getbuffer())
        path = Path(f.name)
    try:
        return migrate_legacy_source_to_neon(path)
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
