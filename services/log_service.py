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


def format_logs_for_display(df: Any) -> pd.DataFrame:
    """Format raw system_logs into a human-readable operation log.

    06 LOG查詢應顯示：哪個帳號、什麼時間、在哪個模組、做了什麼動作。
    原始 SQL 細節仍保留在「明細」欄，供追查用。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=[
            "ID / ID", "LOG時間 / Log Time", "帳號 / User", "動作 / Action",
            "模組 / Module", "目標ID / Target ID", "操作內容 / Message",
            "結果 / Level", "明細 / Detail",
        ])
    x = df.copy()
    for col in ["id", "log_time", "user_name", "action_type", "target_table", "target_id", "message", "detail", "level"]:
        if col not in x.columns:
            x[col] = ""
    out = pd.DataFrame({
        "ID / ID": x["id"],
        "LOG時間 / Log Time": x["log_time"].map(_clean_text),
        "帳號 / User": x["user_name"].map(_clean_text),
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
