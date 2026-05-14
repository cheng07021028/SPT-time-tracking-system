# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import pandas as pd

from .db_service import execute, query_df
from .log_service import write_log


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_value(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _get_any(row: dict, keys: list[str]) -> str:
    # Direct match first.
    for key in keys:
        if key in row and _clean_value(row.get(key)):
            return _clean_value(row.get(key))

    # Case-insensitive / whitespace-normalized fallback.
    normalized = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        nk = str(key).strip().lower()
        if nk in normalized and _clean_value(normalized[nk]):
            return _clean_value(normalized[nk])
    return ""


def load_work_orders(active_only: bool = True) -> pd.DataFrame:
    sql = "SELECT * FROM work_orders"
    if active_only:
        sql += " WHERE is_active=1"
    sql += " ORDER BY work_order"
    return query_df(sql)


def load_employees(active_only: bool = True, in_factory_only: bool = False) -> pd.DataFrame:
    sql = "SELECT * FROM employees WHERE 1=1"
    params = []
    if active_only:
        sql += " AND is_active=1"
    if in_factory_only:
        sql += " AND is_in_factory=1"
    sql += " ORDER BY employee_id"
    return query_df(sql, params)


def upsert_work_order(row: dict) -> bool:
    now = _now()
    wo = _get_any(row, ["work_order", "製令", "工單", "工令", "製令號碼", "製令單號", "MO", "WO"])
    if not wo:
        return False

    execute(
        """
        INSERT INTO work_orders(work_order, part_no, type_name, assembly_location, customer, note, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(work_order) DO UPDATE SET
            part_no=excluded.part_no,
            type_name=excluded.type_name,
            assembly_location=excluded.assembly_location,
            customer=excluded.customer,
            note=excluded.note,
            is_active=1,
            updated_at=excluded.updated_at
        """,
        (
            wo,
            _get_any(row, ["part_no", "P/N", "PN", "料號", "品號", "物料編號"]),
            _get_any(row, ["type_name", "Type", "TYPE", "機型", "類型", "型號"]),
            _get_any(row, ["assembly_location", "組立地點", "組裝地點", "地點", "區域"]),
            _get_any(row, ["customer", "客戶", "客戶名稱"]),
            _get_any(row, ["note", "備註", "說明", "Remark", "remarks"]),
            now,
            now,
        ),
    )
    return True


def upsert_employee(row: dict) -> bool:
    now = _now()
    emp_id = _get_any(row, ["employee_id", "工號", "員工編號", "人員編號", "ID"])
    emp_name = _get_any(row, ["employee_name", "姓名", "人員", "員工姓名", "Name"])
    if not emp_id or not emp_name:
        return False

    execute(
        """
        INSERT INTO employees(employee_id, employee_name, department, title, is_active, is_in_factory, is_today_attendance, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, 1, ?, ?, ?)
        ON CONFLICT(employee_id) DO UPDATE SET
            employee_name=excluded.employee_name,
            department=excluded.department,
            title=excluded.title,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (
            emp_id,
            emp_name,
            _get_any(row, ["department", "單位", "部門", "課別"]),
            _get_any(row, ["title", "職稱", "職務"]),
            _get_any(row, ["note", "備註", "說明", "Remark", "remarks"]),
            now,
            now,
        ),
    )
    return True


def import_work_orders_df(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0

    count = 0
    df = df.fillna("")
    for _, r in df.iterrows():
        if upsert_work_order(dict(r)):
            count += 1
    write_log("IMPORT_WORK_ORDERS", f"匯入製令資料 {count} 筆", "work_orders")
    return count


def import_employees_df(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0

    count = 0
    df = df.fillna("")
    for _, r in df.iterrows():
        if upsert_employee(dict(r)):
            count += 1
    write_log("IMPORT_EMPLOYEES", f"匯入人員資料 {count} 筆", "employees")
    return count
