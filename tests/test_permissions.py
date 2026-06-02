from __future__ import annotations

from spt_core.services.employee_service import create_employee
from spt_core.services.work_order_service import create_work_order


def test_operator_cannot_create_employee(test_db, operator_actor):
    result = create_employee(operator_actor, "E001", "王小明")
    assert not result.ok


def test_supervisor_can_create_work_order(test_db, supervisor_actor):
    result = create_work_order(supervisor_actor, "WO100")
    assert result.ok
