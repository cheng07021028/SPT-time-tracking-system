from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import execute, fetch_all, fetch_one, transaction
from ..result import Result
from ..utils import json_dumps, minute_bucket, new_id, now_dt, now_iso, parse_iso
from .log_service import append_log
from .permission_service import require_permission
from .settings_service import get_setting
from .time_calculation_service import calculate_work_minutes


def _group_key(work_date: str, employee_id: str, process_code: str, start_time: datetime) -> str:
    bucket = minute_bucket(start_time, 3).isoformat(timespec="minutes")
    return f"{work_date}|{employee_id}|{process_code}|{bucket}"


def _get_break_windows() -> list[dict[str, Any]]:
    return get_setting("break_windows", [{"start": "12:00", "end": "13:00", "name": "午休"}])


def _recompute_group_average(conn, group_key: str) -> None:
    rows = fetch_all(conn, "SELECT record_id, start_time, end_time, work_minutes FROM time_records WHERE group_key=:group_key AND deleted_at IS NULL AND end_time IS NOT NULL", {"group_key": group_key})
    count = len(rows)
    if count <= 0:
        return

    # Business rule: records in the same 3-minute bucket are treated as one simultaneous group.
    # The displayed average uses the group span, not each row's tiny start-time offset.
    starts = [parse_iso(row["start_time"]) for row in rows if row.get("start_time")]
    ends = [parse_iso(row["end_time"]) for row in rows if row.get("end_time")]
    if starts and ends:
        group_calc = calculate_work_minutes(min(starts), max(ends), _get_break_windows())
        avg = round(group_calc["work_minutes"] / count, 2)
    else:
        avg = round(sum(float(row.get("work_minutes") or 0) for row in rows) / count, 2)

    for row in rows:
        execute(conn, "UPDATE time_records SET average_minutes=:average_minutes, updated_at=:updated_at, version=version+1 WHERE record_id=:record_id", {"average_minutes": avg, "updated_at": now_iso(), "record_id": row["record_id"]})


def start_work(actor: dict, employee_id: str, work_order_no: str, process_code: str, start_at: datetime | None = None, idempotency_key: str | None = None) -> Result:
    perm = require_permission(actor, "time.start")
    if not perm.ok:
        return perm
    employee_id = employee_id.strip()
    work_order_no = work_order_no.strip()
    process_code = process_code.strip().upper()
    started = start_at or now_dt()
    work_date = started.date().isoformat()
    group_key = _group_key(work_date, employee_id, process_code, started)
    now = now_iso()

    with transaction() as conn:
        if idempotency_key:
            existing_key = fetch_one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=:key", {"key": idempotency_key})
            if existing_key:
                return Result.success("此開始作業請求已處理，未重複新增", warnings=["idempotency_key duplicated"], data=existing_key)

        employee = fetch_one(conn, "SELECT * FROM employees WHERE employee_id=:employee_id AND active=1 AND deleted_at IS NULL", {"employee_id": employee_id})
        if not employee:
            return Result.failure("找不到啟用中的人員")
        work_order = fetch_one(conn, "SELECT * FROM work_orders WHERE work_order_no=:work_order_no AND deleted_at IS NULL AND status IN ('open','running')", {"work_order_no": work_order_no})
        if not work_order:
            return Result.failure("找不到可作業的製令")
        process = fetch_one(conn, "SELECT * FROM processes WHERE process_code=:process_code AND active=1", {"process_code": process_code})
        if not process:
            return Result.failure("找不到啟用中的工段")

        auto_pause = bool(get_setting("auto_pause_different_group", True))
        paused_records = []
        if auto_pause:
            active_rows = fetch_all(conn, "SELECT * FROM time_records WHERE employee_id=:employee_id AND status='active' AND deleted_at IS NULL AND group_key<>:group_key", {"employee_id": employee_id, "group_key": group_key})
            for row in active_rows:
                calc = calculate_work_minutes(parse_iso(row["start_time"]), started, _get_break_windows())
                execute(
                    conn,
                    """
                    UPDATE time_records
                    SET end_time=:end_time, status='paused', raw_minutes=:raw_minutes, work_minutes=:work_minutes,
                        average_minutes=:work_minutes, pause_reason=:pause_reason, updated_by=:updated_by, updated_at=:updated_at, version=version+1
                    WHERE record_id=:record_id
                    """,
                    {
                        "end_time": started.isoformat(timespec="seconds"),
                        "raw_minutes": calc["raw_minutes"],
                        "work_minutes": calc["work_minutes"],
                        "pause_reason": "開始不同群組作業，自動暫停舊作業",
                        "updated_by": actor.get("username"),
                        "updated_at": now,
                        "record_id": row["record_id"],
                    },
                )
                paused_records.append(row["record_id"])
                append_log(conn, actor=actor.get("username"), module="01_工時紀錄", action="auto_pause", target_type="time_record", target_id=row["record_id"], before=row, after={"status": "paused"})

        record_id = new_id("tr")
        data = {
            "record_id": record_id,
            "work_date": work_date,
            "employee_id": employee_id,
            "employee_name": employee["employee_name"],
            "work_order_no": work_order_no,
            "process_code": process_code,
            "process_name": process["process_name"],
            "start_time": started.isoformat(timespec="seconds"),
            "status": "active",
            "group_key": group_key,
            "created_by": actor.get("username"),
            "created_at": now,
            "updated_by": actor.get("username"),
            "updated_at": now,
        }
        execute(
            conn,
            """
            INSERT INTO time_records(
                record_id, work_date, employee_id, employee_name, work_order_no, process_code, process_name,
                start_time, status, group_key, raw_minutes, work_minutes, average_minutes,
                created_by, created_at, updated_by, updated_at, version
            ) VALUES(
                :record_id, :work_date, :employee_id, :employee_name, :work_order_no, :process_code, :process_name,
                :start_time, :status, :group_key, 0, 0, 0,
                :created_by, :created_at, :updated_by, :updated_at, 1
            )
            """,
            data,
        )
        if idempotency_key:
            execute(conn, "INSERT INTO idempotency_keys(idempotency_key, module, action, target_id, created_at, result_ref) VALUES(:key, '01_工時紀錄', 'start_work', :target_id, :created_at, :result_ref)", {"key": idempotency_key, "target_id": record_id, "created_at": now, "result_ref": record_id})
        log_id = append_log(conn, actor=actor.get("username"), module="01_工時紀錄", action="start_work", target_type="time_record", target_id=record_id, after=data)

    warnings = [f"已自動暫停舊作業：{len(paused_records)} 筆"] if paused_records else []
    return Result.success("開始作業完成", data={"record_id": record_id, "group_key": group_key, "paused_records": paused_records}, warnings=warnings, log_id=log_id)


def finish_work(actor: dict, record_id: str, finish_at: datetime | None = None, finish_group: bool = True) -> Result:
    perm = require_permission(actor, "time.finish")
    if not perm.ok:
        return perm
    ended = finish_at or now_dt()
    now = now_iso()
    break_windows = _get_break_windows()
    with transaction() as conn:
        target = fetch_one(conn, "SELECT * FROM time_records WHERE record_id=:record_id AND deleted_at IS NULL", {"record_id": record_id})
        if not target:
            return Result.failure("找不到工時紀錄")
        if target["status"] != "active":
            return Result.failure("此紀錄不是進行中狀態，無法完工")
        if finish_group:
            rows = fetch_all(conn, "SELECT * FROM time_records WHERE group_key=:group_key AND status='active' AND deleted_at IS NULL", {"group_key": target["group_key"]})
        else:
            rows = [target]
        finished_ids = []
        for row in rows:
            calc = calculate_work_minutes(parse_iso(row["start_time"]), ended, break_windows)
            execute(
                conn,
                """
                UPDATE time_records
                SET end_time=:end_time, status='completed', raw_minutes=:raw_minutes, work_minutes=:work_minutes,
                    average_minutes=:work_minutes, updated_by=:updated_by, updated_at=:updated_at, version=version+1
                WHERE record_id=:record_id
                """,
                {
                    "end_time": ended.isoformat(timespec="seconds"),
                    "raw_minutes": calc["raw_minutes"],
                    "work_minutes": calc["work_minutes"],
                    "updated_by": actor.get("username"),
                    "updated_at": now,
                    "record_id": row["record_id"],
                },
            )
            append_log(conn, actor=actor.get("username"), module="01_工時紀錄", action="finish_work", target_type="time_record", target_id=row["record_id"], before=row, after={"status": "completed", **calc})
            finished_ids.append(row["record_id"])
        if bool(get_setting("enable_group_average", True)):
            _recompute_group_average(conn, target["group_key"])
        log_id = append_log(conn, actor=actor.get("username"), module="01_工時紀錄", action="finish_work_batch", target_type="group_key", target_id=target["group_key"], after={"finished_ids": finished_ids})
    return Result.success("完工作業完成", data={"finished_ids": finished_ids}, log_id=log_id)


def delete_time_record(actor: dict, record_id: str, reason: str = "") -> Result:
    perm = require_permission(actor, "time.delete")
    if not perm.ok:
        return perm
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM time_records WHERE record_id=:record_id AND deleted_at IS NULL", {"record_id": record_id})
        if not before:
            return Result.failure("找不到工時紀錄或已刪除")
        execute(
            conn,
            """
            UPDATE time_records SET status='deleted', deleted_at=:deleted_at, deleted_by=:deleted_by,
                delete_reason=:delete_reason, updated_by=:updated_by, updated_at=:updated_at, version=version+1
            WHERE record_id=:record_id
            """,
            {"record_id": record_id, "deleted_at": now, "deleted_by": actor.get("username"), "delete_reason": reason, "updated_by": actor.get("username"), "updated_at": now},
        )
        delete_event_id = new_id("del")
        execute(conn, "INSERT INTO delete_events(delete_event_id, target_table, target_id, deleted_by, deleted_at, reason, before_snapshot) VALUES(:id, 'time_records', :target_id, :deleted_by, :deleted_at, :reason, :before_snapshot)", {"id": delete_event_id, "target_id": record_id, "deleted_by": actor.get("username"), "deleted_at": now, "reason": reason, "before_snapshot": json_dumps(before)})
        log_id = append_log(conn, actor=actor.get("username"), module="01_工時紀錄", action="delete_time_record", target_type="time_record", target_id=record_id, before=before, after={"deleted_at": now, "reason": reason})
        _recompute_group_average(conn, before["group_key"])
    return Result.success("工時紀錄已刪除並留下 tombstone / delete_event", log_id=log_id)


def list_time_records(filters: dict[str, Any] | None = None, include_deleted: bool = False, limit: int | None = None) -> Result:
    filters = filters or {}
    limit = int(limit or filters.get("limit") or 500)
    limit = max(1, min(limit, 10000))
    sql = "SELECT * FROM time_records WHERE 1=1"
    params: dict[str, Any] = {}
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    if filters.get("work_date_from"):
        sql += " AND work_date>=:work_date_from"
        params["work_date_from"] = str(filters["work_date_from"])
    if filters.get("work_date_to"):
        sql += " AND work_date<=:work_date_to"
        params["work_date_to"] = str(filters["work_date_to"])
    if filters.get("employee_id"):
        sql += " AND employee_id=:employee_id"
        params["employee_id"] = filters["employee_id"]
    if filters.get("work_order_no"):
        sql += " AND work_order_no=:work_order_no"
        params["work_order_no"] = filters["work_order_no"]
    if filters.get("process_code"):
        sql += " AND process_code=:process_code"
        params["process_code"] = filters["process_code"]
    if filters.get("status"):
        sql += " AND status=:status"
        params["status"] = filters["status"]
    sql += f" ORDER BY start_time DESC LIMIT {limit}"
    with transaction() as conn:
        rows = fetch_all(conn, sql, params)
    return Result.success(data=rows)


def list_active_records(employee_id: str | None = None) -> Result:
    filters = {"status": "active"}
    if employee_id:
        filters["employee_id"] = employee_id
    return list_time_records(filters, limit=1000)
