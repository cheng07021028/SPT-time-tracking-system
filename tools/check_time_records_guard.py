# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.time_records_guard_service import health_report, rescue_time_records_if_empty


def main() -> int:
    report = health_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("db_time_records_count", 0) == 0 and report.get("has_backup"):
        print("\nDB time_records is empty but backup exists. Running safe rescue...")
        print(json.dumps(rescue_time_records_if_empty(trigger="tool_check"), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
