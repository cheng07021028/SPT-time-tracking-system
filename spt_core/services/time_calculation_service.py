from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from ..utils import date_range, parse_hhmm


def _combine(day, t: time, tzinfo) -> datetime:
    return datetime.combine(day, t).replace(tzinfo=tzinfo)


def overlap_minutes(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> float:
    latest_start = max(start, window_start)
    earliest_end = min(end, window_end)
    if earliest_end <= latest_start:
        return 0.0
    return (earliest_end - latest_start).total_seconds() / 60


def break_minutes_between(start: datetime, end: datetime, break_windows: list[dict[str, Any]]) -> float:
    if end <= start:
        return 0.0
    total = 0.0
    for day in date_range(start.date(), end.date()):
        for window in break_windows or []:
            try:
                ws = parse_hhmm(window["start"])
                we = parse_hhmm(window["end"])
            except Exception:
                continue
            w_start = _combine(day, ws, start.tzinfo)
            w_end = _combine(day, we, start.tzinfo)
            if w_end <= w_start:
                w_end += timedelta(days=1)
            total += overlap_minutes(start, end, w_start, w_end)
    return round(total, 2)


def calculate_work_minutes(start: datetime, end: datetime, break_windows: list[dict[str, Any]] | None = None) -> dict[str, float]:
    raw = max(0.0, (end - start).total_seconds() / 60)
    breaks = break_minutes_between(start, end, break_windows or [])
    work = max(0.0, raw - breaks)
    return {"raw_minutes": round(raw, 2), "break_minutes": round(breaks, 2), "work_minutes": round(work, 2)}
