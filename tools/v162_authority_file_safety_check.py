# -*- coding: utf-8 -*-
"""SPT V162 authority JSON safety checker.

Usage:
  python tools/v162_authority_file_safety_check.py
  python tools/v162_authority_file_safety_check.py --repair
  python tools/v162_authority_file_safety_check.py --json reports/v162_authority_health.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.safe_file_write_service import authority_file_health, repair_corrupted_json_files, atomic_write_json_safely


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true", help="Restore corrupted JSON files from latest valid safety backup.")
    ap.add_argument("--json", default="", help="Write JSON report to this path.")
    args = ap.parse_args()

    if args.repair:
        result = repair_corrupted_json_files(dry_run=False)
    else:
        result = authority_file_health()

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(text)
    if args.json:
        out = PROJECT_ROOT / args.json
        atomic_write_json_safely(out, result, reason="v162_authority_file_safety_check_report", create_bak=True)
        print(f"Report written: {out}")
    invalid = int(result.get("invalid_files", 0) or 0) if isinstance(result, dict) else 0
    return 2 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
