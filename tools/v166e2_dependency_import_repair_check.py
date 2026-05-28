# -*- coding: utf-8 -*-
"""V166E2 dependency/import repair smoke test."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED_LOG_SNAPSHOT_NAMES = [
    "collect_log_snapshot_recovery_candidates",
    "recover_records_from_log_snapshots",
    "export_log_snapshot_candidates_excel_bytes",
    "get_log_snapshot_status",
    "get_log_snapshot_coverage_status",
    "backfill_missing_log_snapshots",
    "export_log_snapshot_coverage_excel_bytes",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    result = {
        "version": "V166E2_dependency_import_repair",
        "ok": True,
        "critical_failures": 0,
        "checks": [],
        "missing": [],
    }
    try:
        mod = importlib.import_module("services.log_snapshot_service")
        for name in REQUIRED_LOG_SNAPSHOT_NAMES:
            has = hasattr(mod, name)
            result["checks"].append({"name": name, "exists": has})
            if not has:
                result["missing"].append(name)
    except Exception as exc:
        result["ok"] = False
        result["critical_failures"] += 1
        result["reason"] = str(exc)
    if result["missing"]:
        result["ok"] = False
        result["critical_failures"] += len(result["missing"])
    page_path = ROOT / "pages" / "14_14. 資料健康檢查中心.py"
    page_text = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
    guard_ok = "V166C_LOG_SNAPSHOT_IMPORT_OK" in page_text and "_v166e2_missing_log_snapshot_result" in page_text
    result["page_import_guard_present"] = guard_ok
    if not guard_ok:
        result["ok"] = False
        result["critical_failures"] += 1
    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
