# -*- coding: utf-8 -*-
"""V63 consolidated master data service.

Runtime master data reads/writes use crud_table_service/db_service.  Local JSON
or GitHub authority is not touched on page hot paths.
"""
from __future__ import annotations

from typing import Any
import pandas as pd

from services.crud_table_service import load_work_orders as _load_work_orders, load_employees as _load_employees, save_work_orders as _save_work_orders, save_employees as _save_employees

_EMP_CACHE: tuple[float, pd.DataFrame] | None = None
_WO_CACHE: tuple[float, pd.DataFrame] | None = None
_CACHE_TTL = 120.0


def _now_ts() -> float:
    import time
    return time.time()


def _copy(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy().reset_index(drop=True) if isinstance(df, pd.DataFrame) else pd.DataFrame()


def clear_time_record_master_fast_cache() -> None:
    global _EMP_CACHE, _WO_CACHE
    _EMP_CACHE = None
    _WO_CACHE = None


def load_work_orders() -> pd.DataFrame:
    return _load_work_orders().drop(columns=["_delete"], errors="ignore")


def load_employees() -> pd.DataFrame:
    return _load_employees().drop(columns=["_delete"], errors="ignore")


def load_work_orders_for_time_record_fast() -> pd.DataFrame:
    global _WO_CACHE
    now = _now_ts()
    if _WO_CACHE is not None and now - _WO_CACHE[0] <= _CACHE_TTL:
        return _copy(_WO_CACHE[1])
    df = load_work_orders()
    if "is_active" in df.columns:
        try:
            df = df[df["is_active"].astype(bool)].copy()
        except Exception:
            pass
    _WO_CACHE = (now, _copy(df))
    return df.reset_index(drop=True)


def load_employees_for_time_record_fast() -> pd.DataFrame:
    global _EMP_CACHE
    now = _now_ts()
    if _EMP_CACHE is not None and now - _EMP_CACHE[0] <= _CACHE_TTL:
        return _copy(_EMP_CACHE[1])
    df = load_employees()
    for c in ["is_active", "is_in_factory"]:
        if c in df.columns:
            try:
                df = df[df[c].astype(bool)].copy()
            except Exception:
                pass
    _EMP_CACHE = (now, _copy(df))
    return df.reset_index(drop=True)


def has_master_data_for_time_record_fast() -> bool:
    return not load_employees_for_time_record_fast().empty and not load_work_orders_for_time_record_fast().empty


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


def audit_v63_master_data_runtime_consolidated() -> dict[str, Any]:
    return {"version": "V63_MASTER_DATA_RUNTIME_CONSOLIDATED", "local_json_hot_path": False, "github_hot_path": False, "cache_ttl_seconds": _CACHE_TTL}
