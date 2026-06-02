# -*- coding: utf-8 -*-
"""V202 final time-record view service.

Purpose
-------
Create one deterministic display/query source for 01/02 time records without
changing UI rendering:
- 01 Today Records
- 02 Editable History
- Active Work lookup

Design rules
------------
1. hard_delete_guard is final: deleted rows never return from SQLite, event rows,
   row shards, or LOG recovery.
2. event_rows / row_shards are audit/rebuild sources only; they do not directly
   enter normal screen display here.
3. unresolved LOGRECOVERY / V164B LOG-only recovery rows are isolated from normal
   01/02 display and Active Work until manually closed.
4. If sources disagree between active and terminal status, terminal status wins.
5. Deduplicate by id, then record_key, then business key.
"""
from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from services.timezone_service import today_text, now_text
except Exception:  # pragma: no cover
    def today_text() -> str:
        return datetime.now().strftime("%Y-%m-%d")
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"

TERMINAL_KEYWORDS = ("下班", "暫停", "完工", "已結束", "結束", "補登結束", "人工結算")
PENDING_RECOVERY_SOURCES = (
    "LOGRECOVERY",
    "V164B_LOG_ONLY_RECOVERY",
    "LOG_ONLY_RECOVERY",
    "PENDING_RECOVERY",
)
CLOSED_RECOVERY_SOURCES = (
    "V166B_LOG_ONLY_MANUAL_CLOSED",
    "V166B_LOG_ONLY_CLOSED",
    "MANUAL_CLOSED",
)


def _txt(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.lower() in {"nan", "none", "nat", "null"}:
        return ""
    return s


def _to_int(v: Any) -> int | None:
    s = _txt(v)
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _norm_ts(v: Any) -> str:
    s = _txt(v).replace("/", "-")
    if not s:
        return ""
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return s[:19]


def _date_from_row(row: dict[str, Any]) -> str:
    d = _txt(row.get("start_date") or row.get("開始日期 / Start Date") or row.get("開始日期"))
    if d:
        return d[:10].replace("/", "-")
    ts = _norm_ts(row.get("start_timestamp") or row.get("開始時間戳 / Start Timestamp") or row.get("開始時間 / Start Timestamp") or row.get("開始時間"))
    return ts[:10]


def _row_id(row: dict[str, Any]) -> int | None:
    return _to_int(row.get("id") or row.get("ID") or row.get("ID / ID") or row.get("紀錄編號") or row.get("record_id"))


def _record_key(row: dict[str, Any]) -> str:
    return _txt(row.get("record_key") or row.get("紀錄鍵 / Record Key") or row.get("Record Key") or row.get("record key"))


def business_key(row: dict[str, Any]) -> str:
    start = _norm_ts(
        row.get("start_timestamp")
        or row.get("開始時間戳 / Start Timestamp")
        or row.get("開始時間 / Start Timestamp")
        or row.get("開始時間")
    )
    if not start:
        sd = _txt(row.get("start_date") or row.get("開始日期 / Start Date") or row.get("開始日期"))
        st = _txt(row.get("start_time") or row.get("開始時刻 / Start Time") or row.get("開始時刻"))
        start = _norm_ts((sd + " " + st).strip()) if (sd or st) else ""
    return "|".join([
        _txt(row.get("employee_id") or row.get("工號") or row.get("工號 / Employee ID") or row.get("Employee ID")),
        _txt(row.get("employee_name") or row.get("姓名") or row.get("姓名 / Name") or row.get("Name")),
        _txt(row.get("work_order") or row.get("製令") or row.get("製令 / Work Order") or row.get("Work Order")),
        _txt(row.get("process_name") or row.get("工段名稱") or row.get("工段名稱 / Process") or row.get("工段 / Process") or row.get("Process") or row.get("process")),
        start,
    ])


def _identity_key(row: dict[str, Any]) -> str:
    rid = _row_id(row)
    if rid is not None:
        return f"id:{rid}"
    rk = _record_key(row)
    if rk:
        return f"record_key:{rk}"
    bk = business_key(row)
    return f"biz:{bk}" if bk.strip("|") else json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _is_terminal(row: dict[str, Any]) -> bool:
    status = _txt(row.get("status") or row.get("狀態") or row.get("狀態 / Status"))
    end_action = _txt(row.get("end_action") or row.get("結束動作 / End Action"))
    end_ts = _txt(row.get("end_timestamp") or row.get("結束時間戳 / End Timestamp") or row.get("結束時間 / End Timestamp"))
    joined = f"{status} {end_action}"
    return bool(end_ts) or any(k in joined for k in TERMINAL_KEYWORDS)


def _is_unresolved_recovery(row: dict[str, Any]) -> bool:
    src = _txt(row.get("source") or row.get("資料來源") or row.get("source_module"))
    rk = _record_key(row)
    status = _txt(row.get("status") or row.get("狀態") or row.get("狀態 / Status"))
    recovery_status = _txt(row.get("recovery_status") or row.get("補登狀態"))
    text = " ".join([src, rk, status, recovery_status]).upper()
    if any(x in text for x in CLOSED_RECOVERY_SOURCES):
        return False
    if _is_terminal(row) and "待人工" not in status and "PENDING" not in text:
        return False
    return any(x in text for x in PENDING_RECOVERY_SOURCES) or rk.startswith("LOGRECOVERY|") or "待人工" in status


def _source_priority(source: str) -> int:
    if source == "sqlite":
        return 30
    if source == "02_history":
        return 20
    if source == "01_time_records":
        return 10
    return 0


def _authority_df(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table
        df = df_from_table(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _sqlite_df() -> pd.DataFrame:
    try:
        if not DB_PATH.exists():
            return pd.DataFrame()
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            return pd.read_sql_query("SELECT * FROM time_records", conn)
    except Exception:
        return pd.DataFrame()


def _filter_hard_deleted(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    try:
        from services.time_record_hard_delete_guard_service import filter_deleted_rows
        return filter_deleted_rows(df)
    except Exception:
        return df.copy().reset_index(drop=True)


def _strip_internal(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return df.drop(columns=[c for c in df.columns if str(c).startswith("_v202_")], errors="ignore").reset_index(drop=True)


def _normalize_df(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["_v202_source"] = source
    out["_v202_source_priority"] = _source_priority(source)
    out["_v202_terminal"] = [1 if _is_terminal(dict(r.to_dict())) else 0 for _, r in out.iterrows()]
    out["_v202_identity"] = [_identity_key(dict(r.to_dict())) for _, r in out.iterrows()]
    out["_v202_start_sort"] = [_norm_ts(r.get("start_timestamp")) for _, r in out.iterrows()]
    return out


def _choose_better(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    # Terminal state always wins over active state.  This avoids 01/02 showing
    # 作業中 when SQLite already has an ended row.
    old_terminal = int(old.get("_v202_terminal") or 0)
    new_terminal = int(new.get("_v202_terminal") or 0)
    if new_terminal != old_terminal:
        return new if new_terminal > old_terminal else old
    # Prefer row with end timestamp when both are terminal.
    old_end = _txt(old.get("end_timestamp") or old.get("結束時間戳 / End Timestamp") or old.get("結束時間 / End Timestamp"))
    new_end = _txt(new.get("end_timestamp") or new.get("結束時間戳 / End Timestamp") or new.get("結束時間 / End Timestamp"))
    if bool(new_end) != bool(old_end):
        return new if bool(new_end) else old
    # Prefer higher source priority, then later updated/start timestamp.
    old_p = int(old.get("_v202_source_priority") or 0)
    new_p = int(new.get("_v202_source_priority") or 0)
    if new_p != old_p:
        return new if new_p > old_p else old
    old_ts = _txt(old.get("updated_at") or old.get("end_timestamp") or old.get("start_timestamp"))
    new_ts = _txt(new.get("updated_at") or new.get("end_timestamp") or new.get("start_timestamp"))
    return new if new_ts >= old_ts else old


def _dedupe_final(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    by_key: dict[str, dict[str, Any]] = {}
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        key = _txt(row.get("_v202_identity")) or _identity_key(row)
        if key not in by_key:
            by_key[key] = row
        else:
            by_key[key] = _choose_better(by_key[key], row)
    out = pd.DataFrame(list(by_key.values())) if by_key else pd.DataFrame()
    if not out.empty:
        sort_cols = [c for c in ["start_date", "start_timestamp", "id"] if c in out.columns]
        if sort_cols:
            try:
                out = out.sort_values(sort_cols, ascending=True, kind="stable")
            except Exception:
                pass
    return out.reset_index(drop=True)


def _apply_filters(df: pd.DataFrame, *, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, employee_name: str | None = None, work_order: str | None = None, process_name: str | None = None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    if start_date or end_date:
        dates = out.apply(lambda r: _date_from_row(dict(r.to_dict())), axis=1)
        if start_date:
            out = out.loc[dates >= str(start_date)]
            dates = out.apply(lambda r: _date_from_row(dict(r.to_dict())), axis=1)
        if end_date:
            out = out.loc[dates <= str(end_date)]
    if employee_id:
        cols = [c for c in ("employee_id", "工號", "工號 / Employee ID", "Employee ID") if c in out.columns]
        if cols:
            mask = False
            for c in cols:
                mask = mask | (out[c].astype(str).str.strip() == str(employee_id).strip())
            out = out.loc[mask]
    if employee_name:
        cols = [c for c in ("employee_name", "姓名", "姓名 / Name", "Name") if c in out.columns]
        if cols:
            mask = False
            for c in cols:
                mask = mask | (out[c].astype(str).str.strip() == str(employee_name).strip())
            out = out.loc[mask]
    if work_order:
        cols = [c for c in ("work_order", "製令", "製令 / Work Order", "Work Order") if c in out.columns]
        if cols:
            mask = False
            for c in cols:
                mask = mask | (out[c].astype(str).str.strip() == str(work_order).strip())
            out = out.loc[mask]
    if process_name:
        cols = [c for c in ("process_name", "工段名稱", "工段名稱 / Process", "工段 / Process", "Process", "process") if c in out.columns]
        if cols:
            mask = False
            for c in cols:
                mask = mask | (out[c].astype(str).str.strip() == str(process_name).strip())
            out = out.loc[mask]
    return out.reset_index(drop=True)


def load_final_time_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None, process_name: str | None = None, employee_name: str | None = None, *, include_recovery: bool = False, include_sqlite: bool = True) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    # Preferred visual authorities first, but SQLite may contain the latest ended row.
    for module in ("02_history", "01_time_records"):
        f = _normalize_df(_authority_df(module), module)
        if not f.empty:
            frames.append(f)
    if include_sqlite:
        s = _normalize_df(_sqlite_df(), "sqlite")
        if not s.empty:
            frames.append(s)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged = _filter_hard_deleted(merged)
    if not include_recovery and not merged.empty:
        keep = []
        for _, rr in merged.iterrows():
            keep.append(not _is_unresolved_recovery(dict(rr.to_dict())))
        merged = merged.loc[keep].copy()
    final = _dedupe_final(merged)
    final = _apply_filters(final, start_date=start_date, end_date=end_date, employee_id=employee_id, employee_name=employee_name, work_order=work_order, process_name=process_name)
    return _strip_internal(final)


def load_final_today_records(include_finished: bool = True, unfinished_only: bool = False, employee_id: str | None = None, *, include_recovery: bool = False) -> pd.DataFrame:
    df = load_final_time_records(start_date=today_text(), end_date=today_text(), employee_id=employee_id, include_recovery=include_recovery)
    if df.empty:
        return df
    if unfinished_only:
        keep = []
        for _, rr in df.iterrows():
            keep.append(not _is_terminal(dict(rr.to_dict())))
        df = df.loc[keep]
    elif not include_finished:
        keep = []
        for _, rr in df.iterrows():
            keep.append(not _is_terminal(dict(rr.to_dict())))
        df = df.loc[keep]
    return df.reset_index(drop=True)


def load_final_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    df = load_final_time_records(start_date=start_date, end_date=start_date, employee_id=employee_id, employee_name=employee_name, process_name=process_name, include_recovery=False)
    if df.empty:
        return df
    keep = []
    for _, rr in df.iterrows():
        keep.append(not _is_terminal(dict(rr.to_dict())))
    return df.loc[keep].reset_index(drop=True)


def rebuild_authority_from_final_view(*, dry_run: bool = True, github: bool = False, reason: str = "V202 rebuild 01/02 from final view") -> dict[str, Any]:
    df = load_final_time_records(include_recovery=False, include_sqlite=True)
    rows = []
    if not df.empty:
        try:
            from services.permanent_authority_service import table_from_df
            rows = table_from_df(df)
        except Exception:
            rows = df.to_dict("records")
    result = {
        "ok": True,
        "version": "V202",
        "dry_run": bool(dry_run),
        "final_rows": len(rows),
        "github": bool(github),
        "reason": reason,
    }
    if dry_run:
        return result
    try:
        from services.permanent_authority_service import update_tables
        for module in ("01_time_records", "02_history"):
            update_tables(module, {"time_records": rows}, reason=reason, github=bool(github))
        result["written_modules"] = ["01_time_records", "02_history"]
    except Exception as exc:
        result.update({"ok": False, "error": str(exc)})
    return result


def audit_v202_time_records_governance() -> dict[str, Any]:
    f01 = _authority_df("01_time_records")
    f02 = _authority_df("02_history")
    sqlite = _sqlite_df()
    final = load_final_time_records(include_recovery=False, include_sqlite=True)
    final_with_recovery = load_final_time_records(include_recovery=True, include_sqlite=True)
    deleted_filtered = 0
    try:
        raw = pd.concat([_normalize_df(f02, "02_history"), _normalize_df(f01, "01_time_records"), _normalize_df(sqlite, "sqlite")], ignore_index=True, sort=False)
        deleted_filtered = len(raw) - len(_filter_hard_deleted(raw)) if not raw.empty else 0
    except Exception:
        deleted_filtered = 0
    unresolved_recovery = 0
    if not final_with_recovery.empty:
        unresolved_recovery = sum(1 for _, rr in final_with_recovery.iterrows() if _is_unresolved_recovery(dict(rr.to_dict())))
    return {
        "version": "V202",
        "checked_at": now_text(),
        "source_counts": {
            "01_time_records": int(len(f01)) if isinstance(f01, pd.DataFrame) else 0,
            "02_history": int(len(f02)) if isinstance(f02, pd.DataFrame) else 0,
            "sqlite_time_records": int(len(sqlite)) if isinstance(sqlite, pd.DataFrame) else 0,
            "final_view_rows": int(len(final)) if isinstance(final, pd.DataFrame) else 0,
        },
        "deleted_rows_filtered_by_guard": int(deleted_filtered),
        "unresolved_log_recovery_isolated": int(unresolved_recovery),
        "rules": {
            "single_display_source": "final_time_records_view",
            "hard_delete_guard_final": True,
            "event_rows_audit_only": True,
            "unresolved_log_recovery_excluded_from_active_work": True,
            "terminal_status_wins": True,
            "dedupe_keys": ["id", "record_key", "business_key"],
        },
    }
