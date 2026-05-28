# -*- coding: utf-8 -*-
"""V172 SQLite index installation and verification tool."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.db_service import DB_PATH, ensure_database  # noqa: E402
from services.sqlite_index_service import (  # noqa: E402
    apply_sqlite_performance_indexes,
    collect_sqlite_index_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="V172 SQLite performance index check")
    parser.add_argument("--json", dest="json_path", default="", help="write report JSON path")
    parser.add_argument("--status-only", action="store_true", help="do not create missing indexes")
    parser.add_argument("--optimize", action="store_true", help="also run PRAGMA optimize after index creation")
    args = parser.parse_args()

    ensure_database()
    if args.status_only:
        result = collect_sqlite_index_status(DB_PATH)
        result["mode"] = "status_only"
    else:
        apply_result = apply_sqlite_performance_indexes(DB_PATH, run_optimize=bool(args.optimize))
        status = collect_sqlite_index_status(DB_PATH)
        result = {
            "ok": bool(apply_result.get("ok")) and bool(status.get("ok")),
            "mode": "apply_and_check",
            "db_path": str(DB_PATH),
            "apply": apply_result,
            "status": status,
        }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_path:
        out = Path(args.json_path)
        if not out.is_absolute():
            out = PROJECT_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"V172 SQLite index report written: {out}")
    else:
        print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
