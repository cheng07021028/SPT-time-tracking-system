# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.timezone_bootstrap_service import apply_app_timezone, timezone_status
from services.timezone_service import now_text, now_stamp, today_text, taiwan_now


def main() -> int:
    apply_app_timezone()
    payload = {
        "check": "V160 Taiwan timezone check",
        "status": timezone_status(),
        "datetime_now_without_tz": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_strftime": time.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone_service_now_text": now_text(),
        "timezone_service_now_stamp": now_stamp(),
        "timezone_service_today_text": today_text(),
        "timezone_service_taiwan_now_iso": taiwan_now().isoformat(),
        "note": "Streamlit Cloud platform build logs may still show UTC; app records should match Asia/Taipei.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
