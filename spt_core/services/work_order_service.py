from __future__ import annotations

from typing import Any

from ..db import execute, fetch_all, fetch_one, transaction
from ..result import Result
from ..utils import json_dumps, json_loads, new_id, now_iso
from .log_service import append_log
from .permission_service import require_permission


def list_work_orders(active_only: bool = False) -> Result:
    sql = "SELECT * FROM work_orders WHERE deleted_at IS NULL"
    if active_only:
        sql += " AND status IN ('open','running')"
    sql += " ORDER BY updated_at DESC, work_order_no"
    with transaction() as conn:
        rows = fetch_all(conn, sql)
    for row in rows:
        row["process_flow_parsed"] = json_loads(row.get("process_flow"), [])
    return Result.success(data=rows)


def create_work_order(actor: dict, work_order_no: str, model: str = "", product_name: str = "", planned_qty: float = 0, process_flow: list[str] | None = None) -> Result:
    perm = require_permission(actor, "work_order.write")
    if not perm.ok:
        return perm
    work_order_no = work_order_no.strip()
    if not work_order_no:
        return Result.failure("製令號不可空白")
    now = now_iso()
    with transaction() as conn:
        existing = fetch_one(conn, "SELECT * FROM work_orders WHERE work_order_no=:work_order_no", {"work_order_no": work_order_no})
        if existing:
            if existing.get("deleted_at") is None:
                return Result.failure("製令已存在，不可重複新增")
            return Result.failure("此製令曾被刪除。為保留稽核鏈，請使用不同製令號或建立正式復原功能。")
        data = {
            "work_order_no": work_order_no,
            "model": model.strip(),
            "product_name": product_name.strip(),
            "planned_qty": float(planned_qty or 0),
            "process_flow": json_dumps(process_flow or []),
            "created_at": now,
            "updated_at": now,
        }
        execute(
            conn,
            """
            INSERT INTO work_orders(work_order_no, model, product_name, planned_qty, completed_qty, status, process_flow, created_at, updated_at, version)
            VALUES(:work_order_no, :model, :product_name, :planned_qty, 0, 'open', :process_flow, :created_at, :updated_at, 1)
            """,
            data,
        )
        log_id = append_log(conn, actor=actor.get("username"), module="03_製令管理", action="create_work_order", target_type="work_order", target_id=work_order_no, after=data)
    return Result.success("製令已新增", data=data, log_id=log_id)


def update_work_order(actor: dict, work_order_no: str, **updates) -> Result:
    perm = require_permission(actor, "work_order.write")
    if not perm.ok:
        return perm
    allowed = {"model", "product_name", "planned_qty", "completed_qty", "status", "process_flow"}
    data = {k: v for k, v in updates.items() if k in allowed}
    if not data:
        return Result.failure("沒有可更新欄位")
    if "process_flow" in data and not isinstance(data["process_flow"], str):
        data["process_flow"] = json_dumps(data["process_flow"])
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM work_orders WHERE work_order_no=:work_order_no AND deleted_at IS NULL", {"work_order_no": work_order_no})
        if not before:
            return Result.failure("找不到製令")
        params = {"work_order_no": work_order_no, "updated_at": now_iso()}
        assignments = []
        for key, value in data.items():
            assignments.append(f"{key}=:{key}")
            params[key] = value
        sql = "UPDATE work_orders SET " + ", ".join(assignments) + ", updated_at=:updated_at, version=version+1 WHERE work_order_no=:work_order_no"
        execute(conn, sql, params)
        after = fetch_one(conn, "SELECT * FROM work_orders WHERE work_order_no=:work_order_no", {"work_order_no": work_order_no})
        log_id = append_log(conn, actor=actor.get("username"), module="03_製令管理", action="update_work_order", target_type="work_order", target_id=work_order_no, before=before, after=after)
    return Result.success("製令已更新", data=after, log_id=log_id)


def soft_delete_work_order(actor: dict, work_order_no: str, reason: str = "") -> Result:
    perm = require_permission(actor, "work_order.delete")
    if not perm.ok:
        return perm
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM work_orders WHERE work_order_no=:work_order_no AND deleted_at IS NULL", {"work_order_no": work_order_no})
        if not before:
            return Result.failure("找不到製令或已刪除")
        used = fetch_one(conn, "SELECT record_id FROM time_records WHERE work_order_no=:work_order_no AND deleted_at IS NULL LIMIT 1", {"work_order_no": work_order_no})
        if used:
            return Result.failure("此製令已有工時紀錄，為避免歷史資料斷鏈，請改為 status=closed 或停用，不建議刪除")
        execute(conn, "UPDATE work_orders SET status='deleted', deleted_at=:deleted_at, deleted_by=:deleted_by, updated_at=:updated_at, version=version+1 WHERE work_order_no=:work_order_no", {"work_order_no": work_order_no, "deleted_at": now, "deleted_by": actor.get("username"), "updated_at": now})
        delete_event_id = new_id("del")
        execute(conn, "INSERT INTO delete_events(delete_event_id, target_table, target_id, deleted_by, deleted_at, reason, before_snapshot) VALUES(:id, 'work_orders', :target_id, :deleted_by, :deleted_at, :reason, :before_snapshot)", {"id": delete_event_id, "target_id": work_order_no, "deleted_by": actor.get("username"), "deleted_at": now, "reason": reason, "before_snapshot": json_dumps(before)})
        log_id = append_log(conn, actor=actor.get("username"), module="03_製令管理", action="soft_delete_work_order", target_type="work_order", target_id=work_order_no, before=before, after={"deleted_at": now, "reason": reason})
    return Result.success("製令已刪除並留下刪除事件", log_id=log_id)
