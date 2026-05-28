# -*- coding: utf-8 -*-
"""V164B smoke test for LOG-only pending recovery.

This test is dry-run only. It verifies that the recovery function can inspect
LOG_START_MISSING_TIME_RECORD issues and prepare pending records without writing
01/02 authority files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from services.time_record_integrity_service import recover_log_only_start_records_to_pending

    result: dict[str, Any] = recover_log_only_start_records_to_pending(
        github=False,
        start_date=args.start,
        end_date=args.end,
        dry_run=True,
    )
    payload = {
        "test": "v164b_log_only_recovery_smoke_test",
        "ok": bool(result.get("ok")) and bool(result.get("dry_run")),
        "dry_run": result.get("dry_run"),
        "candidate_count": result.get("candidate_count", 0),
        "created_01_count": result.get("created_01_count", 0),
        "created_02_count": result.get("created_02_count", 0),
        "skipped_count": result.get("skipped_count", 0),
        "reason": result.get("reason", ""),
    }
    if args.json_path:
        out = PROJECT_ROOT / args.json_path if not Path(args.json_path).is_absolute() else Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
