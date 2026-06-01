# -*- coding: utf-8 -*-
"""V168 smoke/static check for 01 time-record page performance patch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()

    service_path = ROOT / "services" / "time_record_service.py"
    page_candidates = [
        ROOT / "pages" / "01_01. 工時紀錄.py",
        *sorted((ROOT / "pages").glob("01_01.*.py")),
    ]
    page_path = next((p for p in page_candidates if p.exists()), None)

    service_text = service_path.read_text(encoding="utf-8") if service_path.exists() else ""
    page_text = page_path.read_text(encoding="utf-8") if page_path else ""

    checks = {
        "service_exists": service_path.exists(),
        "page_exists": page_path is not None,
        "has_v168_cache": "V168 01 TIME RECORD PAGE PERFORMANCE GUARD" in service_text,
        "has_v168_clear_function": "clear_v168_time_record_runtime_cache" in service_text,
        "wraps_today_records": "def today_records(include_finished: bool = True, unfinished_only: bool = False)" in service_text and "('today_records'" in service_text,
        "wraps_active_refresh": "def refresh_active_records_for_employee" in service_text and "_V168_ACTIVE_REFRESH_TTL_SECONDS" in service_text,
        "page_live_url_sync_disabled": "# _v105_inject_live_work_order_keyword_sync()" in page_text,
        "no_new_mojibake_page_required": not any("#U" in p.name for p in [page_path] if p is not None),
    }
    ok = all(checks.values())
    result = {
        "version": "V168",
        "title": "01 time record interaction performance guard",
        "ok": ok,
        "checks": checks,
        "page_path": str(page_path.relative_to(ROOT)) if page_path else "",
        "notes": [
            "This check is static and safe: it does not read/write time records.",
            "Run compileall separately after applying the patch.",
        ],
    }
    if args.json_path:
        out = ROOT / args.json_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
