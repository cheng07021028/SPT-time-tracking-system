# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse, json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from services.duplicate_guard_service import (
        dedupe_work_orders_dataframe,
        dedupe_employees_dataframe,
        dedupe_time_records_exact,
    )
    wo = pd.DataFrame([
        {"id": 1, "work_order": "26M0001-01", "part_no": "A"},
        {"id": 2, "work_order": "26M0001-01", "part_no": "A"},
        {"id": 3, "work_order": "26M0002-01", "part_no": "B"},
    ])
    emp = pd.DataFrame([
        {"id": 1, "employee_id": "SPT001", "employee_name": "A"},
        {"id": 2, "employee_id": "SPT001", "employee_name": "A"},
        {"id": 3, "employee_id": "SPT002", "employee_name": "B"},
    ])
    tr = pd.DataFrame([
        {"id": 1, "record_key": "A", "status": "作業中", "start_timestamp": "2026-05-28 08:00:00"},
        {"id": 2, "record_key": "A", "status": "作業中", "start_timestamp": "2026-05-28 08:00:00"},
        {"id": 3, "record_key": "A", "status": "下班", "start_timestamp": "2026-05-28 08:00:00", "end_timestamp": "2026-05-28 09:00:00"},
    ])
    result = {
        "ok": True,
        "work_orders_before": len(wo),
        "work_orders_after": len(dedupe_work_orders_dataframe(wo)),
        "employees_before": len(emp),
        "employees_after": len(dedupe_employees_dataframe(emp)),
        "time_records_before": len(tr),
        "time_records_after": len(dedupe_time_records_exact(tr)),
        "page14_contains_v166e_form": "v166e_v166b_pending_close_editor_form" in (ROOT / "pages" / "14_14. 資料健康檢查中心.py").read_text(encoding="utf-8"),
        "theme_installs_editor_guard": "install_editor_stability_guards" in (ROOT / "services" / "theme_service.py").read_text(encoding="utf-8"),
    }
    result["ok"] = bool(result["page14_contains_v166e_form"] and result["theme_installs_editor_guard"] and result["work_orders_after"] == 2 and result["employees_after"] == 2 and result["time_records_after"] == 2)
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_path", default="")
    args = ap.parse_args()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
