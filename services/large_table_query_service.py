# -*- coding: utf-8 -*-
"""V174 backend-only large table query helpers.

目的：針對 02 / 06 / 08 這類大表，提供 SQL 先篩選、必要欄位查詢與
分頁/上限查詢能力。這個 service 不產生任何 Streamlit 元件、不改 CSS、
不改表格渲染、不寫入資料。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from services.db_service import query_df


TIME_RECORD_COLS = [
    "id", "record_key", "status", "work_order", "part_no", "type_name", "process_name",
    "employee_id", "employee_name", "start_action", "start_timestamp", "end_action", "end_timestamp",
    "remark", "start_date", "start_time", "end_date", "end_time", "work_hours", "assembly_location",
    "group_key", "is_group_work", "source", "created_at", "updated_at",
]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _date_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip().replace("/", "-")
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return text[:10]


def _safe_int(value: Any, default: int, min_value: int = 1, max_value: int = 200000) -> int:
    try:
        n = int(float(str(value).strip()))
    except Exception:
        n = default
    return max(min_value, min(max_value, n))


def _list_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values.strip()] if values.strip() else []
    if isinstance(values, (list, tuple, set)):
        return [str(v).strip() for v in values if str(v).strip()]
    return []


def _add_in_filter(where: list[str], params: list[Any], column: str, values: Any) -> None:
    vals = _list_values(values)
    if not vals:
        return
    placeholders = ",".join(["?"] * len(vals))
    where.append(f"COALESCE({column},'') IN ({placeholders})")
    params.extend(vals)


def _time_record_date_where(start_date: Any, end_date: Any) -> tuple[str, list[Any]]:
    s = _date_text(start_date)
    e = _date_text(end_date)
    where: list[str] = []
    params: list[Any] = []
    # 盡量使用原欄位比較，避免 date(COALESCE(...)) 讓索引失效。
    if s:
        where.append("(COALESCE(start_date,'') >= ? OR substr(COALESCE(start_timestamp,''),1,10) >= ?)")
        params.extend([s, s])
    if e:
        where.append("(COALESCE(start_date,'') <= ? OR substr(COALESCE(start_timestamp,''),1,10) <= ?)")
        params.extend([e, e])
    if not where:
        return "", []
    return " AND ".join(where), params


def _history_order_sql(sort_by: Any) -> str:
    text = _clean_text(sort_by)
    if text == "ID由舊到新":
        return "CAST(id AS INTEGER) ASC"
    if text == "開始時間由舊到新":
        return "COALESCE(start_timestamp,start_date,'') ASC, CAST(id AS INTEGER) ASC"
    if text == "開始時間由新到舊":
        return "COALESCE(start_timestamp,start_date,'') DESC, CAST(id AS INTEGER) DESC"
    if text == "製令排序":
        return "COALESCE(work_order,'') ASC, COALESCE(process_name,'') ASC, COALESCE(employee_id,'') ASC, CAST(id AS INTEGER) DESC"
    if text == "人員排序":
        return "COALESCE(employee_id,'') ASC, COALESCE(start_timestamp,start_date,'') DESC, CAST(id AS INTEGER) DESC"
    # 工時排序牽涉 HH:MM:SS 與 decimal 混合，保留頁面既有 pandas 精準排序。
    return "CAST(id AS INTEGER) DESC"


def load_history_records_sql_filtered(filters: dict[str, Any] | None = None, *, start_date: Any = None, end_date: Any = None, limit: int | None = None, offset: int = 0) -> pd.DataFrame:
    """Return candidate history rows using SQL-side filters first.

    頁面仍可保留原本 pandas 的異常篩選/跨日判斷/工時混合格式處理；
    這裡只把可安全下推到 SQL 的條件先處理，減少進入 pandas 的資料量。
    """
    f = dict(filters or {})
    s = start_date if start_date is not None else f.get("start_date")
    e = end_date if end_date is not None else f.get("end_date")
    where: list[str] = []
    params: list[Any] = []

    date_clause, date_params = _time_record_date_where(s, e)
    if date_clause:
        where.append(date_clause)
        params.extend(date_params)

    _add_in_filter(where, params, "work_order", f.get("work_orders"))
    _add_in_filter(where, params, "part_no", f.get("part_nos"))
    _add_in_filter(where, params, "type_name", f.get("type_names"))
    _add_in_filter(where, params, "assembly_location", f.get("assembly_locations"))
    _add_in_filter(where, params, "process_name", f.get("process_names"))
    _add_in_filter(where, params, "employee_id", f.get("employee_ids"))
    _add_in_filter(where, params, "employee_name", f.get("employee_names"))
    _add_in_filter(where, params, "status", f.get("statuses"))

    # 02 的單位/職稱來自員工主檔，仍保留頁面 merge/filter；這裡不直接 join，避免改變資料語意。
    keyword = _clean_text(f.get("keyword"))
    if keyword:
        kw = f"%{keyword}%"
        where.append("(" + " OR ".join([
            "COALESCE(work_order,'') LIKE ?",
            "COALESCE(part_no,'') LIKE ?",
            "COALESCE(type_name,'') LIKE ?",
            "COALESCE(process_name,'') LIKE ?",
            "COALESCE(employee_id,'') LIKE ?",
            "COALESCE(employee_name,'') LIKE ?",
            "COALESCE(remark,'') LIKE ?",
            "COALESCE(assembly_location,'') LIKE ?",
        ]) + ")")
        params.extend([kw] * 8)

    end_state = _clean_text(f.get("end_state"))
    if end_state == "未結束":
        where.append("COALESCE(end_timestamp,'') IN ('','None','none','nan','NaT','nat','null')")
    elif end_state == "已結束":
        where.append("COALESCE(end_timestamp,'') NOT IN ('','None','none','nan','NaT','nat','null')")

    sql = "SELECT " + ", ".join(TIME_RECORD_COLS) + " FROM time_records"
    if where:
        sql += " WHERE " + " AND ".join(f"({w})" for w in where)
    sql += " ORDER BY " + _history_order_sql(f.get("sort_by"))

    effective_limit = limit
    if effective_limit is None:
        try:
            effective_limit = int(f.get("detail_limit") or 1000)
        except Exception:
            effective_limit = 1000
    effective_limit = _safe_int(effective_limit, 1000, 1, 200000)
    effective_offset = max(0, _safe_int(offset, 0, 0, 999999999))
    sql += " LIMIT ? OFFSET ?"
    params.extend([effective_limit, effective_offset])

    df = query_df(sql, tuple(params))
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def count_history_records_sql_filtered(filters: dict[str, Any] | None = None, *, start_date: Any = None, end_date: Any = None) -> int:
    f = dict(filters or {})
    s = start_date if start_date is not None else f.get("start_date")
    e = end_date if end_date is not None else f.get("end_date")
    where: list[str] = []
    params: list[Any] = []
    date_clause, date_params = _time_record_date_where(s, e)
    if date_clause:
        where.append(date_clause)
        params.extend(date_params)
    _add_in_filter(where, params, "work_order", f.get("work_orders"))
    _add_in_filter(where, params, "part_no", f.get("part_nos"))
    _add_in_filter(where, params, "type_name", f.get("type_names"))
    _add_in_filter(where, params, "assembly_location", f.get("assembly_locations"))
    _add_in_filter(where, params, "process_name", f.get("process_names"))
    _add_in_filter(where, params, "employee_id", f.get("employee_ids"))
    _add_in_filter(where, params, "employee_name", f.get("employee_names"))
    _add_in_filter(where, params, "status", f.get("statuses"))
    sql = "SELECT COUNT(*) AS cnt FROM time_records"
    if where:
        sql += " WHERE " + " AND ".join(f"({w})" for w in where)
    df = query_df(sql, tuple(params))
    if df is None or df.empty:
        return 0
    try:
        return int(df.iloc[0].get("cnt", 0) or 0)
    except Exception:
        return 0


def load_daily_record_summary_sql(work_date: Any) -> pd.DataFrame:
    """Return minimal columns needed by 08 daily hours.

    08 以前會透過 load_records(date,date) 拿整張 time_records 全欄位；本函式只取
    employee_id/work_hours/end_timestamp/status，降低資料傳輸與 pandas 記憶體。
    """
    d = _date_text(work_date)
    if not d:
        return pd.DataFrame(columns=["employee_id", "work_hours", "end_timestamp", "status"])
    sql = """
        SELECT employee_id, work_hours, end_timestamp, status
        FROM time_records
        WHERE COALESCE(start_date,'') = ? OR substr(COALESCE(start_timestamp,''),1,10) = ?
    """
    df = query_df(sql, (d, d))
    if df is None or df.empty:
        return pd.DataFrame(columns=["employee_id", "work_hours", "end_timestamp", "status"])
    return df


def load_logs_sql_page(*, limit: int = 1000, offset: int = 0, start_date: Any = None, end_date: Any = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None) -> pd.DataFrame:
    where: list[str] = []
    params: list[Any] = []
    s = _date_text(start_date)
    e = _date_text(end_date)
    if s:
        where.append("substr(COALESCE(log_time,''),1,10) >= ?")
        params.append(s)
    if e:
        where.append("substr(COALESCE(log_time,''),1,10) <= ?")
        params.append(e)
    if action_type:
        where.append("COALESCE(action_type,'') = ?")
        params.append(str(action_type).strip())
    if level and str(level).upper() != "ALL":
        where.append("COALESCE(level,'') = ?")
        params.append(str(level).strip())
    if keyword:
        kw = f"%{str(keyword).strip()}%"
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
        sql += " WHERE " + " AND ".join(f"({w})" for w in where)
    sql += " ORDER BY CAST(id AS INTEGER) DESC LIMIT ? OFFSET ?"
    params.extend([_safe_int(limit, 1000, 1, 200000), max(0, _safe_int(offset, 0, 0, 999999999))])
    df = query_df(sql, tuple(params))
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def count_logs_sql_filtered(*, start_date: Any = None, end_date: Any = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None) -> int:
    where: list[str] = []
    params: list[Any] = []
    s = _date_text(start_date)
    e = _date_text(end_date)
    if s:
        where.append("substr(COALESCE(log_time,''),1,10) >= ?")
        params.append(s)
    if e:
        where.append("substr(COALESCE(log_time,''),1,10) <= ?")
        params.append(e)
    if action_type:
        where.append("COALESCE(action_type,'') = ?")
        params.append(str(action_type).strip())
    if level and str(level).upper() != "ALL":
        where.append("COALESCE(level,'') = ?")
        params.append(str(level).strip())
    if keyword:
        kw = f"%{str(keyword).strip()}%"
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
    sql = "SELECT COUNT(*) AS cnt FROM system_logs"
    if where:
        sql += " WHERE " + " AND ".join(f"({w})" for w in where)
    df = query_df(sql, tuple(params))
    if df is None or df.empty:
        return 0
    try:
        return int(df.iloc[0].get("cnt", 0) or 0)
    except Exception:
        return 0


def get_v174_large_table_query_status() -> dict[str, Any]:
    return {
        "version": "V174",
        "enabled": True,
        "visual_changed": False,
        "css_changed": False,
        "theme_changed": False,
        "write_path_changed": False,
        "features": ["02_history_sql_filter", "06_log_sql_page", "08_daily_hours_minimal_record_query"],
    }
