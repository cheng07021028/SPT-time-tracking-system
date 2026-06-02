# -*- coding: utf-8 -*-
"""SPT V163 daily close / lock service.

Purpose
-------
Provide a conservative daily settlement layer for the time-tracking system.
It records which work dates are closed, blocks accidental edits to closed dates,
creates a pre-close health snapshot, and optionally creates a full backup.

Design rules
------------
- Closing a date never deletes or rewrites time-record rows.
- Reopening a date is explicit and audited in the daily-close state history.
- A date with active unfinished records is blocked by default.
- The state file is written with V162 safe JSON write when available.
- Lock checks are intentionally small and side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
import json
import os
import re

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "14_data_health" / "daily_close_state.json"
REPORT_DIR = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "14_data_health" / "daily_close_reports"
VERSION = "V163_DAILY_CLOSE_LOCK"
TERMINAL_STATUSES = {"暫停", "下班", "完工", "已結束", "結束", "停止", "completed", "finished", "paused", "off_duty"}
ACTIVE_STATUS = "作業中"


def _now_text() -> str:
    try:
        from services.timezone_service import now_text  # type: ignore
        return str(now_text())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_text() -> str:
    try:
        from services.timezone_service import today_text  # type: ignore
        return str(today_text())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _normalize_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip().replace("/", "-")
    if not text:
        return ""
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text[:10]


def _date_from_row(row: Any) -> str:
    getter = row.get if hasattr(row, "get") else lambda k, default=None: default
    for col in ("start_date", "work_date", "日期 / Date", "開始日期 / Start Date", "日期", "work_day"):
        v = getter(col, None)
        d = _normalize_date(v)
        if d:
            return d
    for col in ("start_timestamp", "Start Timestamp", "開始時間戳 / Start Timestamp", "開始時間", "created_at"):
        v = getter(col, None)
        d = _normalize_date(v)
        if d:
            return d
    return ""


def _blank(value: Any) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _json_default(value: Any) -> Any:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value)


def _read_json(path: Path, default: Any) -> Any:
    try:
        from services.safe_file_write_service import read_json_safely  # type: ignore
        return read_json_safely(path, restore_if_corrupt=True, default=default)
    except Exception:
        pass
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: Any, reason: str) -> dict[str, Any]:
    try:
        from services.safe_file_write_service import atomic_write_json_safely  # type: ignore
        return atomic_write_json_safely(path, payload, reason=reason, default=_json_default)
    except Exception:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))
        os.replace(tmp, path)
        return {"ok": True, "path": str(path), "reason": reason, "updated_at": _now_text()}


def _empty_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "updated_at": _now_text(),
        "closed_dates": {},
        "history": [],
    }


def load_daily_close_state() -> dict[str, Any]:
    state = _read_json(STATE_PATH, _empty_state())
    if not isinstance(state, dict):
        state = _empty_state()
    state.setdefault("version", VERSION)
    state.setdefault("updated_at", _now_text())
    state.setdefault("closed_dates", {})
    state.setdefault("history", [])
    if not isinstance(state.get("closed_dates"), dict):
        state["closed_dates"] = {}
    if not isinstance(state.get("history"), list):
        state["history"] = []
    return state


def save_daily_close_state(state: dict[str, Any], reason: str = "save_daily_close_state") -> dict[str, Any]:
    state = dict(state or _empty_state())
    state["version"] = VERSION
    state["updated_at"] = _now_text()
    return _write_json(STATE_PATH, state, reason=reason)


def is_work_date_closed(work_date: Any) -> bool:
    d = _normalize_date(work_date)
    if not d:
        return False
    item = (load_daily_close_state().get("closed_dates") or {}).get(d) or {}
    return str(item.get("status") or "").lower() == "closed"


def closed_date_info(work_date: Any) -> dict[str, Any]:
    d = _normalize_date(work_date)
    if not d:
        return {}
    item = (load_daily_close_state().get("closed_dates") or {}).get(d) or {}
    return dict(item) if isinstance(item, dict) else {}


def assert_work_date_open(work_date: Any, operation: str = "modify") -> None:
    d = _normalize_date(work_date)
    if d and is_work_date_closed(d):
        info = closed_date_info(d)
        raise ValueError(
            f"{d} 已完成每日結帳並鎖定，禁止執行「{operation}」。"
            f"如需更正，請先由管理員至 14. 資料健康檢查中心重新開啟該日期。"
            f"結帳人={info.get('closed_by','')}，結帳時間={info.get('closed_at','')}。"
        )


def extract_work_dates_from_dataframe(df: pd.DataFrame | None) -> list[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    dates: list[str] = []
    for _, row in df.iterrows():
        d = _date_from_row(row)
        if d and d not in dates:
            dates.append(d)
    return dates


def assert_dataframe_dates_open(df: pd.DataFrame | None, operation: str = "save") -> None:
    for d in extract_work_dates_from_dataframe(df):
        assert_work_date_open(d, operation=operation)


def _query_df(sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
    try:
        from services.db_service import query_df  # type: ignore
        df = query_df(sql, tuple(params))
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def load_time_records_for_date(work_date: Any) -> pd.DataFrame:
    d = _normalize_date(work_date)
    frames: list[pd.DataFrame] = []
    if d:
        try:
            from services.time_record_service import load_records  # type: ignore
            df = load_records(start_date=d, end_date=d)
            if isinstance(df, pd.DataFrame) and not df.empty:
                frames.append(df.copy())
        except Exception:
            pass
        # SQLite fallback. Safe read only.
        df_sql = _query_df(
            """
            SELECT * FROM time_records
            WHERE COALESCE(start_date, substr(start_timestamp,1,10), '')=?
            ORDER BY id
            """,
            (d,),
        )
        if not df_sql.empty:
            frames.append(df_sql)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    # Conservative de-dupe: prefer record_key, then business key, then id.
    keys: list[str] = []
    for _, r in out.iterrows():
        rk = str(r.get("record_key") or "").strip()
        if rk:
            keys.append("rk:" + rk)
            continue
        biz = "|".join(str(r.get(c) or "").strip() for c in ("employee_id", "employee_name", "work_order", "process_name", "start_timestamp"))
        if biz.strip("|"):
            keys.append("biz:" + biz)
            continue
        keys.append("id:" + str(r.get("id") or len(keys)))
    out["_v163_key"] = keys
    out = out.drop_duplicates(subset=["_v163_key"], keep="last").drop(columns=["_v163_key"], errors="ignore")
    return out.reset_index(drop=True)


def _is_unfinished_row(row: Any) -> bool:
    getter = row.get if hasattr(row, "get") else lambda k, default=None: default
    status = str(getter("status", "") or "").strip()
    end_ts = getter("end_timestamp", None)
    end_action = str(getter("end_action", "") or "").strip()
    if status in TERMINAL_STATUSES or end_action in TERMINAL_STATUSES:
        return False
    return status == ACTIVE_STATUS and _blank(end_ts)


def active_records_for_date(work_date: Any) -> pd.DataFrame:
    df = load_time_records_for_date(work_date)
    if df.empty:
        return pd.DataFrame()
    mask = df.apply(_is_unfinished_row, axis=1)
    return df.loc[mask].copy().reset_index(drop=True)


def daily_close_report(work_date: Any) -> dict[str, Any]:
    d = _normalize_date(work_date) or _today_text()
    records = load_time_records_for_date(d)
    active = active_records_for_date(d)
    status_counts: dict[str, int] = {}
    if not records.empty and "status" in records.columns:
        status_counts = {str(k): int(v) for k, v in records["status"].fillna("").astype(str).value_counts(dropna=False).to_dict().items()}
    health_summary: dict[str, Any] = {}
    try:
        from services.time_record_integrity_service import audit_time_record_integrity  # type: ignore
        result = audit_time_record_integrity(d, d)
        health_summary = dict(result.get("summary", {}) if isinstance(result, dict) else {})
    except Exception as exc:
        health_summary = {"error": str(exc)}
    info = closed_date_info(d)
    return {
        "ok": True,
        "work_date": d,
        "checked_at": _now_text(),
        "closed": is_work_date_closed(d),
        "close_info": info,
        "record_count": int(len(records)),
        "active_count": int(len(active)),
        "status_counts": status_counts,
        "health_summary": health_summary,
        "records_preview": records.head(200).to_dict(orient="records") if not records.empty else [],
        "active_records": active.to_dict(orient="records") if not active.empty else [],
    }


def _safe_user_name(default: str = "system") -> str:
    try:
        import streamlit as st  # type: ignore
        user = st.session_state.get("user") or st.session_state.get("current_user") or {}
        if isinstance(user, dict):
            return str(user.get("username") or user.get("account") or user.get("user_name") or default)
    except Exception:
        pass
    return default


def _make_backup(reason: str) -> dict[str, Any]:
    try:
        from services.backup_restore_service import create_full_backup_snapshot  # type: ignore
        result = create_full_backup_snapshot(reason=reason, save_to_disk=True)
        if isinstance(result, dict):
            # zip bytes can be very large and should not be stored in close state.
            result = dict(result)
            result.pop("zip_bytes", None)
            return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "backup_restore_service unavailable"}


def close_work_date(
    work_date: Any,
    *,
    closed_by: str | None = None,
    note: str = "",
    require_no_active: bool = True,
    create_backup: bool = True,
    block_on_critical_health: bool = True,
) -> dict[str, Any]:
    """Close one work date and mark it locked.

    This function is conservative: it refuses to close when unfinished records exist,
    unless require_no_active=False is explicitly passed.
    """
    d = _normalize_date(work_date) or _today_text()
    state = load_daily_close_state()
    existing = (state.get("closed_dates") or {}).get(d) or {}
    if str(existing.get("status") or "").lower() == "closed":
        return {"ok": False, "reason": "already_closed", "work_date": d, "info": existing}

    report = daily_close_report(d)
    active_count = int(report.get("active_count") or 0)
    if require_no_active and active_count > 0:
        return {"ok": False, "reason": "active_records_exist", "work_date": d, "active_count": active_count, "report": report}

    health = report.get("health_summary") if isinstance(report.get("health_summary"), dict) else {}
    critical_count = int(health.get("critical_count", 0) or 0) if isinstance(health, dict) else 0
    if block_on_critical_health and critical_count > 0:
        return {"ok": False, "reason": "critical_health_issues", "work_date": d, "critical_count": critical_count, "report": report}

    backup_result = _make_backup(f"daily_close_{d}") if create_backup else {"ok": True, "skipped": True}
    now = _now_text()
    entry = {
        "status": "closed",
        "work_date": d,
        "closed_at": now,
        "closed_by": closed_by or _safe_user_name(),
        "note": note,
        "record_count": int(report.get("record_count") or 0),
        "active_count": active_count,
        "health_summary": health,
        "backup": backup_result,
    }
    state.setdefault("closed_dates", {})[d] = entry
    state.setdefault("history", []).append({"event": "CLOSE", "work_date": d, "at": now, "by": entry["closed_by"], "note": note, "entry": entry})
    write_result = save_daily_close_state(state, reason=f"close_work_date_{d}")
    try:
        from services.log_service import write_log  # type: ignore
        write_log("DAILY_CLOSE", f"每日工時結帳：{d}，筆數={entry['record_count']}，未結束={active_count}", "daily_close", level="INFO")
    except Exception:
        pass
    return {"ok": True, "work_date": d, "entry": entry, "write_result": write_result, "report": report}


def reopen_work_date(work_date: Any, *, reopened_by: str | None = None, reason: str = "管理員重新開啟日期更正") -> dict[str, Any]:
    d = _normalize_date(work_date) or _today_text()
    state = load_daily_close_state()
    entry = (state.get("closed_dates") or {}).get(d) or {}
    now = _now_text()
    if not entry or str(entry.get("status") or "").lower() != "closed":
        return {"ok": False, "reason": "not_closed", "work_date": d, "info": entry}
    new_entry = dict(entry)
    new_entry.update({"status": "reopened", "reopened_at": now, "reopened_by": reopened_by or _safe_user_name(), "reopen_reason": reason})
    state.setdefault("closed_dates", {})[d] = new_entry
    state.setdefault("history", []).append({"event": "REOPEN", "work_date": d, "at": now, "by": new_entry["reopened_by"], "reason": reason, "previous": entry})
    write_result = save_daily_close_state(state, reason=f"reopen_work_date_{d}")
    try:
        from services.log_service import write_log  # type: ignore
        write_log("DAILY_REOPEN", f"每日工時結帳重新開啟：{d}，原因={reason}", "daily_close", level="WARN")
    except Exception:
        pass
    return {"ok": True, "work_date": d, "entry": new_entry, "write_result": write_result}


def list_daily_close_status(start_date: Any | None = None, end_date: Any | None = None, days: int = 14) -> pd.DataFrame:
    end = _normalize_date(end_date) or _today_text()
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
    except Exception:
        end_dt = datetime.now().date()
    if start_date:
        start = _normalize_date(start_date)
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d").date()
        except Exception:
            start_dt = end_dt - timedelta(days=max(int(days) - 1, 0))
    else:
        start_dt = end_dt - timedelta(days=max(int(days) - 1, 0))
    state = load_daily_close_state()
    closed = state.get("closed_dates") or {}
    rows: list[dict[str, Any]] = []
    cur = start_dt
    while cur <= end_dt:
        d = cur.strftime("%Y-%m-%d")
        info = closed.get(d) or {}
        rows.append({
            "work_date": d,
            "status": info.get("status", "open"),
            "closed": str(info.get("status", "")).lower() == "closed",
            "closed_at": info.get("closed_at", ""),
            "closed_by": info.get("closed_by", ""),
            "record_count": info.get("record_count", ""),
            "active_count_at_close": info.get("active_count", ""),
            "note": info.get("note", ""),
        })
        cur += timedelta(days=1)
    return pd.DataFrame(rows)


def export_daily_close_excel_bytes(work_date: Any) -> bytes:
    d = _normalize_date(work_date) or _today_text()
    report = daily_close_report(d)
    state = load_daily_close_state()
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame([{
            "work_date": d,
            "generated_at": _now_text(),
            "closed": report.get("closed"),
            "record_count": report.get("record_count"),
            "active_count": report.get("active_count"),
        }]).to_excel(writer, index=False, sheet_name="結帳摘要")
        active = pd.DataFrame(report.get("active_records") or [])
        active.to_excel(writer, index=False, sheet_name="未結束作業")
        preview = pd.DataFrame(report.get("records_preview") or [])
        preview.to_excel(writer, index=False, sheet_name="當日工時預覽")
        pd.DataFrame([report.get("health_summary") or {}]).to_excel(writer, index=False, sheet_name="健康檢查摘要")
        pd.DataFrame(state.get("history") or []).tail(300).to_excel(writer, index=False, sheet_name="結帳歷程")
    return bio.getvalue()
