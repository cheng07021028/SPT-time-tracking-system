# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
import pandas as pd
from .db_service import execute, query_df
from .log_service import write_log


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def upsert_work_order(row: dict) -> None:
    now = _now()
    wo = str(row.get("work_order") or row.get("製令") or "").strip()
    if not wo:
        return
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
            row.get("part_no") or row.get("P/N") or row.get("料號") or "",
            row.get("type_name") or row.get("Type") or row.get("機型") or "",
            row.get("assembly_location") or row.get("組立地點") or "",
            row.get("customer") or row.get("客戶") or "",
            row.get("note") or row.get("備註") or "",
            now,
            now,
        ),
    )


def upsert_employee(row: dict) -> None:
    now = _now()
    emp_id = str(row.get("employee_id") or row.get("工號") or "").strip()
    emp_name = str(row.get("employee_name") or row.get("姓名") or "").strip()
    if not emp_id or not emp_name:
        return
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
            row.get("department") or row.get("單位") or "",
            row.get("title") or row.get("職稱") or "",
            row.get("note") or row.get("備註") or "",
            now,
            now,
        ),
    )


def import_work_orders_df(df: pd.DataFrame) -> int:
    count = 0
    for _, r in df.fillna("").iterrows():
        before = count
        upsert_work_order(dict(r))
        count = before + 1
    write_log("IMPORT_WORK_ORDERS", f"匯入製令資料 {count} 筆", "work_orders")
    return count


def import_employees_df(df: pd.DataFrame) -> int:
    count = 0
    for _, r in df.fillna("").iterrows():
        upsert_employee(dict(r))
        count += 1
    write_log("IMPORT_EMPLOYEES", f"匯入人員資料 {count} 筆", "employees")
    return count
