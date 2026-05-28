# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.regression_test_service import run_v157_regression_suite, export_v157_regression_excel_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="V157 non-destructive regression + 50-user stress simulation")
    parser.add_argument("--workers", type=int, default=50, help="simulated concurrent users, default 50")
    parser.add_argument("--works-per-worker", type=int, default=2, help="parallel active works per simulated user, default 2")
    parser.add_argument("--no-import-checks", action="store_true", help="skip import/signature checks")
    parser.add_argument("--excel", default="", help="optional Excel report output path")
    args = parser.parse_args()

    def progress(pct: float, msg: str) -> None:
        print(f"[{pct:5.1%}] {msg}", flush=True)

    result = run_v157_regression_suite(
        worker_count=args.workers,
        works_per_worker=args.works_per_worker,
        include_import_checks=not args.no_import_checks,
        progress_callback=progress,
    )
    summary = result.get("summary", {})
    print("\n========== V157 Regression Summary ==========")
    for k in ["pass_count", "warn_count", "fail_count", "total_checks", "expected_records", "sandbox_root"]:
        print(f"{k}: {summary.get(k)}")
    print(f"elapsed_seconds: {result.get('elapsed_seconds')}")
    print(f"ok: {result.get('ok')}")

    if args.excel:
        out = Path(args.excel)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(export_v157_regression_excel_bytes(result))
        print(f"Excel report: {out}")

    if not bool(result.get("ok")):
        checks = result.get("checks")
        try:
            failed = checks[checks["severity"].astype(str) == "FAIL"]
            print("\nFAILED CHECKS:")
            print(failed[["category", "check", "detail"]].to_string(index=False))
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
