# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime
import getpass
from typing import Any

from .db_service import execute, query_df

try:
    from .db_service import clear_query_cache
except Exception:  # 舊版相容
    def clear_query_cache() -> None:  # type: ignore
        return None


def _date_text(value: Any) -> str | None:
    """Convert date/datetime/string to YYYY-MM-DD text for SQLite date() filtering."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _safe_int(value: Any, default: int = 500) -> int:
    try:
        return int(value)
    except Exception:
        return default


def write_log(
    action_type: str,
    message: str,
    target_table: str = "",
    target_id: str = "",
    detail: str = "",
    level: str = "INFO",
    user_name: str | None = None,
) -> None:
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

    V2.01：保留舊版 load_logs(limit) 相容，並支援 06｜LOG查詢 日期、類型、等級、關鍵字篩選。
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
        where.append("COALESCE(action_type,'') = ?")
        params.append(str(action_type))
    if level and str(level).upper() != "ALL":
        where.append("COALESCE(level,'') = ?")
        params.append(str(level))
    if keyword:
        kw = f"%{keyword}%"
        where.append(
            "(" + " OR ".join([
                "COALESCE(user_name,'') LIKE ?",
                "COALESCE(action_type,'') LIKE ?",
                "COALESCE(target_table,'') LIKE ?",
                "COALESCE(target_id,'') LIKE ?",
                "COALESCE(message,'') LIKE ?",
                "COALESCE(detail,'') LIKE ?",
                "COALESCE(level,'') LIKE ?",
            ]) + ")"
        )
        params.extend([kw] * 7)

    sql = "SELECT * FROM system_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, _safe_int(limit, 500)))
    return query_df(sql, tuple(params))


def count_logs_by_date_range(start_date: Any, end_date: Any) -> int:
    """Count logs in date range. Kept as top-level function to avoid ImportError in page 06."""
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    df = query_df(
        """
        SELECT COUNT(*) AS cnt
        FROM system_logs
        WHERE date(log_time) >= date(?) AND date(log_time) <= date(?)
        """,
        (s, e),
    )
    if df is None or df.empty:
        return 0
    return int(df.iloc[0].get("cnt", 0) or 0)


def delete_logs_by_date_range(
    start_date: Any,
    end_date: Any,
    keep_delete_audit: bool = True,
    user_name: str | None = None,
) -> int:
    """Delete system_logs in a date range and keep one audit log after deletion.

    V2.01：此函式必須存在，避免 06｜LOG查詢 import error。
    刪除確認由頁面用 checkbox 控制，不再要求輸入 DELETE。
    """
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    before = count_logs_by_date_range(s, e)
    if before <= 0:
        return 0
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
