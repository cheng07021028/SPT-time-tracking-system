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
from services.table_ui_service import render_table, label_for, render_width_settings
from services.duration_service import hours_to_hms
from services.history_filter_service import load_history_filters, save_history_filters, reset_history_filters

st.set_page_config(page_title="02. 歷史紀錄", page_icon="⧠", layout="wide")
apply_theme()
require_module_access("02_history")
render_header("02｜歷史紀錄", "完整工時明細查詢、資料編輯、刪除、重新計算、Excel 匯入、貼上資料與 Excel 匯出")

HISTORY_IMPORT_PREVIEW_KEY = "v197_history_import_preview"
HISTORY_PASTE_RAW_KEY = "v197_history_paste_raw"
HISTORY_RESULT_MESSAGES_KEY = "v238_history_result_messages"


def _add_history_result(level: str, message: str, *, append: bool = True) -> None:
    """Queue one-time action messages without restoring the removed status panel."""
    item = {"level": str(level or "info"), "message": str(message or "").strip()}
    if not item["message"]:
        return
    msgs = list(st.session_state.get(HISTORY_RESULT_MESSAGES_KEY, [])) if append else []
    msgs.append(item)
    st.session_state[HISTORY_RESULT_MESSAGES_KEY] = msgs[-5:]


def _show_history_results() -> None:
    """Show queued messages once, then clear them automatically.

    使用者已要求不要再顯示固定保留的結果面板，
    因此這裡只保留一次性成功/警告/錯誤提示，不再產生保留面板與清除按鈕。
    """
    msgs = list(st.session_state.pop(HISTORY_RESULT_MESSAGES_KEY, []) or [])
    for msg in msgs:
        level = msg.get("level", "info")
        text = msg.get("message", "")
        if level == "success":
            st.success(text)
        elif level == "error":
            st.error(text)
        elif level == "warning":
            st.warning(text)
        else:
            st.info(text)


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


_show_history_results()


def _normalize_text(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v)
    # Excel / browser paste may contain full-width spaces, NBSP, zero-width chars.
    # Keep internal spaces for model names, but normalize invisible padding so import
    # will not fail just because cells contain spaces.
    text = (text.replace("\u3000", " ")
                .replace("\xa0", " ")
                .replace("\u200b", "")
                .replace("\ufeff", ""))
    return text.strip()


def _normalize_header_name(v) -> str:
    text = _normalize_text(v).lower()
    # Remove separators and hidden characters.  This makes headers such as
    # "工號 / Employee ID", " 工號　/ Employee ID " and duplicated bilingual
    # headers match the same alias.
    for ch in [" ", "　", "\t", "\n", "\r", "_", "-", "－", "—", "/", "／", "\\", ".", "．", "：", ":", "（", "）", "(", ")", "[", "]", "【", "】", "\u200b", "\ufeff"]:
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

# No-header paste layouts supported by this page.
# 1) Extended Excel order used by manufacturing history exports:
#    狀態、製令、P/N、機型、工段、工號、姓名、開始動作、開始時間戳、結束動作、結束時間戳、開始日期、開始時間、結束日期、結束時間、工時小計、備註、組立地點
# 2) Legacy compact order:
#    狀態、製令、P/N、機型、工段、工號、姓名、開始時間戳、結束時間戳、備註、組立地點
DEFAULT_PASTE_ORDER_EXTENDED = [
    "status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name",
    "start_action", "start_timestamp", "end_action", "end_timestamp",
    "start_date", "start_time", "end_date", "end_time", "work_hours", "remark", "assembly_location",
]

DEFAULT_PASTE_ORDER_COMPACT = [
    "status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name",
    "start_timestamp", "end_timestamp", "remark", "assembly_location",
]


def _guess_no_header_order(width: int) -> list[str]:
    if width >= 15:
        return DEFAULT_PASTE_ORDER_EXTENDED
    return DEFAULT_PASTE_ORDER_COMPACT


def _merge_date_time_if_possible(d, t) -> str:
    d_text = _normalize_text(d)
    t_text = _normalize_text(t)
    if not d_text:
        return ""
    if t_text:
        # Excel sometimes pastes time as 1900-01-00 09:45:00. Keep only the final HH:MM[:SS].
        if " " in t_text:
            t_text = t_text.split()[-1]
        return f"{d_text[:10]} {t_text}".strip()
    return d_text


def _postprocess_import_rows(parsed: pd.DataFrame) -> pd.DataFrame:
    if parsed is None or parsed.empty:
        return parsed
    parsed = parsed.copy()
    for c in HISTORY_COLS:
        if c not in parsed.columns:
            parsed[c] = ""

    # When pasted data includes separate start/end date + time columns, build timestamps for import.
    start_blank = parsed["start_timestamp"].map(_normalize_text).eq("")
    parsed.loc[start_blank, "start_timestamp"] = [
        _merge_date_time_if_possible(d, t)
        for d, t in zip(parsed.loc[start_blank, "start_date"], parsed.loc[start_blank, "start_time"])
    ]
    end_blank = parsed["end_timestamp"].map(_normalize_text).eq("")
    parsed.loc[end_blank, "end_timestamp"] = [
        _merge_date_time_if_possible(d, t)
        for d, t in zip(parsed.loc[end_blank, "end_date"], parsed.loc[end_blank, "end_time"])
    ]

    # If timestamp exists but date/time columns are empty, split for preview and downstream consistency.
    for prefix in ["start", "end"]:
        ts_col = f"{prefix}_timestamp"
        d_col = f"{prefix}_date"
        t_col = f"{prefix}_time"
        d_blank = parsed[d_col].map(_normalize_text).eq("")
        t_blank = parsed[t_col].map(_normalize_text).eq("")
        ts_text = parsed[ts_col].map(_normalize_text)
        parsed.loc[d_blank & ts_text.ne(""), d_col] = ts_text[d_blank & ts_text.ne("")].str[:10]
        parsed.loc[t_blank & ts_text.str.len().ge(16), t_col] = ts_text[t_blank & ts_text.str.len().ge(16)].str[11:19]

    return parsed


def _find_col(source: pd.DataFrame, aliases: list[str]):
    """Find a source column by bilingual header aliases without false short matches.

    修正 V2.37：Excel 匯入範本的標題可能是
    「工號 / Employee ID 工號 / Employee ID」這種合併/重複標題。
    舊版用 alias in norm_col，會把 employee_id 內的短字串 id 誤判成 ID 欄，
    導致 ID 欄變成 B002、SPT193，正式匯入時欄位錯位。
    """
    norm_to_col = {_normalize_header_name(c): c for c in source.columns}
    norm_aliases = [_normalize_header_name(a) for a in aliases if _normalize_header_name(a)]

    # 1) Exact match is always safest.
    for alias in norm_aliases:
        if alias in norm_to_col:
            return norm_to_col[alias]

    # 2) Token-aware matching. Avoid very short aliases such as id/pn/wo/name
    #    unless they are an exact match above.
    unsafe_short_aliases = {"id", "pn", "wo", "mo", "key", "name"}
    for alias in norm_aliases:
        if alias in unsafe_short_aliases or len(alias) < 3:
            continue
        for norm_col, real_col in norm_to_col.items():
            if alias in norm_col:
                return real_col

    # 3) Fallback: allow source header inside a long alias only when the source
    #    header itself is meaningful enough.
    for alias in norm_aliases:
        for norm_col, real_col in norm_to_col.items():
            if len(norm_col) >= 3 and norm_col not in unsafe_short_aliases and norm_col in alias:
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
    """Return a column-sized Series.

    Pandas cannot build a DataFrame from an all-scalar dict.
    Paste/Excel imports often have no recognizable headers, so most
    fields fall back to defaults. Always returning a Series keeps the
    parser stable and lets the later positional parser handle no-header
    paste data.
    """
    col = _find_col(source, HISTORY_ALIAS_GROUPS[target])
    if col is None:
        return pd.Series([default] * len(source), index=source.index)
    picked = source[col]
    if not isinstance(picked, pd.Series):
        return pd.Series([default] * len(source), index=source.index)
    return picked.reset_index(drop=True)


def _ensure_history_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in HISTORY_COLS:
        if c not in df.columns:
            if c == "is_group_work":
                df[c] = False
            else:
                df[c] = ""
    return df[HISTORY_COLS].copy()


def _prepare_source_dataframe(source: pd.DataFrame) -> pd.DataFrame:
    """Normalize uploaded/pasted Excel tables before column matching.

    Fixes cases where the Excel sheet has blank header cells, duplicated bilingual
    headers, leading/trailing spaces, or an extra header row after pd.read_excel.
    It does not remove meaningful spaces inside values such as model names.
    """
    if source is None:
        return pd.DataFrame()
    df = source.copy()
    df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if df.empty:
        return df

    # Clean column names but preserve display text; make duplicates unique.
    new_cols = []
    seen = {}
    for c in df.columns:
        name = _normalize_text(c)
        if not name or name.lower().startswith("unnamed"):
            name = f"col_{len(new_cols)+1}"
        base = name
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count:
            name = f"{base}__{count+1}"
        new_cols.append(name)
    df.columns = new_cols

    # If pd.read_excel read a blank/incorrect header but first row looks like a
    # real header, promote the first row.
    try:
        first = [_normalize_text(x) for x in df.iloc[0].tolist()]
        if _row_looks_like_header(first):
            width = len(first)
            body = df.iloc[1:].reset_index(drop=True)
            cols = []
            seen = {}
            for i, c in enumerate(first):
                name = _normalize_text(c) or f"col_{i+1}"
                base = name
                count = seen.get(base, 0)
                seen[base] = count + 1
                if count:
                    name = f"{base}__{count+1}"
                cols.append(name)
            body = body.iloc[:, :width]
            body.columns = cols
            df = body
    except Exception:
        pass

    # Clean object values for matching/import; keep internal normal spaces.
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(_normalize_text)
    return df


def parse_history_dataframe(source: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if source is None or source.empty:
        return _ensure_history_cols(pd.DataFrame()), ["來源資料為空。"]

    source = _prepare_source_dataframe(source)
    if source.empty:
        return _ensure_history_cols(pd.DataFrame()), ["來源資料沒有有效列。"]

    data = {}
    for c in HISTORY_COLS:
        picked = _pick_series(source, c, default="")
        data[c] = picked
    parsed = pd.DataFrame(data)

    # If no recognizable headers were found, preserve the original columns by position.
    if parsed[["work_order", "process_name", "employee_id", "start_timestamp"]].astype(str).replace("", pd.NA).isna().all().all():
        rows = source.fillna("").astype(str).values.tolist()
        width = max((len(r) for r in rows), default=0)
        order = _guess_no_header_order(width)
        if order is DEFAULT_PASTE_ORDER_EXTENDED:
            warnings.append("未偵測到可辨識標題，已依擴充順序解析：狀態、製令、P/N、機型、工段、工號、姓名、開始動作、開始時間戳、結束動作、結束時間戳、開始日期、開始時間、結束日期、結束時間、工時小計、備註、組立地點。")
        else:
            warnings.append("未偵測到可辨識標題，已依預設順序解析：狀態、製令、P/N、機型、工段、工號、姓名、開始時間戳、結束時間戳、備註、組立地點。")
        normalized = []
        for row in rows:
            item = {c: "" for c in HISTORY_COLS}
            for idx, col_name in enumerate(order):
                if idx < len(row):
                    item[col_name] = row[idx]
            normalized.append(item)
        parsed = pd.DataFrame(normalized)

    parsed = _postprocess_import_rows(parsed)

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

def _date_from_any_value(value):
    text = _normalize_text(value)
    if not text:
        return None
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.date()
    except Exception:
        pass
    try:
        dt = pd.to_datetime(text.replace("/", "-")[:10], errors="coerce")
        if not pd.isna(dt):
            return dt.date()
    except Exception:
        pass
    return None


def _extract_import_date_range(import_df: pd.DataFrame):
    """Return min/max dates contained in parsed import rows.

    Excel / paste imports are often outside the current 02 filter range.  The
    records were written successfully, but the page still showed only the old
    filtered range, which looked like only one row was imported.  This helper
    finds the real import date range so the page can switch the filter after a
    successful import and show all newly imported rows immediately.
    """
    dates = []
    if import_df is None or import_df.empty:
        return None, None
    for _, row in import_df.iterrows():
        for col in ["start_date", "end_date", "start_timestamp", "end_timestamp"]:
            if col in import_df.columns:
                d = _date_from_any_value(row.get(col))
                if d is not None:
                    dates.append(d)
    if not dates:
        return None, None
    return min(dates), max(dates)


def _focus_filter_to_import_rows(import_df: pd.DataFrame, label: str = "匯入資料") -> None:
    """Persistently switch 02 filter to the imported date range.

    This does not change imported data.  It only updates the visible filter so
    users can immediately verify all rows just imported, even when the import
    file contains old dates such as 2026-02 while the default filter is 近30天.
    """
    start_d, end_d = _extract_import_date_range(import_df)
    if start_d is None or end_d is None:
        _add_history_result("warning", f"{label}已寫入，但系統無法判斷日期範圍；請手動調整上方歷史篩選日期。")
        return
    new_filters = load_history_filters()
    new_filters.update({
        "date_preset": "自訂區間",
        "start_date": str(start_d),
        "end_date": str(end_d),
        "work_orders": [],
        "part_nos": [],
        "type_names": [],
        "assembly_locations": [],
        "process_names": [],
        "employee_ids": [],
        "employee_names": [],
        "departments": [],
        "titles": [],
        "statuses": [],
        "end_state": "全部",
        "anomaly_filter": "全部",
        "keyword": "",
        "top_n": "全部",
        "sort_by": "開始時間由新到舊",
        "detail_limit": max(int(new_filters.get("detail_limit") or 1000), min(max(len(import_df) + 50, 1000), 50000)),
    })
    saved = save_history_filters(new_filters)
    st.session_state["history_filters_applied_v216"] = saved
    _add_history_result("info", f"已自動切換 02｜歷史紀錄篩選到{label}日期範圍：{start_d} ~ {end_d}，方便確認全部匯入結果。")



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
    """Normalize blank-like end values.

    SQLite / CSV / Excel 讀回來時，空值可能是 None、nan、NaT、空白字串；
    這裡統一判斷，避免跨日結束篩選漏判。
    """
    text = s.fillna("").astype(str).str.strip().str.lower()
    return text.isin(["", "none", "nan", "nat", "null"])


def _date_text_from_series(series: pd.Series, index) -> pd.Series:
    """Convert mixed date strings / timestamps into yyyy-mm-dd text.

    支援：
    - 2026-05-17
    - 2026/5/17
    - 2026-05-17 00:00:00
    - pandas Timestamp
    - Excel / CSV 讀回來的字串日期
    """
    if series is None:
        return pd.Series("", index=index)
    raw = series.reindex(index).fillna("").astype(str).str.strip()
    blank = raw.str.lower().isin(["", "none", "nan", "nat", "null"])
    parsed = pd.to_datetime(raw.where(~blank, ""), errors="coerce")
    out = parsed.dt.strftime("%Y-%m-%d").fillna("")

    # Fallback：pd.to_datetime 無法解析時，抓字串內第一個 yyyy/mm/dd 或 yyyy-mm-dd。
    fallback = raw.str.extract(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", expand=True)
    fallback_text = pd.Series("", index=index)
    matched = fallback.notna().all(axis=1)
    if matched.any():
        fallback_text.loc[matched] = (
            fallback.loc[matched, 0].astype(str)
            + "-"
            + fallback.loc[matched, 1].astype(int).astype(str).str.zfill(2)
            + "-"
            + fallback.loc[matched, 2].astype(int).astype(str).str.zfill(2)
        )
    out = out.where(out.ne(""), fallback_text)
    return out.fillna("")


def _history_start_end_dates(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return normalized start/end date series.

    優先順序：
    1. start_date / end_date
    2. start_timestamp / end_timestamp

    修正 V2.20 問題：過去直接用字串前 10 碼，遇到 2026/5/17、
    Timestamp、或日期欄帶時間時，跨日紀錄 / 跨日結束可能篩不出來。
    """
    index = df.index
    start_date = pd.Series("", index=index)
    end_date = pd.Series("", index=index)

    if "start_date" in df.columns:
        start_date = _date_text_from_series(df["start_date"], index)
    if "end_date" in df.columns:
        end_date = _date_text_from_series(df["end_date"], index)

    if "start_timestamp" in df.columns:
        ts_start = _date_text_from_series(df["start_timestamp"], index)
        start_date = start_date.where(start_date.ne(""), ts_start)
    if "end_timestamp" in df.columns:
        ts_end = _date_text_from_series(df["end_timestamp"], index)
        end_date = end_date.where(end_date.ne(""), ts_end)

    return start_date.fillna(""), end_date.fillna("")


def _is_cross_day_record_df(df: pd.DataFrame) -> pd.Series:
    """Return True when start date and end date are different.

    用於『跨日紀錄』：只要開始日期與結束日期不同就列出。
    """
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, "index", None))
    start_date, end_date = _history_start_end_dates(df)
    return start_date.ne("") & end_date.ne("") & start_date.ne(end_date)



def _duration_series_to_hours(series: pd.Series, index=None) -> pd.Series:
    """Convert work_hours values to decimal hours.

    支援資料格式：
    - 1.5 / "1.5"：視為小時
    - "00:03:36"、"12:30:00"：HH:MM:SS
    - "1:30"：HH:MM
    - "0 days 01:02:03" / pandas timedelta 字串
    - "1時2分3秒"、"90分"
    
    修正異常篩選原本用 pd.to_numeric，導致 00:03:36 全部變 NaN/0 的問題。
    """
    if index is None:
        index = getattr(series, "index", None)
    if series is None:
        return pd.Series(0.0, index=index)
    raw = series.reindex(index) if index is not None else series
    out = pd.Series(0.0, index=raw.index, dtype="float64")

    # Numeric values already represent hours in this project.
    numeric = pd.to_numeric(raw, errors="coerce")
    numeric_mask = numeric.notna()
    out.loc[numeric_mask] = numeric.loc[numeric_mask].astype(float)

    text = raw.fillna("").astype(str).str.strip()
    blank = text.str.lower().isin(["", "none", "nan", "nat", "null"])

    def parse_one(s: str) -> float:
        s = str(s).strip()
        if not s or s.lower() in ["none", "nan", "nat", "null"]:
            return 0.0
        # Pure numeric string means hours.
        try:
            return float(s)
        except Exception:
            pass

        # Chinese duration text.
        try:
            h = re.search(r"(\d+(?:\.\d+)?)\s*(?:時|小時|hr|hrs|hour|hours)", s, flags=re.I)
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分|分鐘|min|mins|minute|minutes)", s, flags=re.I)
            sec = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|sec|secs|second|seconds)", s, flags=re.I)
            if h or m or sec:
                return (float(h.group(1)) if h else 0.0) + (float(m.group(1)) / 60 if m else 0.0) + (float(sec.group(1)) / 3600 if sec else 0.0)
        except Exception:
            pass

        # HH:MM:SS or HH:MM.
        if ":" in s:
            try:
                # Strip optional day prefix like "0 days 01:02:03".
                day_hours = 0.0
                dm = re.search(r"(\d+)\s+days?\s+", s, flags=re.I)
                if dm:
                    day_hours = int(dm.group(1)) * 24.0
                    s2 = re.sub(r"\d+\s+days?\s+", "", s, flags=re.I).strip()
                else:
                    s2 = s
                parts = [float(x) for x in s2.split(":") if str(x).strip() != ""]
                if len(parts) == 3:
                    return day_hours + parts[0] + parts[1] / 60 + parts[2] / 3600
                if len(parts) == 2:
                    return day_hours + parts[0] + parts[1] / 60
            except Exception:
                pass

        try:
            td = pd.to_timedelta(s, errors="coerce")
            if pd.notna(td):
                return float(td.total_seconds()) / 3600
        except Exception:
            pass
        return 0.0

    text_mask = ~blank & ~numeric_mask
    if text_mask.any():
        out.loc[text_mask] = text.loc[text_mask].map(parse_one).astype(float)
    return out.fillna(0.0)


def _has_end_info_df(df: pd.DataFrame) -> pd.Series:
    """Robust ended-record detection for filters.

    過去只看 end_timestamp，若歷史資料只有 end_date/end_time/status/work_hours，
    『已結束』『未按結束』『有開始無結束』會判斷錯。
    """
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, "index", None))
    ended = pd.Series(False, index=df.index)
    for col in ["end_timestamp", "end_date", "end_time"]:
        if col in df.columns:
            ended = ended | (~_normalize_end_blank(df[col]))
    if "status" in df.columns:
        status_text = df["status"].fillna("").astype(str).str.strip().str.lower()
        running_words = {"", "作業中", "進行中", "running", "active", "in progress", "open"}
        ended = ended | (~status_text.isin({x.lower() for x in running_words}))
    if "work_hours" in df.columns:
        ended = ended | _duration_series_to_hours(df["work_hours"], df.index).gt(0)
    return ended.fillna(False)


def _has_start_info_df(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, "index", None))
    started = pd.Series(False, index=df.index)
    for col in ["start_timestamp", "start_date", "start_time"]:
        if col in df.columns:
            started = started | (~_normalize_end_blank(df[col]))
    return started.fillna(False)

def _is_cross_day_end_df(df: pd.DataFrame) -> pd.Series:
    """Return True for records that start on one date and finish on another date.

    用於『跨日結束』：
    - 開始日期與結束日期不同
    - 且有結束資訊（end_date 或 end_timestamp）

    不再只靠 end_timestamp，避免歷史資料只有 end_date/end_time 時漏判。
    """
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, "index", None))
    cross_day = _is_cross_day_record_df(df)
    ended = _has_end_info_df(df)
    return cross_day & ended


def _add_cross_day_end_marker(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    marker = _is_cross_day_end_df(out)
    out.insert(0, "跨日結束", marker.map(lambda x: "跨日結束" if bool(x) else ""))
    return out


# V110：歷史明細編輯也要能明顯看出「開始時間戳 / 結束時間戳不同日期」。
# Streamlit data_editor 不支援像 st.dataframe Styler 那樣逐列上色，
# 因此在可編輯表格內增加唯讀提醒欄，並在表格上方顯示淺黃色框選預覽。
# 儲存、重算、刪除前會把這些顯示欄位移除，不會寫回權威檔。
HISTORY_CROSS_DAY_ALERT_COL = "跨日提醒 / Cross Day Alert"
HISTORY_CROSS_DAY_RANGE_COL = "跨日日期 / Cross Day Date"
HISTORY_CROSS_DAY_DISPLAY_COLS = [HISTORY_CROSS_DAY_ALERT_COL, HISTORY_CROSS_DAY_RANGE_COL, "跨日結束"]


def _with_history_cross_day_edit_marker(df: pd.DataFrame) -> pd.DataFrame:
    """Add read-only cross-day alert columns for Editable History."""
    out = df.copy()
    if out.empty:
        return out
    for col in HISTORY_CROSS_DAY_DISPLAY_COLS:
        out = out.drop(columns=[col], errors="ignore")
    marker = _is_cross_day_end_df(out)
    start_date, end_date = _history_start_end_dates(out)
    alert_text = marker.map(lambda x: "⚠ 跨日結束｜請確認是否昨天忘記按結束" if bool(x) else "")
    range_text = [f"{s} → {e}" if bool(m) else "" for s, e, m in zip(start_date, end_date, marker)]
    out.insert(0, HISTORY_CROSS_DAY_ALERT_COL, alert_text)
    out.insert(1, HISTORY_CROSS_DAY_RANGE_COL, range_text)
    return out


def _strip_history_cross_day_display_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Remove display-only cross-day columns before saving/recalculating/deleting."""
    if df is None:
        return df
    return df.drop(columns=HISTORY_CROSS_DAY_DISPLAY_COLS, errors="ignore")


def _render_cross_day_edit_notice(edit_df: pd.DataFrame) -> None:
    """Show a light framed preview for cross-day-ended rows in edit mode."""
    if edit_df is None or edit_df.empty:
        return
    mask = _is_cross_day_end_df(edit_df)
    count = int(mask.sum()) if mask is not None else 0
    if count <= 0:
        return
    st.warning(f"偵測到 {count} 筆『開始時間戳與結束時間戳不同日期』紀錄，可能是昨天忘記按結束。下方表格已用『⚠ 跨日提醒』欄標示。")
    preview_cols = [c for c in ["id", "employee_id", "employee_name", "work_order", "process_name", "start_timestamp", "end_timestamp", "work_hours"] if c in edit_df.columns]
    if not preview_cols:
        return
    preview = edit_df.loc[mask, preview_cols].copy()
    if "work_hours" in preview.columns:
        preview["work_hours"] = preview["work_hours"].map(hours_to_hms)

    def _highlight_cross_day_rows(row):
        return [
            "background-color: #fff7d6; color: #1f2937; font-weight: 700; border: 1px solid #f6c85f;"
            for _ in row
        ]

    st.caption("淺黃色框選預覽：開始日期與結束日期不同，且已有結束資訊。")
    st.dataframe(
        preview.rename(columns={c: label_for(str(c)) for c in preview.columns}).style.apply(_highlight_cross_day_rows, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(260, 72 + max(count, 1) * 34),
        key="frame_history_cross_day_edit_preview_v110",
    )


def _prepare_history_display_df(view_df: pd.DataFrame, *, include_action_cols: bool = False, delete_ids: set[int] | None = None, recalc_ids: set[int] | None = None) -> pd.DataFrame:
    """Build one canonical 02 history table shape for view/edit/width settings.

    V133：修正啟動編輯前後顯示內容不同。
    未啟用編輯、啟用編輯與欄寬設定都先套用同一份跨日提醒欄位，
    編輯模式才額外插入「刪除 / Delete」「重算 / Recalc」兩欄。
    """
    out = view_df.copy() if isinstance(view_df, pd.DataFrame) else pd.DataFrame()
    if out.empty:
        return out
    out = out.drop(columns=["刪除", "重算", "刪除 / Delete", "重算 / Recalc"], errors="ignore")
    out = _with_history_cross_day_edit_marker(out)
    if include_action_cols:
        delete_ids = delete_ids or set()
        recalc_ids = recalc_ids or set()

        def _id_in_state(x, id_set: set[int]) -> bool:
            try:
                return int(float(str(x).strip())) in id_set
            except Exception:
                return False

        out.insert(0, "刪除 / Delete", out["id"].map(lambda x: _id_in_state(x, delete_ids)) if "id" in out.columns else False)
        out.insert(1, "重算 / Recalc", out["id"].map(lambda x: _id_in_state(x, recalc_ids)) if "id" in out.columns else False)
    return out


def _render_history_view_table(view_df: pd.DataFrame, table_key: str = "history_records", height: int = 520) -> None:
    """Read-only history table using the same table engine/settings as edit mode.

    V133：改用 render_table + history_records 同一個權威欄寬/欄位順序設定，
    避免未啟用編輯與啟用編輯時欄位內容、順序、寬度看起來不同。
    """
    if view_df is None or view_df.empty:
        st.info("目前沒有資料 / No data")
        return
    display_df = _prepare_history_display_df(view_df, include_action_cols=False)
    st.caption("跨日結束會以『⚠ 跨日提醒』與『跨日日期』欄提示；表格欄寬/欄位順序與編輯模式共用同一份權威設定。")
    render_table(
        display_df,
        table_key,
        editable=False,
        height=height,
        show_width_settings=False,  # V145: page already has one dedicated history width setting block.
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
    ended_mask = _has_end_info_df(out)
    if end_state == "未結束":
        out = out[~ended_mask]
    elif end_state == "已結束":
        out = out[ended_mask]

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
    hours = _duration_series_to_hours(out["work_hours"], out.index) if "work_hours" in out.columns else pd.Series(0.0, index=out.index)
    ended_mask = _has_end_info_df(out)
    started_mask = _has_start_info_df(out)
    if anomaly == "工時 = 0":
        out = out[hours.eq(0)]
    elif anomaly == "工時小於5分鐘":
        out = out[hours.gt(0) & hours.lt(5 / 60)]
    elif anomaly == "工時大於8小時":
        out = out[hours.gt(8)]
    elif anomaly == "工時大於12小時":
        out = out[hours.gt(12)]
    elif anomaly == "未按結束":
        out = out[~ended_mask]
    elif anomaly == "跨日紀錄":
        out = out[_is_cross_day_record_df(out)]
    elif anomaly == "跨日結束":
        out = out[_is_cross_day_end_df(out)]
    elif anomaly == "有開始無結束":
        out = out[started_mask & ~ended_mask]
    elif anomaly == "有結束無開始":
        out = out[~started_mask & ended_mask]

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
            out = out.assign(_wh=_duration_series_to_hours(out["work_hours"], out.index)).sort_values("_wh", ascending=False).drop(columns=["_wh"])
        elif sort_by == "工時由小到大" and "work_hours" in out.columns:
            out = out.assign(_wh=_duration_series_to_hours(out["work_hours"], out.index)).sort_values("_wh", ascending=True).drop(columns=["_wh"])
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

    with st.expander("⌕ 專業篩選 / Professional Filters", expanded=True):
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
            apply_clicked = b1.form_submit_button("⌕ 套用篩選並永久記錄", type="primary", use_container_width=True)
            reset_clicked = b2.form_submit_button("↺ 恢復預設篩選", use_container_width=True)

        if reset_clicked:
            new_filters = reset_history_filters()
            st.session_state["history_filters_applied_v216"] = new_filters
            _add_history_result("success", "已恢復 02｜歷史紀錄預設篩選。", append=False)
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
            _add_history_result("success", "已套用並永久記錄 02｜歷史紀錄篩選條件。", append=False)
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
if not df.empty:
    _ended_metric = _has_end_info_df(df)
    m3.metric("未結束 / Open", f"{(~_ended_metric).sum():,}")
    m4.metric("已結束 / Closed", f"{_ended_metric.sum():,}")
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

    # V131：02 歷史明細編輯欄寬設定。
    # 只新增欄寬/欄位順序設定入口，沿用 table_ui_service 的權威檔永久讀寫；
    # 不改 02 儲存、重算、刪除、匯入、01/02 同步等既有功能。
    _history_width_df = _prepare_history_display_df(df, include_action_cols=False) if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if not _history_width_df.empty:
        try:
            render_width_settings(
                "history_records",
                _history_width_df,
                title="02 歷史明細編輯欄寬設定 / Column Width Settings",
            )
        except Exception as _history_width_exc:
            st.caption(f"欄寬設定暫時無法載入：{_history_width_exc}")

    if not can_edit:
        st.info("目前帳號只有查詢權限；若需修改或刪除歷史紀錄，請由管理員在權限管理開放 02 歷史紀錄的編輯/刪除權限。")
        _render_history_view_table(df, "history_records", height=520)
    else:
        edit_key = "history_edit_enabled"
        delete_select_key = "_spt_history_delete_ids_v27"
        recalc_select_key = "_spt_history_recalc_ids_v27"
        editor_version_key = "history_editor_version_v27"

        if edit_key not in st.session_state:
            st.session_state[edit_key] = False
        if editor_version_key not in st.session_state:
            st.session_state[editor_version_key] = 0

        def _history_all_ids() -> list[int]:
            try:
                return [int(x) for x in df["id"].dropna().tolist()] if "id" in df.columns else []
            except Exception:
                return []

        def _history_clear_widget_state(*tokens: str) -> None:
            # V38: Clear stale data_editor/form widget state by token containment, not only prefix.
            # Streamlit forms can keep a hidden delta that writes checkbox True back to False after rerun.
            clean_tokens = [str(x) for x in tokens if str(x)]
            for k in list(st.session_state.keys()):
                sk = str(k)
                if any(tok in sk for tok in clean_tokens):
                    try:
                        del st.session_state[k]
                    except Exception:
                        pass

        def _history_refresh_editor() -> None:
            _history_clear_widget_state("history_editor_v27_", "history_records_commit_form_v27", "history_records")
            try:
                from services.column_settings_service import clear_editor_draft
                clear_editor_draft("history_editor")
                clear_editor_draft("history_records")
            except Exception:
                pass
            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1

        def _history_set_edit(enabled: bool) -> None:
            st.session_state[edit_key] = bool(enabled)
            if not enabled:
                st.session_state[delete_select_key] = []
                st.session_state[recalc_select_key] = []
            _history_refresh_editor()
            rerun()

        def _history_select(kind: str, select_all: bool) -> None:
            key = delete_select_key if kind == "delete" else recalc_select_key
            st.session_state[key] = _history_all_ids() if select_all else []
            _history_refresh_editor()
            rerun()

        ec1, ec2, ec3 = st.columns([1, 1, 2])
        ec1.button("◇ 啟動編輯 / Enable Edit", use_container_width=True, key="history_enable_edit_v27", disabled=bool(st.session_state[edit_key]), on_click=_history_set_edit, args=(True,))
        ec2.button("◌ 停止編輯 / Stop Edit", use_container_width=True, key="history_stop_edit_v27", disabled=not bool(st.session_state[edit_key]), on_click=_history_set_edit, args=(False,))
        ec3.info("編輯啟動後可修改資料；『刪除』與『重算』分開勾選。儲存編輯不需要勾選。")

        if st.session_state[edit_key]:
            delete_col_label = "刪除 / Delete"
            recalc_col_label = "重算 / Recalc"
            edit_df = df.copy()
            _render_cross_day_edit_notice(edit_df)
            all_ids = _history_all_ids()
            all_id_set = set(all_ids)
            delete_ids_state = set(int(x) for x in st.session_state.get(delete_select_key, []) if int(x) in all_id_set)
            recalc_ids_state = set(int(x) for x in st.session_state.get(recalc_select_key, []) if int(x) in all_id_set)

            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.button("☑ 刪除全選 / Select Delete", use_container_width=True, key="history_select_delete_all_v27", on_click=_history_select, args=("delete", True))
            hc2.button("☐ 刪除取消 / Clear Delete", use_container_width=True, key="history_clear_delete_all_v27", on_click=_history_select, args=("delete", False))
            hc3.button("☑ 重算全選 / Select Recalc", use_container_width=True, key="history_select_recalc_all_v27", on_click=_history_select, args=("recalc", True))
            hc4.button("☐ 重算取消 / Clear Recalc", use_container_width=True, key="history_clear_recalc_all_v27", on_click=_history_select, args=("recalc", False))

            def _id_in_state(x, id_set: set[int]) -> bool:
                try:
                    return int(x) in id_set
                except Exception:
                    return False

            edit_df = _prepare_history_display_df(edit_df, include_action_cols=True, delete_ids=delete_ids_state, recalc_ids=recalc_ids_state)

            editor_key = f"history_editor_v27_{st.session_state[editor_version_key]}"
            history_draft_key = "history_records_edited_draft_v58"
            st.info("V63：歷史紀錄表格與 10｜權限管理同模式；批次按鈕會清除全域 data_editor 草稿，避免 KPI 與 checkbox 畫面不同步。")
            edited = render_table(
                edit_df,
                "history_records",
                editable=True,
                disabled=["id", "record_key", "created_at", "updated_at", HISTORY_CROSS_DAY_ALERT_COL, HISTORY_CROSS_DAY_RANGE_COL],
                key=editor_key,
                height=560,
            )
            if isinstance(edited, pd.DataFrame):
                st.session_state[history_draft_key] = edited.copy()
            st.markdown("**確認後執行動作 / Confirm Action**")
            hist_save_col, hist_recalc_col, hist_delete_col = st.columns([1.1, 1.7, 1.2])
            history_save_clicked = hist_save_col.button(
                "◈ 儲存編輯 / Save",
                type="primary",
                use_container_width=True,
                key="history_records_save_button_v73",
            )
            history_recalc_clicked = hist_recalc_col.button(
                "◇ 重算勾選工時 / Recalc Selected",
                type="primary",
                use_container_width=True,
                key="history_records_recalc_button_v73",
            )
            history_delete_clicked = hist_delete_col.button(
                "◉ 刪除勾選整列 / Delete Selected",
                type="primary",
                use_container_width=True,
                key="history_records_delete_button_v73",
            )
            submitted_history = bool(history_save_clicked or history_recalc_clicked or history_delete_clicked)
            if history_save_clicked:
                history_action = "儲存編輯"
            elif history_recalc_clicked:
                history_action = "重新計算勾選紀錄工時"
            elif history_delete_clicked:
                history_action = "刪除勾選整列紀錄"
            else:
                history_action = ""

            if submitted_history:
                edited = st.session_state.get(history_draft_key, edited)
                if edited is None:
                    _add_history_result("warning", "找不到可儲存的歷史紀錄表格內容，請重新載入後再試。", append=False)
                    rerun()
                def _checked_ids(frame: pd.DataFrame, col: str) -> list[int]:
                    if frame is None or frame.empty or col not in frame.columns or "id" not in frame.columns:
                        return []
                    try:
                        mask = frame[col].map(lambda v: str(v).strip().lower() in {"true", "1", "yes", "y", "on", "勾選", "是"} if not isinstance(v, bool) else v)
                        return [int(x) for x in frame.loc[mask, "id"].dropna().tolist()]
                    except Exception:
                        return []

                delete_ids = sorted(set(_checked_ids(edited, delete_col_label)))
                recalc_ids = sorted(set(_checked_ids(edited, recalc_col_label)))
                st.session_state[delete_select_key] = delete_ids
                st.session_state[recalc_select_key] = recalc_ids

                if history_action == "儲存編輯":
                    save_df = _strip_history_cross_day_display_cols(edited).drop(columns=[delete_col_label, recalc_col_label, "刪除", "重算"], errors="ignore")
                    count = save_time_records(save_df)
                    _add_history_result("success", f"已儲存 {count} 筆歷史紀錄。", append=False)
                    _history_refresh_editor()
                    rerun()
                elif history_action == "重新計算勾選紀錄工時":
                    if not recalc_ids:
                        _add_history_result("warning", "請先在『重算』欄勾選要重新計算的紀錄，再按確認執行。", append=False)
                        rerun()
                    else:
                        save_df = _strip_history_cross_day_display_cols(edited).drop(columns=[delete_col_label, recalc_col_label, "刪除", "重算"], errors="ignore")
                        save_time_records(save_df, recalc_edited_timestamps=True)
                        count = recalculate_time_records(recalc_ids)
                        _add_history_result("success", f"已先同步修改後的開始/結束日期時間，並重新計算 {count} 筆工時。", append=False)
                        _history_refresh_editor()
                        rerun()
                else:
                    if not can_delete:
                        _add_history_result("error", "權限不足：你沒有刪除歷史紀錄權限。", append=False)
                        rerun()
                    elif not delete_ids:
                        _add_history_result("warning", "請先在『刪除』欄勾選要刪除的紀錄，再按確認執行。", append=False)
                        rerun()
                    else:
                        count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")
                        st.session_state[delete_select_key] = []
                        st.session_state[recalc_select_key] = []
                        _add_history_result("success", f"已刪除 {count} 筆歷史紀錄。", append=False)
                        _history_refresh_editor()
                        rerun()

        else:
            _render_history_view_table(df, "history_records", height=520)


with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    if not can_edit:
        st.warning("目前帳號沒有 02 歷史紀錄編輯權限，不能匯入歷史資料。")
    else:
        dl1, dl2 = st.columns(2)
        with dl1:
            export_bio = BytesIO()
            export_df = df.copy()
            with pd.ExcelWriter(export_bio, engine="xlsxwriter") as writer:
                export_df.to_excel(writer, index=False, sheet_name="歷史紀錄")
            st.download_button(
                "下載目前清單 / Download Current List",
                data=export_bio.getvalue(),
                file_name=f"SPT_歷史紀錄_{start}_{end}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with dl2:
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
                source_df = pd.read_excel(uploaded, dtype=object)
                source_df = _prepare_source_dataframe(source_df)
                parsed, warnings = parse_history_dataframe(source_df)
                # Keep the parsed rows in session_state.  This makes the import
                # button reliable after Streamlit reruns and avoids "button clicked
                # but nothing happened" when the uploaded file is reparsed.
                st.session_state[HISTORY_IMPORT_PREVIEW_KEY] = parsed.copy()
                st.session_state[HISTORY_IMPORT_PREVIEW_KEY + "_warnings"] = warnings
                st.caption("原始 Excel 預覽 / Source Preview")
                st.dataframe(source_df.head(30), use_container_width=True, height=220)
                for msg in warnings:
                    st.warning(msg)
                if parsed.empty:
                    st.error("解析後沒有可匯入資料。請確認至少包含：工號、製令、工段、開始時間。")
                else:
                    st.success(f"已解析 {len(parsed)} 筆歷史工時資料。")
                    st.info("請先確認下方解析結果。按『確認匯入 Excel 歷史紀錄』後，結果會永久顯示在頁面上方。")
                    if st.button("⟟ 確認匯入 Excel 歷史紀錄 / Import Excel History", type="primary", use_container_width=True, key="history_excel_import_save_v242_top"):
                        import_df = st.session_state.get(HISTORY_IMPORT_PREVIEW_KEY, parsed).copy()
                        result = import_time_records(import_df, recalc=recalc_excel, source="history_excel_import")
                        _add_history_result("success", f"Excel 匯入完成：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。", append=False)
                        for msg in result.get("errors", [])[:20]:
                            _add_history_result("warning", msg)
                        if result.get("inserted", 0) or result.get("updated", 0):
                            _focus_filter_to_import_rows(import_df, "Excel 匯入資料")
                            rerun()
                        else:
                            _add_history_result("warning", "這次沒有寫入任何資料。請確認解析預覽中的工號、製令、工段名稱、開始時間戳是否正確。")
                            rerun()
                    st.dataframe(parsed, use_container_width=True, height=360)
            except Exception as exc:
                _add_history_result("error", f"Excel 匯入失敗：{exc}", append=False)
                st.error(f"Excel 匯入失敗：{exc}")

with tab3:
    st.subheader("貼上資料 / Paste Data")
    if not can_edit:
        st.warning("目前帳號沒有 02 歷史紀錄編輯權限，不能貼上匯入歷史資料。")
    else:
        st.caption("支援從 Excel 複製整批資料貼上。建議包含標題列：狀態、製令、P/N、機型、工段名稱、工號、姓名、開始時間戳、結束時間戳、備註、組立地點。")
        paste_raw_version_key = "v239_history_paste_raw_version"
        paste_raw_widget_key = f"{HISTORY_PASTE_RAW_KEY}_{int(st.session_state.get(paste_raw_version_key, 0))}"
        raw = st.text_area("貼上 Excel 複製的歷史紀錄資料", height=260, key=paste_raw_widget_key)
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
                if st.button("▣ 確認匯入貼上歷史紀錄 / Save Pasted History", type="primary", use_container_width=True, key="history_paste_save_v242"):
                    import_df = parsed.copy()
                    result = import_time_records(import_df, recalc=recalc_paste, source="history_paste_import")
                    _add_history_result("success", f"貼上資料已匯入：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。", append=False)
                    for msg in result.get("errors", [])[:20]:
                        _add_history_result("warning", msg)
                    if result.get("inserted", 0) == 0 and result.get("updated", 0) == 0:
                        _add_history_result("warning", "這次沒有寫入任何資料。請確認解析預覽中的工號、製令、工段名稱、開始時間戳是否正確。")
                    else:
                        # 不可在 text_area 建立後直接改同一個 session_state key，
                        # 否則 Streamlit 會拋 StreamlitAPIException。
                        # 改用 key version 方式，成功匯入後下一次 rerun 產生新輸入框，達到清空效果。
                        st.session_state[paste_raw_version_key] = int(st.session_state.get(paste_raw_version_key, 0)) + 1
                        _focus_filter_to_import_rows(import_df, "貼上匯入資料")
                    rerun()
                st.caption("匯入前預覽 / Parsed Preview")
                st.dataframe(parsed, use_container_width=True, height=360)
        else:
            st.info("請先貼上 Excel 資料。")
