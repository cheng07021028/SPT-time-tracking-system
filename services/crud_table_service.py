# -*- coding: utf-8 -*-
"""V63 consolidated CRUD service for master data.

This keeps the old page imports stable while removing local JSON/GitHub authority
from the 03/04 runtime path. All live reads/writes go through services.db_service.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
import time

import pandas as pd

from services.db_service import ensure_database, query_df, query_one, execute, execute_transaction, clear_query_cache, get_database_backend
try:
    from services.timezone_service import now_text
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

WORK_ORDER_COLS = ["_delete", "id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
EMPLOYEE_COLS = ["_delete", "id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]

WO_DISPLAY_TO_INTERNAL = {
    "刪除 / Delete": "_delete", "ID / ID": "id", "製令 / Work Order": "work_order", "P/N / Part No.": "part_no",
    "機型 / Type": "type_name", "組立地點 / Assembly Location": "assembly_location", "客戶 / Customer": "customer",
    "備註 / Note": "note", "啟用 / Active": "is_active", "建立時間 / Created At": "created_at", "更新時間 / Updated At": "updated_at",
}
EMP_DISPLAY_TO_INTERNAL = {
    "刪除 / Delete": "_delete", "ID / ID": "id", "工號 / Employee ID": "employee_id", "姓名 / Name": "employee_name",
    "單位 / Department": "department", "職稱 / Title": "title", "啟用 / Active": "is_active", "在廠 / In Factory": "is_in_factory",
    "今日出勤 / Today Attendance": "is_today_attendance", "備註 / Note": "note", "建立時間 / Created At": "created_at", "更新時間 / Updated At": "updated_at",
}

# V68: schema checks are expensive on Neon/PostgreSQL because every check can
# open a remote connection. 03/04 pages call load_* on many reruns, so keep this
# migration guard process-local and run it only once per worker.
_RUNTIME_COLUMNS_READY = False

# V69: page switches and every Streamlit widget rerun used to re-query 03/04
# master data from Neon.  Master tables are small and only change through this
# service, so keep a short process-local cache and clear it immediately on save.
_LOAD_CACHE_TTL_SECONDS = 180.0
_LOAD_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}


def _cached_df(key: str) -> pd.DataFrame | None:
    item = _LOAD_CACHE.get(key)
    if not item:
        return None
    ts, df = item
    if time.time() - ts > _LOAD_CACHE_TTL_SECONDS:
        _LOAD_CACHE.pop(key, None)
        return None
    return df.copy().reset_index(drop=True)


def _store_cached_df(key: str, df: pd.DataFrame) -> pd.DataFrame:
    cached = df.copy().reset_index(drop=True) if isinstance(df, pd.DataFrame) else pd.DataFrame()
    _LOAD_CACHE[key] = (time.time(), cached)
    return cached.copy().reset_index(drop=True)


def clear_master_data_cache() -> None:
    _LOAD_CACHE.clear()


def _text(v: Any) -> str:
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v if v is not None else "").strip()


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    text = _text(v).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否"}:
        return False
    return bool(v)


def _int_or_none(v: Any) -> int | None:
    try:
        if _text(v) == "":
            return None
        return int(float(str(v)))
    except Exception:
        return None




def _column_exists(table: str, column: str) -> bool:
    try:
        info = query_df(f"PRAGMA table_info({table})", ())
        if isinstance(info, pd.DataFrame) and "name" in info.columns:
            return column in set(info["name"].astype(str))
    except Exception:
        pass
    try:
        df = query_df("SELECT column_name AS name FROM information_schema.columns WHERE table_name=? AND column_name=? LIMIT 1", (table, column))
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


def _ensure_runtime_columns(force: bool = False) -> None:
    global _RUNTIME_COLUMNS_READY
    if _RUNTIME_COLUMNS_READY and not force:
        return
    ensure_database()
    for ddl in ["work_order_no TEXT", "customer TEXT", "active INTEGER DEFAULT 1", "deleted_at TEXT", "deleted_by TEXT", "delete_reason TEXT"]:
        _add_col("work_orders", ddl)
    for ddl in ["active INTEGER DEFAULT 1", "is_in_factory INTEGER DEFAULT 1", "is_today_attendance INTEGER DEFAULT 1", "deleted_at TEXT", "deleted_by TEXT", "delete_reason TEXT"]:
        _add_col("employees", ddl)
    _RUNTIME_COLUMNS_READY = True


def ensure_tables() -> None:
    _ensure_runtime_columns(force=True)


def _normalize(df: pd.DataFrame | None, cols: list[str], mapping: dict[str, str]) -> pd.DataFrame:
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if work.empty:
        return pd.DataFrame(columns=cols)
    work = work.rename(columns={c: mapping.get(str(c), str(c)) for c in work.columns})
    aliases = {
        "製令": "work_order", "工單": "work_order", "工號": "employee_id", "姓名": "employee_name",
        "部門": "department", "單位": "department", "備註": "note", "啟用": "is_active", "在廠": "is_in_factory", "今日出勤": "is_today_attendance",
    }
    work = work.rename(columns={c: aliases.get(str(c), str(c)) for c in work.columns})
    for c in cols:
        if c not in work.columns:
            work[c] = False if c == "_delete" else ""
    return work[cols]


def load_work_orders() -> pd.DataFrame:
    cached = _cached_df("work_orders")
    if cached is not None:
        return cached
    _ensure_runtime_columns()
    df = query_df(
        """
        SELECT id, work_order, part_no, type_name, assembly_location, customer, note,
               COALESCE(is_active, active, 1) AS is_active, created_at, updated_at
        FROM work_orders
        WHERE deleted_at IS NULL OR deleted_at=''
        ORDER BY work_order
        """,
        (),
    )
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    for c in WORK_ORDER_COLS:
        if c not in df.columns:
            df[c] = False if c == "_delete" else ""
    df["_delete"] = False
    df["is_active"] = df["is_active"].map(lambda x: _bool(x, True))
    return _store_cached_df("work_orders", df[WORK_ORDER_COLS].reset_index(drop=True))


def load_employees() -> pd.DataFrame:
    cached = _cached_df("employees")
    if cached is not None:
        return cached
    _ensure_runtime_columns()
    df = query_df(
        """
        SELECT id, employee_id, employee_name, department, title,
               COALESCE(is_active, active, 1) AS is_active,
               COALESCE(is_in_factory, 1) AS is_in_factory,
               COALESCE(is_today_attendance, 1) AS is_today_attendance,
               note, created_at, updated_at
        FROM employees
        WHERE deleted_at IS NULL OR deleted_at=''
        ORDER BY employee_id
        """,
        (),
    )
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    for c in EMPLOYEE_COLS:
        if c not in df.columns:
            df[c] = False if c == "_delete" else ""
    df["_delete"] = False
    for c in ["is_active", "is_in_factory", "is_today_attendance"]:
        df[c] = df[c].map(lambda x: _bool(x, True))
    return _store_cached_df("employees", df[EMPLOYEE_COLS].reset_index(drop=True))


def _save_log(action_type: str, table: str, msg: str) -> None:
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, ?, ?, '', ?, '', 'INFO')",
            (now_text(), "SYSTEM", action_type, table, msg),
        )
    except Exception:
        pass


def save_work_orders(df: pd.DataFrame) -> dict[str, Any]:
    """Persist 03 work orders through the Neon/PostgreSQL authority table.

    V300.28: keep the public behavior of the old row-by-row save, but remove
    the expensive hot path that did one SELECT plus one write per row.  Large
    paste/Excel/OneDrive imports now read existing keys once, then write all
    changes in one transaction.  This reduces Neon compute and connection churn
    without changing UI behavior, soft-delete rules, or reboot durability.
    """
    _ensure_runtime_columns()
    work = _normalize(df, WORK_ORDER_COLS, WO_DISPLAY_TO_INTERNAL)
    now = now_text()
    result = {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0}

    try:
        existing_df = query_df("SELECT id, work_order FROM work_orders", ())
    except Exception:
        existing_df = pd.DataFrame()
    if not isinstance(existing_df, pd.DataFrame):
        existing_df = pd.DataFrame()

    existing_by_wo: dict[str, int] = {}
    existing_by_id: set[int] = set()
    if not existing_df.empty:
        for _, old in existing_df.iterrows():
            old_id = _int_or_none(old.get("id"))
            old_wo = _text(old.get("work_order"))
            if old_id is not None:
                existing_by_id.add(old_id)
            if old_wo and old_id is not None and old_wo not in existing_by_wo:
                existing_by_wo[old_wo] = old_id

    operations: list[tuple[str, Iterable[Any]]] = []
    for _, row in work.iterrows():
        wo = _text(row.get("work_order"))
        if not wo:
            result["skipped"] += 1
            continue
        rid = _int_or_none(row.get("id"))

        if _bool(row.get("_delete")):
            if rid:
                operations.append((
                    "UPDATE work_orders SET deleted_at=?, deleted_by='admin', delete_reason='03 製令管理刪除', updated_at=? WHERE id=? AND (deleted_at IS NULL OR deleted_at='')",
                    (now, now, rid),
                ))
                if rid in existing_by_id:
                    result["deleted"] += 1
            else:
                operations.append((
                    "UPDATE work_orders SET deleted_at=?, deleted_by='admin', delete_reason='03 製令管理刪除', updated_at=? WHERE work_order=? AND (deleted_at IS NULL OR deleted_at='')",
                    (now, now, wo),
                ))
                if wo in existing_by_wo:
                    result["deleted"] += 1
            continue

        part_no = _text(row.get("part_no"))
        type_name = _text(row.get("type_name"))
        assembly_location = _text(row.get("assembly_location"))
        customer = _text(row.get("customer"))
        note = _text(row.get("note"))
        active_val = 1 if _bool(row.get("is_active"), True) else 0

        if rid:
            operations.append((
                """
                UPDATE work_orders SET work_order=?, work_order_no=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, active=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
                WHERE id=?
                """,
                (wo, wo, part_no, type_name, assembly_location, customer, note, active_val, active_val, now, rid),
            ))
            result["updated"] += 1
            existing_by_wo[wo] = rid
            existing_by_id.add(rid)
            continue

        if wo in existing_by_wo:
            operations.append((
                """
                UPDATE work_orders SET work_order_no=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, active=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
                WHERE work_order=?
                """,
                (wo, part_no, type_name, assembly_location, customer, note, active_val, active_val, now, wo),
            ))
            result["updated"] += 1
        else:
            operations.append((
                """
                INSERT INTO work_orders(work_order, work_order_no, part_no, type_name, assembly_location, customer, note, is_active, active, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (wo, wo, part_no, type_name, assembly_location, customer, note, active_val, active_val, now, now),
            ))
            result["inserted"] += 1
            # Preserve old row-order semantics for duplicated work_order values in
            # the same import: first row inserts, later rows update that key.
            existing_by_wo[wo] = -1

    if operations:
        execute_transaction(
            operations,
            mark_changed=True,
            reason="03 製令管理批次儲存",
            source_sql="SAVE_WORK_ORDERS_BATCH",
        )
    _save_log("SAVE_WORK_ORDERS", "work_orders", f"製令儲存 inserted={result['inserted']} updated={result['updated']} deleted={result['deleted']}")
    clear_query_cache()
    clear_master_data_cache()
    return result


def save_employees(df: pd.DataFrame) -> dict[str, Any]:
    """Persist 04 employee master data through the Neon/PostgreSQL authority table.

    V300.56: harden the V300.29 batch path against PostgreSQL UniqueViolation.
    The previous fast path still built plain INSERT statements after a pre-read
    of existing employee_id values. If a duplicate employee_id existed in the
    editor payload, or another Streamlit session inserted the same employee_id
    between the pre-read and the transaction, PostgreSQL could raise
    psycopg.errors.UniqueViolation and crash the page. This version keeps the
    same UI and authority rules, but writes non-deleted rows through an atomic
    INSERT ... ON CONFLICT(employee_id) DO UPDATE path and de-duplicates the
    incoming payload before opening the transaction.
    """
    _ensure_runtime_columns()
    work = _normalize(df, EMPLOYEE_COLS, EMP_DISPLAY_TO_INTERNAL)
    now = now_text()
    result = {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0}

    try:
        existing_df = query_df("SELECT id, employee_id FROM employees", ())
    except Exception:
        existing_df = pd.DataFrame()
    if not isinstance(existing_df, pd.DataFrame):
        existing_df = pd.DataFrame()

    existing_by_emp: dict[str, int] = {}
    existing_emp_by_id: dict[int, str] = {}
    existing_by_id: set[int] = set()
    if not existing_df.empty:
        for _, old in existing_df.iterrows():
            old_id = _int_or_none(old.get("id"))
            old_emp = _text(old.get("employee_id"))
            if old_id is not None:
                existing_by_id.add(old_id)
                existing_emp_by_id[old_id] = old_emp
            if old_emp and old_id is not None and old_emp not in existing_by_emp:
                existing_by_emp[old_emp] = old_id

    # V300.56: last-row-wins de-duplication before DB writes. This prevents a
    # single save click from generating several INSERT/UPDATE operations for the
    # same employee_id and also matches the existing paste/import behavior.
    staged: dict[str, dict[str, Any]] = {}
    staged_order: list[str] = []
    for _, row in work.iterrows():
        emp_id = _text(row.get("employee_id"))
        name = _text(row.get("employee_name"))
        rid = _int_or_none(row.get("id"))
        delete_flag = _bool(row.get("_delete"))
        if not emp_id and not rid:
            result["skipped"] += 1
            continue
        if not delete_flag and (not emp_id or not name):
            result["skipped"] += 1
            continue
        key = emp_id or f"__id__{rid}"
        if key not in staged:
            staged_order.append(key)
        staged[key] = {"row": row, "rid": rid, "emp_id": emp_id, "delete": delete_flag}

    operations: list[tuple[str, Iterable[Any]]] = []
    for key in staged_order:
        item = staged[key]
        row = item["row"]
        rid = item["rid"]
        emp_id = item["emp_id"]

        if item["delete"]:
            if rid:
                operations.append((
                    "UPDATE employees SET deleted_at=?, deleted_by='admin', delete_reason='04 人員名單刪除', updated_at=? WHERE id=? AND (deleted_at IS NULL OR deleted_at='')",
                    (now, now, rid),
                ))
                if rid in existing_by_id:
                    result["deleted"] += 1
            elif emp_id:
                operations.append((
                    "UPDATE employees SET deleted_at=?, deleted_by='admin', delete_reason='04 人員名單刪除', updated_at=? WHERE employee_id=? AND (deleted_at IS NULL OR deleted_at='')",
                    (now, now, emp_id),
                ))
                if emp_id in existing_by_emp:
                    result["deleted"] += 1
            else:
                result["skipped"] += 1
            continue

        name = _text(row.get("employee_name"))
        department = _text(row.get("department"))
        title = _text(row.get("title"))
        active_val = 1 if _bool(row.get("is_active"), True) else 0
        factory_val = 1 if _bool(row.get("is_in_factory"), True) else 0
        today_val = 1 if _bool(row.get("is_today_attendance"), True) else 0
        note = _text(row.get("note"))

        # If the user edits an existing row's employee_id, preserve that row when
        # the new employee_id is not already used. If it is already used by a
        # different row, skip instead of crashing with UniqueViolation.
        old_emp_for_id = existing_emp_by_id.get(rid) if rid else None
        if rid and old_emp_for_id and old_emp_for_id != emp_id:
            conflict_id = existing_by_emp.get(emp_id)
            if conflict_id is not None and conflict_id != rid:
                result["skipped"] += 1
                continue
            operations.append((
                """
                UPDATE employees SET employee_id=?, employee_name=?, department=?, title=?, is_active=?, active=?, is_in_factory=?, is_today_attendance=?, note=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
                WHERE id=?
                """,
                (emp_id, name, department, title, active_val, active_val, factory_val, today_val, note, now, rid),
            ))
            result["updated"] += 1
            existing_by_emp.pop(old_emp_for_id, None)
            existing_by_emp[emp_id] = rid
            existing_emp_by_id[rid] = emp_id
            continue

        # V300.56: atomic upsert. This handles existing rows, soft-deleted rows,
        # duplicate paste rows after staging, and concurrent inserts from another
        # browser/session without surfacing UniqueViolation to the user.
        operations.append((
            """
            INSERT INTO employees(employee_id, employee_name, department, title, is_active, active, is_in_factory, is_today_attendance, note, created_at, updated_at, deleted_at, deleted_by, delete_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '')
            ON CONFLICT(employee_id) DO UPDATE SET
                employee_name=excluded.employee_name,
                department=excluded.department,
                title=excluded.title,
                is_active=excluded.is_active,
                active=excluded.active,
                is_in_factory=excluded.is_in_factory,
                is_today_attendance=excluded.is_today_attendance,
                note=excluded.note,
                updated_at=excluded.updated_at,
                deleted_at='',
                deleted_by='',
                delete_reason=''
            """,
            (emp_id, name, department, title, active_val, active_val, factory_val, today_val, note, now, now),
        ))
        if emp_id in existing_by_emp:
            result["updated"] += 1
        else:
            result["inserted"] += 1
            existing_by_emp[emp_id] = -1

    if operations:
        execute_transaction(
            operations,
            mark_changed=True,
            reason="04 人員名單批次儲存",
            source_sql="SAVE_EMPLOYEES_BATCH_V30056_UPSERT",
        )
    _save_log("SAVE_EMPLOYEES", "employees", f"人員儲存 inserted={result['inserted']} updated={result['updated']} deleted={result['deleted']} skipped={result['skipped']}")
    clear_query_cache()
    clear_master_data_cache()
    return result


class _CursorProxy:
    rowcount: int = 0
    def execute(self, sql: str, params: Iterable[Any] | None = None):
        self.rowcount = int(execute(sql, tuple(params or ())) or 0)
        return self


class _ConnProxy:
    def cursor(self):
        return _CursorProxy()
    def commit(self):
        return None
    def close(self):
        return None


def get_conn():
    # Compatibility for pages that used sqlite cursor. New runtime should prefer load/save functions.
    return _ConnProxy()


def audit_v63_crud_runtime_consolidated() -> dict[str, Any]:
    return {
        "version": "V63_CRUD_RUNTIME_CONSOLIDATED",
        "backend": get_database_backend(),
        "work_orders_authority": "db_service/neon",
        "employees_authority": "db_service/neon",
        "local_json_write_on_save": False,
        "github_write_on_save": False,
        "load_cache_ttl_seconds": _LOAD_CACHE_TTL_SECONDS,
    }
