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
PERSISTENT_MODULES_DIR = PROJECT_ROOT / "data" / "persistent_modules"


def _load_persistent_module_rows(module_code: str, table_name: str) -> list[dict]:
    """Load rows from data/persistent_modules as a non-destructive fallback.

    模組更新後如果 SQLite 暫時為空，但 data/persistent_modules 仍有資料，
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




# ========================= V28 Permanent Authority Overrides =========================
# 核心原則：03/04 主檔讀寫以 data/permanent_store/modules/<module>/records.json 為唯一權威。
# SQLite 僅為快取；開頁讀取不掃 history、不跑 GitHub、不做大量 restore。
try:
    from services.permanent_authority_service import df_from_table as _v28_df_from_table, update_tables as _v28_update_tables, table_from_df as _v28_table_from_df
except Exception:  # pragma: no cover
    _v28_df_from_table = _v28_update_tables = _v28_table_from_df = None  # type: ignore

def _v28_bool_series(df, col):
    if col in df.columns:
        return df[col].astype(str).str.lower().str.strip().isin(["1","true","yes","y","是","啟用","在廠","出勤"]) | (df[col] == 1) | (df[col] == True)
    return None

def load_work_orders(active_only: bool = True) -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    if _v28_df_from_table is not None:
        df = _v28_df_from_table("03_work_orders", "work_orders", columns=cols)
        if df is not None and not df.empty:
            if active_only:
                mask = _v28_bool_series(df, "is_active")
                if mask is not None: df = df[mask]
            return df.sort_values("work_order", kind="stable").reset_index(drop=True)
    sql = "SELECT * FROM work_orders" + (" WHERE is_active=1" if active_only else "") + " ORDER BY work_order"
    return query_df(sql)

def load_employees(active_only: bool = True, in_factory_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    if _v28_df_from_table is not None:
        df = _v28_df_from_table("04_employees", "employees", columns=cols)
        if df is not None and not df.empty:
            if active_only:
                mask = _v28_bool_series(df, "is_active")
                if mask is not None: df = df[mask]
            if in_factory_only:
                mask = _v28_bool_series(df, "is_in_factory")
                if mask is not None: df = df[mask]
            return _filter_employees_for_time_record(df.sort_values("employee_id", kind="stable").reset_index(drop=True))
    sql = "SELECT * FROM employees WHERE 1=1"
    if active_only: sql += " AND is_active=1"
    if in_factory_only: sql += " AND is_in_factory=1"
    sql += " ORDER BY employee_id"
    return _filter_employees_for_time_record(query_df(sql))

def save_work_orders_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    rows = _v28_table_from_df(df) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("03_work_orders", {"work_orders": rows}, reason="save_work_orders_df_v28")
    # SQLite cache update is best effort only.
    try:
        execute("DELETE FROM work_orders")
        for r in rows:
            upsert_work_order(r)
    except Exception:
        pass
    write_log("SAVE_WORK_ORDERS", f"V28 權威檔儲存製令 {len(rows)} 筆", "work_orders")
    return len(rows)

def save_employees_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    rows = _v28_table_from_df(df) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("04_employees", {"employees": rows}, reason="save_employees_df_v28")
    try:
        execute("DELETE FROM employees")
        for r in rows:
            upsert_employee(r)
    except Exception:
        pass
    write_log("SAVE_EMPLOYEES", f"V28 權威檔儲存人員 {len(rows)} 筆", "employees")
    return len(rows)

def import_work_orders_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    old = load_work_orders(active_only=False)
    work = pd.concat([old, df.fillna("")], ignore_index=True) if old is not None and not old.empty else df.fillna("")
    if "work_order" in work.columns:
        work = work.drop_duplicates(subset=["work_order"], keep="last")
    return save_work_orders_df(work)

def import_employees_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    old = load_employees(active_only=False, in_factory_only=False)
    work = pd.concat([old, df.fillna("")], ignore_index=True) if old is not None and not old.empty else df.fillna("")
    if "employee_id" in work.columns:
        work = work.drop_duplicates(subset=["employee_id"], keep="last")
    return save_employees_df(work)

# ===== V35 master data compatibility wrappers =====
def load_employees_for_time_record_fast(active_only: bool = True, in_factory_only: bool = False):
    """Compatibility wrapper for 01｜工時紀錄.

    Keeps the page import stable while using the existing employee loader.
    """
    return load_employees(active_only=active_only, in_factory_only=in_factory_only)


def load_work_orders_for_time_record_fast(active_only: bool = True):
    """Compatibility wrapper for 01｜工時紀錄.

    Keeps the page import stable while using the existing work-order loader.
    """
    return load_work_orders(active_only=active_only)


def has_master_data_for_time_record_fast(employees=None, work_orders=None):
    """Return master-data availability for 01｜工時紀錄.

    Supports both current page usage:
        has_employees_master, has_work_orders_master = has_master_data_for_time_record_fast(employees, work_orders)

    and diagnostic usage:
        has_master_data_for_time_record_fast()
    """
    try:
        emp_df = employees if employees is not None else load_employees_for_time_record_fast(active_only=True, in_factory_only=False)
    except Exception:
        emp_df = None
    try:
        wo_df = work_orders if work_orders is not None else load_work_orders_for_time_record_fast(active_only=True)
    except Exception:
        wo_df = None

    has_emp = bool(emp_df is not None and hasattr(emp_df, "empty") and not emp_df.empty)
    has_wo = bool(wo_df is not None and hasattr(wo_df, "empty") and not wo_df.empty)

    if employees is None and work_orders is None:
        return {
            "has_employees_master": has_emp,
            "has_work_orders_master": has_wo,
            "employees_count": int(len(emp_df)) if emp_df is not None and hasattr(emp_df, "__len__") else 0,
            "work_orders_count": int(len(wo_df)) if wo_df is not None and hasattr(wo_df, "__len__") else 0,
        }
    return has_emp, has_wo


# ========================= V84 03/04 SINGLE AUTHORITY LOAD/SAVE =========================
# canonical 檔存在時，即使為空也視為正式資料，不得 fallback SQLite 舊快取。

def _v84_md_authority_exists(module_key: str) -> bool:
    try:
        from services.permanent_authority_service import authority_file_exists as _pa_exists
        return bool(_pa_exists(module_key, "records"))
    except Exception:
        return False


def load_work_orders(active_only: bool = True) -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    if _v28_df_from_table is not None and _v84_md_authority_exists("03_work_orders"):
        df = _v28_df_from_table("03_work_orders", "work_orders", columns=cols)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        if active_only and not df.empty:
            mask = _v28_bool_series(df, "is_active")
            if mask is not None:
                df = df[mask]
        return df[cols].sort_values("work_order", kind="stable").reset_index(drop=True) if not df.empty else df[cols]
    return query_df("SELECT * FROM work_orders" + (" WHERE is_active=1" if active_only else "") + " ORDER BY work_order")


def load_employees(active_only: bool = True, in_factory_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    if _v28_df_from_table is not None and _v84_md_authority_exists("04_employees"):
        df = _v28_df_from_table("04_employees", "employees", columns=cols)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        if active_only and not df.empty:
            mask = _v28_bool_series(df, "is_active")
            if mask is not None:
                df = df[mask]
        if in_factory_only and not df.empty:
            mask = _v28_bool_series(df, "is_in_factory")
            if mask is not None:
                df = df[mask]
        out = df[cols].sort_values("employee_id", kind="stable").reset_index(drop=True) if not df.empty else df[cols]
        return _filter_employees_for_time_record(out)
    sql = "SELECT * FROM employees WHERE 1=1"
    if active_only:
        sql += " AND is_active=1"
    if in_factory_only:
        sql += " AND is_in_factory=1"
    sql += " ORDER BY employee_id"
    return _filter_employees_for_time_record(query_df(sql))


def save_work_orders_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    rows = _v28_table_from_df(df) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("03_work_orders", {"work_orders": rows}, reason="save_work_orders_df_v84", github=True)
    try:
        execute("DELETE FROM work_orders")
        for r in rows:
            upsert_work_order(r)
    except Exception:
        pass
    write_log("SAVE_WORK_ORDERS", f"V84 canonical 權威檔儲存製令 {len(rows)} 筆", "work_orders")
    return len(rows)


def save_employees_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    rows = _v28_table_from_df(df) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("04_employees", {"employees": rows}, reason="save_employees_df_v84", github=True)
    try:
        execute("DELETE FROM employees")
        for r in rows:
            upsert_employee(r)
    except Exception:
        pass
    write_log("SAVE_EMPLOYEES", f"V84 canonical 權威檔儲存人員 {len(rows)} 筆", "employees")
    return len(rows)
# ======================= END V84 03/04 SINGLE AUTHORITY LOAD/SAVE =====================


# ======================= V86 01 MASTER DATA FAST CACHE =======================
# 01 工時紀錄每次 widget 互動都會 rerun；此處只快取作業員頁必需下拉資料。
# 資料新增/修改/刪除仍走原本 03/04 權威檔，短暫快取只減少同一使用者連續點選的讀檔成本。
_V86_MD_FAST_CACHE: dict[tuple[str, bool, bool], tuple[float, pd.DataFrame]] = {}
_V86_MD_CACHE_SECONDS = 15.0

try:
    _v86_prev_load_employees_for_time_record_fast = load_employees_for_time_record_fast
except Exception:
    _v86_prev_load_employees_for_time_record_fast = None
try:
    _v86_prev_load_work_orders_for_time_record_fast = load_work_orders_for_time_record_fast
except Exception:
    _v86_prev_load_work_orders_for_time_record_fast = None
try:
    _v86_prev_has_master_data_for_time_record_fast = has_master_data_for_time_record_fast
except Exception:
    _v86_prev_has_master_data_for_time_record_fast = None


def _v86_md_now() -> float:
    try:
        import time as _time
        return float(_time.time())
    except Exception:
        return 0.0


def clear_time_record_master_fast_cache() -> None:
    try:
        _V86_MD_FAST_CACHE.clear()
    except Exception:
        pass


def _v86_md_cached(key: tuple[str, bool, bool], loader):
    now_s = _v86_md_now()
    got = _V86_MD_FAST_CACHE.get(key)
    if got and (now_s - got[0] <= _V86_MD_CACHE_SECONDS):
        return got[1].copy()
    df = loader()
    if df is None:
        df = pd.DataFrame()
    _V86_MD_FAST_CACHE[key] = (now_s, df.copy())
    return df.copy()


def load_employees_for_time_record_fast(active_only: bool = True, in_factory_only: bool = False):  # type: ignore[override]
    return _v86_md_cached(
        ("employees", bool(active_only), bool(in_factory_only)),
        lambda: _v86_prev_load_employees_for_time_record_fast(active_only=active_only, in_factory_only=in_factory_only) if callable(_v86_prev_load_employees_for_time_record_fast) else load_employees(active_only=active_only, in_factory_only=in_factory_only),
    )


def load_work_orders_for_time_record_fast(active_only: bool = True):  # type: ignore[override]
    return _v86_md_cached(
        ("work_orders", bool(active_only), False),
        lambda: _v86_prev_load_work_orders_for_time_record_fast(active_only=active_only) if callable(_v86_prev_load_work_orders_for_time_record_fast) else load_work_orders(active_only=active_only),
    )


def has_master_data_for_time_record_fast(employees=None, work_orders=None):  # type: ignore[override]
    if callable(_v86_prev_has_master_data_for_time_record_fast):
        return _v86_prev_has_master_data_for_time_record_fast(employees, work_orders)
    emp_df = employees if employees is not None else load_employees_for_time_record_fast(active_only=True, in_factory_only=False)
    wo_df = work_orders if work_orders is not None else load_work_orders_for_time_record_fast(active_only=True)
    has_emp = bool(emp_df is not None and hasattr(emp_df, "empty") and not emp_df.empty)
    has_wo = bool(wo_df is not None and hasattr(wo_df, "empty") and not wo_df.empty)
    if employees is None and work_orders is None:
        return {"has_employees_master": has_emp, "has_work_orders_master": has_wo, "employees_count": len(emp_df) if emp_df is not None else 0, "work_orders_count": len(wo_df) if wo_df is not None else 0}
    return has_emp, has_wo
# ===================== END V86 01 MASTER DATA FAST CACHE =====================

# ===================== V127 MULTI-USER EMPLOYEE FAST CACHE ISOLATION =====================
# 修正：V86 fast cache 的 employees key 未包含登入者身份。Streamlit 是多 session 共用
# Python process；如果 001 先載入 01 工時紀錄，002 後載入可能拿到 001 的 filtered
# employee dataframe，造成「畫面上登入者正確，但 01 工號/姓名下拉帶到別人」。
# V127 將 01 用人員 fast cache 改為「登入帳號/工號/角色」隔離，不再跨人共用。
try:
    _v127_prev_has_master_data_for_time_record_fast = has_master_data_for_time_record_fast
except Exception:
    _v127_prev_has_master_data_for_time_record_fast = None

_V127_EMPLOYEE_FAST_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}


def _v127_identity_cache_key() -> tuple[str, str, str]:
    try:
        username, employee_id, roles = _current_login_context()
    except Exception:
        username, employee_id, roles = "", "", []
    if isinstance(roles, str):
        roles = [roles]
    role_text = ",".join(sorted({str(r).strip().lower() for r in (roles or []) if str(r).strip()}))
    return (str(username or "").strip().lower(), str(employee_id or "").strip().lower(), role_text)


def clear_time_record_master_fast_cache() -> None:  # type: ignore[override]
    try:
        _V86_MD_FAST_CACHE.clear()
    except Exception:
        pass
    try:
        _V127_EMPLOYEE_FAST_CACHE.clear()
    except Exception:
        pass


def load_employees_for_time_record_fast(active_only: bool = True, in_factory_only: bool = False):  # type: ignore[override]
    """Load 01 employee options with per-login cache isolation.

    Do NOT call the older V86 fast loader here, because its cache key is global and can
    leak one operator's employee list into another operator's session.  We call
    load_employees() directly so _filter_employees_for_time_record() runs against the
    current session identity.
    """
    now_s = _v86_md_now() if "_v86_md_now" in globals() else 0.0
    key = ("employees_v127", bool(active_only), bool(in_factory_only), *_v127_identity_cache_key())
    got = _V127_EMPLOYEE_FAST_CACHE.get(key)
    ttl = globals().get("_V86_MD_CACHE_SECONDS", 20)
    try:
        ttl = float(ttl)
    except Exception:
        ttl = 20.0
    if got and now_s and (now_s - got[0] <= ttl):
        return got[1].copy()
    try:
        # Prevent any legacy global employee fast-cache entry from being reused by accident.
        if "_V86_MD_FAST_CACHE" in globals() and isinstance(_V86_MD_FAST_CACHE, dict):
            for old_key in list(_V86_MD_FAST_CACHE.keys()):
                if isinstance(old_key, tuple) and old_key and old_key[0] == "employees":
                    _V86_MD_FAST_CACHE.pop(old_key, None)
    except Exception:
        pass
    df = load_employees(active_only=active_only, in_factory_only=in_factory_only)
    if df is None:
        df = pd.DataFrame()
    _V127_EMPLOYEE_FAST_CACHE[key] = (now_s, df.copy())
    return df.copy()


def has_master_data_for_time_record_fast(employees=None, work_orders=None):  # type: ignore[override]
    # Keep original return contract, but make employee-side check use V127 isolated loader
    # whenever caller does not pass an employee dataframe explicitly.
    emp_df = employees if employees is not None else load_employees_for_time_record_fast(active_only=True, in_factory_only=False)
    if work_orders is not None:
        wo_df = work_orders
    else:
        try:
            wo_df = load_work_orders_for_time_record_fast(active_only=True)
        except Exception:
            wo_df = load_work_orders(active_only=True)
    has_emp = bool(emp_df is not None and hasattr(emp_df, "empty") and not emp_df.empty)
    has_wo = bool(wo_df is not None and hasattr(wo_df, "empty") and not wo_df.empty)
    if employees is None and work_orders is None:
        return {"has_employees_master": has_emp, "has_work_orders_master": has_wo, "employees_count": len(emp_df) if emp_df is not None else 0, "work_orders_count": len(wo_df) if wo_df is not None else 0}
    return has_emp, has_wo
# =================== END V127 MULTI-USER EMPLOYEE FAST CACHE ISOLATION ===================

# =================== V171 PERFORMANCE PROFILER HOOKS ===================
try:
    from services.performance_profiler_service import wrap_function, mark_installed
    if mark_installed("master_data_service"):
        for _name in ("load_work_orders", "load_employees", "load_employees_for_time_record_fast", "load_work_orders_for_time_record_fast"):
            if _name in globals() and callable(globals()[_name]):
                globals()[_name] = wrap_function(globals()[_name], category="master_data", name="master_data_service." + _name, threshold_ms=400)  # type: ignore[index]
        for _name in ("save_work_orders_df", "save_employees_df", "import_work_orders_df", "import_employees_df", "upsert_work_order", "upsert_employee"):
            if _name in globals() and callable(globals()[_name]):
                globals()[_name] = wrap_function(globals()[_name], category="master_data_write", name="master_data_service." + _name, threshold_ms=800)  # type: ignore[index]
except Exception:
    pass
# =================== END V171 PERFORMANCE PROFILER HOOKS ===================

