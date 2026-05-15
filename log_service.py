# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime
import getpass
from typing import Any

from .db_service import execute, query_df, clear_query_cache


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


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


def load_logs(
    limit: int = 500,
    start_date: Any | None = None,
    end_date: Any | None = None,
    action_type: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
):
    """Load system logs with optional SQL-side filtering.

    V2.00：支援 06｜LOG查詢 依日期區間查詢，避免每次先載入大量 LOG 再前端過濾。
    """
    where: list[str] = []
    params: list[Any] = []

    s = _date_text(start_date)
    e = _date_text(end_date)
    if s:
        where.append("date(log_time) >= date(?)")
        params.append(s)
    if e:
        where.append("date(log_time) <= date(?)")
        params.append(e)
    if action_type:
        where.append("action_type = ?")
        params.append(str(action_type))
    if level and str(level).upper() != "ALL":
        where.append("level = ?")
        params.append(str(level))
    if keyword:
        kw = f"%{keyword}%"
        where.append("(" + " OR ".join([
            "COALESCE(user_name,'') LIKE ?",
            "COALESCE(action_type,'') LIKE ?",
            "COALESCE(target_table,'') LIKE ?",
            "COALESCE(target_id,'') LIKE ?",
            "COALESCE(message,'') LIKE ?",
            "COALESCE(detail,'') LIKE ?",
            "COALESCE(level,'') LIKE ?",
        ]) + ")")
        params.extend([kw] * 7)

    sql = "SELECT * FROM system_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit or 500))
    return query_df(sql, tuple(params))


def count_logs_by_date_range(start_date: Any, end_date: Any) -> int:
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    df = query_df(
        "SELECT COUNT(*) AS cnt FROM system_logs WHERE date(log_time) >= date(?) AND date(log_time) <= date(?)",
        (s, e),
    )
    if df.empty:
        return 0
    return int(df.iloc[0].get("cnt", 0) or 0)


def delete_logs_by_date_range(start_date: Any, end_date: Any, keep_delete_audit: bool = True, user_name: str | None = None) -> int:
    """Delete system_logs in a date range and keep one audit log after deletion.

    不使用文字輸入 DELETE；頁面會用 checkbox 確認。
    """
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    before = count_logs_by_date_range(s, e)
    execute(
        "DELETE FROM system_logs WHERE date(log_time) >= date(?) AND date(log_time) <= date(?)",
        (s, e),
    )
    clear_query_cache()
    if keep_delete_audit:
        write_log(
            "DELETE_LOG_RANGE",
            f"刪除 LOG 日期區間：{s} ~ {e}，刪除筆數：{before}",
            target_table="system_logs",
            target_id=f"{s}~{e}",
            detail=f"deleted_count={before}",
            level="WARN",
            user_name=user_name,
        )
    return before
