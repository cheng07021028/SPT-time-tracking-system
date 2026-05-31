# -*- coding: utf-8 -*-
"""V300 Phase 1 backend acceleration and delete-resurrection guard.

Scope:
- Backend only. No UI/CSS/theme/table layout changes.
- Make 01/02 reads filter tombstoned/deleted rows consistently.
- If 02 History no longer contains a finished record, 01 Today detail must not
  resurrect it from 01 authority, SQLite fallback, query cache, or session cache.
- Keep foreground operations light; GitHub/JSON backup must not be part of the
  critical click path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import pandas as pd

MODULE_01 = "01_time_records"
MODULE_02 = "02_history"
TABLE = "time_records"

ID_COLS = ["id", "ID", "ID / ID", "序號", "編號"]
KEY_COLS = ["record_key", "紀錄鍵 / Record Key", "Record Key"]
EMP_COLS = ["employee_id", "工號", "工號 / Employee ID", "Employee ID"]
NAME_COLS = ["employee_name", "姓名", "姓名 / Name", "Name"]
WO_COLS = ["work_order", "製令", "製令 / Work Order", "Work Order"]
PROC_COLS = ["process_name", "工段", "工段 / Process", "製程", "製程 / Process", "Process"]
START_TS_COLS = ["start_timestamp", "開始時間戳", "開始時間戳 / Start Timestamp", "Start Timestamp", "開始時間"]
START_DATE_COLS = ["start_date", "開始日期", "開始日期 / Start Date", "Start Date"]
START_TIME_COLS = ["start_time", "開始時間", "開始時間 / Start Time", "Start Time"]
DELETE_STATUS_WORDS = {"deleted", "delete", "刪除", "已刪除"}
END_STATUS_WORDS = ("下班", "暫停", "完工", "完成", "結束", "已結束", "補登結束")


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
    for c in cols:
        try:
            if isinstance(row, dict) and c in row:
                val = _text(row.get(c))
            elif hasattr(row, "index") and c in row.index:
                val = _text(row.get(c))
            else:
                continue
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
    return _get(row, KEY_COLS)


def business_key(row: Any) -> str:
    emp = _get(row, EMP_COLS)
    name = _get(row, NAME_COLS)
    wo = _get(row, WO_COLS)
    proc = _get(row, PROC_COLS)
    start_ts = _get(row, START_TS_COLS)
    if not start_ts:
        d = _get(row, START_DATE_COLS)
        t = _get(row, START_TIME_COLS)
        start_ts = (d + " " + t).strip()
    parts = [emp, name, wo, proc, start_ts]
    return "|".join(parts) if any(parts) else ""


def _is_deleted_marker(row: Any) -> bool:
    for c in ("is_deleted", "delete_flag", "deleted", "已刪除", "刪除"):
        try:
            val = _text(row.get(c) if isinstance(row, dict) else row.get(c))
        except Exception:
            val = ""
        if val.lower() in {"1", "true", "yes", "y", "on", "deleted", "刪除", "已刪除"}:
            return True
    try:
        status = _text(row.get("status") if isinstance(row, dict) else row.get("status")).lower()
        if status in DELETE_STATUS_WORDS:
            return True
    except Exception:
        pass
    return False


def _is_finished(row: Any) -> bool:
    try:
        end_ts = _get(row, ["end_timestamp", "結束時間戳", "結束時間", "End Timestamp"])
        if end_ts:
            return True
    except Exception:
        pass
    try:
        status = _text(row.get("status") if isinstance(row, dict) else row.get("status"))
        return any(w in status for w in END_STATUS_WORDS)
    except Exception:
        return False


def _df_from_table(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table
        df = df_from_table(module_key, TABLE)
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _table_from_df(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    try:
        from services.permanent_authority_service import table_from_df
        return list(table_from_df(df))
    except Exception:
        clean = df.copy().where(pd.notna(df), None)
        return [dict(r) for _, r in clean.iterrows()]


def _save_authority_df(module_key: str, df: pd.DataFrame, reason: str, github: bool = False) -> int:
    try:
        from services.permanent_authority_service import save_authority
        rows = _table_from_df(df)
        save_authority(module_key, records={TABLE: rows}, reason=reason, github=bool(github))
        return len(rows)
    except Exception:
        return 0


def _settings(module_key: str) -> dict[str, Any]:
    try:
        from services.permanent_authority_service import load_settings
        stg = load_settings(module_key)
        return dict(stg) if isinstance(stg, dict) else {}
    except Exception:
        return {}


def _save_settings(module_key: str, stg: dict[str, Any], reason: str) -> None:
    try:
        from services.permanent_authority_service import save_settings
        save_settings(module_key, stg or {}, reason=reason, github=False)
    except Exception:
        pass


def _tombstone_sets() -> tuple[set[int], set[str], set[str]]:
    ids: set[int] = set()
    keys: set[str] = set()
    biz: set[str] = set()
    for module in (MODULE_01, MODULE_02):
        stg = _settings(module)
        for x in stg.get("deleted_record_ids", []) if isinstance(stg.get("deleted_record_ids", []), list) else []:
            rid = _norm_id(x)
            if rid is not None:
                ids.add(rid)
        for x in stg.get("deleted_record_keys", []) if isinstance(stg.get("deleted_record_keys", []), list) else []:
            s = _text(x)
            if s:
                keys.add(s)
        for x in stg.get("deleted_record_business_keys", []) if isinstance(stg.get("deleted_record_business_keys", []), list) else []:
            s = _text(x)
            if s:
                biz.add(s)
    return ids, keys, biz


def _add_tombstones_from_rows(rows: list[dict[str, Any]], ids: Iterable[Any] | None = None, reason: str = "v300_tombstone") -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    add_ids: set[int] = set()
    add_keys: set[str] = set()
    add_biz: set[str] = set()
    for x in ids or []:
        rid = _norm_id(x)
        if rid is not None:
            add_ids.add(rid)
    for row in rows or []:
        rid = _row_id(row)
        if rid is not None:
            add_ids.add(rid)
        rk = _record_key(row)
        if rk:
            add_keys.add(rk)
        bk = business_key(row)
        if bk:
            add_biz.add(bk)
    for module in (MODULE_01, MODULE_02):
        stg = _settings(module)
        cur_ids = {_norm_id(x) for x in (stg.get("deleted_record_ids", []) if isinstance(stg.get("deleted_record_ids", []), list) else [])}
        cur_ids = {int(x) for x in cur_ids if x is not None}
        cur_keys = {_text(x) for x in (stg.get("deleted_record_keys", []) if isinstance(stg.get("deleted_record_keys", []), list) else []) if _text(x)}
        cur_biz = {_text(x) for x in (stg.get("deleted_record_business_keys", []) if isinstance(stg.get("deleted_record_business_keys", []), list) else []) if _text(x)}
        stg["deleted_record_ids"] = sorted(cur_ids | add_ids)
        stg["deleted_record_keys"] = sorted(cur_keys | add_keys)
        stg["deleted_record_business_keys"] = sorted(cur_biz | add_biz)
        stg["delete_tombstone_updated_at"] = now
        stg["delete_tombstone_version"] = "V300_PHASE1"
        stg["delete_tombstone_reason"] = reason
        _save_settings(module, stg, reason="v300_phase1_save_tombstone")


def _row_matches_identity(row: Any, ids: set[int], keys: set[str], biz: set[str]) -> bool:
    rid = _row_id(row)
    if rid is not None and rid in ids:
        return True
    rk = _record_key(row)
    if rk and rk in keys:
        return True
    bk = business_key(row)
    if bk and bk in biz:
        return True
    return False


def _identity_sets(df: pd.DataFrame) -> tuple[set[int], set[str], set[str]]:
    ids: set[int] = set()
    keys: set[str] = set()
    biz: set[str] = set()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return ids, keys, biz
    for _, row in df.iterrows():
        rid = _row_id(row)
        if rid is not None:
            ids.add(rid)
        rk = _record_key(row)
        if rk:
            keys.add(rk)
        bk = business_key(row)
        if bk:
            biz.add(bk)
    return ids, keys, biz


def filter_deleted_rows_v300(df: pd.DataFrame, *, reconcile_with_history: bool = True) -> pd.DataFrame:
    """Filter deleted/tombstoned rows and stop 01 from resurrecting deleted history rows.

    A finished row that is no longer in 02_history is considered deleted for 01 display.
    Active unfinished rows are not removed just because they are not yet in 02_history.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    ids, keys, biz = _tombstone_sets()
    hist_ids: set[int] = set()
    hist_keys: set[str] = set()
    hist_biz: set[str] = set()
    if reconcile_with_history:
        hist_df = _df_from_table(MODULE_02)
        hist_df = hist_df.copy() if isinstance(hist_df, pd.DataFrame) else pd.DataFrame()
        if not hist_df.empty:
            hist_df = filter_deleted_rows_v300(hist_df, reconcile_with_history=False)
            hist_ids, hist_keys, hist_biz = _identity_sets(hist_df)

    keep: list[bool] = []
    resurrected_rows: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        if _is_deleted_marker(row) or _row_matches_identity(row, ids, keys, biz):
            keep.append(False)
            continue
        if reconcile_with_history and _is_finished(row):
            has_identity = (_row_id(row) is not None) or bool(_record_key(row)) or bool(business_key(row))
            in_history = _row_matches_identity(row, hist_ids, hist_keys, hist_biz)
            if has_identity and not in_history:
                try:
                    resurrected_rows.append(dict(row))
                except Exception:
                    pass
                keep.append(False)
                continue
        keep.append(True)
    if resurrected_rows:
        _add_tombstones_from_rows(resurrected_rows, reason="v300_phase1_block_01_resurrection_after_02_delete")
    return out.loc[keep].copy().reset_index(drop=True)


def clear_frontend_caches_v300() -> None:
    try:
        from services.db_service import clear_query_cache
        clear_query_cache()
    except Exception:
        pass
    try:
        import streamlit as st
        for key in list(getattr(st, "session_state", {}).keys()):
            sk = str(key)
            if any(token in sk.lower() for token in ("today_records", "history_records", "v259_01", "v260", "time_records_df", "finished_today")):
                try:
                    del st.session_state[key]
                except Exception:
                    pass
        st.session_state["v300_phase1_delete_cache_token"] = datetime.now().strftime("%Y%m%d%H%M%S%f")
    except Exception:
        pass


def delete_time_records_v300(record_ids: Iterable[Any] | None, *, selected_rows: pd.DataFrame | None = None, reason: str = "V300 Phase1 delete", github: bool = False) -> int:
    ids = []
    for x in record_ids or []:
        rid = _norm_id(x)
        if rid is not None and rid not in ids:
            ids.append(rid)
    deleted = 0
    try:
        from services.time_record_delete_unifier_service import force_delete_time_records
        deleted = int(force_delete_time_records(ids, selected_rows=selected_rows, reason=reason, github=bool(github)) or 0)
    except TypeError:
        try:
            from services.time_record_delete_unifier_service import force_delete_time_records
            deleted = int(force_delete_time_records(ids, reason=reason, github=bool(github)) or 0)
        except Exception:
            deleted = 0
    except Exception:
        deleted = 0
    # Add tombstones again from selected rows; this blocks resurrection even if older delete layers only removed 02.
    try:
        rows = selected_rows.to_dict("records") if isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty else []
        _add_tombstones_from_rows(rows, ids=ids, reason=reason)
    except Exception:
        pass
    # Purge any now-tombstoned rows that still exist in 01 authority.
    try:
        for module in (MODULE_01, MODULE_02):
            df = _df_from_table(module)
            if isinstance(df, pd.DataFrame):
                filtered = filter_deleted_rows_v300(df, reconcile_with_history=(module == MODULE_01))
                if len(filtered) != len(df):
                    _save_authority_df(module, filtered, reason="v300_phase1_purge_tombstoned_display_rows", github=False)
    except Exception:
        pass
    clear_frontend_caches_v300()
    return int(deleted or len(ids) or 0)


def delete_selected_from_editor_v300(frame: pd.DataFrame, delete_col: str = "刪除 / Delete", reason: str = "V300 editor delete") -> int:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return 0
    selected = pd.DataFrame()
    try:
        col = delete_col if delete_col in frame.columns else None
        if col is None:
            for c in ("刪除 / Delete", "刪除", "Delete", "_delete"):
                if c in frame.columns:
                    col = c
                    break
        if col:
            mask = frame[col].map(lambda v: str(v).strip().lower() in {"true", "1", "yes", "y", "on", "刪除", "checked"} or bool(v) is True)
            selected = frame.loc[mask].drop(columns=[col], errors="ignore").copy()
    except Exception:
        selected = pd.DataFrame()
    ids: list[int] = []
    if not selected.empty:
        for _, row in selected.iterrows():
            rid = _row_id(row)
            if rid is not None and rid not in ids:
                ids.append(rid)
    return delete_time_records_v300(ids, selected_rows=selected, reason=reason, github=False)


def ensure_database_indexes_v300() -> None:
    """Best-effort simple indexes for SQLite/PostgreSQL. Safe to fail per index."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_time_records_employee_id ON time_records(employee_id)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_start_date ON time_records(start_date)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_status ON time_records(status)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_end_timestamp ON time_records(end_timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_work_order ON time_records(work_order)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_process_name ON time_records(process_name)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_record_key ON time_records(record_key)",
    ]
    try:
        from services import db_service as db
        for sql in indexes:
            try:
                db.execute(sql, mark_changed=False, reason="v300_phase1_index")
            except TypeError:
                try:
                    db.execute(sql)
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass


_INDEX_DONE = False

def ensure_once_v300() -> None:
    global _INDEX_DONE
    if _INDEX_DONE:
        return
    _INDEX_DONE = True
    ensure_database_indexes_v300()
