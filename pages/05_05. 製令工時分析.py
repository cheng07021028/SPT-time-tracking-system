# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
import hashlib

import pandas as pd
import plotly.express as px
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.time_record_service import load_records, save_time_records
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms
from services.timezone_service import today_date
from services.analysis_filter_service import load_analysis_filters, save_analysis_filters
from services.master_data_service import load_work_orders, load_employees
try:
    from services.large_table_query_service import load_history_filter_options_sql
except Exception:
    load_history_filter_options_sql = None

st.set_page_config(page_title="05. 製令工時分析", page_icon="📊", layout="wide")
apply_theme()
require_module_access("05_analysis")
render_header("05｜製令工時分析", "製令、工段、人員累積工時分析與明細編輯")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("05", "製令工時分析")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


FILTER_KEY = "_spt_05_analysis_filters"
V69_QUERY_KEY = "_spt_v69_05_query_applied"
V69_DF_KEY = "_spt_v69_05_base_df"
V69_FILTER_SIG_KEY = "_spt_v69_05_filter_signature"
V30030_SUMMARY_CACHE_KEY = "_spt_v30030_05_summary_bundle"
V30030_EXCEL_CACHE_PREFIX = "_spt_v30030_05_excel_"
V30071_FILTER_OPTIONS_CACHE_KEY = "_spt_v30071_05_filter_options_cache"
V30091_ANALYSIS_DEFAULT_PRESET = "今日"

if FILTER_KEY not in st.session_state:
    st.session_state[FILTER_KEY] = _v30091_today_default_analysis_filters(load_analysis_filters())
filters = _v30091_today_default_analysis_filters(st.session_state[FILTER_KEY])
st.session_state[FILTER_KEY] = dict(filters)

DATE_PRESETS = ["今日", "近7天", "近30天", "本月", "上月", "自訂區間"]
STATUS_OPTIONS = ["全部", "作業中", "暫停", "完工", "下班", "未結束", "已結束"]
ANOMALY_OPTIONS = ["全部", "工時 = 0", "工時小於5分鐘", "工時大於8小時", "工時大於12小時", "未按結束", "跨日紀錄", "有開始無結束", "有結束無開始"]
TOP_OPTIONS = ["Top 10", "Top 20", "Top 50", "全部"]
SORT_OPTIONS = ["累積工時由大到小", "製令由新到舊", "工段數量", "人數", "紀錄筆數", "平均工時"]



def _excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, data in sheets.items():
            (data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)).to_excel(writer, index=False, sheet_name=str(name)[:31] or "Sheet1")
    return bio.getvalue()


def _v30030_clear_analysis_output_cache() -> None:
    """Clear derived 05 outputs without touching Neon authority data.

    05 can render several heavy groupby/pivot tables and Excel files after one
    query.  These are derived UI artifacts, so they should be reused while the
    filter signature is unchanged and cleared after a new query or save.
    """
    try:
        for key in list(st.session_state.keys()):
            if str(key).startswith(V30030_EXCEL_CACHE_PREFIX) or key == V30030_SUMMARY_CACHE_KEY:
                st.session_state.pop(key, None)
    except Exception:
        pass


def _v30030_cache_token(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _v30030_excel_bytes_cached(name: str, signature: str, sheets: dict[str, pd.DataFrame]) -> bytes:
    """Cache Excel bytes per applied filter to avoid rebuilding workbooks on every rerun."""
    key = f"{V30030_EXCEL_CACHE_PREFIX}{name}_{_v30030_cache_token(signature)}"
    cached = st.session_state.get(key)
    if isinstance(cached, (bytes, bytearray)):
        return bytes(cached)
    data = _excel_bytes(sheets)
    st.session_state[key] = data
    return data

def _parse_date(value, fallback: date) -> date:
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return fallback


def _v30091_today_default_analysis_filters(filters: dict | None) -> dict:
    """Return UI default filters with Quick Date defaulting to 今日.

    This does not write to Neon on render.  Existing custom saved filters remain
    unchanged; blank filters or the previous exact 近30天 default are shown as
    今日.
    """
    f = dict(filters or {})
    today = today_date()
    old_start = str(today - timedelta(days=30))
    old_end = str(today)
    preset = str(f.get("date_preset") or "").strip()
    start_raw = str(f.get("start_date") or "").strip()
    end_raw = str(f.get("end_date") or "").strip()
    should_use_today = (
        not preset
        or preset == "近30天" and (not start_raw or start_raw == old_start) and (not end_raw or end_raw == old_end)
    )
    if should_use_today:
        f["date_preset"] = V30091_ANALYSIS_DEFAULT_PRESET
        f["start_date"] = str(today)
        f["end_date"] = str(today)
    return f


def _date_range_from_preset(preset: str, start_value: date, end_value: date) -> tuple[date, date]:
    today = today_date()
    if preset == "今日":
        return today, today
    if preset == "近7天":
        return today - timedelta(days=7), today
    if preset == "近30天":
        return today - timedelta(days=30), today
    if preset == "本月":
        return today.replace(day=1), today
    if preset == "上月":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    return start_value, end_value


def _safe_unique(df: pd.DataFrame, col: str, selected: list[str] | None = None) -> list[str]:
    selected = selected or []
    vals: list[str] = []
    if df is not None and not df.empty and col in df.columns:
        vals = sorted({str(x).strip() for x in df[col].dropna().tolist() if str(x).strip() and str(x).strip().lower() != "none"})
    for x in selected:
        if x and x not in vals:
            vals.append(x)
    return vals


def _v30071_clean_option(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "nan", "nat", "null"} else text


def _v30071_merge_options(*sources) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for src in sources:
        if src is None:
            continue
        if isinstance(src, pd.Series):
            values = src.dropna().tolist()
        elif isinstance(src, (list, tuple, set)):
            values = list(src)
        else:
            values = [src]
        for value in values:
            text = _v30071_clean_option(value)
            if text and text not in seen:
                out.append(text)
                seen.add(text)
    return sorted(out)


def _v30071_filter_selected(filters_map: dict, key: str) -> list[str]:
    value = (filters_map or {}).get(key, [])
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _v30071_df_options(df: pd.DataFrame, col: str) -> list[str]:
    if isinstance(df, pd.DataFrame) and not df.empty and col in df.columns:
        return _v30071_merge_options(df[col])
    return []


def _v30071_load_analysis_filter_options_cached(start_value, end_value, filters_map: dict, last_df: pd.DataFrame | None = None) -> dict[str, list[str]]:
    """Load 05 filter options without scanning full 02 history records.

    V69 stopped loading time_records on page open for speed, but the filter
    option widgets still depended on base_df.  The result was many empty
    multiselects.  This helper keeps the fast page-open behavior: small master
    tables provide master options, and a date-bounded DISTINCT query supplies
    time-record-only fields such as process/status.
    """
    key = (str(start_value or ""), str(end_value or ""))
    cache = st.session_state.get(V30071_FILTER_OPTIONS_CACHE_KEY)
    if isinstance(cache, dict) and cache.get("key") == key and isinstance(cache.get("options"), dict):
        base_options = {str(k): list(v or []) for k, v in cache.get("options", {}).items()}
    else:
        base_options: dict[str, list[str]] = {
            "work_order": [], "part_no": [], "type_name": [], "customer": [], "assembly_location": [],
            "process_name": [], "employee_id": [], "employee_name": [], "department": [], "title": [], "status": [],
        }
        try:
            wo = load_work_orders(active_only=False)
            if isinstance(wo, pd.DataFrame) and not wo.empty:
                base_options["work_order"] = _v30071_merge_options(base_options["work_order"], _v30071_df_options(wo, "work_order"))
                base_options["part_no"] = _v30071_merge_options(base_options["part_no"], _v30071_df_options(wo, "part_no"))
                base_options["type_name"] = _v30071_merge_options(base_options["type_name"], _v30071_df_options(wo, "type_name"))
                base_options["customer"] = _v30071_merge_options(base_options["customer"], _v30071_df_options(wo, "customer"))
                base_options["assembly_location"] = _v30071_merge_options(base_options["assembly_location"], _v30071_df_options(wo, "assembly_location"))
        except Exception:
            pass
        try:
            emp = load_employees(active_only=False)
            if isinstance(emp, pd.DataFrame) and not emp.empty:
                base_options["employee_id"] = _v30071_merge_options(base_options["employee_id"], _v30071_df_options(emp, "employee_id"))
                base_options["employee_name"] = _v30071_merge_options(base_options["employee_name"], _v30071_df_options(emp, "employee_name"))
                base_options["department"] = _v30071_merge_options(base_options["department"], _v30071_df_options(emp, "department"))
                base_options["title"] = _v30071_merge_options(base_options["title"], _v30071_df_options(emp, "title"))
        except Exception:
            pass
        if callable(load_history_filter_options_sql):
            try:
                time_opts = load_history_filter_options_sql(start_value, end_value, limit_per_column=5000)
                if isinstance(time_opts, dict):
                    for col in ["work_order", "part_no", "type_name", "assembly_location", "process_name", "employee_id", "employee_name", "status"]:
                        base_options[col] = _v30071_merge_options(base_options.get(col, []), time_opts.get(col, []))
            except Exception:
                pass
        base_options["status"] = _v30071_merge_options(base_options.get("status", []), [x for x in STATUS_OPTIONS if x != "全部"])
        st.session_state[V30071_FILTER_OPTIONS_CACHE_KEY] = {"key": key, "options": dict(base_options)}

    # Always merge current saved selections and the last queried df so defaults
    # remain selectable even if the date range changed or master data is partial.
    option_map = dict(base_options)
    selected_key_map = {
        "work_order": "work_orders", "part_no": "part_nos", "type_name": "type_names", "customer": "customers",
        "assembly_location": "assembly_locations", "process_name": "process_names", "employee_id": "employee_ids",
        "employee_name": "employee_names", "department": "departments", "title": "titles",
    }
    for col, filter_key in selected_key_map.items():
        option_map[col] = _v30071_merge_options(option_map.get(col, []), _v30071_df_options(last_df, col), _v30071_filter_selected(filters_map, filter_key))
    option_map["status"] = _v30071_merge_options(option_map.get("status", []), _v30071_df_options(last_df, "status"), [str((filters_map or {}).get("status_filter") or "")])
    return option_map


def _v30071_options(options_map: dict[str, list[str]], col: str, selected: list[str] | None = None) -> list[str]:
    return _v30071_merge_options(options_map.get(col, []), selected or [])


def _clean_filter_list(values) -> list[str]:
    if values is None:
        return []
    return [str(x).strip() for x in list(values) if str(x).strip()]


def _enrich_records(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    # 補入製令主檔欄位：客戶、組立地點、P/N、機型。
    try:
        wo = load_work_orders(active_only=False)
        if wo is not None and not wo.empty and "work_order" in wo.columns and "work_order" in out.columns:
            keep = [c for c in ["work_order", "customer", "assembly_location", "part_no", "type_name"] if c in wo.columns]
            wo2 = wo[keep].drop_duplicates("work_order").copy()
            rename = {c: f"wo_{c}" for c in keep if c != "work_order"}
            wo2 = wo2.rename(columns=rename)
            out = out.merge(wo2, on="work_order", how="left")
            for c in ["customer", "assembly_location", "part_no", "type_name"]:
                wc = f"wo_{c}"
                if wc in out.columns:
                    if c not in out.columns:
                        out[c] = out[wc]
                    else:
                        out[c] = out[c].fillna("")
                        out[c] = out[c].astype(str)
                        mask = out[c].str.strip().isin(["", "None", "nan"])
                        out.loc[mask, c] = out.loc[mask, wc]
                    out = out.drop(columns=[wc])
    except Exception:
        pass

    # 補入人員主檔欄位：單位、職稱。
    try:
        emp = load_employees(active_only=False)
        if emp is not None and not emp.empty and "employee_id" in emp.columns and "employee_id" in out.columns:
            keep = [c for c in ["employee_id", "department", "title"] if c in emp.columns]
            emp2 = emp[keep].drop_duplicates("employee_id").copy()
            out = out.merge(emp2, on="employee_id", how="left")
    except Exception:
        pass

    for col in ["customer", "assembly_location", "department", "title"]:
        if col not in out.columns:
            out[col] = ""
    return out


def _apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df.copy()
    exact_map = {
        "work_orders": "work_order",
        "part_nos": "part_no",
        "type_names": "type_name",
        "customers": "customer",
        "assembly_locations": "assembly_location",
        "process_names": "process_name",
        "employee_ids": "employee_id",
        "employee_names": "employee_name",
        "departments": "department",
        "titles": "title",
    }
    for key, col in exact_map.items():
        vals = _clean_filter_list(f.get(key, []))
        if vals and col in out.columns:
            out = out[out[col].fillna("").astype(str).isin(vals)]

    status = str(f.get("status_filter") or "全部")
    if "status" in out.columns:
        st_series = out["status"].fillna("").astype(str)
        end_ts = out.get("end_timestamp", pd.Series([""] * len(out))).fillna("").astype(str).str.strip()
        if status in {"作業中", "暫停", "完工", "下班"}:
            out = out[st_series == status]
        elif status == "未結束":
            out = out[(st_series == "作業中") & (end_ts.isin(["", "None", "none", "nan"]))]
        elif status == "已結束":
            out = out[~((st_series == "作業中") & (end_ts.isin(["", "None", "none", "nan"])))]

    if "work_hours" in out.columns:
        out["work_hours"] = _coerce_work_hours(out["work_hours"])
    else:
        out["work_hours"] = 0.0

    anomaly = str(f.get("anomaly_filter") or "全部")
    end_ts = out.get("end_timestamp", pd.Series([""] * len(out))).fillna("").astype(str).str.strip()
    start_ts = out.get("start_timestamp", pd.Series([""] * len(out))).fillna("").astype(str).str.strip()
    start_date = out.get("start_date", pd.Series([""] * len(out))).fillna("").astype(str)
    end_date = out.get("end_date", pd.Series([""] * len(out))).fillna("").astype(str)
    if anomaly == "工時 = 0":
        out = out[out["work_hours"] == 0]
    elif anomaly == "工時小於5分鐘":
        out = out[(out["work_hours"] > 0) & (out["work_hours"] < (5 / 60))]
    elif anomaly == "工時大於8小時":
        out = out[out["work_hours"] > 8]
    elif anomaly == "工時大於12小時":
        out = out[out["work_hours"] > 12]
    elif anomaly in {"未按結束", "有開始無結束"}:
        out = out[(start_ts != "") & (end_ts.isin(["", "None", "none", "nan"]))]
    elif anomaly == "有結束無開始":
        out = out[(start_ts.isin(["", "None", "none", "nan"])) & (~end_ts.isin(["", "None", "none", "nan"]))]
    elif anomaly == "跨日紀錄":
        out = out[(start_date != "") & (end_date != "") & (start_date != end_date)]
    return out


def _sort_summary(df: pd.DataFrame, mode: str, key_col: str = "work_order") -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if mode == "製令由新到舊" and key_col in df.columns:
        return df.sort_values(key_col, ascending=False, na_position="last").reset_index(drop=True)
    if mode == "紀錄筆數" and "count" in df.columns:
        return df.sort_values("count", ascending=False, na_position="last").reset_index(drop=True)
    if mode == "平均工時" and "avg_hours" in df.columns:
        return df.sort_values("avg_hours", ascending=False, na_position="last").reset_index(drop=True)
    return df.sort_values("total_hours", ascending=False, na_position="last").reset_index(drop=True)


def _apply_top(df: pd.DataFrame, top_n: str) -> pd.DataFrame:
    if top_n == "全部":
        return df
    try:
        n = int(str(top_n).replace("Top", "").strip())
        return df.head(n)
    except Exception:
        return df.head(20)


def _blank_to_unknown(series: pd.Series, unknown: str) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    return s.mask(s.isin(["", "None", "none", "nan", "NaN"]), unknown)


def _parse_work_hours_value(value) -> float:
    """Return decimal hours from numeric values or HH:MM:SS text.

    Some legacy records store work_hours as decimal hours, while others store
    display text such as 00:12:30. This page must aggregate both correctly.
    """
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except Exception:
        pass
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return 0.0
    s = str(value).strip()
    if not s or s.lower() in {"none", "nan", "nat"}:
        return 0.0
    s = s.replace("，", ",").replace(",", "")
    if ":" in s:
        try:
            parts = [float(x or 0) for x in s.split(":")]
            if len(parts) == 3:
                return max(0.0, parts[0] + parts[1] / 60 + parts[2] / 3600)
            if len(parts) == 2:
                return max(0.0, parts[0] + parts[1] / 60)
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _coerce_work_hours(series: pd.Series) -> pd.Series:
    return series.map(_parse_work_hours_value).astype(float)


def _build_work_order_process_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the requested work-order total + per-process hour summaries.

    Returns:
        detail: one row per Work Order + Process.
        pivot_hours: matrix with work orders as rows and process names as columns.
        pivot_text: same matrix but formatted as HH:MM:SS text for Excel/readability.
    """
    if df is None or df.empty:
        empty_detail = pd.DataFrame(columns=[
            "work_order", "process_name", "process_hours", "process_time",
            "work_order_total_hours", "work_order_total_time", "share_percent",
            "count", "employee_count", "avg_hours", "avg_time",
        ])
        return empty_detail, pd.DataFrame(), pd.DataFrame()

    work = df.copy()
    if "work_order" not in work.columns:
        work["work_order"] = ""
    if "process_name" not in work.columns:
        work["process_name"] = ""
    if "work_hours" not in work.columns:
        work["work_hours"] = 0.0
    if "employee_id" not in work.columns:
        work["employee_id"] = ""
    if "id" not in work.columns:
        work["id"] = range(1, len(work) + 1)

    work["work_order"] = _blank_to_unknown(work["work_order"], "未填製令")
    work["process_name"] = _blank_to_unknown(work["process_name"], "未填工段")
    work["work_hours"] = _coerce_work_hours(work["work_hours"])

    detail = (
        work.groupby(["work_order", "process_name"], dropna=False)
        .agg(
            process_hours=("work_hours", "sum"),
            count=("id", "count"),
            employee_count=("employee_id", "nunique"),
            avg_hours=("work_hours", "mean"),
        )
        .reset_index()
    )
    totals = (
        work.groupby("work_order", dropna=False)["work_hours"]
        .sum()
        .reset_index()
        .rename(columns={"work_hours": "work_order_total_hours"})
    )
    detail = detail.merge(totals, on="work_order", how="left")
    detail["share_percent"] = detail.apply(
        lambda r: round((float(r["process_hours"]) / float(r["work_order_total_hours"]) * 100), 2)
        if float(r.get("work_order_total_hours") or 0) > 0 else 0.0,
        axis=1,
    )
    detail["process_time"] = detail["process_hours"].map(hours_to_hms)
    detail["work_order_total_time"] = detail["work_order_total_hours"].map(hours_to_hms)
    detail["avg_time"] = detail["avg_hours"].map(hours_to_hms)
    detail = detail.sort_values(
        ["work_order_total_hours", "work_order", "process_hours"],
        ascending=[False, True, False],
        na_position="last",
    ).reset_index(drop=True)

    pivot_hours = (
        work.pivot_table(
            index="work_order",
            columns="process_name",
            values="work_hours",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    if not pivot_hours.empty:
        process_cols = [c for c in pivot_hours.columns if c != "work_order"]
        pivot_hours["總工時 / Total Hours"] = pivot_hours[process_cols].sum(axis=1) if process_cols else 0
        pivot_hours = pivot_hours.sort_values("總工時 / Total Hours", ascending=False).reset_index(drop=True)
        # Put total immediately after work_order for easier reading.
        cols = ["work_order", "總工時 / Total Hours"] + [c for c in pivot_hours.columns if c not in {"work_order", "總工時 / Total Hours"}]
        pivot_hours = pivot_hours[cols]

    pivot_text = pivot_hours.copy()
    for col in [c for c in pivot_text.columns if c != "work_order"]:
        pivot_text[col] = pd.to_numeric(pivot_text[col], errors="coerce").fillna(0).map(hours_to_hms)

    return detail, pivot_hours, pivot_text


def _localize_work_order_process_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    cols = {
        "work_order": "製令 / Work Order",
        "process_name": "工段名稱 / Process",
        "process_hours": "工段工時(小時) / Process Hours",
        "process_time": "工段工時 / Process Time",
        "work_order_total_hours": "製令總工時(小時) / WO Total Hours",
        "work_order_total_time": "製令總工時 / WO Total Time",
        "share_percent": "工段佔比% / Share %",
        "count": "紀錄筆數 / Records",
        "employee_count": "人員數 / Employees",
        "avg_hours": "平均工時(小時) / Avg Hours",
        "avg_time": "平均工時 / Avg Time",
    }
    return df.rename(columns={k: v for k, v in cols.items() if k in df.columns})


def _v30030_build_analysis_bundle(source_df: pd.DataFrame, filters: dict) -> dict:
    """Build heavy derived analysis outputs once per applied filter signature.

    This keeps the read/write model unchanged: Neon is still queried only when
    the user applies filters.  It only prevents Streamlit reruns from rebuilding
    the same groupby, pivot and metric data over and over.
    """
    work_df = _apply_filters(source_df, filters)
    if work_df is None or work_df.empty:
        return {
            "df": pd.DataFrame() if work_df is None else work_df,
            "avg_hours": 0.0,
            "unfinished_count": 0,
            "abnormal_count": 0,
            "max_wo": "-",
            "by_wo": pd.DataFrame(),
            "by_proc": pd.DataFrame(),
            "wo_process": pd.DataFrame(),
            "wo_process_display": pd.DataFrame(),
            "wo_process_pivot_hours": pd.DataFrame(),
            "wo_process_pivot_text": pd.DataFrame(),
            "by_emp": pd.DataFrame(),
            "trend": pd.DataFrame(),
        }

    work_df = work_df.copy()
    if "work_hours" not in work_df.columns:
        work_df["work_hours"] = 0.0
    work_df["work_hours"] = _coerce_work_hours(work_df["work_hours"])
    work_df["work_time_text"] = work_df["work_hours"].map(hours_to_hms)

    for col in ["work_order", "process_name", "employee_id", "employee_name", "department", "start_date", "id"]:
        if col not in work_df.columns:
            work_df[col] = "" if col != "id" else range(1, len(work_df) + 1)

    end_ts = work_df.get("end_timestamp", pd.Series([""] * len(work_df))).fillna("").astype(str).str.strip()
    status_series = work_df.get("status", pd.Series([""] * len(work_df))).fillna("").astype(str)
    unfinished_mask = (status_series == "作業中") & (end_ts.isin(["", "None", "none", "nan"]))
    abnormal_mask = (work_df["work_hours"] == 0) | (work_df["work_hours"] > 12) | unfinished_mask
    avg_hours = work_df["work_hours"].mean() if len(work_df) else 0

    max_wo = "-"
    if "work_order" in work_df.columns and not work_df.empty:
        tmp = work_df.groupby("work_order", dropna=False)["work_hours"].sum().sort_values(ascending=False)
        max_wo = str(tmp.index[0]) if len(tmp) else "-"

    sort_by = filters.get("sort_by", "累積工時由大到小")
    by_wo = (
        work_df.groupby("work_order", dropna=False)
        .agg(total_hours=("work_hours", "sum"), count=("id", "count"), avg_hours=("work_hours", "mean"), employee_count=("employee_id", "nunique"), process_count=("process_name", "nunique"))
        .reset_index()
    )
    by_wo = _sort_summary(by_wo, sort_by, "work_order")
    by_wo["工時 / Time"] = by_wo["total_hours"].map(hours_to_hms)
    by_wo["平均 / Avg"] = by_wo["avg_hours"].map(hours_to_hms)

    by_proc = (
        work_df.groupby("process_name", dropna=False)
        .agg(total_hours=("work_hours", "sum"), count=("id", "count"), avg_hours=("work_hours", "mean"), employee_count=("employee_id", "nunique"), work_order_count=("work_order", "nunique"))
        .reset_index()
    )
    by_proc = _sort_summary(by_proc, sort_by, "process_name")
    by_proc["工時 / Time"] = by_proc["total_hours"].map(hours_to_hms)
    by_proc["平均 / Avg"] = by_proc["avg_hours"].map(hours_to_hms)

    wo_process, wo_process_pivot_hours, wo_process_pivot_text = _build_work_order_process_summary(work_df)
    wo_process_display = _localize_work_order_process_table(wo_process)

    by_emp = (
        work_df.groupby(["employee_id", "employee_name", "department"], dropna=False)
        .agg(total_hours=("work_hours", "sum"), count=("id", "count"), avg_hours=("work_hours", "mean"), work_order_count=("work_order", "nunique"), process_count=("process_name", "nunique"))
        .reset_index()
    )
    by_emp = _sort_summary(by_emp, sort_by, "employee_name")
    by_emp["工時 / Time"] = by_emp["total_hours"].map(hours_to_hms)
    by_emp["平均 / Avg"] = by_emp["avg_hours"].map(hours_to_hms)

    trend = (
        work_df.groupby("start_date", dropna=False)
        .agg(total_hours=("work_hours", "sum"), count=("id", "count"), work_order_count=("work_order", "nunique"), employee_count=("employee_id", "nunique"))
        .reset_index()
        .sort_values("start_date")
    )
    trend["工時 / Time"] = trend["total_hours"].map(hours_to_hms)

    return {
        "df": work_df,
        "avg_hours": avg_hours,
        "unfinished_count": int(unfinished_mask.sum()),
        "abnormal_count": int(abnormal_mask.sum()),
        "max_wo": max_wo,
        "by_wo": by_wo,
        "by_proc": by_proc,
        "wo_process": wo_process,
        "wo_process_display": wo_process_display,
        "wo_process_pivot_hours": wo_process_pivot_hours,
        "wo_process_pivot_text": wo_process_pivot_text,
        "by_emp": by_emp,
        "trend": trend,
    }


start_saved = _parse_date(filters.get("start_date"), today_date())
end_saved = _parse_date(filters.get("end_date"), today_date())
# V69: do not query time_records detail rows just to open the analysis page.
# V300.71: still preload lightweight filter option lists from master data and
# date-bounded SQL DISTINCT so multiselects are usable without full history scans.
base_df = st.session_state.get(V69_DF_KEY, pd.DataFrame())
if not isinstance(base_df, pd.DataFrame):
    base_df = pd.DataFrame()
analysis_option_values = _v30071_load_analysis_filter_options_cached(start_saved, end_saved, filters, base_df)

with st.expander("🔎 專業 BI 篩選 / Professional BI Filters", expanded=True):
    st.caption("所有條件按「套用篩選」後才重新運算，避免每點一下就卡頓；條件會永久記錄。")
    with st.form("analysis_filter_form", clear_on_submit=False):
        r1c1, r1c2, r1c3, r1c4 = st.columns([1.2, 1, 1, 1])
        preset = r1c1.selectbox("快速日期 / Quick Date", DATE_PRESETS, index=DATE_PRESETS.index(filters.get("date_preset", V30091_ANALYSIS_DEFAULT_PRESET)) if filters.get("date_preset", V30091_ANALYSIS_DEFAULT_PRESET) in DATE_PRESETS else 0)
        start_input = r1c2.date_input("開始日期 / Start Date", value=start_saved)
        end_input = r1c3.date_input("結束日期 / End Date", value=end_saved)
        top_n = r1c4.selectbox("Top N", TOP_OPTIONS, index=TOP_OPTIONS.index(filters.get("top_n", "Top 20")) if filters.get("top_n", "Top 20") in TOP_OPTIONS else 1)

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        selected_wo = r2c1.multiselect("製令 / Work Order", _v30071_options(analysis_option_values, "work_order", filters.get("work_orders")), default=filters.get("work_orders", []))
        selected_pn = r2c2.multiselect("P/N", _v30071_options(analysis_option_values, "part_no", filters.get("part_nos")), default=filters.get("part_nos", []))
        selected_type = r2c3.multiselect("機型 / Type", _v30071_options(analysis_option_values, "type_name", filters.get("type_names")), default=filters.get("type_names", []))
        selected_customer = r2c4.multiselect("客戶 / Customer", _v30071_options(analysis_option_values, "customer", filters.get("customers")), default=filters.get("customers", []))

        r3c1, r3c2, r3c3, r3c4 = st.columns(4)
        selected_loc = r3c1.multiselect("組立地點 / Assembly", _v30071_options(analysis_option_values, "assembly_location", filters.get("assembly_locations")), default=filters.get("assembly_locations", []))
        selected_process = r3c2.multiselect("工段名稱 / Process", _v30071_options(analysis_option_values, "process_name", filters.get("process_names")), default=filters.get("process_names", []))
        selected_emp_id = r3c3.multiselect("工號 / Employee ID", _v30071_options(analysis_option_values, "employee_id", filters.get("employee_ids")), default=filters.get("employee_ids", []))
        selected_emp_name = r3c4.multiselect("姓名 / Name", _v30071_options(analysis_option_values, "employee_name", filters.get("employee_names")), default=filters.get("employee_names", []))

        r4c1, r4c2, r4c3, r4c4 = st.columns(4)
        selected_dept = r4c1.multiselect("單位 / Department", _v30071_options(analysis_option_values, "department", filters.get("departments")), default=filters.get("departments", []))
        selected_title = r4c2.multiselect("職稱 / Title", _v30071_options(analysis_option_values, "title", filters.get("titles")), default=filters.get("titles", []))
        status_filter = r4c3.selectbox("狀態 / Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(filters.get("status_filter", "全部")) if filters.get("status_filter", "全部") in STATUS_OPTIONS else 0)
        anomaly_filter = r4c4.selectbox("異常篩選 / Exception", ANOMALY_OPTIONS, index=ANOMALY_OPTIONS.index(filters.get("anomaly_filter", "全部")) if filters.get("anomaly_filter", "全部") in ANOMALY_OPTIONS else 0)

        r5c1, r5c2, r5c3 = st.columns([1.4, 1, 1])
        sort_by = r5c1.selectbox("圖表排序 / Sort", SORT_OPTIONS, index=SORT_OPTIONS.index(filters.get("sort_by", "累積工時由大到小")) if filters.get("sort_by", "累積工時由大到小") in SORT_OPTIONS else 0)
        detail_limit = r5c2.number_input("明細讀取上限 / Detail Limit", min_value=100, max_value=20000, value=int(filters.get("detail_limit", 1000) or 1000), step=100)
        clear_filter = r5c3.checkbox("清除所有篩選 / Clear", value=False)


        apply_filter = st.form_submit_button("🔎 套用篩選並永久記錄 / Apply Filters", type="primary", use_container_width=True)
    if apply_filter:
        if clear_filter:
            new_filters = load_analysis_filters()
            new_filters.update({
                "date_preset": V30091_ANALYSIS_DEFAULT_PRESET,
                "start_date": str(today_date()),
                "end_date": str(today_date()),
                "work_orders": [], "part_nos": [], "type_names": [], "customers": [], "assembly_locations": [],
                "process_names": [], "employee_ids": [], "employee_names": [], "departments": [], "titles": [],
                "status_filter": "全部", "anomaly_filter": "全部", "top_n": "Top 20", "sort_by": "累積工時由大到小", "detail_limit": 1000,
            })
        else:
            new_start, new_end = _date_range_from_preset(preset, start_input, end_input)
            new_filters = {
                "date_preset": preset,
                "start_date": str(new_start),
                "end_date": str(new_end),
                "work_orders": _clean_filter_list(selected_wo),
                "part_nos": _clean_filter_list(selected_pn),
                "type_names": _clean_filter_list(selected_type),
                "customers": _clean_filter_list(selected_customer),
                "assembly_locations": _clean_filter_list(selected_loc),
                "process_names": _clean_filter_list(selected_process),
                "employee_ids": _clean_filter_list(selected_emp_id),
                "employee_names": _clean_filter_list(selected_emp_name),
                "departments": _clean_filter_list(selected_dept),
                "titles": _clean_filter_list(selected_title),
                "status_filter": status_filter,
                "anomaly_filter": anomaly_filter,
                "top_n": top_n,
                "sort_by": sort_by,
                "detail_limit": int(detail_limit),
            }
        st.session_state[FILTER_KEY] = new_filters
        save_analysis_filters(new_filters)
        st.session_state[V69_QUERY_KEY] = True
        st.session_state.pop(V69_DF_KEY, None)
        st.session_state.pop(V69_FILTER_SIG_KEY, None)
        _v30030_clear_analysis_output_cache()
        st.success("已套用並永久記錄 05 分析篩選條件，正在查詢分析資料。")
        st.rerun()

# 依已套用條件重新查詢與分析。
filters = dict(st.session_state[FILTER_KEY])
start = _parse_date(filters.get("start_date"), today_date() - timedelta(days=30))
end = _parse_date(filters.get("end_date"), today_date())
if not st.session_state.get(V69_QUERY_KEY, False):
    st.info("請設定條件後按『套用篩選並永久記錄』查詢。V69：本頁不再於開啟時自動掃描工時紀錄。")
    try:
        _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
    except Exception:
        pass
    st.stop()

_filter_signature = repr(sorted(filters.items()))
if st.session_state.get(V69_FILTER_SIG_KEY) == _filter_signature and isinstance(st.session_state.get(V69_DF_KEY), pd.DataFrame):
    df = st.session_state[V69_DF_KEY].copy()
else:
    df = _enrich_records(load_records(str(start), str(end)))
    st.session_state[V69_DF_KEY] = df.copy()
    st.session_state[V69_FILTER_SIG_KEY] = _filter_signature

if df.empty:
    st.info("查無工時資料 / No records")
    st.stop()

_summary_sig = f"{_filter_signature}|rows={len(df)}|v30030"
_cached_summary = st.session_state.get(V30030_SUMMARY_CACHE_KEY)
if isinstance(_cached_summary, dict) and _cached_summary.get("sig") == _summary_sig and isinstance(_cached_summary.get("bundle"), dict):
    _bundle = _cached_summary["bundle"]
else:
    _bundle = _v30030_build_analysis_bundle(df, filters)
    st.session_state[V30030_SUMMARY_CACHE_KEY] = {"sig": _summary_sig, "bundle": _bundle}

df = _bundle.get("df", pd.DataFrame())
if df.empty:
    st.warning("目前篩選條件下查無資料，請調整篩選條件後再套用。")
    st.stop()

avg_hours = float(_bundle.get("avg_hours") or 0)
max_wo = str(_bundle.get("max_wo") or "-")
by_wo = _bundle.get("by_wo", pd.DataFrame())
by_proc = _bundle.get("by_proc", pd.DataFrame())
wo_process = _bundle.get("wo_process", pd.DataFrame())
wo_process_display = _bundle.get("wo_process_display", pd.DataFrame())
wo_process_pivot_hours = _bundle.get("wo_process_pivot_hours", pd.DataFrame())
wo_process_pivot_text = _bundle.get("wo_process_pivot_text", pd.DataFrame())
by_emp = _bundle.get("by_emp", pd.DataFrame())
trend = _bundle.get("trend", pd.DataFrame())

m1, m2, m3, m4 = st.columns(4)
m1.metric("累積工時 / Total Time", hours_to_hms(df["work_hours"].sum()))
m2.metric("製令數 / Work Orders", f"{df['work_order'].nunique():,}" if "work_order" in df.columns else "0")
m3.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}" if "employee_id" in df.columns else "0")
m4.metric("工段數 / Processes", f"{df['process_name'].nunique():,}" if "process_name" in df.columns else "0")

k1, k2, k3, k4 = st.columns(4)
k1.metric("平均每筆工時 / Avg", hours_to_hms(avg_hours))
k2.metric("未結束筆數 / Unfinished", f"{int(_bundle.get('unfinished_count') or 0):,}")
k3.metric("異常筆數 / Exceptions", f"{int(_bundle.get('abnormal_count') or 0):,}")
k4.metric("最大工時製令 / Top WO", max_wo)

sort_by = filters.get("sort_by", "累積工時由大到小")
top_n = filters.get("top_n", "Top 20")

plotly_template = "plotly_dark"


def style_fig(fig, height: int = 430):
    fig.update_layout(
        template=plotly_template,
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=60, b=80),
        font=dict(size=14, color="#EAFBFF"),
        yaxis_title="累積時數",
        xaxis=dict(showgrid=False, linecolor="rgba(90,244,255,.35)"),
        yaxis=dict(gridcolor="rgba(180,220,255,.16)", linecolor="rgba(90,244,255,.35)"),
    )
    fig.update_traces(marker_line_width=1.2, marker_line_color="rgba(255,255,255,.55)")
    return fig



st.markdown("### ⟰ Excel 下載 / Excel Export")
st.download_button(
    "⟰ 下載目前分析結果 Excel / Export Current Analysis",
    data=_v30030_excel_bytes_cached("current_analysis", _summary_sig, {
        "summary_work_order": by_wo,
        "work_order_process": wo_process_display,
        "wo_process_pivot_hours": wo_process_pivot_hours,
        "wo_process_pivot_time": wo_process_pivot_text,
        "summary_process": by_proc,
        "summary_employee": by_emp,
        "daily_trend": trend,
        "filtered_detail": df.head(int(filters.get("detail_limit", 1000) or 1000)),
    }),
    file_name="SPT_製令工時分析.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["製令分析", "製令 x 工段", "工段分析", "人員分析", "趨勢分析", "明細編輯"])

with tab1:
    st.subheader("製令累積工時 / Work Order Time")
    plot_df = _apply_top(by_wo, top_n)
    fig = px.bar(
        plot_df,
        x="work_order",
        y="total_hours",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "employee_count": True, "process_count": True},
        labels={"work_order": "製令 / Work Order", "total_hours": "累積時數 / Total Hours", "count": "筆數"},
        title=f"{top_n} 製令累積工時 / Work Order Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 460), use_container_width=True)
    render_table(by_wo.drop(columns=["工時 / Time", "平均 / Avg"], errors="ignore"), "analysis_by_work_order", editable=False, height=380)

with tab2:
    st.subheader("每個製令總工時與各工段工時 / Work Order by Process")
    st.caption("依目前篩選條件彙總：每個製令的總工時，以及該製令底下各工段名稱 / Process 的工時、佔比、筆數與人員數。")
    p1, p2, p3 = st.columns(3)
    p1.metric("製令 x 工段組合 / WO-Process", f"{len(wo_process):,}")
    p2.metric("製令總數 / Work Orders", f"{wo_process['work_order'].nunique():,}" if not wo_process.empty and "work_order" in wo_process.columns else "0")
    p3.metric("工段總數 / Processes", f"{wo_process['process_name'].nunique():,}" if not wo_process.empty and "process_name" in wo_process.columns else "0")

    if not wo_process.empty:
        top_work_orders = _apply_top(by_wo, top_n)["work_order"].astype(str).tolist() if "work_order" in by_wo.columns else []
        plot_df = wo_process[wo_process["work_order"].astype(str).isin(top_work_orders)].copy() if top_work_orders else wo_process.copy()
        if plot_df.empty:
            plot_df = wo_process.copy()
        fig = px.bar(
            plot_df,
            x="work_order",
            y="process_hours",
            color="process_name",
            text="process_time",
            hover_data={
                "process_hours": ":.2f",
                "process_time": True,
                "work_order_total_time": True,
                "share_percent": ":.2f",
                "count": True,
                "employee_count": True,
            },
            labels={
                "work_order": "製令 / Work Order",
                "process_hours": "工段工時 / Process Hours",
                "process_name": "工段名稱 / Process",
                "share_percent": "佔比%",
            },
            title=f"{top_n} 製令各工段工時堆疊 / Work Order Process Breakdown",
        )
        fig.update_traces(textposition="inside")
        st.plotly_chart(style_fig(fig, 520), use_container_width=True)

    st.markdown("#### 製令 x 工段明細 / Work Order x Process Detail")
    render_table(wo_process_display, "analysis_work_order_process_detail_v233", editable=False, height=420)

    st.markdown("#### 製令工段矩陣 / Work Order Process Matrix")
    matrix_mode = st.radio(
        "矩陣顯示格式 / Matrix Format",
        ["時:分:秒", "小時數"],
        horizontal=True,
        key="analysis_wo_process_matrix_mode_v233",
    )
    matrix_df = wo_process_pivot_text if matrix_mode == "時:分:秒" else wo_process_pivot_hours
    render_table(matrix_df, "analysis_work_order_process_matrix_v233", editable=False, height=420)

    st.download_button(
        "⟰ 下載製令 x 工段分析 Excel / Export Work Order Process Analysis",
        data=_v30030_excel_bytes_cached("wo_process", _summary_sig, {
            "work_order_process": wo_process_display,
            "pivot_hours": wo_process_pivot_hours,
            "pivot_time": wo_process_pivot_text,
            "filtered_detail": df.head(int(filters.get("detail_limit", 1000) or 1000)),
        }),
        file_name="SPT_製令工段工時分析.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

with tab3:
    st.subheader("工段累積工時 / Process Time")
    plot_df = _apply_top(by_proc, top_n)
    fig = px.bar(
        plot_df,
        x="process_name",
        y="total_hours",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "employee_count": True, "work_order_count": True},
        labels={"process_name": "工段 / Process", "total_hours": "累積時數 / Total Hours", "count": "筆數"},
        title=f"{top_n} 工段累積工時 / Process Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 460), use_container_width=True)
    render_table(by_proc.drop(columns=["工時 / Time", "平均 / Avg"], errors="ignore"), "analysis_by_process", editable=False, height=380)

with tab4:
    st.subheader("人員累積工時 / Employee Time")
    plot_df = _apply_top(by_emp, top_n)
    fig = px.bar(
        plot_df,
        x="employee_name",
        y="total_hours",
        color="employee_id",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "department": True},
        labels={"employee_name": "人員 / Employee", "total_hours": "累積時數 / Total Hours", "employee_id": "工號"},
        title=f"{top_n} 人員累積工時 / Employee Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 480), use_container_width=True)
    render_table(by_emp.drop(columns=["工時 / Time", "平均 / Avg"], errors="ignore"), "analysis_by_employee", editable=False, height=380)

with tab5:
    st.subheader("每日趨勢 / Daily Trend")
    fig = px.line(
        trend,
        x="start_date",
        y="total_hours",
        markers=True,
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "work_order_count": True, "employee_count": True},
        labels={"start_date": "日期 / Date", "total_hours": "累積時數 / Total Hours"},
        title="每日累積工時趨勢 / Daily Time Trend",
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(style_fig(fig, 430), use_container_width=True)
    render_table(trend.drop(columns=["工時 / Time"], errors="ignore"), "analysis_daily_trend", editable=False, height=320)

with tab6:
    st.caption("此處編輯的是分析來源明細，儲存後會影響歷史紀錄與後續統計。工時欄位以 00:00:00 顯示，需調整時請改開始/結束時間後重新計算。")
    detail_limit = int(filters.get("detail_limit", 1000) or 1000)
    detail_df = df.head(detail_limit).drop(columns=["work_time_text"], errors="ignore")
    st.info("V63：明細編輯與 10｜權限管理同模式；儲存後會清除全域 data_editor 草稿，避免畫面殘留舊資料。")
    analysis_detail_draft_key = "analysis_detail_records_draft_v58"
    edited = render_table(
        detail_df,
        "analysis_detail_records",
        editable=True,
        disabled=["id", "record_key", "created_at", "updated_at", "work_hours"],
        key="analysis_detail_editor_v58",
        height=520,
    )
    if isinstance(edited, pd.DataFrame):
        st.session_state[analysis_detail_draft_key] = edited.copy()
    submitted_analysis_detail = st.button(
        "▣ 確認儲存分析明細 / Save Detail Records",
        type="primary",
        use_container_width=True,
        key="analysis_detail_save_button_v58",
    )
    if submitted_analysis_detail:
        edited = st.session_state.get(analysis_detail_draft_key, edited)
        if edited is None:
            st.warning("找不到可儲存的分析明細內容，請重新載入後再試。")
            st.stop()
        count = save_time_records(edited)
        try:
            from services.column_settings_service import clear_editor_draft
            clear_editor_draft("analysis_detail_editor")
            clear_editor_draft("analysis_detail_records")
        except Exception:
            pass
        st.session_state.pop(V69_DF_KEY, None)
        st.session_state.pop(V69_FILTER_SIG_KEY, None)
        _v30030_clear_analysis_output_cache()
        st.success(f"已儲存 {count} 筆明細。")
        st.rerun()

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

