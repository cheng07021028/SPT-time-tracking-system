# -*- coding: utf-8 -*-
"""V166B LOG-only pending close smoke test.

This test is intentionally non-destructive.  It imports the service, collects real
pending rows read-only, and validates the close calculation path using dry-run or
a synthetic private row when no real candidate exists.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _json_default(value: Any) -> Any:
    try:
        import pandas as pd
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (datetime,)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from services.log_only_pending_close_service import (
        collect_log_only_pending_close_candidates,
        close_log_only_pending_records,
        _close_one_row,  # private smoke-test validation only; no writes.
    )

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=max(1, int(args.days)))).strftime("%Y-%m-%d")
    snapshot = collect_log_only_pending_close_candidates(start, end, suggestion_max_hours=18)
    rows = snapshot.get("rows", []) or []
    dry_run_result: dict[str, Any] | None = None

    # If there is a real row with a suggested end, validate the public dry-run path.
    for row in rows:
        if row.get("結束時間 / End Timestamp"):
            dry_run_result = close_log_only_pending_records([
                {
                    "identity_key": row.get("identity_key"),
                    "record_key": row.get("record_key"),
                    "id": row.get("id"),
                    "end_timestamp": row.get("結束時間 / End Timestamp"),
                    "close_status": row.get("結束狀態 / Close Status") or "補登結束",
                    "note": "V166B smoke test dry-run only",
                }
            ], github=False, dry_run=True)
            break

    # Always validate calculation/field-update logic with a synthetic pending row.
    synthetic_row = {
        "id": "V166BTEST001",
        "record_key": "LOGRECOVERY|SPTTEST|25MTEST|S.T.|2026-05-01 08:00:00|V166BTEST001",
        "status": "待人工確認",
        "work_order": "25MTEST",
        "process_name": "S.T.",
        "employee_id": "SPTTEST",
        "employee_name": "測試人員",
        "start_timestamp": "2026-05-01 08:00:00",
        "start_date": "2026-05-01",
        "start_time": "08:00:00",
        "source": "V164B_LOG_ONLY_RECOVERY",
        "recovery_status": "待人工確認",
        "remark": "V164B_LOG_ONLY_RECOVERY smoke-test synthetic row",
    }
    synthetic_closed = _close_one_row(
        synthetic_row,
        {"end_timestamp": "2026-05-01 10:00:00", "close_status": "補登結束", "note": "synthetic smoke test"},
    )

    checks = []
    checks.append({"name": "import_service", "ok": True})
    checks.append({"name": "collect_read_only", "ok": bool(snapshot.get("ok")), "pending_count": snapshot.get("pending_count", 0)})
    checks.append({"name": "synthetic_closed_status", "ok": synthetic_closed.get("source") == "V166B_LOG_ONLY_MANUAL_CLOSED"})
    checks.append({"name": "synthetic_work_hours_positive", "ok": float(synthetic_closed.get("work_hours") or 0) > 0})
    checks.append({"name": "synthetic_has_end_timestamp", "ok": bool(synthetic_closed.get("end_timestamp"))})
    if dry_run_result is not None:
        checks.append({"name": "real_candidate_dry_run", "ok": bool(dry_run_result.get("ok")), "closed_count": dry_run_result.get("closed_count", 0)})
    else:
        checks.append({"name": "real_candidate_dry_run", "ok": True, "skipped": "no_real_candidate_with_suggested_end"})

    ok = all(bool(c.get("ok")) for c in checks)
    result = {
        "ok": ok,
        "version": "V166B_LOG_ONLY_PENDING_CLOSE",
        "project_root": str(PROJECT_ROOT),
        "date_range": f"{start} ~ {end}",
        "checks": checks,
        "snapshot_summary": {k: v for k, v in snapshot.items() if k not in {"rows", "dataframe"}},
        "dry_run_result": dry_run_result,
    }
    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
