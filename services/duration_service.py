# -*- coding: utf-8 -*-
"""Duration formatting helpers for SPT time tracking.

Internal database keeps durations as decimal hours for calculation.
UI displays durations as HH:MM:SS for operators and supervisors.
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd


def hours_to_seconds(value: Any) -> int:
    """Convert decimal hours or HH:MM:SS text to seconds."""
    if value is None:
        return 0
    try:
        if pd.isna(value):
            return 0
    except Exception:
        pass
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        # HH:MM:SS or H:MM
        m = re.match(r"^(-?\d+)\s*[:：]\s*(\d{1,2})(?:\s*[:：]\s*(\d{1,2}))?$", text)
        if m:
            sign = -1 if m.group(1).startswith("-") else 1
            h = abs(int(m.group(1)))
            mi = int(m.group(2))
            sec = int(m.group(3) or 0)
            return sign * (h * 3600 + mi * 60 + sec)
        # Chinese-like 1時02分03秒
        m = re.match(r"^(-?\d+)\s*(?:時|小時|h|H)\s*(\d{1,2})?\s*(?:分|m|M)?\s*(\d{1,2})?\s*(?:秒|s|S)?$", text)
        if m:
            sign = -1 if m.group(1).startswith("-") else 1
            h = abs(int(m.group(1)))
            mi = int(m.group(2) or 0)
            sec = int(m.group(3) or 0)
            return sign * (h * 3600 + mi * 60 + sec)
        # Decimal hour string
        try:
            return int(round(float(text) * 3600))
        except Exception:
            return 0
    try:
        if isinstance(value, bool):
            return 0
        if math.isfinite(float(value)):
            return int(round(float(value) * 3600))
    except Exception:
        return 0
    return 0


def seconds_to_hms(seconds: Any) -> str:
    """Format seconds as HH:MM:SS. Hours may exceed 24."""
    try:
        total = int(round(float(seconds)))
    except Exception:
        total = 0
    sign = "-" if total < 0 else ""
    total = abs(total)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{sign}{h:02d}:{m:02d}:{s:02d}"


def hours_to_hms(value: Any) -> str:
    return seconds_to_hms(hours_to_seconds(value))


def hms_to_hours(value: Any) -> float:
    return round(hours_to_seconds(value) / 3600, 6)


def format_duration_series(series: pd.Series) -> pd.Series:
    return series.map(hours_to_hms)
