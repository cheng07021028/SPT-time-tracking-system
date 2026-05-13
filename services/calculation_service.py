# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime, date, time, timedelta
from .db_service import query_df


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(str(value))


def _combine(d: date, hhmm: str) -> datetime:
    h, m = [int(x) for x in str(hhmm).split(":")[:2]]
    return datetime.combine(d, time(h, m))


def load_rest_periods() -> list[tuple[str, str]]:
    df = query_df("SELECT start_time, end_time FROM rest_periods WHERE is_active=1 ORDER BY sort_order, id")
    if df.empty:
        return [("10:30", "10:45"), ("12:00", "13:00"), ("15:00", "15:15"), ("18:00", "18:30"), ("20:00", "20:15")]
    return list(df[["start_time", "end_time"]].itertuples(index=False, name=None))


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

    return round(max((total_seconds - rest_seconds) / 3600, 0), 2)


def split_timestamp(ts: str | datetime) -> tuple[str, str]:
    dt = parse_dt(ts)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
