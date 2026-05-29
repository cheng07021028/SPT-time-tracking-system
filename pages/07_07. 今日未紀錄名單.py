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
from services.time_record_service import load_records
from services.table_ui_service import render_table

st.set_page_config(page_title="07. 今日未紀錄名單", page_icon="⟁️", layout="wide")
apply_theme()
require_module_access("07_missing")
render_header(
    "07｜今日未紀錄名單",
    "每日出勤紀錄、未紀錄工時人員查詢、Excel 匯出｜永久保存且穩定編輯。",
)

STATE_KEY = "v202_today_attendance_editor"
EDITOR_REV_KEY = "v202_today_attendance_editor_rev"
EDITOR_IGNORE_RETURN_KEY = "v263_today_attendance_ignore_next_editor_return"
COLS = [
    "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at",
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
BOOL_INTERNAL_COLS = ["is_active", "is_in_factory", "is_today_attendance"]

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
    return _normalise_daily_rows(_extract_daily_rows(_read_daily_payload()))


def _save_all_daily_attendance_rows(rows: list[dict[str, Any]], *, reason: str = "save_daily_attendance") -> None:
    clean = _normalise_daily_rows(rows)
    payload = {
        "authority_schema": "SPT-07-DailyAttendance-V234",
        "module_key": DAILY_MODULE_KEY,
        "kind": "records",
        "updated_at": _now_text(),
        "reason": reason,
        "tables": {"daily_attendance": clean},
        "table_counts": {"daily_attendance": len(clean)},
        "records": clean,
    }
    _atomic_write_json(DAILY_RECORDS_PATH, payload, reason=reason)


def _append_daily_event(action: str, rows: list[dict[str, Any]], *, target_date: str, note: str = "") -> None:
    try:
        DAILY_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    all_rows = _load_all_daily_attendance_rows()
    rows = [r for r in all_rows if _date_to_text(r.get("attendance_date")) == target_date]
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
    if DAILY_DELETE_COL in work.columns:
        work["_delete"] = work[DAILY_DELETE_COL].map(_to_bool_value).fillna(False).astype(bool)
        work = work.drop(columns=[DAILY_DELETE_COL], errors="ignore")
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


def _save_daily_editor_df(editor_df: pd.DataFrame, target_date: str) -> dict[str, Any]:
    incoming = _from_daily_editor_df(editor_df, target_date)
    all_existing = _load_all_daily_attendance_rows()
    keep_other_dates = [r for r in all_existing if _date_to_text(r.get("attendance_date")) != target_date]

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
    final_rows = keep_other_dates + list(dedup.values())
    _save_all_daily_attendance_rows(final_rows, reason="v234_save_daily_attendance")
    _append_daily_event("SAVE_DAILY_ATTENDANCE", list(dedup.values()), target_date=target_date, note=f"deleted={len(deleted_rows)}")
    if deleted_rows:
        _append_daily_event("DELETE_DAILY_ATTENDANCE", deleted_rows, target_date=target_date, note="deleted rows from 07 daily attendance editor")
    return {"saved": len(dedup), "deleted": len(deleted_rows), "total": len(final_rows)}


def _build_missing_from_daily_attendance(att_df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    if att_df is None or att_df.empty:
        return pd.DataFrame(columns=[
            "employee_id", "employee_name", "department", "title", "attendance_status",
            "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count",
        ])
    att = pd.DataFrame(att_df).copy()
    for c in DAILY_COLS:
        if c not in att.columns:
            att[c] = False if c in DAILY_BOOL_COLS else ""
    att["employee_id"] = att["employee_id"].fillna("").astype(str).str.strip()
    att = att[(att["employee_id"] != "") & (att["is_in_factory"].map(_to_bool_value)) & (att["is_today_attendance"].map(_to_bool_value))].copy()
    if att.empty:
        att["last_start_time"] = ""
        att["today_record_count"] = 0
        return att[["employee_id", "employee_name", "department", "title", "attendance_status", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]]
    try:
        rec = load_records(start_date=target_date, end_date=target_date)
    except Exception:
        rec = pd.DataFrame()
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty or "employee_id" not in rec.columns:
        att["last_start_time"] = ""
        att["today_record_count"] = 0
        return att[["employee_id", "employee_name", "department", "title", "attendance_status", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]].sort_values("employee_id")
    rec = rec.copy()
    rec["employee_id"] = rec["employee_id"].fillna("").astype(str).str.strip()
    rec["__record_date"] = _date_text_series(rec)
    rec = rec[(rec["employee_id"] != "") & (rec["__record_date"] == str(target_date))].copy()
    if rec.empty:
        att["last_start_time"] = ""
        att["today_record_count"] = 0
        return att[["employee_id", "employee_name", "department", "title", "attendance_status", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]].sort_values("employee_id")
    if "start_timestamp" not in rec.columns:
        rec["start_timestamp"] = rec["start_time"] if "start_time" in rec.columns else ""
    grp = rec.groupby("employee_id", dropna=False).agg(
        last_start_time=("start_timestamp", "max"),
        today_record_count=("employee_id", "size"),
    ).reset_index()
    out = att.merge(grp, on="employee_id", how="left")
    out["today_record_count"] = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    out["last_start_time"] = out["last_start_time"].fillna("").astype(str)
    out = out[out["today_record_count"] == 0].copy()
    return out[["employee_id", "employee_name", "department", "title", "attendance_status", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]].sort_values("employee_id")


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
            out[c] = False if c in {"is_active", "is_in_factory", "is_today_attendance"} else ""
    for c in BOOL_INTERNAL_COLS:
        out[c] = out[c].map(_to_bool_value).fillna(False).astype(bool)
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
            to_editor_df=_to_editor_df,
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
    # V65：今日未紀錄名單改用 04 人員權威檔 + 02/01 工時權威檔即時計算。
    # 不再查 SQLite employees 快取，避免 Reboot / GitHub 永久檔已更新但 SQLite 快取未同步，造成缺勤人數誤顯示 0。
    emp = ensure_cols(employee_df)
    if emp.empty:
        return pd.DataFrame(columns=[
            "employee_id", "employee_name", "department", "title",
            "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count",
        ])
    for c in BOOL_INTERNAL_COLS:
        emp[c] = emp[c].map(_to_bool_value).fillna(False).astype(bool)
    emp = emp[(emp["is_active"]) & (emp["is_in_factory"]) & (emp["is_today_attendance"])].copy()
    emp["employee_id"] = emp["employee_id"].fillna("").astype(str).str.strip()
    emp = emp[emp["employee_id"] != ""].copy()
    if emp.empty:
        out = emp.copy()
        out["last_start_time"] = ""
        out["today_record_count"] = 0
        return out[["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]]

    try:
        rec = load_records(start_date=target_date, end_date=target_date)
    except Exception:
        rec = pd.DataFrame()
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty or "employee_id" not in rec.columns:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]].sort_values("employee_id")

    rec = rec.copy()
    rec["employee_id"] = rec["employee_id"].fillna("").astype(str).str.strip()
    rec["__record_date"] = _date_text_series(rec)
    rec = rec[(rec["employee_id"] != "") & (rec["__record_date"] == str(target_date))].copy()
    if rec.empty:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]].sort_values("employee_id")

    if "start_timestamp" not in rec.columns:
        if "start_time" in rec.columns:
            rec["start_timestamp"] = rec["start_time"]
        else:
            rec["start_timestamp"] = ""
    grp = rec.groupby("employee_id", dropna=False).agg(
        last_start_time=("start_timestamp", "max"),
        today_record_count=("employee_id", "size"),
    ).reset_index()
    out = emp.merge(grp, on="employee_id", how="left")
    out["today_record_count"] = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    out["last_start_time"] = out["last_start_time"].fillna("").astype(str)
    out = out[out["today_record_count"] == 0].copy()
    return out[["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]].sort_values("employee_id")


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
    # V120：穩定編輯模式。把 data_editor 與儲存按鈕放在同一個 form，
    # 避免 checkbox / cell edit 每一下都 rerun 跳頁；批次按鈕與原儲存邏輯不變。
    with st.form("v120_today_attendance_stable_editor_form", clear_on_submit=False):
        edited = st.data_editor(
            editor_df,
            hide_index=True,
            use_container_width=True,
            height=460,
            disabled=[DISPLAY_ROW_NO] + [DISPLAY_COLUMNS[c] for c in ["employee_id", "employee_name", "department", "title", "note", "created_at", "updated_at"]],
            column_order=EDITOR_COLS,
            column_config={
                DISPLAY_ROW_NO: st.column_config.NumberColumn("序號 / No.", width="small"),
                DISPLAY_COLUMNS["employee_id"]: st.column_config.TextColumn("工號 / Employee ID", width="medium"),
                DISPLAY_COLUMNS["employee_name"]: st.column_config.TextColumn("姓名 / Name", width="medium"),
                DISPLAY_COLUMNS["department"]: st.column_config.TextColumn("單位 / Department", width="medium"),
                DISPLAY_COLUMNS["title"]: st.column_config.TextColumn("職稱 / Title", width="medium"),
                DISPLAY_COLUMNS["is_active"]: st.column_config.CheckboxColumn("啟用 / Active", width="medium"),
                DISPLAY_COLUMNS["is_in_factory"]: st.column_config.CheckboxColumn("在廠 / In Factory", width="medium"),
                DISPLAY_COLUMNS["is_today_attendance"]: st.column_config.CheckboxColumn("今日出勤 / Today Attendance", width="medium"),
                DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width="large"),
                DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", width="medium"),
                DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", width="medium"),
            },
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
if st.session_state.get(DAILY_LAST_DATE_KEY) != selected_date or DAILY_STATE_KEY not in st.session_state:
    st.session_state[DAILY_STATE_KEY] = _load_daily_rows_for_date(selected_date, current_employee_df)
    st.session_state[DAILY_LAST_DATE_KEY] = selected_date
    st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1

msg = st.session_state.pop(DAILY_MESSAGE_KEY, "")
if msg:
    st.success(msg)

btn1, btn2, btn3, btn4 = st.columns(4)
if btn1.button("⟳ 重新載入出勤紀錄 / Reload", use_container_width=True, key="v234_daily_reload"):
    st.session_state[DAILY_STATE_KEY] = _load_daily_rows_for_date(selected_date, current_employee_df)
    st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
    rerun()
if btn2.button("＋ 依人員名單補齊 / Fill From Employees", use_container_width=True, key="v234_daily_fill_from_employees"):
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
    df0 = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame())).copy()
    if not df0.empty:
        df0["is_today_attendance"] = True
        df0["is_in_factory"] = True
        df0["attendance_status"] = "出勤"
        st.session_state[DAILY_STATE_KEY] = df0
        st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
        rerun()
if btn4.button("☐ 全部未出勤 / Clear Attendance", use_container_width=True, key="v234_daily_clear_attendance"):
    df0 = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame())).copy()
    if not df0.empty:
        df0["is_today_attendance"] = False
        df0["attendance_status"] = "未出勤"
        st.session_state[DAILY_STATE_KEY] = df0
        st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
        rerun()

_daily_editor_key = f"v234_daily_attendance_editor_{selected_date}_{st.session_state.get(DAILY_REV_KEY, 0)}"
_daily_df = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame()), columns=DAILY_COLS)
_daily_view = _to_daily_editor_df(_daily_df)
can_edit_daily = can_edit
if not can_edit_daily:
    st.warning("目前帳號沒有 07 今日未紀錄名單編輯權限，只能查看每日出勤紀錄。")
    render_table(_daily_df, "v234_daily_attendance_readonly", editable=False, height=460)
else:
    with st.form("v234_daily_attendance_stable_editor_form", clear_on_submit=False):
        daily_edited = st.data_editor(
            _daily_view,
            hide_index=True,
            use_container_width=True,
            height=520,
            num_rows="dynamic",
            column_order=DAILY_EDITOR_COLS,
            disabled=[
                DAILY_DISPLAY_ROW_NO,
                DAILY_DISPLAY_COLUMNS["record_id"],
                DAILY_DISPLAY_COLUMNS["attendance_date"],
                DAILY_DISPLAY_COLUMNS["created_at"],
                DAILY_DISPLAY_COLUMNS["updated_at"],
                DAILY_DISPLAY_COLUMNS["updated_by"],
            ],
            column_config={
                DAILY_DELETE_COL: st.column_config.CheckboxColumn("刪除 / Delete", width="small"),
                DAILY_DISPLAY_ROW_NO: st.column_config.NumberColumn("序號 / No.", width="small"),
                DAILY_DISPLAY_COLUMNS["employee_id"]: st.column_config.TextColumn("工號 / Employee ID", width="medium"),
                DAILY_DISPLAY_COLUMNS["employee_name"]: st.column_config.TextColumn("姓名 / Name", width="medium"),
                DAILY_DISPLAY_COLUMNS["department"]: st.column_config.TextColumn("單位 / Department", width="medium"),
                DAILY_DISPLAY_COLUMNS["title"]: st.column_config.TextColumn("職稱 / Title", width="medium"),
                DAILY_DISPLAY_COLUMNS["attendance_status"]: st.column_config.SelectboxColumn(
                    "出勤狀態 / Attendance Status",
                    options=["出勤", "請假", "公出", "休假", "未出勤", "離職", "其他"],
                    width="medium",
                ),
                DAILY_DISPLAY_COLUMNS["is_in_factory"]: st.column_config.CheckboxColumn("在廠 / In Factory", width="medium"),
                DAILY_DISPLAY_COLUMNS["is_today_attendance"]: st.column_config.CheckboxColumn("出勤 / Attendance", width="medium"),
                DAILY_DISPLAY_COLUMNS["check_in_time"]: st.column_config.TextColumn("到廠時間 / Check In", width="medium", help="可填 08:00 或 2026-05-29 08:00"),
                DAILY_DISPLAY_COLUMNS["check_out_time"]: st.column_config.TextColumn("離廠時間 / Check Out", width="medium"),
                DAILY_DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width="large"),
                DAILY_DISPLAY_COLUMNS["record_id"]: st.column_config.TextColumn("紀錄ID / Record ID", width="medium"),
                DAILY_DISPLAY_COLUMNS["attendance_date"]: st.column_config.TextColumn("日期 / Date", width="medium"),
                DAILY_DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", width="medium"),
                DAILY_DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", width="medium"),
                DAILY_DISPLAY_COLUMNS["updated_by"]: st.column_config.TextColumn("更新者 / Updated By", width="medium"),
            },
            key=_daily_editor_key,
        )
        daily_submit = st.form_submit_button("▣ 儲存每日出勤紀錄 / Save Daily Attendance Records", type="primary", use_container_width=True)

    if isinstance(daily_edited, pd.DataFrame):
        # 在 submit 之前也保留目前畫面草稿，切換下載或其他操作時不會丟失。
        st.session_state[DAILY_STATE_KEY] = _from_daily_editor_df(daily_edited, selected_date).drop(columns=["_delete"], errors="ignore")
    if daily_submit:
        result = _save_daily_editor_df(daily_edited, selected_date)
        st.session_state[DAILY_STATE_KEY] = _load_daily_rows_for_date(selected_date, current_employee_df)
        st.session_state[DAILY_MESSAGE_KEY] = f"每日出勤紀錄已儲存：保存 {result.get('saved', 0)} 筆，刪除 {result.get('deleted', 0)} 筆，永久紀錄總筆數 {result.get('total', 0)} 筆。"
        st.session_state[DAILY_REV_KEY] = int(st.session_state.get(DAILY_REV_KEY, 0)) + 1
        rerun()

current_daily_df = pd.DataFrame(st.session_state.get(DAILY_STATE_KEY, pd.DataFrame()), columns=DAILY_COLS)
selected_missing_df = _build_missing_from_daily_attendance(current_daily_df, selected_date)
summary_df = _attendance_summary(current_daily_df)
met1, met2, met3, met4 = st.columns(4)
met1.metric("所選日期出勤表筆數 / Records", f"{len(current_daily_df):,}")
met2.metric("出勤 / Attendance", f"{int(current_daily_df.get('is_today_attendance', pd.Series(dtype=bool)).map(_to_bool_value).sum()) if not current_daily_df.empty else 0:,}")
met3.metric("在廠 / In Factory", f"{int(current_daily_df.get('is_in_factory', pd.Series(dtype=bool)).map(_to_bool_value).sum()) if not current_daily_df.empty else 0:,}")
met4.metric("該日未紀錄 / Missing", f"{len(selected_missing_df):,}")

excel_bytes = _make_daily_attendance_excel(current_daily_df, selected_missing_df, selected_date)
st.download_button(
    "⬇ 下載每日出勤紀錄 Excel / Download Daily Attendance Excel",
    data=excel_bytes,
    file_name=f"SPT_每日出勤紀錄_{selected_date}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
    key="v234_download_daily_attendance_excel",
)

with st.expander("所選日期未紀錄名單 / Missing Records By Selected Attendance Date", expanded=False):
    render_table(selected_missing_df, "v234_selected_date_missing_records", editable=False, height=360)
# ===== V234 新增：每日出勤紀錄表 END =====

st.divider()
st.subheader("今日未紀錄名單 / Missing Today")
today = today_date().strftime("%Y-%m-%d")
current_attendance_df = _current_internal_df() if STATE_KEY in st.session_state else ensure_cols(load_employees())
df = _build_missing_today_df(current_attendance_df, today)

st.metric("今日未紀錄人數 / Missing Records", f"{len(df):,}")
st.caption("V66：此區依目前畫面暫存的『啟用 / 在廠 / 今日出勤』狀態，加上今日工時權威檔即時計算；ID 為空不影響判斷，實際主鍵使用工號。")
render_table(df, "missing_today_v202", editable=False, height=460)
