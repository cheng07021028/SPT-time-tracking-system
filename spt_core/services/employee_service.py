from __future__ import annotations

from typing import Any

from ..db import execute, fetch_all, fetch_one, transaction
from ..result import Result
from ..utils import now_iso, json_dumps, new_id
from .log_service import append_log
from .permission_service import require_permission


def list_employees(active_only: bool = False) -> Result:
    sql = "SELECT * FROM employees WHERE deleted_at IS NULL"
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY employee_id"
    with transaction() as conn:
        rows = fetch_all(conn, sql)
    return Result.success(data=rows)


def get_employee(employee_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        return fetch_one(conn, "SELECT * FROM employees WHERE employee_id=:employee_id AND deleted_at IS NULL", {"employee_id": employee_id})


def create_employee(actor: dict, employee_id: str, employee_name: str, department: str = "", team: str = "", role: str = "", permission_group: str = "operator", idempotency_key: str | None = None) -> Result:
    perm = require_permission(actor, "employee.write")
    if not perm.ok:
        return perm
    employee_id = employee_id.strip()
    employee_name = employee_name.strip()
    if not employee_id or not employee_name:
        return Result.failure("工號與姓名不可空白")
    now = now_iso()
    with transaction() as conn:
        if idempotency_key:
            existing_key = fetch_one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=:key", {"key": idempotency_key})
            if existing_key:
                return Result.success("此新增請求已處理，未重複新增", warnings=["idempotency_key duplicated"], data=existing_key)
        existing = fetch_one(conn, "SELECT * FROM employees WHERE employee_id=:employee_id", {"employee_id": employee_id})
        if existing:
            if existing.get("deleted_at") is None:
                return Result.failure("工號已存在，不可重複新增")
            return Result.failure("此工號曾被刪除。為保留稽核鏈，請使用不同工號或建立正式復原功能。")
        data = {
            "employee_id": employee_id,
            "employee_name": employee_name,
            "department": department.strip(),
            "team": team.strip(),
            "role": role.strip(),
            "permission_group": permission_group.strip() or "operator",
            "created_at": now,
            "updated_at": now,
        }
        execute(
            conn,
            """
            INSERT INTO employees(employee_id, employee_name, department, team, role, active, permission_group, created_at, updated_at, version)
            VALUES(:employee_id, :employee_name, :department, :team, :role, 1, :permission_group, :created_at, :updated_at, 1)
            """,
            data,
        )
        if idempotency_key:
            execute(conn, "INSERT INTO idempotency_keys(idempotency_key, module, action, target_id, created_at, result_ref) VALUES(:key, '04_人員名單', 'create_employee', :target_id, :created_at, :result_ref)", {"key": idempotency_key, "target_id": employee_id, "created_at": now, "result_ref": employee_id})
        log_id = append_log(conn, actor=actor.get("username"), module="04_人員名單", action="create_employee", target_type="employee", target_id=employee_id, after=data)
    return Result.success("人員已新增", data=data, log_id=log_id)


def update_employee(actor: dict, employee_id: str, **updates) -> Result:
    perm = require_permission(actor, "employee.write")
    if not perm.ok:
        return perm
    allowed = {"employee_name", "department", "team", "role", "active", "permission_group"}
    data = {k: v for k, v in updates.items() if k in allowed}
    if not data:
        return Result.failure("沒有可更新欄位")
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM employees WHERE employee_id=:employee_id AND deleted_at IS NULL", {"employee_id": employee_id})
        if not before:
            return Result.failure("找不到人員")
        params = {"employee_id": employee_id, "updated_at": now_iso()}
        assignments = []
        for key, value in data.items():
            assignments.append(f"{key}=:{key}")
            params[key] = 1 if key == "active" and bool(value) else 0 if key == "active" else value
        sql = "UPDATE employees SET " + ", ".join(assignments) + ", updated_at=:updated_at, version=version+1 WHERE employee_id=:employee_id"
        execute(conn, sql, params)
        after = fetch_one(conn, "SELECT * FROM employees WHERE employee_id=:employee_id", {"employee_id": employee_id})
        log_id = append_log(conn, actor=actor.get("username"), module="04_人員名單", action="update_employee", target_type="employee", target_id=employee_id, before=before, after=after)
    return Result.success("人員資料已更新", data=after, log_id=log_id)


def soft_delete_employee(actor: dict, employee_id: str, reason: str = "") -> Result:
    perm = require_permission(actor, "employee.delete")
    if not perm.ok:
        return perm
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM employees WHERE employee_id=:employee_id AND deleted_at IS NULL", {"employee_id": employee_id})
        if not before:
            return Result.failure("找不到人員或已刪除")
        execute(conn, "UPDATE employees SET active=0, deleted_at=:deleted_at, deleted_by=:deleted_by, updated_at=:updated_at, version=version+1 WHERE employee_id=:employee_id", {"employee_id": employee_id, "deleted_at": now, "deleted_by": actor.get("username"), "updated_at": now})
        delete_event_id = new_id("del")
        execute(conn, "INSERT INTO delete_events(delete_event_id, target_table, target_id, deleted_by, deleted_at, reason, before_snapshot) VALUES(:id, 'employees', :target_id, :deleted_by, :deleted_at, :reason, :before_snapshot)", {"id": delete_event_id, "target_id": employee_id, "deleted_by": actor.get("username"), "deleted_at": now, "reason": reason, "before_snapshot": json_dumps(before)})
        log_id = append_log(conn, actor=actor.get("username"), module="04_人員名單", action="soft_delete_employee", target_type="employee", target_id=employee_id, before=before, after={"deleted_at": now, "reason": reason})
    return Result.success("人員已停用並留下刪除事件", log_id=log_id)
