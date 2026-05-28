# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.time_record_integrity_service import audit_time_record_integrity, repair_0102_authority_non_destructive, export_audit_excel_bytes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SPT V153 time-record health check and non-destructive repair")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--repair", action="store_true", help="Run non-destructive 01/02 authority repair")
    parser.add_argument("--no-github", action="store_true", help="Do not sync repaired authority files to GitHub")
    parser.add_argument("--excel", default="", help="Optional Excel report path")
    args = parser.parse_args()

    result = audit_time_record_integrity(args.start, args.end)
    print(json.dumps(result.get("summary", {}), ensure_ascii=False, indent=2, default=str))
    issues = result.get("issues")
    try:
        if issues is not None and not issues.empty:
            print("\nTop issues:")
            print(issues.head(50).to_string(index=False))
    except Exception:
        pass

    if args.excel:
        out = Path(args.excel)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(export_audit_excel_bytes(result))
        print(f"Excel written: {out}")

    if args.repair:
        repair = repair_0102_authority_non_destructive(github=not args.no_github, start_date=args.start, end_date=args.end, dry_run=False)
        print("\nRepair result:")
        print(json.dumps(repair, ensure_ascii=False, indent=2, default=str))
        return 0 if repair.get("ok") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
