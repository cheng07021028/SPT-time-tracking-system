from __future__ import annotations

from ..db import execute, fetch_all, transaction
from ..result import Result
from ..utils import new_id, now_iso


def append_login_event(conn, *, username: str | None, display_name: str | None, role: str | None, result: str, session_id: str | None = None, error_message: str | None = None) -> str:
    event_id = new_id("login")
    execute(
        conn,
        """
        INSERT INTO login_events(login_event_id, timestamp, username, display_name, role, login_result, session_id, error_message, logout_time)
        VALUES(:login_event_id, :timestamp, :username, :display_name, :role, :login_result, :session_id, :error_message, NULL)
        """,
        {
            "login_event_id": event_id,
            "timestamp": now_iso(),
            "username": username,
            "display_name": display_name,
            "role": role,
            "login_result": result,
            "session_id": session_id,
            "error_message": error_message,
        },
    )
    return event_id


def list_login_events(username: str | None = None, limit: int = 200) -> Result:
    limit = max(1, min(int(limit), 5000))
    sql = "SELECT * FROM login_events WHERE 1=1"
    params: dict[str, str] = {}
    if username:
        sql += " AND username=:username"
        params["username"] = username
    sql += f" ORDER BY timestamp DESC LIMIT {limit}"
    with transaction() as conn:
        rows = fetch_all(conn, sql, params)
    return Result.success(data=rows)
