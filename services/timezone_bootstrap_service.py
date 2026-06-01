# -*- coding: utf-8 -*-
"""V160 Taiwan timezone bootstrap.

Streamlit Cloud server logs are usually shown in UTC and cannot be changed by the app.
This module standardizes the *application runtime* timezone to Asia/Taipei so that
business records, LOG rows, export timestamps, backup timestamps, and date filters
use Taiwan time consistently.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

APP_TIMEZONE_NAME = "Asia/Taipei"
APP_TZ = ZoneInfo(APP_TIMEZONE_NAME)
UTC_TZ = timezone.utc

_BOOTSTRAPPED = False


def apply_app_timezone() -> str:
    """Force process-local timezone to Asia/Taipei when supported.

    On Linux/Streamlit Cloud, datetime.now() and time.strftime() follow TZ after
    time.tzset().  This fixes older modules that still call datetime.now() or
    time.strftime() directly instead of services.timezone_service.now_text().
    """
    global _BOOTSTRAPPED
    os.environ["TZ"] = APP_TIMEZONE_NAME
    try:
        time.tzset()  # type: ignore[attr-defined]
    except Exception:
        # Windows does not provide tzset in all Python builds.  The explicit
        # helpers below still return Taiwan time.
        pass
    _BOOTSTRAPPED = True
    return APP_TIMEZONE_NAME


def app_now() -> datetime:
    apply_app_timezone()
    return datetime.now(APP_TZ)


def utc_now() -> datetime:
    return datetime.now(UTC_TZ)


def now_text() -> str:
    return app_now().strftime("%Y-%m-%d %H:%M:%S")


def now_stamp() -> str:
    return app_now().strftime("%Y%m%d_%H%M%S")


def today_date() -> date:
    return app_now().date()


def today_text() -> str:
    return today_date().strftime("%Y-%m-%d")


def parse_local_datetime(value) -> datetime | None:
    """Parse common persisted timestamp text as Taiwan local time when naive."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=APP_TZ)
        return value.astimezone(APP_TZ)
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat", "null"}:
        return None
    text = text.replace("T", " ").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:len(fmt.replace('%Y','0000').replace('%m','00').replace('%d','00').replace('%H','00').replace('%M','00').replace('%S','00'))], fmt)
            return dt.replace(tzinfo=APP_TZ)
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
    except Exception:
        return None


def timezone_status() -> dict:
    apply_app_timezone()
    return {
        "app_timezone": APP_TIMEZONE_NAME,
        "env_TZ": os.environ.get("TZ", ""),
        "taiwan_now": now_text(),
        "utc_now": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_tzname": getattr(time, "tzname", ("", "")),
        "time_timezone_seconds": getattr(time, "timezone", None),
    }


# Apply at import time.  Importing this module has no database side effects.
apply_app_timezone()
