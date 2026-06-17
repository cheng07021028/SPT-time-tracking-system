# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
import io
import json
import os
import uuid

import pandas as pd
import streamlit as st

from services.timezone_service import today_date
try:
    from services.timezone_service import now_text as _tz_now_text
except Exception:  # pragma: no cover
    _tz_now_text = None

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.crud_table_service import load_employees, save_employees
from services.time_record_service import load_records, load_daily_record_summary_sql
try:
    from services.time_record_service import load_daily_record_employee_index_sql
except Exception:  # pragma: no cover
    load_daily_record_employee_index_sql = None
from services.table_ui_service import render_table
try:
    from services.table_ui_service import render_width_settings, apply_column_order, load_widths
except Exception:
    def render_width_settings(table_key, df, title="欄位設定 / Column Settings（永久保存)"):
        return None
    def apply_column_order(table_key, df):
        return df
    def load_widths(table_key):
        return {}


# V300.68：07 本頁已在表格前方自行渲染新版欄位設定面板。
# 若再經過全域 column_settings_service 的 monkey patch，畫面會多出第二個
# 「欄位設定 / Column Settings」。本頁兩個主要 data_editor 改用原始
# Streamlit data_editor（若全域 patch 尚未安裝，st.data_editor 本身就是原始函式），
# 只避免重複欄位設定，不改資料儲存、計算或 UI/CSS/theme。
def _v30068_page_owned_data_editor(*args, **kwargs):
    try:
        from services import column_settings_service as _column_settings_service
        original_editor = getattr(_column_settings_service, "_ORIGINAL_DATA_EDITOR", None)
        if callable(original_editor):
            return original_editor(*args, **kwargs)
    except Exception:
        pass
    return st.data_editor(*args, **kwargs)

st.set_page_config(page_title="07. 今日未紀錄名單", page_icon="⟁️", layout="wide")
apply_theme()
require_module_access("07_missing")
render_header(
    "07｜今日未紀錄名單",
    "每日出勤紀錄、未紀錄工時人員查詢、Excel 匯出｜永久保存且穩定編輯。",
)

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("07", "今日未紀錄名單")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


STATE_KEY = "v202_today_attendance_editor"
EDITOR_REV_KEY = "v202_today_attendance_editor_rev"
EDITOR_IGNORE_RETURN_KEY = "v263_today_attendance_ignore_next_editor_return"
COLS = [
    "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "include_in_missing_records", "note", "created_at", "updated_at",
]

# V61：今日出勤維護表格也使用與 10｜權限管理相同的中英雙語實際欄名。
DISPLAY_COLUMNS = {
    "id": "ID / ID",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "is_active": "啟用 / Active",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "今日出勤 / Today Attendance",
    "include_in_missing_records": "納入未紀錄統計 / Include Missing",
    "note": "備註 / Note",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
}
DISPLAY_TO_INTERNAL = {v: k for k, v in DISPLAY_COLUMNS.items()}
DISPLAY_ROW_NO = "序號 / No."
# V66：07 頁不再把 SQLite id 直接當成畫面主鍵顯示。
# 人員永久檔若來自 JSON / GitHub，id 可能為 None；實際儲存會以 employee_id 做 UPSERT，
# 所以畫面改顯示穩定序號，避免出現整欄 None 被誤判為缺資料或按鈕失效。
EDITOR_COLS = [DISPLAY_ROW_NO] + [DISPLAY_COLUMNS[c] for c in COLS if c != "id"]
BOOL_INTERNAL_COLS = ["is_active", "is_in_factory", "is_today_attendance", "include_in_missing_records"]

# ===== V234：07 每日出勤紀錄表｜永久紀錄 + 穩定編輯 START =====
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAILY_MODULE_KEY = "07_daily_attendance_records"
DAILY_DIR = PROJECT_ROOT / "data" / "permanent_store" / "modules" / DAILY_MODULE_KEY
DAILY_RECORDS_PATH = DAILY_DIR / "records.json"
DAILY_HISTORY_DIR = DAILY_DIR / "history"
DAILY_EVENT_PATH = DAILY_DIR / "events.jsonl"

DAILY_STATE_KEY = "v234_07_daily_attendance_editor_df"
DAILY_DATE_KEY = "v234_07_daily_attendance_selected_date"
DAILY_REV_KEY = "v234_07_daily_attendance_editor_rev"
DAILY_LAST_DATE_KEY = "v234_07_daily_attendance_last_loaded_date"
DAILY_MESSAGE_KEY = "v234_07_daily_attendance_message"
DAILY_LOADED_KEY = "v69_07_daily_attendance_loaded"
MISSING_TODAY_DF_KEY = "v69_07_missing_today_df"
MISSING_TODAY_LOADED_KEY = "v69_07_missing_today_loaded"
MISSING_TODAY_TS_KEY = "v69_07_missing_today_ts"
# V300.93：今日未出勤統計與明細。只使用 04 人員主檔/07 今日出勤暫存，
# 不查 02 歷史整表，也不打 time_records，避免拖慢 01/02。
TODAY_ABSENT_DF_KEY = "v30093_07_today_absent_df"

# V300.32：07 省 Neon Compute 快速路徑。
# - 每日出勤紀錄改優先以「單日 payload」讀寫，避免每次儲存整份歷史 JSON。
# - 所選日期未紀錄名單加入短 TTL session cache，避免同一份出勤表在 rerun 時重複查 time_records。
V30032_DAILY_KIND_PREFIX = "records_by_date"
V30032_SELECTED_MISSING_CACHE_KEY = "v30032_07_selected_missing_cache"
V30032_SELECTED_MISSING_TTL_SECONDS = 15
V30032_DAILY_EXCEL_SIG_KEY = "v30032_daily_attendance_excel_sig"

# V300.55：07 Load/Reload 防止一直運轉快速路徑。
# - Load/Reload 不再多做一次 st.rerun()，避免同一輪載入後又馬上重跑。
# - 舊版全量 records payload 優先用 SQL jsonb 只取指定日期，避免整包 JSON 下載/解析。
# - 未紀錄名單改用 08 共用的輕量每日工時 SQL，不再呼叫 load_records() 讀完整欄位。
V30055_DAILY_LOAD_MESSAGE_KEY = "v30055_07_daily_load_message"

DAILY_COLS = [
    "record_id",
    "attendance_date",
    "employee_id",
    "employee_name",
    "department",
    "title",
    "attendance_status",
    "is_in_factory",
    "is_today_attendance",
    "check_in_time",
    "check_out_time",
    "note",
    "created_at",
    "updated_at",
    "updated_by",
]
DAILY_BOOL_COLS = ["is_in_factory", "is_today_attendance"]
DAILY_DISPLAY_ROW_NO = "序號 / No."
DAILY_DELETE_COL = "刪除 / Delete"
DAILY_DISPLAY_COLUMNS = {
    "record_id": "紀錄ID / Record ID",
    "attendance_date": "日期 / Date",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "attendance_status": "出勤狀態 / Attendance Status",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "出勤 / Attendance",
    "check_in_time": "到廠時間 / Check In",
    "check_out_time": "離廠時間 / Check Out",
    "note": "備註 / Note",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
    "updated_by": "更新者 / Updated By",
}
DAILY_DISPLAY_TO_INTERNAL = {v: k for k, v in DAILY_DISPLAY_COLUMNS.items()}
DAILY_EDITOR_COLS = [
    DAILY_DELETE_COL,
    DAILY_DISPLAY_ROW_NO,
    DAILY_DISPLAY_COLUMNS["employee_id"],
    DAILY_DISPLAY_COLUMNS["employee_name"],
    DAILY_DISPLAY_COLUMNS["department"],
    DAILY_DISPLAY_COLUMNS["title"],
    DAILY_DISPLAY_COLUMNS["attendance_status"],
    DAILY_DISPLAY_COLUMNS["is_in_factory"],
    DAILY_DISPLAY_COLUMNS["is_today_attendance"],
    DAILY_DISPLAY_COLUMNS["check_in_time"],
    DAILY_DISPLAY_COLUMNS["check_out_time"],
    DAILY_DISPLAY_COLUMNS["note"],
    DAILY_DISPLAY_COLUMNS["record_id"],
    DAILY_DISPLAY_COLUMNS["attendance_date"],
    DAILY_DISPLAY_COLUMNS["created_at"],
    DAILY_DISPLAY_COLUMNS["updated_at"],
    DAILY_DISPLAY_COLUMNS["updated_by"],
]


def _now_text() -> str:
    if _tz_now_text is not None:
        try:
            return str(_tz_now_text())
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_default(v: Any) -> Any:
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    return str(v)


def _safe_text(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _v30032_df_signature(df: pd.DataFrame) -> str:
    """Build a small stable signature for cache invalidation without touching Neon."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return "empty"
    try:
        work = df.fillna("").astype(str)
        # hash_pandas_object is fast for the small daily attendance / missing tables.
        h = pd.util.hash_pandas_object(work, index=True).sum()
        return f"{len(work)}:{len(work.columns)}:{int(h)}"
    except Exception:
        return f"{len(df)}:{list(df.columns)}"


def _v30032_clear_daily_output_cache() -> None:
    for key in (
        V30032_SELECTED_MISSING_CACHE_KEY,
        "v69_daily_attendance_excel_bytes",
        "v69_daily_attendance_excel_date",
        V30032_DAILY_EXCEL_SIG_KEY,
    ):
        try:
            st.session_state.pop(key, None)
        except Exception:
            pass


def _date_to_text(v: Any) -> str:
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    txt = _safe_text(v)
    if not txt:
        return today_date().strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(txt, errors="coerce").strftime("%Y-%m-%d")
    except Exception:
        return txt[:10]


def _stable_record_id(attendance_date: str, employee_id: str) -> str:
    d = str(attendance_date or "").replace("-", "") or today_date().strftime("%Y%m%d")
    emp = _safe_text(employee_id)
    if emp:
        clean_emp = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in emp)[:40]
        return f"ATT-{d}-{clean_emp}"
    return f"ATT-{d}-{uuid.uuid4().hex[:12].upper()}"


def _atomic_write_json(path: Path, payload: dict[str, Any], *, reason: str = "write") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 2:
        try:
            DAILY_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            bak = DAILY_HISTORY_DIR / f"records_{stamp}_{reason}.json"
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    txt = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    tmp.write_text(txt, encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def _read_daily_payload() -> dict[str, Any]:
    try:
        if DAILY_RECORDS_PATH.exists() and DAILY_RECORDS_PATH.stat().st_size > 2:
            payload = json.loads(DAILY_RECORDS_PATH.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def _extract_daily_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(r) for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables")
    if isinstance(tables, dict):
        rows = tables.get("daily_attendance") or tables.get("records")
        if isinstance(rows, list):
            return [dict(r) for r in rows if isinstance(r, dict)]
    for key in ("records", "rows", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(r) for r in rows if isinstance(r, dict)]
    return []


def _normalise_daily_rows(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        x = {c: r.get(c, "") for c in DAILY_COLS}
        x["attendance_date"] = _date_to_text(x.get("attendance_date"))
        x["employee_id"] = _safe_text(x.get("employee_id"))
        x["employee_name"] = _safe_text(x.get("employee_name"))
        # 空白新增列不保存。
        if not x["employee_id"] and not x["employee_name"]:
            continue
        rid = _safe_text(x.get("record_id")) or _stable_record_id(x["attendance_date"], x["employee_id"])
        if rid in seen:
            rid = f"{rid}-{uuid.uuid4().hex[:6].upper()}"
        seen.add(rid)
        x["record_id"] = rid
        x["department"] = _safe_text(x.get("department"))
        x["title"] = _safe_text(x.get("title"))
        x["attendance_status"] = _safe_text(x.get("attendance_status")) or "出勤"
        for c in DAILY_BOOL_COLS:
            x[c] = _to_bool_value(x.get(c, False))
        x["check_in_time"] = _safe_text(x.get("check_in_time"))
        x["check_out_time"] = _safe_text(x.get("check_out_time"))
        x["note"] = _safe_text(x.get("note"))
        x["created_at"] = _safe_text(x.get("created_at")) or _now_text()
        x["updated_at"] = _safe_text(x.get("updated_at")) or _now_text()
        x["updated_by"] = _safe_text(x.get("updated_by")) or _current_user_name()
        out.append(x)
    return out


def _load_all_daily_attendance_rows() -> list[dict[str, Any]]:
    # V32：正式環境改讀 Neon spt_module_authority；本機無 DATABASE_URL 時才讀舊 JSON fallback。
    try:
        from services.neon_authority_service import is_neon_enabled, load_payload
        if is_neon_enabled():
            payload = load_payload(DAILY_MODULE_KEY, "records", {}) or {}
            return _normalise_daily_rows(_extract_daily_rows(payload))
    except Exception:
        pass
    return _normalise_daily_rows(_extract_daily_rows(_read_daily_payload()))


def _v30032_daily_kind_for_date(target_date: str) -> str:
    return f"{V30032_DAILY_KIND_PREFIX}:{_date_to_text(target_date)}"


def _v30032_load_daily_rows_for_date_from_neon(target_date: str) -> list[dict[str, Any]] | None:
    """Load only one attendance date from Neon when the V300.32 per-date payload exists.

    Returns None when the per-date payload has never been created, so callers can fall back
    to the legacy all-records payload without losing old data.
    """
    try:
        from services.neon_authority_service import is_neon_enabled, load_payload
        if not is_neon_enabled():
            return None
        payload = load_payload(DAILY_MODULE_KEY, _v30032_daily_kind_for_date(target_date), None)
        if payload is None:
            return None
        return _normalise_daily_rows(_extract_daily_rows(payload))
    except Exception:
        return None


def _v30055_load_legacy_daily_rows_for_date_from_neon_sql(target_date: str) -> list[dict[str, Any]] | None:
    """Load one date from the old all-date Neon payload without pulling the whole JSON to Python.

    V300.32 already introduced per-date payloads.  Sites that still have only
    the legacy ``kind='records'`` payload used to hit load_payload() and parse
    the full historical JSON on every Load/Reload.  On Neon Free this can look
    like the button never stops.  This SQL extracts only rows whose
    attendance_date matches target_date.  ``None`` means the optimized fallback
    was not usable, not that there are rows.
    """
    try:
        from services.neon_authority_service import is_neon_enabled
        from services.db_service import query_df
        if not is_neon_enabled():
            return None
        d = _date_to_text(target_date)
        sql = """
            WITH src AS (
                SELECT payload::jsonb AS p
                FROM spt_module_authority
                WHERE module_key = ? AND kind = 'records' AND deleted_at IS NULL
                LIMIT 1
            ), rows AS (
                SELECT value AS row_payload
                FROM src, jsonb_array_elements(
                    CASE
                        WHEN jsonb_typeof(p->'records') = 'array' THEN p->'records'
                        WHEN jsonb_typeof(p->'tables'->'daily_attendance') = 'array' THEN p->'tables'->'daily_attendance'
                        ELSE '[]'::jsonb
                    END
                ) AS value
            )
            SELECT row_payload::text AS row_payload
            FROM rows
            WHERE COALESCE(row_payload->>'attendance_date', '') = ?
            LIMIT 5000
        """
        df = query_df(sql, (DAILY_MODULE_KEY, d))
        if df is None or not isinstance(df, pd.DataFrame):
            return None
        out: list[dict[str, Any]] = []
        for raw in df.get("row_payload", pd.Series(dtype=str)).tolist():
            try:
                val = json.loads(str(raw))
                if isinstance(val, dict):
                    out.append(val)
            except Exception:
                continue
        return _normalise_daily_rows(out)
    except Exception:
        return None


def _v30055_load_time_records_summary_for_date(target_date: str) -> pd.DataFrame:
    """Lightweight selected-date work summary for compatibility fallback."""
    try:
        df = load_daily_record_summary_sql(_date_to_text(target_date))
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    # Last-resort compatibility fallback.  This should normally not run after V300.33.
    try:
        df = load_records(start_date=_date_to_text(target_date), end_date=_date_to_text(target_date))
        if isinstance(df, pd.DataFrame):
            keep = [c for c in ["employee_id", "employee_name", "work_hours", "end_timestamp", "status", "start_timestamp", "start_time", "start_date"] if c in df.columns]
            return df[keep].copy() if keep else pd.DataFrame()
    except Exception:
        pass
    return pd.DataFrame()


def _v30063_load_time_record_employee_index_for_date(target_date: str) -> pd.DataFrame:
    """Return one row per employee with a work record on target_date.

    07 Missing Records only needs employee_id/count/last_start_time.  Prefer the
    V300.62 indexed SQL helper; use the older summary query only as a fallback.
    The comparison itself stays in pandas/session state so 07 does not load the
    large 02 history table and does not disturb 01 foreground operations.
    """
    d = _date_to_text(target_date)
    cols = ["employee_id", "employee_name", "today_record_count", "last_start_time"]
    try:
        if callable(load_daily_record_employee_index_sql):
            df = load_daily_record_employee_index_sql(d)
            if isinstance(df, pd.DataFrame):
                work = df.copy()
                for c in cols:
                    if c not in work.columns:
                        work[c] = 0 if c == "today_record_count" else ""
                work["employee_id"] = work["employee_id"].fillna("").astype(str).str.strip()
                work = work[work["employee_id"] != ""].copy()
                work["today_record_count"] = pd.to_numeric(work["today_record_count"], errors="coerce").fillna(0).astype(int)
                return work[cols].sort_values("employee_id").reset_index(drop=True)
    except Exception:
        pass

    rec = _v30055_load_time_records_summary_for_date(d)
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty or "employee_id" not in rec.columns:
        return pd.DataFrame(columns=cols)
    rec = rec.copy()
    rec["employee_id"] = rec["employee_id"].fillna("").astype(str).str.strip()
    rec = rec[rec["employee_id"] != ""].copy()
    # load_daily_record_summary_sql(work_date) is already date-scoped.  Only do
    # a second date filter when the fallback payload actually carries date fields.
    if any(c in rec.columns for c in ["start_date", "work_date", "start_timestamp"]):
        rec["__record_date"] = _date_text_series(rec)
        rec = rec[rec["__record_date"] == d].copy()
    if rec.empty:
        return pd.DataFrame(columns=cols)
    if "start_timestamp" not in rec.columns:
        rec["start_timestamp"] = rec["start_time"] if "start_time" in rec.columns else ""
    grp = rec.groupby("employee_id", dropna=False).agg(
        employee_name=("employee_name", "max") if "employee_name" in rec.columns else ("employee_id", "max"),
        today_record_count=("employee_id", "size"),
        last_start_time=("start_timestamp", "max"),
    ).reset_index()
    grp["today_record_count"] = pd.to_numeric(grp["today_record_count"], errors="coerce").fillna(0).astype(int)
    return grp[cols].sort_values("employee_id").reset_index(drop=True)


def _v30032_save_daily_rows_for_date_to_neon(target_date: str, rows: list[dict[str, Any]], *, reason: str) -> bool:
    """Save only one attendance date to Neon.

    This avoids rewriting the legacy all-date JSON payload and prevents one admin saving
    today's attendance from overwriting another admin's edits on a different date.
    """
    clean = [r for r in _normalise_daily_rows(rows) if _date_to_text(r.get("attendance_date")) == _date_to_text(target_date)]
    payload = {
        "authority_schema": "SPT-07-DailyAttendance-V30032-per-date",
        "module_key": DAILY_MODULE_KEY,
        "kind": _v30032_daily_kind_for_date(target_date),
        "attendance_date": _date_to_text(target_date),
        "updated_at": _now_text(),
        "updated_by": _current_user_name(),
        "reason": reason,
        "tables": {"daily_attendance": clean},
        "table_counts": {"daily_attendance": len(clean)},
        "records": clean,
    }
    try:
        from services.neon_authority_service import is_neon_enabled, save_payload, append_audit
        if not is_neon_enabled():
            return False
        save_payload(DAILY_MODULE_KEY, _v30032_daily_kind_for_date(target_date), payload, user=_current_user_name())
        append_audit(DAILY_MODULE_KEY, "SAVE_DAILY_ATTENDANCE_DATE", _current_user_name(), "OK", reason, {"attendance_date": target_date, "count": len(clean)})
        return True
    except Exception:
        return False


def _save_all_daily_attendance_rows(rows: list[dict[str, Any]], *, reason: str = "save_daily_attendance") -> None:
    clean = _normalise_daily_rows(rows)
    payload = {
        "authority_schema": "SPT-07-DailyAttendance-V32-neon_07_daily_attendance_v32",
        "module_key": DAILY_MODULE_KEY,
        "kind": "records",
        "updated_at": _now_text(),
        "updated_by": _current_user_name(),
        "reason": reason,
        "tables": {"daily_attendance": clean},
        "table_counts": {"daily_attendance": len(clean)},
        "records": clean,
    }
    try:
        from services.neon_authority_service import is_neon_enabled, save_payload, append_audit
        if is_neon_enabled():
            save_payload(DAILY_MODULE_KEY, "records", payload, user=_current_user_name())
            append_audit(DAILY_MODULE_KEY, "SAVE_DAILY_ATTENDANCE", _current_user_name(), "OK", reason, {"count": len(clean)})
            return
    except Exception:
        pass
    _atomic_write_json(DAILY_RECORDS_PATH, payload, reason=reason)


def _append_daily_event(action: str, rows: list[dict[str, Any]], *, target_date: str, note: str = "") -> None:
    event = {
        "event_id": f"DA-{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}",
        "action": action,
        "target_date": target_date,
        "row_count": len(rows),
        "rows": rows,
        "note": note,
        "created_at": _now_text(),
        "created_by": _current_user_name(),
    }
    try:
        from services.neon_authority_service import is_neon_enabled, append_audit
        if is_neon_enabled():
            append_audit(DAILY_MODULE_KEY, action, _current_user_name(), "OK", note, event)
            return
    except Exception:
        pass
    try:
        DAILY_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DAILY_EVENT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")
    except Exception:
        pass


def _current_user_name() -> str:
    try:
        for k in ("account", "username", "user_name", "login_user", "current_user", "auth_user"):
            val = st.session_state.get(k)
            if isinstance(val, dict):
                for kk in ("username", "account", "name", "display_name"):
                    if val.get(kk):
                        return str(val.get(kk))
            elif val:
                return str(val)
    except Exception:
        pass
    return "SYSTEM"


def _default_daily_rows_from_employee_master(target_date: str, employee_df: pd.DataFrame) -> list[dict[str, Any]]:
    emp = ensure_cols(employee_df)
    if emp.empty:
        return []
    rows: list[dict[str, Any]] = []
    now = _now_text()
    for _, r in emp.iterrows():
        emp_id = _safe_text(r.get("employee_id"))
        emp_name = _safe_text(r.get("employee_name"))
        if not emp_id and not emp_name:
            continue
        if not _to_bool_value(r.get("is_active", True)):
            continue
        in_factory = _to_bool_value(r.get("is_in_factory", True))
        attendance = _to_bool_value(r.get("is_today_attendance", True))
        rows.append({
            "record_id": _stable_record_id(target_date, emp_id),
            "attendance_date": target_date,
            "employee_id": emp_id,
            "employee_name": emp_name,
            "department": _safe_text(r.get("department")),
            "title": _safe_text(r.get("title")),
            "attendance_status": "出勤" if attendance else "未出勤",
            "is_in_factory": in_factory,
            "is_today_attendance": attendance,
            "check_in_time": "",
            "check_out_time": "",
            "note": _safe_text(r.get("note")),
            "created_at": now,
            "updated_at": now,
            "updated_by": _current_user_name(),
        })
    return _normalise_daily_rows(rows)


def _load_daily_rows_for_date(target_date: str, employee_df: pd.DataFrame) -> pd.DataFrame:
    # V300.32：正式 Neon 先讀單日 payload；舊資料尚未轉成單日 payload 時才回退讀 legacy 全量 payload。
    rows = _v30032_load_daily_rows_for_date_from_neon(target_date)
    if rows is None:
        # V300.55：若尚未有單日 payload，先用 Neon SQL 從舊全量 payload 只取指定日期。
        # 只有非 Neon / SQL fallback 失敗時才回退舊本機 JSON 全量讀取，避免 Load/Reload 長時間運轉。
        rows = _v30055_load_legacy_daily_rows_for_date_from_neon_sql(target_date)
        if rows is None:
            try:
                from services.neon_authority_service import is_neon_enabled
                if is_neon_enabled():
                    rows = []
                else:
                    all_rows = _load_all_daily_attendance_rows()
                    rows = [r for r in all_rows if _date_to_text(r.get("attendance_date")) == target_date]
            except Exception:
                rows = []
    if not rows:
        rows = _default_daily_rows_from_employee_master(target_date, employee_df)
    return pd.DataFrame(_normalise_daily_rows(rows), columns=DAILY_COLS)


def _to_daily_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = pd.DataFrame(df).copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=DAILY_COLS)
    for c in DAILY_COLS:
        if c not in work.columns:
            work[c] = False if c in DAILY_BOOL_COLS else ""
    work = work[DAILY_COLS]
    for c in DAILY_BOOL_COLS:
        work[c] = work[c].map(_to_bool_value).fillna(False).astype(bool)
    view = work.rename(columns=DAILY_DISPLAY_COLUMNS)
    view.insert(0, DAILY_DISPLAY_ROW_NO, range(1, len(view) + 1))
    view.insert(0, DAILY_DELETE_COL, False)
    for c in DAILY_EDITOR_COLS:
        if c not in view.columns:
            view[c] = False if c == DAILY_DELETE_COL else ""
    return view[DAILY_EDITOR_COLS]


def _from_daily_editor_df(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    work = pd.DataFrame(df).copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    work = work.rename(columns={c: DAILY_DISPLAY_TO_INTERNAL.get(c, c) for c in work.columns})
    if DAILY_DISPLAY_ROW_NO in work.columns:
        work = work.drop(columns=[DAILY_DISPLAY_ROW_NO], errors="ignore")
    if "row_no" in work.columns:
        work = work.drop(columns=["row_no"], errors="ignore")
    if DAILY_DELETE_COL in work.columns:
        work["_delete"] = work[DAILY_DELETE_COL].map(_to_bool_value).fillna(False).astype(bool)
        work = work.drop(columns=[DAILY_DELETE_COL], errors="ignore")
    elif "_delete" in work.columns:
        work["_delete"] = work["_delete"].map(_to_bool_value).fillna(False).astype(bool)
    else:
        work["_delete"] = False
    for c in DAILY_COLS:
        if c not in work.columns:
            work[c] = False if c in DAILY_BOOL_COLS else ""
    work["attendance_date"] = target_date
    for c in DAILY_BOOL_COLS:
        work[c] = work[c].map(_to_bool_value).fillna(False).astype(bool)
    work["_delete"] = work["_delete"].map(_to_bool_value).fillna(False).astype(bool)
    return work[DAILY_COLS + ["_delete"]]


# V300.59：07 直接 data_editor 表格改用內部欄位 key + 顯示 label。
# 避免 Streamlit / column_settings wrapper 把中英雙語欄名再疊一次，並補回明確的套用欄位設定按鈕。
V30059_TODAY_ATTENDANCE_TABLE_KEY = "07_today_attendance_editor"
V30059_DAILY_ATTENDANCE_TABLE_KEY = "07_daily_attendance_editor"
V30059_ROW_NO_COL = "row_no"
V30059_TODAY_INTERNAL_ORDER = [V30059_ROW_NO_COL] + [c for c in COLS if c != "id"]
V30059_DAILY_INTERNAL_ORDER = ["_delete", V30059_ROW_NO_COL] + DAILY_COLS


def _v30059_width(table_key: str, col: str, default="medium"):
    try:
        widths = load_widths(table_key)
        value = widths.get(str(col))
        if value:
            return int(value)
    except Exception:
        pass
    return default


def _v30059_apply_order(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    try:
        return apply_column_order(table_key, df)
    except Exception:
        return df


def _v30059_today_table_df(editor_df: pd.DataFrame) -> pd.DataFrame:
    work = pd.DataFrame(editor_df).copy() if isinstance(editor_df, pd.DataFrame) else pd.DataFrame()
    work = work.rename(columns={v: k for k, v in DISPLAY_COLUMNS.items()})
    if DISPLAY_ROW_NO in work.columns:
        work = work.rename(columns={DISPLAY_ROW_NO: V30059_ROW_NO_COL})
    for c in V30059_TODAY_INTERNAL_ORDER:
        if c not in work.columns:
            work[c] = range(1, len(work) + 1) if c == V30059_ROW_NO_COL else ""
    work = work[V30059_TODAY_INTERNAL_ORDER]
    return _v30059_apply_order(V30059_TODAY_ATTENDANCE_TABLE_KEY, work)


def _v30059_today_column_config(table_key: str) -> dict:
    return {
        V30059_ROW_NO_COL: st.column_config.NumberColumn("序號 / No.", width=_v30059_width(table_key, V30059_ROW_NO_COL, "small")),
        "employee_id": st.column_config.TextColumn("工號 / Employee ID", width=_v30059_width(table_key, "employee_id", "medium")),
        "employee_name": st.column_config.TextColumn("姓名 / Name", width=_v30059_width(table_key, "employee_name", "medium")),
        "department": st.column_config.TextColumn("單位 / Department", width=_v30059_width(table_key, "department", "medium")),
        "title": st.column_config.TextColumn("職稱 / Title", width=_v30059_width(table_key, "title", "medium")),
        "is_active": st.column_config.CheckboxColumn("啟用 / Active", width=_v30059_width(table_key, "is_active", "medium")),
        "is_in_factory": st.column_config.CheckboxColumn("在廠 / In Factory", width=_v30059_width(table_key, "is_in_factory", "medium")),
        "is_today_attendance": st.column_config.CheckboxColumn("今日出勤 / Today Attendance", width=_v30059_width(table_key, "is_today_attendance", "medium")),
        "include_in_missing_records": st.column_config.CheckboxColumn("納入未紀錄統計 / Include Missing", width=_v30059_width(table_key, "include_in_missing_records", "medium"), help="取消勾選後，該人員仍可出勤，但不列入 07 今日未紀錄人數 / Missing Records。"),
        "note": st.column_config.TextColumn("備註 / Note", width=_v30059_width(table_key, "note", "large")),
        "created_at": st.column_config.TextColumn("建立時間 / Created At", width=_v30059_width(table_key, "created_at", "medium")),
        "updated_at": st.column_config.TextColumn("更新時間 / Updated At", width=_v30059_width(table_key, "updated_at", "medium")),
    }


def _v30059_daily_table_df(daily_view_df: pd.DataFrame) -> pd.DataFrame:
    work = pd.DataFrame(daily_view_df).copy() if isinstance(daily_view_df, pd.DataFrame) else pd.DataFrame()
    work = work.rename(columns={v: k for k, v in DAILY_DISPLAY_COLUMNS.items()})
    if DAILY_DISPLAY_ROW_NO in work.columns:
        work = work.rename(columns={DAILY_DISPLAY_ROW_NO: V30059_ROW_NO_COL})
    if DAILY_DELETE_COL in work.columns:
        work = work.rename(columns={DAILY_DELETE_COL: "_delete"})
    for c in V30059_DAILY_INTERNAL_ORDER:
        if c not in work.columns:
            if c == V30059_ROW_NO_COL:
                work[c] = range(1, len(work) + 1)
            elif c in {"_delete", "is_in_factory", "is_today_attendance"}:
                work[c] = False
            else:
                work[c] = ""
    work = work[V30059_DAILY_INTERNAL_ORDER]
    return _v30059_apply_order(V30059_DAILY_ATTENDANCE_TABLE_KEY, work)


def _v30059_daily_column_config(table_key: str) -> dict:
    return {
        "_delete": st.column_config.CheckboxColumn("刪除 / Delete", width=_v30059_width(table_key, "_delete", "small")),
        V30059_ROW_NO_COL: st.column_config.NumberColumn("序號 / No.", width=_v30059_width(table_key, V30059_ROW_NO_COL, "small")),
        "employee_id": st.column_config.TextColumn("工號 / Employee ID", width=_v30059_width(table_key, "employee_id", "medium")),
        "employee_name": st.column_config.TextColumn("姓名 / Name", width=_v30059_width(table_key, "employee_name", "medium")),
        "department": st.column_config.TextColumn("單位 / Department", width=_v30059_width(table_key, "department", "medium")),
        "title": st.column_config.TextColumn("職稱 / Title", width=_v30059_width(table_key, "title", "medium")),
        "attendance_status": st.column_config.SelectboxColumn("出勤狀態 / Attendance Status", options=["出勤", "請假", "公出", "休假", "未出勤", "離職", "其他"], width=_v30059_width(table_key, "attendance_status", "medium")),
        "is_in_factory": st.column_config.CheckboxColumn("在廠 / In Factory", width=_v30059_width(table_key, "is_in_factory", "medium")),
        "is_today_attendance": st.column_config.CheckboxColumn("出勤 / Attendance", width=_v30059_width(table_key, "is_today_attendance", "medium")),
        "check_in_time": st.column_config.TextColumn("到廠時間 / Check In", width=_v30059_width(table_key, "check_in_time", "medium"), help="可填 08:00 或 2026-05-29 08:00"),
        "check_out_time": st.column_config.TextColumn("離廠時間 / Check Out", width=_v30059_width(table_key, "check_out_time", "medium")),
        "note": st.column_config.TextColumn("備註 / Note", width=_v30059_width(table_key, "note", "large")),
        "record_id": st.column_config.TextColumn("紀錄ID / Record ID", width=_v30059_width(table_key, "record_id", "medium")),
        "attendance_date": st.column_config.TextColumn("日期 / Date", width=_v30059_width(table_key, "attendance_date", "medium")),
        "created_at": st.column_config.TextColumn("建立時間 / Created At", width=_v30059_width(table_key, "created_at", "medium")),
        "updated_at": st.column_config.TextColumn("更新時間 / Updated At", width=_v30059_width(table_key, "updated_at", "medium")),
        "updated_by": st.column_config.TextColumn("更新者 / Updated By", width=_v30059_width(table_key, "updated_by", "medium")),
    }


def _save_daily_editor_df(editor_df: pd.DataFrame, target_date: str) -> dict[str, Any]:
    incoming = _from_daily_editor_df(editor_df, target_date)

    now = _now_text()
    saved_rows: list[dict[str, Any]] = []
    deleted_rows: list[dict[str, Any]] = []
    for _, r in incoming.iterrows():
        rec = {c: r.get(c, "") for c in DAILY_COLS}
        rec["attendance_date"] = target_date
        rec["employee_id"] = _safe_text(rec.get("employee_id"))
        rec["employee_name"] = _safe_text(rec.get("employee_name"))
        if not rec["employee_id"] and not rec["employee_name"]:
            continue
        rec["record_id"] = _safe_text(rec.get("record_id")) or _stable_record_id(target_date, rec["employee_id"])
        rec["created_at"] = _safe_text(rec.get("created_at")) or now
        rec["updated_at"] = now
        rec["updated_by"] = _current_user_name()
        rec["attendance_status"] = _safe_text(rec.get("attendance_status")) or ("出勤" if _to_bool_value(rec.get("is_today_attendance")) else "未出勤")
        for c in DAILY_BOOL_COLS:
            rec[c] = _to_bool_value(rec.get(c, False))
        if _to_bool_value(r.get("_delete")):
            deleted_rows.append(rec)
            continue
        saved_rows.append(rec)

    # 同日同工號保留最後一筆；無工號則用 record_id。
    dedup: dict[str, dict[str, Any]] = {}
    for rec in saved_rows:
        k = _safe_text(rec.get("employee_id")) or _safe_text(rec.get("record_id")) or uuid.uuid4().hex
        dedup[k] = rec

    final_today_rows = list(dedup.values())
    # V300.32：Neon 正式環境只寫所選日期 payload，避免整份每日出勤歷史被重寫。
    saved_to_neon_date = _v30032_save_daily_rows_for_date_to_neon(
        target_date,
        final_today_rows,
        reason="v30032_save_daily_attendance_date",
    )
    if not saved_to_neon_date:
        # 本機 / 無 Neon fallback 保持舊行為，確保 local JSON 測試仍能保存其他日期。
        all_existing = _load_all_daily_attendance_rows()
        keep_other_dates = [r for r in all_existing if _date_to_text(r.get("attendance_date")) != target_date]
        _save_all_daily_attendance_rows(keep_other_dates + final_today_rows, reason="v30032_save_daily_attendance_local_fallback")

    _append_daily_event("SAVE_DAILY_ATTENDANCE", final_today_rows, target_date=target_date, note=f"deleted={len(deleted_rows)}")
    if deleted_rows:
        _append_daily_event("DELETE_DAILY_ATTENDANCE", deleted_rows, target_date=target_date, note="deleted rows from 07 daily attendance editor")
    return {"saved": len(final_today_rows), "deleted": len(deleted_rows), "total": len(final_today_rows), "rows": final_today_rows}


def _v30063_missing_output_cols(include_attendance_status: bool = False) -> list[str]:
    base = ["employee_id", "employee_name", "department", "title"]
    if include_attendance_status:
        base.append("attendance_status")
    base += ["is_in_factory", "is_today_attendance", "include_in_missing_records", "last_start_time", "today_record_count"]
    return base


def _v30063_include_missing_map(employee_df: pd.DataFrame | None = None) -> dict[str, bool]:
    try:
        emp = ensure_cols(employee_df) if isinstance(employee_df, pd.DataFrame) else ensure_cols(load_employees())
    except Exception:
        emp = pd.DataFrame()
    if emp is None or emp.empty or "employee_id" not in emp.columns:
        return {}
    out: dict[str, bool] = {}
    for _, r in emp.iterrows():
        emp_id = _safe_text(r.get("employee_id"))
        if not emp_id:
            continue
        out[emp_id] = _to_bool_value_with_default(r.get("include_in_missing_records", True), True)
    return out


def _v30063_apply_missing_exemption(df: pd.DataFrame, employee_df: pd.DataFrame | None = None) -> pd.DataFrame:
    work = pd.DataFrame(df).copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if work.empty or "employee_id" not in work.columns:
        if "include_in_missing_records" not in work.columns:
            work["include_in_missing_records"] = True
        return work
    include_map = _v30063_include_missing_map(employee_df)
    if "include_in_missing_records" not in work.columns:
        work["include_in_missing_records"] = True
    work["include_in_missing_records"] = work.apply(
        lambda r: bool(include_map.get(_safe_text(r.get("employee_id")), _to_bool_value_with_default(r.get("include_in_missing_records", True), True))),
        axis=1,
    )
    return work[work["include_in_missing_records"].map(lambda v: _to_bool_value_with_default(v, True))].copy()


def _v30063_missing_rule_signature(employee_df: pd.DataFrame | None = None) -> str:
    try:
        emp = ensure_cols(employee_df) if isinstance(employee_df, pd.DataFrame) else ensure_cols(load_employees())
        if emp.empty:
            return "empty"
        sig_df = emp[["employee_id", "include_in_missing_records"]].copy()
        sig_df["employee_id"] = sig_df["employee_id"].fillna("").astype(str).str.strip()
        sig_df["include_in_missing_records"] = sig_df["include_in_missing_records"].map(lambda v: _to_bool_value_with_default(v, True))
        sig_df = sig_df.sort_values("employee_id").reset_index(drop=True)
        return _v30032_df_signature(sig_df)
    except Exception:
        return "unknown"


def _to_bool_value_with_default(v, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    try:
        if pd.isna(v):
            return bool(default)
    except Exception:
        pass
    text = str(v).strip().lower()
    if text in {"", "nan", "none"}:
        return bool(default)
    if text in {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選", "納入", "include"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否", "免統計", "排除", "exclude"}:
        return False
    return bool(v)


def _build_missing_from_daily_attendance(att_df: pd.DataFrame, target_date: str, employee_df: pd.DataFrame | None = None) -> pd.DataFrame:
    out_cols = _v30063_missing_output_cols(include_attendance_status=True)
    if att_df is None or att_df.empty:
        return pd.DataFrame(columns=out_cols)
    att = pd.DataFrame(att_df).copy()
    for c in DAILY_COLS:
        if c not in att.columns:
            att[c] = False if c in DAILY_BOOL_COLS else ""
    att["employee_id"] = att["employee_id"].fillna("").astype(str).str.strip()
    att = att[(att["employee_id"] != "") & (att["is_in_factory"].map(_to_bool_value)) & (att["is_today_attendance"].map(_to_bool_value))].copy()
    att = _v30063_apply_missing_exemption(att, employee_df)
    if att.empty:
        return pd.DataFrame(columns=out_cols)

    rec = _v30063_load_time_record_employee_index_for_date(target_date)
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty or "employee_id" not in rec.columns:
        att["last_start_time"] = ""
        att["today_record_count"] = 0
        return att[out_cols].sort_values("employee_id").reset_index(drop=True)
    rec = rec.copy()
    rec["employee_id"] = rec["employee_id"].fillna("").astype(str).str.strip()
    rec = rec[rec["employee_id"] != ""].copy()
    if rec.empty:
        att["last_start_time"] = ""
        att["today_record_count"] = 0
        return att[out_cols].sort_values("employee_id").reset_index(drop=True)

    keep = ["employee_id", "last_start_time", "today_record_count"]
    for c in keep:
        if c not in rec.columns:
            rec[c] = 0 if c == "today_record_count" else ""
    out = att.merge(rec[keep], on="employee_id", how="left")
    out["today_record_count"] = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    out["last_start_time"] = out["last_start_time"].fillna("").astype(str)
    out = out[out["today_record_count"] == 0].copy()
    return out[out_cols].sort_values("employee_id").reset_index(drop=True)


def _v30032_build_missing_from_daily_attendance_cached(att_df: pd.DataFrame, target_date: str, employee_df: pd.DataFrame | None = None) -> pd.DataFrame:
    sig = f"{_date_to_text(target_date)}:{_v30032_df_signature(att_df)}:{_v30063_missing_rule_signature(employee_df)}"
    now_ts = datetime.now().timestamp()
    cache = st.session_state.get(V30032_SELECTED_MISSING_CACHE_KEY, {})
    if isinstance(cache, dict) and cache.get("sig") == sig:
        age = now_ts - float(cache.get("ts", 0) or 0)
        cached_df = cache.get("df")
        if age <= V30032_SELECTED_MISSING_TTL_SECONDS and isinstance(cached_df, pd.DataFrame):
            return cached_df.copy()
    out = _build_missing_from_daily_attendance(att_df, target_date, employee_df)
    st.session_state[V30032_SELECTED_MISSING_CACHE_KEY] = {"sig": sig, "ts": now_ts, "df": out.copy()}
    return out


def _attendance_summary(att_df: pd.DataFrame) -> pd.DataFrame:
    if att_df is None or att_df.empty:
        return pd.DataFrame(columns=["項目 / Item", "數量 / Count"])
    df = att_df.copy()
    return pd.DataFrame([
        {"項目 / Item": "總筆數 / Total", "數量 / Count": len(df)},
        {"項目 / Item": "在廠 / In Factory", "數量 / Count": int(df.get("is_in_factory", pd.Series(dtype=bool)).map(_to_bool_value).sum()) if "is_in_factory" in df.columns else 0},
        {"項目 / Item": "出勤 / Attendance", "數量 / Count": int(df.get("is_today_attendance", pd.Series(dtype=bool)).map(_to_bool_value).sum()) if "is_today_attendance" in df.columns else 0},
        {"項目 / Item": "未出勤 / Not Attendance", "數量 / Count": int((~df.get("is_today_attendance", pd.Series(dtype=bool)).map(_to_bool_value)).sum()) if "is_today_attendance" in df.columns else 0},
    ])


def _make_daily_attendance_excel(att_df: pd.DataFrame, missing_df: pd.DataFrame, target_date: str) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        export_att = att_df.copy() if isinstance(att_df, pd.DataFrame) else pd.DataFrame()
        export_missing = missing_df.copy() if isinstance(missing_df, pd.DataFrame) else pd.DataFrame()
        _attendance_summary(export_att).to_excel(writer, index=False, sheet_name="summary")
        export_att.to_excel(writer, index=False, sheet_name="daily_attendance")
        export_missing.to_excel(writer, index=False, sheet_name="missing_records")
        if not export_att.empty and "department" in export_att.columns:
            dept = export_att.groupby(["department", "attendance_status"], dropna=False).size().reset_index(name="count")
            dept.to_excel(writer, index=False, sheet_name="department_status")
        ws = writer.book.add_worksheet("README")
        ws.write(0, 0, "07 今日未紀錄名單｜每日出勤紀錄匯出")
        ws.write(1, 0, f"日期：{target_date}")
        ws.write(2, 0, "daily_attendance：每日出勤紀錄表")
        ws.write(3, 0, "missing_records：依該日出勤紀錄表與工時紀錄計算的未紀錄名單")
        ws.write(4, 0, "summary：統計摘要")
    return output.getvalue()
# ===== V234：07 每日出勤紀錄表｜永久紀錄 + 穩定編輯 END =====


def rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def _to_bool_value(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    text = str(v).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否", ""}:
        return False
    return bool(v)


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = out.rename(columns={c: DISPLAY_TO_INTERNAL.get(c, c) for c in out.columns})
    for c in COLS:
        if c not in out.columns:
            out[c] = True if c == "include_in_missing_records" else (False if c in {"is_active", "is_in_factory", "is_today_attendance"} else "")
    for c in BOOL_INTERNAL_COLS:
        _default = True if c == "include_in_missing_records" else False
        out[c] = out[c].map(lambda v, d=_default: _to_bool_value_with_default(v, d)).fillna(_default).astype(bool)
    return out[COLS]


def _to_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_cols(df)
    view = work.rename(columns=DISPLAY_COLUMNS)
    view.insert(0, DISPLAY_ROW_NO, range(1, len(view) + 1))
    return view[EDITOR_COLS]


def _from_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if DISPLAY_ROW_NO in work.columns:
        work = work.drop(columns=[DISPLAY_ROW_NO], errors="ignore")
    # 07 的畫面不顯示 id；回存前補回空 id，save_employees 會用 employee_id 做更新/新增。
    if DISPLAY_COLUMNS["id"] not in work.columns and "id" not in work.columns:
        work["id"] = ""
    return ensure_cols(work)


def _commit_current_editor_widget_state() -> None:
    """V67: commit data_editor widget delta into this page draft before buttons/KPI read it."""
    try:
        from services.data_editor_state_service import commit_editor_widget_state_to_session
        _editor_key = f"today_attendance_editor_v202_{st.session_state.get(EDITOR_REV_KEY, 0)}"
        commit_editor_widget_state_to_session(
            state_key=STATE_KEY,
            editor_key=_editor_key,
            to_editor_df=lambda df: _v30059_today_table_df(_to_editor_df(df)),
            from_editor_df=_from_editor_df,
            ensure_df=ensure_cols,
        )
    except Exception:
        pass


def reload_employees() -> None:
    st.session_state[STATE_KEY] = ensure_cols(load_employees())
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def touch_editor() -> None:
    # V65：只清除 data_editor widget 本身，不可把 STATE_KEY / REV / IGNORE 一起刪掉。
    # V64 的條件包含「today_attendance_editor」字串，會誤刪 v202_today_attendance_editor，
    # 導致批次按鈕剛改完暫存資料又被 reload_employees() 蓋回，看起來像按鈕無作用。
    protected_keys = {STATE_KEY, EDITOR_REV_KEY, EDITOR_IGNORE_RETURN_KEY}
    try:
        for _k0 in list(st.session_state.keys()):
            sk = str(_k0)
            if sk in protected_keys:
                continue
            if sk.startswith("today_attendance_editor_v202_"):
                st.session_state.pop(_k0, None)
    except Exception:
        pass
    try:
        from services.column_settings_service import clear_editor_draft
        clear_editor_draft("today_attendance_editor")
        clear_editor_draft("today_attendance")
    except Exception:
        pass
    st.session_state[EDITOR_IGNORE_RETURN_KEY] = True
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def _current_internal_df() -> pd.DataFrame:
    _commit_current_editor_widget_state()
    return ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))


def _bulk_set_bool_column(col: str, value: bool) -> None:
    """V65: 批次按鈕重新指定整份 DataFrame，避免 in-place 修改被 data_editor 舊草稿覆蓋。"""
    df = _current_internal_df().copy()
    if col not in df.columns:
        df[col] = False
    df[col] = bool(value)
    st.session_state[STATE_KEY] = ensure_cols(df)
    touch_editor()
    rerun()


def _date_text_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    if "start_date" in df.columns:
        return pd.to_datetime(df["start_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "work_date" in df.columns:
        return pd.to_datetime(df["work_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "start_timestamp" in df.columns:
        return pd.to_datetime(df["start_timestamp"], errors="coerce").dt.strftime("%Y-%m-%d")
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _build_missing_today_df(employee_df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    # V300.63：今日未紀錄名單 = 今日出勤且納入未紀錄統計的人員，
    # 再比對 01/time_records 當日工時索引；幹部/主管可在 04 取消納入統計。
    out_cols = _v30063_missing_output_cols(include_attendance_status=False)
    emp = ensure_cols(employee_df)
    if emp.empty:
        return pd.DataFrame(columns=out_cols)
    for c in BOOL_INTERNAL_COLS:
        _default = True if c == "include_in_missing_records" else False
        emp[c] = emp[c].map(lambda v, d=_default: _to_bool_value_with_default(v, d)).fillna(_default).astype(bool)
    emp = emp[(emp["is_active"]) & (emp["is_in_factory"]) & (emp["is_today_attendance"]) & (emp["include_in_missing_records"])].copy()
    emp["employee_id"] = emp["employee_id"].fillna("").astype(str).str.strip()
    emp = emp[emp["employee_id"] != ""].copy()
    if emp.empty:
        return pd.DataFrame(columns=out_cols)

    rec = _v30063_load_time_record_employee_index_for_date(target_date)
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty or "employee_id" not in rec.columns:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[out_cols].sort_values("employee_id").reset_index(drop=True)

    rec = rec.copy()
    rec["employee_id"] = rec["employee_id"].fillna("").astype(str).str.strip()
    rec = rec[rec["employee_id"] != ""].copy()
    if rec.empty:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[out_cols].sort_values("employee_id").reset_index(drop=True)

    keep = ["employee_id", "last_start_time", "today_record_count"]
    for c in keep:
        if c not in rec.columns:
            rec[c] = 0 if c == "today_record_count" else ""
    out = emp.merge(rec[keep], on="employee_id", how="left")
    out["today_record_count"] = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    out["last_start_time"] = out["last_start_time"].fillna("").astype(str)
    out = out[out["today_record_count"] == 0].copy()
    return out[out_cols].sort_values("employee_id").reset_index(drop=True)


def _v30093_today_absent_output_cols() -> list[str]:
    return [
        "employee_id",
        "employee_name",
        "department",
        "title",
        "attendance_status",
        "is_active",
        "is_in_factory",
        "is_today_attendance",
        "include_in_missing_records",
        "note",
    ]


def _build_today_absent_df(employee_df: pd.DataFrame) -> pd.DataFrame:
    """Build today's not-attendance employee details from the current 04/07 employee master.

    Rule: count active + in-factory employees whose Today Attendance is false.
    This is intentionally separate from Missing Records. Executives excluded from
    Missing Records by include_in_missing_records=False may still appear here if
    they are active/in-factory and not marked attendance today.
    """
    out_cols = _v30093_today_absent_output_cols()
    emp = ensure_cols(employee_df)
    if emp.empty:
        return pd.DataFrame(columns=out_cols)
    for c in BOOL_INTERNAL_COLS:
        _default = True if c == "include_in_missing_records" else False
        emp[c] = emp[c].map(lambda v, d=_default: _to_bool_value_with_default(v, d)).fillna(_default).astype(bool)
    emp["employee_id"] = emp["employee_id"].fillna("").astype(str).str.strip()
    emp = emp[emp["employee_id"] != ""].copy()
    if emp.empty:
        return pd.DataFrame(columns=out_cols)
    emp = emp[(emp["is_active"]) & (emp["is_in_factory"]) & (~emp["is_today_attendance"])].copy()
    if emp.empty:
        return pd.DataFrame(columns=out_cols)
    emp["attendance_status"] = "未出勤 / Not Attendance"
    for c in out_cols:
        if c not in emp.columns:
            emp[c] = False if c in BOOL_INTERNAL_COLS else ""
    return emp[out_cols].sort_values("employee_id").reset_index(drop=True)



if STATE_KEY not in st.session_state:
    reload_employees()

can_edit = check_permission("07_missing", "can_edit") or check_permission("04_employees", "can_edit")

st.subheader("今日出勤名單編輯 / Today Attendance Editor")
st.info("V66：今日出勤表格改用『序號 / No.』取代空白 SQLite ID；批次按鈕仍只改畫面暫存，按儲存後才寫入正式人員資料。")

if not can_edit:
    st.warning("目前帳號沒有今日出勤 / 人員名單編輯權限，只能查看資料。")
    view_df = st.session_state[STATE_KEY].copy()
    render_table(view_df, "today_attendance_readonly_v202", editable=False, height=460)
else:
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("☑ 在廠全選 / Factory All", use_container_width=True, key="v64_today_factory_all_on"):
        _bulk_set_bool_column("is_in_factory", True)
    if c2.button("☐ 在廠取消 / Clear Factory", use_container_width=True, key="v64_today_factory_all_off"):
        _bulk_set_bool_column("is_in_factory", False)
    if c3.button("☑ 今日出勤全選 / Attendance All", use_container_width=True, key="v64_today_attendance_all_on"):
        _bulk_set_bool_column("is_today_attendance", True)
    if c4.button("☐ 今日出勤取消 / Clear Attendance", use_container_width=True, key="v64_today_attendance_all_off"):
        _bulk_set_bool_column("is_today_attendance", False)

    c5, c6, c7, c8 = st.columns(4)
    if c5.button("☑ 啟用全選 / Active All", use_container_width=True, key="v64_today_active_all_on"):
        _bulk_set_bool_column("is_active", True)
    if c6.button("☐ 啟用取消 / Inactive All", use_container_width=True, key="v64_today_active_all_off"):
        _bulk_set_bool_column("is_active", False)
    if c7.button("⟳ 重新載入 / Reload", use_container_width=True, key="v202_today_reload"):
        reload_employees()
        rerun()
    c8.caption("批次按鈕只改畫面暫存，按儲存後才寫入。")

    editor_key = f"today_attendance_editor_v202_{st.session_state.get(EDITOR_REV_KEY, 0)}"
    _commit_current_editor_widget_state()
    st.session_state[STATE_KEY] = ensure_cols(st.session_state[STATE_KEY])
    editor_df = _to_editor_df(st.session_state[STATE_KEY])
    today_table_df = _v30059_today_table_df(editor_df)
    render_width_settings(V30059_TODAY_ATTENDANCE_TABLE_KEY, today_table_df, title="欄位設定 / Column Settings（永久保存）")
    today_table_df = _v30059_today_table_df(editor_df)
    # V300.59：使用內部欄位 key 交給 data_editor，避免中英雙語欄名被重複顯示。
    with st.form("v120_today_attendance_stable_editor_form", clear_on_submit=False):
        edited = _v30068_page_owned_data_editor(
            today_table_df,
            hide_index=True,
            use_container_width=True,
            height=460,
            disabled=[V30059_ROW_NO_COL, "employee_id", "employee_name", "department", "title", "note", "created_at", "updated_at"],
            column_config=_v30059_today_column_config(V30059_TODAY_ATTENDANCE_TABLE_KEY),
            key=editor_key,
        )
        submitted_today_attendance = st.form_submit_button("▣ 確認儲存今日出勤設定 / Save Today Attendance", type="primary", use_container_width=True)
    ignore_editor_return = bool(st.session_state.pop(EDITOR_IGNORE_RETURN_KEY, False))
    if isinstance(edited, pd.DataFrame) and not ignore_editor_return:
        st.session_state[STATE_KEY] = _from_editor_df(edited)
    if submitted_today_attendance:
        save_df = st.session_state[STATE_KEY].copy()
        save_df.insert(0, "_delete", False)
        result = save_employees(save_df)
        reload_employees()
        st.success(f"今日出勤設定已儲存：目前保留/更新 {len(save_df)} 筆，略過 {result.get('skipped', 0)} 筆。")
        rerun()

# ===== V234 新增：每日出勤紀錄表 START =====
st.divider()
st.subheader("每日出勤紀錄表 / Daily Attendance Records")
st.caption("V234：此表獨立永久保存於 data/permanent_store/modules/07_daily_attendance_records/records.json；編輯採表單模式，輸入與勾選不會每一下 rerun，畫面不會因編輯跳動。")

if DAILY_DATE_KEY not in st.session_state:
    st.session_state[DAILY_DATE_KEY] = today_date()
selected_date_obj = st.date_input(
    "選擇日期 / Select Date",
    value=st.session_state.get(DAILY_DATE_KEY, today_date()),
    key="v234_07_daily_attendance_date_input",
)
selected_date = _date_to_text(selected_date_obj)
st.session_state[DAILY_DATE_KEY] = selected_date_obj

current_employee_df = _current_internal_df() if STATE_KEY in st.session_state else ensure_cols(load_employees())
# V69: do not load the independent daily attendance authority automatically on every page open/date change.
# It may read Neon/module payloads; load only after explicit user action, then keep it in session.
if st.session_state.get(DAILY_LAST_DATE_KEY) != selected_date:
    _v30032_clear_daily_output_cache()
    st.session_state[DAILY_LOADED_KEY] = False
    st.session_state[DAILY_STATE_KEY] = pd.DataFrame(columns=DAILY_COLS)
    st.session_state[DAILY_LAST_DATE_KEY] = selected_date
    st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
if DAILY_STATE_KEY not in st.session_state:
    st.session_state[DAILY_STATE_KEY] = pd.DataFrame(columns=DAILY_COLS)

msg = st.session_state.pop(DAILY_MESSAGE_KEY, "")
if msg:
    st.success(msg)

btn1, btn2, btn3, btn4 = st.columns(4)
if btn1.button("⟳ 載入/重新載入出勤紀錄 / Load / Reload", use_container_width=True, key="v234_daily_reload"):
    _v30032_clear_daily_output_cache()
    with st.spinner("正在載入所選日期出勤紀錄，請稍候 / Loading selected attendance records..."):
        loaded_df = _load_daily_rows_for_date(selected_date, current_employee_df)
    st.session_state[DAILY_STATE_KEY] = loaded_df
    st.session_state[DAILY_LOADED_KEY] = True
    st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
    st.session_state[V30055_DAILY_LOAD_MESSAGE_KEY] = f"已載入 {selected_date} 出勤紀錄 {len(loaded_df):,} 筆。"
if btn2.button("＋ 依人員名單補齊 / Fill From Employees", use_container_width=True, key="v234_daily_fill_from_employees"):
    _v30032_clear_daily_output_cache()
    base = st.session_state.get(DAILY_STATE_KEY, pd.DataFrame()).copy()
    defaults = pd.DataFrame(_default_daily_rows_from_employee_master(selected_date, current_employee_df), columns=DAILY_COLS)
    if base is None or base.empty:
        merged = defaults
    else:
        base = pd.DataFrame(base)
        exists = set(base.get("employee_id", pd.Series(dtype=str)).fillna("").astype(str).str.strip())
        add = defaults[~defaults["employee_id"].fillna("").astype(str).str.strip().isin(exists)].copy()
        merged = pd.concat([base, add], ignore_index=True)
    st.session_state[DAILY_STATE_KEY] = pd.DataFrame(_normalise_daily_rows(merged.to_dict(orient="records")), columns=DAILY_COLS)
    st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
    rerun()
if btn3.button("☑ 全部出勤 / All Attendance", use_container_width=True, key="v234_daily_all_attendance"):
    _v30032_clear_daily_output_cache()
    df0 = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame())).copy()
    if not df0.empty:
        df0["is_today_attendance"] = True
        df0["is_in_factory"] = True
        df0["attendance_status"] = "出勤"
        st.session_state[DAILY_STATE_KEY] = df0
        st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
        rerun()
if btn4.button("☐ 全部未出勤 / Clear Attendance", use_container_width=True, key="v234_daily_clear_attendance"):
    _v30032_clear_daily_output_cache()
    df0 = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame())).copy()
    if not df0.empty:
        df0["is_today_attendance"] = False
        df0["attendance_status"] = "未出勤"
        st.session_state[DAILY_STATE_KEY] = df0
        st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
        rerun()

_load_msg = st.session_state.pop(V30055_DAILY_LOAD_MESSAGE_KEY, "")
if _load_msg:
    st.success(_load_msg)

_daily_editor_key = f"v234_daily_attendance_editor_{selected_date}_{st.session_state.get(DAILY_REV_KEY, 0)}"
_daily_df = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame()), columns=DAILY_COLS)
_daily_view = _to_daily_editor_df(_daily_df)
can_edit_daily = can_edit
if not can_edit_daily:
    st.warning("目前帳號沒有 07 今日未紀錄名單編輯權限，只能查看每日出勤紀錄。")
    render_table(_daily_df, "v234_daily_attendance_readonly", editable=False, height=460)
else:
    daily_table_df = _v30059_daily_table_df(_daily_view)
    render_width_settings(V30059_DAILY_ATTENDANCE_TABLE_KEY, daily_table_df, title="欄位設定 / Column Settings（永久保存）")
    daily_table_df = _v30059_daily_table_df(_daily_view)
    with st.form("v234_daily_attendance_stable_editor_form", clear_on_submit=False):
        daily_edited = _v30068_page_owned_data_editor(
            daily_table_df,
            hide_index=True,
            use_container_width=True,
            height=520,
            num_rows="dynamic",
            disabled=[
                V30059_ROW_NO_COL,
                "record_id",
                "attendance_date",
                "created_at",
                "updated_at",
                "updated_by",
            ],
            column_config=_v30059_daily_column_config(V30059_DAILY_ATTENDANCE_TABLE_KEY),
            key=_daily_editor_key,
        )
        daily_submit = st.form_submit_button("▣ 儲存每日出勤紀錄 / Save Daily Attendance Records", type="primary", use_container_width=True)
    if isinstance(daily_edited, pd.DataFrame):
        # 在 submit 之前也保留目前畫面草稿，切換下載或其他操作時不會丟失。
        st.session_state[DAILY_STATE_KEY] = _from_daily_editor_df(daily_edited, selected_date).drop(columns=["_delete"], errors="ignore")
    if daily_submit:
        _v30032_clear_daily_output_cache()
        result = _save_daily_editor_df(daily_edited, selected_date)
        st.session_state[DAILY_STATE_KEY] = pd.DataFrame(result.get("rows", []), columns=DAILY_COLS)
        st.session_state[DAILY_LOADED_KEY] = True
        st.session_state[DAILY_MESSAGE_KEY] = f"每日出勤紀錄已儲存：保存 {result.get('saved', 0)} 筆，刪除 {result.get('deleted', 0)} 筆，所選日期永久紀錄 {result.get('total', 0)} 筆。"
        st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
        rerun()

current_daily_df = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame()), columns=DAILY_COLS)
selected_missing_df = _v30032_build_missing_from_daily_attendance_cached(current_daily_df, selected_date, current_employee_df) if st.session_state.get(DAILY_LOADED_KEY, False) else pd.DataFrame()
if not st.session_state.get(DAILY_LOADED_KEY, False):
    st.info("V69：每日出勤紀錄不再於開頁自動載入；請按『載入/重新載入出勤紀錄』。")
summary_df = _attendance_summary(current_daily_df)
met1, met2, met3, met4 = st.columns(4)
met1.metric("所選日期出勤表筆數 / Records", f"{len(current_daily_df):,}")
met2.metric("出勤 / Attendance", f"{int(current_daily_df.get('is_today_attendance', pd.Series(dtype=bool)).map(_to_bool_value).sum()) if not current_daily_df.empty else 0:,}")
met3.metric("在廠 / In Factory", f"{int(current_daily_df.get('is_in_factory', pd.Series(dtype=bool)).map(_to_bool_value).sum()) if not current_daily_df.empty else 0:,}")
met4.metric("該日未紀錄 / Missing", f"{len(selected_missing_df):,}")

ex1, ex2 = st.columns([1, 3])
_daily_excel_sig = f"{selected_date}:{_v30032_df_signature(current_daily_df)}:{_v30032_df_signature(selected_missing_df)}"
if ex1.button("準備每日出勤 Excel / Prepare Excel", use_container_width=True, key="v69_prepare_daily_attendance_excel"):
    st.session_state["v69_daily_attendance_excel_bytes"] = _make_daily_attendance_excel(current_daily_df, selected_missing_df, selected_date)
    st.session_state["v69_daily_attendance_excel_date"] = selected_date
    st.session_state[V30032_DAILY_EXCEL_SIG_KEY] = _daily_excel_sig
if "v69_daily_attendance_excel_bytes" in st.session_state and st.session_state.get(V30032_DAILY_EXCEL_SIG_KEY) == _daily_excel_sig:
    st.download_button(
        "⬇ 下載每日出勤紀錄 Excel / Download Daily Attendance Excel",
        data=st.session_state["v69_daily_attendance_excel_bytes"],
        file_name=f"SPT_每日出勤紀錄_{st.session_state.get('v69_daily_attendance_excel_date', selected_date)}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="v234_download_daily_attendance_excel",
    )
else:
    ex2.caption("V69：Excel 不再於每次 rerun 自動產生，按左側按鈕後才準備下載檔。")

with st.expander("所選日期未紀錄名單 / Missing Records By Selected Attendance Date", expanded=False):
    render_table(selected_missing_df, "v234_selected_date_missing_records", editable=False, height=360)
# ===== V234 新增：每日出勤紀錄表 END =====

st.divider()
st.subheader("今日未紀錄名單 / Missing Today")
today = today_date().strftime("%Y-%m-%d")
mt1, mt2 = st.columns([1, 3])
if mt1.button("重新計算今日未紀錄 / Refresh Missing Today", use_container_width=True, key="v69_refresh_missing_today"):
    current_attendance_df = _current_internal_df() if STATE_KEY in st.session_state else ensure_cols(load_employees())
    st.session_state[MISSING_TODAY_DF_KEY] = _build_missing_today_df(current_attendance_df, today)
    st.session_state[TODAY_ABSENT_DF_KEY] = _build_today_absent_df(current_attendance_df)
    st.session_state[MISSING_TODAY_LOADED_KEY] = True
    st.session_state[MISSING_TODAY_TS_KEY] = today

df = st.session_state.get(MISSING_TODAY_DF_KEY, pd.DataFrame()) if st.session_state.get(MISSING_TODAY_LOADED_KEY, False) else pd.DataFrame()
absent_df = st.session_state.get(TODAY_ABSENT_DF_KEY, pd.DataFrame()) if st.session_state.get(MISSING_TODAY_LOADED_KEY, False) else pd.DataFrame()
metric_a, metric_b = st.columns(2)
metric_a.metric("今日未紀錄人數 / Missing Records", f"{len(df):,}")
metric_b.metric("今日未出勤人數 / Not Attendance", f"{len(absent_df):,}")
st.caption("V300.93：今日未紀錄會比對 01/time_records；今日未出勤只依 04 人員主檔/07 今日出勤設定計算：啟用 + 在廠 + 今日出勤未勾選。按『重新計算今日未紀錄』才刷新兩項統計。")
if st.session_state.get(MISSING_TODAY_LOADED_KEY, False):
    render_table(df, "missing_today_v202", editable=False, height=460)
    with st.expander("今日未出勤人員明細 / Today Not Attendance Details", expanded=False):
        render_table(absent_df, "v30093_today_absent_details", editable=False, height=360)
else:
    st.info("尚未載入今日未紀錄與今日未出勤統計。")

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

