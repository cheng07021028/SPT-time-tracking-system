# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, date
from zoneinfo import ZoneInfo

TAIWAN_TZ = ZoneInfo("Asia/Taipei")

def taiwan_now() -> datetime:
    return datetime.now(TAIWAN_TZ)

def now_text() -> str:
    return taiwan_now().strftime("%Y-%m-%d %H:%M:%S")

def now_stamp() -> str:
    return taiwan_now().strftime("%Y%m%d_%H%M%S")

def today_date() -> date:
    return taiwan_now().date()

def today_text() -> str:
    return today_date().strftime("%Y-%m-%d")
