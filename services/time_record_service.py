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
        "開始時間戳": "start_timestamp", "結束時間戳": "end_timestamp", "備註": "remark", "工時小計": "work_hours",
        "ID": "id",
    }
    work = work.rename(columns={c: alias.get(str(c), str(c)) for c in work.columns})
    for c in TIME_RECORD_COLUMNS:
        if c not in work.columns:
            work[c] = ""
    return work[TIME_RECORD_COLUMNS]


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


def _load_rest_periods() -> list[tuple[dt_time, dt_time]]:
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


def _row_to_payload(row: dict[str, Any], recalc: bool = False) -> dict[str, Any]:
    now = now_text()
    start_ts = _text(row.get("start_timestamp"))
    end_ts = _text(row.get("end_timestamp"))
    start_date = _text(row.get("start_date")); start_time = _text(row.get("start_time"))
    end_date = _text(row.get("end_date")); end_time = _text(row.get("end_time"))
    if start_ts and (not start_date or not start_time):
        start_date, start_time = _split_ts(start_ts)
    if end_ts and (not end_date or not end_time):
        end_date, end_time = _split_ts(end_ts)
    if not start_ts and start_date and start_time:
        start_ts = f"{start_date} {start_time}"
    if not end_ts and end_date and end_time:
        end_ts = f"{end_date} {end_time}"
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
    try:
        clear_query_cache()
    except Exception:
        pass


def clear_today_records_fast_cache() -> None:
    _cache_clear()


def clear_today_finished_from_work_page() -> int:
    # UI-only refresh hook kept for compatibility. It must not delete or mutate data.
    _cache_clear()
    return 0


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    _ensure_time_runtime_columns()
    sql = f"SELECT {_base_cols()} FROM time_records WHERE {_not_deleted_predicate()}"
    params: list[Any] = []
    if start_date:
        sql += " AND COALESCE(start_date, substr(COALESCE(start_timestamp,''),1,10)) >= ?"
        params.append(_text(start_date))
    if end_date:
        sql += " AND COALESCE(start_date, substr(COALESCE(start_timestamp,''),1,10)) <= ?"
        params.append(_text(end_date))
    if employee_id:
        sql += " AND employee_id = ?"
        params.append(_text(employee_id))
    if work_order:
        sql += " AND (work_order = ? OR work_order_no = ?)"
        params.extend([_text(work_order), _text(work_order)])
    if not start_date and not end_date:
        # Never whole-table scan on page render.
        sql += " ORDER BY id DESC LIMIT 3000"
    else:
        sql += " ORDER BY id DESC LIMIT 10000"
    return _safe_df(sql, tuple(params))


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:
    today = today_text()
    if unfinished_only:
        sql = f"SELECT {_base_cols()} FROM time_records WHERE {_active_predicate()} ORDER BY id DESC LIMIT 500"
        return _safe_df(sql, ())
    sql = f"SELECT {_base_cols()} FROM time_records WHERE {_not_deleted_predicate()} AND (start_date=? OR substr(COALESCE(start_timestamp,''),1,10)=?)"
    params: list[Any] = [today, today]
    if not include_finished:
        sql += f" AND {_active_predicate()}"
    sql += " ORDER BY id DESC LIMIT 800"
    return _safe_df(sql, tuple(params))


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
    rec = _safe_one(f"SELECT {_base_cols()} FROM time_records WHERE id=? LIMIT 1", (int(record_id),))
    if not rec:
        return pd.DataFrame(columns=TIME_RECORD_COLUMNS)
    if _text(rec.get("end_timestamp")) or _text(rec.get("deleted_at")):
        return pd.DataFrame([rec])
    emp = _text(rec.get("employee_id")); name = _text(rec.get("employee_name")); proc = _text(rec.get("process_name")); sdate = _text(rec.get("start_date")); wo = _text(rec.get("work_order") or rec.get("work_order_no"))
    group_key = _text(rec.get("group_key"))
    start_dt = _parse_dt(rec.get("start_timestamp"))
    df = get_active_records(employee_id=emp, employee_name=name or None, process_name=proc or None, start_date=sdate or None)
    if df.empty:
        return pd.DataFrame([rec])
    if group_key:
        same = df[df.get("group_key", "").astype(str) == group_key].copy()
        if len(same) > 1:
            return same.reset_index(drop=True)
    if start_dt is not None and "start_timestamp" in df.columns:
        def close_enough(v):
            d = _parse_dt(v)
            return bool(d and abs((d - start_dt).total_seconds()) <= 180)
        same = df[df["start_timestamp"].map(close_enough)].copy()
        if len(same) > 1:
            return same.reset_index(drop=True)
    # Same person/process but different work_order means parallel work; include only if start time close.
    return pd.DataFrame([rec])


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
    raw_net: dict[int, tuple[float, float]] = {}
    for i in ids:
        rec = _safe_one(f"SELECT {_base_cols()} FROM time_records WHERE id=? LIMIT 1", (i,)) or {}
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


def _insert_or_update_payload(payload: dict[str, Any], record_id: int | None = None) -> tuple[str, int]:
    cols = [c for c in TIME_RECORD_COLUMNS if c != "id"]
    if record_id:
        assignments = ", ".join([f"{c}=?" for c in cols if c not in {"created_at"}])
        vals = [payload.get(c, "") for c in cols if c not in {"created_at"}] + [record_id]
        n = execute(f"UPDATE time_records SET {assignments} WHERE id=? AND (deleted_at IS NULL OR deleted_at='')", tuple(vals))
        return "updated", int(n or 0)
    sql = f"INSERT INTO time_records ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
    new_id = execute(sql, tuple(payload.get(c, "") for c in cols))
    return "inserted", int(new_id or 0)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:
    _ensure_time_runtime_columns()
    work = _normalize_df(df)
    if work.empty:
        return 0
    count = 0
    for _, row in work.iterrows():
        rd = dict(row)
        if not _text(rd.get("employee_id")) or not _text(rd.get("work_order") or rd.get("work_order_no")) or not _text(rd.get("process_name")):
            continue
        rid = _int_or_none(rd.get("id"))
        payload = _row_to_payload(rd, recalc=bool(recalc_edited_timestamps))
        _kind, n = _insert_or_update_payload(payload, rid)
        count += 1 if n else 0
    _cache_clear()
    return int(count)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:
    _ensure_time_runtime_columns()
    work = _normalize_df(df)
    result = {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}
    for idx, row in work.iterrows():
        rd = dict(row)
        if not _text(rd.get("employee_id")) or not _text(rd.get("work_order") or rd.get("work_order_no")) or not _text(rd.get("process_name")) or not _text(rd.get("start_timestamp") or rd.get("start_date")):
            result["skipped"] += 1
            continue
        try:
            rd["source"] = source
            payload = _row_to_payload(rd, recalc=bool(recalc))
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
