# -*- coding: utf-8 -*-
"""Neon-runtime consolidated time record service.

V63 design goals:
- Preserve the existing UI/pages function names.
- Remove the old 30k-line patch stack from the hot path.
- Use services.db_service only; Neon/PostgreSQL is the runtime authority when configured.
- Never write local JSON/GitHub during buttons. 09/14 remain manual backup tools.
- Use soft delete/tombstone semantics for admin deletes.
"""
from __future__ import annotations

import json
import os
import math
import uuid
from datetime import datetime, timedelta, time as dt_time
from typing import Any, Iterable

import pandas as pd

from services.db_service import (
    ensure_database,
    query_df,
    query_one,
    execute,
    executemany,
    execute_transaction,
    clear_query_cache,
    is_postgres_enabled,
)
try:
    from services.timezone_service import now_text, today_text
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def today_text() -> str:
        return datetime.now().strftime("%Y-%m-%d")

TIME_RECORD_COLUMNS = [
    "id", "record_id", "record_key", "operation_id", "status",
    "work_order", "work_order_no", "part_no", "type_name", "process_code", "process_name",
    "employee_id", "employee_name", "start_action", "start_timestamp", "end_action", "end_timestamp",
    "remark", "start_date", "start_time", "end_date", "end_time",
    "work_hours", "work_minutes", "raw_minutes", "average_minutes",
    "assembly_location", "group_key", "is_group_work", "source",
    "created_at", "updated_at", "updated_by", "deleted_at", "deleted_by", "delete_reason", "version",
]

DISPLAY_TO_INTERNAL = {
    "ID / ID": "id",
    "紀錄編號": "id",
    "狀態 / Status": "status",
    "製令 / Work Order": "work_order",
    "製令號碼 / Work Order No.": "work_order_no",
    "P/N / Part No.": "part_no",
    "機型 / Type": "type_name",
    "工段名稱 / Process": "process_name",
    "工段 / Process": "process_name",
    "工號 / Employee ID": "employee_id",
    "姓名 / Name": "employee_name",
    "開始動作 / Start Action": "start_action",
    "開始時間戳 / Start Timestamp": "start_timestamp",
    "結束動作 / End Action": "end_action",
    "結束時間戳 / End Timestamp": "end_timestamp",
    "開始日期 / Start Date": "start_date",
    "開始時間 / Start Time": "start_time",
    "結束日期 / End Date": "end_date",
    "結束時間 / End Time": "end_time",
    "工時小計 / Hours": "work_hours",
    "工時分鐘 / Minutes": "work_minutes",
    "備註 / Remark": "remark",
    "組立地點 / Assembly Location": "assembly_location",
    "建立時間 / Created At": "created_at",
    "更新時間 / Updated At": "updated_at",
}

END_ACTION_STATUS = {
    "暫停": "暫停",
    "下班": "下班",
    "完工": "完工",
    "結束": "已結束",
    "已結束": "已結束",
    "Pause": "暫停",
    "Off Duty": "下班",
    "Complete": "完工",
    "Finished": "已結束",
}
ACTIVE_STATUSES = {"", "作業中", "進行中", "ACTIVE", "Active", "active"}
ENDED_STATUSES = {"暫停", "下班", "完工", "已結束", "結束", "Pause", "Off Duty", "Complete", "Finished"}


def _text(value: Any, default: str = "") -> str:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value if value is not None else default).strip()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return default
        if pd.isna(value):
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or _text(value) == "":
            return None
        return int(float(str(value).strip()))
    except Exception:
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y", "on", "是", "勾選", "selected", "checked"}


def _normalize_df(df: pd.DataFrame | None) -> pd.DataFrame:
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if work.empty:
        return pd.DataFrame(columns=TIME_RECORD_COLUMNS)
    work = work.rename(columns={c: DISPLAY_TO_INTERNAL.get(str(c), str(c)) for c in work.columns})
    # Common old labels without bilingual text.
    alias = {
        "製令": "work_order", "工號": "employee_id", "姓名": "employee_name", "工段": "process_name",
        "開始時間戳": "start_timestamp", "結束時間戳": "end_timestamp",
        "開始日期": "start_date", "開始時間": "start_time",
        "結束日期": "end_date", "結束時間": "end_time",
        "備註": "remark", "工時小計": "work_hours",
        "ID": "id",
    }
    work = work.rename(columns={c: alias.get(str(c), str(c)) for c in work.columns})
    source_cols = set(str(c) for c in work.columns)
    for c in TIME_RECORD_COLUMNS:
        if c not in work.columns:
            work[c] = ""
    out = work[TIME_RECORD_COLUMNS]
    # Keep track of which columns came from the editor/import source.  This is
    # important for 01/02 edit-save: missing timestamp/date/time columns must not
    # be interpreted as the user clearing those fields.
    out.attrs["_spt_source_columns"] = source_cols
    return out


def _safe_df(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
    ensure_database()
    try:
        df = query_df(sql, tuple(params or ()))
        if isinstance(df, pd.DataFrame):
            return df.where(pd.notna(df), "").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame(columns=TIME_RECORD_COLUMNS)


def _safe_one(sql: str, params: Iterable[Any] | None = None) -> dict | None:
    ensure_database()
    try:
        row = query_one(sql, tuple(params or ()))
        return dict(row) if isinstance(row, dict) else None
    except Exception:
        return None




def _column_exists(table: str, column: str) -> bool:
    try:
        info = query_df(f"PRAGMA table_info({table})", ())
        if isinstance(info, pd.DataFrame) and "name" in info.columns:
            return column in set(info["name"].astype(str))
    except Exception:
        pass
    try:
        df = query_df("SELECT column_name AS name FROM information_schema.columns WHERE table_name=? AND column_name=? LIMIT 1", (table, column))
        return isinstance(df, pd.DataFrame) and not df.empty
    except Exception:
        return False


def _add_col(table: str, ddl: str) -> None:
    col = ddl.split()[0]
    if _column_exists(table, col):
        return
    try:
        execute(f"ALTER TABLE {table} ADD COLUMN {ddl}", ())
    except Exception:
        try:
            execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}", ())
        except Exception:
            pass


_TIME_RUNTIME_READY = False
_REST_PERIODS_CACHE: list[tuple[dt_time, dt_time]] | None = None
_REST_PERIODS_CACHE_AT = 0.0
_REST_PERIODS_TTL_SECONDS = 300.0

def _ensure_time_runtime_columns() -> None:
    global _TIME_RUNTIME_READY
    ensure_database()
    if _TIME_RUNTIME_READY:
        return
    cols = [
        "record_id TEXT", "record_key TEXT", "operation_id TEXT", "work_date TEXT", "work_order_no TEXT", "process_code TEXT",
        "work_minutes REAL DEFAULT 0", "raw_minutes REAL DEFAULT 0", "average_minutes REAL DEFAULT 0", "assembly_location TEXT",
        "group_key TEXT", "is_group_work INTEGER DEFAULT 0", "source TEXT", "updated_by TEXT", "deleted_at TEXT", "deleted_by TEXT",
        "delete_reason TEXT", "version INTEGER DEFAULT 1",
    ]
    for ddl in cols:
        _add_col("time_records", ddl)
    _TIME_RUNTIME_READY = True


def _active_predicate() -> str:
    ended = "('暫停','下班','完工','已結束','結束','Pause','Off Duty','Complete','Finished')"
    return f"(deleted_at IS NULL OR deleted_at='') AND (end_timestamp IS NULL OR end_timestamp='') AND COALESCE(status,'') NOT IN {ended}"


def _not_deleted_predicate() -> str:
    return "(deleted_at IS NULL OR deleted_at='')"


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 5000) -> int:
    """Read bounded integer environment settings for interactive page queries."""
    try:
        value = int(float(str(os.environ.get(name, default)).strip()))
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


def _today_end_text(day: str) -> str:
    try:
        return (pd.to_datetime(day).to_pydatetime() + timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        try:
            return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            return day


def _base_cols() -> str:
    return ", ".join(TIME_RECORD_COLUMNS)


def _parse_dt(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except Exception:
            continue
    try:
        ts = pd.to_datetime(text, errors="coerce")
        if pd.notna(ts):
            return ts.to_pydatetime()
    except Exception:
        pass
    return None


def _fmt_dt(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S") if isinstance(d, datetime) else ""


def _split_ts(ts: str) -> tuple[str, str]:
    dt = _parse_dt(ts)
    if not dt:
        return "", ""
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")


def _normalize_date_part(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    dt = _parse_dt(text)
    if dt:
        return dt.strftime("%Y-%m-%d")
    if len(text) >= 10:
        return text[:10].replace("/", "-")
    return text.replace("/", "-")


def _normalize_time_part(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if " " in text:
        text = text.split()[-1]
    # Pandas / Excel time values may arrive as 1900-01-01 08:30:00; after the
    # split above only the final time part remains.
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text[:8], fmt).strftime("%H:%M:%S")
        except Exception:
            pass
    parts = text.split(":")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    if len(parts) >= 3 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
        try:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(float(parts[2])):02d}"
        except Exception:
            return text
    return text


def _merge_date_time_parts(date_value: Any, time_value: Any) -> str:
    d = _normalize_date_part(date_value)
    t = _normalize_time_part(time_value)
    if d and t:
        return f"{d} {t}"
    if d:
        return d
    return ""


def _normalize_timestamp_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    dt = _parse_dt(text)
    if dt:
        return _fmt_dt(dt)
    return text


def _canonicalize_datetime_pair(
    row: dict[str, Any],
    before: dict[str, Any] | None,
    prefix: str,
    source_columns: set[str] | None = None,
) -> tuple[str, str, str]:
    """Keep timestamp and separate date/time columns in sync for 01/02 edits.

    Priority rules:
    1. If the editor changed date/time columns, rebuild timestamp from those values.
    2. If the editor changed timestamp, split it back to date/time.
    3. If only one side exists, derive the other side.
    4. If a caller did not provide any timing columns, keep the existing DB values.
    """
    source_columns = source_columns or set(row.keys())
    ts_col = f"{prefix}_timestamp"
    d_col = f"{prefix}_date"
    t_col = f"{prefix}_time"
    has_ts = ts_col in source_columns
    has_d = d_col in source_columns
    has_t = t_col in source_columns

    cur_ts = _normalize_timestamp_text(row.get(ts_col))
    cur_d = _normalize_date_part(row.get(d_col))
    cur_t = _normalize_time_part(row.get(t_col))

    old_ts = _normalize_timestamp_text((before or {}).get(ts_col))
    old_d = _normalize_date_part((before or {}).get(d_col))
    old_t = _normalize_time_part((before or {}).get(t_col))
    if old_ts and (not old_d or not old_t):
        sd, st = _split_ts(old_ts)
        old_d = old_d or sd
        old_t = old_t or st

    if before is not None and not (has_ts or has_d or has_t):
        return old_ts, old_d, old_t

    ts_changed = bool(before is not None and has_ts and cur_ts != old_ts)
    split_changed = bool(
        before is not None
        and ((has_d and cur_d != old_d) or (has_t and cur_t != old_t))
    )

    # V82 rule: when users edit the timestamp column in 01/02, the
    # timestamp is the authority.  Split date/time columns are helper/display
    # fields and must be regenerated from the edited timestamp.
    #
    # This must be checked before split_changed because Streamlit data_editor
    # sends the whole row back.  The row can contain stale start_date/start_time
    # values together with the newly edited start_timestamp; if split fields win,
    # the timestamp edit appears to be ignored and 01/02 drift apart.
    if ts_changed:
        ts = cur_ts
        d, t = _split_ts(ts)
        return ts, d, t

    if split_changed:
        # If only one split field was supplied, preserve the other one from DB.
        d = cur_d if has_d else old_d
        t = cur_t if has_t else old_t
        if d and t:
            ts = _merge_date_time_parts(d, t)
            sd, st = _split_ts(ts)
            return ts, sd or d, st or t
        if not d and not t:
            return "", "", ""
        return "", d, t

    # No detected edit.  Prefer timestamp when it exists because timestamp is
    # the canonical user-edit field in 01/02.  Split fields are regenerated from
    # it so historical rows do not keep stale start_date/start_time values.
    if cur_ts:
        d, t = _split_ts(cur_ts)
        return cur_ts, d, t
    if cur_d and cur_t:
        ts = _merge_date_time_parts(cur_d, cur_t)
        sd, st = _split_ts(ts)
        return ts, sd or cur_d, st or cur_t
    if before is not None:
        return old_ts, old_d, old_t
    return "", cur_d, cur_t


def _load_rest_periods() -> list[tuple[dt_time, dt_time]]:
    global _REST_PERIODS_CACHE, _REST_PERIODS_CACHE_AT
    now_perf = datetime.now().timestamp()
    if _REST_PERIODS_CACHE is not None and (now_perf - _REST_PERIODS_CACHE_AT) < _REST_PERIODS_TTL_SECONDS:
        return list(_REST_PERIODS_CACHE)
    try:
        df = query_df(
            """
            SELECT start_time, end_time FROM rest_periods
            WHERE COALESCE(is_active, active, 1)=1
            ORDER BY sort_order, start_time
            """,
            (),
        )
    except Exception:
        df = pd.DataFrame()
    periods: list[tuple[dt_time, dt_time]] = []
    for _, row in (df if isinstance(df, pd.DataFrame) else pd.DataFrame()).iterrows():
        st = _text(row.get("start_time")); et = _text(row.get("end_time"))
        try:
            s = datetime.strptime(st[:5], "%H:%M").time()
            e = datetime.strptime(et[:5], "%H:%M").time()
            periods.append((s, e))
        except Exception:
            continue
    if not periods:
        # Conservative default used only when 13 has no rest settings.
        for st, et in [("10:00", "10:10"), ("12:00", "13:00"), ("15:00", "15:10"), ("17:00", "17:30"), ("00:00", "00:00")]:
            try:
                s = datetime.strptime(st, "%H:%M").time(); e = datetime.strptime(et, "%H:%M").time()
                if s != e:
                    periods.append((s, e))
            except Exception:
                pass
    _REST_PERIODS_CACHE = list(periods)
    _REST_PERIODS_CACHE_AT = now_perf
    return periods


def _overlap_minutes(start: datetime, end: datetime, s: datetime, e: datetime) -> float:
    latest = max(start, s); earliest = min(end, e)
    if earliest <= latest:
        return 0.0
    return max(0.0, (earliest - latest).total_seconds() / 60.0)


def calculate_work_minutes(start_ts: Any, end_ts: Any) -> tuple[float, float]:
    start = _parse_dt(start_ts); end = _parse_dt(end_ts)
    if not start or not end or end <= start:
        return 0.0, 0.0
    raw = (end - start).total_seconds() / 60.0
    rest = 0.0
    periods = _load_rest_periods()
    cur_day = datetime(start.year, start.month, start.day)
    last_day = datetime(end.year, end.month, end.day)
    while cur_day <= last_day:
        for rs, re in periods:
            rs_dt = datetime.combine(cur_day.date(), rs)
            re_dt = datetime.combine(cur_day.date(), re)
            if re_dt <= rs_dt:
                re_dt += timedelta(days=1)
            rest += _overlap_minutes(start, end, rs_dt, re_dt)
        cur_day += timedelta(days=1)
    net = max(0.0, raw - rest)
    return raw, net


def _row_to_payload(
    row: dict[str, Any],
    recalc: bool = False,
    before: dict[str, Any] | None = None,
    source_columns: set[str] | None = None,
) -> dict[str, Any]:
    now = now_text()
    start_ts, start_date, start_time = _canonicalize_datetime_pair(row, before, "start", source_columns)
    end_ts, end_date, end_time = _canonicalize_datetime_pair(row, before, "end", source_columns)
    raw_minutes = _num(row.get("raw_minutes"))
    work_minutes = _num(row.get("work_minutes"))
    work_hours = _num(row.get("work_hours"))
    if recalc or (start_ts and end_ts and (work_minutes <= 0 and work_hours <= 0)):
        raw_minutes, work_minutes = calculate_work_minutes(start_ts, end_ts)
        work_hours = round(work_minutes / 60.0, 4)
    if work_minutes <= 0 and work_hours > 0:
        work_minutes = work_hours * 60.0
    status = _text(row.get("status")) or (END_ACTION_STATUS.get(_text(row.get("end_action")), "") if end_ts else "作業中")
    operation_id = _text(row.get("operation_id")) or _text(row.get("record_id")) or uuid.uuid4().hex
    emp = _text(row.get("employee_id")); wo = _text(row.get("work_order") or row.get("work_order_no")); proc = _text(row.get("process_name"))
    record_key = _text(row.get("record_key")) or f"{emp}|{wo}|{proc}|{operation_id}"
    return {
        "record_id": _text(row.get("record_id")) or operation_id,
        "record_key": record_key,
        "operation_id": operation_id,
        "status": status,
        "work_order": wo,
        "work_order_no": _text(row.get("work_order_no")) or wo,
        "part_no": _text(row.get("part_no")),
        "type_name": _text(row.get("type_name")),
        "process_code": _text(row.get("process_code")),
        "process_name": proc,
        "employee_id": emp,
        "employee_name": _text(row.get("employee_name")),
        "start_action": _text(row.get("start_action")) or "開始",
        "start_timestamp": start_ts,
        "end_action": _text(row.get("end_action")),
        "end_timestamp": end_ts,
        "remark": _text(row.get("remark")),
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "work_hours": round(work_hours, 4),
        "work_minutes": round(work_minutes, 2),
        "raw_minutes": round(raw_minutes, 2),
        "average_minutes": round(_num(row.get("average_minutes")) or work_minutes, 2),
        "assembly_location": _text(row.get("assembly_location")),
        "group_key": _text(row.get("group_key")) or f"{emp}|{proc}|{start_date}",
        "is_group_work": 1 if _truthy(row.get("is_group_work")) else 0,
        "source": _text(row.get("source")) or "streamlit",
        "created_at": _text(row.get("created_at")) or now,
        "updated_at": now,
        "updated_by": _text(row.get("updated_by")) or "system",
        "deleted_at": _text(row.get("deleted_at")),
        "deleted_by": _text(row.get("deleted_by")),
        "delete_reason": _text(row.get("delete_reason")),
        "version": int(_num(row.get("version"), 1)) or 1,
    }


def _cache_clear() -> None:
    global _REST_PERIODS_CACHE, _REST_PERIODS_CACHE_AT
    try:
        clear_query_cache()
    except Exception:
        pass
    # Runtime write paths may change settings/imported rows. Keep calculation settings fresh without querying Neon for every row.
    _REST_PERIODS_CACHE = None
    _REST_PERIODS_CACHE_AT = 0.0


def clear_today_records_fast_cache() -> None:
    _cache_clear()


def clear_today_finished_from_work_page() -> int:
    # UI-only refresh hook kept for compatibility. It must not delete or mutate data.
    _cache_clear()
    return 0


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    """Fast bounded record query used by 01/02/05/07/08.

    V89: do not use COALESCE(start_date, substr(start_timestamp,...)) on the
    main path.  That expression prevents PostgreSQL from using the normal
    start_date indexes and made 01/02 detail reads spin on large Neon tables.
    start_date is the maintained authority column; timestamp fallback is only
    attempted when the indexed query returns no rows.
    """
    _ensure_time_runtime_columns()

    def _build_sql(*, timestamp_fallback: bool = False) -> tuple[str, list[Any]]:
        sql = f"SELECT {_base_cols()} FROM time_records WHERE {_not_deleted_predicate()}"
        params: list[Any] = []
        if start_date:
            if timestamp_fallback:
                sql += " AND COALESCE(start_date,'')='' AND start_timestamp >= ?"
                params.append(f"{_text(start_date)[:10]} 00:00:00")
            else:
                sql += " AND start_date >= ?"
                params.append(_text(start_date)[:10])
        if end_date:
            if timestamp_fallback:
                # Exclusive next-day upper bound keeps the old timestamp-only rows
                # bounded without calling substr()/date() on every row.
                sql += " AND start_timestamp < ?"
                params.append(f"{_today_end_text(_text(end_date)[:10])} 00:00:00")
            else:
                sql += " AND start_date <= ?"
                params.append(_text(end_date)[:10])
        if employee_id:
            sql += " AND employee_id = ?"
            params.append(_text(employee_id))
        if work_order:
            sql += " AND (work_order = ? OR work_order_no = ?)"
            params.extend([_text(work_order), _text(work_order)])
        if not start_date and not end_date:
            sql += " ORDER BY id DESC LIMIT 1000"
        else:
            sql += " ORDER BY start_date DESC, start_time DESC, id DESC LIMIT 3000"
        return sql, params

    sql, params = _build_sql(timestamp_fallback=False)
    df = _safe_df(sql, tuple(params))
    if isinstance(df, pd.DataFrame) and (not df.empty or not (start_date or end_date)):
        return df

    # Legacy fallback: rows imported before start_date/start_time normalization.
    if start_date or end_date:
        fb_sql, fb_params = _build_sql(timestamp_fallback=True)
        return _safe_df(fb_sql, tuple(fb_params))
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:
    """Fast interactive query for 01 Today Records.

    V83: the previous query used ``start_date=? OR substr(start_timestamp,1,10)=?``.
    On Neon/PostgreSQL that OR + function path can bypass indexes and scan the
    whole time_records table when the operator presses 「重新整理今日明細」.
    This function now uses indexed start_date first, only falling back to a
    bounded timestamp range when no rows are found.  It also keeps interactive
    row counts small so table rendering cannot lock the page.
    """
    today = today_text()
    limit = _env_int("SPT_TODAY_RECORDS_REFRESH_MAX_ROWS", 300, min_value=50, max_value=2000)
    active_limit = _env_int("SPT_TODAY_ACTIVE_REFRESH_MAX_ROWS", 200, min_value=20, max_value=1000)

    if unfinished_only:
        # Current active work is usually small.  Keep this independent from
        # finished history so operators can recover even when old data is large.
        sql = f"SELECT {_base_cols()} FROM time_records WHERE {_active_predicate()} ORDER BY id DESC LIMIT {active_limit}"
        return _safe_df(sql, ())

    if not include_finished:
        sql = f"SELECT {_base_cols()} FROM time_records WHERE {_active_predicate()} AND (start_date=? OR start_date IS NULL OR start_date='') ORDER BY id DESC LIMIT {active_limit}"
        return _safe_df(sql, (today,))

    # Fast path: indexed start_date query.  Do not use OR/substr here.
    sql = f"SELECT {_base_cols()} FROM time_records WHERE {_not_deleted_predicate()} AND start_date=? ORDER BY id DESC LIMIT {limit}"
    df = _safe_df(sql, (today,))
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df

    # Legacy fallback for old rows that have timestamp but missing start_date.
    # It is bounded and only runs when the indexed query returns no rows.
    next_day = _today_end_text(today)
    fallback_limit = min(limit, 300)
    fallback_sql = (
        f"SELECT {_base_cols()} FROM time_records "
        f"WHERE {_not_deleted_predicate()} "
        "AND COALESCE(start_date,'')='' "
        "AND start_timestamp>=? AND start_timestamp<? "
        f"ORDER BY id DESC LIMIT {fallback_limit}"
    )
    return _safe_df(fallback_sql, (f"{today} 00:00:00", f"{next_day} 00:00:00"))


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None, work_order: str | None = None, **kwargs) -> pd.DataFrame:
    sql = f"SELECT {_base_cols()} FROM time_records WHERE {_active_predicate()}"
    params: list[Any] = []
    if employee_id:
        sql += " AND employee_id=?"; params.append(_text(employee_id))
    if employee_name:
        sql += " AND COALESCE(employee_name,'')=?"; params.append(_text(employee_name))
    if process_name:
        sql += " AND process_name=?"; params.append(_text(process_name))
    if start_date:
        sql += " AND start_date=?"; params.append(_text(start_date))
    if work_order:
        sql += " AND (work_order=? OR work_order_no=?)"; params.extend([_text(work_order), _text(work_order)])
    sql += " ORDER BY id DESC LIMIT 100"
    return _safe_df(sql, tuple(params))


def get_active_record(employee_id: str, employee_name: str | None = None) -> dict | None:
    df = get_active_records(employee_id=employee_id, employee_name=employee_name)
    if df.empty:
        return None
    return dict(df.iloc[0])


def _ids_from_df(df: pd.DataFrame) -> list[int]:
    ids: list[int] = []
    if not isinstance(df, pd.DataFrame) or df.empty:
        return ids
    for x in df.get("id", []):
        i = _int_or_none(x)
        if i is not None and i not in ids:
            ids.append(i)
    return ids


def get_active_group(record_id: int) -> pd.DataFrame:
    """Return the active synchronous work group for finishing one selected record.

    V75 site rule:
    Different work orders in the same process for the same employee are synchronous
    work.  Ending any one selected record must end every active same-employee,
    same-start-date, same-process record and average the Python-calculated work
    minutes across those records.  Neon only persists the final transaction.
    """
    rec = _safe_one(f"SELECT {_base_cols()} FROM time_records WHERE id=? LIMIT 1", (int(record_id),))
    if not rec:
        return pd.DataFrame(columns=TIME_RECORD_COLUMNS)
    if _text(rec.get("end_timestamp")) or _text(rec.get("deleted_at")):
        return pd.DataFrame([rec])
    emp = _text(rec.get("employee_id"))
    name = _text(rec.get("employee_name"))
    proc = _text(rec.get("process_name"))
    sdate = _text(rec.get("start_date"))
    if not emp or not proc:
        return pd.DataFrame([rec])
    df = get_active_records(employee_id=emp, employee_name=name or None, process_name=proc, start_date=sdate or None)
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame([rec])
    # Keep only same-process active records.  This intentionally includes
    # different work_order / work_order_no values because they are同步作業.
    try:
        if "process_name" in df.columns:
            df = df[df["process_name"].astype(str).str.strip() == proc].copy()
    except Exception:
        pass
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame([rec])
    return df.reset_index(drop=True)


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    return get_active_records(employee_id=employee_id, employee_name=employee_name, process_name=process_name, start_date=start_date, work_order=work_order)


def get_conflicting_active_records(employee_id: str, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    df = get_active_records(employee_id=employee_id, employee_name=employee_name, start_date=start_date)
    if df.empty or not process_name:
        return df
    return df[df["process_name"].astype(str) != _text(process_name)].reset_index(drop=True)


def refresh_active_records_for_employee(employee_id: str, employee_name: str | None = None) -> pd.DataFrame:
    _cache_clear()
    return get_active_records(employee_id=employee_id, employee_name=employee_name)


def _lookup_work_order(wo: str) -> dict:
    row = _safe_one(
        """
        SELECT work_order, work_order_no, part_no, type_name, assembly_location, customer, note
        FROM work_orders
        WHERE (deleted_at IS NULL OR deleted_at='') AND (work_order=? OR work_order_no=?)
        ORDER BY id DESC LIMIT 1
        """,
        (_text(wo), _text(wo)),
    )
    return row or {}


def _records_by_ids(ids: list[int]) -> dict[int, dict[str, Any]]:
    clean = [int(x) for x in ids if _int_or_none(x) is not None]
    if not clean:
        return {}
    ph = ",".join(["?"] * len(clean))
    df = _safe_df(f"SELECT {_base_cols()} FROM time_records WHERE id IN ({ph}) AND (deleted_at IS NULL OR deleted_at='')", tuple(clean))
    out: dict[int, dict[str, Any]] = {}
    if isinstance(df, pd.DataFrame) and not df.empty:
        for _, row in df.iterrows():
            rid = _int_or_none(row.get("id"))
            if rid is not None:
                out[int(rid)] = row.to_dict()
    return out


def _soft_pause_conflicts(ids: list[int], now: str) -> int:
    if not ids:
        return 0
    end_date, end_time = _split_ts(now)
    total = 0
    for rid in ids:
        rec = _safe_one(f"SELECT {_base_cols()} FROM time_records WHERE id=? LIMIT 1", (rid,)) or {}
        raw, net = calculate_work_minutes(rec.get("start_timestamp"), now)
        total += execute(
            """
            UPDATE time_records
            SET status='暫停', end_action='暫停', end_timestamp=?, end_date=?, end_time=?,
                raw_minutes=?, work_minutes=?, average_minutes=?, work_hours=?,
                remark=CASE WHEN COALESCE(remark,'')='' THEN ? ELSE remark || '；' || ? END,
                updated_at=?, updated_by='system', version=COALESCE(version,1)+1
            WHERE id=? AND (deleted_at IS NULL OR deleted_at='') AND (end_timestamp IS NULL OR end_timestamp='')
            """,
            (now, end_date, end_time, raw, net, net, round(net/60.0, 4), "系統自動暫停：同一人員切換不同作業", "系統自動暫停：同一人員切換不同作業", now, rid),
        )
    return total


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:
    _ensure_time_runtime_columns()
    now = now_text(); today = now[:10]
    emp_id = _text((employee or {}).get("employee_id")); emp_name = _text((employee or {}).get("employee_name"))
    wo_no = _text((work_order or {}).get("work_order") or (work_order or {}).get("work_order_no"))
    proc = _text(process_name)
    if not emp_id or not wo_no or not proc:
        raise ValueError("工號、製令、工段名稱不可空白。")
    duplicate = get_active_same_work(emp_id, wo_no, proc, today, emp_name)
    if not duplicate.empty:
        raise ValueError(f"禁止重複紀錄：此人員已有相同製令與工段正在計時：{wo_no} / {proc}")
    conflicts = get_conflicting_active_records(emp_id, proc, today, emp_name)
    conflict_ids = _ids_from_df(conflicts)
    if conflict_ids and not auto_pause_old:
        raise ValueError("此人員已有不同作業正在計時，請先暫停、完工或下班前一筆作業。")
    if conflict_ids and auto_pause_old:
        _soft_pause_conflicts(conflict_ids, now)
    wo_info = {**_lookup_work_order(wo_no), **(work_order or {})}
    opid = uuid.uuid4().hex
    record_key = f"{emp_id}|{wo_no}|{proc}|{opid}"
    row = {
        "record_id": opid,
        "record_key": record_key,
        "operation_id": opid,
        "status": "作業中",
        "work_order": wo_no,
        "work_order_no": wo_no,
        "part_no": _text(wo_info.get("part_no")),
        "type_name": _text(wo_info.get("type_name")),
        "process_name": proc,
        "employee_id": emp_id,
        "employee_name": emp_name,
        "start_action": "開始",
        "start_timestamp": now,
        "remark": _text(remark),
        "start_date": today,
        "start_time": now[11:19],
        "assembly_location": _text(wo_info.get("assembly_location")),
        "group_key": f"{emp_id}|{proc}|{today}|{now[11:16]}",
        "source": "v63_neon_runtime",
        "created_at": now,
        "updated_at": now,
    }
    payload = _row_to_payload(row, recalc=False)
    cols = [c for c in TIME_RECORD_COLUMNS if c != "id"]
    sql = f"INSERT INTO time_records ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
    rid = execute(sql, tuple(payload.get(c, "") for c in cols))
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'START_WORK', 'time_records', ?, ?, '', 'INFO')",
            (now, "SYSTEM", str(rid), f"{emp_name} 開始 {wo_no} / {proc}"),
        )
    except Exception:
        pass
    _cache_clear()
    return int(rid or 0)


def finish_work(record_id: int, end_action: str = "完工", remark: str = "", finish_parallel_group: bool = True) -> int:
    _ensure_time_runtime_columns()
    rid = int(record_id)
    now = now_text(); end_date, end_time = _split_ts(now)
    group_df = get_active_group(rid) if finish_parallel_group else pd.DataFrame()
    ids = _ids_from_df(group_df) if isinstance(group_df, pd.DataFrame) and not group_df.empty else [rid]
    action = _text(end_action) or "完工"
    status = END_ACTION_STATUS.get(action, action)
    # Fetch all active records in one lightweight read; all duration/rest/average calculations stay in Python.
    records = _records_by_ids(ids)
    raw_net: dict[int, tuple[float, float]] = {}
    for i in ids:
        rec = records.get(int(i), {})
        raw_net[i] = calculate_work_minutes(rec.get("start_timestamp"), now)
    if len(ids) > 1:
        total_net = sum(v[1] for v in raw_net.values())
        avg_net = round(total_net / max(len(ids), 1), 2)
    else:
        avg_net = None
    ops: list[tuple[str, tuple[Any, ...]]] = []
    for i in ids:
        raw, net = raw_net.get(i, (0.0, 0.0))
        final_net = avg_net if avg_net is not None else net
        msg = _text(remark)
        ops.append((
            """
            UPDATE time_records
            SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?,
                raw_minutes=?, work_minutes=?, average_minutes=?, work_hours=?, is_group_work=?,
                remark=CASE WHEN ?='' THEN remark WHEN COALESCE(remark,'')='' THEN ? ELSE remark || '；' || ? END,
                updated_at=?, updated_by='system', version=COALESCE(version,1)+1
            WHERE id=? AND (deleted_at IS NULL OR deleted_at='') AND (end_timestamp IS NULL OR end_timestamp='')
            """,
            (status, action, now, end_date, end_time, round(raw, 2), round(final_net, 2), round(final_net, 2), round(final_net / 60.0, 4), 1 if len(ids) > 1 else 0, msg, msg, msg, now, i),
        ))
    counts = execute_transaction(ops, mark_changed=True, reason="finish_work", source_sql="finish_work")
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'FINISH_WORK', 'time_records', ?, ?, ?, 'INFO')",
            (now, "SYSTEM", str(rid), f"{action} 工時紀錄", f"ids={ids}"),
        )
    except Exception:
        pass
    _cache_clear()
    return int(sum(int(x or 0) for x in counts) or len(ids))


def delete_time_records(record_ids: Iterable[Any], reason: str = "管理員刪除工時紀錄") -> int:
    _ensure_time_runtime_columns()
    ids: list[int] = []
    for x in record_ids or []:
        i = _int_or_none(x)
        if i is not None and i > 0 and i not in ids:
            ids.append(i)
    if not ids:
        return 0
    now = now_text(); total = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i+100]
        ph = ",".join(["?"] * len(chunk))
        total += execute(
            f"""
            UPDATE time_records
            SET deleted_at=?, deleted_by='admin', delete_reason=?, updated_at=?, version=COALESCE(version,1)+1
            WHERE id IN ({ph}) AND (deleted_at IS NULL OR deleted_at='')
            """,
            tuple([now, _text(reason), now] + chunk),
        )
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'SOFT_DELETE', 'time_records', ?, ?, ?, 'WARN')",
            (now, "admin", ",".join(map(str, ids[:50])), f"soft delete {len(ids)} time records", _text(reason)),
        )
    except Exception:
        pass
    _cache_clear()
    return int(total or len(ids))


def _checked_ids_from_editor(editor_df: pd.DataFrame, delete_column: str = "刪除 / Delete") -> list[int]:
    df = _normalize_df(editor_df)
    if df.empty:
        return []
    original = editor_df if isinstance(editor_df, pd.DataFrame) else pd.DataFrame()
    del_col = next((c for c in [delete_column, "刪除 / Delete", "刪除", "Delete", "_delete"] if c in original.columns), "")
    if not del_col:
        return []
    id_col = next((c for c in ["id", "ID / ID", "ID", "紀錄編號"] if c in original.columns), "")
    if not id_col:
        return []
    return [i for i in (_int_or_none(x) for x in original.loc[original[del_col].map(_truthy), id_col].tolist()) if i is not None]


def delete_time_records_from_editor_df(editor_df: pd.DataFrame, delete_column: str = "刪除 / Delete", reason: str = "01 管理員維護表刪除") -> int:
    return delete_time_records(_checked_ids_from_editor(editor_df, delete_column), reason=reason)


def delete_time_records_from_02_history_editor(editor_df: pd.DataFrame, record_ids: list[int] | None = None, delete_column: str = "刪除 / Delete", reason: str = "02 歷史紀錄刪除") -> dict:
    ids = [int(x) for x in (record_ids or []) if _int_or_none(x) is not None] or _checked_ids_from_editor(editor_df, delete_column)
    if not ids:
        return {"ok": False, "deleted_count": 0, "ids": [], "message": "沒有勾選可刪除的紀錄"}
    n = delete_time_records(ids, reason=reason)
    return {"ok": True, "deleted_count": int(n), "ids": ids, "version": "V63"}


def _insert_or_update_payload(
    payload: dict[str, Any],
    record_id: int | None = None,
    changed_fields: Iterable[str] | None = None,
) -> tuple[str, int]:
    """Insert or update one time record.

    V82 fix: admin/history editors must not UPDATE every column of every
    visible row.  Updating the full row makes 02 Save/Recalc very slow on Neon
    and can hit statement_timeout / QueryCanceled when the editor contains many
    rows.  For existing records, update only fields that actually changed plus
    updated_at/updated_by/version.
    """
    cols = [c for c in TIME_RECORD_COLUMNS if c != "id"]
    if record_id:
        allowed = set(TIME_RECORD_COLUMNS) - {"id", "created_at", "version"}
        if changed_fields is None:
            update_cols = [c for c in cols if c in allowed]
        else:
            seen: set[str] = set()
            update_cols = []
            for c in changed_fields:
                c = str(c)
                if c in allowed and c not in seen:
                    update_cols.append(c)
                    seen.add(c)
        # Always update audit fields for real edits.  Do not run a no-op UPDATE.
        if update_cols:
            for c in ["updated_at", "updated_by"]:
                if c in allowed and c not in update_cols:
                    update_cols.append(c)
        if not update_cols:
            return "updated", 0
        assignments = ", ".join([f"{c}=?" for c in update_cols] + ["version=COALESCE(version,1)+1"])
        vals = [payload.get(c, "") for c in update_cols] + [record_id]
        n = execute(f"UPDATE time_records SET {assignments} WHERE id=? AND (deleted_at IS NULL OR deleted_at='')", tuple(vals))
        return "updated", int(n or 0)
    sql = f"INSERT INTO time_records ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
    new_id = execute(sql, tuple(payload.get(c, "") for c in cols))
    return "inserted", int(new_id or 0)


_V73_AUDIT_FIELDS = [
    "status", "work_order", "work_order_no", "part_no", "type_name", "process_code", "process_name",
    "employee_id", "employee_name", "start_action", "start_timestamp", "end_action", "end_timestamp",
    "remark", "start_date", "start_time", "end_date", "end_time", "work_hours", "work_minutes",
    "raw_minutes", "average_minutes", "assembly_location", "group_key", "is_group_work", "source",
]
_V73_TIMING_FIELDS = {"start_timestamp", "end_timestamp", "start_date", "start_time", "end_date", "end_time"}
_V73_GROUP_FIELDS = {"employee_id", "employee_name", "process_name", "start_date", "start_timestamp", "end_timestamp", "group_key"}


def _same_value_for_audit(a: Any, b: Any) -> bool:
    ta = _text(a)
    tb = _text(b)
    if ta == tb:
        return True
    try:
        return abs(float(ta or 0) - float(tb or 0)) < 0.0001
    except Exception:
        return False


def _diff_payload(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, dict[str, str]]:
    if not before:
        return {c: {"old": "", "new": _text(after.get(c))} for c in _V73_AUDIT_FIELDS if _text(after.get(c))}
    diff: dict[str, dict[str, str]] = {}
    for c in _V73_AUDIT_FIELDS:
        if not _same_value_for_audit((before or {}).get(c), after.get(c)):
            diff[c] = {"old": _text((before or {}).get(c)), "new": _text(after.get(c))}
    return diff


def _load_existing_records_map(ids: list[int]) -> dict[int, dict[str, Any]]:
    clean = [int(x) for x in ids if _int_or_none(x) is not None]
    if not clean:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for i in range(0, len(clean), 200):
        chunk = clean[i:i + 200]
        ph = ",".join(["?"] * len(chunk))
        df = _safe_df(f"SELECT {_base_cols()} FROM time_records WHERE id IN ({ph}) AND (deleted_at IS NULL OR deleted_at='')", tuple(chunk))
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                rid = _int_or_none(row.get("id"))
                if rid is not None:
                    out[int(rid)] = row.to_dict()
    return out


def _audit_time_record_change(record_id: int | None, action_type: str, changed: dict[str, dict[str, str]], source: str) -> None:
    if not changed:
        return
    now = now_text()
    try:
        detail = json.dumps({"source": source, "changed_fields": changed}, ensure_ascii=False, default=str)[:6000]
    except Exception:
        detail = str({"source": source, "changed_fields": changed})[:6000]
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, ?, 'time_records', ?, ?, ?, 'INFO')",
            (now, "SYSTEM", action_type, str(record_id or ""), f"工時紀錄已修改：{record_id or ''}", detail),
        )
    except Exception:
        pass


def _related_group_ids_from_record(record: dict[str, Any]) -> list[int]:
    rid = _int_or_none(record.get("id"))
    ids: list[int] = []
    group_key = _text(record.get("group_key"))
    if group_key:
        df = _safe_df(f"SELECT id FROM time_records WHERE group_key=? AND {_not_deleted_predicate()}", (group_key,))
        if isinstance(df, pd.DataFrame) and not df.empty and "id" in df.columns:
            ids = [i for i in (_int_or_none(x) for x in df["id"].tolist()) if i is not None]
    if len(ids) <= 1:
        emp = _text(record.get("employee_id")); proc = _text(record.get("process_name")); sdate = _text(record.get("start_date"))
        start_dt = _parse_dt(record.get("start_timestamp"))
        if emp and proc and sdate and start_dt is not None:
            cand = _safe_df(
                f"SELECT id, start_timestamp FROM time_records WHERE employee_id=? AND process_name=? AND start_date=? AND {_not_deleted_predicate()} LIMIT 100",
                (emp, proc, sdate),
            )
            ids = []
            if isinstance(cand, pd.DataFrame) and not cand.empty:
                for _, row in cand.iterrows():
                    d = _parse_dt(row.get("start_timestamp"))
                    i = _int_or_none(row.get("id"))
                    if d is not None and i is not None and abs((d - start_dt).total_seconds()) <= 180:
                        ids.append(i)
    if rid is not None and rid not in ids:
        ids.append(rid)
    return sorted({int(x) for x in ids if _int_or_none(x) is not None})


def _sync_parallel_group_after_edit(seed_ids: list[int]) -> int:
    if not seed_ids:
        return 0
    existing = _load_existing_records_map(seed_ids)
    group_ids: set[int] = set()
    for rec in existing.values():
        group_ids.update(_related_group_ids_from_record(rec))
    if len(group_ids) <= 1:
        return 0
    records = _load_existing_records_map(sorted(group_ids))
    ended_ids = [i for i, rec in records.items() if _text(rec.get("start_timestamp")) and _text(rec.get("end_timestamp"))]
    if len(ended_ids) <= 1:
        return 0
    nets: dict[int, tuple[float, float]] = {}
    for i in ended_ids:
        rec = records.get(i, {})
        nets[i] = calculate_work_minutes(rec.get("start_timestamp"), rec.get("end_timestamp"))
    total_net = sum(v[1] for v in nets.values())
    avg_net = round(total_net / max(len(ended_ids), 1), 2)
    now = now_text()
    ops: list[tuple[str, tuple[Any, ...]]] = []
    for i in ended_ids:
        raw, _net = nets.get(i, (0.0, 0.0))
        ops.append((
            """
            UPDATE time_records
            SET raw_minutes=?, work_minutes=?, average_minutes=?, work_hours=?, is_group_work=1,
                updated_at=?, updated_by='system', version=COALESCE(version,1)+1
            WHERE id=? AND (deleted_at IS NULL OR deleted_at='')
            """,
            (round(raw, 2), avg_net, avg_net, round(avg_net / 60.0, 4), now, i),
        ))
    counts = execute_transaction(ops, mark_changed=True, reason="sync_parallel_group_after_edit", source_sql="sync_parallel_group_after_edit")
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'SYNC_PARALLEL_GROUP', 'time_records', ?, ?, ?, 'INFO')",
            (now, "SYSTEM", ",".join(map(str, ended_ids[:50])), f"同步作業平均重算 {len(ended_ids)} 筆", f"ids={ended_ids}; average_minutes={avg_net}"),
        )
    except Exception:
        pass
    return int(sum(int(x or 0) for x in counts) or len(ended_ids))


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:
    _ensure_time_runtime_columns()
    work = _normalize_df(df)
    if work.empty:
        return 0
    ids = []
    for _, row in work.iterrows():
        rid = _int_or_none(row.get("id"))
        if rid is not None and rid > 0:
            ids.append(rid)
    existing_map = _load_existing_records_map(sorted(set(ids)))
    source_columns = set(work.attrs.get("_spt_source_columns", set(work.columns)))
    count = 0
    changed_or_group_seed_ids: list[int] = []
    for _, row in work.iterrows():
        rd = dict(row)
        if not _text(rd.get("employee_id")) or not _text(rd.get("work_order") or rd.get("work_order_no")) or not _text(rd.get("process_name")):
            continue
        rid = _int_or_none(rd.get("id"))
        before = existing_map.get(int(rid)) if rid is not None else None
        # 02/01 編輯儲存要遵守重算原則：只要開始/結束日期時間被改，就在前台 Python service 重算，Neon 只做交易寫入。
        preliminary = _row_to_payload(rd, recalc=False, before=before, source_columns=source_columns)
        diff0 = _diff_payload(before, preliminary)
        timing_changed = bool(_V73_TIMING_FIELDS.intersection(diff0.keys()))
        group_changed = bool(_V73_GROUP_FIELDS.intersection(diff0.keys()))
        should_recalc = bool(recalc_edited_timestamps or timing_changed)
        payload = _row_to_payload(rd, recalc=should_recalc, before=before, source_columns=source_columns)
        diff = _diff_payload(before, payload)
        if before and not diff:
            continue
        kind, n = _insert_or_update_payload(payload, rid, changed_fields=diff.keys())
        saved_id = int(rid or n or 0)
        if n or (kind == "updated" and before is not None):
            # db_service.execute may return 0 for SQLite UPDATE rowcount even when the row was updated.
            # Count a detected changed existing row as saved so 01/02 does not show a false "0 筆" result.
            count += 1
            _audit_time_record_change(saved_id, "UPDATE_TIME_RECORD" if kind == "updated" else "INSERT_TIME_RECORD", diff, "01/02_edit_save")
            if saved_id and (should_recalc or group_changed or _text(payload.get("group_key"))):
                changed_or_group_seed_ids.append(saved_id)
    if changed_or_group_seed_ids:
        _sync_parallel_group_after_edit(changed_or_group_seed_ids)
    _cache_clear()
    return int(count)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:
    _ensure_time_runtime_columns()
    work = _normalize_df(df)
    result = {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}
    source_columns = set(work.attrs.get("_spt_source_columns", set(work.columns)))
    for idx, row in work.iterrows():
        rd = dict(row)
        if not _text(rd.get("employee_id")) or not _text(rd.get("work_order") or rd.get("work_order_no")) or not _text(rd.get("process_name")) or not _text(rd.get("start_timestamp") or rd.get("start_date")):
            result["skipped"] += 1
            continue
        try:
            rd["source"] = source
            payload = _row_to_payload(rd, recalc=bool(recalc), before=None, source_columns=source_columns)
            rid = _int_or_none(rd.get("id"))
            if not rid and payload.get("record_key"):
                old = _safe_one("SELECT id FROM time_records WHERE record_key=? AND (deleted_at IS NULL OR deleted_at='') LIMIT 1", (payload["record_key"],))
                rid = _int_or_none((old or {}).get("id"))
            kind, n = _insert_or_update_payload(payload, rid)
            if kind == "inserted":
                result["inserted"] += 1 if n else 0
            else:
                result["updated"] += 1 if n else 0
        except Exception as exc:
            result["skipped"] += 1
            result["errors"].append(f"第 {idx+1} 筆失敗：{exc}")
    _cache_clear()
    return result


def recalculate_time_records(record_ids: Iterable[Any]) -> int:
    _ensure_time_runtime_columns()
    ids = []
    for x in record_ids or []:
        i = _int_or_none(x)
        if i is not None and i > 0 and i not in ids:
            ids.append(i)
    count = 0
    now = now_text()
    for rid in ids:
        rec = _safe_one(f"SELECT {_base_cols()} FROM time_records WHERE id=? AND (deleted_at IS NULL OR deleted_at='') LIMIT 1", (rid,))
        if not rec:
            continue
        raw, net = calculate_work_minutes(rec.get("start_timestamp"), rec.get("end_timestamp"))
        count += execute(
            """
            UPDATE time_records
            SET raw_minutes=?, work_minutes=?, average_minutes=?, work_hours=?, updated_at=?, version=COALESCE(version,1)+1
            WHERE id=? AND (deleted_at IS NULL OR deleted_at='')
            """,
            (round(raw, 2), round(net, 2), round(net, 2), round(net/60.0, 4), now, rid),
        )
    _cache_clear()
    return int(count)


def load_daily_record_summary_sql(work_date: str):
    df = load_records(str(work_date), str(work_date))
    if df.empty:
        return pd.DataFrame()
    if "work_minutes" not in df.columns:
        df["work_minutes"] = 0.0
    out = df.groupby(["employee_id", "employee_name"], dropna=False)["work_minutes"].sum().reset_index()
    out["work_hours"] = out["work_minutes"].astype(float) / 60.0
    return out


def audit_v63_time_record_runtime_consolidated() -> dict[str, Any]:
    return {
        "version": "V63_TIME_RECORD_RUNTIME_CONSOLIDATED",
        "legacy_patch_stack_removed": True,
        "neon_runtime_authority": bool(is_postgres_enabled()),
        "soft_delete_only": True,
        "parallel_finish_average_supported": True,
        "ui_css_changed": False,
    }
