# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import inspect
import json
from pathlib import Path
import pandas as pd

from services.timezone_service import now_text, now_stamp, today_text, today_date

from .db_service import execute, query_df
from .log_service import write_log


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERMANENT_STORE_DIR = PROJECT_ROOT / "data" / "permanent_store"
PERSISTENT_MODULES_DIR = PERMANENT_STORE_DIR / "persistent_modules"


def _load_persistent_module_rows(module_code: str, table_name: str) -> list[dict]:
    """Load rows from data/permanent_store/persistent_modules as a fast non-destructive fallback.

    模組更新後如果 SQLite 暫時為空，但 data/permanent_store/persistent_modules 仍有資料，
    01｜工時紀錄不應誤判成 03/04 沒資料。這裡只在讀取為空時使用，
    並回補到 SQLite，避免其他頁面/下拉選單讀不到主檔。
    """
    try:
        module_dir = PERSISTENT_MODULES_DIR / module_code
        file_path = module_dir / f"{module_code}_records.json"
        if not file_path.exists():
            return []
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
        rows = tables.get(table_name, [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _restore_work_orders_from_persistent() -> int:
    rows = _load_persistent_module_rows("03_work_orders", "work_orders")
    count = 0
    for row in rows:
        try:
            if upsert_work_order(dict(row or {})):
                count += 1
        except Exception:
            continue
    return count


def _restore_employees_from_persistent() -> int:
    rows = _load_persistent_module_rows("04_employees", "employees")
    count = 0
    for row in rows:
        try:
            if upsert_employee(dict(row or {})):
                count += 1
        except Exception:
            continue
    return count



# ===== V11 FAST MASTER DATA LATEST CACHE START =====
# Purpose:
# - 01｜工時紀錄 and 04｜人員名單 must load the newest permanent JSON after reboot.
# - Do not scan history or GitHub on every page open.
# - If SQLite has only 1 stale row but permanent JSON has 70~80 rows, merge the latest JSON into SQLite once.
_FAST_MASTER_RESTORE_DONE: set[str] = set()
_FAST_MASTER_JSON_CACHE: dict[str, tuple[float, list[dict]]] = {}

_MASTER_LATEST_MAP = {
    "work_orders": ("03_work_orders", "03_work_orders_records.json"),
    "employees": ("04_employees", "04_employees_records.json"),
}


def _extract_fast_rows(payload, table_name: str) -> list[dict]:
    if isinstance(payload, dict):
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        rows = tables.get(table_name)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        for key in ("records", "rows", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _fast_latest_rows(table_name: str) -> list[dict]:
    mod, fname = _MASTER_LATEST_MAP.get(table_name, ("", ""))
    if not mod:
        return []
    path = PERSISTENT_MODULES_DIR / mod / fname
    try:
        mtime = path.stat().st_mtime
    except Exception:
        return []
    cache = _FAST_MASTER_JSON_CACHE.get(str(path))
    if cache and cache[0] == mtime:
        return cache[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = _extract_fast_rows(payload, table_name)
        _FAST_MASTER_JSON_CACHE[str(path)] = (mtime, rows)
        return rows
    except Exception:
        return []


def _row_count_sql(table_name: str) -> int:
    try:
        row = query_one(f"SELECT COUNT(*) AS cnt FROM {table_name}")
        return int((row or {}).get("cnt") or 0)
    except Exception:
        return 0


def _restore_master_if_permanent_newer(table_name: str) -> int:
    # Once per process/table; keeps page open fast and avoids repeated write-through.
    if table_name in _FAST_MASTER_RESTORE_DONE:
        return 0
    _FAST_MASTER_RESTORE_DONE.add(table_name)
    rows = _fast_latest_rows(table_name)
    if not rows:
        return 0
    current = _row_count_sql(table_name)
    # Important: restore not only when DB is empty.  If DB has 1 old row but JSON has 80 rows,
    # merge the JSON so 04｜人員名單 and 01｜工時紀錄 do not show false missing data.
    if current >= len(rows):
        return 0
    count = 0
    try:
        from services.db_service import suspend_after_write_sync
    except Exception:
        suspend_after_write_sync = None
    def _do_restore():
        nonlocal count
        for row in rows:
            try:
                if table_name == "employees":
                    if upsert_employee(dict(row or {})):
                        count += 1
                elif table_name == "work_orders":
                    if upsert_work_order(dict(row or {})):
                        count += 1
            except Exception:
                continue
    if suspend_after_write_sync is not None:
        try:
            with suspend_after_write_sync(f"v11_fast_restore_{table_name}"):
                _do_restore()
        except Exception:
            _do_restore()
    else:
        _do_restore()
    return count
# ===== V11 FAST MASTER DATA LATEST CACHE END =====



# ===== V13 01 FAST OPEN MASTER DATA START =====
def _safe_bool_series(series) -> pd.Series:
    try:
        text = series.fillna("").astype(str).str.strip().str.lower()
        return text.isin({"1", "true", "yes", "y", "on", "啟用", "是"})
    except Exception:
        return pd.Series([], dtype=bool)


def _fast_master_df_from_latest_json(table_name: str) -> pd.DataFrame:
    """Return latest permanent master rows as DataFrame without restoring into SQLite.

    01｜工時紀錄只需要下拉選單資料，不應在開頁時把 03/04 主檔大量
    merge 回 SQLite。舊版在冷啟動或 DB 筆數少於 JSON 時會逐筆 upsert，
    製令很多時會讓 01 開頁超過數分鐘。
    """
    rows = _fast_latest_rows(table_name)
    if not rows:
        return pd.DataFrame()
    try:
        return pd.DataFrame(rows).fillna("")
    except Exception:
        return pd.DataFrame()


def _fast_master_df_from_sql(sql: str, params: list | tuple | None = None) -> pd.DataFrame:
    try:
        df = query_df(sql, list(params or []))
        if df is None:
            return pd.DataFrame()
        return df.fillna("")
    except Exception:
        return pd.DataFrame()


def _pick_fast_master_df(table_name: str, sql: str, params: list | tuple | None = None) -> pd.DataFrame:
    """Pick the larger/fresher source for fast opening, but do not write to DB."""
    sql_df = _fast_master_df_from_sql(sql, params)
    json_df = _fast_master_df_from_latest_json(table_name)
    if json_df.empty:
        return sql_df
    if sql_df.empty:
        return json_df
    # 若 permanent_store 有較完整資料，01 頁直接使用 JSON；避免等待 DB 修復。
    if len(json_df) > len(sql_df):
        return json_df
    return sql_df


def _filter_active_df(df: pd.DataFrame, active_only: bool = True, in_factory_only: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if active_only and "is_active" in out.columns:
        mask = _safe_bool_series(out["is_active"])
        # 若整欄不是 0/1/true/false 格式，不用誤殺資料。
        if mask.any():
            out = out[mask].copy()
    if in_factory_only and "is_in_factory" in out.columns:
        mask = _safe_bool_series(out["is_in_factory"])
        if mask.any():
            out = out[mask].copy()
    return out.fillna("")


def _sort_df(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if df is None or df.empty or by not in df.columns:
        return df if df is not None else pd.DataFrame()
    try:
        return df.sort_values(by=by, kind="stable").reset_index(drop=True)
    except Exception:
        return df.reset_index(drop=True)


def load_employees_for_time_record_fast(active_only: bool = True, in_factory_only: bool = False) -> pd.DataFrame:
    """Fast 01｜工時紀錄 employee dropdown loader.

    不改 04 人員名單正式儲存邏輯，只讓 01 頁開啟時直接讀最新記憶檔/SQLite
    中較完整者，避免冷啟動時逐筆還原造成超過 3 分鐘。
    """
    sql = "SELECT * FROM employees ORDER BY employee_id"
    df = _pick_fast_master_df("employees", sql)
    df = _filter_active_df(df, active_only=active_only, in_factory_only=in_factory_only)
    df = _sort_df(df, "employee_id")
    return _filter_employees_for_time_record(df)


def load_work_orders_for_time_record_fast(active_only: bool = True) -> pd.DataFrame:
    """Fast 01｜工時紀錄 work-order dropdown loader."""
    sql = "SELECT * FROM work_orders ORDER BY work_order"
    df = _pick_fast_master_df("work_orders", sql)
    df = _filter_active_df(df, active_only=active_only, in_factory_only=False)
    return _sort_df(df, "work_order")


def has_master_data_for_time_record_fast(employees_df: pd.DataFrame | None = None, work_orders_df: pd.DataFrame | None = None) -> tuple[bool, bool]:
    """Fast existence check for 01 page; never restores master rows inline."""
    emp_ok = employees_df is not None and not employees_df.empty
    wo_ok = work_orders_df is not None and not work_orders_df.empty
    if not emp_ok:
        emp_ok = bool(_fast_latest_rows("employees")) or _row_count_sql("employees") > 0
    if not wo_ok:
        wo_ok = bool(_fast_latest_rows("work_orders")) or _row_count_sql("work_orders") > 0
    return bool(emp_ok), bool(wo_ok)
# ===== V13 01 FAST OPEN MASTER DATA END =====

def _now() -> str:
    return now_text()


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
    _restore_master_if_permanent_newer("work_orders")
    sql = "SELECT * FROM work_orders"
    if active_only:
        sql += " WHERE is_active=1"
    sql += " ORDER BY work_order"
    df = query_df(sql)
    if not df.empty:
        return df

    # Fallback: if DB is temporarily empty after module update, recover from
    # persistent module JSON instead of showing a false "請先到 03/04 匯入資料" message.
    _restore_work_orders_from_persistent()
    return query_df(sql)


def load_employees(active_only: bool = True, in_factory_only: bool = False) -> pd.DataFrame:
    _restore_master_if_permanent_newer("employees")
    sql = "SELECT * FROM employees WHERE 1=1"
    params = []
    if active_only:
        sql += " AND is_active=1"
    if in_factory_only:
        sql += " AND is_in_factory=1"
    sql += " ORDER BY employee_id"
    df = query_df(sql, params)
    if df.empty:
        _restore_employees_from_persistent()
        df = query_df(sql, params)
    return _filter_employees_for_time_record(df)



def has_master_data_for_time_record() -> tuple[bool, bool]:
    """Fast raw master-data check for 01｜工時紀錄.

    V13: do not restore 03/04 master data inline during 01 page open.
    This keeps opening time under control while still recognizing permanent_store data.
    """
    return has_master_data_for_time_record_fast()

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
