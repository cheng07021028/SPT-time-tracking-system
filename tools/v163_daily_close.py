# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.daily_close_service import (  # noqa: E402
    close_work_date,
    daily_close_report,
    export_daily_close_excel_bytes,
    list_daily_close_status,
    reopen_work_date,
)


def main() -> int:
    p = argparse.ArgumentParser(description="SPT V163 daily close / lock CLI")
    p.add_argument("--date", required=False, help="Work date YYYY-MM-DD. Default: today.")
    p.add_argument("--status", action="store_true", help="Show recent daily close status.")
    p.add_argument("--report", action="store_true", help="Show one-day close report.")
    p.add_argument("--close", action="store_true", help="Close and lock the work date.")
    p.add_argument("--reopen", action="store_true", help="Reopen a closed work date.")
    p.add_argument("--note", default="", help="Close note / reopen reason.")
    p.add_argument("--operator", default="cli", help="Operator account/name.")
    p.add_argument("--allow-active", action="store_true", help="Allow close even if active unfinished records exist. Not recommended.")
    p.add_argument("--allow-critical", action="store_true", help="Allow close even if health check has critical issues. Not recommended.")
    p.add_argument("--no-backup", action="store_true", help="Do not create full backup during close.")
    p.add_argument("--excel", default="", help="Export daily close report Excel path.")
    p.add_argument("--json", dest="json_path", default="", help="Write JSON result path.")
    args = p.parse_args()

    if args.close and args.reopen:
        raise SystemExit("--close and --reopen cannot be used together")

    if args.close:
        result = close_work_date(
            args.date,
            closed_by=args.operator,
            note=args.note,
            require_no_active=not args.allow_active,
            create_backup=not args.no_backup,
            block_on_critical_health=not args.allow_critical,
        )
    elif args.reopen:
        result = reopen_work_date(args.date, reopened_by=args.operator, reason=args.note or "CLI reopen")
    elif args.status:
        df = list_daily_close_status(end_date=args.date, days=14)
        result = {"ok": True, "rows": df.to_dict(orient="records")}
        print(df.to_string(index=False))
    else:
        result = daily_close_report(args.date)

    if args.excel:
        out = Path(args.excel)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(export_daily_close_excel_bytes(args.date))
        result["excel_path"] = str(out)
    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if not args.status:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
