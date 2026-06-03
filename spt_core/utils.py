from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


APP_VERSION = os.getenv("SPT_APP_VERSION", "SPT-Neon-Core-v1.0")
DEFAULT_TIMEZONE = os.getenv("SPT_TIMEZONE", "Asia/Taipei")


def get_tz() -> ZoneInfo:
    return ZoneInfo(os.getenv("SPT_TIMEZONE", DEFAULT_TIMEZONE))


def now_dt() -> datetime:
    return datetime.now(get_tz())


def now_iso() -> str:
    return now_dt().isoformat(timespec="seconds")


def today_str() -> str:
    return now_dt().date().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def json_loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def minute_bucket(dt: datetime, bucket_minutes: int = 3) -> datetime:
    minute = (dt.minute // bucket_minutes) * bucket_minutes
    return dt.replace(minute=minute, second=0, microsecond=0)


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")[:2]
    return time(hour=int(hour), minute=int(minute))
