# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.performance_profiler_service import (
    EVENT_PATH,
    record_event,
    read_events,
    summarize_events,
    write_summary_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="V171 Performance Profiler report")
    parser.add_argument("--json", dest="json_path", default="reports/v171_performance_profile.json", help="Output JSON report path")
    parser.add_argument("--last-hours", type=float, default=24.0, help="Include events within the last N hours")
    parser.add_argument("--limit", type=int, default=3000, help="Maximum events to read")
    parser.add_argument("--top", type=int, default=30, help="Top rows per summary section")
    parser.add_argument("--self-test", action="store_true", help="Write one sample event before report")
    args = parser.parse_args()

    if args.self_test:
        record_event(
            category="self_test",
            name="tools.v171_performance_profiler_report.self_test",
            duration_ms=999.0,
            ok=True,
            threshold_ms=1.0,
            detail={"note": "profiler write test"},
        )

    summary = write_summary_json(args.json_path, limit=args.limit, last_hours=args.last_hours, top_n=args.top)
    print(json.dumps({
        "ok": True,
        "event_file": str(EVENT_PATH),
        "json_report": str(Path(args.json_path)),
        "event_count": summary.get("event_count", 0),
        "slow_count": summary.get("slow_count", 0),
        "error_count": summary.get("error_count", 0),
        "top_names": summary.get("by_name", [])[:5],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
