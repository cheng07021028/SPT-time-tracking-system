# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, date
from zoneinfo import ZoneInfo

# V160: one canonical application timezone.  Importing the bootstrap also sets
# process-local TZ=Asia/Taipei so legacy datetime.now()/time.strftime() calls in
# older modules stop using UTC on Streamlit Cloud.
try:
    from services.timezone_bootstrap_service import (
        APP_TIMEZONE_NAME,
        APP_TZ as TAIWAN_TZ,
        apply_app_timezone,
        app_now,
        now_text as _boot_now_text,
        now_stamp as _boot_now_stamp,
        today_date as _boot_today_date,
        today_text as _boot_today_text,
        timezone_status,
    )
except Exception:  # fallback for unusual import paths
    from datetime import timezone, timedelta
    APP_TIMEZONE_NAME = "Asia/Taipei"
    TAIWAN_TZ = ZoneInfo("Asia/Taipei")
    def apply_app_timezone() -> str:
        return APP_TIMEZONE_NAME
    def app_now() -> datetime:
        return datetime.now(TAIWAN_TZ)
    def _boot_now_text() -> str:
        return app_now().strftime("%Y-%m-%d %H:%M:%S")
    def _boot_now_stamp() -> str:
        return app_now().strftime("%Y%m%d_%H%M%S")
    def _boot_today_date() -> date:
        return app_now().date()
    def _boot_today_text() -> str:
        return _boot_today_date().strftime("%Y-%m-%d")
    def timezone_status() -> dict:
        return {"app_timezone": APP_TIMEZONE_NAME, "taiwan_now": _boot_now_text()}


def taiwan_now() -> datetime:
    apply_app_timezone()
    return app_now()


def now_text() -> str:
    return _boot_now_text()


def now_stamp() -> str:
    return _boot_now_stamp()


def today_date() -> date:
    return _boot_today_date()


def today_text() -> str:
    return _boot_today_text()
