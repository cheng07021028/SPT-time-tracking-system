# -*- coding: utf-8 -*-
"""V174 backend-only large table query helpers.

目的：針對 02 / 06 / 08 這類大表，提供 SQL 先篩選、必要欄位查詢與
分頁/上限查詢能力。這個 service 不產生任何 Streamlit 元件、不改 CSS、
不改表格渲染、不寫入資料。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable
import os

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
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
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
        raw_values = [values]
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = [values]

    out: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = _clean_text(value)
        # Excel / web paste can carry BOM, zero-width chars, NBSP or full-width spaces.
        # Normalize here as the final SQL boundary so pasted Work Order filters match
        # the same values that were parsed in the Streamlit page.
        text = (
            text.replace("\ufeff", "")
            .replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\xa0", " ")
            .replace("　", " ")
            .strip()
            .strip("'\"")
        )
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _effective_work_order_values(filters: dict[str, Any]) -> list[str]:
    """Return the Work Order filter used by SQL-first 02 history queries.

    V301.10: 02 added an independent 「批量貼上製令 / Paste Work Orders」
    field to avoid rendering hundreds of selected values as multiselect chips.
    The page stores those values in `work_orders_pasted` and the combined list
    in `work_orders_effective`, but the SQL-first count/page loaders previously
    still read only `work_orders`.  As a result the screen could show that three
    pasted work orders were parsed while the query still returned all work orders
    in the date range.  Keep the UI independent, but make the SQL predicate use
    the effective list.
    """
    if not isinstance(filters, dict):
        return []
    effective = _list_values(filters.get("work_orders_effective"))
    if effective:
        return effective
    return _list_values(filters.get("work_orders")) + [
        x for x in _list_values(filters.get("work_orders_pasted"))
        if x not in set(_list_values(filters.get("work_orders")))
    ]


def _add_in_filter(where: list[str], params: list[Any], column: str, values: Any) -> None:
    vals = _list_values(values)
    if not vals:
        return
    placeholders = ",".join(["?"] * len(vals))
    # V89: keep 02 history predicates index-friendly. COALESCE(column,'') IN (...)
    # forces PostgreSQL to evaluate an expression and can prevent normal indexes
    # on work_order/employee_id/process_name/status from being used.  Empty-string
    # rows are irrelevant when the UI supplies concrete values, so use column IN.
    where.append(f"{column} IN ({placeholders})")
    params.extend(vals)


def _time_record_date_where(start_date: Any, end_date: Any) -> tuple[str, list[Any]]:
    s = _date_text(start_date)
    e = _date_text(end_date)
    where: list[str] = []
    params: list[Any] = []
    # V58: 02 history must not use OR/substr(COALESCE(...)) in the hot query path.
    # Those expressions defeat normal indexes on start_date and caused Neon statement
    # timeout on real data.  start_date is the authoritative filter column generated by
    # 01/02, so use it directly and keep the query index-friendly.
    if s:
        where.append("start_date >= ?")
        params.append(s)
    if e:
        where.append("start_date <= ?")
        params.append(e)
    if not where:
        return "", []
    return " AND ".join(where), params






def _v79_default_history_range_if_blank(start_date: Any, end_date: Any) -> tuple[Any, Any]:
    """Protect interactive 02 queries from accidentally scanning all history rows.

    The page always presents a quick date preset.  If an older saved filter lacks
    explicit start/end values, use the same default as the UI (last 30 days).
    """
    s = _date_text(start_date)
    e = _date_text(end_date)
    if s or e:
        return start_date, end_date
    today = datetime.now().date()
    return (today - pd.Timedelta(days=30)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def _time_records_not_deleted_where() -> str:
    """SQL predicate for rows that are visible in 01/02/05/08 runtime views.

    02 history delete is implemented as a DB soft delete.  Any SQL-first read
    path must apply the same predicate as services.time_record_service.load_records;
    otherwise deleted rows can reappear after a Reboot when the page reloads from
    Neon instead of the current session cache.
    """
    return "(deleted_at IS NULL OR deleted_at='')"

def _history_order_sql(sort_by: Any) -> str:
    text = _clean_text(sort_by)
    if text == "ID由舊到新":
        return "id ASC"
    # V71: avoid ORDER BY COALESCE(start_timestamp,start_date).  That expression
    # prevents PostgreSQL/Neon from using the start_date indexes and made 02 refresh
    # take minutes on larger tables.  start_date/start_time are maintained by 01/02
    # and are the index-friendly history ordering columns.
    if text == "開始時間由舊到新":
        return "start_date ASC, start_time ASC, id ASC"
    if text == "開始時間由新到舊":
        return "start_date DESC, start_time DESC, id DESC"
    if text == "製令排序":
        return "work_order ASC, process_name ASC, employee_id ASC, id DESC"
    if text == "人員排序":
        return "employee_id ASC, start_date DESC, start_time DESC, id DESC"
    # 工時排序牽涉 HH:MM:SS 與 decimal 混合，保留頁面既有 pandas 精準排序。
    return "id DESC"


def load_history_records_sql_filtered(filters: dict[str, Any] | None = None, *, start_date: Any = None, end_date: Any = None, limit: int | None = None, offset: int = 0) -> pd.DataFrame:
    """Return candidate history rows using SQL-side filters first.

    頁面仍可保留原本 pandas 的異常篩選/跨日判斷/工時混合格式處理；
    這裡只把可安全下推到 SQL 的條件先處理，減少進入 pandas 的資料量。
    """
    f = dict(filters or {})
    s = start_date if start_date is not None else f.get("start_date")
    e = end_date if end_date is not None else f.get("end_date")
    s, e = _v79_default_history_range_if_blank(s, e)
    where: list[str] = [_time_records_not_deleted_where()]
    params: list[Any] = []

    date_clause, date_params = _time_record_date_where(s, e)
    if date_clause:
        where.append(date_clause)
        params.extend(date_params)

    _add_in_filter(where, params, "work_order", _effective_work_order_values(f))
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
    # V58: interactive history queries must remain short.  Exports/background jobs
    # should use a dedicated batch/export path rather than loading huge history data
    # through the Streamlit page.
    try:
        max_interactive = int(float(str(os.environ.get("SPT_HISTORY_INTERACTIVE_MAX_ROWS", "1000")).strip()))
    except Exception:
        max_interactive = 1000
    max_interactive = max(100, min(5000, max_interactive))
    effective_limit = _safe_int(effective_limit, 1000, 1, max_interactive)
    effective_offset = max(0, _safe_int(offset, 0, 0, 999999999))
    sql += " LIMIT ? OFFSET ?"
    params.extend([effective_limit, effective_offset])

    try:
        df = query_df(sql, tuple(params))
    except Exception:
        # Do not crash 02 if Neon cancels a query.  Return an empty frame; the page
        # remains usable and the user can narrow filters or export via a background path.
        return pd.DataFrame(columns=TIME_RECORD_COLS)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=TIME_RECORD_COLS)


def count_history_records_sql_filtered(filters: dict[str, Any] | None = None, *, start_date: Any = None, end_date: Any = None) -> int:
    f = dict(filters or {})
    s = start_date if start_date is not None else f.get("start_date")
    e = end_date if end_date is not None else f.get("end_date")
    s, e = _v79_default_history_range_if_blank(s, e)
    where: list[str] = [_time_records_not_deleted_where()]
    params: list[Any] = []
    date_clause, date_params = _time_record_date_where(s, e)
    if date_clause:
        where.append(date_clause)
        params.extend(date_params)
    _add_in_filter(where, params, "work_order", _effective_work_order_values(f))
    _add_in_filter(where, params, "part_no", f.get("part_nos"))
    _add_in_filter(where, params, "type_name", f.get("type_names"))
    _add_in_filter(where, params, "assembly_location", f.get("assembly_locations"))
    _add_in_filter(where, params, "process_name", f.get("process_names"))
    _add_in_filter(where, params, "employee_id", f.get("employee_ids"))
    _add_in_filter(where, params, "employee_name", f.get("employee_names"))
    _add_in_filter(where, params, "status", f.get("statuses"))

    # V300.86: count must match the SQL-first page query.  Earlier count logic
    # ignored keyword and end-state filters, so the page total could be much
    # larger than the actual rows available to browse.
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

    sql = "SELECT COUNT(*) AS cnt FROM time_records"
    if where:
        sql += " WHERE " + " AND ".join(f"({w})" for w in where)
    try:
        df = query_df(sql, tuple(params))
    except Exception:
        return 0
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
        WHERE (_time_records_not_deleted_where_PLACEHOLDER_)
          AND (COALESCE(start_date,'') = ? OR substr(COALESCE(start_timestamp,''),1,10) = ?)
    """
    sql = sql.replace("_time_records_not_deleted_where_PLACEHOLDER_", _time_records_not_deleted_where())
    df = query_df(sql, (d, d))
    if df is None or df.empty:
        return pd.DataFrame(columns=["employee_id", "work_hours", "end_timestamp", "status"])
    return df



# ===== V253 HISTORY FILTER OPTION SQL PREFETCH =====
def load_history_filter_options_sql(start_date: Any = None, end_date: Any = None, *, limit_per_column: int = 5000) -> dict[str, list[str]]:
    """Load distinct option values for 02 filters without loading full history rows.

    Backend-only speed helper.  It keeps the existing UI exactly the same, but
    avoids using load_records(start,end) only to build selectbox/multiselect
    options.  This is safe for Neon/PostgreSQL and SQLite fallback because it
    uses the existing query_df abstraction.
    """
    start_date, end_date = _v79_default_history_range_if_blank(start_date, end_date)
    cols = [
        "work_order", "part_no", "type_name", "assembly_location", "process_name",
        "employee_id", "employee_name", "status",
    ]
    out: dict[str, list[str]] = {c: [] for c in cols}
    date_clause, date_params = _time_record_date_where(start_date, end_date)
    base_where = [_time_records_not_deleted_where()]
    if date_clause:
        base_where.append(f"({date_clause})")
    where_sql = " WHERE " + " AND ".join(base_where)
    lim = _safe_int(limit_per_column, 5000, 50, 50000)
    for col in cols:
        try:
            sql = (
                f"SELECT DISTINCT COALESCE({col}, '') AS v FROM time_records"
                f"{where_sql} AND COALESCE({col}, '') <> ''"
            )
            sql += " ORDER BY v LIMIT ?"
            params = list(date_params) + [lim]
            df = query_df(sql, tuple(params))
            if isinstance(df, pd.DataFrame) and not df.empty and "v" in df.columns:
                vals = []
                for v in df["v"].tolist():
                    t = _clean_text(v)
                    if t and t not in vals:
                        vals.append(t)
                out[col] = vals
        except Exception:
            out[col] = []
    return out


def audit_v253_history_sql_first_options() -> dict[str, Any]:
    return {
        "version": "V253_HISTORY_SQL_FIRST_OPTIONS_20260531",
        "ui_changed": False,
        "loads_full_history_for_filter_options": False,
        "uses_query_df_backend": True,
        "postgres_and_sqlite_fallback": True,
    }
# ===== END V253 HISTORY FILTER OPTION SQL PREFETCH =====

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
    try:
        df = query_df(sql, tuple(params))
    except Exception:
        return 0
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
