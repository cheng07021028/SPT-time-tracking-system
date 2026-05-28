# -*- coding: utf-8 -*-
"""V166 system monitoring smoke test.

Usage:
    python tools/v166_system_monitoring_check.py --json reports/v166_system_monitoring.json

This is read-only.  It does not write production records, does not repair, does
not delete, and does not upload to GitHub.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.system_monitoring_service import collect_system_monitoring_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    parser.add_argument("--include-integrity", action="store_true")
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    snapshot = collect_system_monitoring_snapshot(
        work_date=args.date or None,
        include_integrity_audit=bool(args.include_integrity),
    )
    result = {
        "ok": True,
        "version": snapshot.get("version"),
        "level": snapshot.get("level"),
        "risk_score": snapshot.get("risk_score"),
        "read_only": snapshot.get("read_only"),
        "production_write_path_changed": snapshot.get("production_write_path_changed"),
        "metrics": snapshot.get("metrics"),
        "warnings": snapshot.get("warnings"),
        "summary_rows_count": len(snapshot.get("summary_rows", []) or []),
        "active_preview_count": len(snapshot.get("active_work_preview_rows", []) or []),
        "source_rows_count": len(snapshot.get("source_rows", []) or []),
    }
    if snapshot.get("read_only") is not True:
        result["ok"] = False
        result.setdefault("errors", []).append("read_only flag is not True")
    if snapshot.get("production_write_path_changed") is not False:
        result["ok"] = False
        result.setdefault("errors", []).append("production_write_path_changed must remain False")
    if not snapshot.get("summary_rows"):
        result["ok"] = False
        result.setdefault("errors", []).append("summary rows are empty")

    if args.json_path:
        p = PROJECT_ROOT / args.json_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
