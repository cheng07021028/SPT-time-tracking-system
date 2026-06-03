# -*- coding: utf-8 -*-
"""V63 consolidated CRUD service for master data.

This keeps the old page imports stable while removing local JSON/GitHub authority
from the 03/04 runtime path. All live reads/writes go through services.db_service.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

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
    return df[WORK_ORDER_COLS].reset_index(drop=True)


def load_employees() -> pd.DataFrame:
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
    return df[EMPLOYEE_COLS].reset_index(drop=True)


def _save_log(action_type: str, table: str, msg: str) -> None:
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, ?, ?, '', ?, '', 'INFO')",
            (now_text(), "SYSTEM", action_type, table, msg),
        )
    except Exception:
        pass


def save_work_orders(df: pd.DataFrame) -> dict[str, Any]:
    _ensure_runtime_columns()
    work = _normalize(df, WORK_ORDER_COLS, WO_DISPLAY_TO_INTERNAL)
    now = now_text()
    result = {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0}
    for _, row in work.iterrows():
        wo = _text(row.get("work_order"))
        if not wo:
            result["skipped"] += 1
            continue
        rid = _int_or_none(row.get("id"))
        if _bool(row.get("_delete")):
            if rid:
                result["deleted"] += execute("UPDATE work_orders SET deleted_at=?, deleted_by='admin', delete_reason='03 製令管理刪除', updated_at=? WHERE id=? AND (deleted_at IS NULL OR deleted_at='')", (now, now, rid))
            else:
                result["deleted"] += execute("UPDATE work_orders SET deleted_at=?, deleted_by='admin', delete_reason='03 製令管理刪除', updated_at=? WHERE work_order=? AND (deleted_at IS NULL OR deleted_at='')", (now, now, wo))
            continue
        payload = (
            wo, wo, _text(row.get("part_no")), _text(row.get("type_name")), _text(row.get("assembly_location")), _text(row.get("customer")), _text(row.get("note")),
            1 if _bool(row.get("is_active"), True) else 0, now,
        )
        if rid:
            execute(
                """
                UPDATE work_orders SET work_order=?, work_order_no=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, active=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
                WHERE id=?
                """,
                payload + (payload[7], rid,),
            )
            result["updated"] += 1
            continue
        existing = query_one("SELECT id FROM work_orders WHERE work_order=? LIMIT 1", (wo,))
        if existing:
            execute(
            """
            UPDATE work_orders SET work_order_no=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, active=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
            WHERE work_order=?
            """,
            (wo, payload[2], payload[3], payload[4], payload[5], payload[6], payload[7], payload[7], now, wo),
        )
            result["updated"] += 1
        else:
            execute(
                """
                INSERT INTO work_orders(work_order, work_order_no, part_no, type_name, assembly_location, customer, note, is_active, active, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (wo, wo, payload[2], payload[3], payload[4], payload[5], payload[6], payload[7], payload[7], now, now),
            )
            result["inserted"] += 1
    _save_log("SAVE_WORK_ORDERS", "work_orders", f"製令儲存 inserted={result['inserted']} updated={result['updated']} deleted={result['deleted']}")
    clear_query_cache()
    return result


def save_employees(df: pd.DataFrame) -> dict[str, Any]:
    _ensure_runtime_columns()
    work = _normalize(df, EMPLOYEE_COLS, EMP_DISPLAY_TO_INTERNAL)
    now = now_text()
    result = {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0}
    for _, row in work.iterrows():
        emp_id = _text(row.get("employee_id")); name = _text(row.get("employee_name"))
        if not emp_id or not name:
            result["skipped"] += 1
            continue
        rid = _int_or_none(row.get("id"))
        if _bool(row.get("_delete")):
            if rid:
                result["deleted"] += execute("UPDATE employees SET deleted_at=?, deleted_by='admin', delete_reason='04 人員名單刪除', updated_at=? WHERE id=? AND (deleted_at IS NULL OR deleted_at='')", (now, now, rid))
            else:
                result["deleted"] += execute("UPDATE employees SET deleted_at=?, deleted_by='admin', delete_reason='04 人員名單刪除', updated_at=? WHERE employee_id=? AND (deleted_at IS NULL OR deleted_at='')", (now, now, emp_id))
            continue
        vals = (
            emp_id, name, _text(row.get("department")), _text(row.get("title")),
            1 if _bool(row.get("is_active"), True) else 0,
            1 if _bool(row.get("is_in_factory"), True) else 0,
            1 if _bool(row.get("is_today_attendance"), True) else 0,
            _text(row.get("note")), now,
        )
        if rid:
            execute(
                """
                UPDATE employees SET employee_id=?, employee_name=?, department=?, title=?, is_active=?, active=?, is_in_factory=?, is_today_attendance=?, note=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
                WHERE id=?
                """,
                (vals[0], vals[1], vals[2], vals[3], vals[4], vals[4], vals[5], vals[6], vals[7], vals[8], rid),
            )
            result["updated"] += 1
            continue
        existing = query_one("SELECT id FROM employees WHERE employee_id=? LIMIT 1", (emp_id,))
        if existing:
            execute(
            """
            UPDATE employees SET employee_name=?, department=?, title=?, is_active=?, active=?, is_in_factory=?, is_today_attendance=?, note=?, updated_at=?, deleted_at='', deleted_by='', delete_reason=''
            WHERE employee_id=?
            """,
            (vals[1], vals[2], vals[3], vals[4], vals[4], vals[5], vals[6], vals[7], vals[8], emp_id),
        )
            result["updated"] += 1
        else:
            execute(
                """
                INSERT INTO employees(employee_id, employee_name, department, title, is_active, active, is_in_factory, is_today_attendance, note, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (vals[0], vals[1], vals[2], vals[3], vals[4], vals[4], vals[5], vals[6], vals[7], now, now),
            )
            result["inserted"] += 1
    _save_log("SAVE_EMPLOYEES", "employees", f"人員儲存 inserted={result['inserted']} updated={result['updated']} deleted={result['deleted']}")
    clear_query_cache()
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
    }
