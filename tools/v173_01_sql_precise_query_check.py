# -*- coding: utf-8 -*-
"""V173 smoke check: 01 SQL precise query optimization.
This check does not write business data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    result = {
        "ok": False,
        "version": "V173",
        "checks": {},
        "errors": [],
    }
    try:
        import services.time_record_service as trs
        required = [
            "get_v173_01_query_optimization_status",
            "today_records_for_employee",
            "clear_v173_01_precise_query_cache",
            "get_active_records",
            "today_records",
            "load_records",
        ]
        for name in required:
            result["checks"][name] = callable(getattr(trs, name, None))
        try:
            status = trs.get_v173_01_query_optimization_status()
        except Exception as exc:
            status = {"error": str(exc)}
        result["status"] = status
        result["ok"] = all(result["checks"].values()) and bool(status.get("enabled")) and not bool(status.get("visual_changed"))
    except Exception as exc:
        result["errors"].append(str(exc))
    if args.json_path:
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
