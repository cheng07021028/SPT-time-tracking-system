from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spt_core.db import init_db, reset_for_tests
from spt_core.services.employee_service import create_employee
from spt_core.services.time_record_service import delete_time_record, finish_work, list_time_records, start_work
from spt_core.services.work_order_service import create_work_order
from spt_core.utils import now_dt


def main() -> int:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name}"
    os.environ["SPT_ADMIN_PASSWORD"] = "admin123"
    reset_for_tests()
    init_db()
    actor = {"username": "admin", "role": "admin", "display_name": "系統管理員"}
    assert create_employee(actor, "E001", "測試員").ok
    assert create_work_order(actor, "WO001", "MODEL", "TEST PRODUCT", 10).ok
    start = now_dt()
    r1 = start_work(actor, "E001", "WO001", "DEW", start_at=start)
    assert r1.ok, r1
    r2 = finish_work(actor, r1.data["record_id"], finish_at=start + timedelta(minutes=90))
    assert r2.ok, r2
    rows = list_time_records({"employee_id": "E001"}).data
    assert rows and rows[0]["status"] == "completed"
    r3 = delete_time_record(actor, r1.data["record_id"], reason="smoke test")
    assert r3.ok, r3
    rows2 = list_time_records({"employee_id": "E001"}).data
    assert not rows2
    print("Smoke test passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
