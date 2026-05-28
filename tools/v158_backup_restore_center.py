# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.backup_restore_service import (
    create_full_backup_snapshot,
    inspect_backup_zip_bytes,
    list_backup_snapshots,
    restore_missing_time_records_from_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="SPT V158 backup / restore center CLI")
    parser.add_argument("--create", action="store_true", help="Create a full backup ZIP under data/permanent_store/_backups/v158")
    parser.add_argument("--list", action="store_true", help="List recent local backup ZIPs")
    parser.add_argument("--inspect", type=str, default="", help="Inspect a backup ZIP path")
    parser.add_argument("--restore-missing", type=str, default="", help="Non-destructively restore missing time_records from backup ZIP")
    parser.add_argument("--apply", action="store_true", help="Actually apply restore. Default is dry-run.")
    parser.add_argument("--no-github", action="store_true", help="Do not upload authority files to GitHub during restore")
    args = parser.parse_args()

    if args.create:
        result = create_full_backup_snapshot(reason="cli_v158_backup", save_to_disk=True)
        result = {k: v for k, v in result.items() if k != "zip_bytes"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.list:
        print(json.dumps(list_backup_snapshots(), ensure_ascii=False, indent=2))
        return 0
    if args.inspect:
        data = Path(args.inspect).read_bytes()
        print(json.dumps(inspect_backup_zip_bytes(data), ensure_ascii=False, indent=2))
        return 0
    if args.restore_missing:
        data = Path(args.restore_missing).read_bytes()
        result = restore_missing_time_records_from_backup(data, dry_run=not args.apply, github=not args.no_github, reason="cli_v158_restore_missing")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
