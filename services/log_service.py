# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
import getpass
from .db_service import execute, query_df


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:
    execute(
        """
        INSERT INTO system_logs
        (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user_name or getpass.getuser(),
            action_type,
            target_table,
            str(target_id or ""),
            message,
            detail,
            level,
        ),
    )


def load_logs(limit: int = 500):
    return query_df("SELECT * FROM system_logs ORDER BY id DESC LIMIT ?", (limit,))
