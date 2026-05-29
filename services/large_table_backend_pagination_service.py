# -*- coding: utf-8 -*-
"""V189 large table backend pagination helpers.

This module is intentionally read-only.  It provides SQL-first pagination and
health checks for large tables used by 02/06/08/14 without changing UI theme or
transaction flows.
"""
from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

try:
    from services.db_service import query_df, query_one, get_connection
except Exception:  # pragma: no cover
    query_df = None  # type: ignore
    query_one = None  # type: ignore
    get_connection = None  # type: ignore

try:
    from services.timezone_service import now_text, today_date
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def today_date() -> date:
        return date.today()

_TEXT_COLS_HISTORY = [
    "record_key", "status", "work_order", "part_no", "type_name", "process_name",
    "employee_id", "employee_name", "start_action", "end_action", "remark",
    "assembly_location", "source",
]
_TEXT_COLS_LOGS = [
    "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source",
]


def _blank(v: Any) -> bool:
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return v is None or str(v).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _date_text(v: Any) -> str:
    if _blank(v):
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    text = str(v).strip().replace("/", "-")
    return text[:10]


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _clamp_limit(limit: int | None, default: int = 500, max_limit: int = 5000) -> int:
    n = _int(limit, default)
    return max(1, min(n, max_limit))


def _offset(page: int | None, page_size: int | None) -> tuple[int, int]:
    size = _clamp_limit(page_size, 500, 5000)
    p = max(1, _int(page, 1))
    return p, (p - 1) * size


def _table_exists(table_name: str) -> bool:
    if query_one is None:
        return False
    try:
        row = query_one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return bool(row)
    except Exception:
        return False


def _table_columns(table_name: str) -> list[str]:
    if get_connection is None:
        return []
    try:
        with get_connection() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        out = []
        for r in rows:
            try:
                out.append(str(r[1]))
            except Exception:
                try:
                    out.append(str(r["name"]))
                except Exception:
                    pass
        return out
    except Exception:
        return []


def _where_like_any(cols: list[str], keyword: str, params: list[Any]) -> str:
    kw = str(keyword or "").strip()
    if not kw:
        return ""
    clauses = []
    for c in cols:
        clauses.append(f"COALESCE(CAST({c} AS TEXT),'') LIKE ?")
        params.append(f"%{kw}%")
    return "(" + " OR ".join(clauses) + ")" if clauses else ""


def _safe_query_df(sql: str, params: Iterable[Any] | None = None) -> pd.DataFrame:
    if query_df is None:
        return pd.DataFrame()
    try:
        return query_df(sql, tuple(params or ()))
    except Exception:
        return pd.DataFrame()


def _safe_scalar(sql: str, params: Iterable[Any] | None = None, default: int = 0) -> int:
    if query_one is None:
        return default
    try:
        row = query_one(sql, tuple(params or ()))
        if not row:
            return default
        return _int(next(iter(row.values())), default)
    except Exception:
        return default


def query_history_backend_page(
    *,
    start_date: Any | None = None,
    end_date: Any | None = None,
    employee_id: str | None = None,
    work_order: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 500,
    order_by: str = "id DESC",
) -> dict[str, Any]:
    """Return a backend-paginated time_records page.

    This is read-only and uses LIMIT/OFFSET so large table pages do not need to
    load the full history before displaying a single page.
    """
    t0 = time.perf_counter()
    if not _table_exists("time_records"):
        return {"ok": False, "rows": [], "df": pd.DataFrame(), "total_rows": 0, "reason": "time_records table not found"}
    cols = set(_table_columns("time_records"))
    where: list[str] = []
    params: list[Any] = []
    s, e = _date_text(start_date), _date_text(end_date)
    if s:
        if "start_date" in cols:
            where.append("date(start_date) >= date(?)")
            params.append(s)
        elif "start_timestamp" in cols:
            where.append("date(start_timestamp) >= date(?)")
            params.append(s)
    if e:
        if "start_date" in cols:
            where.append("date(start_date) <= date(?)")
            params.append(e)
        elif "start_timestamp" in cols:
            where.append("date(start_timestamp) <= date(?)")
            params.append(e)
    if employee_id and "employee_id" in cols:
        where.append("COALESCE(employee_id,'') = ?")
        params.append(str(employee_id).strip())
    if work_order and "work_order" in cols:
        where.append("COALESCE(work_order,'') = ?")
        params.append(str(work_order).strip())
    if status and str(status).strip().upper() not in {"ALL", "全部"} and "status" in cols:
        where.append("COALESCE(status,'') = ?")
        params.append(str(status).strip())
    like = _where_like_any([c for c in _TEXT_COLS_HISTORY if c in cols], str(keyword or ""), params)
    if like:
        where.append(like)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    safe_order = "id DESC"
    allowed_order = {
        "id DESC", "id ASC", "start_timestamp DESC", "start_timestamp ASC",
        "updated_at DESC", "updated_at ASC", "employee_id ASC", "work_order ASC",
    }
    if order_by in allowed_order:
        safe_order = order_by
    page, off = _offset(page, page_size)
    size = _clamp_limit(page_size, 500, 5000)
    total = _safe_scalar(f"SELECT COUNT(*) AS n FROM time_records{where_sql}", params)
    df = _safe_query_df(f"SELECT * FROM time_records{where_sql} ORDER BY {safe_order} LIMIT ? OFFSET ?", params + [size, off])
    return {
        "ok": True,
        "df": df,
        "rows": df.to_dict("records"),
        "total_rows": int(total),
        "page": page,
        "page_size": size,
        "total_pages": max(1, math.ceil(int(total) / size)) if size else 1,
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
        "where_pushed_to_sql": True,
    }


def query_logs_backend_page(
    *,
    start_date: Any | None = None,
    end_date: Any | None = None,
    action_type: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    if not _table_exists("system_logs"):
        return {"ok": False, "rows": [], "df": pd.DataFrame(), "total_rows": 0, "reason": "system_logs table not found"}
    cols = set(_table_columns("system_logs"))
    where: list[str] = []
    params: list[Any] = []
    s, e = _date_text(start_date), _date_text(end_date)
    if s and "log_time" in cols:
        where.append("date(log_time) >= date(?)")
        params.append(s)
    if e and "log_time" in cols:
        where.append("date(log_time) <= date(?)")
        params.append(e)
    if action_type and "action_type" in cols:
        where.append("COALESCE(action_type,'') = ?")
        params.append(str(action_type).strip())
    lvl = str(level or "").strip().upper()
    if lvl and lvl not in {"ALL", "全部"} and "level" in cols:
        where.append("UPPER(COALESCE(level,'')) = ?")
        params.append(lvl)
    like = _where_like_any([c for c in _TEXT_COLS_LOGS if c in cols], str(keyword or ""), params)
    if like:
        where.append(like)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    page, off = _offset(page, page_size)
    size = _clamp_limit(page_size, 500, 5000)
    total = _safe_scalar(f"SELECT COUNT(*) AS n FROM system_logs{where_sql}", params)
    df = _safe_query_df(f"SELECT * FROM system_logs{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", params + [size, off])
    return {
        "ok": True,
        "df": df,
        "rows": df.to_dict("records"),
        "total_rows": int(total),
        "page": page,
        "page_size": size,
        "total_pages": max(1, math.ceil(int(total) / size)) if size else 1,
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
        "where_pushed_to_sql": True,
    }


def query_daily_hours_backend(
    *,
    work_date: Any | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    d = _date_text(work_date) or _date_text(today_date())
    if not _table_exists("time_records"):
        return {"ok": False, "df": pd.DataFrame(), "rows": [], "total_rows": 0, "reason": "time_records table not found"}
    page, off = _offset(page, page_size)
    size = _clamp_limit(page_size, 500, 5000)
    # SQLite can sum numeric strings but not HH:MM:SS reliably.  We still fetch only grouped rows;
    # page 08 keeps its safe HH:MM:SS conversion if needed.
    sql = """
        SELECT
            COALESCE(employee_id,'') AS employee_id,
            COALESCE(employee_name,'') AS employee_name,
            COUNT(*) AS record_count,
            SUM(CASE WHEN COALESCE(end_timestamp,'')='' THEN 1 ELSE 0 END) AS active_count,
            SUM(CASE WHEN typeof(work_hours) IN ('integer','real') THEN work_hours ELSE 0 END) AS numeric_total_hours
        FROM time_records
        WHERE date(COALESCE(start_date, start_timestamp)) = date(?)
        GROUP BY COALESCE(employee_id,''), COALESCE(employee_name,'')
        ORDER BY employee_id ASC
        LIMIT ? OFFSET ?
    """
    count_sql = """
        SELECT COUNT(*) AS n FROM (
            SELECT COALESCE(employee_id,'') AS employee_id
            FROM time_records
            WHERE date(COALESCE(start_date, start_timestamp)) = date(?)
            GROUP BY COALESCE(employee_id,''), COALESCE(employee_name,'')
        ) x
    """
    total = _safe_scalar(count_sql, (d,))
    df = _safe_query_df(sql, (d, size, off))
    return {
        "ok": True,
        "df": df,
        "rows": df.to_dict("records"),
        "total_rows": int(total),
        "page": page,
        "page_size": size,
        "total_pages": max(1, math.ceil(int(total) / size)) if size else 1,
        "elapsed_seconds": round(time.perf_counter() - t0, 4),
        "where_pushed_to_sql": True,
    }


def collect_v189_large_table_report(page_size: int = 500) -> dict[str, Any]:
    """Collect read-only backend pagination readiness and smoke results."""
    started = time.perf_counter()
    today = today_date()
    checks: list[dict[str, Any]] = []
    for name, table in [("02_history/time_records", "time_records"), ("06_logs/system_logs", "system_logs"), ("08_daily/employees", "employees")]:
        exists = _table_exists(table)
        row_count = _safe_scalar(f"SELECT COUNT(*) AS n FROM {table}") if exists else 0
        checks.append({"area": name, "table": table, "exists": exists, "row_count": row_count})
    hist = query_history_backend_page(start_date=today, end_date=today, page=1, page_size=page_size)
    logs = query_logs_backend_page(start_date=today, end_date=today, page=1, page_size=page_size)
    daily = query_daily_hours_backend(work_date=today, page=1, page_size=page_size)
    return {
        "ok": True,
        "version": "V189",
        "generated_at": now_text(),
        "production_write_path_changed": False,
        "visual_changed": False,
        "page_size": _clamp_limit(page_size, 500, 5000),
        "table_checks": checks,
        "smoke_results": [
            {"query": "history_today_page", "ok": hist.get("ok"), "total_rows": hist.get("total_rows"), "page_rows": len(hist.get("rows", [])), "elapsed_seconds": hist.get("elapsed_seconds")},
            {"query": "logs_today_page", "ok": logs.get("ok"), "total_rows": logs.get("total_rows"), "page_rows": len(logs.get("rows", [])), "elapsed_seconds": logs.get("elapsed_seconds")},
            {"query": "daily_hours_today_page", "ok": daily.get("ok"), "total_rows": daily.get("total_rows"), "page_rows": len(daily.get("rows", [])), "elapsed_seconds": daily.get("elapsed_seconds")},
        ],
        "recommendations": [
            "02/06/08 大表應優先使用 LIMIT/OFFSET 與 SQL WHERE，避免畫面載入全量資料。",
            "Excel 匯出才允許查全量；一般畫面只查目前頁與目前篩選條件。",
            "若 02 編輯頁仍需全量載入，建議先做只讀查詢頁後端化，再分階段改 editable history。",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }


def export_v189_report_excel_bytes(report: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame([{
            "version": report.get("version"),
            "generated_at": report.get("generated_at"),
            "production_write_path_changed": report.get("production_write_path_changed"),
            "visual_changed": report.get("visual_changed"),
            "elapsed_seconds": report.get("elapsed_seconds"),
        }]).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(report.get("table_checks", [])).to_excel(writer, sheet_name="TableChecks", index=False)
        pd.DataFrame(report.get("smoke_results", [])).to_excel(writer, sheet_name="SmokeResults", index=False)
        pd.DataFrame({"recommendation": report.get("recommendations", [])}).to_excel(writer, sheet_name="Recommendations", index=False)
    output.seek(0)
    return output.getvalue()

# ===================== V200 LOG BACKEND PAGINATION USES COMPLETE LOG SOURCE =====================
# 06 LOG 查詢不可只查 SQLite system_logs，否則會漏掉 authority / JSONL shard 中的逐筆 LOG。
try:
    _v200_prev_query_logs_backend_page = query_logs_backend_page
except Exception:  # pragma: no cover
    _v200_prev_query_logs_backend_page = None


def query_logs_backend_page(
    *,
    start_date: Any | None = None,
    end_date: Any | None = None,
    action_type: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:  # type: ignore[override]
    try:
        from services import log_service as _v200_log_service
        if hasattr(_v200_log_service, "load_logs_page"):
            res = _v200_log_service.load_logs_page(
                start_date=start_date,
                end_date=end_date,
                action_type=action_type,
                level=level,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
            if isinstance(res, dict) and res.get("ok"):
                res["where_pushed_to_sql"] = False
                res["complete_log_source"] = True
                return res
    except Exception:
        pass
    if callable(_v200_prev_query_logs_backend_page):
        return _v200_prev_query_logs_backend_page(
            start_date=start_date,
            end_date=end_date,
            action_type=action_type,
            level=level,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    return {"ok": False, "df": pd.DataFrame(), "rows": [], "total_rows": 0, "reason": "query_logs_backend_page unavailable"}

# =================== END V200 LOG BACKEND PAGINATION USES COMPLETE LOG SOURCE ===================
