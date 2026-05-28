# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.backup_queue_status_service import collect_backup_queue_status, flush_backup_queues_now  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="SPT V155 backup queue status / manual flush")
    ap.add_argument("--flush", action="store_true", help="Manually flush authority/log/event backup queues")
    ap.add_argument("--max-seconds", type=float, default=12.0)
    args = ap.parse_args()
    if args.flush:
        out = flush_backup_queues_now(reason="cli_v155_backup_queue_flush", max_seconds=args.max_seconds)
    else:
        out = collect_backup_queue_status()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    level = str((out.get("after") or out).get("level") or "OK") if isinstance(out, dict) else "OK"
    return 1 if level == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
