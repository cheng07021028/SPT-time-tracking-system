# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime
import getpass
from typing import Any

import pandas as pd
from services.timezone_service import now_text, now_stamp, today_text, today_date

from .db_service import execute, query_df

try:
    from .db_service import clear_query_cache
except Exception:  # 舊版相容
    def clear_query_cache() -> None:  # type: ignore
        return None




def _current_log_user(default: str = "SYSTEM") -> str:
    """Return the real Streamlit login account instead of the OS account.

    Streamlit Cloud normally runs as appuser/adminuser. 06 LOG查詢要看的是
    哪個系統帳號執行動作，所以優先讀取登入模組寫入的 session_state。
    """
    try:
        import streamlit as st  # local import: log_service is also used by scripts
        ss = getattr(st, "session_state", {})
        for key in (
            "auth_username",
            "auth_user",
            "username",
            "current_username",
            "login_username",
        ):
            value = str(ss.get(key, "") or "").strip()
            if value and value.lower() not in {"none", "nan", "null"}:
                return value
        for key in ("current_user", "user", "auth_user_info"):
            value = ss.get(key)
            if isinstance(value, dict):
                for sub_key in ("username", "account", "user", "name"):
                    sub_value = str(value.get(sub_key, "") or "").strip()
                    if sub_value and sub_value.lower() not in {"none", "nan", "null"}:
                        return sub_value
    except Exception:
        pass
    try:
        os_user = str(getpass.getuser() or "").strip()
        return os_user or default
    except Exception:
        return default


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"none", "nan", "null", "<na>"}:
        return ""
    return text


_ACTION_LABELS = {
    "INSERT": "新增資料",
    "UPDATE": "修改資料",
    "DELETE": "刪除資料",
    "REPLACE": "覆蓋資料",
    "START_WORK": "開始作業",
    "FINISH_WORK": "結束作業",
    "END_WORK": "結束作業",
    "PAUSE_WORK": "暫停作業",
    "SAVE_TIME_RECORDS": "儲存工時紀錄",
    "DELETE_TIME_RECORDS": "刪除工時紀錄",
    "SYNC_TIME_RECORDS_01_02": "同步 01/02 工時紀錄",
    "SYNC_RECALC_TIME_RECORDS_01_02": "重算並同步 01/02",
    "IMPORT_WORK_ORDERS": "匯入製令資料",
    "SAVE_WORK_ORDERS": "儲存製令資料",
    "IMPORT_EMPLOYEES": "匯入人員資料",
    "SAVE_EMPLOYEES": "儲存人員資料",
    "SAVE_PROCESS_OPTIONS": "儲存工段設定",
    "DELETE_PROCESS_OPTIONS": "刪除工段設定",
    "SAVE_PROCESS_CATEGORIES": "儲存類別設定",
    "DELETE_PROCESS_CATEGORIES": "刪除類別設定",
    "SAVE_REST_PERIODS": "儲存休息時間",
    "DELETE_REST_PERIODS": "刪除休息時間",
    "DELETE_LOG_RANGE": "刪除 LOG 區間",
    "AUTO_INIT_DATABASE": "初始化資料庫",
}

_TABLE_LABELS = {
    "time_records": "01 工時紀錄 / 02 歷史紀錄",
    "work_orders": "03 製令管理",
    "employees": "04 人員名單 / 07 今日未紀錄名單",
    "process_options": "13 系統設定-工段",
    "process_model_options": "13 系統設定-機型工段",
    "process_category_options": "13 系統設定-類別工段",
    "process_categories": "13 系統設定-類別",
    "rest_periods": "13 系統設定-休息時間",
    "app_settings": "13 系統設定",
    "auth_users": "10 權限管理-帳號",
    "security_users": "10 權限管理-帳號",
    "auth_account_permissions": "10 權限管理-模組權限",
    "security_user_roles": "10 權限管理-角色",
    "security_settings": "10 權限管理-安全設定",
    "system_logs": "06 LOG查詢",
    "login_logs": "11 登入紀錄",
}


def _format_action(action_type: Any) -> str:
    raw = _clean_text(action_type)
    label = _ACTION_LABELS.get(raw.upper(), "")
    return f"{label} / {raw}" if label else raw


def _format_module(target_table: Any) -> str:
    raw = _clean_text(target_table)
    return _TABLE_LABELS.get(raw.lower(), raw)


def _user_display_name_map() -> dict[str, str]:
    """Best-effort username -> display name map for 06 LOG.

    V133：06 LOG 查詢新增「姓名 / Name」欄。
    優先讀 10 權限管理的帳號權威資料；失敗時回退 SQLite auth/security users。
    這只影響顯示，不改 LOG 寫入、刪除、權威檔 tombstone。
    """
    mapping: dict[str, str] = {}
    try:
        from services.permission_service import get_users as _perm_get_users
        for row in _perm_get_users() or []:
            username = _clean_text((row or {}).get("username") or (row or {}).get("帳號 / Username"))
            name = _clean_text((row or {}).get("display_name") or (row or {}).get("姓名 / Display Name"))
            if username and name:
                mapping[username.lower()] = name
    except Exception:
        pass
    for table in ("auth_users", "security_users"):
        try:
            df = query_df(f"SELECT username, display_name FROM {table}")
            if isinstance(df, pd.DataFrame) and not df.empty:
                for _, r in df.iterrows():
                    username = _clean_text(r.get("username"))
                    name = _clean_text(r.get("display_name"))
                    if username and name and username.lower() not in mapping:
                        mapping[username.lower()] = name
        except Exception:
            pass
    return mapping


def _lookup_display_name(username: Any, name_map: dict[str, str] | None = None) -> str:
    user = _clean_text(username)
    if not user:
        return ""
    mapping = name_map or _user_display_name_map()
    return _clean_text(mapping.get(user.lower(), ""))


def format_logs_for_display(df: Any) -> pd.DataFrame:
    """Format raw system_logs into a human-readable operation log.

    06 LOG查詢應顯示：哪個帳號、什麼時間、在哪個模組、做了什麼動作。
    原始 SQL 細節仍保留在「明細」欄，供追查用。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=[
            "ID / ID", "LOG時間 / Log Time", "帳號 / User", "姓名 / Name", "動作 / Action",
            "模組 / Module", "目標ID / Target ID", "操作內容 / Message",
            "結果 / Level", "明細 / Detail",
        ])
    x = df.copy()
    for col in ["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level"]:
        if col not in x.columns:
            x[col] = ""
    _name_map = _user_display_name_map()
    out = pd.DataFrame({
        "ID / ID": x["id"],
        "LOG時間 / Log Time": x["log_time"].map(_clean_text),
        "帳號 / User": x["user_name"].map(_clean_text),
        "姓名 / Name": x["user_name"].map(lambda v: _lookup_display_name(v, _name_map)),
        "動作 / Action": x["action_type"].map(_format_action),
        "模組 / Module": x["target_table"].map(_format_module),
        "目標ID / Target ID": x["target_id"].map(_clean_text),
        "操作內容 / Message": x["message"].map(_clean_text),
        "結果 / Level": x["level"].map(_clean_text),
        "明細 / Detail": x["detail"].map(_clean_text),
    })
    return out

def _date_text(value: Any) -> str | None:
    """Convert date/datetime/string to YYYY-MM-DD text for SQLite date() filtering."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _safe_int(value: Any, default: int = 500) -> int:
    try:
        return int(value)
    except Exception:
        return default


def write_log(
    action_type: str,
    message: str,
    target_table: str = "",
    target_id: str = "",
    detail: str = "",
    level: str = "INFO",
    user_name: str | None = None,
) -> None:
    execute(
        """
        INSERT INTO system_logs
        (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_text(),
            user_name or _current_log_user(),
            action_type,
            target_table,
            str(target_id or ""),
            message,
            detail,
            level,
        ),
    )


def load_logs(
    limit: int = 500,
    start_date: Any | None = None,
    end_date: Any | None = None,
    action_type: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
):
    """Load system logs with optional SQL-side filtering.

    V2.01：保留舊版 load_logs(limit) 相容，並支援 06｜LOG查詢 日期、類型、等級、關鍵字篩選。
    """
    where: list[str] = []
    params: list[Any] = []

    s = _date_text(start_date)
    e = _date_text(end_date)
    if s:
        where.append("date(log_time) >= date(?)")
        params.append(s)
    if e:
        where.append("date(log_time) <= date(?)")
        params.append(e)
    if action_type:
        where.append("COALESCE(action_type,'') = ?")
        params.append(str(action_type))
    if level and str(level).upper() != "ALL":
        where.append("COALESCE(level,'') = ?")
        params.append(str(level))
    if keyword:
        kw = f"%{keyword}%"
        where.append(
            "(" + " OR ".join([
                "COALESCE(user_name,'') LIKE ?",
                "COALESCE(action_type,'') LIKE ?",
                "COALESCE(target_table,'') LIKE ?",
                "COALESCE(target_id,'') LIKE ?",
                "COALESCE(message,'') LIKE ?",
                "COALESCE(detail,'') LIKE ?",
                "COALESCE(level,'') LIKE ?",
            ]) + ")"
        )
        params.extend([kw] * 7)

    sql = "SELECT * FROM system_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, _safe_int(limit, 500)))
    return query_df(sql, tuple(params))


def count_logs_by_date_range(start_date: Any, end_date: Any) -> int:
    """Count logs in date range. Kept as top-level function to avoid ImportError in page 06."""
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    df = query_df(
        """
        SELECT COUNT(*) AS cnt
        FROM system_logs
        WHERE date(log_time) >= date(?) AND date(log_time) <= date(?)
        """,
        (s, e),
    )
    if df is None or df.empty:
        return 0
    return int(df.iloc[0].get("cnt", 0) or 0)


def delete_logs_by_date_range(
    start_date: Any,
    end_date: Any,
    keep_delete_audit: bool = True,
    user_name: str | None = None,
) -> int:
    """Delete system_logs in a date range and keep one audit log after deletion.

    V2.01：此函式必須存在，避免 06｜LOG查詢 import error。
    刪除確認由頁面用 checkbox 控制，不再要求輸入 DELETE。
    """
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    before = count_logs_by_date_range(s, e)
    if before <= 0:
        return 0
    execute(
        "DELETE FROM system_logs WHERE date(log_time) >= date(?) AND date(log_time) <= date(?)",
        (s, e),
    )
    clear_query_cache()
    if keep_delete_audit:
        write_log(
            "DELETE_LOG_RANGE",
            f"刪除 LOG 日期區間：{s} ~ {e}，刪除筆數：{before}",
            target_table="system_logs",
            target_id=f"{s}~{e}",
            detail=f"deleted_count={before}",
            level="WARN",
            user_name=user_name,
        )
    return before

# ===================== V122 06 LOG AUTHORITY WRITE-THROUGH + DELETE TOMBSTONE =====================
# 目的：06｜LOG查詢不可只依賴 SQLite 快取；新增/查詢/刪除都要對齊正式權威檔，
# 且刪除過的舊 LOG 不可因 SQLite / legacy cache 又復活。
from pathlib import Path as _V122Path
import json as _v122_json
import threading as _v122_threading
import hashlib as _v122_hashlib
import time as _v122_time

_V122_PROJECT_ROOT = _V122Path(__file__).resolve().parents[1]
_V122_LOG_MODULE_KEY = "06_logs"
_V122_LOG_AUTH_DIR = _V122_PROJECT_ROOT / "data" / "permanent_store" / "modules" / _V122_LOG_MODULE_KEY
_V122_LOG_DELETE_STATE_PATH = _V122_LOG_AUTH_DIR / "delete_state.json"
_V122_LOG_LOCK = _v122_threading.RLock()
_V122_LOG_UPLOAD_STATE = {"running": False, "pending": False, "last_error": "", "last_upload_ts": 0.0}

try:
    _v122_original_write_log = write_log
except Exception:  # pragma: no cover
    _v122_original_write_log = None


def _v122_log_date(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return text.replace("/", "-")[:10]


def _v122_log_clean_row(row: Any, source: str = "") -> dict[str, Any]:
    r = dict(row) if isinstance(row, dict) else {}
    out = {
        "id": r.get("id", ""),
        "log_time": _clean_text(r.get("log_time") or r.get("created_at") or r.get("time") or r.get("LOG時間 / Log Time")),
        "user_name": _clean_text(r.get("user_name") or r.get("username") or r.get("帳號 / User")),
        "action_type": _clean_text(r.get("action_type") or r.get("action") or r.get("動作 / Action")),
        "target_table": _clean_text(r.get("target_table") or r.get("module") or r.get("模組 / Module")),
        "target_id": _clean_text(r.get("target_id") or r.get("目標ID / Target ID")),
        "message": _clean_text(r.get("message") or r.get("操作內容 / Message")),
        "detail": _clean_text(r.get("detail") or r.get("明細 / Detail")),
        "level": _clean_text(r.get("level") or r.get("result") or r.get("結果 / Level") or "INFO"),
        "source": _clean_text(r.get("source") or source or "system_logs"),
    }
    if not out["log_time"]:
        out["log_time"] = now_text()
    return out


def _v122_log_key(row: dict[str, Any]) -> str:
    parts = [
        _clean_text(row.get("log_time")), _clean_text(row.get("user_name")),
        _clean_text(row.get("action_type")), _clean_text(row.get("target_table")),
        _clean_text(row.get("target_id")), _clean_text(row.get("message")),
        _clean_text(row.get("detail")), _clean_text(row.get("level")),
    ]
    raw = "|".join(parts)
    return _v122_hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _v122_read_log_delete_state() -> dict[str, Any]:
    try:
        if _V122_LOG_DELETE_STATE_PATH.exists() and _V122_LOG_DELETE_STATE_PATH.stat().st_size > 0:
            data = _v122_json.loads(_V122_LOG_DELETE_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("deleted_keys", [])
                data.setdefault("deleted_ranges", [])
                return data
    except Exception:
        pass
    return {"version": "V122", "module_key": _V122_LOG_MODULE_KEY, "deleted_keys": [], "deleted_ranges": [], "updated_at": now_text()}


def _v122_write_log_delete_state(state: dict[str, Any]) -> None:
    try:
        state = dict(state or {})
        state["version"] = "V122"
        state["module_key"] = _V122_LOG_MODULE_KEY
        state["updated_at"] = now_text()
        _V122_LOG_DELETE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _V122_LOG_DELETE_STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(_v122_json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(_V122_LOG_DELETE_STATE_PATH)
    except Exception:
        pass


def _v122_deleted_key_set() -> set[str]:
    state = _v122_read_log_delete_state()
    raw = state.get("deleted_keys") if isinstance(state.get("deleted_keys"), list) else []
    return {str(x) for x in raw if str(x).strip()}


def _v122_read_authority_log_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from services.permanent_authority_service import load_tables
        tables = load_tables(_V122_LOG_MODULE_KEY, "records")
        for r in (tables.get("system_logs") or []):
            if isinstance(r, dict):
                rows.append(_v122_log_clean_row(r, "authority"))
    except Exception:
        try:
            auth_path = _V122_LOG_AUTH_DIR / "records.json"
            if auth_path.exists() and auth_path.stat().st_size > 0:
                data = _v122_json.loads(auth_path.read_text(encoding="utf-8"))
                tables = data.get("tables", {}) if isinstance(data, dict) else {}
                for r in (tables.get("system_logs") or data.get("records") or []):
                    if isinstance(r, dict):
                        rows.append(_v122_log_clean_row(r, "authority"))
        except Exception:
            pass
    return rows


def _v122_sqlite_log_rows(limit: int = 200000) -> list[dict[str, Any]]:
    try:
        df = query_df("SELECT * FROM system_logs ORDER BY id DESC LIMIT ?", (max(1, int(limit)),))
        if df is None or df.empty:
            return []
        return [_v122_log_clean_row(r, "sqlite") for r in df.to_dict("records")]
    except Exception:
        return []


def _v122_dedupe_log_rows(rows: list[dict[str, Any]], apply_tombstone: bool = True) -> list[dict[str, Any]]:
    deleted = _v122_deleted_key_set() if apply_tombstone else set()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        clean = _v122_log_clean_row(r, str(r.get("source") or ""))
        key = _v122_log_key(clean)
        if key in deleted:
            continue
        if key in seen:
            continue
        seen.add(key)
        clean["log_key"] = key
        out.append(clean)
    return out


def _v122_all_log_rows(*, include_sqlite: bool = True, apply_tombstone: bool = True) -> list[dict[str, Any]]:
    rows = _v122_read_authority_log_rows()
    if include_sqlite:
        rows += _v122_sqlite_log_rows()
    rows = _v122_dedupe_log_rows(rows, apply_tombstone=apply_tombstone)
    try:
        rows.sort(key=lambda r: (_clean_text(r.get("log_time")), int(float(r.get("id") or 0))), reverse=True)
    except Exception:
        rows.sort(key=lambda r: _clean_text(r.get("log_time")), reverse=True)
    return rows


def _v122_save_authority_log_rows(rows: list[dict[str, Any]], reason: str = "v122_system_logs", *, github: bool = False) -> dict[str, Any]:
    clean = _v122_dedupe_log_rows(rows, apply_tombstone=True)
    for r in clean:
        r.pop("log_key", None)
    try:
        from services.permanent_authority_service import save_authority
        return save_authority(_V122_LOG_MODULE_KEY, records={"system_logs": clean}, reason=reason, github=github)
    except Exception as exc:
        # Direct local fallback.
        try:
            _V122_LOG_AUTH_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "authority_schema": "SPT-PermanentAuthority-V122",
                "module_key": _V122_LOG_MODULE_KEY,
                "kind": "records",
                "updated_at": now_text(),
                "reason": reason,
                "tables": {"system_logs": clean},
                "table_counts": {"system_logs": len(clean)},
            }
            (_V122_LOG_AUTH_DIR / "records.json").write_text(_v122_json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return {"ok": True, "fallback": True, "error": str(exc)[:300]}
        except Exception as exc2:
            return {"ok": False, "error": f"{exc}; fallback={exc2}"[:500]}


def _v122_schedule_log_authority_upload(reason: str = "v122_async_system_log_upload") -> None:
    try:
        import threading
        import time
    except Exception:
        return
    def _worker() -> None:
        try:
            time.sleep(0.6)
            while True:
                _V122_LOG_UPLOAD_STATE["pending"] = False
                try:
                    from services.permanent_authority_service import force_upload_authority_file
                    force_upload_authority_file(_V122_LOG_MODULE_KEY, "records", reason=reason)
                    _V122_LOG_UPLOAD_STATE["last_upload_ts"] = time.time()
                    _V122_LOG_UPLOAD_STATE["last_error"] = ""
                except Exception as exc:
                    _V122_LOG_UPLOAD_STATE["last_error"] = str(exc)[:500]
                if not _V122_LOG_UPLOAD_STATE.get("pending"):
                    _V122_LOG_UPLOAD_STATE["running"] = False
                    return
                time.sleep(0.3)
        except Exception as exc:
            _V122_LOG_UPLOAD_STATE["last_error"] = str(exc)[:500]
            _V122_LOG_UPLOAD_STATE["running"] = False
    try:
        _V122_LOG_UPLOAD_STATE["pending"] = True
        if _V122_LOG_UPLOAD_STATE.get("running"):
            return
        _V122_LOG_UPLOAD_STATE["running"] = True
        threading.Thread(target=_worker, name="SPT-V122-SystemLogAuthorityUpload", daemon=True).start()
    except Exception:
        _V122_LOG_UPLOAD_STATE["running"] = False


def _v122_sync_latest_sqlite_log_to_authority(reason: str = "v122_write_log") -> None:
    with _V122_LOG_LOCK:
        rows = _v122_read_authority_log_rows()
        rows += _v122_sqlite_log_rows(limit=30)
        _v122_save_authority_log_rows(rows, reason=reason, github=False)
    _v122_schedule_log_authority_upload(reason)


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    if callable(_v122_original_write_log):
        _v122_original_write_log(action_type, message, target_table, target_id, detail, level, user_name)
    else:
        execute(
            """
            INSERT INTO system_logs
            (log_time, user_name, action_type, target_table, target_id, message, detail, level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_text(), user_name or _current_log_user(), action_type, target_table, str(target_id or ""), message, detail, level),
        )
    try:
        _v122_sync_latest_sqlite_log_to_authority("v122_write_log_authority")
    except Exception:
        pass


def _v122_apply_log_filters(rows: list[dict[str, Any]], start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None) -> list[dict[str, Any]]:
    s = _date_text(start_date)
    e = _date_text(end_date)
    action = _clean_text(action_type)
    lvl = _clean_text(level).upper()
    kw = _clean_text(keyword).lower()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _v122_log_date(r.get("log_time"))
        if s and d and d < s:
            continue
        if e and d and d > e:
            continue
        if action and _clean_text(r.get("action_type")) != action:
            continue
        if lvl and lvl != "ALL" and _clean_text(r.get("level")).upper() != lvl:
            continue
        if kw:
            blob = " ".join(_clean_text(r.get(c)) for c in ("user_name", "action_type", "target_table", "target_id", "message", "detail", "level"))
            if kw not in blob.lower():
                continue
        out.append(r)
    return out


def load_logs(limit: int = 500, start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None):  # type: ignore[override]
    rows = _v122_all_log_rows(include_sqlite=True, apply_tombstone=True)
    rows = _v122_apply_log_filters(rows, start_date, end_date, action_type, level, keyword)
    limit = max(1, _safe_int(limit, 500))
    df = pd.DataFrame(rows[:limit])
    for c in ["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]:
        if c not in df.columns:
            df[c] = ""
    return df[["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]]


def count_logs_by_date_range(start_date: Any, end_date: Any) -> int:  # type: ignore[override]
    rows = _v122_all_log_rows(include_sqlite=True, apply_tombstone=True)
    return len(_v122_apply_log_filters(rows, start_date, end_date))


def _v122_replace_sqlite_logs(rows: list[dict[str, Any]]) -> None:
    try:
        execute("DELETE FROM system_logs")
        for r in rows:
            execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _clean_text(r.get("log_time")), _clean_text(r.get("user_name")), _clean_text(r.get("action_type")),
                    _clean_text(r.get("target_table")), _clean_text(r.get("target_id")), _clean_text(r.get("message")),
                    _clean_text(r.get("detail")), _clean_text(r.get("level") or "INFO"),
                ),
            )
        clear_query_cache()
    except Exception:
        pass


def delete_logs_by_date_range(start_date: Any, end_date: Any, keep_delete_audit: bool = True, user_name: str | None = None) -> int:  # type: ignore[override]
    s = _date_text(start_date)
    e = _date_text(end_date)
    if not s or not e:
        return 0
    with _V122_LOG_LOCK:
        rows = _v122_all_log_rows(include_sqlite=True, apply_tombstone=True)
        target: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for r in rows:
            d = _v122_log_date(r.get("log_time"))
            if d and s <= d <= e:
                target.append(r)
            else:
                remaining.append(r)
        deleted_count = len(target)
        if deleted_count <= 0:
            return 0
        state = _v122_read_log_delete_state()
        deleted_keys = set(str(x) for x in (state.get("deleted_keys") or []))
        for r in target:
            deleted_keys.add(_v122_log_key(r))
        state["deleted_keys"] = sorted(deleted_keys)
        ranges = state.get("deleted_ranges") if isinstance(state.get("deleted_ranges"), list) else []
        ranges.append({"start_date": s, "end_date": e, "deleted_count": deleted_count, "deleted_at": now_text(), "deleted_by": user_name or _current_log_user()})
        state["deleted_ranges"] = ranges[-200:]
        state["last_deleted_count"] = deleted_count
        _v122_write_log_delete_state(state)
        _v122_save_authority_log_rows(remaining, reason="v122_delete_system_logs_tombstone", github=True)
        _v122_replace_sqlite_logs(remaining)
    if keep_delete_audit:
        write_log(
            "DELETE_LOG_RANGE",
            f"刪除 LOG 日期區間：{s} ~ {e}，刪除筆數：{deleted_count}",
            target_table="system_logs",
            target_id=f"{s}~{e}",
            detail=f"deleted_count={deleted_count};authority=06_logs.records.json;tombstone=delete_state.json",
            level="WARN",
            user_name=user_name,
        )
    return int(deleted_count)


def get_system_log_authority_status() -> dict[str, Any]:
    rows = _v122_read_authority_log_rows()
    db_rows = _v122_sqlite_log_rows(limit=200000)
    state = _v122_read_log_delete_state()
    return {
        "module_key": _V122_LOG_MODULE_KEY,
        "path": str(_V122_LOG_AUTH_DIR / "records.json"),
        "exists": (_V122_LOG_AUTH_DIR / "records.json").exists(),
        "count": len(_v122_dedupe_log_rows(rows, apply_tombstone=True)),
        "db_count": len(db_rows),
        "delete_state_path": str(_V122_LOG_DELETE_STATE_PATH),
        "delete_state_exists": _V122_LOG_DELETE_STATE_PATH.exists(),
        "deleted_keys": len(state.get("deleted_keys") or []),
        "deleted_ranges": len(state.get("deleted_ranges") or []),
        "upload_running": bool(_V122_LOG_UPLOAD_STATE.get("running")),
        "last_upload_error": _V122_LOG_UPLOAD_STATE.get("last_error", ""),
    }

# =================== END V122 06 LOG AUTHORITY WRITE-THROUGH + DELETE TOMBSTONE ===================

# ===================== V147 HIGH-FREQUENCY LOG BATCHING =====================
# 目的：50 人同時操作時，LOG 仍即時寫入 SQLite，但不再每一筆 LOG 都同步/上傳整份 06_logs 權威檔。
# 讀取 LOG 時仍會合併 SQLite + authority，因此畫面不會少資料；刪除日期區間仍走原 tombstone 權威流程。
import threading as _v147_log_threading
import time as _v147_log_time

_V147_LOG_BATCH_LOCK = _v147_log_threading.RLock()
_V147_LOG_BATCH_STATE = {
    "running": False,
    "pending": False,
    "last_sync_at": 0.0,
    "last_error": "",
    "write_count_since_sync": 0,
}


def _v147_schedule_log_authority_batch(reason: str = "v147_log_batch") -> None:
    def _worker() -> None:
        try:
            delay = float(__import__("os").environ.get("SPT_LOG_AUTH_BATCH_DELAY_SEC", "4.0") or 4.0)
        except Exception:
            delay = 4.0
        try:
            _v147_log_time.sleep(max(delay, 0.5))
            while True:
                with _V147_LOG_BATCH_LOCK:
                    _V147_LOG_BATCH_STATE["pending"] = False
                try:
                    # 背景批次：保留 authority 既有 LOG + SQLite 最新 LOG。limit 足夠覆蓋目前現場量；不在按鈕執行緒內跑。
                    rows = _v122_read_authority_log_rows() if "_v122_read_authority_log_rows" in globals() else []
                    rows += _v122_sqlite_log_rows(limit=3000) if "_v122_sqlite_log_rows" in globals() else []
                    _v122_save_authority_log_rows(rows, reason=reason, github=False)
                    try:
                        from services.permanent_authority_service import force_upload_authority_file
                        force_upload_authority_file("06_logs", "records", reason=reason)
                    except Exception:
                        pass
                    with _V147_LOG_BATCH_LOCK:
                        _V147_LOG_BATCH_STATE["last_sync_at"] = _v147_log_time.time()
                        _V147_LOG_BATCH_STATE["last_error"] = ""
                        _V147_LOG_BATCH_STATE["write_count_since_sync"] = 0
                except Exception as exc:
                    with _V147_LOG_BATCH_LOCK:
                        _V147_LOG_BATCH_STATE["last_error"] = str(exc)[:500]
                with _V147_LOG_BATCH_LOCK:
                    if not _V147_LOG_BATCH_STATE.get("pending"):
                        _V147_LOG_BATCH_STATE["running"] = False
                        return
                _v147_log_time.sleep(1.0)
        except Exception as exc:
            with _V147_LOG_BATCH_LOCK:
                _V147_LOG_BATCH_STATE["last_error"] = str(exc)[:500]
                _V147_LOG_BATCH_STATE["running"] = False

    with _V147_LOG_BATCH_LOCK:
        _V147_LOG_BATCH_STATE["pending"] = True
        _V147_LOG_BATCH_STATE["write_count_since_sync"] = int(_V147_LOG_BATCH_STATE.get("write_count_since_sync") or 0) + 1
        if _V147_LOG_BATCH_STATE.get("running"):
            return
        _V147_LOG_BATCH_STATE["running"] = True
    try:
        _v147_log_threading.Thread(target=_worker, name="SPT-V147-SystemLogBatchSync", daemon=True).start()
    except Exception as exc:
        with _V147_LOG_BATCH_LOCK:
            _V147_LOG_BATCH_STATE["running"] = False
            _V147_LOG_BATCH_STATE["last_error"] = str(exc)[:500]


try:
    _v147_original_sqlite_only_write_log = _v122_original_write_log if callable(_v122_original_write_log) else None  # type: ignore[name-defined]
except Exception:
    _v147_original_sqlite_only_write_log = None


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    """V147：LOG 先即時寫 SQLite，06_logs 權威檔改為背景批次同步。"""
    if callable(_v147_original_sqlite_only_write_log):
        _v147_original_sqlite_only_write_log(action_type, message, target_table, target_id, detail, level, user_name)
    else:
        execute(
            """
            INSERT INTO system_logs
            (log_time, user_name, action_type, target_table, target_id, message, detail, level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_text(), user_name or _current_log_user(), action_type, target_table, str(target_id or ""), message, detail, level),
        )
    # 不阻塞使用者操作；06 LOG 查詢仍會從 SQLite 看到新資料。
    try:
        _v147_schedule_log_authority_batch("v147_batched_write_log_authority")
    except Exception:
        pass


def flush_log_authority_batch_now(reason: str = "manual_v147_log_flush") -> dict[str, Any]:
    """手動/登出前補送 LOG 權威檔；不刪資料。"""
    try:
        rows = _v122_read_authority_log_rows() if "_v122_read_authority_log_rows" in globals() else []
        rows += _v122_sqlite_log_rows(limit=5000) if "_v122_sqlite_log_rows" in globals() else []
        res = _v122_save_authority_log_rows(rows, reason=reason, github=False)
        try:
            from services.permanent_authority_service import flush_authority_upload_queue_now, force_upload_authority_file
            force_upload_authority_file("06_logs", "records", reason=reason)
            q = flush_authority_upload_queue_now(reason=reason, max_seconds=6.0)
        except Exception as exc:
            q = {"ok": False, "error": str(exc)[:300]}
        return {"ok": True, "save": res, "upload": q, "rows": len(rows)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}


def get_log_batch_status() -> dict[str, Any]:
    try:
        with _V147_LOG_BATCH_LOCK:
            return dict(_V147_LOG_BATCH_STATE)
    except Exception:
        return {"running": False, "pending": False, "last_error": "status_unavailable"}
# =================== END V147 HIGH-FREQUENCY LOG BATCHING ===================
