# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import re
import pandas as pd
from services.timezone_service import today_date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.time_record_service import (
    load_records,
    save_time_records,
    delete_time_records,
    recalculate_time_records,
    import_time_records,
)
from services.master_data_service import load_employees, load_work_orders
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms
from services.history_filter_service import load_history_filters, save_history_filters, reset_history_filters

st.set_page_config(page_title="02. 歷史紀錄", page_icon="📚", layout="wide")
apply_theme()
require_module_access("02_history")
render_header("02｜歷史紀錄", "完整工時明細查詢、資料編輯、刪除、重新計算、Excel 匯入、貼上資料與 Excel 匯出")

HISTORY_IMPORT_PREVIEW_KEY = "v197_history_import_preview"
HISTORY_PASTE_RAW_KEY = "v197_history_paste_raw"


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def _normalize_text(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _normalize_header_name(v) -> str:
    text = _normalize_text(v).lower()
    for ch in [" ", "\t", "\n", "\r", "_", "-", "－", "—", "/", "／", "\\", ".", "．", "：", ":", "（", "）", "(", ")"]:
        text = text.replace(ch, "")
    return text


def _split_paste_line(line: str) -> list[str]:
    line = line.rstrip("\n")
    if "\t" in line:
        return [x.strip() for x in line.split("\t")]
    if "," in line:
        return [x.strip() for x in line.split(",")]
    parts = [x.strip() for x in re.split(r"\s{2,}", line) if x.strip()]
    if len(parts) <= 1:
        parts = [x.strip() for x in line.split()]
    return parts


HISTORY_ALIAS_GROUPS = {
    "id": ["id", "編號"],
    "record_key": ["record key", "record_key", "紀錄鍵", "唯一鍵", "key"],
    "status": ["狀態", "status"],
    "work_order": ["製令", "工單", "工令", "製令號碼", "work order", "work_order", "wo", "mo"],
    "part_no": ["p/n", "pn", "part no", "part_no", "料號", "品號"],
    "type_name": ["機型", "type", "type name", "type_name", "model", "型號"],
    "process_name": ["工段名稱", "工段", "process", "process name", "process_name", "作業工段"],
    "employee_id": ["工號", "employee id", "employee_id", "emp id", "人員工號"],
    "employee_name": ["姓名", "name", "employee name", "employee_name", "人員姓名"],
    "start_action": ["開始動作", "start action", "start_action"],
    "start_timestamp": ["開始時間戳", "開始時間", "start timestamp", "start_timestamp", "start datetime", "開始日期時間"],
    "end_action": ["結束動作", "end action", "end_action"],
    "end_timestamp": ["結束時間戳", "結束時間", "end timestamp", "end_timestamp", "end datetime", "結束日期時間"],
    "remark": ["備註", "remark", "note", "memo"],
    "start_date": ["開始日期", "start date", "start_date"],
    "start_time": ["開始時間", "start time", "start_time"],
    "end_date": ["結束日期", "end date", "end_date"],
    "end_time": ["結束時間", "end time", "end_time"],
    "work_hours": ["工時小計", "工時", "work time", "work hours", "work_hours", "total hours"],
    "assembly_location": ["組立地點", "組裝地點", "assembly location", "assembly_location", "location"],
    "group_key": ["群組", "群組鍵", "group key", "group_key"],
    "is_group_work": ["同時作業", "群組作業", "parallel work", "is_group_work"],
    "source": ["來源", "source"],
}

HISTORY_COLS = [
    "id", "record_key", "status", "work_order", "part_no", "type_name", "process_name",
    "employee_id", "employee_name", "start_action", "start_timestamp", "end_action", "end_timestamp",
    "remark", "start_date", "start_time", "end_date", "end_time", "work_hours", "assembly_location",
    "group_key", "is_group_work", "source",
]

DEFAULT_PASTE_ORDER = [
    "status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name",
    "start_timestamp", "end_timestamp", "remark", "assembly_location",
]


def _find_col(source: pd.DataFrame, aliases: list[str]):
    norm_to_col = {_normalize_header_name(c): c for c in source.columns}
    norm_aliases = [_normalize_header_name(a) for a in aliases]
    for alias in norm_aliases:
        if alias in norm_to_col:
            return norm_to_col[alias]
    for alias in norm_aliases:
        for norm_col, real_col in norm_to_col.items():
            if alias and (alias in norm_col or norm_col in alias):
                return real_col
    return None


def _row_looks_like_header(row: list[str]) -> bool:
    norm_row = {_normalize_header_name(x) for x in row}
    hits = 0
    for aliases in HISTORY_ALIAS_GROUPS.values():
        norm_aliases = {_normalize_header_name(a) for a in aliases}
        if norm_row & norm_aliases:
            hits += 1
    return hits >= 2


def _pick_series(source: pd.DataFrame, target: str, default=""):
    col = _find_col(source, HISTORY_ALIAS_GROUPS[target])
    if col is None:
        return default
    return source[col]


def _ensure_history_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in HISTORY_COLS:
        if c not in df.columns:
            if c == "is_group_work":
                df[c] = False
            else:
                df[c] = ""
    return df[HISTORY_COLS].copy()


def parse_history_dataframe(source: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if source is None or source.empty:
        return _ensure_history_cols(pd.DataFrame()), ["來源資料為空。"]

    source = source.copy()
    # Some Excel exports have completely blank rows/columns.
    source = source.dropna(how="all").dropna(axis=1, how="all")
    if source.empty:
        return _ensure_history_cols(pd.DataFrame()), ["來源資料沒有有效列。"]

    data = {}
    for c in HISTORY_COLS:
        picked = _pick_series(source, c, default="")
        data[c] = picked
    parsed = pd.DataFrame(data)

    # If no recognizable headers were found, preserve the original columns by position.
    if parsed[["work_order", "process_name", "employee_id", "start_timestamp"]].astype(str).replace("", pd.NA).isna().all().all():
        warnings.append("未偵測到可辨識標題，已依預設順序解析：狀態、製令、P/N、機型、工段、工號、姓名、開始時間戳、結束時間戳、備註、組立地點。")
        rows = source.astype(str).fillna("").values.tolist()
        normalized = []
        for row in rows:
            item = {c: "" for c in HISTORY_COLS}
            for idx, col_name in enumerate(DEFAULT_PASTE_ORDER):
                if idx < len(row):
                    item[col_name] = row[idx]
            normalized.append(item)
        parsed = pd.DataFrame(normalized)

    for c in HISTORY_COLS:
        if c not in parsed.columns:
            parsed[c] = ""
    for c in ["status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name", "start_action", "end_action", "remark", "assembly_location", "group_key", "source"]:
        parsed[c] = parsed[c].map(_normalize_text)
    if "is_group_work" in parsed.columns:
        parsed["is_group_work"] = parsed["is_group_work"].map(lambda x: str(x).strip().lower() in ["1", "true", "是", "y", "yes", "群組", "同時作業"])

    before = len(parsed)
    required_blank = (
        parsed["employee_id"].map(_normalize_text).eq("")
        | parsed["work_order"].map(_normalize_text).eq("")
        | parsed["process_name"].map(_normalize_text).eq("")
        | (parsed["start_timestamp"].map(_normalize_text).eq("") & (parsed["start_date"].map(_normalize_text).eq("") | parsed["start_time"].map(_normalize_text).eq("")))
    )
    parsed = parsed[~required_blank].copy()
    dropped = before - len(parsed)
    if dropped > 0:
        warnings.append(f"已略過 {dropped} 筆缺少工號、製令、工段或開始時間的資料列。")
    return _ensure_history_cols(parsed), warnings


def parse_pasted_history(raw: str) -> tuple[pd.DataFrame, bool, list[str]]:
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [_split_paste_line(line) for line in lines]
    if not rows:
        return _ensure_history_cols(pd.DataFrame()), False, ["尚未貼上資料。"]
    has_header = _row_looks_like_header(rows[0])
    if has_header:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])
    else:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows)
    parsed, warnings = parse_history_dataframe(source)
    if not has_header:
        # parse_history_dataframe already adds default-order warning if needed; make it explicit for paste users.
        if not any("預設順序" in w for w in warnings):
            warnings.append("未偵測到標題列，已用預設順序解析。")
    return parsed, has_header, warnings


def _download_history_template():
    template = pd.DataFrame([
        {
            "狀態 / Status": "已結束",
            "製令 / Work Order": "21M0241-01",
            "P/N / Part No.": "4TRSC020-004-02",
            "機型 / Type": "NTB 3 PORT",
            "工段名稱 / Process": "配電",
            "工號 / Employee ID": "B002",
            "姓名 / Name": "張文品",
            "開始時間戳 / Start Timestamp": "2026-05-15 08:30:00",
            "結束時間戳 / End Timestamp": "2026-05-15 10:30:00",
            "備註 / Remark": "Excel 匯入範例",
            "組立地點 / Assembly Location": "竹東",
        }
    ])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        template.to_excel(writer, index=False, sheet_name="歷史紀錄匯入範本")
    return bio.getvalue()



def _safe_unique(df: pd.DataFrame, col: str) -> list[str]:
    if df is None or df.empty or col not in df.columns:
        return []
    vals = df[col].dropna().astype(str).map(str.strip)
    vals = vals[(vals != "") & (vals.str.lower() != "none")]
    return sorted(vals.unique().tolist())


def _merge_options(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def _month_range(offset: int = 0) -> tuple[date, date]:
    today = today_date()
    year = today.year
    month = today.month + offset
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    start_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return start_day, next_month - timedelta(days=1)


def _date_range_from_preset(preset: str, fallback_start: str, fallback_end: str) -> tuple[date, date]:
    today = today_date()
    if preset == "今日":
        return today, today
    if preset == "近7天":
        return today - timedelta(days=7), today
    if preset == "近30天":
        return today - timedelta(days=30), today
    if preset == "近90天":
        return today - timedelta(days=90), today
    if preset == "本月":
        return _month_range(0)
    if preset == "上月":
        return _month_range(-1)
    try:
        return date.fromisoformat(str(fallback_start)), date.fromisoformat(str(fallback_end))
    except Exception:
        return today - timedelta(days=30), today


def _normalize_end_blank(s: pd.Series) -> pd.Series:
    text = s.fillna("").astype(str).str.strip().str.lower()
    return text.isin(["", "none", "nan", "nat"])


def _is_cross_day_end_df(df: pd.DataFrame) -> pd.Series:
    """Return True for records that start on one date and finish on another date.

    判斷條件：已結束 + 開始日期與結束日期不同。
    優先使用 start_date/end_date，若欄位缺漏則從時間戳前 10 碼取日期。
    """
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, "index", None))
    index = df.index
    start_date = pd.Series("", index=index)
    end_date = pd.Series("", index=index)
    if "start_date" in df.columns:
        start_date = df["start_date"].fillna("").astype(str).str.strip()
    if "end_date" in df.columns:
        end_date = df["end_date"].fillna("").astype(str).str.strip()
    if "start_timestamp" in df.columns:
        ts_start = df["start_timestamp"].fillna("").astype(str).str.strip().str[:10]
        start_date = start_date.where(start_date.ne(""), ts_start)
    if "end_timestamp" in df.columns:
        ts_end = df["end_timestamp"].fillna("").astype(str).str.strip().str[:10]
        end_date = end_date.where(end_date.ne(""), ts_end)

    if "end_timestamp" in df.columns:
        ended = ~_normalize_end_blank(df["end_timestamp"])
    else:
        ended = end_date.ne("")
    return ended & start_date.ne("") & end_date.ne("") & start_date.ne(end_date)


def _add_cross_day_end_marker(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    marker = _is_cross_day_end_df(out)
    out.insert(0, "跨日結束", marker.map(lambda x: "跨日結束" if bool(x) else ""))
    return out


def _render_history_view_table(view_df: pd.DataFrame, table_key: str = "history_records_view", height: int = 520) -> None:
    """Read-only history table with light cross-day-end highlighting.

    編輯模式仍使用共用 render_table，避免把『跨日結束』標示欄寫回資料庫。
    """
    if view_df is None or view_df.empty:
        st.info("目前沒有資料 / No data")
        return
    display_df = _add_cross_day_end_marker(view_df)
    cross_mask = display_df["跨日結束"].astype(str).eq("跨日結束")

    def highlight_rows(row):
        if bool(cross_mask.loc[row.name]):
            return [
                "background-color: #fff7d6; color: #1f2937; font-weight: 700; border-top: 1px solid #f6c85f; border-bottom: 1px solid #f6c85f;"
                for _ in row
            ]
        return ["" for _ in row]

    st.caption("淺黃色列代表『跨日結束』：開始日期與結束日期不同，且已完成結束。")
    st.dataframe(
        display_df.style.apply(highlight_rows, axis=1),
        use_container_width=True,
        hide_index=True,
        height=height,
        key=f"frame_{table_key}",
    )


def _apply_history_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()

    def in_list(col: str, values: list[str]):
        nonlocal out
        if values and col in out.columns:
            allowed = {str(x).strip() for x in values if str(x).strip()}
            out = out[out[col].fillna("").astype(str).str.strip().isin(allowed)]

    in_list("work_order", filters.get("work_orders", []))
    in_list("part_no", filters.get("part_nos", []))
    in_list("type_name", filters.get("type_names", []))
    in_list("assembly_location", filters.get("assembly_locations", []))
    in_list("process_name", filters.get("process_names", []))
    in_list("employee_id", filters.get("employee_ids", []))
    in_list("employee_name", filters.get("employee_names", []))
    in_list("status", filters.get("statuses", []))

    end_state = str(filters.get("end_state") or "全部")
    if "end_timestamp" in out.columns:
        end_blank = _normalize_end_blank(out["end_timestamp"])
        if end_state == "未結束":
            out = out[end_blank]
        elif end_state == "已結束":
            out = out[~end_blank]

    keyword = str(filters.get("keyword") or "").strip()
    if keyword:
        search_cols = [c for c in ["work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name", "remark", "assembly_location", "status"] if c in out.columns]
        if search_cols:
            mask = pd.Series(False, index=out.index)
            for c in search_cols:
                mask = mask | out[c].fillna("").astype(str).str.contains(keyword, case=False, na=False)
            out = out[mask]

    # Join employee master fields for department/title filtering when available.
    try:
        emp_df = load_employees(active_only=False)
        if not emp_df.empty and "employee_id" in out.columns and "employee_id" in emp_df.columns:
            add_cols = [c for c in ["employee_id", "department", "title"] if c in emp_df.columns]
            if len(add_cols) > 1:
                out = out.merge(emp_df[add_cols].drop_duplicates("employee_id"), on="employee_id", how="left", suffixes=("", "_emp"))
    except Exception:
        pass
    in_list("department", filters.get("departments", []))
    in_list("title", filters.get("titles", []))

    anomaly = str(filters.get("anomaly_filter") or "全部")
    hours = pd.to_numeric(out["work_hours"], errors="coerce") if "work_hours" in out.columns else pd.Series(0, index=out.index)
    if anomaly == "工時 = 0":
        out = out[hours.fillna(0).eq(0)]
    elif anomaly == "工時小於5分鐘":
        out = out[(hours.fillna(0) > 0) & (hours.fillna(0) < (5 / 60))]
    elif anomaly == "工時大於8小時":
        out = out[hours.fillna(0) > 8]
    elif anomaly == "工時大於12小時":
        out = out[hours.fillna(0) > 12]
    elif anomaly == "未按結束":
        if "end_timestamp" in out.columns:
            out = out[_normalize_end_blank(out["end_timestamp"])]
    elif anomaly == "跨日紀錄":
        if "start_date" in out.columns and "end_date" in out.columns:
            start_text = out["start_date"].fillna("").astype(str).str.strip()
            end_text = out["end_date"].fillna("").astype(str).str.strip()
            out = out[start_text.ne("") & end_text.ne("") & start_text.ne(end_text)]
    elif anomaly == "跨日結束":
        out = out[_is_cross_day_end_df(out)]
    elif anomaly == "有開始無結束":
        if "start_timestamp" in out.columns and "end_timestamp" in out.columns:
            out = out[~_normalize_end_blank(out["start_timestamp"]) & _normalize_end_blank(out["end_timestamp"])]
    elif anomaly == "有結束無開始":
        if "start_timestamp" in out.columns and "end_timestamp" in out.columns:
            out = out[_normalize_end_blank(out["start_timestamp"]) & ~_normalize_end_blank(out["end_timestamp"])]

    sort_by = str(filters.get("sort_by") or "ID由新到舊")
    try:
        if sort_by == "ID由新到舊" and "id" in out.columns:
            out = out.sort_values("id", ascending=False)
        elif sort_by == "ID由舊到新" and "id" in out.columns:
            out = out.sort_values("id", ascending=True)
        elif sort_by == "開始時間由新到舊" and "start_timestamp" in out.columns:
            out = out.sort_values("start_timestamp", ascending=False)
        elif sort_by == "開始時間由舊到新" and "start_timestamp" in out.columns:
            out = out.sort_values("start_timestamp", ascending=True)
        elif sort_by == "工時由大到小" and "work_hours" in out.columns:
            out = out.assign(_wh=pd.to_numeric(out["work_hours"], errors="coerce")).sort_values("_wh", ascending=False).drop(columns=["_wh"])
        elif sort_by == "工時由小到大" and "work_hours" in out.columns:
            out = out.assign(_wh=pd.to_numeric(out["work_hours"], errors="coerce")).sort_values("_wh", ascending=True).drop(columns=["_wh"])
        elif sort_by == "製令排序" and "work_order" in out.columns:
            out = out.sort_values(["work_order", "process_name", "employee_id"], ascending=True)
        elif sort_by == "人員排序" and "employee_id" in out.columns:
            out = out.sort_values(["employee_id", "start_timestamp"], ascending=[True, False])
    except Exception:
        pass

    top_n = str(filters.get("top_n") or "全部")
    if top_n.startswith("Top"):
        try:
            n = int(top_n.replace("Top", "").strip())
            out = out.head(n)
        except Exception:
            pass
    try:
        limit = int(filters.get("detail_limit") or 0)
        if limit > 0:
            out = out.head(limit)
    except Exception:
        pass
    return out


def _render_history_filter_panel(base_df: pd.DataFrame, employees: pd.DataFrame, work_orders: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stored = load_history_filters()
    if "history_filters_applied_v216" not in st.session_state:
        st.session_state["history_filters_applied_v216"] = stored
    applied = st.session_state["history_filters_applied_v216"]

    start_default, end_default = _date_range_from_preset(
        applied.get("date_preset", "近30天"),
        applied.get("start_date"),
        applied.get("end_date"),
    )

    with st.expander("🔎 專業篩選 / Professional Filters", expanded=True):
        with st.form("history_professional_filter_form", clear_on_submit=False):
            r1c1, r1c2, r1c3, r1c4 = st.columns([1, 1, 1, 1])
            date_preset = r1c1.selectbox(
                "快速日期",
                ["今日", "近7天", "近30天", "近90天", "本月", "上月", "自訂區間"],
                index=["今日", "近7天", "近30天", "近90天", "本月", "上月", "自訂區間"].index(applied.get("date_preset", "近30天")) if applied.get("date_preset", "近30天") in ["今日", "近7天", "近30天", "近90天", "本月", "上月", "自訂區間"] else 2,
            )
            start_input = r1c2.date_input("開始日期", value=start_default)
            end_input = r1c3.date_input("結束日期", value=end_default)
            detail_limit = r1c4.number_input("明細讀取上限", min_value=50, max_value=50000, value=int(applied.get("detail_limit") or 1000), step=50)

            # Build options from current broad query + master data.
            wo_options = _merge_options(_safe_unique(work_orders, "work_order"), _safe_unique(base_df, "work_order"))
            pn_options = _merge_options(_safe_unique(work_orders, "part_no"), _safe_unique(base_df, "part_no"))
            type_options = _merge_options(_safe_unique(work_orders, "type_name"), _safe_unique(base_df, "type_name"))
            loc_options = _merge_options(_safe_unique(work_orders, "assembly_location"), _safe_unique(base_df, "assembly_location"))
            process_options = _safe_unique(base_df, "process_name")
            emp_id_options = _merge_options(_safe_unique(employees, "employee_id"), _safe_unique(base_df, "employee_id"))
            emp_name_options = _merge_options(_safe_unique(employees, "employee_name"), _safe_unique(base_df, "employee_name"))
            dept_options = _safe_unique(employees, "department")
            title_options = _safe_unique(employees, "title")
            status_options = _safe_unique(base_df, "status")

            r2c1, r2c2, r2c3 = st.columns(3)
            work_orders_selected = r2c1.multiselect("製令", wo_options, default=[x for x in applied.get("work_orders", []) if x in wo_options])
            part_nos = r2c2.multiselect("P/N / 料號", pn_options, default=[x for x in applied.get("part_nos", []) if x in pn_options])
            type_names = r2c3.multiselect("機型", type_options, default=[x for x in applied.get("type_names", []) if x in type_options])

            r3c1, r3c2, r3c3 = st.columns(3)
            assembly_locations = r3c1.multiselect("組立地點", loc_options, default=[x for x in applied.get("assembly_locations", []) if x in loc_options])
            process_names = r3c2.multiselect("工段名稱", process_options, default=[x for x in applied.get("process_names", []) if x in process_options])
            statuses = r3c3.multiselect("狀態", status_options, default=[x for x in applied.get("statuses", []) if x in status_options])

            r4c1, r4c2, r4c3, r4c4 = st.columns(4)
            employee_ids = r4c1.multiselect("工號", emp_id_options, default=[x for x in applied.get("employee_ids", []) if x in emp_id_options])
            employee_names = r4c2.multiselect("姓名", emp_name_options, default=[x for x in applied.get("employee_names", []) if x in emp_name_options])
            departments = r4c3.multiselect("單位", dept_options, default=[x for x in applied.get("departments", []) if x in dept_options])
            titles = r4c4.multiselect("職稱", title_options, default=[x for x in applied.get("titles", []) if x in title_options])

            r5c1, r5c2, r5c3, r5c4 = st.columns(4)
            end_state = r5c1.selectbox("結束狀態", ["全部", "未結束", "已結束"], index=["全部", "未結束", "已結束"].index(applied.get("end_state", "全部")) if applied.get("end_state", "全部") in ["全部", "未結束", "已結束"] else 0)
            anomaly_filter = r5c2.selectbox("異常篩選", ["全部", "工時 = 0", "工時小於5分鐘", "工時大於8小時", "工時大於12小時", "未按結束", "跨日紀錄", "跨日結束", "有開始無結束", "有結束無開始"], index=["全部", "工時 = 0", "工時小於5分鐘", "工時大於8小時", "工時大於12小時", "未按結束", "跨日紀錄", "跨日結束", "有開始無結束", "有結束無開始"].index(applied.get("anomaly_filter", "全部")) if applied.get("anomaly_filter", "全部") in ["全部", "工時 = 0", "工時小於5分鐘", "工時大於8小時", "工時大於12小時", "未按結束", "跨日紀錄", "跨日結束", "有開始無結束", "有結束無開始"] else 0)
            top_n = r5c3.selectbox("Top N", ["全部", "Top 50", "Top 100", "Top 200", "Top 500"], index=["全部", "Top 50", "Top 100", "Top 200", "Top 500"].index(applied.get("top_n", "全部")) if applied.get("top_n", "全部") in ["全部", "Top 50", "Top 100", "Top 200", "Top 500"] else 0)
            sort_by = r5c4.selectbox("排序方式", ["ID由新到舊", "ID由舊到新", "開始時間由新到舊", "開始時間由舊到新", "工時由大到小", "工時由小到大", "製令排序", "人員排序"], index=["ID由新到舊", "ID由舊到新", "開始時間由新到舊", "開始時間由舊到新", "工時由大到小", "工時由小到大", "製令排序", "人員排序"].index(applied.get("sort_by", "ID由新到舊")) if applied.get("sort_by", "ID由新到舊") in ["ID由新到舊", "ID由舊到新", "開始時間由新到舊", "開始時間由舊到新", "工時由大到小", "工時由小到大", "製令排序", "人員排序"] else 0)

            keyword = st.text_input("關鍵字搜尋：製令 / 料號 / 機型 / 工段 / 工號 / 姓名 / 備註", value=applied.get("keyword", ""))
            b1, b2, b3 = st.columns([1.3, 1, 2])
            apply_clicked = b1.form_submit_button("🔎 套用篩選並永久記錄", type="primary", use_container_width=True)
            reset_clicked = b2.form_submit_button("♻️ 恢復預設篩選", use_container_width=True)

        if reset_clicked:
            new_filters = reset_history_filters()
            st.session_state["history_filters_applied_v216"] = new_filters
            st.success("已恢復 02｜歷史紀錄預設篩選。")
            rerun()

        if apply_clicked:
            actual_start, actual_end = _date_range_from_preset(date_preset, str(start_input), str(end_input))
            if date_preset == "自訂區間":
                actual_start, actual_end = start_input, end_input
            new_filters = {
                "date_preset": date_preset,
                "start_date": str(actual_start),
                "end_date": str(actual_end),
                "work_orders": work_orders_selected,
                "part_nos": part_nos,
                "type_names": type_names,
                "assembly_locations": assembly_locations,
                "process_names": process_names,
                "employee_ids": employee_ids,
                "employee_names": employee_names,
                "departments": departments,
                "titles": titles,
                "statuses": statuses,
                "end_state": end_state,
                "anomaly_filter": anomaly_filter,
                "keyword": keyword,
                "top_n": top_n,
                "sort_by": sort_by,
                "detail_limit": int(detail_limit),
            }
            saved = save_history_filters(new_filters)
            st.session_state["history_filters_applied_v216"] = saved
            st.success("已套用並永久記錄 02｜歷史紀錄篩選條件。")
            rerun()

    applied = st.session_state["history_filters_applied_v216"]
    filtered = _apply_history_filters(base_df, applied)
    return filtered, applied


employees = load_employees(active_only=False)
work_orders = load_work_orders(active_only=False)

# V2.16：02 歷史紀錄改為專業篩選。先依日期範圍載入，再在畫面層套用多條件篩選；
# 篩選條件只有按「套用篩選並永久記錄」才寫入永久檔。
_history_filter_seed = load_history_filters()
_seed_start, _seed_end = _date_range_from_preset(
    _history_filter_seed.get("date_preset", "近30天"),
    _history_filter_seed.get("start_date"),
    _history_filter_seed.get("end_date"),
)
base_df = load_records(str(_seed_start), str(_seed_end), None, None)
df, history_filters = _render_history_filter_panel(base_df, employees, work_orders)

start = history_filters.get("start_date", str(_seed_start))
end = history_filters.get("end_date", str(_seed_end))

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("篩選筆數 / Records", f"{len(df):,}")
m2.metric("總工時 / Total Time", hours_to_hms(df['work_hours'].sum()) if not df.empty and 'work_hours' in df.columns else "00:00:00")
if not df.empty and 'end_timestamp' in df.columns:
    _end_blank = _normalize_end_blank(df['end_timestamp'])
    m3.metric("未結束 / Open", f"{_end_blank.sum():,}")
    m4.metric("已結束 / Closed", f"{(~_end_blank).sum():,}")
else:
    m3.metric("未結束 / Open", "0")
    m4.metric("已結束 / Closed", "0")
m5.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}" if not df.empty and 'employee_id' in df.columns else "0")
m6.metric("製令數 / W/O", f"{df['work_order'].nunique():,}" if not df.empty and 'work_order' in df.columns else "0")

can_edit = check_permission("02_history", "can_edit")
can_delete = check_permission("02_history", "can_delete")

tab1, tab2, tab3 = st.tabs(["歷史明細編輯", "Excel 匯入", "貼上資料"])

with tab1:
    st.subheader("歷史明細編輯 / Editable History")
    if not can_edit:
        st.info("目前帳號只有查詢權限；若需修改或刪除歷史紀錄，請由管理員在權限管理開放 02 歷史紀錄的編輯/刪除權限。")
        _render_history_view_table(df, "history_records", height=520)
    else:
        edit_key = "history_edit_enabled"
        if edit_key not in st.session_state:
            st.session_state[edit_key] = False
        ec1, ec2, ec3 = st.columns([1, 1, 2])
        if ec1.button("✏️ 啟動編輯 / Enable Edit", use_container_width=True, key="history_enable_edit"):
            st.session_state[edit_key] = True
            rerun()
        if ec2.button("🔒 停止編輯 / Stop Edit", use_container_width=True, key="history_stop_edit"):
            st.session_state[edit_key] = False
            rerun()
        ec3.info("編輯啟動後可修改資料；勾選『刪除』後可整列刪除。刪除需具備 can_delete 權限。")

        if st.session_state[edit_key]:
            edit_df = df.copy()
            if "刪除" not in edit_df.columns:
                edit_df.insert(0, "刪除", False)
            st.info("V1.97：表格內輸入或勾選不會立即重算；選擇動作後按確認執行才會儲存、重算或刪除。")
            with st.form("history_records_commit_form", clear_on_submit=False):
                edited = render_table(edit_df, "history_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at"], key="history_editor", height=560)
                history_action = st.radio(
                    "確認後執行動作",
                    ["儲存編輯", "重新計算勾選紀錄工時", "刪除勾選整列紀錄"],
                    horizontal=True,
                    key="history_action",
                )
                submitted_history = st.form_submit_button("✅ 確認執行 / Confirm", type="primary", use_container_width=True)

            if submitted_history and edited is not None:
                try:
                    delete_rows = edited[edited["刪除"].astype(bool)] if "刪除" in edited.columns else pd.DataFrame()
                    delete_ids = [int(x) for x in delete_rows["id"].dropna().tolist()]
                except Exception:
                    delete_ids = []

                if history_action == "儲存編輯":
                    save_df = edited.drop(columns=["刪除"], errors="ignore")
                    count = save_time_records(save_df)
                    st.success(f"已儲存 {count} 筆歷史紀錄。")
                    rerun()
                elif history_action == "重新計算勾選紀錄工時":
                    if not delete_ids:
                        st.warning("請先在『刪除』勾選欄勾選要重新計算的紀錄，再按確認執行。")
                    else:
                        count = recalculate_time_records(delete_ids)
                        st.success(f"已重新計算 {count} 筆工時。")
                        rerun()
                else:
                    if not can_delete:
                        st.error("權限不足：你沒有刪除歷史紀錄權限。")
                    elif not delete_ids:
                        st.warning("請先在『刪除』勾選欄勾選要刪除的紀錄，再按確認執行。")
                    else:
                        count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")
                        st.success(f"已刪除 {count} 筆歷史紀錄。")
                        rerun()
        else:
            _render_history_view_table(df, "history_records", height=520)

    if not df.empty:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="歷史紀錄")
        st.download_button("下載 Excel / Export Excel", data=bio.getvalue(), file_name=f"SPT_歷史紀錄_{start}_{end}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    if not can_edit:
        st.warning("目前帳號沒有 02 歷史紀錄編輯權限，不能匯入歷史資料。")
    else:
        st.download_button(
            "下載歷史紀錄匯入範本 / Download Template",
            data=_download_history_template(),
            file_name="SPT_歷史紀錄匯入範本.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        uploaded = st.file_uploader("上傳歷史紀錄 Excel", type=["xlsx", "xlsm", "xls"], key="history_excel_upload_v197")
        recalc_excel = st.checkbox("匯入時依 13｜系統設定休息時間重新計算工時", value=True, key="history_excel_recalc_v197")
        if uploaded is not None:
            try:
                source_df = pd.read_excel(uploaded)
                parsed, warnings = parse_history_dataframe(source_df)
                st.caption("原始 Excel 預覽 / Source Preview")
                st.dataframe(source_df.head(30), use_container_width=True, height=220)
                for msg in warnings:
                    st.warning(msg)
                if parsed.empty:
                    st.error("解析後沒有可匯入資料。請確認至少包含：工號、製令、工段、開始時間。")
                else:
                    st.success(f"已解析 {len(parsed)} 筆歷史工時資料。")
                    st.dataframe(parsed, use_container_width=True, height=360)
                    if st.button("💾 確認匯入 Excel 歷史紀錄 / Import Excel History", type="primary", use_container_width=True, key="history_excel_import_save_v197"):
                        result = import_time_records(parsed, recalc=recalc_excel, source="history_excel_import")
                        st.success(f"匯入完成：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。")
                        for msg in result.get("errors", [])[:10]:
                            st.warning(msg)
                        rerun()
            except Exception as exc:
                st.error(f"Excel 匯入失敗：{exc}")

with tab3:
    st.subheader("貼上資料 / Paste Data")
    if not can_edit:
        st.warning("目前帳號沒有 02 歷史紀錄編輯權限，不能貼上匯入歷史資料。")
    else:
        st.caption("支援從 Excel 複製整批資料貼上。建議包含標題列：狀態、製令、P/N、機型、工段名稱、工號、姓名、開始時間戳、結束時間戳、備註、組立地點。")
        raw = st.text_area("貼上 Excel 複製的歷史紀錄資料", height=260, key=HISTORY_PASTE_RAW_KEY)
        recalc_paste = st.checkbox("貼上匯入時依 13｜系統設定休息時間重新計算工時", value=True, key="history_paste_recalc_v197")
        if raw.strip():
            parsed, has_header, warnings = parse_pasted_history(raw)
            if has_header:
                st.success("已偵測到標題列，並依標題列自動對應欄位。")
            for msg in warnings:
                st.warning(msg)
            if parsed.empty:
                st.error("解析後沒有可匯入資料。請確認至少包含：工號、製令、工段、開始時間。")
            else:
                st.success(f"已解析 {len(parsed)} 筆歷史工時資料。")
                st.dataframe(parsed, use_container_width=True, height=360)
                if st.button("💾 直接儲存貼上歷史紀錄 / Save Pasted History", type="primary", use_container_width=True, key="history_paste_save_v197"):
                    result = import_time_records(parsed, recalc=recalc_paste, source="history_paste_import")
                    st.success(f"貼上資料已匯入：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。")
                    for msg in result.get("errors", [])[:10]:
                        st.warning(msg)
                    rerun()
        else:
            st.info("請先貼上 Excel 資料。")
