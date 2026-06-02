# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from services.app_config import DEFAULT_REST_PERIODS
from services.permanent_store import load_records


def parse_dt(date_val: Any, time_val: Any) -> datetime | None:
    if time_val is None or str(time_val).strip() == "":
        return None
    text = str(time_val).strip()
    if len(text) >= 10:
        try:
            return pd.to_datetime(text).to_pydatetime()
        except Exception:
            pass
    date_text = str(date_val).strip() if date_val is not None and str(date_val).strip() else datetime.now().strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(f"{date_text} {text}").to_pydatetime()
    except Exception:
        return None


def _rest_windows_for_day(day: datetime, rest_rows: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    wins = []
    for r in rest_rows:
        if not bool(r.get("啟用", True)):
            continue
        try:
            s_hour, s_min = [int(x) for x in str(r.get("開始", "00:00")).split(":")[:2]]
            e_hour, e_min = [int(x) for x in str(r.get("結束", "00:00")).split(":")[:2]]
            s = day.replace(hour=s_hour, minute=s_min, second=0, microsecond=0)
            e = day.replace(hour=e_hour, minute=e_min, second=0, microsecond=0)
            if e <= s:
                e += timedelta(days=1)
            wins.append((s, e))
        except Exception:
            continue
    return wins


def working_seconds(start: datetime | None, end: datetime | None) -> int:
    if not start or not end:
        return 0
    if end < start:
        end += timedelta(days=1)
    total = max(0, int((end - start).total_seconds()))
    rest_rows = load_records("13_system_settings_rest", DEFAULT_REST_PERIODS)
    cur_day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    last_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
    deduct = 0
    while cur_day <= last_day:
        for rs, re in _rest_windows_for_day(cur_day, rest_rows):
            overlap = max(0, int((min(end, re) - max(start, rs)).total_seconds()))
            deduct += overlap
        cur_day += timedelta(days=1)
    return max(0, total - deduct)


def seconds_to_hhmmss(sec: int | float | None) -> str:
    sec = int(sec or 0)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def recalc_time_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    cumulative: dict[str, int] = {}
    for r in rows:
        row = dict(r)
        st = parse_dt(row.get("日期"), row.get("開始時間"))
        en = parse_dt(row.get("日期"), row.get("結束時間"))
        sec = working_seconds(st, en)
        row["工時小計"] = seconds_to_hhmmss(sec)
        key = str(row.get("製令", ""))
        cumulative[key] = cumulative.get(key, 0) + sec
        row["累積工時"] = seconds_to_hhmmss(cumulative[key]) if key else row["工時小計"]
        out.append(row)
    return out
