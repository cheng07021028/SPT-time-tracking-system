from __future__ import annotations

from typing import Any

from ..db import execute, fetch_all, fetch_one, transaction
from ..result import Result
from ..utils import json_dumps, json_loads, now_iso
from .log_service import append_log
from .permission_service import require_permission


def get_setting(key: str, default: Any = None) -> Any:
    with transaction() as conn:
        row = fetch_one(conn, "SELECT setting_value FROM system_settings WHERE setting_key=:key", {"key": key})
    if not row:
        return default
    return json_loads(row.get("setting_value"), default)


def list_settings(actor: dict) -> Result:
    perm = require_permission(actor, "setting.manage")
    if not perm.ok:
        return perm
    with transaction() as conn:
        rows = fetch_all(conn, "SELECT * FROM system_settings ORDER BY setting_key")
    for row in rows:
        row["parsed_value"] = json_loads(row.get("setting_value"), row.get("setting_value"))
    return Result.success(data=rows)


def set_setting(actor: dict, key: str, value: Any) -> Result:
    perm = require_permission(actor, "setting.manage")
    if not perm.ok:
        return perm
    now = now_iso()
    with transaction() as conn:
        before = fetch_one(conn, "SELECT * FROM system_settings WHERE setting_key=:key", {"key": key})
        if before:
            execute(conn, "UPDATE system_settings SET setting_value=:value, updated_at=:updated_at, updated_by=:updated_by WHERE setting_key=:key", {"key": key, "value": json_dumps(value), "updated_at": now, "updated_by": actor.get("username")})
        else:
            execute(conn, "INSERT INTO system_settings(setting_key, setting_value, updated_at, updated_by) VALUES(:key, :value, :updated_at, :updated_by)", {"key": key, "value": json_dumps(value), "updated_at": now, "updated_by": actor.get("username")})
        after = fetch_one(conn, "SELECT * FROM system_settings WHERE setting_key=:key", {"key": key})
        log_id = append_log(conn, actor=actor.get("username"), module="13_系統設定", action="set_setting", target_type="setting", target_id=key, before=before, after=after)
    return Result.success("設定已更新", data=after, log_id=log_id)
