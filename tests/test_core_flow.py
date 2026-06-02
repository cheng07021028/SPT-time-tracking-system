from __future__ import annotations

from datetime import timedelta

from spt_core.services.employee_service import create_employee, list_employees
from spt_core.services.log_service import list_logs
from spt_core.services.time_record_service import delete_time_record, finish_work, list_active_records, list_time_records, start_work
from spt_core.services.work_order_service import create_work_order, list_work_orders
from spt_core.utils import now_dt


def test_start_finish_delete_flow(test_db, admin_actor):
    assert create_employee(admin_actor, "E001", "王小明").ok
    assert create_work_order(admin_actor, "WO001", "A1", "產品A", 100).ok

    start = now_dt().replace(hour=8, minute=0, second=0, microsecond=0)
    r = start_work(admin_actor, "E001", "WO001", "DEW", start_at=start)
    assert r.ok, r.errors
    record_id = r.data["record_id"]
    assert len(list_active_records().data) == 1

    finish = finish_work(admin_actor, record_id, finish_at=start + timedelta(minutes=120))
    assert finish.ok, finish.errors
    rows = list_time_records({"employee_id": "E001"}).data
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["work_minutes"] == 120

    deleted = delete_time_record(admin_actor, record_id, reason="測試刪除")
    assert deleted.ok, deleted.errors
    assert list_time_records({"employee_id": "E001"}).data == []
    assert len(list_time_records({"employee_id": "E001"}, include_deleted=True).data) == 1


def test_employee_and_work_order_unique(test_db, admin_actor):
    assert create_employee(admin_actor, "E001", "王小明").ok
    assert not create_employee(admin_actor, "E001", "王小明2").ok
    assert create_work_order(admin_actor, "WO001").ok
    assert not create_work_order(admin_actor, "WO001").ok


def test_group_average_same_three_minute_bucket(test_db, admin_actor):
    assert create_employee(admin_actor, "E001", "王小明").ok
    assert create_work_order(admin_actor, "WO001").ok
    assert create_work_order(admin_actor, "WO002").ok
    start = now_dt().replace(hour=8, minute=1, second=0, microsecond=0)
    r1 = start_work(admin_actor, "E001", "WO001", "DEW", start_at=start)
    r2 = start_work(admin_actor, "E001", "WO002", "DEW", start_at=start + timedelta(minutes=1))
    assert r1.ok and r2.ok
    assert r1.data["group_key"] == r2.data["group_key"]
    f = finish_work(admin_actor, r1.data["record_id"], finish_at=start + timedelta(minutes=60), finish_group=True)
    assert f.ok
    rows = sorted(list_time_records({"employee_id": "E001"}).data, key=lambda x: x["work_order_no"])
    assert len(rows) == 2
    assert {r["status"] for r in rows} == {"completed"}
    assert all(r["average_minutes"] == 30 for r in rows)


def test_log_written(test_db, admin_actor):
    create_employee(admin_actor, "E001", "王小明")
    logs = list_logs(limit=20).data
    assert any(row["action"] == "create_employee" for row in logs)
