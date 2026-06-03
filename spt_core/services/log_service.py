from __future__ import annotations

from typing import Any

from ..db import fetch_all, execute, transaction
from ..result import Result
from ..utils import APP_VERSION, json_dumps, new_id, now_iso


def append_log(
    conn,
    *,
    actor: str | None,
    module: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: Any = None,
    after: Any = None,
    result: str = "success",
    error_message: str | None = None,
    request_id: str | None = None,
) -> str:
    log_id = new_id("log")
    execute(
        conn,
        """
        INSERT INTO operation_logs(
            log_id, timestamp, actor, module, action, target_type, target_id,
            before_value, after_value, result, error_message, request_id, app_version
        ) VALUES(
            :log_id, :timestamp, :actor, :module, :action, :target_type, :target_id,
            :before_value, :after_value, :result, :error_message, :request_id, :app_version
        )
        """,
        {
            "log_id": log_id,
            "timestamp": now_iso(),
            "actor": actor,
            "module": module,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "before_value": json_dumps(before) if before is not None else None,
            "after_value": json_dumps(after) if after is not None else None,
            "result": result,
            "error_message": error_message,
            "request_id": request_id,
            "app_version": APP_VERSION,
        },
    )
    return log_id


def list_logs(module: str | None = None, actor: str | None = None, limit: int = 200) -> Result:
    limit = max(1, min(int(limit), 5000))
    sql = "SELECT * FROM operation_logs WHERE 1=1"
    params: dict[str, Any] = {}
    if module:
        sql += " AND module=:module"
        params["module"] = module
    if actor:
        sql += " AND actor=:actor"
        params["actor"] = actor
    sql += f" ORDER BY timestamp DESC LIMIT {limit}"
    with transaction() as conn:
        rows = fetch_all(conn, sql, params)
    return Result.success(data=rows)
