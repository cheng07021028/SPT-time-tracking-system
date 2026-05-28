# -*- coding: utf-8 -*-
"""V166C2 dependency repair smoke test.
Checks the services required by latest 14_資料健康檢查中心 page are importable.
This test is read-only and does not write production data.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED = {
    "services.time_record_integrity_service": [
        "audit_time_record_integrity",
        "repair_0102_authority_non_destructive",
        "recover_log_only_start_records_to_pending",
        "export_audit_excel_bytes",
    ],
    "services.system_monitoring_service": [
        "collect_system_monitoring_snapshot",
        "export_monitoring_excel_bytes",
        "monitoring_summary_rows",
    ],
    "services.log_only_pending_close_service": [
        "collect_log_only_pending_close_candidates",
        "close_log_only_pending_records",
        "export_pending_close_excel_bytes",
    ],
    "services.log_snapshot_service": [
        "collect_log_snapshot_recovery_candidates",
        "recover_records_from_log_snapshots",
        "export_log_snapshot_candidates_excel_bytes",
        "get_log_snapshot_status",
        "append_snapshot_to_detail",
    ],
    "services.log_service": ["write_log"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    ok = True
    for mod_name, attrs in REQUIRED.items():
        item: dict[str, Any] = {"module": mod_name, "imported": False, "missing": []}
        try:
            mod = importlib.import_module(mod_name)
            item["imported"] = True
            for attr in attrs:
                if not hasattr(mod, attr):
                    item["missing"].append(attr)
            if item["missing"]:
                ok = False
        except Exception as exc:
            ok = False
            item["error"] = repr(exc)
        results.append(item)

    payload = {
        "version": "V166C2_missing_dependency_repair",
        "ok": ok,
        "all_required_services_importable": ok,
        "results": results,
    }
    if args.json_path:
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
