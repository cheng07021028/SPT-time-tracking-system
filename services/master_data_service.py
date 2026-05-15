# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import inspect
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


def _called_from_time_record_page() -> bool:
    """V1.64: Detect 01｜工時紀錄 page without requiring page-file rename.

    This lets us keep all existing page functionality while restricting the employee
    dropdown for normal operators only on the time-recording page.
    """
    try:
        for frame in inspect.stack()[:18]:
            name = str(frame.filename).replace("\\", "/").lower()
            if "/pages/" in name and ("01_01" in name or "01_time" in name or "time_record" in name):
                return True
    except Exception:
        pass
    return False


def _current_login_context() -> tuple[str, str, list[str]]:
    try:
        import streamlit as st
        username = str(st.session_state.get("auth_username", "") or "").strip()
        employee_id = str(st.session_state.get("auth_employee_id", "") or "").strip()
        roles = st.session_state.get("auth_roles", []) or []
        if isinstance(roles, str):
            roles = [roles]
        return username, employee_id, [str(r).strip() for r in roles]
    except Exception:
        return "", "", []


def _set_employee_binding_required(required: bool, username: str = "") -> None:
    """Store 01｜工時紀錄 employee-binding status for the page message.

    Do not show all employees when an operator account is not mapped to a valid
    employee_id.  The page will display:「該人員未在人員名單，請洽管理員設定。」
    """
    try:
        import streamlit as st
        st.session_state["_spt_employee_binding_required"] = bool(required)
        if username:
            st.session_state["_spt_employee_binding_username"] = username
    except Exception:
        pass


def _filter_employees_for_time_record(df: pd.DataFrame) -> pd.DataFrame:
    """Filter employee dropdown on 01｜工時紀錄 without exposing all employees.

    V1.64 曾將 operator 限制成只能看到自己的工號；但如果帳號尚未綁定
    employee_id，或帳號名稱如 spt142 不存在於人員名單，01 頁會被誤判成
    「請先匯入 03 / 04」，即使製令與人員資料其實都已存在。

    V1.80 修正：
    1. 管理類角色維持可看全部。
    2. operator 若能對應到工號/姓名，仍只顯示本人。
    3. operator 若無法對應，不再顯示全部人員，也不再誤判 03/04 未匯入；
       改由 01 頁顯示「該人員未在人員名單，請洽管理員設定。」
    """
    _set_employee_binding_required(False)
    if df is None or df.empty or not _called_from_time_record_page():
        return df

    username, employee_id, roles = _current_login_context()
    role_set = {r.lower() for r in roles}
    if role_set.intersection({"admin", "manager", "leader"}):
        return df

    target = employee_id or username

    def _block_unbound_account() -> pd.DataFrame:
        _set_employee_binding_required(True, username)
        return df.iloc[0:0].copy()

    if not target:
        return _block_unbound_account()

    if "employee_id" in df.columns:
        employee_id_series = df["employee_id"].fillna("").astype(str).str.strip().str.lower()
        mask = employee_id_series == target.lower()
        if mask.any():
            _set_employee_binding_required(False)
            return df[mask].copy()

        # Common account/user input may be lowercase while employee master is uppercase.
        # Also support account like spt142 vs employee_id SPT142.
        if username:
            mask = employee_id_series == username.lower()
            if mask.any():
                _set_employee_binding_required(False)
                return df[mask].copy()

    try:
        import streamlit as st
        display_name = str(st.session_state.get("auth_display_name", "") or "").strip()
        if display_name and "employee_name" in df.columns:
            mask = df["employee_name"].fillna("").astype(str).str.strip() == display_name
            if mask.any():
                _set_employee_binding_required(False)
                return df[mask].copy()
    except Exception:
        pass

    return _block_unbound_account()


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
    df = query_df(sql, params)
    return _filter_employees_for_time_record(df)


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


def save_work_orders_df(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    count = 0
    now = _now()
    for _, r in df.iterrows():
        if pd.isna(r.get("id")):
            continue
        execute(
            """
            UPDATE work_orders
            SET work_order=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, updated_at=?
            WHERE id=?
            """,
            (
                _clean_value(r.get("work_order")),
                _clean_value(r.get("part_no")),
                _clean_value(r.get("type_name")),
                _clean_value(r.get("assembly_location")),
                _clean_value(r.get("customer")),
                _clean_value(r.get("note")),
                int(bool(r.get("is_active"))),
                now,
                int(r.get("id")),
            ),
        )
        count += 1
    write_log("SAVE_WORK_ORDERS", f"人工編輯並儲存製令資料 {count} 筆", "work_orders")
    return count


def save_employees_df(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    count = 0
    now = _now()
    for _, r in df.iterrows():
        if pd.isna(r.get("id")):
            continue
        execute(
            """
            UPDATE employees
            SET employee_id=?, employee_name=?, department=?, title=?, is_active=?, is_in_factory=?, is_today_attendance=?, note=?, updated_at=?
            WHERE id=?
            """,
            (
                _clean_value(r.get("employee_id")),
                _clean_value(r.get("employee_name")),
                _clean_value(r.get("department")),
                _clean_value(r.get("title")),
                int(bool(r.get("is_active"))),
                int(bool(r.get("is_in_factory"))),
                int(bool(r.get("is_today_attendance"))),
                _clean_value(r.get("note")),
                now,
                int(r.get("id")),
            ),
        )
        count += 1
    write_log("SAVE_EMPLOYEES", f"人工編輯並儲存人員資料 {count} 筆", "employees")
    return count
