from __future__ import annotations

from ..db import execute, fetch_all, fetch_one, transaction
from ..result import Result
from ..utils import now_iso
from .log_service import append_log
from .permission_service import require_permission


def list_processes(active_only: bool = False) -> Result:
    sql = "SELECT * FROM processes WHERE 1=1"
    params = {}
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY sort_order, process_code"
    with transaction() as conn:
        rows = fetch_all(conn, sql, params)
    return Result.success(data=rows)


def upsert_process(actor: dict, process_code: str, process_name: str, sort_order: int = 0, active: bool = True, allow_parallel: bool = True, allow_group_average: bool = True, standard_minutes: float = 0) -> Result:
    perm = require_permission(actor, "setting.manage")
    if not perm.ok:
        return perm
    process_code = process_code.strip().upper()
    process_name = process_name.strip()
    if not process_code or not process_name:
        return Result.failure("工段代碼與名稱不可空白")
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM processes WHERE process_code=:process_code", {"process_code": process_code})
        data = {
            "process_code": process_code,
            "process_name": process_name,
            "sort_order": int(sort_order),
            "active": 1 if active else 0,
            "allow_parallel": 1 if allow_parallel else 0,
            "allow_group_average": 1 if allow_group_average else 0,
            "standard_minutes": float(standard_minutes or 0),
            "created_at": now,
            "updated_at": now,
        }
        if before:
            execute(
                conn,
                """
                UPDATE processes SET process_name=:process_name, sort_order=:sort_order, active=:active,
                    allow_parallel=:allow_parallel, allow_group_average=:allow_group_average,
                    standard_minutes=:standard_minutes, updated_at=:updated_at
                WHERE process_code=:process_code
                """,
                data,
            )
            action = "update_process"
        else:
            execute(
                conn,
                """
                INSERT INTO processes(process_code, process_name, sort_order, active, allow_parallel, allow_group_average, standard_minutes, created_at, updated_at)
                VALUES(:process_code, :process_name, :sort_order, :active, :allow_parallel, :allow_group_average, :standard_minutes, :created_at, :updated_at)
                """,
                data,
            )
            action = "create_process"
        after = fetch_one(conn, "SELECT * FROM processes WHERE process_code=:process_code", {"process_code": process_code})
        log_id = append_log(conn, actor=actor.get("username"), module="13_系統設定", action=action, target_type="process", target_id=process_code, before=before, after=after)
    return Result.success("工段設定已儲存", data=after, log_id=log_id)
