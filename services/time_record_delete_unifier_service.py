# -*- coding: utf-8 -*-
"""V179 time-record unified delete lane.

Purpose
-------
Make 01/02 time-record deletion deterministic after LOG recovery / event repair /
SQLite-cache layers have accumulated.  This module is intentionally backend-only:
no CSS, no Streamlit layout changes, no rendering changes.

Rules
-----
- 02_history is treated as the visible canonical source for history display.
- Deletion writes tombstones by id, record_key, and business identity key.
- Deletion removes matching rows from 01_time_records, 02_history, and SQLite cache.
- LOGRECOVERY / event / row-shard remnants are blocked by tombstone filtering.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import sqlite3
import pandas as pd

try:
    from services.db_service import DB_PATH, clear_query_cache
except Exception:  # pragma: no cover
    DB_PATH = Path(__file__).resolve().parents[1] / "data" / "database" / "spt_time_tracking.db"
    def clear_query_cache():
        return None

try:
    from services.log_service import write_log
except Exception:  # pragma: no cover
    def write_log(*args, **kwargs):
        return None

MODULE_01 = "01_time_records"
MODULE_02 = "02_history"
TABLE = "time_records"
TOMBSTONE_ID_KEY = "deleted_record_ids"
TOMBSTONE_RECORD_KEY = "deleted_record_keys"
TOMBSTONE_BUSINESS_KEY = "deleted_record_business_keys"
TOMBSTONE_LOG_KEY = "delete_tombstone_log_v179"

ID_COLS = ["id", "ID", "ID / ID", "ID / ID / ID", "序號", "編號"]
RECORD_KEY_COLS = ["record_key", "紀錄鍵 / Record Key", "Record Key"]
EMPLOYEE_ID_COLS = ["employee_id", "工號 / Employee ID", "工號", "Employee ID"]
EMPLOYEE_NAME_COLS = ["employee_name", "姓名 / Name", "姓名", "Name"]
WORK_ORDER_COLS = ["work_order", "製令 / Work Order", "製令", "Work Order"]
PROCESS_COLS = ["process_name", "工段 / Process", "製程 / Process", "工段", "製程", "Process"]
START_TS_COLS = ["start_timestamp", "開始時間戳 / Start Timestamp", "開始時間戳", "Start Timestamp"]
START_DATE_COLS = ["start_date", "開始日期 / Start Date", "開始日期", "Start Date"]
START_TIME_COLS = ["start_time", "開始時間 / Start Time", "開始時間", "Start Time"]
DELETE_COLS = ["刪除 / Delete", "Delete", "刪除", "_delete"]


def _now_text() -> str:
    try:
        from services.timezone_service import now_text
        return str(now_text())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(v: Any) -> str:
    try:
        if v is None or pd.isna(v):
            return ""
    except Exception:
        if v is None:
            return ""
    return str(v).strip()


def _norm_id(v: Any) -> int | None:
    s = _text(v)
    if not s:
        return None
    try:
        i = int(float(s))
        return i if i > 0 else None
    except Exception:
        return None


def _get(row: Any, cols: Iterable[str]) -> str:
    if row is None:
        return ""
    for c in cols:
        try:
            if isinstance(row, dict):
                if c in row:
                    val = _text(row.get(c))
                    if val:
                        return val
            elif hasattr(row, "index") and c in row.index:
                val = _text(row.get(c))
                if val:
                    return val
        except Exception:
            continue
    return ""


def _row_id(row: Any) -> int | None:
    for c in ID_COLS:
        try:
            if isinstance(row, dict) and c in row:
                rid = _norm_id(row.get(c))
            elif hasattr(row, "index") and c in row.index:
                rid = _norm_id(row.get(c))
            else:
                rid = None
            if rid is not None:
                return rid
        except Exception:
            continue
    return None


def _record_key(row: Any) -> str:
    return _get(row, RECORD_KEY_COLS)


def business_key_from_row(row: Any) -> str:
    emp = _get(row, EMPLOYEE_ID_COLS)
    name = _get(row, EMPLOYEE_NAME_COLS)
    wo = _get(row, WORK_ORDER_COLS)
    proc = _get(row, PROCESS_COLS)
    start_ts = _get(row, START_TS_COLS)
    if not start_ts:
        d = _get(row, START_DATE_COLS)
        t = _get(row, START_TIME_COLS)
        if d or t:
            start_ts = (d + " " + t).strip()
    parts = [emp, name, wo, proc, start_ts]
    # If all important parts are blank, do not create a broad tombstone.
    if not any(parts):
        return ""
    return "|".join(parts)


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = _text(v).lower()
    return s in {"1", "true", "yes", "y", "on", "checked", "☑", "✅", "是", "勾選", "刪除"}


def _df_from_table(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table
        df = df_from_table(module_key, TABLE)
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _table_rows_from_df(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    try:
        from services.permanent_authority_service import table_from_df
        return list(table_from_df(df))
    except Exception:
        clean = df.copy().where(pd.notna(df), None)
        return [dict(r) for _, r in clean.iterrows()]


def _save_authority(module_key: str, df: pd.DataFrame, reason: str, *, github: bool = False) -> int:
    rows = _table_rows_from_df(df)
    try:
        from services.permanent_authority_service import save_authority
        save_authority(module_key, records={TABLE: rows}, reason=reason, github=bool(github))
    except Exception as exc:
        try:
            write_log("V179_DELETE_AUTHORITY_SAVE_ERROR", f"{module_key} 寫入失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    return len(rows)


def _load_settings(module_key: str = MODULE_02) -> dict[str, Any]:
    try:
        from services.permanent_authority_service import load_settings
        stg = load_settings(module_key)
        return dict(stg) if isinstance(stg, dict) else {}
    except Exception:
        return {}


def _save_settings(module_key: str, settings: dict[str, Any], reason: str, *, github: bool = False) -> None:
    try:
        from services.permanent_authority_service import save_settings
        save_settings(module_key, settings or {}, reason=reason, github=bool(github))
    except Exception:
        pass


def _tombstone_sets() -> tuple[set[int], set[str], set[str]]:
    stg = _load_settings(MODULE_02)
    ids: set[int] = set()
    for x in stg.get(TOMBSTONE_ID_KEY, []) if isinstance(stg.get(TOMBSTONE_ID_KEY, []), list) else []:
        rid = _norm_id(x)
        if rid is not None:
            ids.add(rid)
    keys = {_text(x) for x in stg.get(TOMBSTONE_RECORD_KEY, []) if _text(x)} if isinstance(stg.get(TOMBSTONE_RECORD_KEY, []), list) else set()
    biz = {_text(x) for x in stg.get(TOMBSTONE_BUSINESS_KEY, []) if _text(x)} if isinstance(stg.get(TOMBSTONE_BUSINESS_KEY, []), list) else set()
    return ids, keys, biz


def _add_tombstones(ids: set[int], record_keys: set[str], business_keys: set[str], reason: str = "") -> None:
    now = _now_text()
    for module_key in [MODULE_02, MODULE_01]:
        stg = _load_settings(module_key)
        old_ids = {_norm_id(x) for x in (stg.get(TOMBSTONE_ID_KEY, []) if isinstance(stg.get(TOMBSTONE_ID_KEY, []), list) else [])}
        old_ids = {int(x) for x in old_ids if x is not None}
        old_keys = {_text(x) for x in (stg.get(TOMBSTONE_RECORD_KEY, []) if isinstance(stg.get(TOMBSTONE_RECORD_KEY, []), list) else []) if _text(x)}
        old_biz = {_text(x) for x in (stg.get(TOMBSTONE_BUSINESS_KEY, []) if isinstance(stg.get(TOMBSTONE_BUSINESS_KEY, []), list) else []) if _text(x)}
        stg[TOMBSTONE_ID_KEY] = sorted(old_ids | {int(x) for x in ids if int(x) > 0})
        stg[TOMBSTONE_RECORD_KEY] = sorted(old_keys | {_text(x) for x in record_keys if _text(x)})
        stg[TOMBSTONE_BUSINESS_KEY] = sorted(old_biz | {_text(x) for x in business_keys if _text(x)})
        stg["delete_tombstone_updated_at"] = now
        log = stg.get(TOMBSTONE_LOG_KEY, [])
        if not isinstance(log, list):
            log = []
        log.append({"at": now, "reason": reason, "ids": sorted(ids), "record_keys": sorted(record_keys), "business_keys": sorted(business_keys)[:200]})
        stg[TOMBSTONE_LOG_KEY] = log[-300:]
        _save_settings(module_key, stg, "v179_unified_delete_tombstone", github=False)


def _row_matches(row: Any, ids: set[int], record_keys: set[str], business_keys: set[str]) -> bool:
    rid = _row_id(row)
    if rid is not None and rid in ids:
        return True
    rk = _record_key(row)
    if rk and rk in record_keys:
        return True
    bk = business_key_from_row(row)
    if bk and bk in business_keys:
        return True
    return False


def filter_deleted_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    ids, keys, biz = _tombstone_sets()
    if not ids and not keys and not biz:
        return df
    out = df.copy()
    keep = []
    for _, row in out.iterrows():
        keep.append(not _row_matches(row, ids, keys, biz))
    return out.loc[keep].copy().reset_index(drop=True)


def selected_rows_from_editor(frame: pd.DataFrame, delete_col: str | None = None) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    col = delete_col if delete_col and delete_col in frame.columns else None
    if not col:
        for c in DELETE_COLS:
            if c in frame.columns:
                col = c
                break
    if not col:
        return pd.DataFrame()
    try:
        mask = frame[col].map(_to_bool)
        return frame.loc[mask].drop(columns=[col], errors="ignore").copy()
    except Exception:
        return pd.DataFrame()


def _sqlite_df() -> pd.DataFrame:
    try:
        if not Path(DB_PATH).exists():
            return pd.DataFrame()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            return pd.read_sql_query("SELECT * FROM time_records", conn)
        finally:
            conn.close()
    except Exception:
        return pd.DataFrame()


def _build_targets(record_ids: Iterable[Any] | None, selected_rows: pd.DataFrame | None) -> tuple[pd.DataFrame, set[int], set[str], set[str]]:
    ids: set[int] = set()
    keys: set[str] = set()
    biz: set[str] = set()
    target_frames: list[pd.DataFrame] = []

    for x in record_ids or []:
        rid = _norm_id(x)
        if rid is not None:
            ids.add(rid)

    if selected_rows is not None and isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty:
        target_frames.append(selected_rows.copy())
        for _, r in selected_rows.iterrows():
            rid = _row_id(r)
            if rid is not None:
                ids.add(rid)
            rk = _record_key(r)
            if rk:
                keys.add(rk)
            bk = business_key_from_row(r)
            if bk:
                biz.add(bk)

    # Pull exact rows from every source so deletion can work even when the UI only has an ID.
    for src in [_df_from_table(MODULE_01), _df_from_table(MODULE_02), _sqlite_df()]:
        if src is None or src.empty:
            continue
        matched = []
        for idx, row in src.iterrows():
            if _row_matches(row, ids, keys, biz):
                matched.append(idx)
        if matched:
            m = src.loc[matched].copy()
            target_frames.append(m)
            for _, r in m.iterrows():
                rid = _row_id(r)
                if rid is not None:
                    ids.add(rid)
                rk = _record_key(r)
                if rk:
                    keys.add(rk)
                bk = business_key_from_row(r)
                if bk:
                    biz.add(bk)

    target_df = pd.concat(target_frames, ignore_index=True, sort=False) if target_frames else pd.DataFrame()
    return target_df, ids, keys, biz


def _drop_targets(df: pd.DataFrame, ids: set[int], record_keys: set[str], business_keys: set[str]) -> tuple[pd.DataFrame, int]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df, 0
    keep = []
    deleted = 0
    for _, row in df.iterrows():
        hit = _row_matches(row, ids, record_keys, business_keys)
        if hit:
            deleted += 1
        keep.append(not hit)
    return df.loc[keep].copy().reset_index(drop=True), deleted


def _delete_sqlite(ids: set[int], record_keys: set[str], business_keys: set[str]) -> int:
    deleted = 0
    try:
        if not Path(DB_PATH).exists():
            return 0
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=8000")
            rows = conn.execute("SELECT * FROM time_records").fetchall()
            sqlite_ids: list[int] = []
            for rr in rows:
                d = dict(rr)
                if _row_matches(d, ids, record_keys, business_keys):
                    rid = _row_id(d)
                    if rid is not None:
                        sqlite_ids.append(rid)
            if sqlite_ids:
                placeholders = ",".join(["?"] * len(sqlite_ids))
                cur = conn.execute(f"DELETE FROM time_records WHERE id IN ({placeholders})", sqlite_ids)
                deleted = int(cur.rowcount or 0)
                conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        try:
            write_log("V179_SQLITE_DELETE_ERROR", f"SQLite cache delete failed: {exc}", "time_records", level="ERROR")
        except Exception:
            pass
    return deleted


def force_delete_time_records(record_ids: Iterable[Any] | None = None, *, selected_rows: pd.DataFrame | None = None, reason: str = "V179 unified delete", github: bool = False) -> int:
    target_df, ids, record_keys, business_keys = _build_targets(record_ids, selected_rows)
    if target_df.empty and not ids and not record_keys and not business_keys:
        return 0

    # Even when target rows are missing, write id tombstones to block future repair layers.
    _add_tombstones(ids, record_keys, business_keys, reason=reason)

    total_deleted = 0
    for module_key in [MODULE_01, MODULE_02]:
        df = _df_from_table(module_key)
        remaining, deleted = _drop_targets(df, ids, record_keys, business_keys)
        remaining = filter_deleted_rows(remaining)
        _save_authority(module_key, remaining, f"v179_unified_delete_{module_key}", github=bool(github))
        total_deleted = max(total_deleted, int(deleted))

    sqlite_deleted = _delete_sqlite(ids, record_keys, business_keys)
    total_deleted = max(total_deleted, sqlite_deleted, len(ids) if ids else 0, len(target_df) if not target_df.empty else 0)

    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        # Clear optional fast caches if the current deployment has them.
        from services import time_record_service as trs
        if hasattr(trs, "clear_today_records_fast_cache"):
            trs.clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        write_log(
            "DELETE_TIME_RECORDS_V179",
            f"{reason}：統一刪除通道完成，ids={sorted(ids)}, record_keys={len(record_keys)}, business_keys={len(business_keys)}, deleted={total_deleted}",
            "time_records",
            level="WARN",
        )
    except Exception:
        pass
    return int(total_deleted)


def delete_selected_time_records_from_editor(frame: pd.DataFrame, delete_col: str | None = None, *, reason: str = "V179 editor selected delete", github: bool = False) -> int:
    selected = selected_rows_from_editor(frame, delete_col)
    ids: list[int] = []
    if not selected.empty:
        for _, r in selected.iterrows():
            rid = _row_id(r)
            if rid is not None and rid not in ids:
                ids.append(rid)
    return force_delete_time_records(ids, selected_rows=selected, reason=reason, github=github)


def assert_delete_available() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "time_record_delete_unifier_service",
        "version": "V179",
        "supports": ["id", "record_key", "business_key", "01/02 authority", "sqlite cache", "tombstone"],
    }
