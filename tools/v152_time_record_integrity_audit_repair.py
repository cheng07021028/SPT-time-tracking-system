# -*- coding: utf-8 -*-
"""V152 工時紀錄完整性稽核 / 修復工具。

用法：
  python tools/v152_time_record_integrity_audit_repair.py
  python tools/v152_time_record_integrity_audit_repair.py --repair

說明：
- 預設只稽核，不寫入資料。
- --repair 會以 append-only event journal / row shard / 01/02 權威檔做非破壞式合併修復。
- 不會用局部畫面資料覆蓋完整歷史。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="SPT V152 time record integrity audit/repair")
    parser.add_argument("--repair", action="store_true", help="run non-destructive repair from event journal")
    parser.add_argument("--no-github", action="store_true", help="do not upload repaired snapshots to GitHub")
    args = parser.parse_args()

    from services.time_record_service import audit_time_record_integrity_v152

    print("========== V152 工時紀錄完整性稽核 ==========")
    audit = audit_time_record_integrity_v152()
    print(json.dumps(audit, ensure_ascii=False, indent=2, default=str))

    if args.repair:
        print("\n========== V152 非破壞式修復 ==========")
        from services.time_record_service import repair_time_records_from_events_v152, sync_time_records_01_02_now
        repair = repair_time_records_from_events_v152("tool_v152_repair_from_events", github=not args.no_github)
        synced = sync_time_records_01_02_now("tool_v152_full_safe_sync", github=not args.no_github)
        print(json.dumps({"repair": repair, "synced_rows": synced}, ensure_ascii=False, indent=2, default=str))

    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
