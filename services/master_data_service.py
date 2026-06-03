# -*- coding: utf-8 -*-
"""V65 consolidated master data service.

Runtime master data reads/writes use crud_table_service/db_service. Local JSON
or GitHub authority is not touched on page hot paths.

V64 fix:
- Keep backward-compatible function signatures used by pages 01/02/05.
- `load_employees_for_time_record_fast(active_only=True, in_factory_only=False)`
  and `load_work_orders_for_time_record_fast(active_only=True)` no longer raise
  TypeError.
- Cache is keyed by filter options so one page cannot receive another page's
  filtered result by accident.

V65 fix:
- `has_master_data_for_time_record_fast(employees, work_orders)` now supports
  the page 01 tuple-unpack call without raising TypeError.
"""
from __future__ import annotations

from typing import Any
import pandas as pd

from services.crud_table_service import (
    load_work_orders as _load_work_orders,
    load_employees as _load_employees,
    save_work_orders as _save_work_orders,
    save_employees as _save_employees,
    clear_master_data_cache as _clear_crud_master_data_cache,
)

_EMP_CACHE: dict[tuple[Any, ...], tuple[float, pd.DataFrame]] = {}
_WO_CACHE: dict[tuple[Any, ...], tuple[float, pd.DataFrame]] = {}
_CACHE_TTL = 120.0


def _now_ts() -> float:
    import time

    return time.time()


def _copy(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy().reset_index(drop=True) if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _bool_series(series: pd.Series, default: bool = True) -> pd.Series:
    """Convert mixed DB boolean values to a stable bool Series."""
    if series is None:
        return pd.Series(dtype=bool)
    text = series.fillna("" if not default else "1").astype(str).str.strip().str.lower()
    true_values = {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選"}
    false_values = {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否"}
    out = text.map(lambda x: True if x in true_values else False if x in false_values else default)
    return out.astype(bool)


def _apply_bool_filter(df: pd.DataFrame, column: str, enabled: bool | None, default: bool = True) -> pd.DataFrame:
    """Filter df by a boolean-ish column only when enabled is True."""
    if enabled is not True or column not in df.columns or df.empty:
        return df
    try:
        return df[_bool_series(df[column], default=default)].copy()
    except Exception:
        return df


def clear_time_record_master_fast_cache() -> None:
    _EMP_CACHE.clear()
    _WO_CACHE.clear()
    try:
        _clear_crud_master_data_cache()
    except Exception:
        pass


def load_work_orders(active_only: bool | None = None, **_: Any) -> pd.DataFrame:
    """Load work-order master data with short filter-aware cache."""
    key = ("work_orders", active_only)
    now = _now_ts()
    cached = _WO_CACHE.get(key)
    if cached is not None and now - cached[0] <= _CACHE_TTL:
        return _copy(cached[1])
    df = _load_work_orders().drop(columns=["_delete"], errors="ignore")
    df = _apply_bool_filter(df, "is_active", active_only, default=True)
    df = df.reset_index(drop=True)
    _WO_CACHE[key] = (now, _copy(df))
    return df


def load_employees(
    active_only: bool | None = None,
    in_factory_only: bool | None = None,
    today_attendance_only: bool | None = None,
    **_: Any,
) -> pd.DataFrame:
    """Load employee master data with short filter-aware cache."""
    key = ("employees", active_only, in_factory_only, today_attendance_only)
    now = _now_ts()
    cached = _EMP_CACHE.get(key)
    if cached is not None and now - cached[0] <= _CACHE_TTL:
        return _copy(cached[1])
    df = _load_employees().drop(columns=["_delete"], errors="ignore")
    df = _apply_bool_filter(df, "is_active", active_only, default=True)
    df = _apply_bool_filter(df, "is_in_factory", in_factory_only, default=True)
    df = _apply_bool_filter(df, "is_today_attendance", today_attendance_only, default=True)
    df = df.reset_index(drop=True)
    _EMP_CACHE[key] = (now, _copy(df))
    return df


def load_work_orders_for_time_record_fast(active_only: bool | None = True, **_: Any) -> pd.DataFrame:
    key = ("work_orders_for_time_record", bool(active_only))
    now = _now_ts()
    cached = _WO_CACHE.get(key)
    if cached is not None and now - cached[0] <= _CACHE_TTL:
        return _copy(cached[1])
    df = load_work_orders(active_only=active_only)
    _WO_CACHE[key] = (now, _copy(df))
    return df.reset_index(drop=True)


def load_employees_for_time_record_fast(
    active_only: bool | None = True,
    in_factory_only: bool | None = True,
    today_attendance_only: bool | None = None,
    **_: Any,
) -> pd.DataFrame:
    key = (
        "employees_for_time_record",
        bool(active_only),
        bool(in_factory_only),
        bool(today_attendance_only),
    )
    now = _now_ts()
    cached = _EMP_CACHE.get(key)
    if cached is not None and now - cached[0] <= _CACHE_TTL:
        return _copy(cached[1])
    df = load_employees(
        active_only=active_only,
        in_factory_only=in_factory_only,
        today_attendance_only=today_attendance_only,
    )
    _EMP_CACHE[key] = (now, _copy(df))
    return df.reset_index(drop=True)


def _has_rows(value: Any) -> bool:
    """Return whether a provided master-data object has at least one row."""
    if isinstance(value, pd.DataFrame):
        return not value.empty
    if value is None:
        return False
    try:
        return len(value) > 0  # type: ignore[arg-type]
    except Exception:
        return False


def has_master_data_for_time_record_fast(
    employees: Any | None = None,
    work_orders: Any | None = None,
    **_: Any,
) -> bool | tuple[bool, bool]:
    """Check whether time-record master data exists.

    Backward compatibility:
    - Older code called this with no arguments and expected one boolean.
    - Page 01 calls `has_master_data_for_time_record_fast(employees, work_orders)`
      and unpacks `(has_employees_master, has_work_orders_master)`.

    When dataframes are supplied, use them directly to avoid an extra Neon query
    during page render. When no dataframes are supplied, load the fast cached
    data and return the historical single boolean.
    """
    if employees is not None or work_orders is not None:
        return (_has_rows(employees), _has_rows(work_orders))

    has_employees = _has_rows(load_employees_for_time_record_fast())
    has_work_orders = _has_rows(load_work_orders_for_time_record_fast())
    return has_employees and has_work_orders


def save_work_orders_df(df: pd.DataFrame) -> dict[str, Any]:
    clear_time_record_master_fast_cache()
    return _save_work_orders(df)


def save_employees_df(df: pd.DataFrame) -> dict[str, Any]:
    clear_time_record_master_fast_cache()
    return _save_employees(df)


def import_work_orders_df(df: pd.DataFrame) -> dict[str, Any]:
    return save_work_orders_df(df)


def import_employees_df(df: pd.DataFrame) -> dict[str, Any]:
    return save_employees_df(df)


def upsert_work_order(row: dict[str, Any]) -> dict[str, Any]:
    return save_work_orders_df(pd.DataFrame([row]))


def upsert_employee(row: dict[str, Any]) -> dict[str, Any]:
    return save_employees_df(pd.DataFrame([row]))


def audit_v64_master_data_runtime_consolidated() -> dict[str, Any]:
    return {
        "version": "V69_MASTER_DATA_FILTER_CACHE",
        "local_json_hot_path": False,
        "github_hot_path": False,
        "cache_ttl_seconds": _CACHE_TTL,
        "backward_compatible_filters": True,
        "backward_compatible_master_check_args": True,
    }


def audit_v63_master_data_runtime_consolidated() -> dict[str, Any]:
    """Backward-compatible audit entry used by existing diagnostic pages."""
    return audit_v64_master_data_runtime_consolidated()
