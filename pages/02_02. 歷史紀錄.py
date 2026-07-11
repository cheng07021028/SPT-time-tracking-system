# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import os
import re
import time as _time
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
from services.table_ui_service import (
    render_table,
    label_for,
    render_width_settings,
    load_widths,
    save_widths,
    load_column_order,
    save_column_order,
    apply_column_order,
)
from services.time_record_delete_unifier_service import delete_selected_time_records_from_editor
from services.duration_service import hours_to_hms
from services.history_filter_service import load_history_filters, save_history_filters, reset_history_filters
try:
    from services.large_table_query_service import load_history_records_sql_filtered, load_history_filter_options_sql, count_history_records_sql_filtered
except Exception:
    load_history_records_sql_filtered = None
    load_history_filter_options_sql = None
    count_history_records_sql_filtered = None

# === V180B_HISTORY_TOTAL_TIME_TYPE_FIX_BEGIN ===
def _v180b_parse_work_hours_to_decimal_hours(value):
    """Safely convert mixed work_hours values to decimal hours.

    Supported inputs:
    - numeric hours, e.g. 0.16
    - HH:MM:SS, e.g. 00:09:36
    - H:MM, e.g. 1:30
    - strings with blanks, commas, or legacy labels
    Invalid/blank values are treated as 0.
    """
    try:
        if value is None:
            return 0.0
        # pandas/numpy missing values
        try:
            import pandas as _pd  # local import: app already depends on pandas
            if _pd.isna(value):
                return 0.0
        except Exception:
            pass
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        if text.lower() in {"nan", "none", "null", "nat", "未按結束", "清空"}:
            return 0.0
        # Remove common human-readable decorations without changing real values.
        text = text.replace(",", "").replace("小時", "").strip()
        text = text.replace("時", ":").replace("分", ":").replace("秒", "")
        if ":" in text:
            parts = [p for p in text.split(":") if p != ""]
            nums = []
            for p in parts[:3]:
                try:
                    nums.append(float(p))
                except Exception:
                    nums.append(0.0)
            while len(nums) < 3:
                nums.append(0.0)
            h, m, s = nums[0], nums[1], nums[2]
            return max(0.0, h + m / 60.0 + s / 3600.0)
        return max(0.0, float(text))
    except Exception:
        return 0.0


def _v180b_decimal_hours_to_hms(total_hours):
    try:
        seconds = int(round(float(total_hours) * 3600))
    except Exception:
        seconds = 0
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _v180b_safe_work_hours_total_hms(df):
    """Return total work hours as HH:MM:SS without pandas mixed-type sum."""
    try:
        if df is None or getattr(df, "empty", True) or "work_hours" not in getattr(df, "columns", []):
            return "00:00:00"
        total = 0.0
        for value in df["work_hours"].tolist():
            total += _v180b_parse_work_hours_to_decimal_hours(value)
        return _v180b_decimal_hours_to_hms(total)
    except Exception:
        return "00:00:00"
# === V180B_HISTORY_TOTAL_TIME_TYPE_FIX_END ===


st.set_page_config(page_title="02. 歷史紀錄", page_icon="⧠", layout="wide")
apply_theme()
require_module_access("02_history")
render_header("02｜歷史紀錄", "完整工時明細查詢、資料編輯、刪除、重新計算、Excel 匯入、貼上資料與 Excel 匯出")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("02", "歷史紀錄")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


HISTORY_IMPORT_PREVIEW_KEY = "v197_history_import_preview"
HISTORY_PASTE_RAW_KEY = "v197_history_paste_raw"
HISTORY_RESULT_MESSAGES_KEY = "v238_history_result_messages"
V259_HISTORY_QUERY_REQUESTED_KEY = "v259_02_history_query_requested"
V259_HISTORY_DF_KEY = "v259_02_history_df"
V259_HISTORY_TS_KEY = "v259_02_history_loaded_at"
V30086_HISTORY_PAGE_KEY = "v30086_02_history_page"
V30086_HISTORY_TOTAL_KEY = "v30086_02_history_total_count"
V30086_HISTORY_FILTER_SIG_KEY = "v30086_02_history_filter_signature"
V30086_HISTORY_EXPORT_BYTES_KEY = "v30086_02_history_all_filtered_export_bytes"
V30086_HISTORY_EXPORT_NAME_KEY = "v30086_02_history_all_filtered_export_name"
V30087_HISTORY_PAGINATION_VERSION_KEY = "v30087_02_history_pagination_version"
V30087_HISTORY_PAGINATION_VERSION = "V30087_20260615_PAGING_TOTAL_UNCAPPED"
V30091_HISTORY_DEFAULT_PRESET = "今日"


# === V300.27 02 HISTORY LOW-RISK FASTPATH BEGIN ===
# 02 歷史紀錄的查詢本身已改成手動觸發；這裡只處理不影響資料正確性的
# 熱路徑：同一輪 rerun 不重複讀篩選設定、不重建固定 Excel 範本。
# 注意：這些 helper 只快取 UI 設定與固定範本，不快取正式工時寫入結果。
V30027_HISTORY_FILTERS_CACHE_KEY = "v30027_02_history_filters_cache"
V30027_HISTORY_TEMPLATE_BYTES_KEY = "v30027_02_history_template_bytes"


def _v30027_load_history_filters_cached() -> dict:
    cached = st.session_state.get(V30027_HISTORY_FILTERS_CACHE_KEY)
    if isinstance(cached, dict) and cached:
        return dict(cached)
    loaded = _v30091_today_default_history_filters(load_history_filters())
    st.session_state[V30027_HISTORY_FILTERS_CACHE_KEY] = dict(loaded or {})
    return dict(loaded or {})


def _v30027_save_history_filters_cached(filters: dict) -> dict:
    saved = save_history_filters(filters)
    st.session_state[V30027_HISTORY_FILTERS_CACHE_KEY] = dict(saved or {})
    return saved


def _v30027_reset_history_filters_cached() -> dict:
    saved = _v30091_today_default_history_filters(reset_history_filters())
    st.session_state[V30027_HISTORY_FILTERS_CACHE_KEY] = dict(saved or {})
    return saved


# === V300.70 02 HISTORY FILTER OPTIONS SQL CACHE BEGIN ===
V30070_HISTORY_FILTER_OPTIONS_CACHE_KEY = "v30070_02_history_filter_options_cache"
V30070_HISTORY_STATUS_FALLBACK = ["作業中", "下班", "暫停", "完工", "已結束", "結束", "補登結束"]


def _v30070_clean_option_text(value) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except Exception:
        if value is None:
            return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _v30070_merge_options(*sources) -> list[str]:
    out: list[str] = []
    for src in sources:
        if src is None:
            continue
        if isinstance(src, str):
            values = [src]
        else:
            try:
                values = list(src)
            except Exception:
                values = [src]
        for raw in values:
            text = _v30070_clean_option_text(raw)
            if text and text not in out:
                out.append(text)
    return out


def _v30070_options_from_df(df: pd.DataFrame | None) -> dict[str, list[str]]:
    cols = [
        "work_order", "part_no", "type_name", "assembly_location", "process_name",
        "employee_id", "employee_name", "status",
    ]
    out = {c: [] for c in cols}
    if not isinstance(df, pd.DataFrame) or df.empty:
        return out
    for col in cols:
        if col in df.columns:
            out[col] = _v30070_merge_options(df[col].dropna().astype(str).tolist())
    return out


def _v30070_load_history_filter_options_cached(start_date_value, end_date_value) -> dict[str, list[str]]:
    """Load lightweight DISTINCT options for 02 filters without loading history rows.

    V259 stopped loading history details when opening 02, which is correct for speed,
    but process/status options have no master-data source.  The old placeholder `{}`
    made 工段名稱 / 狀態 display "No options to select" even when time_records had data.
    This helper uses the existing SQL DISTINCT service once per date range, caches the
    result in session, and falls back to the current query cache only if SQL is not
    available.  It does not scan 02 full history and does not write Neon.
    """
    key = (str(start_date_value or ""), str(end_date_value or ""))
    cache = st.session_state.get(V30070_HISTORY_FILTER_OPTIONS_CACHE_KEY)
    if isinstance(cache, dict) and cache.get("key") == key and isinstance(cache.get("options"), dict):
        return dict(cache.get("options") or {})

    options: dict[str, list[str]] = {}
    if callable(load_history_filter_options_sql):
        try:
            loaded = load_history_filter_options_sql(start_date_value, end_date_value, limit_per_column=5000)
            if isinstance(loaded, dict):
                options = {str(k): _v30070_merge_options(v) for k, v in loaded.items()}
        except Exception:
            options = {}

    # Fallback only uses an already-loaded page cache; it never triggers a heavy read.
    cached_df_options = _v30070_options_from_df(st.session_state.get(V259_HISTORY_DF_KEY))
    for col, vals in cached_df_options.items():
        options[col] = _v30070_merge_options(options.get(col, []), vals)

    # Status has a small, stable vocabulary.  Keep it selectable even before the
    # first successful DISTINCT query; SQL/result filtering still determines rows.
    options["status"] = _v30070_merge_options(options.get("status", []), V30070_HISTORY_STATUS_FALLBACK)

    st.session_state[V30070_HISTORY_FILTER_OPTIONS_CACHE_KEY] = {"key": key, "options": dict(options)}
    return dict(options)
# === V300.70 02 HISTORY FILTER OPTIONS SQL CACHE END ===


def _v30027_history_template_bytes() -> bytes:
    cached = st.session_state.get(V30027_HISTORY_TEMPLATE_BYTES_KEY)
    if isinstance(cached, (bytes, bytearray)) and cached:
        return bytes(cached)
    data = _download_history_template()
    st.session_state[V30027_HISTORY_TEMPLATE_BYTES_KEY] = data
    return data
# === V300.27 02 HISTORY LOW-RISK FASTPATH END ===

# V71: 02 歷史明細是互動頁面，不適合一次把數萬筆拉進 Streamlit。
# 大量匯出/稽核應走 09/15/背景報表；互動查詢先保持 2~3 秒目標。
def _v71_env_int(name: str, default: int, min_value: int = 50, max_value: int = 5000) -> int:
    try:
        value = int(float(str(os.environ.get(name, default)).strip()))
    except Exception:
        value = default
    return max(min_value, min(max_value, value))

V71_HISTORY_INTERACTIVE_MAX_ROWS = _v71_env_int("SPT_HISTORY_INTERACTIVE_MAX_ROWS", 1000, 100, 5000)
V71_HISTORY_PYTHON_SCAN_MAX_ROWS = _v71_env_int("SPT_HISTORY_PYTHON_SCAN_MAX_ROWS", 2000, 200, 5000)


def _v71_top_n_limit(filters: dict | None) -> int | None:
    try:
        text = str((filters or {}).get("top_n") or "全部").strip()
        if text.startswith("Top"):
            return int(text.replace("Top", "").strip())
    except Exception:
        pass
    return None


def _v71_requested_detail_limit(filters: dict | None, default: int = 300) -> int:
    try:
        raw = int(float(str((filters or {}).get("detail_limit") or default).strip()))
    except Exception:
        raw = default
    # V300.87: detail_limit is now the server-side page size.  It must not be
    # reduced by Top N, otherwise a saved Top 100 setting makes the page and
    # total area look like only 100 records were imported.  Top N is a legacy
    # display cap; page size and total count are handled separately.
    return max(50, min(V71_HISTORY_INTERACTIVE_MAX_ROWS, raw))


def _v71_needs_python_post_filter(filters: dict | None) -> bool:
    f = filters or {}
    anomaly = str(f.get("anomaly_filter") or "全部").strip()
    sort_by = str(f.get("sort_by") or "").strip()
    return bool(
        f.get("departments")
        or f.get("titles")
        or anomaly != "全部"
        or sort_by in {"工時由大到小", "工時由小到大"}
    )


# V300.86: 02 history server-side pagination helpers.
# Keep the existing Professional Filters and table UI; only change the data loading
# strategy so large result sets are read page by page instead of loading tens of
# thousands of rows into Streamlit at once.
def _v30086_history_filter_signature(filters: dict | None) -> str:
    try:
        return json.dumps(filters or {}, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return repr(filters or {})


def _v30086_clear_history_page_cache(*, reset_page: bool = True) -> None:
    st.session_state.pop(V259_HISTORY_DF_KEY, None)
    st.session_state.pop(V259_HISTORY_TS_KEY, None)
    st.session_state.pop(V30086_HISTORY_TOTAL_KEY, None)
    st.session_state.pop("v100_history_current_export_bytes", None)
    st.session_state.pop("v100_history_current_export_name", None)
    st.session_state.pop(V30086_HISTORY_EXPORT_BYTES_KEY, None)
    st.session_state.pop(V30086_HISTORY_EXPORT_NAME_KEY, None)
    if reset_page:
        st.session_state[V30086_HISTORY_PAGE_KEY] = 1


def _v30086_history_page_size(filters: dict | None) -> int:
    return _v71_requested_detail_limit(filters, default=500)


def _v30087_filters_without_legacy_display_caps(filters: dict | None) -> dict:
    """Return filters used for server-side paging/export post filters.

    V300.86 could apply legacy Top N/detail_limit after the SQL page was already
    loaded.  That made the screen show 100/100 even when Neon held thousands of
    rows.  Pagination owns the display limit now, so pandas post-filters should
    keep semantic filters only.
    """
    f = dict(filters or {})
    f["top_n"] = "全部"
    f["detail_limit"] = 0
    return f


def _v30086_top_n_cap(filters: dict | None, total: int) -> int:
    top_limit = _v71_top_n_limit(filters)
    if top_limit:
        try:
            return min(int(total), int(top_limit))
        except Exception:
            return int(total or 0)
    return int(total or 0)


def _v30086_load_history_total_count(filters: dict | None) -> tuple[int, bool]:
    """Return total count for SQL-side filters.

    The count is exact for SQL-safe filters.  If the user chooses Python-only
    filters such as anomaly or department/title, this value is the SQL candidate
    count and the current page still applies the final Python filter after loading.
    """
    if not callable(count_history_records_sql_filtered):
        return 0, False
    try:
        total = int(count_history_records_sql_filtered(filters or {}) or 0)
    except Exception:
        return 0, False
    # V300.87: total count must represent all rows matching the filters.  Do not
    # cap it by the legacy Top N option, otherwise users think only 100 rows were
    # imported after a large Excel import.
    return int(total or 0), (not _v71_needs_python_post_filter(filters))


def _v30086_load_history_page(filters: dict | None, *, page: int, page_size: int) -> pd.DataFrame:
    offset = max(0, int(page_size) * max(0, int(page) - 1))
    if callable(load_history_records_sql_filtered):
        _needs_python_post_filter = _v71_needs_python_post_filter(filters)
        # For Python-only filters, read a bounded candidate page and then apply
        # the existing pandas filter, preserving current calculation semantics.
        _sql_limit = min(V71_HISTORY_PYTHON_SCAN_MAX_ROWS, max(page_size, min(V71_HISTORY_PYTHON_SCAN_MAX_ROWS, page_size * 2))) if _needs_python_post_filter else page_size
        _sql_df = load_history_records_sql_filtered(filters, limit=_sql_limit, offset=offset)
        if isinstance(_sql_df, pd.DataFrame):
            out = _apply_history_filters(_sql_df, _v30087_filters_without_legacy_display_caps(filters)) if _needs_python_post_filter else _sql_df
            if len(out) > page_size:
                out = out.head(page_size).copy()
            return out
        return pd.DataFrame()
    # Fallback keeps the old bounded path.  It is not used on Streamlit Cloud with Neon.
    fallback_df = load_records(str((filters or {}).get("start_date", _seed_start)), str((filters or {}).get("end_date", _seed_end)), None, None)
    fallback_df = _apply_history_filters(fallback_df, filters)
    start_idx = offset
    end_idx = offset + page_size
    return fallback_df.iloc[start_idx:end_idx].copy() if isinstance(fallback_df, pd.DataFrame) else pd.DataFrame()


def _v30086_prepare_all_filtered_export(filters: dict | None, *, batch_size: int = 3000, max_rows: int = 100000) -> pd.DataFrame:
    """Load all filtered rows for explicit export only, never for screen rendering."""
    if not callable(load_history_records_sql_filtered):
        fallback_df = load_records(str((filters or {}).get("start_date", _seed_start)), str((filters or {}).get("end_date", _seed_end)), None, None)
        return _apply_history_filters(fallback_df, filters).head(max_rows)
    frames: list[pd.DataFrame] = []
    offset = 0
    page_size = max(100, min(5000, int(batch_size)))
    total_loaded = 0
    while total_loaded < int(max_rows):
        part = load_history_records_sql_filtered(filters, limit=page_size, offset=offset)
        if not isinstance(part, pd.DataFrame) or part.empty:
            break
        if _v71_needs_python_post_filter(filters):
            part = _apply_history_filters(part, _v30087_filters_without_legacy_display_caps(filters))
        if isinstance(part, pd.DataFrame) and not part.empty:
            frames.append(part)
            total_loaded += len(part)
        # Offset follows SQL candidate rows, not post-filter rows.
        offset += page_size
        if len(part) < page_size and not _v71_needs_python_post_filter(filters):
            break
        if offset >= int(max_rows) and _v71_needs_python_post_filter(filters):
            # Protection for Python-only export filters.
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).head(max_rows)


def _v259_now_label() -> str:
    try:
        from services.timezone_service import now_text
        return str(now_text())
    except Exception:
        try:
            from datetime import datetime
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""


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


def _work_hours_value_to_decimal_hours(value) -> float:
    """Convert mixed work_hours values to decimal hours without changing stored data.

    V154: 02 history may receive decimal hours (0.16), HH:MM:SS text
    (00:09:36), or old display text that accidentally carried the explanatory
    suffix.  Pandas Series.sum() will crash on mixed strings/floats, so all KPI
    totals must use this read-only converter.
    """
    try:
        if pd.isna(value):
            return 0.0
    except Exception:
        pass
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return 0.0
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return 0.0
    # Clean legacy display-only suffixes.  These strings should never affect data.
    text = (
        text.replace("時:分:秒", "")
            .replace("時：分：秒", "")
            .replace("（時:分:秒）", "")
            .replace("(時:分:秒)", "")
            .strip()
    )
    text = text.replace(",", "").replace(" ", "")
    # HH:MM:SS / H:MM / full-width colon.
    if ":" in text or "：" in text:
        parts = re.split(r"[:：]", text)
        try:
            sign = -1 if parts[0].startswith("-") else 1
            h = abs(int(float(parts[0] or 0)))
            m = int(float(parts[1] or 0)) if len(parts) > 1 else 0
            s = int(float(parts[2] or 0)) if len(parts) > 2 else 0
            return sign * ((h * 3600 + m * 60 + s) / 3600.0)
        except Exception:
            return 0.0
    # Chinese text such as 1時02分03秒.
    m = re.match(r"^(-?\d+)\s*(?:時|小時|h|H)\s*(\d{1,2})?\s*(?:分|m|M)?\s*(\d{1,2})?\s*(?:秒|s|S)?$", text)
    if m:
        try:
            sign = -1 if m.group(1).startswith("-") else 1
            h = abs(int(m.group(1)))
            minute = int(m.group(2) or 0)
            sec = int(m.group(3) or 0)
            return sign * ((h * 3600 + minute * 60 + sec) / 3600.0)
        except Exception:
            return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def _safe_work_hours_total_hms(df: pd.DataFrame) -> str:
    """Read-only KPI total for mixed decimal/HMS work_hours values."""
    if df is None or df.empty or "work_hours" not in df.columns:
        return "00:00:00"
    total_hours = 0.0
    try:
        total_hours = sum(_work_hours_value_to_decimal_hours(v) for v in df["work_hours"].tolist())
    except Exception:
        total_hours = 0.0
    return hours_to_hms(total_hours)


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
    # V30077: Excel template uses bilingual header "姓名 / Name".  The safer
    # header matcher intentionally avoids short fuzzy aliases such as "name", so
    # include normalized bilingual aliases explicitly to prevent employee_name
    # from being parsed as blank.
    "employee_name": ["姓名", "姓名 / Name", "姓名 Name", "姓名name", "name姓名", "name", "employee name", "employee_name", "人員姓名"],
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
    new_filters = _v30027_load_history_filters_cached()
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
        "detail_limit": min(V71_HISTORY_INTERACTIVE_MAX_ROWS, max(300, min(max(len(import_df) + 50, 300), V71_HISTORY_INTERACTIVE_MAX_ROWS))),
    })
    saved = _v30027_save_history_filters_cached(new_filters)
    st.session_state["history_filters_applied_v216"] = saved
    _add_history_result("info", f"已自動切換 02｜歷史紀錄篩選到{label}日期範圍：{start_d} ~ {end_d}，方便確認全部匯入結果。")




def _v30080_format_seconds(seconds: float) -> str:
    try:
        total = max(int(float(seconds or 0)), 0)
    except Exception:
        total = 0
    minutes, sec = divmod(total, 60)
    if minutes <= 0:
        return f"{sec} 秒"
    return f"{minutes} 分 {sec} 秒"


def _v30080_import_with_progress(import_df: pd.DataFrame, *, recalc: bool, source: str, label: str, restore_deleted_matching_records: bool = False) -> dict:
    """Run 02 history import with visible progress for large Excel/Paste batches.

    V300.80 keeps the authority write logic inside time_record_service, but the
    page owns Streamlit UI progress and ETA.  This prevents 16k-row imports from
    looking frozen while still avoiding per-row Neon writes.
    """
    total_rows = int(len(import_df)) if isinstance(import_df, pd.DataFrame) else 0
    progress_bar = st.progress(0)
    status_box = st.empty()
    status_box.info(f"{label}：準備匯入 {total_rows} 筆...")
    started = _time.monotonic()
    last_ui = {"time": 0.0, "stage": ""}

    def _callback(event: dict) -> None:
        now = _time.monotonic()
        fraction = float((event or {}).get("fraction") or 0.0)
        fraction = max(0.0, min(1.0, fraction))
        stage = str((event or {}).get("stage") or "")
        # Avoid updating the UI too often on large imports, but always show
        # stage changes.  V300.83: without this, the screen could remain at
        # 「比對 Neon 16491/16491」 while the backend had already moved to diff
        # or the first write chunk.
        if fraction < 1.0 and stage == str(last_ui.get("stage") or "") and now - float(last_ui.get("time") or 0.0) < 0.25:
            return
        last_ui["time"] = now
        last_ui["stage"] = stage
        elapsed = now - started
        eta_text = "估算中"
        if fraction > 0.03:
            eta = max(0.0, elapsed * (1.0 - fraction) / fraction)
            eta_text = _v30080_format_seconds(eta)
        message = str((event or {}).get("message") or "處理中")
        current = int((event or {}).get("current") or 0)
        total = int((event or {}).get("total") or 0)
        detail = f"{message}"
        if total > 0:
            detail += f"：{current}/{total}"
        detail += f"；已用 {_v30080_format_seconds(elapsed)}；預估剩餘 {eta_text}"
        percent = int(round(fraction * 100))
        try:
            progress_bar.progress(percent, text=f"{label}：{detail}")
        except TypeError:
            progress_bar.progress(percent)
        status_box.info(detail)

    try:
        result = import_time_records(
            import_df,
            recalc=recalc,
            source=source,
            batch_size=1000,
            progress_callback=_callback,
            restore_deleted_matching_records=bool(restore_deleted_matching_records),
        )
    finally:
        elapsed = _time.monotonic() - started
        try:
            progress_bar.progress(100, text=f"{label}：匯入流程完成，用時 {_v30080_format_seconds(elapsed)}")
        except TypeError:
            progress_bar.progress(100)
    status_box.success(f"{label}：匯入流程完成，用時 {_v30080_format_seconds(float(result.get('duration_seconds') or elapsed))}")
    return result

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


def _clean_history_filter_token(value: object) -> str:
    text = str(value or "")
    text = text.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("　", " ").strip().strip("'\"")
    return text.strip()


def _history_filter_norm(value: object) -> str:
    return _clean_history_filter_token(value).casefold()


def _apply_history_exact_text_filter(df: pd.DataFrame, column: str, values: list[str]) -> pd.DataFrame:
    if not values or column not in df.columns:
        return df
    value_set = {_history_filter_norm(v) for v in values if _history_filter_norm(v)}
    if not value_set:
        return df
    return df.loc[df[column].map(_history_filter_norm).isin(value_set)].copy()


def _parse_pasted_history_work_order_filters(raw: object) -> list[str]:
    """Parse pasted work-order values for the 02 history filter form only.

    This stays in the front-end/session layer: it does not query Neon and it
    does not write history data. Users can paste one Work Order column copied
    from Excel or a newline/comma/tab separated list, then the parsed values are
    merged into the normal Work Order filter only after pressing Apply.
    """
    raw_text = str(raw or "").replace("\r", "\n").strip()
    if not raw_text:
        return []
    skip_tokens = {
        "製令", "工單", "工令", "製令號碼", "製令編號",
        "work", "order", "work order", "workorder", "wo", "mo",
        "/", "-", "none", "nan", "null",
    }
    out: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n\t,，;；]+|\s+", raw_text):
        value = _clean_history_filter_token(token)
        if not value:
            continue
        if value.lower().strip() in skip_tokens:
            continue
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _merge_filter_lists(*groups) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if group is None:
            continue
        try:
            iterable = list(group)
        except Exception:
            iterable = [group]
        for value in iterable:
            text = _clean_history_filter_token(value)
            if text and text not in seen:
                out.append(text)
                seen.add(text)
    return out


def _v30108_history_bulk_work_orders_from_filters(filters_map: dict | None) -> list[str]:
    filters_map = filters_map or {}
    pasted = _merge_filter_lists(filters_map.get("work_orders_pasted", []))
    if pasted:
        return pasted
    legacy = _merge_filter_lists(filters_map.get("work_orders", []))
    return legacy if len(legacy) > 8 else []


def _v30108_history_manual_work_orders_for_widget(filters_map: dict | None) -> list[str]:
    filters_map = filters_map or {}
    legacy_bulk = _v30108_history_bulk_work_orders_from_filters(filters_map)
    if legacy_bulk and not _merge_filter_lists(filters_map.get("work_orders_pasted", [])):
        return []
    return _merge_filter_lists(filters_map.get("work_orders", []))


def _v30108_history_effective_work_orders(filters_map: dict | None) -> list[str]:
    filters_map = filters_map or {}
    effective = _merge_filter_lists(filters_map.get("work_orders_effective", []))
    if effective:
        return effective
    return _merge_filter_lists(filters_map.get("work_orders", []), _v30108_history_bulk_work_orders_from_filters(filters_map))


def _v30109_history_make_effective_work_orders(manual_values, pasted_values) -> list[str]:
    return _merge_filter_lists(manual_values, pasted_values)


def _render_v30107_history_filter_input_text_css() -> None:
    """Keep typed text readable on the dark glass filters in 02."""
    st.markdown(
        """
        <style>
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] input,
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] input:focus,
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] input:active,
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] [role="combobox"],
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] [contenteditable="true"],
        .stApp div[data-baseweb="select"] input,
        .stApp div[data-baseweb="select"] input:focus,
        .stApp div[data-baseweb="select"] input:active,
        .stApp div[data-baseweb="input"] input,
        .stApp div[data-baseweb="textarea"] textarea {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            caret-color: #FFFFFF !important;
            text-shadow: 0 0 0 #FFFFFF !important;
        }
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] input::placeholder,
        .stApp div[data-baseweb="select"] input::placeholder,
        .stApp div[data-baseweb="input"] input::placeholder,
        .stApp div[data-baseweb="textarea"] textarea::placeholder {
            color: rgba(248, 255, 255, .78) !important;
            -webkit-text-fill-color: rgba(248, 255, 255, .78) !important;
            text-shadow: none !important;
        }
        .stApp div[data-testid="stMultiSelect"] div[data-baseweb="select"] input::selection,
        .stApp div[data-baseweb="select"] input::selection {
            color: #FFFFFF !important;
            background: rgba(51, 219, 255, .38) !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        .stApp div[data-baseweb="select"] [role="listbox"] [role="option"],
        .stApp div[data-baseweb="select"] [role="option"] {
            color: #F8FFFF !important;
            -webkit-text-fill-color: #F8FFFF !important;
        }
        .stApp div[data-baseweb="select"] [aria-selected="true"],
        .stApp div[data-baseweb="select"] [aria-selected="true"] * {
            color: #061123 !important;
            -webkit-text-fill-color: #061123 !important;
            text-shadow: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
        return today, today


def _v30091_today_default_history_filters(filters: dict | None) -> dict:
    """Return UI default filters with Quick Date defaulting to 今日.

    This is intentionally session/UI-level only: it does not write to Neon during
    page render.  If an existing saved filter is a real custom range, keep it;
    if it is blank or matches the old system default 近30天, show 今日 as the
    new default.
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
        f["date_preset"] = V30091_HISTORY_DEFAULT_PRESET
        f["start_date"] = str(today)
        f["end_date"] = str(today)
    return f


def _v79_effective_history_filters(filters: dict | None) -> dict:
    """Return filters with an explicit bounded date range for the 02 hot query path.

    舊永久篩選檔可能只有 date_preset，沒有 start_date / end_date。
    這種狀況下按「查詢 / 重新整理歷史明細」會變成沒有日期條件，
    Neon 需要掃描整張 time_records，現場會看起來一直運轉。
    
    這裡不改 UI，也不寫回永久檔；只在查詢當下把快速日期轉成
    明確日期，讓 SQL 能走 start_date 索引。
    """
    f = dict(filters or {})
    preset = str(f.get("date_preset") or V30091_HISTORY_DEFAULT_PRESET)
    start_raw = f.get("start_date")
    end_raw = f.get("end_date")
    start_dt, end_dt = _date_range_from_preset(preset, str(start_raw or ""), str(end_raw or ""))
    f["start_date"] = str(start_dt)
    f["end_date"] = str(end_dt)
    return f


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


def _v82_text_cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none", "null"}:
        return ""
    return text


def _v82_split_timestamp(value) -> tuple[str, str]:
    text = _v82_text_cell(value)
    if not text:
        return "", ""
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
    except Exception:
        pass
    return text[:10], text[11:19] if len(text) >= 16 else ""


def _v82_first_existing_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _v82_sync_timestamp_to_split_columns(edited_df: pd.DataFrame, original_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Synchronize 02 editor timestamp edits into date/time helper columns.

    In 01/02 maintenance, 開始時間戳 and 結束時間戳 are the authoritative
    edit fields.  When they change, 開始日期/開始時間/結束日期/結束時間 must
    be regenerated before save/recalc so both pages and Neon remain consistent.
    """
    if not isinstance(edited_df, pd.DataFrame) or edited_df.empty:
        return edited_df.copy() if isinstance(edited_df, pd.DataFrame) else pd.DataFrame()
    out = edited_df.copy()
    id_col = "id" if "id" in out.columns else ("ID / ID" if "ID / ID" in out.columns else None)
    original_map = {}
    if isinstance(original_df, pd.DataFrame) and id_col and id_col in original_df.columns:
        for _, old_row in original_df.iterrows():
            try:
                rid = int(float(str(old_row.get(id_col)).strip()))
            except Exception:
                continue
            original_map[rid] = old_row

    pairs = {
        "start": {
            "ts": ["start_timestamp", "開始時間戳 / Start Timestamp", "開始時間戳"],
            "date": ["start_date", "開始日期 / Start Date", "開始日期"],
            "time": ["start_time", "開始時間 / Start Time", "開始時間"],
        },
        "end": {
            "ts": ["end_timestamp", "結束時間戳 / End Timestamp", "結束時間戳"],
            "date": ["end_date", "結束日期 / End Date", "結束日期"],
            "time": ["end_time", "結束時間 / End Time", "結束時間"],
        },
    }
    for _prefix, cols in pairs.items():
        ts_col = _v82_first_existing_col(out, cols["ts"])
        date_col = _v82_first_existing_col(out, cols["date"])
        time_col = _v82_first_existing_col(out, cols["time"])
        if not ts_col:
            continue
        for idx, row in out.iterrows():
            try:
                rid = int(float(str(row.get(id_col)).strip())) if id_col else None
            except Exception:
                rid = None
            old = original_map.get(rid)
            cur_ts = _v82_text_cell(row.get(ts_col))
            old_ts = _v82_text_cell(old.get(ts_col)) if old is not None and ts_col in getattr(old, "index", []) else ""
            # If the timestamp changed, timestamp wins and split fields are regenerated.
            if old is not None and cur_ts != old_ts:
                d, t = _v82_split_timestamp(cur_ts)
                if date_col:
                    out.at[idx, date_col] = d
                if time_col:
                    out.at[idx, time_col] = t
                if ts_col and d and t:
                    out.at[idx, ts_col] = f"{d} {t}"
            elif cur_ts:
                # Repair display/helper columns for old rows that only had timestamp.
                d, t = _v82_split_timestamp(cur_ts)
                if date_col:
                    out.at[idx, date_col] = d or _v82_text_cell(row.get(date_col))
                if time_col:
                    out.at[idx, time_col] = t or _v82_text_cell(row.get(time_col))
    return out


# ===== V82 HISTORY SAVE DIFF HELPERS =====
_V82_HISTORY_DISPLAY_TO_INTERNAL = {
    "ID / ID": "id", "紀錄編號": "id", "ID": "id",
    "狀態 / Status": "status",
    "製令 / Work Order": "work_order",
    "製令號碼 / Work Order No.": "work_order_no",
    "P/N / Part No.": "part_no",
    "機型 / Type": "type_name",
    "工段名稱 / Process": "process_name", "工段 / Process": "process_name",
    "工號 / Employee ID": "employee_id",
    "姓名 / Name": "employee_name",
    "開始動作 / Start Action": "start_action",
    "開始時間戳 / Start Timestamp": "start_timestamp",
    "結束動作 / End Action": "end_action",
    "結束時間戳 / End Timestamp": "end_timestamp",
    "開始日期 / Start Date": "start_date",
    "開始時間 / Start Time": "start_time",
    "結束日期 / End Date": "end_date",
    "結束時間 / End Time": "end_time",
    "工時小計 / Hours": "work_hours",
    "工時分鐘 / Minutes": "work_minutes",
    "備註 / Remark": "remark",
    "組立地點 / Assembly Location": "assembly_location",
    "建立時間 / Created At": "created_at",
    "更新時間 / Updated At": "updated_at",
}

_V82_HISTORY_SAVE_IGNORE_COLS = {
    "刪除", "重算", "刪除 / Delete", "重算 / Recalc",
    HISTORY_CROSS_DAY_ALERT_COL, HISTORY_CROSS_DAY_RANGE_COL, "跨日結束",
    "created_at", "updated_at", "version",
}


def _v82_norm_compare_cell(value) -> str:
    text = _v82_text_cell(value)
    if not text:
        return ""
    try:
        if text.endswith(".0"):
            return str(int(float(text)))
    except Exception:
        pass
    return text


def _v82_history_normalize_compare_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    out = _strip_history_cross_day_display_cols(frame.copy())
    out = out.drop(columns=["刪除", "重算", "刪除 / Delete", "重算 / Recalc"], errors="ignore")
    out = out.rename(columns={c: _V82_HISTORY_DISPLAY_TO_INTERNAL.get(str(c), str(c)) for c in out.columns})
    return out


def _v82_history_changed_rows_for_save(original_df: pd.DataFrame, edited_df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows that really changed before 02 Save/Recalc writes Neon.

    This prevents 02 from sending the whole visible table into save_time_records().
    It also preserves the rule requested by the user: when 開始時間戳/結束時間戳
    changes, 開始日期/開始時間/結束日期/結束時間 are synchronized first, then
    only those changed rows are saved and recalculated.
    """
    edited_norm = _v82_history_normalize_compare_frame(edited_df)
    original_norm = _v82_history_normalize_compare_frame(original_df)
    if edited_norm.empty:
        return pd.DataFrame(columns=getattr(edited_df, "columns", []))
    if "id" not in edited_norm.columns or "id" not in original_norm.columns:
        return edited_df.copy().reset_index(drop=True)

    old_map = {}
    for _, row in original_norm.iterrows():
        try:
            rid = int(float(str(row.get("id")).strip()))
        except Exception:
            continue
        old_map[rid] = row

    changed_indices: list[int] = []
    compare_cols = [c for c in edited_norm.columns if c in original_norm.columns and c not in _V82_HISTORY_SAVE_IGNORE_COLS]
    for idx, row in edited_norm.iterrows():
        try:
            rid = int(float(str(row.get("id")).strip()))
        except Exception:
            changed_indices.append(idx)
            continue
        old = old_map.get(rid)
        if old is None:
            changed_indices.append(idx)
            continue
        for col in compare_cols:
            if _v82_norm_compare_cell(row.get(col)) != _v82_norm_compare_cell(old.get(col)):
                changed_indices.append(idx)
                break
    if not changed_indices:
        return pd.DataFrame(columns=edited_df.columns)
    return edited_df.loc[changed_indices].copy().reset_index(drop=True)


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




# ===================== V88 02 HISTORY EXPLICIT COLUMN SETTINGS =====================
def _v88_safe_widget_part(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", str(text or "table")).strip("_") or "table"


def _v88_current_column_order(table_key: str, df: pd.DataFrame) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    current = [str(c) for c in df.columns]
    current_set = set(current)
    try:
        saved = [str(c) for c in load_column_order(table_key)]
    except Exception:
        saved = []
    out: list[str] = []
    seen: set[str] = set()
    for col in saved:
        if col in current_set and col not in seen:
            out.append(col)
            seen.add(col)
    for col in current:
        if col not in seen:
            out.append(col)
            seen.add(col)
    return out


def _v88_render_history_column_settings(table_key: str, df: pd.DataFrame, title: str) -> None:
    """Explicit 02 history column order/width settings.

    V100: this panel must not build the heavy text_area + width data_editor during
    every history query refresh.  Streamlit executes expander contents even when
    the expander is collapsed, so the old implementation rebuilt the column
    settings editor immediately after the user pressed 「查詢 / 重新整理歷史明細」.
    That made the page look like the data query was still running.

    The new implementation shows a lightweight header by default and creates the
    settings editor only when the user explicitly checks 「開啟欄位設定編輯器」.
    Permanent settings are still read by table_ui_service when rendering the table
    and are still written only when Apply is pressed.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return
    safe_key = _v88_safe_widget_part(table_key)
    current_cols = [str(c) for c in df.columns]

    with st.expander(title, expanded=False):
        st.caption("此區只管理 02 歷史明細表格的欄位順序與欄寬；不會修改工時資料。只有按下『套用並永久儲存欄位設定』才會寫入。")
        open_editor = st.checkbox(
            "開啟欄位設定編輯器 / Open column settings editor",
            value=False,
            key=f"v100_history_column_settings_open_{safe_key}",
        )
        if not open_editor:
            st.caption(f"目前表格共有 {len(current_cols)} 個欄位。為避免查詢歷史明細時重建欄位設定編輯器，請需要調整時再開啟。")
            return

        # Only load the persisted order/widths after the user explicitly opens the
        # settings editor.  The table itself still applies cached/persisted settings
        # through table_ui_service, so Reboot persistence is not affected.
        try:
            widths = {str(k): int(v) for k, v in load_widths(table_key).items()}
        except Exception:
            widths = {}
        ordered = _v88_current_column_order(table_key, df) or current_cols
        settings_rows = []
        for col in ordered:
            if col in current_cols:
                settings_rows.append({"欄位 / Column": col, "欄寬 / Width": int(widths.get(col, 140))})
        if not settings_rows:
            settings_rows = [{"欄位 / Column": c, "欄寬 / Width": int(widths.get(c, 140))} for c in current_cols]

        with st.form(f"v88_history_column_settings_form_{safe_key}", clear_on_submit=False):
            order_text = st.text_area(
                "欄位順序 / Column order（每行一個欄位；上方越前面越靠左）",
                value="\n".join([str(r["欄位 / Column"]) for r in settings_rows]),
                height=190,
                key=f"v88_history_column_order_text_{safe_key}",
            )
            try:
                width_df = st.data_editor(
                    pd.DataFrame(settings_rows),
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed",
                    key=f"v88_history_width_editor_{safe_key}",
                    column_config={
                        "欄位 / Column": st.column_config.Column("欄位 / Column"),
                        "欄寬 / Width": st.column_config.NumberColumn("欄寬 / Width", min_value=60, max_value=700, step=10),
                    },
                    disabled=["欄位 / Column"],
                    height=260,
                )
            except Exception:
                width_df = pd.DataFrame(settings_rows)
                st.caption("欄寬表格暫時無法載入，將沿用目前欄寬。")
            b1, b2 = st.columns([1.5, 1])
            apply_settings = b1.form_submit_button("✅ 套用並永久儲存欄位設定 / Apply & Save", type="primary", use_container_width=True)
            reset_settings = b2.form_submit_button("↺ 恢復預設順序 / Reset order", use_container_width=True)

        if apply_settings:
            raw_order = [x.strip() for x in str(order_text or "").splitlines() if x.strip()]
            seen: set[str] = set()
            clean_order: list[str] = []
            for col in raw_order:
                if col in current_cols and col not in seen:
                    clean_order.append(col)
                    seen.add(col)
            for col in current_cols:
                if col not in seen:
                    clean_order.append(col)
                    seen.add(col)
            clean_widths: dict[str, int] = {}
            try:
                for _, row in width_df.iterrows():
                    col = str(row.get("欄位 / Column", "")).strip()
                    if col not in current_cols:
                        continue
                    try:
                        width = int(float(row.get("欄寬 / Width", 140)))
                    except Exception:
                        width = 140
                    clean_widths[col] = max(60, min(700, width))
            except Exception:
                clean_widths = {c: int(widths.get(c, 140)) for c in current_cols}
            try:
                save_widths(table_key, clean_widths)
                save_column_order(table_key, clean_order)
                st.success("02 歷史明細欄位設定已套用並永久儲存。")
                st.rerun()
            except Exception as exc:
                st.error(f"欄位設定儲存失敗：{exc}")
        elif reset_settings:
            try:
                save_column_order(table_key, current_cols)
                save_widths(table_key, {c: int(widths.get(c, 140)) for c in current_cols})
                st.success("已恢復 02 歷史明細預設欄位順序。")
                st.rerun()
            except Exception as exc:
                st.error(f"恢復預設失敗：{exc}")
# =================== END V88 02 HISTORY EXPLICIT COLUMN SETTINGS ===================

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

    work_order_vals = _v30108_history_effective_work_orders(filters)
    if work_order_vals and "work_order" in out.columns:
        out = _apply_history_exact_text_filter(out, "work_order", work_order_vals)
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

    # Join employee master fields only when department/title filters are actually used.
    # V71: loading and merging the employee master on every 02 query made the refresh path slow
    # even when the user did not filter by department/title.
    if filters.get("departments") or filters.get("titles"):
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


def _render_history_filter_panel(base_df: pd.DataFrame, employees: pd.DataFrame, work_orders: pd.DataFrame, option_values: dict | None = None) -> tuple[pd.DataFrame, dict]:
    stored = _v30027_load_history_filters_cached()
    if "history_filters_applied_v216" not in st.session_state:
        st.session_state["history_filters_applied_v216"] = stored
    applied = st.session_state["history_filters_applied_v216"]
    _render_v30107_history_filter_input_text_css()

    start_default, end_default = _date_range_from_preset(
        applied.get("date_preset", V30091_HISTORY_DEFAULT_PRESET),
        applied.get("start_date"),
        applied.get("end_date"),
    )

    with st.expander("⌕ 專業篩選 / Professional Filters", expanded=True):
        with st.form("history_professional_filter_form", clear_on_submit=False):
            r1c1, r1c2, r1c3, r1c4 = st.columns([1, 1, 1, 1])
            date_preset = r1c1.selectbox(
                "快速日期",
                ["今日", "近7天", "近30天", "近90天", "本月", "上月", "自訂區間"],
                index=["今日", "近7天", "近30天", "近90天", "本月", "上月", "自訂區間"].index(applied.get("date_preset", V30091_HISTORY_DEFAULT_PRESET)) if applied.get("date_preset", V30091_HISTORY_DEFAULT_PRESET) in ["今日", "近7天", "近30天", "近90天", "本月", "上月", "自訂區間"] else 0,
            )
            start_input = r1c2.date_input("開始日期", value=start_default)
            end_input = r1c3.date_input("結束日期", value=end_default)
            detail_default = min(V71_HISTORY_INTERACTIVE_MAX_ROWS, max(50, int(applied.get("detail_limit") or 300)))
            detail_limit = r1c4.number_input("每頁筆數 / Page Size（原明細讀取上限）", min_value=50, max_value=V71_HISTORY_INTERACTIVE_MAX_ROWS, value=detail_default, step=50)

            # V253: build options from SQL DISTINCT values when available, not full history rows.
            _opt = option_values or {}
            saved_manual_work_orders = _v30108_history_manual_work_orders_for_widget(applied)
            saved_bulk_work_orders = _v30108_history_bulk_work_orders_from_filters(applied)
            wo_options = _merge_options(_safe_unique(work_orders, "work_order"), list(_opt.get("work_order", [])) or _safe_unique(base_df, "work_order"), saved_manual_work_orders)
            pn_options = _merge_options(_safe_unique(work_orders, "part_no"), list(_opt.get("part_no", [])) or _safe_unique(base_df, "part_no"))
            type_options = _merge_options(_safe_unique(work_orders, "type_name"), list(_opt.get("type_name", [])) or _safe_unique(base_df, "type_name"))
            loc_options = _merge_options(_safe_unique(work_orders, "assembly_location"), list(_opt.get("assembly_location", [])) or _safe_unique(base_df, "assembly_location"))
            process_options = _merge_options(list(_opt.get("process_name", [])), _safe_unique(base_df, "process_name"), applied.get("process_names", []))
            emp_id_options = _merge_options(_safe_unique(employees, "employee_id"), list(_opt.get("employee_id", [])) or _safe_unique(base_df, "employee_id"))
            emp_name_options = _merge_options(_safe_unique(employees, "employee_name"), list(_opt.get("employee_name", [])) or _safe_unique(base_df, "employee_name"))
            dept_options = _safe_unique(employees, "department")
            title_options = _safe_unique(employees, "title")
            status_options = _merge_options(list(_opt.get("status", [])), _safe_unique(base_df, "status"), V30070_HISTORY_STATUS_FALLBACK, applied.get("statuses", []))

            r2c1, r2c2, r2c3 = st.columns(3)
            work_orders_selected = r2c1.multiselect("製令", wo_options, default=[x for x in saved_manual_work_orders if x in wo_options])
            part_nos = r2c2.multiselect("P/N / 料號", pn_options, default=[x for x in applied.get("part_nos", []) if x in pn_options])
            type_names = r2c3.multiselect("機型", type_options, default=[x for x in applied.get("type_names", []) if x in type_options])

            paste_work_orders_raw = st.text_area(
                "批量貼上製令 / Paste Work Orders",
                value="\n".join(saved_bulk_work_orders),
                height=118,
                placeholder="可直接從 Excel / 表格複製製令欄貼上；支援一行一筆、Tab、逗號或分號分隔。貼上清單會獨立套用，不會塞回上方多選框造成版面重疊。",
                key="history_work_order_paste_v30108",
            )
            pasted_work_orders = _parse_pasted_history_work_order_filters(paste_work_orders_raw)
            if pasted_work_orders:
                preview = "、".join(pasted_work_orders[:6])
                more = f"...等 {len(pasted_work_orders)} 筆" if len(pasted_work_orders) > 6 else ""
                st.caption(f"已解析 {len(pasted_work_orders)} 筆貼上製令：{preview}{more}。此清單會作為獨立篩選，不會顯示成上方多選框 chip。")

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
            with b1:
                apply_clicked = st.form_submit_button("⌕ 套用篩選並永久記錄", type="primary", use_container_width=True)
            with b2:
                reset_clicked = st.form_submit_button("↺ 恢復預設篩選", use_container_width=True)
        if reset_clicked:
            new_filters = _v30027_reset_history_filters_cached()
            st.session_state["history_filters_applied_v216"] = new_filters
            st.session_state[V259_HISTORY_QUERY_REQUESTED_KEY] = False
            _v30086_clear_history_page_cache(reset_page=True)
            _add_history_result("success", "已恢復 02｜歷史紀錄預設篩選；歷史明細不會自動載入，請按查詢。", append=False)
            rerun()

        if apply_clicked:
            actual_start, actual_end = _date_range_from_preset(date_preset, str(start_input), str(end_input))
            if date_preset == "自訂區間":
                actual_start, actual_end = start_input, end_input
            new_filters = {
                "date_preset": date_preset,
                "start_date": str(actual_start),
                "end_date": str(actual_end),
                "work_orders": _merge_filter_lists(work_orders_selected),
                "work_orders_pasted": _merge_filter_lists(pasted_work_orders),
                "work_orders_effective": _v30109_history_make_effective_work_orders(work_orders_selected, pasted_work_orders),
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
            saved = _v30027_save_history_filters_cached(new_filters)
            st.session_state["history_filters_applied_v216"] = saved
            st.session_state[V259_HISTORY_QUERY_REQUESTED_KEY] = True
            _v30086_clear_history_page_cache(reset_page=True)
            _add_history_result("success", "已套用篩選條件，正在載入本次查詢結果。", append=False)
            rerun()

    applied = st.session_state["history_filters_applied_v216"]
    filtered = _apply_history_filters(base_df, applied)
    return filtered, applied


employees = load_employees(active_only=False)
work_orders = load_work_orders(active_only=False)

# V2.16：02 歷史紀錄改為專業篩選。先依日期範圍載入，再在畫面層套用多條件篩選；
# 篩選條件只有按「套用篩選並永久記錄」才寫入永久檔。
_history_filter_seed = _v30027_load_history_filters_cached()
_seed_start, _seed_end = _date_range_from_preset(
    _history_filter_seed.get("date_preset", V30091_HISTORY_DEFAULT_PRESET),
    _history_filter_seed.get("start_date"),
    _history_filter_seed.get("end_date"),
)
# V259: 02 must not load heavy history rows simply because the page is opened.
# Filter options use 03/04 master data first; history rows are loaded only after
# the user presses "套用篩選並永久記錄" or the manual refresh button below.
_history_option_values = _v30070_load_history_filter_options_cached(_seed_start, _seed_end)
base_df = pd.DataFrame()
_panel_df, history_filters = _render_history_filter_panel(base_df, employees, work_orders, _history_option_values)
history_filters = _v79_effective_history_filters(history_filters)

# V300.87: deployment changes must invalidate old pagination totals.
# Streamlit sessions can keep V300.86 values such as total_count=100 even after
# the user changes Top N back to 全部.  Clear only query-page caches, not saved
# filter settings.
if st.session_state.get(V30087_HISTORY_PAGINATION_VERSION_KEY) != V30087_HISTORY_PAGINATION_VERSION:
    st.session_state[V30087_HISTORY_PAGINATION_VERSION_KEY] = V30087_HISTORY_PAGINATION_VERSION
    _v30086_clear_history_page_cache(reset_page=True)

hr1, hr2, hr3 = st.columns([1.2, 1.2, 3])
manual_query_clicked = hr1.button("查詢 / 重新整理歷史明細", type="primary", use_container_width=True, key="v259_history_manual_query")
clear_history_cache_clicked = hr2.button("清除歷史查詢快取", use_container_width=True, key="v259_history_clear_cache")
with hr3:
    if st.session_state.get(V259_HISTORY_TS_KEY):
        st.caption(f"目前顯示快取查詢結果，最後刷新：{st.session_state.get(V259_HISTORY_TS_KEY)}。")
    else:
        st.caption("V259：歷史明細不再於開頁自動載入；請先設定條件，再按查詢。")
if clear_history_cache_clicked:
    st.session_state[V259_HISTORY_QUERY_REQUESTED_KEY] = False
    _v30086_clear_history_page_cache(reset_page=True)
    _add_history_result("success", "已清除歷史查詢快取。", append=False)
    rerun()
if manual_query_clicked:
    st.session_state[V259_HISTORY_QUERY_REQUESTED_KEY] = True
    _v30086_clear_history_page_cache(reset_page=True)

_query_requested = bool(st.session_state.get(V259_HISTORY_QUERY_REQUESTED_KEY))
_filter_sig = _v30086_history_filter_signature(history_filters)
if st.session_state.get(V30086_HISTORY_FILTER_SIG_KEY) != _filter_sig:
    st.session_state[V30086_HISTORY_FILTER_SIG_KEY] = _filter_sig
    _v30086_clear_history_page_cache(reset_page=True)

_page_size = _v30086_history_page_size(history_filters)
_current_page = max(1, int(st.session_state.get(V30086_HISTORY_PAGE_KEY, 1) or 1))
_total_count = int(st.session_state.get(V30086_HISTORY_TOTAL_KEY, 0) or 0)
_total_is_exact = True

if _query_requested and callable(count_history_records_sql_filtered) and V30086_HISTORY_TOTAL_KEY not in st.session_state:
    with st.spinner("正在計算符合條件的歷史紀錄總筆數..."):
        _total_count, _total_is_exact = _v30086_load_history_total_count(history_filters)
        st.session_state[V30086_HISTORY_TOTAL_KEY] = int(_total_count)
        st.session_state["v30086_02_history_total_exact"] = bool(_total_is_exact)
else:
    _total_is_exact = bool(st.session_state.get("v30086_02_history_total_exact", True))

_total_count = int(st.session_state.get(V30086_HISTORY_TOTAL_KEY, _total_count) or 0)
_max_page = max(1, int((_total_count + _page_size - 1) // _page_size)) if _total_count else 1
if _current_page > _max_page:
    _current_page = _max_page
    st.session_state[V30086_HISTORY_PAGE_KEY] = _current_page

if _query_requested:
    pg1, pg2, pg3, pg4, pg5 = st.columns([1, 1, 1.2, 1, 2.2])
    prev_clicked = pg1.button("上一頁 / Prev", use_container_width=True, key="v30086_history_prev_page", disabled=_current_page <= 1)
    next_clicked = pg2.button("下一頁 / Next", use_container_width=True, key="v30086_history_next_page", disabled=_current_page >= _max_page)
    jump_page = pg3.number_input("頁碼 / Page", min_value=1, max_value=max(1, _max_page), value=_current_page, step=1, key="v30086_history_jump_page_input")
    go_clicked = pg4.button("跳頁 / Go", use_container_width=True, key="v30086_history_go_page")
    with pg5:
        count_label = "總筆數" if _total_is_exact else "候選筆數"
        _legacy_top = _v71_top_n_limit(history_filters)
        _top_note = "；Top N 不再限制分頁總筆數" if _legacy_top else ""
        st.caption(f"{count_label}：{_total_count:,}；每頁：{_page_size:,}；目前第 {_current_page:,} / {_max_page:,} 頁{_top_note}。")
    if prev_clicked:
        st.session_state[V30086_HISTORY_PAGE_KEY] = max(1, _current_page - 1)
        st.session_state.pop(V259_HISTORY_DF_KEY, None)
        st.session_state.pop(V259_HISTORY_TS_KEY, None)
        rerun()
    if next_clicked:
        st.session_state[V30086_HISTORY_PAGE_KEY] = min(_max_page, _current_page + 1)
        st.session_state.pop(V259_HISTORY_DF_KEY, None)
        st.session_state.pop(V259_HISTORY_TS_KEY, None)
        rerun()
    if go_clicked:
        st.session_state[V30086_HISTORY_PAGE_KEY] = max(1, min(_max_page, int(jump_page)))
        st.session_state.pop(V259_HISTORY_DF_KEY, None)
        st.session_state.pop(V259_HISTORY_TS_KEY, None)
        rerun()

df = st.session_state.get(V259_HISTORY_DF_KEY, pd.DataFrame())
_query_not_loaded = (not isinstance(df, pd.DataFrame)) or (isinstance(df, pd.DataFrame) and df.empty and not st.session_state.get(V259_HISTORY_TS_KEY))
if _query_requested and _query_not_loaded:
    with st.spinner(f"正在查詢歷史明細第 {_current_page} 頁，已套用伺服器端分頁..."):
        df = _v30086_load_history_page(history_filters, page=_current_page, page_size=_page_size)
        st.session_state[V259_HISTORY_DF_KEY] = df
        st.session_state[V259_HISTORY_TS_KEY] = _v259_now_label()
if not isinstance(df, pd.DataFrame):
    df = pd.DataFrame()

start = history_filters.get("start_date", str(_seed_start))
end = history_filters.get("end_date", str(_seed_end))

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("當頁 / 總筆數", f"{len(df):,} / {_total_count:,}" if _query_requested and _total_count else f"{len(df):,}")
m2.metric("總工時 / Total Time", _safe_work_hours_total_hms(df))
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

    # V90：02 歷史明細欄位設定。
    # 刪除 / Delete、重算 / Recalc 是編輯模式才會出現的操作欄位，
    # 但也必須列入同一份永久欄位順序設定，否則現場無法調整它們的位置。
    # 因此有編輯權限時，設定面板用 include_action_cols=True 建立欄位清單；
    # 唯讀表格沒有這兩欄時，table_ui_service 會自動略過不存在欄位，
    # 編輯表格出現這兩欄時則套用同一份永久順序與欄寬。
    _history_width_df = (
        _prepare_history_display_df(df.head(1), include_action_cols=bool(can_edit))
        if isinstance(df, pd.DataFrame)
        else pd.DataFrame()
    )
    if not _history_width_df.empty:
        try:
            _v88_render_history_column_settings(
                "history_records",
                _history_width_df,
                title="▤ 02 歷史明細欄位設定 / History Records Column Settings",
            )
        except Exception as _history_width_exc:
            st.caption(f"欄位設定暫時無法載入：{_history_width_exc}")

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
            # V80: after Save/Recalc/Delete, force the cached detail table to be
            # reloaded from the Neon authority on the next rerun.  This keeps
            # 01/02 linked: start_date/start_time/end_date/end_time edits rebuild
            # timestamps in the service, then 02 displays the canonical values.
            st.session_state.pop(V259_HISTORY_DF_KEY, None)
            st.session_state.pop(V259_HISTORY_TS_KEY, None)
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
            st.info(
                "V97：歷史明細編輯已改為表單暫存模式；在表格內編輯不會立即查詢、重算或寫入 Neon，"
                "只有按下下方『儲存 / 重算 / 刪除』確認按鈕後才會執行。"
            )

            # V97: keep the data_editor inside a Streamlit form.  Without a form,
            # every cell edit triggers a full Streamlit rerun; this rebuilds the
            # history table, column settings, metrics and query cache and makes the
            # page look like it is calculating while the user is still typing.  A
            # form buffers edits on the frontend and sends the edited dataframe only
            # when one of the confirm buttons is pressed.
            form_key = f"history_records_commit_form_v97_{st.session_state[editor_version_key]}"
            with st.form(form_key, clear_on_submit=False):
                edited = render_table(
                    edit_df,
                    "history_records",
                    editable=True,
                    disabled=["id", "record_key", "created_at", "updated_at", HISTORY_CROSS_DAY_ALERT_COL, HISTORY_CROSS_DAY_RANGE_COL],
                    key=editor_key,
                    height=560,
                )
                st.markdown("**確認後執行動作 / Confirm Action**")
                hist_save_col, hist_recalc_col, hist_delete_col = st.columns([1.1, 1.7, 1.2])
                history_save_clicked = hist_save_col.form_submit_button(
                    "◈ 儲存編輯 / Save",
                    type="primary",
                    use_container_width=True,
                )
                history_recalc_clicked = hist_recalc_col.form_submit_button(
                    "◇ 重算勾選工時 / Recalc Selected",
                    type="primary",
                    use_container_width=True,
                )
                history_delete_clicked = hist_delete_col.form_submit_button(
                    "◉ 刪除勾選整列 / Delete Selected",
                    type="primary",
                    use_container_width=True,
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
                if isinstance(edited, pd.DataFrame):
                    st.session_state[history_draft_key] = edited.copy()
                else:
                    edited = st.session_state.get(history_draft_key)
                if edited is None or not isinstance(edited, pd.DataFrame):
                    _add_history_result("warning", "找不到可儲存的歷史紀錄表格內容，請重新載入後再試。", append=False)
                    rerun()
                def _checked_ids(frame: pd.DataFrame, col: str) -> list[int]:
                    try:
                        from services.history_delete_repair_service import checked_ids_from_editor
                        got = checked_ids_from_editor(frame, col)
                        if got:
                            return got
                    except Exception:
                        pass
                    if frame is None or frame.empty or col not in frame.columns:
                        return []
                    id_col = "id" if "id" in frame.columns else ("ID / ID" if "ID / ID" in frame.columns else ("ID" if "ID" in frame.columns else None))
                    if not id_col:
                        return []
                    try:
                        mask = frame[col].map(lambda v: str(v).strip().lower() in {"true", "1", "yes", "y", "on", "勾選", "是"} if not isinstance(v, bool) else v)
                        return [int(float(str(x))) for x in frame.loc[mask, id_col].dropna().tolist()]
                    except Exception:
                        return []

                delete_ids = sorted(set(_checked_ids(edited, delete_col_label)))
                recalc_ids = sorted(set(_checked_ids(edited, recalc_col_label)))
                st.session_state[delete_select_key] = delete_ids
                st.session_state[recalc_select_key] = recalc_ids

                if history_action == "儲存編輯":
                    save_df_all = _strip_history_cross_day_display_cols(edited).drop(columns=[delete_col_label, recalc_col_label, "刪除", "重算"], errors="ignore")
                    save_df_all = _v82_sync_timestamp_to_split_columns(save_df_all, df)
                    changed_df = _v82_history_changed_rows_for_save(df, save_df_all)
                    if changed_df.empty:
                        _add_history_result("info", "沒有偵測到實際修改；未寫入 Neon，避免查詢逾時或長時間運轉。", append=False)
                    else:
                        count = save_time_records(changed_df, recalc_edited_timestamps=True)
                        _add_history_result("success", f"已儲存 {count} 筆歷史紀錄，並已依最新開始/結束時間重算工時、寫入修改紀錄與同步作業平均。", append=False)
                    _history_refresh_editor()
                    rerun()
                elif history_action == "重新計算勾選紀錄工時":
                    if not recalc_ids:
                        _add_history_result("warning", "請先在『重算』欄勾選要重新計算的紀錄，再按確認執行。", append=False)
                        rerun()
                    else:
                        save_df_all = _strip_history_cross_day_display_cols(edited).drop(columns=[delete_col_label, recalc_col_label, "刪除", "重算"], errors="ignore")
                        save_df_all = _v82_sync_timestamp_to_split_columns(save_df_all, df)
                        changed_df = _v82_history_changed_rows_for_save(df, save_df_all)
                        if not changed_df.empty:
                            save_time_records(changed_df, recalc_edited_timestamps=True)
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
                        try:
                            from services.time_record_service import delete_time_records_from_02_history_editor
                            _v199_delete_result = delete_time_records_from_02_history_editor(
                                edited,
                                record_ids=delete_ids,
                                delete_column=delete_col_label,
                                reason="02 歷史紀錄啟動編輯後整列刪除",
                            )
                            count = int((_v199_delete_result or {}).get("deleted_count") or 0)
                        except Exception:
                            count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")
                        # V59: immediately remove deleted rows from the cached result set so the
                        # screen does not look like deletion failed.  The authority source is Neon;
                        # this only updates the current display cache.
                        try:
                            _cached_df = st.session_state.get(V259_HISTORY_DF_KEY)
                            if isinstance(_cached_df, pd.DataFrame) and not _cached_df.empty and "id" in _cached_df.columns:
                                _del_set = {int(x) for x in delete_ids}
                                st.session_state[V259_HISTORY_DF_KEY] = _cached_df.loc[~_cached_df["id"].map(lambda x: int(float(str(x))) if str(x).strip() else -1).isin(_del_set)].copy().reset_index(drop=True)
                        except Exception:
                            st.session_state.pop(V259_HISTORY_DF_KEY, None)
                            st.session_state[V259_HISTORY_QUERY_REQUESTED_KEY] = False
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
        # V100: Streamlit executes all tab bodies, even when the Excel tab is not
        # selected.  The old code generated the current-list xlsx on every history
        # query refresh, so pressing 「查詢 / 重新整理歷史明細」 also paid the Excel
        # export cost before the table appeared.  Build the file only when the user
        # explicitly asks for it.
        export_cache_key = "v100_history_current_export_bytes"
        export_name_key = "v100_history_current_export_name"
        with dl1:
            if st.button("準備目前清單下載 / Prepare Current List", use_container_width=True, key="v100_prepare_history_current_export"):
                export_bio = BytesIO()
                export_df = df.copy()
                with pd.ExcelWriter(export_bio, engine="xlsxwriter") as writer:
                    export_df.to_excel(writer, index=False, sheet_name="歷史紀錄")
                st.session_state[export_cache_key] = export_bio.getvalue()
                st.session_state[export_name_key] = f"SPT_歷史紀錄_{start}_{end}.xlsx"
                _add_history_result("success", "已準備目前清單下載檔。", append=False)
            if st.session_state.get(export_cache_key):
                st.download_button(
                    "下載目前清單 / Download Current List",
                    data=st.session_state.get(export_cache_key),
                    file_name=st.session_state.get(export_name_key, f"SPT_歷史紀錄_{start}_{end}.xlsx"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.caption("需匯出時請先按『準備目前清單下載』，避免查詢歷史明細時同步產生 Excel。")
            st.markdown("---")
            if st.button("準備全部篩選資料下載 / Prepare All Filtered", use_container_width=True, key="v30086_prepare_all_filtered_history_export"):
                with st.spinner("正在分批準備全部符合篩選的歷史紀錄下載檔，不會把全部資料顯示在畫面表格..."):
                    export_all_df = _v30086_prepare_all_filtered_export(history_filters, batch_size=3000, max_rows=100000)
                    export_all_bio = BytesIO()
                    with pd.ExcelWriter(export_all_bio, engine="xlsxwriter") as writer:
                        export_all_df.to_excel(writer, index=False, sheet_name="歷史紀錄")
                    st.session_state[V30086_HISTORY_EXPORT_BYTES_KEY] = export_all_bio.getvalue()
                    st.session_state[V30086_HISTORY_EXPORT_NAME_KEY] = f"SPT_歷史紀錄_全部篩選_{start}_{end}.xlsx"
                    _add_history_result("success", f"已準備全部篩選資料下載檔，共 {len(export_all_df):,} 筆。", append=False)
            if st.session_state.get(V30086_HISTORY_EXPORT_BYTES_KEY):
                st.download_button(
                    "下載全部篩選資料 / Download All Filtered",
                    data=st.session_state.get(V30086_HISTORY_EXPORT_BYTES_KEY),
                    file_name=st.session_state.get(V30086_HISTORY_EXPORT_NAME_KEY, f"SPT_歷史紀錄_全部篩選_{start}_{end}.xlsx"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        with dl2:
            st.download_button(
                "下載歷史紀錄匯入範本 / Download Template",
                data=_v30027_history_template_bytes(),
                file_name="SPT_歷史紀錄匯入範本.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        uploaded = st.file_uploader("上傳歷史紀錄 Excel", type=["xlsx", "xlsm", "xls"], key="history_excel_upload_v197")
        recalc_excel = st.checkbox("匯入時依 13｜系統設定休息時間重新計算工時", value=True, key="history_excel_recalc_v197")
        restore_deleted_excel = st.checkbox(
            "恢復已刪除的相同紀錄 / Restore Deleted Matching Records",
            value=False,
            key="history_excel_restore_deleted_v30089",
            help="預設不勾選，避免正式刪除的歷史紀錄自動復活；只有確認要重新匯入已刪除資料時才勾選。",
        )
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
                st.dataframe(source_df.head(30), use_container_width=True, height=220, key="history_excel_source_preview_v30078")
                for msg in warnings:
                    st.warning(msg)
                if parsed.empty:
                    st.error("解析後沒有可匯入資料。請確認至少包含：工號、製令、工段、開始時間。")
                else:
                    st.success(f"已解析 {len(parsed)} 筆歷史工時資料。")
                    st.info("請先確認下方解析結果。按『確認匯入 Excel 歷史紀錄』後，結果會永久顯示在頁面上方。")
                    if st.button("⟟ 確認匯入 Excel 歷史紀錄 / Import Excel History", type="primary", use_container_width=True, key="history_excel_import_save_v242_top"):
                        import_df = st.session_state.get(HISTORY_IMPORT_PREVIEW_KEY, parsed).copy()
                        result = _v30080_import_with_progress(import_df, recalc=recalc_excel, source="history_excel_import", label="Excel 歷史紀錄匯入", restore_deleted_matching_records=restore_deleted_excel)
                        _parallel_note = f"，同時作業 {int(result.get('parallel_groups', 0) or 0)} 組 / {int(result.get('parallel_records', 0) or 0)} 筆" if int(result.get('parallel_records', 0) or 0) else ""
                        _identity_note = f"，身分鍵既有比對 {int(result.get('identity_matches', 0) or 0)} 筆" if int(result.get('identity_matches', 0) or 0) else ""
                        _db_dup_note = f"，資料庫防重略過 {int(result.get('db_duplicate_skipped', 0) or 0)} 筆" if int(result.get('db_duplicate_skipped', 0) or 0) else ""
                        _deleted_skip_note = f"，已刪除紀錄略過 {int(result.get('deleted_skipped', 0) or 0)} 筆" if int(result.get('deleted_skipped', 0) or 0) else ""
                        _restore_note = f"，恢復已刪除 {int(result.get('restored_deleted', 0) or 0)} 筆" if int(result.get('restored_deleted', 0) or 0) else ""
                        _batch_note = f"，預計新增 {int(result.get('to_insert', 0) or 0)}，預計更新 {int(result.get('to_update', 0) or 0)}，分批 {int(result.get('batch_size', 0) or 0)} 筆/批，用時 {_v30080_format_seconds(float(result.get('duration_seconds', 0) or 0))}"
                        _add_history_result("success", f"Excel 匯入完成：新增 {result['inserted']}，更新 {result['updated']}{_restore_note}，略過 {result['skipped']}{_deleted_skip_note}{_parallel_note}{_identity_note}{_db_dup_note}{_batch_note}。", append=False)
                        for msg in result.get("errors", [])[:20]:
                            _add_history_result("warning", msg)
                        if result.get("inserted", 0) or result.get("updated", 0) or result.get("restored_deleted", 0):
                            _focus_filter_to_import_rows(import_df, "Excel 匯入資料")
                            rerun()
                        else:
                            if result.get("duplicate_only") or int(result.get("skipped", 0) or 0) > 0:
                                if int(result.get("deleted_skipped", 0) or 0):
                                    _add_history_result("info", "本次沒有新增或更新，因為匯入資料符合先前已刪除的紀錄，預設已略過以避免刪除資料自動復活；若確認要重新匯入，請勾選『恢復已刪除的相同紀錄』後再匯入。")
                                else:
                                    _add_history_result("info", "本次沒有新增或更新，因為匯入資料已被防重機制判定為既有/重複紀錄；這不是欄位解析錯誤。若要確認資料是否已存在，請使用匯入日期區間查詢。")
                                _focus_filter_to_import_rows(import_df, "Excel 匯入資料")
                            else:
                                _add_history_result("warning", "這次沒有寫入任何資料。請確認解析預覽中的工號、製令、工段名稱、開始時間戳是否正確。")
                            rerun()
                    st.dataframe(parsed, use_container_width=True, height=360, key="history_excel_parsed_preview_v30078")
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
        restore_deleted_paste = st.checkbox(
            "貼上匯入時恢復已刪除的相同紀錄 / Restore Deleted Matching Records",
            value=False,
            key="history_paste_restore_deleted_v30089",
            help="預設不勾選，避免正式刪除的歷史紀錄自動復活；只有確認要重新匯入已刪除資料時才勾選。",
        )
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
                    result = _v30080_import_with_progress(import_df, recalc=recalc_paste, source="history_paste_import", label="貼上歷史紀錄匯入", restore_deleted_matching_records=restore_deleted_paste)
                    _parallel_note = f"，同時作業 {int(result.get('parallel_groups', 0) or 0)} 組 / {int(result.get('parallel_records', 0) or 0)} 筆" if int(result.get('parallel_records', 0) or 0) else ""
                    _identity_note = f"，身分鍵既有比對 {int(result.get('identity_matches', 0) or 0)} 筆" if int(result.get('identity_matches', 0) or 0) else ""
                    _db_dup_note = f"，資料庫防重略過 {int(result.get('db_duplicate_skipped', 0) or 0)} 筆" if int(result.get('db_duplicate_skipped', 0) or 0) else ""
                    _deleted_skip_note = f"，已刪除紀錄略過 {int(result.get('deleted_skipped', 0) or 0)} 筆" if int(result.get('deleted_skipped', 0) or 0) else ""
                    _restore_note = f"，恢復已刪除 {int(result.get('restored_deleted', 0) or 0)} 筆" if int(result.get('restored_deleted', 0) or 0) else ""
                    _batch_note = f"，預計新增 {int(result.get('to_insert', 0) or 0)}，預計更新 {int(result.get('to_update', 0) or 0)}，分批 {int(result.get('batch_size', 0) or 0)} 筆/批，用時 {_v30080_format_seconds(float(result.get('duration_seconds', 0) or 0))}"
                    _add_history_result("success", f"貼上資料已匯入：新增 {result['inserted']}，更新 {result['updated']}{_restore_note}，略過 {result['skipped']}{_deleted_skip_note}{_parallel_note}{_identity_note}{_db_dup_note}{_batch_note}。", append=False)
                    for msg in result.get("errors", [])[:20]:
                        _add_history_result("warning", msg)
                    if result.get("inserted", 0) == 0 and result.get("updated", 0) == 0 and result.get("restored_deleted", 0) == 0:
                        if result.get("duplicate_only") or int(result.get("skipped", 0) or 0) > 0:
                            if int(result.get("deleted_skipped", 0) or 0):
                                _add_history_result("info", "本次沒有新增或更新，因為貼上資料符合先前已刪除的紀錄，預設已略過以避免刪除資料自動復活；若確認要重新匯入，請勾選『恢復已刪除的相同紀錄』後再匯入。")
                            else:
                                _add_history_result("info", "本次沒有新增或更新，因為貼上資料已被防重機制判定為既有/重複紀錄；這不是欄位解析錯誤。")
                            _focus_filter_to_import_rows(parsed, "貼上匯入資料")
                        else:
                            _add_history_result("warning", "這次沒有寫入任何資料。請確認解析預覽中的工號、製令、工段名稱、開始時間戳是否正確。")
                    else:
                        # 不可在 text_area 建立後直接改同一個 session_state key，
                        # 否則 Streamlit 會拋 StreamlitAPIException。
                        # 改用 key version 方式，成功匯入後下一次 rerun 產生新輸入框，達到清空效果。
                        st.session_state[paste_raw_version_key] = int(st.session_state.get(paste_raw_version_key, 0)) + 1
                        _focus_filter_to_import_rows(import_df, "貼上匯入資料")
                    rerun()
                st.caption("匯入前預覽 / Parsed Preview")
                st.dataframe(parsed, use_container_width=True, height=360, key="history_paste_parsed_preview_v30078")
        else:
            st.info("請先貼上 Excel 資料。")

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

