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

# ===================== V156 LOG QUERY CACHE =====================
# 目的：06 LOG 查詢與各模組寫 LOG 後 rerun 時，避免短時間重複掃描 LOG 來源。
# 正確性：cache signature 包含 SQLite DB mtime 與 06_logs 權威檔 mtime；write/delete 後立即清除。
try:
    import copy as _v156_log_copy
    from pathlib import Path as _v156_log_Path
except Exception:
    _v156_log_copy = None
    _v156_log_Path = None

_V156_LOG_CACHE: dict[tuple, tuple[tuple, object]] = {}


def _v156_log_sig() -> tuple:
    out = []
    try:
        from services.db_service import DB_PATH as _DB_PATH
        p = _DB_PATH
        stt = p.stat(); out.append((str(p), int(stt.st_mtime_ns), int(stt.st_size)))
    except Exception:
        out.append(('db', 0, -1))
    try:
        from services.permanent_authority_service import canonical_path as _pa_path
        for module_key in ('06_logs', '06_system_logs'):
            p = _pa_path(module_key, 'records')
            try:
                stt = p.stat(); out.append((str(p), int(stt.st_mtime_ns), int(stt.st_size)))
            except Exception:
                out.append((str(p), 0, -1))
    except Exception:
        pass
    return tuple(out)


def _v156_log_copy_value(v):
    try:
        if hasattr(v, 'copy'):
            return v.copy(deep=True) if v.__class__.__name__ == 'DataFrame' else v.copy()
    except Exception:
        pass
    try:
        return _v156_log_copy.deepcopy(v) if _v156_log_copy is not None else v
    except Exception:
        return v


def clear_log_query_cache() -> None:
    try:
        _V156_LOG_CACHE.clear()
    except Exception:
        pass


_v156_prev_write_log = write_log
_v156_prev_load_logs = load_logs
_v156_prev_delete_logs_by_date_range = delete_logs_by_date_range


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    res = _v156_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
    clear_log_query_cache()
    return res


def load_logs(limit: int = 500, start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None):  # type: ignore[override]
    key = ('load_logs', int(limit or 0), str(start_date or ''), str(end_date or ''), str(action_type or ''), str(level or ''), str(keyword or ''))
    sig = _v156_log_sig()
    got = _V156_LOG_CACHE.get(key)
    if got and got[0] == sig:
        return _v156_log_copy_value(got[1])
    val = _v156_prev_load_logs(limit=limit, start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword)
    try:
        _V156_LOG_CACHE[key] = (sig, _v156_log_copy_value(val))
        if len(_V156_LOG_CACHE) > 48:
            for k in list(_V156_LOG_CACHE.keys())[:16]:
                _V156_LOG_CACHE.pop(k, None)
    except Exception:
        pass
    return _v156_log_copy_value(val)


def delete_logs_by_date_range(start_date: Any, end_date: Any, keep_delete_audit: bool = True, user_name: str | None = None) -> int:  # type: ignore[override]
    n = _v156_prev_delete_logs_by_date_range(start_date, end_date, keep_delete_audit=keep_delete_audit, user_name=user_name)
    clear_log_query_cache()
    return n
# =================== END V156 LOG QUERY CACHE ===================

# ===================== V166C TIME RECORD FULL SNAPSHOT LOGGING =====================
# 目的：讓 06 LOG 不只是人類可讀文字，也保存 time_records 完整 JSON 快照。
# 後續資料遺失時，修復優先序為 row shard / event journal / V166C LOG snapshot / LOG-only text。
# 此 wrapper 只增強 detail 內容，不改原本 LOG 寫入、刪除 tombstone、V147 批次同步與 V156 cache 行為。
try:
    _v166c_prev_write_log = write_log
except Exception:  # pragma: no cover
    _v166c_prev_write_log = None


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    new_detail = detail
    try:
        from services.log_snapshot_service import append_snapshot_to_detail
        new_detail = append_snapshot_to_detail(
            detail=detail,
            action_type=action_type,
            message=message,
            target_table=target_table,
            target_id=str(target_id or ""),
        )
    except Exception:
        new_detail = detail
    if callable(_v166c_prev_write_log):
        return _v166c_prev_write_log(action_type, message, target_table, target_id, new_detail, level, user_name)
    return None

# =================== END V166C TIME RECORD FULL SNAPSHOT LOGGING ===================

# ===================== V200 COMPLETE ROW-LEVEL LOG RELIABILITY =====================
# 目的：
# 1) 06 LOG 查詢必須保留每一次操作、每一筆資料異動紀錄，不可因同秒重複、authority 去重、
#    SQLite/權威檔不同步而漏顯。
# 2) 不改 UI / CSS / theme / 表格渲染。
# 3) 寫 LOG 仍先快速寫 SQLite；同時追加本機 JSONL append-only shard，避免 Reboot 後 SQLite/authority
#    不完整時 06 查詢少資料。
# 4) V189 後端分頁可透過 load_logs_page() 使用完整來源。
try:
    import uuid as _v200_uuid
    import re as _v200_re
except Exception:  # pragma: no cover
    _v200_uuid = None
    _v200_re = None

try:
    _ACTION_LABELS.update({
        "V200_ROW_START_WORK": "逐筆紀錄-開始作業",
        "V200_ROW_FINISH_WORK": "逐筆紀錄-結束作業",
        "V200_ROW_SAVE_TIME_RECORD": "逐筆紀錄-儲存工時",
        "V200_ROW_DELETE_TIME_RECORD": "逐筆紀錄-刪除工時",
        "V200_ROW_RECALC_TIME_RECORD": "逐筆紀錄-重算工時",
        "V200_ROW_IMPORT_TIME_RECORD": "逐筆紀錄-匯入工時",
    })
except Exception:
    pass

try:
    _v200_prev_write_log = write_log
except Exception:  # pragma: no cover
    _v200_prev_write_log = None
try:
    _v200_prev_load_logs = load_logs
except Exception:  # pragma: no cover
    _v200_prev_load_logs = None
try:
    _v200_prev_count_logs_by_date_range = count_logs_by_date_range
except Exception:  # pragma: no cover
    _v200_prev_count_logs_by_date_range = None
try:
    _v200_prev_delete_logs_by_date_range = delete_logs_by_date_range
except Exception:  # pragma: no cover
    _v200_prev_delete_logs_by_date_range = None

_V200_LOG_SHARD_DIR = _V122_LOG_AUTH_DIR / "log_shards" if "_V122_LOG_AUTH_DIR" in globals() else (_V122_PROJECT_ROOT / "data" / "permanent_store" / "modules" / "06_logs" / "log_shards")
_V200_LOG_UID_PREFIX = "__spt_log_uid="


def _v200_now_text_precise() -> str:
    try:
        base = now_text()
        # now_text()通常到秒，補上微秒，避免同秒 LOG 被誤判為同一筆。
        return f"{base}.{datetime.now().strftime('%f')}"
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _v200_new_uid() -> str:
    try:
        return _v200_uuid.uuid4().hex if _v200_uuid is not None else str(datetime.now().timestamp()).replace('.', '')
    except Exception:
        return str(datetime.now().timestamp()).replace('.', '')


def _v200_detail_with_uid(detail: Any, uid: str) -> str:
    text = _clean_text(detail)
    if _V200_LOG_UID_PREFIX in text:
        return text
    return (text + "\n" if text else "") + f"{_V200_LOG_UID_PREFIX}{uid}"


def _v200_extract_uid(row_or_detail: Any) -> str:
    try:
        if isinstance(row_or_detail, dict):
            detail = _clean_text(row_or_detail.get("detail") or row_or_detail.get("明細 / Detail"))
            direct = _clean_text(row_or_detail.get("log_uid") or row_or_detail.get("uid"))
            if direct:
                return direct
        else:
            detail = _clean_text(row_or_detail)
        if _V200_LOG_UID_PREFIX in detail:
            part = detail.split(_V200_LOG_UID_PREFIX, 1)[1]
            return part.split()[0].split("|")[0].strip()
    except Exception:
        pass
    return ""


def _v200_shard_path_for_log_time(log_time: Any) -> _V122Path:
    d = _v122_log_date(log_time) if "_v122_log_date" in globals() else str(log_time or "")[:10]
    if not d:
        d = today_text() if "today_text" in globals() else datetime.now().strftime("%Y-%m-%d")
    return _V200_LOG_SHARD_DIR / f"{d}.jsonl"


def _v200_append_shard(row: dict[str, Any]) -> None:
    try:
        p = _v200_shard_path_for_log_time(row.get("log_time"))
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(_v122_json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _v200_read_shard_rows(start_date: Any | None = None, end_date: Any | None = None, max_days: int = 370) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        s = _date_text(start_date) or "0000-00-00"
        e = _date_text(end_date) or "9999-99-99"
        if not _V200_LOG_SHARD_DIR.exists():
            return []
        files = sorted(_V200_LOG_SHARD_DIR.glob("*.jsonl"), reverse=True)[:max_days]
        for p in files:
            d = p.stem[:10]
            if d < s or d > e:
                continue
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not line.strip():
                        continue
                    obj = _v122_json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(_v122_log_clean_row(obj, "v200_shard") if "_v122_log_clean_row" in globals() else obj)
            except Exception:
                continue
    except Exception:
        pass
    return rows


def _v200_log_key(row: dict[str, Any]) -> str:
    uid = _v200_extract_uid(row)
    if uid:
        return "uid:" + uid
    if "_v122_log_key" in globals():
        try:
            return "v122:" + _v122_log_key(row)
        except Exception:
            pass
    parts = [_clean_text(row.get(c)) for c in ("log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level")]
    return "raw:" + "|".join(parts)


def _v200_dedupe_rows(rows: list[dict[str, Any]], apply_tombstone: bool = True) -> list[dict[str, Any]]:
    deleted = _v122_deleted_key_set() if apply_tombstone and "_v122_deleted_key_set" in globals() else set()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        clean = _v122_log_clean_row(r, str(r.get("source") or "")) if "_v122_log_clean_row" in globals() else dict(r)
        legacy_key = _v122_log_key(clean) if "_v122_log_key" in globals() else ""
        key = _v200_log_key(clean)
        if legacy_key and legacy_key in deleted:
            continue
        if key in deleted:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _v200_all_log_rows(start_date: Any | None = None, end_date: Any | None = None, include_sqlite: bool = True, include_authority: bool = True, include_shards: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if include_authority and "_v122_read_authority_log_rows" in globals():
        try:
            rows += _v122_read_authority_log_rows()
        except Exception:
            pass
    if include_sqlite and "_v122_sqlite_log_rows" in globals():
        try:
            rows += _v122_sqlite_log_rows(limit=300000)
        except Exception:
            pass
    if include_shards:
        rows += _v200_read_shard_rows(start_date, end_date)
    rows = _v200_dedupe_rows(rows, apply_tombstone=True)
    try:
        rows = _v122_apply_log_filters(rows, start_date, end_date) if "_v122_apply_log_filters" in globals() else rows
    except Exception:
        pass
    try:
        rows.sort(key=lambda r: (_clean_text(r.get("log_time")), int(float(r.get("id") or 0))), reverse=True)
    except Exception:
        rows.sort(key=lambda r: _clean_text(r.get("log_time")), reverse=True)
    return rows


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    """V200：每一次 LOG 都加入唯一 UID，並同步追加 JSONL shard，避免漏記/漏顯。"""
    uid = _v200_new_uid()
    log_time = _v200_now_text_precise()
    user = user_name or _current_log_user()
    new_detail = _v200_detail_with_uid(detail, uid)
    # 先走舊鏈路，保留 V166C snapshot、V147 背景批次、V156 cache 等既有功能。
    if callable(_v200_prev_write_log):
        try:
            _v200_prev_write_log(action_type, message, target_table, target_id, new_detail, level, user)
        except Exception:
            try:
                execute(
                    """
                    INSERT INTO system_logs
                    (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (log_time, user, action_type, target_table, str(target_id or ""), message, new_detail, level),
                )
            except Exception:
                pass
    else:
        try:
            execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_time, user, action_type, target_table, str(target_id or ""), message, new_detail, level),
            )
        except Exception:
            pass
    # append-only shard：不覆蓋、不等待 GitHub，給 06 查詢與 Reboot 後追查使用。
    _v200_append_shard({
        "log_time": log_time,
        "user_name": user,
        "action_type": action_type,
        "target_table": target_table,
        "target_id": str(target_id or ""),
        "message": message,
        "detail": new_detail,
        "level": level,
        "source": "v200_shard",
        "log_uid": uid,
    })
    try:
        clear_log_query_cache()  # type: ignore[name-defined]
    except Exception:
        pass


def write_log_many(rows: list[dict[str, Any]], *, default_target_table: str = "", default_level: str = "INFO", user_name: str | None = None) -> int:
    """V200 row-level bulk helper. Each row is inserted as an independent LOG entry."""
    count = 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        write_log(
            _clean_text(r.get("action_type") or r.get("action") or "ROW_LOG"),
            _clean_text(r.get("message") or r.get("操作內容 / Message") or "row log"),
            _clean_text(r.get("target_table") or default_target_table),
            _clean_text(r.get("target_id") or r.get("id") or r.get("record_key")),
            _clean_text(r.get("detail") or r.get("明細 / Detail")),
            _clean_text(r.get("level") or default_level or "INFO"),
            user_name=user_name,
        )
        count += 1
    return count


def load_logs(limit: int = 500, start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None):  # type: ignore[override]
    rows = _v200_all_log_rows(start_date, end_date, include_sqlite=True, include_authority=True, include_shards=True)
    rows = _v122_apply_log_filters(rows, start_date, end_date, action_type, level, keyword) if "_v122_apply_log_filters" in globals() else rows
    limit = max(1, _safe_int(limit, 500))
    df = pd.DataFrame(rows[:limit])
    for c in ["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]:
        if c not in df.columns:
            df[c] = ""
    return df[["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]]


def load_logs_page(start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None, page: int = 1, page_size: int = 500) -> dict[str, Any]:
    t0 = _v122_time.time() if "_v122_time" in globals() else datetime.now().timestamp()
    rows = _v200_all_log_rows(start_date, end_date, include_sqlite=True, include_authority=True, include_shards=True)
    rows = _v122_apply_log_filters(rows, start_date, end_date, action_type, level, keyword) if "_v122_apply_log_filters" in globals() else rows
    size = max(1, min(_safe_int(page_size, 500), 5000))
    p = max(1, _safe_int(page, 1))
    total = len(rows)
    start = (p - 1) * size
    end = start + size
    df = pd.DataFrame(rows[start:end])
    for c in ["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]:
        if c not in df.columns:
            df[c] = ""
    elapsed = (_v122_time.time() if "_v122_time" in globals() else datetime.now().timestamp()) - t0
    return {
        "ok": True,
        "df": df[["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]],
        "rows": df.to_dict("records"),
        "total_rows": total,
        "page": p,
        "page_size": size,
        "total_pages": max(1, (total + size - 1) // size),
        "elapsed_seconds": round(float(elapsed), 4),
        "source": "v200_sqlite_authority_shard",
    }


def count_logs_by_date_range(start_date: Any, end_date: Any) -> int:  # type: ignore[override]
    try:
        return int(load_logs_page(start_date=start_date, end_date=end_date, page=1, page_size=1).get("total_rows", 0) or 0)
    except Exception:
        if callable(_v200_prev_count_logs_by_date_range):
            return int(_v200_prev_count_logs_by_date_range(start_date, end_date) or 0)
        return 0


def get_system_log_authority_status() -> dict[str, Any]:  # type: ignore[override]
    base = {}
    try:
        if "_v122_read_log_delete_state" in globals():
            state = _v122_read_log_delete_state()
        else:
            state = {}
        base = {
            "module_key": "06_logs",
            "path": str(_V122_LOG_AUTH_DIR / "records.json") if "_V122_LOG_AUTH_DIR" in globals() else "",
            "exists": bool((_V122_LOG_AUTH_DIR / "records.json").exists()) if "_V122_LOG_AUTH_DIR" in globals() else False,
            "count": len(_v122_read_authority_log_rows()) if "_v122_read_authority_log_rows" in globals() else 0,
            "db_count": len(_v122_sqlite_log_rows(limit=300000)) if "_v122_sqlite_log_rows" in globals() else 0,
            "shard_count": len(_v200_read_shard_rows()),
            "delete_state_path": str(_V122_LOG_DELETE_STATE_PATH) if "_V122_LOG_DELETE_STATE_PATH" in globals() else "",
            "delete_state_exists": bool(_V122_LOG_DELETE_STATE_PATH.exists()) if "_V122_LOG_DELETE_STATE_PATH" in globals() else False,
            "deleted_keys": len(state.get("deleted_keys") or []),
            "deleted_ranges": len(state.get("deleted_ranges") or []),
            "v200_complete_log": True,
        }
        try:
            base.update(get_log_batch_status())
        except Exception:
            pass
    except Exception as exc:
        base = {"v200_complete_log": True, "error": str(exc)[:300]}
    return base

# =================== END V200 COMPLETE ROW-LEVEL LOG RELIABILITY ===================

# ===================== V210 LOG SCHEMA GUARD + REBOOT-SAFE DISPLAY =====================
# Purpose:
# - Streamlit Cloud Reboot may recreate a fresh SQLite file. If system_logs table
#   has not been initialized yet, 06 LOG查詢 can show no records or write_log can
#   silently fail.
# - V210 guarantees the LOG table exists before write/query/delete/status, while
#   still preserving V200 JSONL shard + authority fallback.
# - No UI/CSS/theme/table-rendering changes.
try:
    import sqlite3 as _v210_sqlite3
    from pathlib import Path as _v210_Path
    try:
        from services.db_service import DB_PATH as _V210_DB_PATH
    except Exception:
        _V210_DB_PATH = _v210_Path(__file__).resolve().parents[1] / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
except Exception:  # pragma: no cover
    _v210_sqlite3 = None  # type: ignore
    _V210_DB_PATH = None  # type: ignore


def _v210_ensure_system_logs_schema() -> bool:
    """Create system_logs table/indexes without triggering heavy DB restore.

    This is intentionally tiny and local. It does not delete, restore, upload,
    or modify business data.
    """
    if _v210_sqlite3 is None or _V210_DB_PATH is None:
        return False
    try:
        db_path = _v210_Path(_V210_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = _v210_sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_time TEXT,
                    user_name TEXT,
                    action_type TEXT,
                    target_table TEXT,
                    target_id TEXT,
                    message TEXT,
                    detail TEXT,
                    level TEXT DEFAULT 'INFO'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_log_time ON system_logs(log_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_action ON system_logs(action_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_user ON system_logs(user_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_target ON system_logs(target_table, target_id)")
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


try:
    _v210_prev_write_log = write_log
except Exception:
    _v210_prev_write_log = None
try:
    _v210_prev_load_logs = load_logs
except Exception:
    _v210_prev_load_logs = None
try:
    _v210_prev_load_logs_page = load_logs_page
except Exception:
    _v210_prev_load_logs_page = None
try:
    _v210_prev_count_logs_by_date_range = count_logs_by_date_range
except Exception:
    _v210_prev_count_logs_by_date_range = None
try:
    _v210_prev_delete_logs_by_date_range = delete_logs_by_date_range
except Exception:
    _v210_prev_delete_logs_by_date_range = None
try:
    _v210_prev_get_system_log_authority_status = get_system_log_authority_status
except Exception:
    _v210_prev_get_system_log_authority_status = None


# Run once at import. If it fails, individual functions still retry.
try:
    _v210_ensure_system_logs_schema()
except Exception:
    pass


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    _v210_ensure_system_logs_schema()
    if callable(_v210_prev_write_log):
        try:
            return _v210_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
        except Exception:
            # Last-resort SQLite insert, then still append shard when available.
            pass
    try:
        execute(
            """
            INSERT INTO system_logs
            (log_time, user_name, action_type, target_table, target_id, message, detail, level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_text(), user_name or _current_log_user(), action_type, target_table, str(target_id or ""), message, detail, level),
        )
    except Exception:
        try:
            db_path = _v210_Path(_V210_DB_PATH)
            conn = _v210_sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
            try:
                conn.execute(
                    """
                    INSERT INTO system_logs
                    (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (now_text(), user_name or _current_log_user(), action_type, target_table, str(target_id or ""), message, detail, level),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
    # If V200 shard helper exists, keep a second durable local append-only copy.
    try:
        if '_v200_append_shard' in globals():
            uid = _v200_new_uid() if '_v200_new_uid' in globals() else ""
            _v200_append_shard({
                "log_time": _v200_now_text_precise() if '_v200_now_text_precise' in globals() else now_text(),
                "user_name": user_name or _current_log_user(),
                "action_type": action_type,
                "target_table": target_table,
                "target_id": str(target_id or ""),
                "message": message,
                "detail": _v200_detail_with_uid(detail, uid) if uid and '_v200_detail_with_uid' in globals() else detail,
                "level": level,
                "source": "v210_schema_guard_shard",
                "log_uid": uid,
            })
    except Exception:
        pass
    try:
        clear_log_query_cache()  # type: ignore[name-defined]
    except Exception:
        pass


def load_logs(limit: int = 500, start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None):  # type: ignore[override]
    _v210_ensure_system_logs_schema()
    if callable(_v210_prev_load_logs):
        try:
            df = _v210_prev_load_logs(limit=limit, start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword)
            if isinstance(df, pd.DataFrame):
                return df
        except Exception:
            pass
    try:
        res = load_logs_page(start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword, page=1, page_size=limit)
        return res.get("df", pd.DataFrame()) if isinstance(res, dict) else pd.DataFrame()
    except Exception:
        return pd.DataFrame(columns=["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"])


def load_logs_page(start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None, page: int = 1, page_size: int = 500) -> dict[str, Any]:  # type: ignore[override]
    _v210_ensure_system_logs_schema()
    if callable(_v210_prev_load_logs_page):
        try:
            res = _v210_prev_load_logs_page(start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword, page=page, page_size=page_size)
            if isinstance(res, dict) and res.get("ok"):
                return res
        except Exception:
            pass
    # Robust fallback: collect from SQLite + V200 shards + authority when helpers are present.
    try:
        if '_v200_all_log_rows' in globals():
            rows = _v200_all_log_rows(start_date, end_date, include_sqlite=True, include_authority=True, include_shards=True)
        elif '_v122_all_log_rows' in globals():
            rows = _v122_all_log_rows(include_sqlite=True, apply_tombstone=True)
        else:
            rows = []
    except Exception:
        rows = []
    try:
        if '_v122_apply_log_filters' in globals():
            rows = _v122_apply_log_filters(rows, start_date, end_date, action_type, level, keyword)
    except Exception:
        pass
    size = max(1, min(_safe_int(page_size, 500), 5000)) if '_safe_int' in globals() else max(1, min(int(page_size or 500), 5000))
    p = max(1, _safe_int(page, 1)) if '_safe_int' in globals() else max(1, int(page or 1))
    start_i = (p - 1) * size
    end_i = start_i + size
    df = pd.DataFrame(rows[start_i:end_i])
    for c in ["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]:
        if c not in df.columns:
            df[c] = ""
    return {
        "ok": True,
        "df": df[["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level", "source"]],
        "rows": df.to_dict("records"),
        "total_rows": len(rows),
        "page": p,
        "page_size": size,
        "total_pages": max(1, (len(rows) + size - 1) // size),
        "elapsed_seconds": 0,
        "source": "v210_schema_guard_sqlite_authority_shard",
        "v210_schema_guard": True,
    }


def count_logs_by_date_range(start_date: Any, end_date: Any) -> int:  # type: ignore[override]
    _v210_ensure_system_logs_schema()
    try:
        return int(load_logs_page(start_date=start_date, end_date=end_date, page=1, page_size=1).get("total_rows", 0) or 0)
    except Exception:
        if callable(_v210_prev_count_logs_by_date_range):
            try:
                return int(_v210_prev_count_logs_by_date_range(start_date, end_date) or 0)
            except Exception:
                pass
        return 0


def delete_logs_by_date_range(start_date: Any, end_date: Any, keep_delete_audit: bool = True, user_name: str | None = None) -> int:  # type: ignore[override]
    _v210_ensure_system_logs_schema()
    if callable(_v210_prev_delete_logs_by_date_range):
        try:
            return int(_v210_prev_delete_logs_by_date_range(start_date, end_date, keep_delete_audit=keep_delete_audit, user_name=user_name) or 0)
        except TypeError:
            try:
                return int(_v210_prev_delete_logs_by_date_range(start_date, end_date) or 0)
            except Exception:
                pass
        except Exception:
            pass
    return 0


def get_system_log_authority_status() -> dict[str, Any]:  # type: ignore[override]
    _v210_ensure_system_logs_schema()
    base: dict[str, Any] = {}
    if callable(_v210_prev_get_system_log_authority_status):
        try:
            base = dict(_v210_prev_get_system_log_authority_status() or {})
        except Exception as exc:
            base = {"error": str(exc)[:300]}
    try:
        db_count = len(_v122_sqlite_log_rows(limit=300000)) if '_v122_sqlite_log_rows' in globals() else 0
    except Exception:
        db_count = 0
    try:
        shard_count = len(_v200_read_shard_rows()) if '_v200_read_shard_rows' in globals() else 0
    except Exception:
        shard_count = 0
    base.update({
        "v210_schema_guard": True,
        "system_logs_schema_ready": True,
        "db_count": db_count,
        "shard_count": shard_count,
    })
    return base

# =================== END V210 LOG SCHEMA GUARD + REBOOT-SAFE DISPLAY ===================


# =================== V211 POSTGRESQL FAST LOG PATH ===================
# On Streamlit Cloud, PostgreSQL is the durable log store. Keep every operation
# log visible in 06, but avoid the legacy local SQLite/schema/shard chain on the
# foreground button path.
try:
    _v211_prev_write_log = write_log
except Exception:  # pragma: no cover
    _v211_prev_write_log = None


def _v211_pg_enabled() -> bool:
    try:
        from services.db_service import is_postgres_enabled
        return bool(is_postgres_enabled())
    except Exception:
        return False


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    if _v211_pg_enabled():
        try:
            from services.db_service import execute
            execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now_text(), user_name or _current_log_user(), action_type, target_table, str(target_id or ""), message, detail, level),
            )
        except Exception:
            pass
        return None
    if callable(_v211_prev_write_log):
        return _v211_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
    return None


def audit_v211_postgresql_fast_log_path() -> dict[str, Any]:
    return {
        "version": "V211_POSTGRESQL_FAST_LOG_PATH",
        "postgres_enabled": _v211_pg_enabled(),
        "foreground_log_path": "postgresql_direct" if _v211_pg_enabled() else "legacy",
        "keeps_06_log_query_visible": True,
    }


# ================= END V211 POSTGRESQL FAST LOG PATH =================


# =================== V212 ASYNC POSTGRESQL LOG WRITES ===================
# Keep foreground button actions focused on the business write. In PostgreSQL
# mode, operation logs are still written to 06/system_logs, but by a background
# worker so Start/Finish/Save/Delete buttons do not wait on audit I/O.
try:
    import queue as _v212_queue
    import threading as _v212_threading
    import time as _v212_time
except Exception:  # pragma: no cover
    _v212_queue = None  # type: ignore
    _v212_threading = None  # type: ignore
    _v212_time = None  # type: ignore

try:
    _v212_prev_write_log = write_log
except Exception:  # pragma: no cover
    _v212_prev_write_log = None

_V212_LOG_QUEUE = _v212_queue.Queue(maxsize=20000) if _v212_queue is not None else None
_V212_LOG_WORKER_STARTED = False
_V212_LOG_LOCK = _v212_threading.Lock() if _v212_threading is not None else None
_V212_LOG_STATS = {"queued": 0, "written": 0, "failed": 0, "sync_fallback": 0}


def _v212_log_sql() -> str:
    return """
        INSERT INTO system_logs
        (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """


def _v212_write_log_row(row: tuple[Any, ...]) -> None:
    from services.db_service import execute as _db_execute
    _db_execute(_v212_log_sql(), row)


def _v212_worker() -> None:
    if _V212_LOG_QUEUE is None:
        return
    while True:
        row = _V212_LOG_QUEUE.get()
        try:
            _v212_write_log_row(row)
            _V212_LOG_STATS["written"] = int(_V212_LOG_STATS.get("written", 0)) + 1
        except Exception:
            _V212_LOG_STATS["failed"] = int(_V212_LOG_STATS.get("failed", 0)) + 1
            try:
                if _v212_time is not None:
                    _v212_time.sleep(0.2)
                _v212_write_log_row(row)
                _V212_LOG_STATS["written"] = int(_V212_LOG_STATS.get("written", 0)) + 1
            except Exception:
                pass
        finally:
            try:
                _V212_LOG_QUEUE.task_done()
            except Exception:
                pass


def _v212_start_worker_once() -> None:
    global _V212_LOG_WORKER_STARTED
    if _V212_LOG_WORKER_STARTED or _v212_threading is None or _V212_LOG_QUEUE is None:
        return
    lock = _V212_LOG_LOCK
    if lock is None:
        return
    with lock:
        if _V212_LOG_WORKER_STARTED:
            return
        _v212_threading.Thread(target=_v212_worker, name="SPT-Async-PostgreSQL-Log", daemon=True).start()
        _V212_LOG_WORKER_STARTED = True


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    if _v211_pg_enabled() and _V212_LOG_QUEUE is not None:
        row = (now_text(), user_name or _current_log_user(), action_type, target_table, str(target_id or ""), message, detail, level)
        _v212_start_worker_once()
        try:
            _V212_LOG_QUEUE.put_nowait(row)
            _V212_LOG_STATS["queued"] = int(_V212_LOG_STATS.get("queued", 0)) + 1
            return None
        except Exception:
            _V212_LOG_STATS["sync_fallback"] = int(_V212_LOG_STATS.get("sync_fallback", 0)) + 1
            try:
                _v212_write_log_row(row)
            except Exception:
                _V212_LOG_STATS["failed"] = int(_V212_LOG_STATS.get("failed", 0)) + 1
            return None
    if callable(_v212_prev_write_log):
        return _v212_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
    return None


def audit_v212_async_postgresql_log_writes() -> dict[str, Any]:
    return {
        "version": "V212_ASYNC_POSTGRESQL_LOG_WRITES",
        "postgres_enabled": _v211_pg_enabled(),
        "worker_started": bool(_V212_LOG_WORKER_STARTED),
        "queue_size": int(_V212_LOG_QUEUE.qsize()) if _V212_LOG_QUEUE is not None else 0,
        **dict(_V212_LOG_STATS),
    }


# ================= END V212 ASYNC POSTGRESQL LOG WRITES =================

# =================== V300.17 06 LOG SINGLE AUTHORITY JSONL PATCH ===================
# Scope: 06 LOG only. Does not touch 01/02, UI, permissions, or system settings.
# Purpose: keep operation logs in an append-only module authority file so Reboot
# does not depend on old persistent_modules/persistent_state sources.
try:
    _v30017_prev_write_log = write_log  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30017_prev_write_log = None
try:
    _v30017_prev_load_logs = load_logs  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30017_prev_load_logs = None
try:
    _v30017_prev_load_logs_page = load_logs_page  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30017_prev_load_logs_page = None
try:
    _v30017_prev_delete_logs_by_date_range = delete_logs_by_date_range  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30017_prev_delete_logs_by_date_range = None


def _v30017_log_row(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> dict[str, Any]:
    return {
        "log_time": now_text(),
        "user_name": user_name or _current_log_user(),
        "action_type": str(action_type or ""),
        "target_table": str(target_table or ""),
        "target_id": str(target_id or ""),
        "message": str(message or ""),
        "detail": str(detail or ""),
        "level": str(level or "INFO"),
        "source": "06_log_query_jsonl_v30017",
    }


def _v30017_append_log_authority(row: dict[str, Any], *, github: bool = False, reason: str = "06_log_append") -> None:
    try:
        from services.authority_consistency_service import append_jsonl
        append_jsonl("06_log_query", row, identity_fields=("log_time", "user_name", "action_type", "target_table", "target_id", "message"), github=github, reason=reason)
    except Exception:
        pass


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    row = _v30017_log_row(action_type, message, target_table, target_id, detail, level, user_name)
    # Keep the existing hot path exactly as before; append-only authority is a parallel durability layer.
    if callable(_v30017_prev_write_log):
        try:
            _v30017_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
        except Exception:
            pass
    _v30017_append_log_authority(row, github=False, reason="write_log_v30017")
    return None


def _v30017_authority_log_rows(limit: int = 5000) -> list[dict[str, Any]]:
    try:
        from services.authority_consistency_service import read_jsonl, merge_by_event_id
        rows = read_jsonl("06_log_query", limit=limit)
        return merge_by_event_id(rows, id_fields=("log_time", "user_name", "action_type", "target_table", "target_id", "message"))
    except Exception:
        return []


def _v30017_filter_log_rows(rows: list[dict[str, Any]], start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None) -> list[dict[str, Any]]:
    s = _date_text(start_date)
    e = _date_text(end_date)
    kw = str(keyword or "").strip().lower()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        d = _date_text(r.get("log_time"))
        if s and (not d or d < s):
            continue
        if e and (not d or d > e):
            continue
        if action_type and str(r.get("action_type") or "") != str(action_type):
            continue
        if level and str(level).upper() != "ALL" and str(r.get("level") or "") != str(level):
            continue
        if kw:
            blob = " ".join(str(r.get(k, "") or "") for k in ("user_name", "action_type", "target_table", "target_id", "message", "detail", "level")).lower()
            if kw not in blob:
                continue
        out.append(r)
    out.sort(key=lambda x: str(x.get("log_time") or ""), reverse=True)
    return out


def load_logs(limit: int = 500, start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None):  # type: ignore[override]
    base_rows: list[dict[str, Any]] = []
    if callable(_v30017_prev_load_logs):
        try:
            obj = _v30017_prev_load_logs(limit=limit, start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword)
            if isinstance(obj, pd.DataFrame):
                base_rows = obj.where(pd.notna(obj), "").to_dict(orient="records")
            elif isinstance(obj, list):
                base_rows = [dict(x) for x in obj if isinstance(x, dict)]
        except Exception:
            base_rows = []
    auth_rows = _v30017_filter_log_rows(_v30017_authority_log_rows(max(int(limit or 500) * 5, 5000)), start_date, end_date, action_type, level, keyword)
    try:
        from services.authority_consistency_service import merge_by_event_id
        merged = merge_by_event_id(base_rows + auth_rows, id_fields=("log_time", "user_name", "action_type", "target_table", "target_id", "message"))
    except Exception:
        merged = base_rows + auth_rows
    merged.sort(key=lambda x: str(x.get("log_time") or ""), reverse=True)
    if limit:
        merged = merged[: int(limit)]
    return pd.DataFrame(merged)


def load_logs_page(start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None, page: int = 1, page_size: int = 500) -> dict[str, Any]:  # type: ignore[override]
    df = load_logs(limit=max(int(page or 1) * int(page_size or 500), int(page_size or 500)), start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword)
    rows = df.where(pd.notna(df), "").to_dict(orient="records") if isinstance(df, pd.DataFrame) else []
    p = max(1, int(page or 1))
    size = max(1, int(page_size or 500))
    start = (p - 1) * size
    page_rows = rows[start:start + size]
    return {
        "rows": page_rows,
        "data": page_rows,
        "total_rows": len(rows),
        "page": p,
        "page_size": size,
        "total_pages": max(1, (len(rows) + size - 1) // size),
        "source": "v30017_06_log_query_jsonl_plus_existing",
    }


def delete_logs_by_date_range(start_date: Any, end_date: Any, keep_delete_audit: bool = True, user_name: str | None = None) -> int:  # type: ignore[override]
    deleted = 0
    if callable(_v30017_prev_delete_logs_by_date_range):
        try:
            deleted = int(_v30017_prev_delete_logs_by_date_range(start_date, end_date, keep_delete_audit=keep_delete_audit, user_name=user_name) or 0)
        except TypeError:
            try:
                deleted = int(_v30017_prev_delete_logs_by_date_range(start_date, end_date) or 0)
            except Exception:
                deleted = 0
        except Exception:
            deleted = 0
    try:
        from services.authority_consistency_service import append_jsonl
        append_jsonl("06_log_query", {
            "log_time": now_text(),
            "user_name": user_name or _current_log_user(),
            "action_type": "DELETE_LOG_RANGE",
            "target_table": "system_logs",
            "target_id": f"{_date_text(start_date)}~{_date_text(end_date)}",
            "message": f"刪除 LOG 日期區間：{_date_text(start_date)} ~ {_date_text(end_date)}，刪除筆數：{deleted}",
            "detail": f"deleted_count={deleted}",
            "level": "WARN",
            "source": "06_log_query_delete_tombstone_v30017",
            "delete_range_start": _date_text(start_date),
            "delete_range_end": _date_text(end_date),
        }, identity_fields=("log_time", "action_type", "target_id", "message"), github=True, reason="delete_logs_range_v30017")
    except Exception:
        pass
    return deleted


def audit_v30017_06_log_authority() -> dict[str, Any]:
    try:
        from services.authority_consistency_service import audit_authority_consistency
        return audit_authority_consistency().get("modules", {}).get("06_log_query", {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

# ================= END V300.17 06 LOG SINGLE AUTHORITY JSONL PATCH =================

# =================== V300.23 06 LOG DIRECT GITHUB AUTHORITY WRITE ===================
# Scope: 06. LOG查詢 only. Does not modify 01/02, 10, 11, 13, UI, CSS, or theme.
# Goal: every new LOG row is appended to the single authority JSONL and uploaded to GitHub,
#       so Reboot App does not read old/empty runtime files.
try:
    _v30023_prev_write_log = write_log  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_write_log = None
try:
    _v30023_prev_load_logs = load_logs  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_load_logs = None
try:
    _v30023_prev_load_logs_page = load_logs_page  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_load_logs_page = None
try:
    _v30023_prev_delete_logs_by_date_range = delete_logs_by_date_range  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_delete_logs_by_date_range = None


def _v30023_log_row(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> dict[str, Any]:
    return {
        "log_time": now_text(),
        "user_name": user_name or _current_log_user(),
        "action_type": str(action_type or ""),
        "target_table": str(target_table or ""),
        "target_id": str(target_id or ""),
        "message": str(message or ""),
        "detail": str(detail or ""),
        "level": str(level or "INFO"),
        "source": "06_log_query_jsonl_v30023_direct_github",
    }


def _v30023_append_log_authority(row: dict[str, Any], *, github: bool = True, reason: str = "06_log_append_v30023") -> dict[str, Any]:
    try:
        from services.authority_consistency_service import append_jsonl
        return append_jsonl(
            "06_log_query",
            row,
            identity_fields=("log_time", "user_name", "action_type", "target_table", "target_id", "message"),
            github=github,
            reason=reason,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    row = _v30023_log_row(action_type, message, target_table, target_id, detail, level, user_name)
    # Keep existing DB/cache behavior first. Authority JSONL is the durable layer.
    if callable(_v30023_prev_write_log):
        try:
            _v30023_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
        except Exception:
            pass
    _v30023_append_log_authority(row, github=True, reason="write_log_v30023_direct_github")
    return None


def _v30023_authority_log_rows(limit: int = 100000) -> list[dict[str, Any]]:
    try:
        from services.authority_consistency_service import read_jsonl, merge_by_event_id
        rows = read_jsonl("06_log_query", limit=limit)
        return merge_by_event_id(rows, id_fields=("log_time", "user_name", "action_type", "target_table", "target_id", "message"))
    except Exception:
        return []


def _v30023_log_delete_ranges(rows: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    ranges: list[tuple[str, str, str]] = []
    for r in rows or []:
        action = str(r.get("action_type") or "").upper()
        if action == "DELETE_LOG_RANGE" or r.get("delete_range_start") or r.get("delete_range_end"):
            s = _date_text(r.get("delete_range_start") or r.get("start_date") or "")
            e = _date_text(r.get("delete_range_end") or r.get("end_date") or "")
            marker_time = str(r.get("log_time") or r.get("created_at") or "")
            if s and e:
                ranges.append((s, e, marker_time))
    return ranges


def _v30023_should_hide_log_row_by_delete_range(row: dict[str, Any], ranges: list[tuple[str, str, str]]) -> bool:
    d = _date_text(row.get("log_time") or row.get("created_at") or "")
    row_time = str(row.get("log_time") or row.get("created_at") or "")
    if not d:
        return False
    for s, e, marker_time in ranges:
        if not (s <= d <= e):
            continue
        # If the deletion range includes today, do not hide logs created after the delete action.
        # Otherwise a clear operation would permanently hide all later same-day logs.
        marker_date = _date_text(marker_time)
        if marker_date and d == marker_date and row_time and marker_time and row_time > marker_time:
            continue
        return True
    return False


def _v30023_apply_log_delete_ranges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges = _v30023_log_delete_ranges(rows)
    if not ranges:
        return rows
    out: list[dict[str, Any]] = []
    for r in rows or []:
        action = str(r.get("action_type") or "").upper()
        if action == "DELETE_LOG_RANGE":
            out.append(r)
            continue
        if _v30023_should_hide_log_row_by_delete_range(r, ranges):
            continue
        out.append(r)
    return out


def _v30023_filter_log_rows(rows: list[dict[str, Any]], start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None) -> list[dict[str, Any]]:
    s = _date_text(start_date)
    e = _date_text(end_date)
    kw = str(keyword or "").strip().lower()
    rows = _v30023_apply_log_delete_ranges(rows)
    out: list[dict[str, Any]] = []
    for r in rows or []:
        d = _date_text(r.get("log_time") or r.get("created_at") or "")
        if s and (not d or d < s):
            continue
        if e and (not d or d > e):
            continue
        if action_type and str(r.get("action_type") or "") != str(action_type):
            continue
        if level and str(level).upper() != "ALL" and str(r.get("level") or "") != str(level):
            continue
        if kw:
            blob = " ".join(str(r.get(k, "") or "") for k in ("user_name", "action_type", "target_table", "target_id", "message", "detail", "level")).lower()
            if kw not in blob:
                continue
        out.append(r)
    out.sort(key=lambda x: str(x.get("log_time") or x.get("created_at") or ""), reverse=True)
    return out


def load_logs(limit: int = 500, start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None):  # type: ignore[override]
    base_rows: list[dict[str, Any]] = []
    if callable(_v30023_prev_load_logs):
        try:
            obj = _v30023_prev_load_logs(limit=limit, start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword)
            if isinstance(obj, pd.DataFrame):
                base_rows = obj.where(pd.notna(obj), "").to_dict(orient="records")
            elif isinstance(obj, list):
                base_rows = [dict(x) for x in obj if isinstance(x, dict)]
        except Exception:
            base_rows = []
    auth_rows = _v30023_authority_log_rows(max(int(limit or 500) * 5, 5000))
    try:
        from services.authority_consistency_service import merge_by_event_id
        merged = merge_by_event_id(base_rows + auth_rows, id_fields=("log_time", "user_name", "action_type", "target_table", "target_id", "message"))
    except Exception:
        merged = base_rows + auth_rows
    filtered = _v30023_filter_log_rows(merged, start_date, end_date, action_type, level, keyword)
    if limit:
        filtered = filtered[: int(limit)]
    return pd.DataFrame(filtered)


def load_logs_page(start_date: Any | None = None, end_date: Any | None = None, action_type: str | None = None, level: str | None = None, keyword: str | None = None, page: int = 1, page_size: int = 500) -> dict[str, Any]:  # type: ignore[override]
    # Read enough rows to page deterministically. 06 LOG is not expected to load all rows in UI.
    p = max(1, int(page or 1))
    size = max(1, int(page_size or 500))
    df = load_logs(limit=max(p * size, size), start_date=start_date, end_date=end_date, action_type=action_type, level=level, keyword=keyword)
    rows = df.where(pd.notna(df), "").to_dict(orient="records") if isinstance(df, pd.DataFrame) else []
    start = (p - 1) * size
    page_rows = rows[start:start + size]
    return {
        "ok": True,
        "rows": page_rows,
        "data": page_rows,
        "df": pd.DataFrame(page_rows),
        "total_rows": len(rows),
        "page": p,
        "page_size": size,
        "total_pages": max(1, (len(rows) + size - 1) // size),
        "elapsed_seconds": 0,
        "source": "v30023_06_log_query_direct_github_jsonl_plus_existing",
    }


def delete_logs_by_date_range(start_date: Any, end_date: Any, keep_delete_audit: bool = True, user_name: str | None = None) -> int:  # type: ignore[override]
    deleted = 0
    if callable(_v30023_prev_delete_logs_by_date_range):
        try:
            deleted = int(_v30023_prev_delete_logs_by_date_range(start_date, end_date, keep_delete_audit=keep_delete_audit, user_name=user_name) or 0)
        except TypeError:
            try:
                deleted = int(_v30023_prev_delete_logs_by_date_range(start_date, end_date) or 0)
            except Exception:
                deleted = 0
        except Exception:
            deleted = 0
    marker = {
        "log_time": now_text(),
        "user_name": user_name or _current_log_user(),
        "action_type": "DELETE_LOG_RANGE",
        "target_table": "system_logs",
        "target_id": f"{_date_text(start_date)}~{_date_text(end_date)}",
        "message": f"刪除 LOG 日期區間：{_date_text(start_date)} ~ {_date_text(end_date)}，刪除筆數：{deleted}",
        "detail": f"deleted_count={deleted}",
        "level": "WARN",
        "source": "06_log_query_delete_tombstone_v30023_direct_github",
        "delete_range_start": _date_text(start_date),
        "delete_range_end": _date_text(end_date),
    }
    _v30023_append_log_authority(marker, github=True, reason="delete_logs_range_v30023_direct_github")
    return deleted


def get_system_log_authority_status() -> dict[str, Any]:  # type: ignore[override]
    try:
        from services.authority_consistency_service import records_jsonl_path, read_jsonl
        p = records_jsonl_path("06_log_query")
        rows = read_jsonl("06_log_query", limit=None)
        return {
            "exists": p.exists(),
            "path": str(p),
            "count": len(rows),
            "db_count": "",
            "deleted_keys": len(_v30023_log_delete_ranges(rows)),
            "authority_type": "jsonl_direct_github_v30023",
        }
    except Exception as exc:
        return {"exists": False, "count": 0, "error": str(exc)[:300]}


def audit_v30023_06_log_authority() -> dict[str, Any]:
    try:
        from services.authority_consistency_service import audit_v30023_jsonl_direct_authority
        return audit_v30023_jsonl_direct_authority().get("modules", {}).get("06_log_query", {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

# ================= END V300.23 06 LOG DIRECT GITHUB AUTHORITY WRITE =================

# =================== V300.23 06 LOG DIRECT AUTHORITY GITHUB SYNC ===================
# Scope: 06. LOG查詢 only. This does not modify 01/02 or permission data.
try:
    _v30023_prev_write_log = write_log  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_write_log = None

_V30023_LOG_SYNC_STATE = {"last_sync_ts": 0.0, "last_error": "", "last_result": {}}


def _v30023_truthy(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _v30023_read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st  # type: ignore
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value)
    except Exception:
        pass
    try:
        import os as _v30023_os
        return str(_v30023_os.environ.get(name, default) or "")
    except Exception:
        return default


def _v30023_should_sync_06(action_type: str = "") -> bool:
    if _v30023_truthy(_v30023_read_secret("SPT_06_LOG_IMMEDIATE_GITHUB_SYNC"), False):
        return True
    a = str(action_type or "").upper()
    critical_tokens = ("DELETE", "SAVE", "IMPORT", "EXPORT", "PERMISSION", "LOGIN", "SECURITY", "BACKUP", "RESTORE")
    if any(t in a for t in critical_tokens):
        return True
    try:
        import time as _v30023_time
        now = _v30023_time.time()
        min_interval = float(_v30023_read_secret("SPT_06_LOG_GITHUB_SYNC_INTERVAL_SECONDS", "60") or 60)
        return (now - float(_V30023_LOG_SYNC_STATE.get("last_sync_ts", 0.0) or 0.0)) >= max(5.0, min_interval)
    except Exception:
        return False


def _v30023_sync_06_log_authority(reason: str = "write_log_v30023") -> dict[str, Any]:
    try:
        from services.authority_consistency_service import upload_authority_file
        res = upload_authority_file("06_log_query", "records.jsonl", reason=reason)
        _V30023_LOG_SYNC_STATE["last_result"] = dict(res or {})
        if not res.get("ok"):
            _V30023_LOG_SYNC_STATE["last_error"] = str(res.get("error") or res.get("message") or "")[:300]
        else:
            _V30023_LOG_SYNC_STATE["last_error"] = ""
        try:
            import time as _v30023_time
            _V30023_LOG_SYNC_STATE["last_sync_ts"] = _v30023_time.time()
        except Exception:
            pass
        return dict(res or {})
    except Exception as exc:
        _V30023_LOG_SYNC_STATE["last_error"] = str(exc)[:300]
        return {"ok": False, "error": str(exc)[:300]}


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    if callable(_v30023_prev_write_log):
        try:
            _v30023_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name)
        except Exception:
            pass
    if _v30023_should_sync_06(action_type):
        _v30023_sync_06_log_authority(f"06_log_write_{str(action_type or '')[:40]}")
    return None


def audit_v30023_06_log_direct_github_sync() -> dict[str, Any]:
    try:
        from services.authority_consistency_service import records_jsonl_path
        p = records_jsonl_path("06_log_query")
        return {"version": "V300.23_06_LOG_DIRECT_GITHUB_SYNC", "authority_file": str(p), "exists": p.exists(), "size": p.stat().st_size if p.exists() else 0, **dict(_V30023_LOG_SYNC_STATE)}
    except Exception as exc:
        return {"version": "V300.23_06_LOG_DIRECT_GITHUB_SYNC", "ok": False, "error": str(exc)[:300]}

# ================= END V300.23 06 LOG DIRECT AUTHORITY GITHUB SYNC =================
