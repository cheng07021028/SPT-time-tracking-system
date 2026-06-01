# -*- coding: utf-8 -*-
from __future__ import annotations

import time as _time_mod
from datetime import datetime, date, time, timedelta
from .db_service import query_df

_DEFAULT_RESTS = [("10:30", "10:45"), ("12:00", "13:00"), ("15:00", "15:15"), ("18:00", "18:30"), ("20:00", "20:15")]
_REST_CACHE: dict[str, object] = {"ts": 0.0, "data": None}
_REST_CACHE_TTL_SEC = 60.0


def clear_rest_periods_cache() -> None:
    _REST_CACHE["ts"] = 0.0
    _REST_CACHE["data"] = None


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0, 0))
    text = str(value).strip().replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 else text, fmt)
        except ValueError:
            pass
    # Last fallback for pandas Timestamp-like / ISO values.
    return datetime.fromisoformat(text)


def _combine(d: date, hhmm: str) -> datetime:
    h, m = [int(x) for x in str(hhmm).split(":")[:2]]
    return datetime.combine(d, time(h, m))


def load_rest_periods() -> list[tuple[str, str]]:
    now = _time_mod.time()
    cached = _REST_CACHE.get("data")
    if cached is not None and now - float(_REST_CACHE.get("ts") or 0) <= _REST_CACHE_TTL_SEC:
        return list(cached)  # type: ignore[arg-type]
    try:
        df = query_df("SELECT start_time, end_time FROM rest_periods WHERE is_active=1 ORDER BY sort_order, id")
        if df.empty:
            data = list(_DEFAULT_RESTS)
        else:
            data = [(str(a), str(b)) for a, b in df[["start_time", "end_time"]].itertuples(index=False, name=None)]
    except Exception:
        data = list(_DEFAULT_RESTS)
    _REST_CACHE["ts"] = now
    _REST_CACHE["data"] = data
    return list(data)


def calculate_work_hours(start_ts: str | datetime, end_ts: str | datetime) -> float:
    start = parse_dt(start_ts)
    end = parse_dt(end_ts)
    if end < start:
        end = end + timedelta(days=1)

    total_seconds = max((end - start).total_seconds(), 0)
    rest_seconds = 0.0
    rests = load_rest_periods()

    d = start.date()
    while d <= end.date():
        for rs, re in rests:
            r_start = _combine(d, rs)
            r_end = _combine(d, re)
            if r_end <= r_start:
                r_end += timedelta(days=1)
            overlap_start = max(start, r_start)
            overlap_end = min(end, r_end)
            if overlap_end > overlap_start:
                rest_seconds += (overlap_end - overlap_start).total_seconds()
        d += timedelta(days=1)

    return round(max((total_seconds - rest_seconds) / 3600, 0), 6)


def split_timestamp(ts: str | datetime) -> tuple[str, str]:
    dt = parse_dt(ts)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
