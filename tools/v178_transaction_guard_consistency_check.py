# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="V178 transaction guard and consistency smoke check")
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()

    result = {"version": "V178", "ok": True, "checks": {}}
    try:
        from services import time_record_transaction_guard_service as guard
        guard.ensure_v178_schema()
        result["checks"]["guard_schema"] = guard.audit_v178_state()
        op_key = "v178_check_dummy"
        c1 = guard.claim_operation("CHECK", op_key, ttl_seconds=5, payload={"check": True})
        guard.complete_operation(op_key, result_id=123, result_count=1, status="DONE")
        c2 = guard.claim_operation("CHECK", op_key, ttl_seconds=5, payload={"check": True})
        result["checks"]["operation_guard"] = {"first_claimed": bool(c1.get("claimed")), "second_duplicate": bool(c2.get("duplicate")), "second_result_id": c2.get("result_id")}
        if not c1.get("claimed") or not c2.get("duplicate") or int(c2.get("result_id") or 0) != 123:
            result["ok"] = False
    except Exception as exc:
        result["ok"] = False
        result["checks"]["guard_error"] = str(exc)

    try:
        import services.time_record_service as trs
        required = [
            "start_work", "finish_work", "load_records", "today_records", "delete_time_records",
            "save_time_records", "audit_time_record_integrity_v178",
        ]
        missing = [name for name in required if not hasattr(trs, name)]
        result["checks"]["time_record_service_functions"] = {"missing": missing}
        if missing:
            result["ok"] = False
        audit = trs.audit_time_record_integrity_v178()
        result["checks"]["time_record_v178_audit"] = audit
    except Exception as exc:
        result["ok"] = False
        result["checks"]["time_record_service_error"] = str(exc)

    try:
        import services.log_service as logs
        result["checks"]["log_service_write_log"] = {"exists": hasattr(logs, "write_log")}
    except Exception as exc:
        result["ok"] = False
        result["checks"]["log_service_error"] = str(exc)

    if args.json_path:
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
