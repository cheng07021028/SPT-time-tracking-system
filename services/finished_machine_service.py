# -*- coding: utf-8 -*-
"""Finished machine / completed work-order authority service.

Module 16 owns the finished work-order list.  Page 01 uses the cached finished
work-order set to hide completed machines from the Work Order selector without
querying Neon for every dropdown render.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
import time

import pandas as pd

from services.db_service import (
    ensure_database,
    query_df,
    execute,
    execute_transaction,
    clear_query_cache,
    get_database_backend,
)

try:
    from services.timezone_service import now_text
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

FINISHED_MACHINE_COLS = [
    "_delete",
    "id",
    "work_order",
    "part_no",
    "type_name",
    "category",
    "assembly_location",
    "customer",
    "finished_date",
    "note",
    "is_active",
    "created_at",
    "updated_at",
]

FINISHED_DISPLAY_TO_INTERNAL = {
    "刪除 / Delete": "_delete",
    "ID / ID": "id",
    "製令 / Work Order": "work_order",
    "P/N / Part No.": "part_no",
    "機型 / Type": "type_name",
    "類別 / Category": "category",
    "Category / 類別": "category",
    "組立地點 / Assembly Location": "assembly_location",
    "客戶 / Customer": "customer",
    "完工日期 / Finished Date": "finished_date",
    "備註 / Note": "note",
    "啟用 / Active": "is_active",
    "建立時間 / Created At": "created_at",
    "更新時間 / Updated At": "updated_at",
}

_RUNTIME_SCHEMA_READY = False
_LOAD_CACHE_TTL_SECONDS = 180.0
_LOAD_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_FINISHED_SET_CACHE: tuple[float, set[str]] | None = None


def _now_ts() -> float:
    return time.time()


def _text(v: Any) -> str:
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v if v is not None else "").strip()


def _key(v: Any) -> str:
    return _text(v).upper()


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    text = _text(v).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選", "active"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否", "inactive"}:
        return False
    return bool(v)


def _int_or_none(v: Any) -> int | None:
    try:
        if _text(v) == "":
            return None
        return int(float(str(v)))
    except Exception:
        return None


def _date_text(v: Any) -> str:
    text = _text(v)
    if not text:
        return ""
    try:
        ts = pd.to_datetime(text, errors="coerce")
        if pd.notna(ts):
            return ts.strftime("%Y-%m-%d")
    except Exception:
        pass
    return text


def _column_exists(table: str, column: str) -> bool:
    try:
        info = query_df(f"PRAGMA table_info({table})", ())
        if isinstance(info, pd.DataFrame) and "name" in info.columns:
            return column in set(info["name"].astype(str))
    except Exception:
        pass
    try:
        df = query_df(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_name=? AND column_name=? LIMIT 1",
            (table, column),
        )
        return isinstance(df, pd.DataFrame) and not df.empty
    except Exception:
        return False


def _add_col(table: str, ddl: str) -> None:
    col = ddl.split()[0]
    if _column_exists(table, col):
        return
    try:
        execute(f"ALTER TABLE {table} ADD COLUMN {ddl}", ())
    except Exception:
        try:
            execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}", ())
        except Exception:
            pass


def ensure_finished_machine_table(force: bool = False) -> None:
    """Create/upgrade Module 16 table.  This is light and guarded per worker."""
    global _RUNTIME_SCHEMA_READY
    if _RUNTIME_SCHEMA_READY and not force:
        return
    ensure_database()
    try:
        backend = str(get_database_backend()).lower()
    except Exception:
        backend = ""
    if backend == "postgresql":
        create_sql = """
        CREATE TABLE IF NOT EXISTS finished_machines (
            id SERIAL PRIMARY KEY,
            work_order TEXT UNIQUE,
            part_no TEXT,
            type_name TEXT,
            category TEXT,
            assembly_location TEXT,
            customer TEXT,
            finished_date TEXT,
            note TEXT,
            is_active INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            deleted_at TEXT,
            deleted_by TEXT,
            delete_reason TEXT
        )
        """
    else:
        create_sql = """
        CREATE TABLE IF NOT EXISTS finished_machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_order TEXT UNIQUE,
            part_no TEXT,
            type_name TEXT,
            category TEXT,
            assembly_location TEXT,
            customer TEXT,
            finished_date TEXT,
            note TEXT,
            is_active INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            deleted_at TEXT,
            deleted_by TEXT,
            delete_reason TEXT
        )
        """
    try:
        execute(create_sql, ())
    except Exception:
        # Existing older database may have created the table through another path.
        pass
    for ddl in [
        "part_no TEXT",
        "type_name TEXT",
        "category TEXT",
        "assembly_location TEXT",
        "customer TEXT",
        "finished_date TEXT",
        "note TEXT",
        "is_active INTEGER DEFAULT 1",
        "active INTEGER DEFAULT 1",
        "created_at TEXT",
        "updated_at TEXT",
        "deleted_at TEXT",
        "deleted_by TEXT",
        "delete_reason TEXT",
    ]:
        _add_col("finished_machines", ddl)
    for stmt in [
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_finished_machines_work_order ON finished_machines(work_order)",
        "CREATE INDEX IF NOT EXISTS idx_finished_machines_active ON finished_machines(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_finished_machines_deleted_at ON finished_machines(deleted_at)",
    ]:
        try:
            execute(stmt, ())
        except Exception:
            pass
    _RUNTIME_SCHEMA_READY = True


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    work = work.rename(columns={c: FINISHED_DISPLAY_TO_INTERNAL.get(str(c), str(c)) for c in work.columns})
    aliases = {
        "製令": "work_order",
        "工單": "work_order",
        "製令號碼": "work_order",
        "Work Order": "work_order",
        "work order": "work_order",
        "P/N": "part_no",
        "PN": "part_no",
        "料號": "part_no",
        "品號": "part_no",
        "Part No": "part_no",
        "Part No.": "part_no",
        "機型": "type_name",
        "型號": "type_name",
        "機種": "type_name",
        "Type": "type_name",
        "Model": "type_name",
        "類別": "category",
        "分類": "category",
        "Category": "category",
        "category": "category",
        "組立地點": "assembly_location",
        "組裝地點": "assembly_location",
        "Assembly Location": "assembly_location",
        "客戶": "customer",
        "Customer": "customer",
        "完工日期": "finished_date",
        "完成日期": "finished_date",
        "Finished Date": "finished_date",
        "備註": "note",
        "Note": "note",
        "Remark": "note",
        "啟用": "is_active",
        "Active": "is_active",
    }
    work = work.rename(columns={c: aliases.get(str(c), str(c)) for c in work.columns})
    for c in FINISHED_MACHINE_COLS:
        if c not in work.columns:
            if c == "_delete":
                work[c] = False
            elif c == "is_active":
                work[c] = True
            else:
                work[c] = ""
    for c in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "created_at", "updated_at"]:
        if c in work.columns:
            work[c] = work[c].map(_text)
    if "finished_date" in work.columns:
        work["finished_date"] = work["finished_date"].map(_date_text)
    if "is_active" in work.columns:
        work["is_active"] = work["is_active"].map(lambda x: _bool(x, True)).astype(bool)
    if "_delete" in work.columns:
        work["_delete"] = work["_delete"].map(lambda x: _bool(x, False)).astype(bool)
    return work[FINISHED_MACHINE_COLS]


def _cached_df(key: str) -> pd.DataFrame | None:
    item = _LOAD_CACHE.get(key)
    if not item:
        return None
    ts, df = item
    if _now_ts() - ts > _LOAD_CACHE_TTL_SECONDS:
        _LOAD_CACHE.pop(key, None)
        return None
    return df.copy().reset_index(drop=True)


def _store_cached_df(key: str, df: pd.DataFrame) -> pd.DataFrame:
    cached = df.copy().reset_index(drop=True) if isinstance(df, pd.DataFrame) else pd.DataFrame()
    _LOAD_CACHE[key] = (_now_ts(), cached)
    return cached.copy().reset_index(drop=True)


def clear_finished_machine_cache() -> None:
    global _FINISHED_SET_CACHE
    _LOAD_CACHE.clear()
    _FINISHED_SET_CACHE = None
    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        from services.master_data_service import clear_time_record_master_fast_cache
        clear_time_record_master_fast_cache()
    except Exception:
        pass


def load_finished_machines(active_only: bool | None = None) -> pd.DataFrame:
    key = f"finished_machines::{active_only}"
    cached = _cached_df(key)
    if cached is not None:
        return cached
    ensure_finished_machine_table()
    df = query_df(
        """
        SELECT id, work_order, part_no, type_name, category, assembly_location, customer,
               finished_date, note, COALESCE(is_active, active, 1) AS is_active,
               created_at, updated_at
        FROM finished_machines
        WHERE deleted_at IS NULL OR deleted_at=''
        ORDER BY work_order
        """,
        (),
    )
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    df = _normalize(df)
    df["_delete"] = False
    if active_only is True and not df.empty:
        df = df[df["is_active"].map(lambda x: _bool(x, True))].copy()
    return _store_cached_df(key, df.reset_index(drop=True))


def load_finished_work_order_set(active_only: bool = True) -> set[str]:
    """Return cached completed work-order keys for 01 dropdown filtering."""
    global _FINISHED_SET_CACHE
    now = _now_ts()
    if _FINISHED_SET_CACHE is not None and now - _FINISHED_SET_CACHE[0] <= _LOAD_CACHE_TTL_SECONDS:
        return set(_FINISHED_SET_CACHE[1])
    try:
        df = load_finished_machines(active_only=active_only)
        keys = {_key(v) for v in df.get("work_order", pd.Series(dtype=str)).tolist() if _key(v)}
    except Exception:
        keys = set()
    _FINISHED_SET_CACHE = (now, keys)
    return set(keys)


def filter_open_work_orders_for_time_record(work_orders_df: pd.DataFrame) -> pd.DataFrame:
    """Hide completed work orders from page 01 with one cached set lookup.

    On any DB/settings error this returns the input unchanged, because preventing
    01 from starting work is worse than showing a completed order.
    """
    if not isinstance(work_orders_df, pd.DataFrame) or work_orders_df.empty or "work_order" not in work_orders_df.columns:
        return work_orders_df.copy() if isinstance(work_orders_df, pd.DataFrame) else pd.DataFrame()
    try:
        finished = load_finished_work_order_set(active_only=True)
        if not finished:
            out = work_orders_df.copy().reset_index(drop=True)
            out.attrs["finished_hidden_count"] = 0
            return out
        mask = ~work_orders_df["work_order"].map(lambda v: _key(v) in finished)
        out = work_orders_df.loc[mask].copy().reset_index(drop=True)
        out.attrs["finished_hidden_count"] = int((~mask).sum())
        return out
    except Exception:
        out = work_orders_df.copy().reset_index(drop=True)
        out.attrs["finished_hidden_count"] = 0
        return out


def _same_text(a: Any, b: Any) -> bool:
    return _text(a) == _text(b)


def save_finished_machines(df: pd.DataFrame) -> dict[str, Any]:
    """Persist Module 16 completed machine list through Neon/PostgreSQL authority."""
    ensure_finished_machine_table()
    work = _normalize(df)
    now = now_text()
    result = {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0}

    work = work[work["work_order"].map(_text) != ""].copy()
    if work.empty:
        return result
    # Keep the last row when the same work_order appears multiple times in paste/import.
    work["_wo_key"] = work["work_order"].map(_key)
    work = work.drop_duplicates(subset=["_wo_key"], keep="last").drop(columns=["_wo_key"]).reset_index(drop=True)

    try:
        existing_df = query_df(
            """
            SELECT id, work_order, part_no, type_name, category, assembly_location, customer,
                   finished_date, note, COALESCE(is_active, active, 1) AS is_active, deleted_at
            FROM finished_machines
            """,
            (),
        )
    except Exception:
        existing_df = pd.DataFrame()
    if not isinstance(existing_df, pd.DataFrame):
        existing_df = pd.DataFrame()

    existing_by_key: dict[str, dict[str, Any]] = {}
    for _, row in existing_df.iterrows() if not existing_df.empty else []:
        k = _key(row.get("work_order"))
        if k:
            existing_by_key[k] = row.to_dict()

    operations: list[tuple[str, Iterable[Any]]] = []
    for _, row in work.iterrows():
        wo = _text(row.get("work_order"))
        if not wo:
            result["skipped"] += 1
            continue
        key = _key(wo)
        old = existing_by_key.get(key, {})
        old_deleted = bool(_text(old.get("deleted_at"))) if old else False
        if _bool(row.get("_delete"), False):
            if old and not old_deleted:
                rid = _int_or_none(old.get("id"))
                if rid is not None:
                    operations.append((
                        "UPDATE finished_machines SET deleted_at=?, deleted_by='admin', delete_reason='16 完工機台刪除', updated_at=? WHERE id=? AND (deleted_at IS NULL OR deleted_at='')",
                        (now, now, rid),
                    ))
                else:
                    operations.append((
                        "UPDATE finished_machines SET deleted_at=?, deleted_by='admin', delete_reason='16 完工機台刪除', updated_at=? WHERE UPPER(TRIM(work_order))=UPPER(TRIM(?)) AND (deleted_at IS NULL OR deleted_at='')",
                        (now, now, wo),
                    ))
                result["deleted"] += 1
            else:
                result["skipped"] += 1
            continue

        payload = {
            "work_order": wo,
            "part_no": _text(row.get("part_no")),
            "type_name": _text(row.get("type_name")),
            "category": _text(row.get("category")),
            "assembly_location": _text(row.get("assembly_location")),
            "customer": _text(row.get("customer")),
            "finished_date": _date_text(row.get("finished_date")),
            "note": _text(row.get("note")),
            "is_active": 1 if _bool(row.get("is_active"), True) else 0,
        }
        changed = not old or old_deleted
        if old and not old_deleted:
            for col in ["part_no", "type_name", "category", "assembly_location", "customer", "finished_date", "note"]:
                if not _same_text(payload.get(col), old.get(col)):
                    changed = True
                    break
            if not changed and int(_bool(old.get("is_active"), True)) != int(bool(payload.get("is_active"))):
                changed = True
        if not changed:
            continue

        if old:
            result["updated"] += 1
            operations.append((
                """
                UPDATE finished_machines
                SET work_order=?, part_no=?, type_name=?, category=?, assembly_location=?, customer=?,
                    finished_date=?, note=?, is_active=?, active=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
                WHERE UPPER(TRIM(work_order))=UPPER(TRIM(?))
                """,
                (
                    payload["work_order"], payload["part_no"], payload["type_name"], payload["category"],
                    payload["assembly_location"], payload["customer"], payload["finished_date"], payload["note"],
                    payload["is_active"], payload["is_active"], now, wo,
                ),
            ))
        else:
            result["inserted"] += 1
            operations.append((
                """
                INSERT INTO finished_machines(
                    work_order, part_no, type_name, category, assembly_location, customer,
                    finished_date, note, is_active, active, created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    payload["work_order"], payload["part_no"], payload["type_name"], payload["category"],
                    payload["assembly_location"], payload["customer"], payload["finished_date"], payload["note"],
                    payload["is_active"], payload["is_active"], now, now,
                ),
            ))

    if operations:
        execute_transaction(
            operations,
            mark_changed=True,
            reason="16 完工機台批次儲存",
            source_sql="SAVE_FINISHED_MACHINES_BATCH",
        )
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, ?, ?, '', ?, '', 'INFO')",
            (now, "SYSTEM", "SAVE_FINISHED_MACHINES", "finished_machines", f"完工機台儲存 inserted={result['inserted']} updated={result['updated']} deleted={result['deleted']} skipped={result.get('skipped', 0)}"),
        )
    except Exception:
        pass
    clear_finished_machine_cache()
    return result


def make_delete_missing_rows(incoming: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Build soft-delete rows for current active finished orders missing from source."""
    inc = _normalize(incoming)
    cur = _normalize(current)
    incoming_keys = {_key(v) for v in inc.get("work_order", pd.Series(dtype=str)).tolist() if _key(v)}
    rows = []
    for _, row in cur.iterrows() if not cur.empty else []:
        wo = _text(row.get("work_order"))
        if wo and _key(wo) not in incoming_keys:
            r = row.to_dict()
            r["_delete"] = True
            rows.append(r)
    return _normalize(pd.DataFrame(rows)) if rows else _normalize(pd.DataFrame())
