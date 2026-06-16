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
import hashlib
import time as _time
from datetime import datetime, timedelta, time as dt_time
from typing import Any, Callable, Iterable

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
    # V96: db_service has a targeted invalidator in current builds.  Import it
    # opportunistically so 01 read refreshes do not evict master/settings caches.
    from services.db_service import _v30_clear_cache_for_tables as _spt_clear_cache_for_tables
except Exception:  # pragma: no cover
    _spt_clear_cache_for_tables = None  # type: ignore
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
    # Preserve page-side metadata such as per-row changed columns.  01 admin
    # maintenance uses this to avoid lost-update overwrites when two PCs edit
    # the same visible row from different sessions.
    try:
        out.attrs.update(getattr(work, "attrs", {}) or {})
    except Exception:
        pass
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
_IMPORT_LOOKUP_INDEX_READY = False
_REST_PERIODS_CACHE: list[tuple[dt_time, dt_time]] | None = None
_REST_PERIODS_CACHE_AT = 0.0
_REST_PERIODS_TTL_SECONDS = 300.0

def _ensure_time_runtime_columns() -> None:
    global _TIME_RUNTIME_READY
    # V300.22：這個函式位在 01/02 熱路徑。舊版即使 runtime 欄位已確認，
    # 仍會先呼叫 ensure_database()，在 Neon 上可能觸發 schema/index 檢查並拖慢
    # 「載入維護表格 / 今日明細 / 刪除 / 存檔」。先檢查記憶體旗標，已完成就直接返回。
    if _TIME_RUNTIME_READY:
        return
    ensure_database()
    cols = [
        "record_id TEXT", "record_key TEXT", "operation_id TEXT", "work_date TEXT", "work_order_no TEXT", "process_code TEXT",
        "work_minutes REAL DEFAULT 0", "raw_minutes REAL DEFAULT 0", "average_minutes REAL DEFAULT 0", "assembly_location TEXT",
        "group_key TEXT", "is_group_work INTEGER DEFAULT 0", "source TEXT", "updated_by TEXT", "deleted_at TEXT", "deleted_by TEXT",
        "delete_reason TEXT", "version INTEGER DEFAULT 1",
    ]
    for ddl in cols:
        _add_col("time_records", ddl)
    # V300.25 concurrency guard for 20 PCs / 50+ operators:
    # - same employee + same work order + same process + same date may only have
    #   one active row.  This protects against two PCs pressing Start together.
    # - non-unique active lookup index keeps duplicate/conflict checks fast.
    # If old duplicate active rows already exist, the unique index creation may
    # fail; the atomic INSERT ... WHERE NOT EXISTS in start_work still protects
    # new writes.  Never block page startup because of legacy dirty data.
    try:
        execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_v30025_time_active_same_work_guard
            ON time_records(employee_id, work_order_no, process_name, start_date)
            WHERE (deleted_at IS NULL OR deleted_at='') AND (end_timestamp IS NULL OR end_timestamp='')
            """,
            (),
        )
    except Exception:
        pass
    try:
        execute(
            """
            CREATE INDEX IF NOT EXISTS idx_v30025_time_active_employee_guard
            ON time_records(employee_id, start_date, process_name, id DESC)
            WHERE (deleted_at IS NULL OR deleted_at='') AND (end_timestamp IS NULL OR end_timestamp='')
            """,
            (),
        )
    except Exception:
        pass
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
        # V300.90: do not create a broad fallback group_key such as
        # employee|process|date for every row.  That legacy fallback made 02
        # history recalculation treat all same-day same-process rows as one
        # simultaneous-work group.  Only keep an explicit group_key supplied by
        # 01 Finish Work / import parallel detection, or preserve the existing
        # value when editing an old row.
        "group_key": _text(row.get("group_key")) or _text((before or {}).get("group_key")),
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
        if callable(_spt_clear_cache_for_tables):
            _spt_clear_cache_for_tables({"time_records", "system_logs"})
        else:
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

    # V300.26 Neon Free compute guard:
    # The previous Start path queried active same-work and conflicting active work
    # separately.  For 20 PCs / 50+ operators this doubles SELECT traffic on the
    # hottest button.  Read this employee's active rows for today once, then split
    # duplicate/conflict checks in Python.  The atomic INSERT ... WHERE NOT EXISTS
    # below remains the final authority, so read/write correctness is unchanged.
    active_today = get_active_records(employee_id=emp_id, start_date=today)
    duplicate = pd.DataFrame()
    conflicts = pd.DataFrame()
    if isinstance(active_today, pd.DataFrame) and not active_today.empty:
        try:
            proc_mask = active_today.get("process_name", pd.Series([], dtype=str)).fillna("").astype(str).str.strip() == proc
            wo_values = active_today.get("work_order", pd.Series([], dtype=str)).fillna("").astype(str).str.strip()
            wo_no_values = active_today.get("work_order_no", pd.Series([], dtype=str)).fillna("").astype(str).str.strip()
            wo_mask = (wo_values == wo_no) | (wo_no_values == wo_no)
            duplicate = active_today.loc[proc_mask & wo_mask].copy()
            conflicts = active_today.loc[~proc_mask].copy()
        except Exception:
            duplicate = get_active_same_work(emp_id, wo_no, proc, today, None)
            conflicts = get_conflicting_active_records(emp_id, proc, today, None)
    if isinstance(duplicate, pd.DataFrame) and not duplicate.empty:
        raise ValueError(f"禁止重複紀錄：此人員已有相同製令與工段正在計時：{wo_no} / {proc}")
    conflict_ids = _ids_from_df(conflicts)
    if conflict_ids and not auto_pause_old:
        raise ValueError("此人員已有不同作業正在計時，請先暫停、完工或下班前一筆作業。")
    if conflict_ids and auto_pause_old:
        _soft_pause_conflicts(conflict_ids, now)

    wo_info = dict(work_order or {})
    # Avoid a second work_orders lookup when the 01 page already supplied the
    # selected master row.  If metadata is incomplete, keep the old lookup path so
    # display/history fields remain complete.
    if not all(_text(wo_info.get(k)) for k in ("part_no", "type_name", "assembly_location")):
        wo_info = {**_lookup_work_order(wo_no), **wo_info}
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
    # V300.25: make Start idempotent under concurrent PCs.  The old path did a
    # SELECT duplicate check and then INSERT; two browsers could both pass the
    # SELECT and create duplicate active rows.  This INSERT only succeeds if no
    # active same-work row and no active different-process row appeared between
    # the earlier checks and this write.
    values_sql = ", ".join(["?"] * len(cols))
    sql = f"""
        INSERT INTO time_records ({', '.join(cols)})
        SELECT {values_sql}
        WHERE NOT EXISTS (
            SELECT 1 FROM time_records
            WHERE employee_id=?
              AND (work_order=? OR work_order_no=?)
              AND process_name=?
              AND start_date=?
              AND (deleted_at IS NULL OR deleted_at='')
              AND (end_timestamp IS NULL OR end_timestamp='')
            LIMIT 1
        )
        AND NOT EXISTS (
            SELECT 1 FROM time_records
            WHERE employee_id=?
              AND start_date=?
              AND process_name<>?
              AND (deleted_at IS NULL OR deleted_at='')
              AND (end_timestamp IS NULL OR end_timestamp='')
            LIMIT 1
        )
    """
    params = tuple(payload.get(c, "") for c in cols) + (emp_id, wo_no, wo_no, proc, today, emp_id, today, proc)
    try:
        rid = execute(sql, params)
    except Exception as exc:
        # PostgreSQL unique index violation is another safe duplicate guard.
        raise ValueError(f"禁止重複紀錄：此人員已有同日進行中的工時紀錄，請重新整理後再操作。原始訊息：{exc}") from exc
    if not rid:
        raise ValueError("禁止重複紀錄：此人員已有同日進行中的相同製令/工段或不同工段紀錄，請重新整理後再操作。")
    try:
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'START_WORK', 'time_records', ?, ?, '', 'INFO')",
            (now, "SYSTEM", str(rid), f"{emp_name} 開始 {wo_no} / {proc}"),
        )
    except Exception:
        pass
    _cache_clear()
    return int(rid or 0)


def _v30045_parallel_average_from_records(
    records: dict[int, dict[str, Any]],
    ids: list[int],
    *,
    group_end_ts: Any | None = None,
) -> dict[str, Any]:
    """Calculate synchronized-work average from earliest start to one group end.

    Site rule V300.45:
    If multiple synchronous work records are ended/recalculated together, the
    subtotal written back to every row must be:

        (group end time - earliest start time, minus rest periods) / row count

    It must NOT be the average of each row's own individual duration, otherwise
    records started later incorrectly receive the same longer subtotal.
    """
    clean_ids: list[int] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    for x in ids or []:
        rid = _int_or_none(x)
        if rid is None or rid in clean_ids:
            continue
        rec = records.get(int(rid), {})
        st = _parse_dt(rec.get("start_timestamp"))
        if st is None:
            continue
        clean_ids.append(int(rid))
        starts.append(st)
        explicit_end = _parse_dt(group_end_ts) if group_end_ts is not None else None
        if explicit_end is not None:
            ends.append(explicit_end)
        else:
            et = _parse_dt(rec.get("end_timestamp"))
            if et is not None:
                ends.append(et)
    if not clean_ids or not starts or not ends:
        return {"ids": clean_ids, "raw_total": 0.0, "net_total": 0.0, "raw_each": 0.0, "net_each": 0.0, "start_ts": "", "end_ts": ""}
    start_dt = min(starts)
    end_dt = max(ends)
    raw_total, net_total = calculate_work_minutes(_fmt_dt(start_dt), _fmt_dt(end_dt))
    n = max(len(clean_ids), 1)
    return {
        "ids": clean_ids,
        "raw_total": round(raw_total, 2),
        "net_total": round(net_total, 2),
        "raw_each": round(raw_total / n, 2),
        "net_each": round(net_total / n, 2),
        "start_ts": _fmt_dt(start_dt),
        "end_ts": _fmt_dt(end_dt),
    }


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
    parallel_average = _v30045_parallel_average_from_records(records, ids, group_end_ts=now) if len(ids) > 1 else {}
    ops: list[tuple[str, tuple[Any, ...]]] = []
    for i in ids:
        if len(ids) > 1:
            raw = float(parallel_average.get("raw_each") or 0.0)
            final_net = float(parallel_average.get("net_each") or 0.0)
        else:
            rec = records.get(int(i), {})
            raw, final_net = calculate_work_minutes(rec.get("start_timestamp"), now)
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
        detail = f"ids={ids}"
        if len(ids) > 1:
            detail += f"; group_start={parallel_average.get('start_ts')}; group_end={parallel_average.get('end_ts')}; group_net={parallel_average.get('net_total')}; average_minutes={parallel_average.get('net_each')}"
        execute(
            "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'FINISH_WORK', 'time_records', ?, ?, ?, 'INFO')",
            (now, "SYSTEM", str(rid), f"{action} 工時紀錄", detail),
        )
    except Exception:
        pass
    _cache_clear()
    updated_count = int(sum(int(x or 0) for x in counts))
    # V300.25: under concurrent finish clicks, PostgreSQL rowcount 0 means another
    # PC already ended the row.  Do not report a false success count, otherwise
    # operators think their click wrote data when it did not.  SQLite fallback keeps
    # the old compatibility behavior for local tests where rowcount can be flaky.
    if is_postgres_enabled():
        return updated_count
    return int(updated_count or len(ids))


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


def _v30083_import_relevant_diff(before: dict[str, Any] | None, after: dict[str, Any], source_columns: set[str] | None = None) -> dict[str, dict[str, str]]:
    """Return only meaningful Excel/Paste import changes.

    V300.83: large 02 history imports could finish Neon record_key lookup but
    then appear frozen because every existing row was treated as changed by
    internal service-only fields such as ``source`` or import-generated empty
    ``group_key``.  That forced thousands of UPDATEs even when the Excel file
    was just a duplicate import.

    For imports, compare user/business fields and recalculated time fields only.
    Do not update an existing row merely because the import source label changed,
    and do not clear an existing group_key unless this batch positively detected
    the row as simultaneous work.
    """
    if not before:
        return {c: {"old": "", "new": _text(after.get(c))} for c in _V73_AUDIT_FIELDS if _text(after.get(c))}

    source_columns = set(source_columns or set())
    base_fields = [
        "status", "work_order", "work_order_no", "part_no", "type_name",
        "process_code", "process_name", "employee_id", "employee_name",
        "start_action", "start_timestamp", "end_action", "end_timestamp",
        "remark", "start_date", "start_time", "end_date", "end_time",
        "work_hours", "work_minutes", "raw_minutes", "average_minutes",
        "assembly_location",
    ]
    compare_fields: list[str] = []
    seen: set[str] = set()
    for c in base_fields:
        if c in TIME_RECORD_COLUMNS and c not in seen:
            compare_fields.append(c); seen.add(c)

    # Keep simultaneous-work fixes from V300.79, but do not let a normal import
    # blank out legacy grouping or update every row only because group_key differs.
    after_group = _text(after.get("group_key"))
    after_is_group = _truthy(after.get("is_group_work"))
    before_is_group = _truthy((before or {}).get("is_group_work"))
    if after_group or after_is_group or before_is_group or "group_key" in source_columns or "is_group_work" in source_columns:
        for c in ["group_key", "is_group_work"]:
            if c not in seen:
                compare_fields.append(c); seen.add(c)

    diff: dict[str, dict[str, str]] = {}
    for c in compare_fields:
        # If a source file did not provide a textual field and the normalized
        # payload has an empty default, do not treat it as a user request to clear
        # a non-empty DB value.  Recalculated time fields are still compared.
        if c not in {"work_hours", "work_minutes", "raw_minutes", "average_minutes", "group_key", "is_group_work"}:
            if c not in source_columns and not _text(after.get(c)) and _text((before or {}).get(c)):
                continue
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



def _v30090_is_explicit_parallel_group_key(group_key: Any) -> bool:
    """Return True only for group keys that identify one real parallel session.

    Legacy rows may have a broad fallback key like employee|process|date.  That
    key is not a real simultaneous-work identity; using it merges every same-day
    same-process row during 02 recalculation.  Explicit keys are those produced
    by 01 start/finish with a time suffix or by the V300.79 import overlap
    detector.
    """
    key = _text(group_key)
    if not key:
        return False
    if key.startswith("import-parallel-"):
        return True
    parts = key.split("|")
    # 01 start_work writes employee|process|yyyy-mm-dd|HH:MM.  Treat 4+ parts as
    # a concrete session key, but do not trust the old 3-part fallback.
    return len(parts) >= 4


def _v30090_intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Actual interval overlap only; touching endpoints are sequential work."""
    return a_start < b_end and b_start < a_end


def _v30090_component_ids_from_candidates(seed_id: int, records: dict[int, dict[str, Any]]) -> list[int]:
    """Find the connected overlap component that contains seed_id.

    A simultaneous-work group for historical recalculation is not "every row with
    the checkbox set" and not "every row sharing employee/process/date".  It is
    the connected set of records for the same employee + process + start_date
    whose time intervals overlap.  This supports large batch recalculation while
    keeping independent jobs separate.
    """
    seed_id = int(seed_id)
    if seed_id not in records:
        return [seed_id]

    intervals: dict[int, tuple[datetime, datetime]] = {}
    for rid, rec in records.items():
        st = _parse_dt(rec.get("start_timestamp"))
        et = _parse_dt(rec.get("end_timestamp"))
        if st is None or et is None or et <= st:
            continue
        intervals[int(rid)] = (st, et)
    if seed_id not in intervals:
        return [seed_id]

    component: set[int] = {seed_id}
    changed = True
    while changed:
        changed = False
        for rid, (st, et) in intervals.items():
            if rid in component:
                continue
            for cid in list(component):
                cst, cet = intervals[cid]
                if _v30090_intervals_overlap(st, et, cst, cet):
                    component.add(rid)
                    changed = True
                    break
    return sorted(component)


def _v30090_candidate_records_for_parallel(seed: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Load only candidate rows that can belong to seed's simultaneous group."""
    rid = _int_or_none(seed.get("id"))
    out: dict[int, dict[str, Any]] = {}

    explicit_key = _text(seed.get("group_key")) if _v30090_is_explicit_parallel_group_key(seed.get("group_key")) else ""
    if explicit_key:
        df = _safe_df(f"SELECT {_base_cols()} FROM time_records WHERE group_key=? AND {_not_deleted_predicate()} LIMIT 500", (explicit_key,))
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                i = _int_or_none(row.get("id"))
                if i is not None:
                    out[int(i)] = row.to_dict()
        if rid is not None and rid not in out:
            out[int(rid)] = seed
        return out

    emp = _text(seed.get("employee_id"))
    proc = _text(seed.get("process_name"))
    sdate = _text(seed.get("start_date")) or _normalize_date_part(seed.get("start_timestamp"))
    st = _parse_dt(seed.get("start_timestamp"))
    et = _parse_dt(seed.get("end_timestamp"))
    if not emp or not proc or not sdate or st is None or et is None or et <= st:
        if rid is not None:
            out[int(rid)] = seed
        return out

    # Load same employee/process/start-date rows only.  02 historical recalcs can
    # cover many pages, but each seed's candidate set stays small and indexed.
    df = _safe_df(
        f"""
        SELECT {_base_cols()}
        FROM time_records
        WHERE employee_id=? AND process_name=? AND start_date=?
          AND start_timestamp IS NOT NULL AND start_timestamp<>''
          AND end_timestamp IS NOT NULL AND end_timestamp<>''
          AND {_not_deleted_predicate()}
        ORDER BY start_timestamp, end_timestamp, id
        LIMIT 1000
        """,
        (emp, proc, sdate),
    )
    if isinstance(df, pd.DataFrame) and not df.empty:
        for _, row in df.iterrows():
            i = _int_or_none(row.get("id"))
            if i is not None:
                out[int(i)] = row.to_dict()
    if rid is not None and rid not in out:
        out[int(rid)] = seed
    return out


def _related_group_ids_from_record(record: dict[str, Any]) -> list[int]:
    """Return the real simultaneous-work group for one historical record.

    V300.90 fixes the old behavior that used broad legacy group_key values and
    merged every same-day same-process row into one recalculation group.  The new
    rule is:
      1. explicit group_key from 01/import-parallel => that exact group;
      2. otherwise same employee + same start date + same process + overlapping
         time intervals only.
    """
    rid = _int_or_none(record.get("id"))
    if rid is None:
        return []
    candidates = _v30090_candidate_records_for_parallel(record)
    return _v30090_component_ids_from_candidates(int(rid), candidates)


def _v30090_parallel_components_for_seed_ids(seed_ids: list[int]) -> list[list[int]]:
    """Build independent simultaneous-work components for a batch of seed rows."""
    clean_seeds: list[int] = []
    for x in seed_ids or []:
        i = _int_or_none(x)
        if i is not None and i > 0 and int(i) not in clean_seeds:
            clean_seeds.append(int(i))
    if not clean_seeds:
        return []

    seed_records = _load_existing_records_map(clean_seeds)
    seen: set[tuple[int, ...]] = set()
    components: list[list[int]] = []
    for seed_id in clean_seeds:
        rec = seed_records.get(int(seed_id))
        if not rec:
            continue
        ids = [int(i) for i in _related_group_ids_from_record(rec) if _int_or_none(i) is not None]
        if len(ids) <= 1:
            continue
        # Keep only ended rows for averaging.  Open rows are handled by 01 Finish
        # Work, not by 02 historical recalculation.
        records = _load_existing_records_map(ids)
        ended = sorted({int(i) for i, r in records.items() if _text(r.get("start_timestamp")) and _text(r.get("end_timestamp"))})
        if len(ended) <= 1:
            continue
        key = tuple(ended)
        if key not in seen:
            seen.add(key)
            components.append(ended)
    return components


def _sync_parallel_group_after_edit(seed_ids: list[int]) -> int:
    """Recalculate independent simultaneous-work components after edit/recalc.

    Previous versions unioned every selected row's related ids and averaged that
    union once.  When an admin selected many rows in 02, unrelated simultaneous
    groups were incorrectly calculated together.  V300.90 processes each overlap
    component independently.
    """
    components = _v30090_parallel_components_for_seed_ids(seed_ids)
    if not components:
        return 0

    now = now_text()
    total_count = 0
    for ended_ids in components:
        records = _load_existing_records_map(ended_ids)
        if len(records) <= 1:
            continue
        parallel_average = _v30045_parallel_average_from_records(records, ended_ids)
        avg_raw = float(parallel_average.get("raw_each") or 0.0)
        avg_net = float(parallel_average.get("net_each") or 0.0)
        ops: list[tuple[str, tuple[Any, ...]]] = []
        for i in ended_ids:
            ops.append((
                """
                UPDATE time_records
                SET raw_minutes=?, work_minutes=?, average_minutes=?, work_hours=?, is_group_work=1,
                    updated_at=?, updated_by='system', version=COALESCE(version,1)+1
                WHERE id=? AND (deleted_at IS NULL OR deleted_at='')
                """,
                (round(avg_raw, 2), round(avg_net, 2), round(avg_net, 2), round(avg_net / 60.0, 4), now, i),
            ))
        counts = execute_transaction(ops, mark_changed=True, reason="sync_parallel_group_after_edit_v30090", source_sql="sync_parallel_group_after_edit_v30090")
        group_count = int(sum(int(x or 0) for x in counts) or len(ended_ids))
        total_count += group_count
        try:
            detail = (
                f"ids={ended_ids}; group_start={parallel_average.get('start_ts')}; "
                f"group_end={parallel_average.get('end_ts')}; group_net={parallel_average.get('net_total')}; "
                f"average_minutes={avg_net}"
            )
            execute(
                "INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, detail, level) VALUES (?, ?, 'SYNC_PARALLEL_GROUP', 'time_records', ?, ?, ?, 'INFO')",
                (now, "SYSTEM", ",".join(map(str, ended_ids[:50])), f"同步作業平均重算 {len(ended_ids)} 筆", detail),
            )
        except Exception:
            pass
    return int(total_count)

def _v30025_normalize_changed_column_map(raw: Any) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    if not isinstance(raw, dict):
        return out
    for key, cols in raw.items():
        rid = _int_or_none(key)
        if rid is None:
            continue
        if isinstance(cols, (set, list, tuple)):
            out[int(rid)] = {DISPLAY_TO_INTERNAL.get(str(c), str(c)) for c in cols if _text(c)}
    return out


def _v30025_restrict_diff_for_editor(
    diff: dict[str, dict[str, str]],
    allowed_cols: set[str] | None,
    *,
    include_recalc_outputs: bool = False,
) -> dict[str, dict[str, str]]:
    if not allowed_cols:
        return diff
    allowed = set(allowed_cols)
    # Timestamp/date/time are coupled; allow the normalized companion fields to
    # be persisted when the operator edits any part of the time pair.
    if {"start_timestamp", "start_date", "start_time"}.intersection(allowed):
        allowed.update({"start_timestamp", "start_date", "start_time"})
    if {"end_timestamp", "end_date", "end_time"}.intersection(allowed):
        allowed.update({"end_timestamp", "end_date", "end_time"})
    if include_recalc_outputs:
        allowed.update({"raw_minutes", "work_minutes", "average_minutes", "work_hours"})
    return {k: v for k, v in diff.items() if k in allowed}


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
    changed_columns_by_id = _v30025_normalize_changed_column_map(work.attrs.get("_spt_changed_columns_by_id"))
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
        allowed_cols = changed_columns_by_id.get(int(rid)) if rid is not None else None
        diff0 = _v30025_restrict_diff_for_editor(_diff_payload(before, preliminary), allowed_cols)
        timing_changed = bool(_V73_TIMING_FIELDS.intersection(diff0.keys()))
        group_changed = bool(_V73_GROUP_FIELDS.intersection(diff0.keys()))
        should_recalc = bool(recalc_edited_timestamps or timing_changed)
        payload = _row_to_payload(rd, recalc=should_recalc, before=before, source_columns=source_columns)
        diff = _v30025_restrict_diff_for_editor(_diff_payload(before, payload), allowed_cols, include_recalc_outputs=should_recalc)
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


def _v30076_import_stable_operation_id(row: dict[str, Any]) -> str:
    """Return a deterministic operation id for 02 history imports.

    Older imports without record_id / operation_id generated a fresh UUID for
    every row.  Re-importing the same Excel therefore produced a different
    record_key, so the service could not detect existing rows and performed
    many duplicate inserts.  For imported history rows, the business identity is
    the worker + order + process + start/end time.
    """
    existing = _text(row.get("operation_id")) or _text(row.get("record_id"))
    if existing:
        return existing
    parts = [
        _text(row.get("employee_id")),
        _text(row.get("work_order") or row.get("work_order_no")),
        _text(row.get("process_name")),
        _text(row.get("start_timestamp") or row.get("start_date")),
        _text(row.get("end_timestamp") or row.get("end_date")),
    ]
    raw = "|".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:24]
    return f"hist-{digest}"




def _v30080_import_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    stage: str,
    current: int = 0,
    total: int = 0,
    message: str = "",
    fraction: float | None = None,
) -> None:
    """Report coarse import progress to the Streamlit page without coupling the service to Streamlit.

    The callback is intentionally optional and best-effort so existing callers
    keep working.  It lets 02 import large Excel/Paste batches show progress and
    ETA while the service still owns the Neon diff/write logic.
    """
    if progress_callback is None:
        return
    try:
        frac = 0.0 if fraction is None else max(0.0, min(1.0, float(fraction)))
        progress_callback({
            "stage": stage,
            "current": int(current or 0),
            "total": int(total or 0),
            "message": _text(message) or stage,
            "fraction": frac,
        })
    except Exception:
        # UI progress must never break the authority write path.
        pass


def _v30080_chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    step = max(int(size or 1000), 1)
    for i in range(0, len(items), step):
        yield items[i:i + step]


def _v30082_set_import_statement_timeout(
    seconds: int,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    message: str = "調整匯入查詢逾時",
) -> bool:
    """Temporarily give large 02 imports enough Neon time without changing page render paths.

    db_service currently opens Neon connections with an 8-second statement_timeout
    to protect normal 01/02 page renders.  A 16k-row Excel import legitimately
    needs a longer lookup/write window; otherwise a chunk can timeout, fall back
    to row-by-row writes, and the UI appears stuck at the previous progress
    message.  SET only affects the current cached PostgreSQL session.
    """
    if not is_postgres_enabled():
        return False
    try:
        ms = max(int(seconds or 8) * 1000, 1000)
        _v30080_import_progress(
            progress_callback,
            stage="import_timeout",
            current=0,
            total=1,
            message=message,
            fraction=0.335 if seconds and seconds > 8 else 0.99,
        )
        execute("SET statement_timeout = ?", (f"{ms}ms",))
        return True
    except Exception:
        return False


def _v30082_query_df_uncached(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
    """Run a PostgreSQL SELECT without db_service's query cache.

    Large import lookups pass a Python list to ANY(%s::text[]).  The generic
    query cache builds a tuple key from params; a list inside that tuple is
    unhashable, so the optimized ANY path can fail before SQL reaches Neon and
    silently fall back to many slower IN queries.  Use db_service's private
    uncached fetcher when available, and fall back to query_df for SQLite/small
    portable paths.
    """
    if is_postgres_enabled():
        from services import db_service as _db_service  # local import avoids changing public service API
        fn = getattr(_db_service, "_v25_pg_fetch_df", None)
        if callable(fn):
            return fn(sql, params or ())
    return query_df(sql, params or ())



def _v30081_import_lookup_columns() -> str:
    """Columns needed for import duplicate/diff lookup.

    V300.81: importing 16k+ history rows used SELECT *-style _base_cols()
    for every record_key lookup chunk.  The diff step only needs id,
    record_key, deleted_at and audit fields, so keep the lookup payload small.
    """
    cols: list[str] = []
    for c in ["id", "record_key", "deleted_at"] + list(_V73_AUDIT_FIELDS):
        if c in TIME_RECORD_COLUMNS and c not in cols:
            cols.append(c)
    return ", ".join(cols)


def _v30081_ensure_import_lookup_index(progress_callback: Callable[[dict[str, Any]], None] | None = None) -> None:
    """Create the import lookup index only on the 02 import path.

    This avoids putting DDL into the normal 01/02 hot render path, but still
    protects large Excel imports from doing many full-table scans by record_key.
    If Neon refuses or times out on index creation, the import still proceeds
    with the optimized ANY/chunk lookup below.
    """
    global _IMPORT_LOOKUP_INDEX_READY
    if _IMPORT_LOOKUP_INDEX_READY:
        return
    _v30080_import_progress(
        progress_callback,
        stage="lookup_index",
        current=0,
        total=1,
        message="確認匯入防重索引",
        fraction=0.33,
    )
    try:
        execute("CREATE INDEX IF NOT EXISTS idx_v30081_time_records_record_key_lookup ON time_records(record_key)", ())
    except Exception:
        pass
    # V300.88: import duplicate planning also checks record_id/operation_id.
    # Create these indexes only on the import path, not on normal page render.
    for _idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_v30088_time_records_record_id_lookup ON time_records(record_id)",
        "CREATE INDEX IF NOT EXISTS idx_v30088_time_records_operation_id_lookup ON time_records(operation_id)",
    ]:
        try:
            execute(_idx_sql, ())
        except Exception:
            pass
    _IMPORT_LOOKUP_INDEX_READY = True
    _v30080_import_progress(
        progress_callback,
        stage="lookup_index",
        current=1,
        total=1,
        message="匯入防重索引確認完成",
        fraction=0.35,
    )

def _v30076_load_records_by_record_key(
    record_keys: list[str],
    *,
    include_deleted: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_start: float = 0.0,
    progress_end: float = 1.0,
    progress_message: str = "比對既有工時紀錄",
) -> dict[str, dict[str, Any]]:
    """Load existing time_records for imported record keys without per-row reads.

    V300.81 fix for imports freezing around 16000/16491:
    - V300.80 still queried record_key IN (...) in 500-key chunks.  Without a
      record_key index this can become dozens of full-table scans on Neon, and
      the last chunks make the UI look stuck.
    - PostgreSQL now uses record_key = ANY(%s::text[]) in 4000-key chunks, so
      16k keys become about 5 lookups instead of 33.
    - Only the columns needed by diff/update are selected, not the whole wide
      time_records row.
    - A final progress event is always sent so the UI does not remain on
      16000/16491 while the next phase starts.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for key in record_keys or []:
        t = _text(key)
        if t and t not in seen:
            keys.append(t)
            seen.add(t)
    if not keys:
        return {}

    out: dict[str, dict[str, Any]] = {}
    cols = _v30081_import_lookup_columns()
    deleted_clause = "" if include_deleted else " AND (deleted_at IS NULL OR deleted_at='')"

    # PostgreSQL can bind a Python list to ANY(%s::text[]).  This dramatically
    # reduces round trips and avoids building thousands of SQL placeholders.
    if is_postgres_enabled():
        chunks = list(_v30080_chunks(keys, 4000))
        total_chunks = max(len(chunks), 1)
        try:
            for chunk_index, chunk in enumerate(chunks, start=1):
                # V300.83: use DISTINCT ON so a database that already contains
                # duplicate record_key rows from older failed imports does not return
                # a huge duplicate result set and stall the next diff/write stage.
                order_sql = "ORDER BY record_key, CASE WHEN deleted_at IS NULL OR deleted_at='' THEN 0 ELSE 1 END, id DESC"
                df = _v30082_query_df_uncached(
                    f"SELECT DISTINCT ON (record_key) {cols} FROM time_records WHERE record_key = ANY(?::text[]){deleted_clause} {order_sql}",
                    (list(chunk),),
                )
                if isinstance(df, pd.DataFrame) and not df.empty:
                    df = df.where(pd.notna(df), "")
                    for _, row in df.iterrows():
                        key = _text(row.get("record_key"))
                        if key and key not in out:
                            out[key] = row.to_dict()
                frac = float(progress_start) + (float(progress_end) - float(progress_start)) * (chunk_index / total_chunks)
                _v30080_import_progress(
                    progress_callback,
                    stage="lookup",
                    current=min(chunk_index * 4000, len(keys)),
                    total=len(keys),
                    message=progress_message,
                    fraction=frac,
                )
            _v30080_import_progress(
                progress_callback,
                stage="lookup",
                current=len(keys),
                total=len(keys),
                message=f"{progress_message}完成",
                fraction=progress_end,
            )
            return out
        except Exception as exc:
            _v30080_import_progress(
                progress_callback,
                stage="lookup",
                current=0,
                total=len(keys),
                message=f"Neon 快速比對未完成，改用相容批次：{str(exc)[:120]}",
                fraction=progress_start,
            )
            # Fallback to portable placeholder chunks below.  Never return an
            # empty map merely because the optimized ANY form is unavailable.
            out = {}

    chunks = list(_v30080_chunks(keys, 1000))
    total_chunks = max(len(chunks), 1)
    for chunk_index, chunk in enumerate(chunks, start=1):
        ph = ",".join(["?"] * len(chunk))
        df = _safe_df(f"SELECT {cols} FROM time_records WHERE record_key IN ({ph}){deleted_clause}", tuple(chunk))
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                key = _text(row.get("record_key"))
                if key and key not in out:
                    out[key] = row.to_dict()
        frac = float(progress_start) + (float(progress_end) - float(progress_start)) * (chunk_index / total_chunks)
        _v30080_import_progress(
            progress_callback,
            stage="lookup",
            current=min(chunk_index * 1000, len(keys)),
            total=len(keys),
            message=progress_message,
            fraction=frac,
        )
    _v30080_import_progress(
        progress_callback,
        stage="lookup",
        current=len(keys),
        total=len(keys),
        message=f"{progress_message}完成",
        fraction=progress_end,
    )
    return out


def _v30088_load_records_by_identity_column(
    values: list[str],
    *,
    column: str,
    include_deleted: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_start: float = 0.0,
    progress_end: float = 1.0,
    progress_message: str = "比對既有工時紀錄身分鍵",
) -> dict[str, dict[str, Any]]:
    """Load existing rows by record_id or operation_id for 02 imports.

    V300.88: the duplicate guard in the fast PostgreSQL insert protects
    record_key, record_id and operation_id.  The diff planner, however, only
    looked up record_key, so rows already present under the same record_id or
    operation_id could be counted as "planned insert" and then skipped by the
    database.  That produced confusing results such as "預計新增 100、實際新增 0".
    Load those identity keys up front so duplicate imports are classified as
    update/skip before the write stage instead of being discovered by the INSERT
    guard.
    """
    if column not in {"record_id", "operation_id"}:
        return {}
    clean: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        t = _text(value)
        if t and t not in seen:
            clean.append(t)
            seen.add(t)
    if not clean:
        return {}

    out: dict[str, dict[str, Any]] = {}
    cols = _v30081_import_lookup_columns()
    deleted_clause = "" if include_deleted else " AND (deleted_at IS NULL OR deleted_at='')"
    if is_postgres_enabled():
        chunks = list(_v30080_chunks(clean, 4000))
        total_chunks = max(len(chunks), 1)
        try:
            for chunk_index, chunk in enumerate(chunks, start=1):
                order_sql = f"ORDER BY {column}, CASE WHEN deleted_at IS NULL OR deleted_at='' THEN 0 ELSE 1 END, id DESC"
                df = _v30082_query_df_uncached(
                    f"SELECT DISTINCT ON ({column}) {cols} FROM time_records WHERE {column} = ANY(?::text[]){deleted_clause} {order_sql}",
                    (list(chunk),),
                )
                if isinstance(df, pd.DataFrame) and not df.empty:
                    df = df.where(pd.notna(df), "")
                    for _, row in df.iterrows():
                        key = _text(row.get(column))
                        if key and key not in out:
                            out[key] = row.to_dict()
                frac = float(progress_start) + (float(progress_end) - float(progress_start)) * (chunk_index / total_chunks)
                _v30080_import_progress(
                    progress_callback,
                    stage=f"lookup_{column}",
                    current=min(chunk_index * 4000, len(clean)),
                    total=len(clean),
                    message=progress_message,
                    fraction=frac,
                )
            return out
        except Exception as exc:
            _v30080_import_progress(
                progress_callback,
                stage=f"lookup_{column}",
                current=0,
                total=len(clean),
                message=f"{progress_message}未完成，改用相容批次：{str(exc)[:120]}",
                fraction=progress_start,
            )
            out = {}

    chunks = list(_v30080_chunks(clean, 1000))
    total_chunks = max(len(chunks), 1)
    for chunk_index, chunk in enumerate(chunks, start=1):
        ph = ",".join(["?"] * len(chunk))
        df = _safe_df(f"SELECT {cols} FROM time_records WHERE {column} IN ({ph}){deleted_clause}", tuple(chunk))
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.where(pd.notna(df), "")
            for _, row in df.iterrows():
                key = _text(row.get(column))
                if key and key not in out:
                    out[key] = row.to_dict()
        frac = float(progress_start) + (float(progress_end) - float(progress_start)) * (chunk_index / total_chunks)
        _v30080_import_progress(
            progress_callback,
            stage=f"lookup_{column}",
            current=min(chunk_index * 1000, len(clean)),
            total=len(clean),
            message=progress_message,
            fraction=frac,
        )
    return out

def _v30079_apply_import_parallel_average(payloads: list[dict[str, Any]]) -> dict[str, int]:
    """Detect and average imported synchronous work rows in Python before DB write.

    Import rule aligned with 01 Finish Work:
    - same employee + same date + same process
    - two or more completed rows whose time intervals overlap
    - average = net minutes from earliest group start to latest group end / row count

    This stays in the foreground Python batch and does not scan 02 history.  It
    only inspects the current import payloads, so repeated Excel/Paste imports
    remain fast and deterministic.
    """
    summary = {"parallel_groups": 0, "parallel_records": 0}
    if not payloads:
        return summary

    buckets: dict[tuple[str, str, str], list[tuple[int, datetime, datetime, dict[str, Any]]]] = {}
    for pos, payload in enumerate(payloads):
        emp = _text(payload.get("employee_id"))
        proc = _text(payload.get("process_name"))
        sdate = _text(payload.get("start_date")) or _normalize_date_part(payload.get("start_timestamp"))
        start_dt = _parse_dt(payload.get("start_timestamp"))
        end_dt = _parse_dt(payload.get("end_timestamp"))
        # Start-only or invalid time rows cannot be averaged safely.
        if not emp or not proc or not sdate or start_dt is None or end_dt is None or end_dt <= start_dt:
            continue
        buckets.setdefault((emp, sdate, proc), []).append((pos, start_dt, end_dt, payload))

    for (emp, sdate, proc), rows in buckets.items():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda item: (item[1], item[2], _text(item[3].get("record_key"))))
        components: list[list[tuple[int, datetime, datetime, dict[str, Any]]]] = []
        cur: list[tuple[int, datetime, datetime, dict[str, Any]]] = []
        cur_end: datetime | None = None
        for item in rows:
            _, st, et, _ = item
            if not cur:
                cur = [item]
                cur_end = et
                continue
            # Actual overlap only.  A row ending exactly when the next starts is
            # sequential work and must not be treated as synchronous work.
            if cur_end is not None and st < cur_end:
                cur.append(item)
                if et > cur_end:
                    cur_end = et
            else:
                components.append(cur)
                cur = [item]
                cur_end = et
        if cur:
            components.append(cur)

        for comp in components:
            if len(comp) <= 1:
                continue
            group_start = min(item[1] for item in comp)
            group_end = max(item[2] for item in comp)
            raw_total, net_total = calculate_work_minutes(_fmt_dt(group_start), _fmt_dt(group_end))
            n = max(len(comp), 1)
            raw_each = round(raw_total / n, 2)
            net_each = round(net_total / n, 2)
            group_seed = "|".join([
                emp,
                sdate,
                proc,
                _fmt_dt(group_start),
                _fmt_dt(group_end),
                "|".join(sorted(_text(item[3].get("record_key")) for item in comp)),
            ])
            group_key = "import-parallel-" + hashlib.sha1(group_seed.encode("utf-8", "ignore")).hexdigest()[:16]
            for _, _, _, payload in comp:
                payload["group_key"] = group_key
                payload["is_group_work"] = 1
                payload["raw_minutes"] = raw_each
                payload["work_minutes"] = net_each
                payload["average_minutes"] = net_each
                payload["work_hours"] = round(net_each / 60.0, 4)
                # Keep imported rows visibly ended when they have an end time but
                # the source did not provide an explicit final status.
                if _text(payload.get("end_timestamp")) and _text(payload.get("status")) in ACTIVE_STATUSES:
                    payload["status"] = END_ACTION_STATUS.get(_text(payload.get("end_action")), "已結束")
            summary["parallel_groups"] += 1
            summary["parallel_records"] += len(comp)
    return summary


def _v30084_json_value_for_insert(col: str, value: Any) -> Any:
    """Normalize values for PostgreSQL JSONB bulk insert.

    V300.84: the old INSERT path used db_service.executemany, which can fall
    back to row-by-row writes on Neon and leaves the UI stuck at
    "開始分批新增 0/n".  The JSONB path below casts values inside PostgreSQL,
    so empty strings for numeric columns must be converted before sending.
    """
    if col in {"work_hours", "work_minutes", "raw_minutes", "average_minutes"}:
        try:
            if value is None or _text(value) == "":
                return 0.0
            return float(value)
        except Exception:
            return 0.0
    if col in {"is_group_work", "version"}:
        try:
            if value is None or _text(value) == "":
                return 1 if col == "version" else 0
            return int(float(value))
        except Exception:
            return 1 if col == "version" else 0
    return _text(value)


def _v30084_pg_insert_from_jsonb(payloads: list[dict[str, Any]]) -> int:
    """Fast PostgreSQL insert for large 02 history imports.

    The previous insert used cursor.executemany through db_service.  When a
    batch hit a duplicate/type issue it dropped into the slow protected path,
    while the page still displayed the previous progress message.  This uses
    one INSERT ... SELECT FROM jsonb_to_recordset statement per chunk and also
    filters keys already present in time_records, so a missed duplicate does not
    force a slow row-by-row recovery.
    """
    if not is_postgres_enabled() or not payloads:
        return 0
    cols = [c for c in TIME_RECORD_COLUMNS if c != "id"]
    numeric_cols = {"work_hours", "work_minutes", "raw_minutes", "average_minutes"}
    integer_cols = {"is_group_work", "version"}
    type_defs: list[str] = []
    for c in cols:
        if c in numeric_cols:
            typ = "double precision"
        elif c in integer_cols:
            typ = "integer"
        else:
            typ = "text"
        type_defs.append(f"{c} {typ}")

    cleaned: list[dict[str, Any]] = []
    for payload in payloads:
        row = {c: _v30084_json_value_for_insert(c, payload.get(c, "")) for c in cols}
        if not _text(row.get("record_key")):
            continue
        if not _text(row.get("record_id")):
            row["record_id"] = _text(row.get("record_key"))
        if not _text(row.get("operation_id")):
            row["operation_id"] = _text(row.get("record_key"))
        if not _text(row.get("created_at")):
            row["created_at"] = now_text()
        if not _text(row.get("updated_at")):
            row["updated_at"] = now_text()
        cleaned.append(row)
    if not cleaned:
        return 0

    select_cols = ", ".join([f"i.{c}" for c in cols])
    # V300.85: use a writable CTE that returns a single COUNT row instead of a
    # plain INSERT.  db_service automatically appends RETURNING id to normal
    # INSERT statements into time_records; for thousands of rows that can create
    # a large returned rowset and, on error, pushes the import into the very slow
    # row-by-row protected path.  A WITH ... INSERT ... RETURNING 1 SELECT COUNT(*)
    # is still one PostgreSQL statement but returns only one scalar count.
    duplicate_guard = (
        "t.record_key = i.record_key"
        " OR (i.record_id IS NOT NULL AND i.record_id <> '' AND t.record_id = i.record_id)"
        " OR (i.operation_id IS NOT NULL AND i.operation_id <> '' AND t.operation_id = i.operation_id)"
    )
    sql = (
        f"WITH incoming AS ("
        f"SELECT * FROM jsonb_to_recordset(?::jsonb) AS i({', '.join(type_defs)})"
        f"), dedup AS ("
        f"SELECT DISTINCT ON (record_key) * FROM incoming "
        f"WHERE record_key IS NOT NULL AND record_key <> '' "
        f"ORDER BY record_key"
        f"), ins AS ("
        f"INSERT INTO time_records ({', '.join(cols)}) "
        f"SELECT {select_cols} FROM dedup i "
        f"WHERE NOT EXISTS (SELECT 1 FROM time_records t WHERE {duplicate_guard}) "
        f"RETURNING 1"
        f") SELECT COUNT(*) AS id FROM ins"
    )
    return int(execute(sql, (json.dumps(cleaned, ensure_ascii=False),)) or 0)


def _v30076_bulk_insert_payloads(
    payloads: list[dict[str, Any]],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_base: int = 0,
    progress_total: int = 0,
) -> int:
    if not payloads:
        return 0
    if is_postgres_enabled():
        try:
            inserted = _v30084_pg_insert_from_jsonb(payloads)
            _v30080_import_progress(
                progress_callback,
                stage="write_insert_pg_batch",
                current=progress_base + len(payloads),
                total=progress_total or len(payloads),
                message=f"PostgreSQL 批次新增完成 {progress_base + len(payloads)}/{progress_total or len(payloads)}，實際新增 {inserted}",
                fraction=0.70,
            )
            return int(inserted or 0)
        except Exception as exc:
            _v30080_import_progress(
                progress_callback,
                stage="write_insert_fallback",
                current=progress_base,
                total=progress_total or len(payloads),
                message=f"大批次新增未完成，改用 100 筆小批次：{str(exc)[:120]}",
                fraction=0.70,
            )
            inserted = 0
            failed = 0
            # V300.85: stay in PostgreSQL JSONB mode for smaller chunks.  Do not
            # immediately fall through to executemany/row-by-row, because the
            # screenshot showing 100 rows/minute means that protected path is the
            # real bottleneck.  Bad micro-batches are skipped with a visible
            # message instead of locking the whole Streamlit request for an hour.
            for small in _v30080_chunks(payloads, 100):
                try:
                    n = _v30084_pg_insert_from_jsonb(small)
                    inserted += int(n or 0)
                except Exception as small_exc:
                    failed += len(small)
                    _v30080_import_progress(
                        progress_callback,
                        stage="write_insert_skip_bad_batch",
                        current=progress_base + inserted + failed,
                        total=progress_total or len(payloads),
                        message=f"小批次新增失敗已略過 {failed} 筆：{str(small_exc)[:100]}",
                        fraction=0.70,
                    )
                    continue
                _v30080_import_progress(
                    progress_callback,
                    stage="write_insert_pg_small_batch",
                    current=progress_base + inserted + failed,
                    total=progress_total or len(payloads),
                    message=f"小批次新增工時紀錄 已處理 {progress_base + inserted + failed}/{progress_total or len(payloads)}，實際新增 {inserted}",
                    fraction=0.70,
                )
            return int(inserted or 0)

    cols = [c for c in TIME_RECORD_COLUMNS if c != "id"]
    sql = f"INSERT INTO time_records ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})"
    inserted = 0
    # SQLite/local fallback only.  PostgreSQL should have returned above.
    for small_index, small in enumerate(_v30080_chunks(payloads, 100), start=1):
        rows = [tuple(p.get(c, "") for c in cols) for p in small]
        executemany(sql, rows)
        inserted += len(small)
        _v30080_import_progress(
            progress_callback,
            stage="write_insert_fallback",
            current=progress_base + inserted,
            total=progress_total or len(payloads),
            message=f"SQLite 相容小批次新增工時紀錄 {progress_base + inserted}/{progress_total or len(payloads)}",
            fraction=0.70,
        )
    return inserted


def _v30083_pg_update_from_values(update_cols: tuple[str, ...], rows: list[tuple[Any, ...]]) -> bool:
    """Fast PostgreSQL batch UPDATE for 02 import chunks.

    ``executemany`` can still behave like many individual UPDATE round trips on
    Neon.  For import chunks, one UPDATE ... FROM (VALUES ...) statement per
    changed-column group is much faster and prevents the UI from looking frozen
    after lookup completed.  SQLite/local testing keeps the previous path.
    """
    if not is_postgres_enabled() or not rows:
        return False
    cols = list(update_cols)
    value_cols = ["id"] + cols
    per_row_placeholders = "(" + ", ".join(["?"] * len(value_cols)) + ")"
    values_sql = ", ".join([per_row_placeholders] * len(rows))
    params: list[Any] = []
    for row in rows:
        # grouped rows are values for update_cols followed by id
        params.append(int(row[-1]))
        params.extend(list(row[:-1]))
    assignments = ", ".join([f"{c}=v.{c}" for c in cols] + ["version=COALESCE(t.version,1)+1"])
    aliases = ", ".join(value_cols)
    sql = (
        f"UPDATE time_records AS t SET {assignments} "
        f"FROM (VALUES {values_sql}) AS v({aliases}) "
        f"WHERE t.id=v.id AND (t.deleted_at IS NULL OR t.deleted_at='')"
    )
    execute(sql, tuple(params))
    return True


def _v30076_bulk_update_payloads(update_items: list[tuple[int, dict[str, Any], set[str]]]) -> int:
    if not update_items:
        return 0
    allowed = set(TIME_RECORD_COLUMNS) - {"id", "created_at", "version"}
    grouped: dict[tuple[str, ...], list[tuple[Any, ...]]] = {}
    for rid, payload, changed_fields in update_items:
        update_cols: list[str] = []
        seen: set[str] = set()
        for c in sorted(str(x) for x in (changed_fields or set())):
            if c in allowed and c not in seen:
                update_cols.append(c)
                seen.add(c)
        for c in ["updated_at", "updated_by"]:
            if c in allowed and c not in seen:
                update_cols.append(c)
                seen.add(c)
        if not update_cols:
            continue
        key = tuple(update_cols)
        grouped.setdefault(key, []).append(tuple(payload.get(c, "") for c in update_cols) + (int(rid),))

    total = 0
    for update_cols, rows in grouped.items():
        if _v30083_pg_update_from_values(tuple(update_cols), rows):
            total += len(rows)
            continue
        assignments = ", ".join([f"{c}=?" for c in update_cols] + ["version=COALESCE(version,1)+1"])
        sql = f"UPDATE time_records SET {assignments} WHERE id=? AND (deleted_at IS NULL OR deleted_at='')"
        executemany(sql, rows)
        total += len(rows)
    return total



def _v30089_restore_deleted_payload(rid: int, payload: dict[str, Any], changed_fields: set[str] | None = None) -> int:
    """Restore one soft-deleted history record when the admin explicitly asks.

    This path is only used by 02 Excel/Paste imports when
    restore_deleted_matching_records=True.  It clears deleted_* tombstone fields
    and updates the restored row with the incoming Excel/Paste values.  The
    default import path still skips deleted matches, so admin deletes do not
    silently resurrect.
    """
    allowed = set(TIME_RECORD_COLUMNS) - {"id", "created_at", "version"}
    fields = [c for c in TIME_RECORD_COLUMNS if c in allowed and c not in {"deleted_at", "deleted_by", "delete_reason"}]
    row = dict(payload or {})
    row["deleted_at"] = ""
    row["deleted_by"] = ""
    row["delete_reason"] = ""
    row["updated_at"] = now_text()
    row["updated_by"] = _text(row.get("updated_by")) or "history_import_restore"
    update_cols = [c for c in fields if c in allowed]
    for c in ["deleted_at", "deleted_by", "delete_reason"]:
        if c in allowed and c not in update_cols:
            update_cols.append(c)
    assignments = ", ".join([f"{c}=?" for c in update_cols] + ["version=COALESCE(version,1)+1"])
    vals = [row.get(c, "") for c in update_cols]
    vals.append(int(rid))
    return int(execute(f"UPDATE time_records SET {assignments} WHERE id=?", tuple(vals)) or 0)


def _v30089_pg_restore_deleted_from_jsonb(restore_items: list[tuple[int, dict[str, Any], set[str]]]) -> int:
    """Fast PostgreSQL restore for deleted rows matched by import identity keys."""
    if not is_postgres_enabled() or not restore_items:
        return 0
    cols = [c for c in TIME_RECORD_COLUMNS if c not in {"id", "created_at", "version"}]
    numeric_cols = {"work_hours", "work_minutes", "raw_minutes", "average_minutes"}
    integer_cols = {"is_group_work"}
    type_defs = ["id integer"]
    for c in cols:
        if c in numeric_cols:
            typ = "double precision"
        elif c in integer_cols:
            typ = "integer"
        else:
            typ = "text"
        type_defs.append(f"{c} {typ}")
    cleaned: list[dict[str, Any]] = []
    for rid, payload, _changed in restore_items:
        row = {"id": int(rid)}
        for c in cols:
            row[c] = _v30084_json_value_for_insert(c, (payload or {}).get(c, ""))
        row["deleted_at"] = ""
        row["deleted_by"] = ""
        row["delete_reason"] = ""
        row["updated_at"] = now_text()
        row["updated_by"] = _text(row.get("updated_by")) or "history_import_restore"
        if not _text(row.get("record_key")):
            row["record_key"] = _text(row.get("record_id") or row.get("operation_id"))
        cleaned.append(row)
    if not cleaned:
        return 0
    assignments = ", ".join([f"{c}=i.{c}" for c in cols] + ["version=COALESCE(t.version,1)+1"])
    sql = (
        f"WITH incoming AS ("
        f"SELECT * FROM jsonb_to_recordset(?::jsonb) AS i({', '.join(type_defs)})"
        f"), upd AS ("
        f"UPDATE time_records AS t SET {assignments} "
        f"FROM incoming i WHERE t.id=i.id AND t.deleted_at IS NOT NULL AND t.deleted_at <> '' "
        f"RETURNING 1"
        f") SELECT COUNT(*) AS id FROM upd"
    )
    return int(execute(sql, (json.dumps(cleaned, ensure_ascii=False),)) or 0)


def _v30089_bulk_restore_deleted_payloads(restore_items: list[tuple[int, dict[str, Any], set[str]]]) -> int:
    if not restore_items:
        return 0
    if is_postgres_enabled():
        try:
            return int(_v30089_pg_restore_deleted_from_jsonb(restore_items) or 0)
        except Exception:
            # Fall through to compatible per-row restore; this is only reached if
            # the optimized JSONB update is unavailable on the current backend.
            pass
    restored = 0
    for rid, payload, changed in restore_items:
        restored += int(_v30089_restore_deleted_payload(int(rid), payload, changed_fields=changed) or 0)
    return restored

def import_time_records(
    df: pd.DataFrame,
    recalc: bool = True,
    source: str = "history_import",
    *,
    batch_size: int = 1000,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    restore_deleted_matching_records: bool = False,
) -> dict:
    """Import 02 history rows using a single diff/batch path.

    V300.76 speed fix:
    - Do not run SELECT id by record_key for every row.
    - Do not UPDATE unchanged rows.
    - Do not open one Neon transaction per imported row.
    - Use deterministic record keys for Excel/Paste history rows that do not
      contain record_id/operation_id, so repeated imports become no-op/update
      instead of duplicate inserts.
    """
    _ensure_time_runtime_columns()
    work = _normalize_df(df)
    started_at = _time.monotonic()
    batch_size = max(int(batch_size or 1000), 100)
    # V300.82: large Excel/Paste imports must not inherit the normal 8s page-render
    # Neon statement_timeout; otherwise a legitimate 16k-row lookup/write can
    # timeout and fall back into very slow protective paths.
    _v30082_set_import_statement_timeout(120, progress_callback, "延長 02 匯入 Neon 查詢/寫入逾時")
    result = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "parallel_groups": 0,
        "parallel_records": 0,
        "prepared": 0,
        "to_insert": 0,
        "to_update": 0,
        "batch_size": batch_size,
        "duration_seconds": 0.0,
        "db_duplicate_skipped": 0,
        "identity_matches": 0,
        "duplicate_only": False,
        "deleted_skipped": 0,
        "restored_deleted": 0,
        "restore_deleted_matching_records": bool(restore_deleted_matching_records),
        "errors": [],
    }
    if work.empty:
        result["duration_seconds"] = round(_time.monotonic() - started_at, 2)
        _v30082_set_import_statement_timeout(8, None, "恢復 Neon 查詢逾時")
        return result

    total_rows = int(len(work))
    _v30080_import_progress(progress_callback, stage="prepare", current=0, total=total_rows, message="整理匯入資料", fraction=0.02)

    source_columns = set(work.attrs.get("_spt_source_columns", set(work.columns)))
    prepared: list[tuple[int, int | None, dict[str, Any]]] = []
    payload_by_key: dict[str, tuple[int, int | None, dict[str, Any]]] = {}

    for prepare_pos, (idx, row) in enumerate(work.iterrows(), start=1):
        rd = dict(row)
        if (
            not _text(rd.get("employee_id"))
            or not _text(rd.get("work_order") or rd.get("work_order_no"))
            or not _text(rd.get("process_name"))
            or not _text(rd.get("start_timestamp") or rd.get("start_date"))
        ):
            result["skipped"] += 1
            continue
        try:
            rd["source"] = source
            if not _text(rd.get("operation_id")) and not _text(rd.get("record_id")) and not _text(rd.get("record_key")):
                rd["operation_id"] = _v30076_import_stable_operation_id(rd)
                rd["record_id"] = rd["operation_id"]
            payload = _row_to_payload(rd, recalc=bool(recalc), before=None, source_columns=source_columns)
            # V300.79: _row_to_payload historically defaulted every import row
            # to employee|process|date as group_key.  That makes sequential
            # same-process records look like synchronous work later.  For 02
            # Excel/Paste imports, keep an explicit source group_key if present;
            # otherwise leave it blank until overlap detection proves the rows
            # are truly simultaneous.
            if "group_key" not in source_columns or not _text(rd.get("group_key")):
                payload["group_key"] = ""
                payload["is_group_work"] = 0
            rid = _int_or_none(rd.get("id"))
            key = _text(payload.get("record_key"))
            if not key:
                result["skipped"] += 1
                continue
            # Same import file may contain duplicate business rows.  Keep the
            # last copy and avoid writing the same record twice in one click.
            if key in payload_by_key:
                result["skipped"] += 1
            payload_by_key[key] = (int(idx), rid, payload)
        except Exception as exc:
            result["skipped"] += 1
            result["errors"].append(f"第 {idx+1} 筆解析失敗：{exc}")

        if prepare_pos == total_rows or prepare_pos % 500 == 0:
            _v30080_import_progress(
                progress_callback,
                stage="prepare",
                current=prepare_pos,
                total=total_rows,
                message="整理匯入資料並建立防重 key",
                fraction=0.02 + 0.23 * (prepare_pos / max(total_rows, 1)),
            )

    prepared = list(payload_by_key.values())
    if not prepared:
        _cache_clear()
        result["duration_seconds"] = round(_time.monotonic() - started_at, 2)
        _v30080_import_progress(progress_callback, stage="done", current=0, total=0, message="沒有可匯入資料", fraction=1.0)
        _v30082_set_import_statement_timeout(8, None, "恢復 Neon 查詢逾時")
        return result

    result["prepared"] = len(prepared)
    _v30080_import_progress(progress_callback, stage="parallel", current=0, total=len(prepared), message="偵測同時作業", fraction=0.27)

    # V300.79: detect same-employee/same-date/same-process overlapping
    # completed rows inside this import batch and apply the 01 Finish Work
    # average rule before diffing/writing Neon.
    parallel_summary = _v30079_apply_import_parallel_average([payload for _, _, payload in prepared])
    result["parallel_groups"] = int(parallel_summary.get("parallel_groups", 0) or 0)
    result["parallel_records"] = int(parallel_summary.get("parallel_records", 0) or 0)
    _v30080_import_progress(progress_callback, stage="parallel", current=len(prepared), total=len(prepared), message="同時作業偵測完成", fraction=0.32)

    ids = sorted({int(rid) for _, rid, _ in prepared if rid is not None and int(rid) > 0})
    keys = [_text(payload.get("record_key")) for _, _, payload in prepared if _text(payload.get("record_key"))]
    _v30080_import_progress(progress_callback, stage="lookup", current=0, total=len(keys), message="比對 Neon 既有紀錄", fraction=0.34)
    _v30081_ensure_import_lookup_index(progress_callback)
    existing_by_id = _load_existing_records_map(ids)
    # V300.80: load all matching keys once, then split active/deleted locally.
    # Previous V300.76 path queried active and all keys separately, doubling
    # lookup work on large imports such as 16k rows.
    existing_all_by_key = _v30076_load_records_by_record_key(
        keys,
        include_deleted=True,
        progress_callback=progress_callback,
        progress_start=0.36,
        progress_end=0.52,
        progress_message="比對 Neon 既有紀錄",
    )
    existing_active_by_key = {
        k: v for k, v in existing_all_by_key.items()
        if not _text((v or {}).get("deleted_at"))
    }

    # V300.88: also lookup record_id / operation_id.  Old imports and manual
    # 01 records may share these identity fields while having a different
    # generated record_key.  The INSERT guard already protects these fields;
    # doing the same lookup before diffing prevents misleading results like
    # "預計新增 100、實際新增 0".
    import_record_ids = [_text(payload.get("record_id")) for _, _, payload in prepared if _text(payload.get("record_id"))]
    import_operation_ids = [_text(payload.get("operation_id")) for _, _, payload in prepared if _text(payload.get("operation_id"))]
    existing_all_by_record_id = _v30088_load_records_by_identity_column(
        import_record_ids,
        column="record_id",
        include_deleted=True,
        progress_callback=progress_callback,
        progress_start=0.525,
        progress_end=0.545,
        progress_message="比對 Neon record_id",
    )
    existing_all_by_operation_id = _v30088_load_records_by_identity_column(
        import_operation_ids,
        column="operation_id",
        include_deleted=True,
        progress_callback=progress_callback,
        progress_start=0.545,
        progress_end=0.565,
        progress_message="比對 Neon operation_id",
    )
    existing_active_by_record_id = {
        k: v for k, v in existing_all_by_record_id.items()
        if not _text((v or {}).get("deleted_at"))
    }
    existing_active_by_operation_id = {
        k: v for k, v in existing_all_by_operation_id.items()
        if not _text((v or {}).get("deleted_at"))
    }
    result["identity_matches"] = len(existing_active_by_record_id) + len(existing_active_by_operation_id)

    _v30080_import_progress(
        progress_callback,
        stage="lookup_done",
        current=len(keys),
        total=len(keys),
        message=(
            f"比對 Neon 完成，record_key {len(existing_all_by_key)} 筆、"
            f"record_id {len(existing_all_by_record_id)} 筆、operation_id {len(existing_all_by_operation_id)} 筆"
        ),
        fraction=0.57,
    )

    inserts: list[dict[str, Any]] = []
    updates: list[tuple[int, dict[str, Any], set[str]]] = []
    restores: list[tuple[int, dict[str, Any], set[str]]] = []

    _v30080_import_progress(progress_callback, stage="diff", current=0, total=len(prepared), message="計算新增 / 更新 / 略過", fraction=0.54)
    for diff_pos, (idx, rid, payload) in enumerate(prepared, start=1):
        try:
            key = _text(payload.get("record_key"))
            rec_identity = _text(payload.get("record_id"))
            op_identity = _text(payload.get("operation_id"))
            before = existing_by_id.get(int(rid)) if rid is not None and int(rid) > 0 else None
            if before is None:
                before = existing_active_by_key.get(key)
            if before is None and rec_identity:
                before = existing_active_by_record_id.get(rec_identity)
            if before is None and op_identity:
                before = existing_active_by_operation_id.get(op_identity)
            if before:
                effective_id = _int_or_none(before.get("id"))
                diff = _v30083_import_relevant_diff(before, payload, source_columns)
                if not diff:
                    result["skipped"] += 1
                    continue
                if effective_id is None:
                    result["skipped"] += 1
                    result["errors"].append(f"第 {idx+1} 筆無法取得既有紀錄 ID，已略過。")
                    continue
                updates.append((int(effective_id), payload, set(diff.keys())))
                continue

            deleted_existing = existing_all_by_key.get(key)
            if deleted_existing is None and rec_identity:
                deleted_existing = existing_all_by_record_id.get(rec_identity)
            if deleted_existing is None and op_identity:
                deleted_existing = existing_all_by_operation_id.get(op_identity)
            if deleted_existing and _text(deleted_existing.get("deleted_at")):
                effective_id = _int_or_none(deleted_existing.get("id"))
                if restore_deleted_matching_records and effective_id is not None:
                    # V300.89: administrator explicitly requested re-import of
                    # matching records that were previously soft-deleted.  Restore
                    # the existing deleted row instead of inserting a duplicate.
                    restore_fields = set(TIME_RECORD_COLUMNS) - {"id", "created_at", "version"}
                    restores.append((int(effective_id), payload, restore_fields))
                    continue
                result["skipped"] += 1
                result["deleted_skipped"] = int(result.get("deleted_skipped", 0) or 0) + 1
                continue

            inserts.append(payload)
        except Exception as exc:
            result["skipped"] += 1
            result["errors"].append(f"第 {idx+1} 筆比對失敗：{exc}")

        if diff_pos == len(prepared) or diff_pos % 1000 == 0:
            _v30080_import_progress(
                progress_callback,
                stage="diff",
                current=diff_pos,
                total=len(prepared),
                message="計算新增 / 更新 / 略過",
                fraction=0.54 + 0.16 * (diff_pos / max(len(prepared), 1)),
            )

    result["to_insert"] = len(inserts)
    result["to_update"] = len(updates)
    _v30080_import_progress(
        progress_callback,
        stage="diff_done",
        current=len(prepared),
        total=len(prepared),
        message=f"差異計算完成：預計新增 {len(inserts)}，預計更新 {len(updates)}，略過 {result.get('skipped', 0)}",
        fraction=0.70,
    )

    try:
        write_total_chunks = (
            len(list(_v30080_chunks(restores, batch_size)))
            + len(list(_v30080_chunks(inserts, batch_size)))
            + len(list(_v30080_chunks(updates, batch_size)))
        )
        write_done_chunks = 0
        if write_total_chunks == 0:
            _v30080_import_progress(progress_callback, stage="write", current=0, total=0, message="沒有需要寫入 Neon 的資料", fraction=0.95)
        if restores:
            restored_total = 0
            for restore_chunk in _v30080_chunks(restores, batch_size):
                _v30080_import_progress(
                    progress_callback,
                    stage="write_restore",
                    current=restored_total,
                    total=len(restores),
                    message=f"開始恢復已刪除工時紀錄 {restored_total}/{len(restores)}",
                    fraction=0.70 + 0.25 * (write_done_chunks / max(write_total_chunks, 1)),
                )
                restored_total += _v30089_bulk_restore_deleted_payloads(restore_chunk)
                write_done_chunks += 1
                _v30080_import_progress(
                    progress_callback,
                    stage="write_restore",
                    current=min(restored_total, len(restores)),
                    total=len(restores),
                    message=f"恢復已刪除工時紀錄 {restored_total}/{len(restores)}",
                    fraction=0.70 + 0.25 * (write_done_chunks / max(write_total_chunks, 1)),
                )
            result["restored_deleted"] = restored_total
        if inserts:
            inserted_total = 0
            for insert_chunk in _v30080_chunks(inserts, batch_size):
                _v30080_import_progress(
                    progress_callback,
                    stage="write_insert",
                    current=inserted_total,
                    total=len(inserts),
                    message=f"開始分批新增工時紀錄 {inserted_total}/{len(inserts)}",
                    fraction=0.70 + 0.25 * (write_done_chunks / max(write_total_chunks, 1)),
                )
                before_inserted = inserted_total
                n_inserted = _v30076_bulk_insert_payloads(
                    insert_chunk,
                    progress_callback=progress_callback,
                    progress_base=inserted_total,
                    progress_total=len(inserts),
                )
                inserted_total += int(n_inserted or 0)
                # If the PostgreSQL anti-duplicate insert skipped rows that now
                # exist in Neon, count them as skipped instead of pretending all
                # planned rows were inserted.
                skipped_by_db = max(len(insert_chunk) - int(n_inserted or 0), 0)
                if skipped_by_db:
                    result["skipped"] = int(result.get("skipped", 0) or 0) + skipped_by_db
                    result["db_duplicate_skipped"] = int(result.get("db_duplicate_skipped", 0) or 0) + skipped_by_db
                write_done_chunks += 1
                _v30080_import_progress(
                    progress_callback,
                    stage="write",
                    current=min(before_inserted + len(insert_chunk), len(inserts)),
                    total=len(inserts),
                    message=f"分批新增工時紀錄 已處理 {min(before_inserted + len(insert_chunk), len(inserts))}/{len(inserts)}，實際新增 {inserted_total}",
                    fraction=0.70 + 0.25 * (write_done_chunks / max(write_total_chunks, 1)),
                )
            result["inserted"] = inserted_total
        if updates:
            updated_total = 0
            for update_chunk in _v30080_chunks(updates, batch_size):
                _v30080_import_progress(
                    progress_callback,
                    stage="write_update",
                    current=updated_total,
                    total=len(updates),
                    message=f"開始分批更新工時紀錄 {updated_total}/{len(updates)}",
                    fraction=0.70 + 0.25 * (write_done_chunks / max(write_total_chunks, 1)),
                )
                updated_total += _v30076_bulk_update_payloads(update_chunk)
                write_done_chunks += 1
                _v30080_import_progress(
                    progress_callback,
                    stage="write",
                    current=min(updated_total, len(updates)),
                    total=len(updates),
                    message=f"分批更新工時紀錄 {updated_total}/{len(updates)}",
                    fraction=0.70 + 0.25 * (write_done_chunks / max(write_total_chunks, 1)),
                )
            result["updated"] = updated_total
    except Exception as exc:
        # Keep the import page usable if a batch hits a legacy constraint.
        # Fall back to the old single-row path only for rows that actually need
        # writing; unchanged rows have already been skipped.
        result["errors"].append(f"批次寫入失敗，已改用逐筆保護寫入：{exc}")
        result["inserted"] = 0
        result["updated"] = 0
        result["restored_deleted"] = 0
        for pos, (rid, payload, changed) in enumerate(restores, start=1):
            try:
                n = _v30089_restore_deleted_payload(int(rid), payload, changed_fields=changed)
                if n:
                    result["restored_deleted"] += 1
                else:
                    result["skipped"] += 1
            except Exception as row_exc:
                result["skipped"] += 1
                result["errors"].append(f"逐筆恢復已刪除紀錄失敗：{row_exc}")
            if pos == len(restores) or pos % 100 == 0:
                _v30080_import_progress(
                    progress_callback,
                    stage="write_restore_row_fallback",
                    current=pos,
                    total=len(restores),
                    message=f"逐筆保護恢復已刪除紀錄 {pos}/{len(restores)}",
                    fraction=0.71,
                )
        for pos, payload in enumerate(inserts, start=1):
            try:
                kind, n = _insert_or_update_payload(payload, None)
                if kind == "inserted" and n:
                    result["inserted"] += 1
                else:
                    result["skipped"] += 1
            except Exception as row_exc:
                result["skipped"] += 1
                result["errors"].append(f"逐筆新增失敗：{row_exc}")
            if pos == len(inserts) or pos % 100 == 0:
                _v30080_import_progress(
                    progress_callback,
                    stage="write_insert_row_fallback",
                    current=pos,
                    total=len(inserts),
                    message=f"逐筆保護新增 {pos}/{len(inserts)}",
                    fraction=0.72,
                )
        for pos, (rid, payload, changed) in enumerate(updates, start=1):
            try:
                kind, n = _insert_or_update_payload(payload, rid, changed_fields=changed)
                if kind == "updated" and n:
                    result["updated"] += 1
                else:
                    result["skipped"] += 1
            except Exception as row_exc:
                result["skipped"] += 1
                result["errors"].append(f"逐筆更新失敗：{row_exc}")
            if pos == len(updates) or pos % 100 == 0:
                _v30080_import_progress(
                    progress_callback,
                    stage="write_update_row_fallback",
                    current=pos,
                    total=len(updates),
                    message=f"逐筆保護更新 {pos}/{len(updates)}",
                    fraction=0.86,
                )

    result["duplicate_only"] = (
        int(result.get("inserted", 0) or 0) == 0
        and int(result.get("updated", 0) or 0) == 0
        and int(result.get("restored_deleted", 0) or 0) == 0
        and int(result.get("errors") and len(result.get("errors") or []) or 0) == 0
        and int(result.get("skipped", 0) or 0) > 0
    )
    _cache_clear()
    result["duration_seconds"] = round(_time.monotonic() - started_at, 2)
    _v30080_import_progress(progress_callback, stage="done", current=1, total=1, message="匯入完成", fraction=1.0)
    _v30082_set_import_statement_timeout(8, None, "恢復 Neon 查詢逾時")
    return result


def recalculate_time_records(record_ids: Iterable[Any]) -> int:
    _ensure_time_runtime_columns()
    ids: list[int] = []
    for x in record_ids or []:
        i = _int_or_none(x)
        if i is not None and i > 0 and i not in ids:
            ids.append(int(i))
    if not ids:
        return 0

    # V300.45: 02 history/admin recalc must use the same synchronized-work rule
    # as Finish Work.  If any selected row belongs to a parallel group, recalc the
    # whole ended group as: earliest start -> group end, divided by group count.
    selected = _load_existing_records_map(ids)
    grouped_ids: set[int] = set()
    for rec in selected.values():
        related = _related_group_ids_from_record(rec)
        if len(related) <= 1:
            continue
        related_records = _load_existing_records_map(related)
        ended = [i for i, r in related_records.items() if _text(r.get("start_timestamp")) and _text(r.get("end_timestamp"))]
        if len(ended) > 1:
            grouped_ids.update(int(i) for i in ended)

    count = 0
    if grouped_ids:
        count += _sync_parallel_group_after_edit(sorted(grouped_ids))

    now = now_text()
    for rid in ids:
        if rid in grouped_ids:
            continue
        rec = selected.get(int(rid)) or _safe_one(f"SELECT {_base_cols()} FROM time_records WHERE id=? AND (deleted_at IS NULL OR deleted_at='') LIMIT 1", (rid,))
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
    """Return only the columns needed by 08 daily employee-hours.

    V300.33: this used to call ``load_records(date, date)``, which loads the
    full 01/02 record column set and then lets 08 group it in pandas.  For the
    Neon Free plan, 08 should not spend compute or bandwidth on unused columns.
    The function now uses an indexed start_date query first and falls back to a
    bounded timestamp range only for legacy rows whose start_date is blank.
    """
    _ensure_time_runtime_columns()
    d = _text(work_date)[:10]
    cols = ["employee_id", "employee_name", "work_hours", "end_timestamp", "status"]
    if not d:
        return pd.DataFrame(columns=cols)

    def _minimal_query(sql: str, params: tuple[Any, ...]) -> pd.DataFrame:
        try:
            df = query_df(sql, params)
            if isinstance(df, pd.DataFrame):
                work = df.where(pd.notna(df), "").reset_index(drop=True)
                for c in cols:
                    if c not in work.columns:
                        work[c] = ""
                return work[cols]
        except Exception:
            pass
        return pd.DataFrame(columns=cols)

    sql = f"""
        SELECT employee_id, employee_name, work_hours, end_timestamp, status
        FROM time_records
        WHERE {_not_deleted_predicate()}
          AND start_date = ?
        ORDER BY employee_id, id
    """
    df = _minimal_query(sql, (d,))
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df

    # Legacy fallback: bounded timestamp-only rows.  Do not use substr()/OR in
    # the primary path because it can bypass indexes on larger Neon tables.
    next_day = _today_end_text(d)
    fallback_sql = f"""
        SELECT employee_id, employee_name, work_hours, end_timestamp, status
        FROM time_records
        WHERE {_not_deleted_predicate()}
          AND COALESCE(start_date,'')=''
          AND start_timestamp >= ?
          AND start_timestamp < ?
        ORDER BY employee_id, id
    """
    return _minimal_query(fallback_sql, (f"{d} 00:00:00", f"{next_day} 00:00:00"))


def load_daily_record_employee_index_sql(work_date: str):
    """Return one row per employee who has any 01/02 time record on a date.

    V300.62: 07 missing-list comparison should not load the full 02 history data.
    This helper performs a single indexed, date-bounded authority-table read and
    returns only employee_id/count/last time.  The actual missing-list comparison
    is performed by 07 in pandas/session state.
    """
    _ensure_time_runtime_columns()
    d = _text(work_date)[:10]
    cols = ["employee_id", "employee_name", "today_record_count", "last_start_time"]
    if not d:
        return pd.DataFrame(columns=cols)

    def _employee_index_query(sql: str, params: tuple[Any, ...]) -> pd.DataFrame:
        try:
            df = query_df(sql, params)
            if isinstance(df, pd.DataFrame):
                work = df.where(pd.notna(df), "").reset_index(drop=True)
                for c in cols:
                    if c not in work.columns:
                        work[c] = 0 if c == "today_record_count" else ""
                work["employee_id"] = work["employee_id"].fillna("").astype(str).str.strip()
                work = work[work["employee_id"] != ""].copy()
                work["today_record_count"] = pd.to_numeric(work["today_record_count"], errors="coerce").fillna(0).astype(int)
                return work[cols]
        except Exception:
            pass
        return pd.DataFrame(columns=cols)

    sql = f"""
        SELECT
            employee_id,
            MAX(employee_name) AS employee_name,
            COUNT(*) AS today_record_count,
            MAX(COALESCE(NULLIF(start_timestamp,''), NULLIF(end_timestamp,''), NULLIF(start_date || ' ' || start_time, ' '), start_date)) AS last_start_time
        FROM time_records
        WHERE {_not_deleted_predicate()}
          AND employee_id IS NOT NULL
          AND employee_id <> ''
          AND start_date = ?
        GROUP BY employee_id
        ORDER BY employee_id
    """
    df = _employee_index_query(sql, (d,))
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df

    next_day = _today_end_text(d)
    fallback_sql = f"""
        SELECT
            employee_id,
            MAX(employee_name) AS employee_name,
            COUNT(*) AS today_record_count,
            MAX(COALESCE(NULLIF(start_timestamp,''), NULLIF(end_timestamp,''))) AS last_start_time
        FROM time_records
        WHERE {_not_deleted_predicate()}
          AND employee_id IS NOT NULL
          AND employee_id <> ''
          AND COALESCE(start_date,'')=''
          AND start_timestamp >= ?
          AND start_timestamp < ?
        GROUP BY employee_id
        ORDER BY employee_id
    """
    return _employee_index_query(fallback_sql, (f"{d} 00:00:00", f"{next_day} 00:00:00"))


def audit_v63_time_record_runtime_consolidated() -> dict[str, Any]:
    return {
        "version": "V63_TIME_RECORD_RUNTIME_CONSOLIDATED",
        "legacy_patch_stack_removed": True,
        "neon_runtime_authority": bool(is_postgres_enabled()),
        "soft_delete_only": True,
        "parallel_finish_average_supported": True,
        "ui_css_changed": False,
    }
