# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import timedelta
import io
import math

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import check_permission, require_module_access
from services import log_service
from services.table_ui_service import render_table
from services.timezone_service import today_date
try:
    from services.large_table_backend_pagination_service import query_logs_backend_page
except Exception:
    query_logs_backend_page = None

st.set_page_config(page_title="06. LOG 查詢", page_icon="⧉", layout="wide")
apply_theme()
require_module_access("06_logs")
render_header("06｜LOG 查詢", "記錄哪個帳號、什麼時間、在哪個模組做了什麼動作｜V189 後端分頁查詢")

try:
    _log_auth_status = log_service.get_system_log_authority_status() if hasattr(log_service, "get_system_log_authority_status") else {}
except Exception:
    _log_auth_status = {}
if _log_auth_status:
    st.caption(
        f"LOG 權威檔：{'Exists' if _log_auth_status.get('exists') else 'Not Found'}｜"
        f"權威筆數：{_log_auth_status.get('count', 0)}｜SQLite快取：{_log_auth_status.get('db_count', 0)}｜"
        f"DeletedKeys：{_log_auth_status.get('deleted_keys', 0)}｜Path：{_log_auth_status.get('path', '-')}"
    )


def _make_logs_excel_bytes(raw_df, display_df, filters: dict) -> bytes:
    raw = raw_df.copy() if isinstance(raw_df, pd.DataFrame) else pd.DataFrame()
    disp = display_df.copy() if isinstance(display_df, pd.DataFrame) else pd.DataFrame()
    output = io.BytesIO()
    meta = pd.DataFrame([
        ["匯出時間 / Export Time", str(log_service.now_text() if hasattr(log_service, "now_text") else "")],
        ["開始日期 / Start Date", str(filters.get("start_date", ""))],
        ["結束日期 / End Date", str(filters.get("end_date", ""))],
        ["動作類型 / Action Type", str(filters.get("action_type", ""))],
        ["等級 / Level", str(filters.get("level", ""))],
        ["關鍵字 / Keyword", str(filters.get("keyword", ""))],
        ["目前頁 / Page", str(filters.get("page", 1))],
        ["每頁筆數 / Page Size", str(filters.get("page_size", filters.get("limit", 1000)))],
        ["匯出筆數 / Rows", len(disp)],
    ], columns=["項目 / Item", "內容 / Value"])
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        disp.to_excel(writer, sheet_name="LOG查詢_目前頁", index=False)
        meta.to_excel(writer, sheet_name="匯出資訊", index=False)
        raw.to_excel(writer, sheet_name="原始資料_目前頁", index=False)
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        body_fmt = workbook.add_format({"text_wrap": True, "valign": "top"})
        for sheet_name, data in (("LOG查詢_目前頁", disp), ("原始資料_目前頁", raw), ("匯出資訊", meta)):
            ws = writer.sheets[sheet_name]
            try:
                ws.freeze_panes(1, 0)
                ws.autofilter(0, 0, max(len(data), 1), max(len(data.columns) - 1, 0))
            except Exception:
                pass
            for col_idx, col in enumerate(list(data.columns)):
                try:
                    ws.write(0, col_idx, str(col), header_fmt)
                    max_len = max([len(str(col))] + [len(str(x)) for x in data[col].head(300).tolist()]) if not data.empty else len(str(col))
                    ws.set_column(col_idx, col_idx, min(max(max_len + 2, 12), 48), body_fmt)
                except Exception:
                    pass
    output.seek(0)
    return output.getvalue()


def _safe_log_export_filename(filters: dict) -> str:
    s = str(filters.get("start_date", "")).replace("/", "-")[:10] or "start"
    e = str(filters.get("end_date", "")).replace("/", "-")[:10] or "end"
    p = str(filters.get("page", 1))
    return f"SPT_LOG查詢_{s}_{e}_page{p}.xlsx"


def _default_filters() -> dict:
    today = today_date()
    return {
        "start_date": today - timedelta(days=7),
        "end_date": today,
        "page_size": 500,
        "page": 1,
        "action_type": "",
        "level": "ALL",
        "keyword": "",
    }


def _load_logs_safely(filters: dict):
    """V189: backend LIMIT/OFFSET first; fallback to old load_logs."""
    if callable(query_logs_backend_page):
        res = query_logs_backend_page(
            start_date=filters.get("start_date"),
            end_date=filters.get("end_date"),
            action_type=str(filters.get("action_type", "")).strip() or None,
            level=str(filters.get("level", "ALL")),
            keyword=str(filters.get("keyword", "")).strip() or None,
            page=int(filters.get("page", 1) or 1),
            page_size=int(filters.get("page_size", 500) or 500),
        )
        if isinstance(res, dict) and res.get("ok"):
            return res
    try:
        limit = int(filters.get("page_size", 500) or 500)
        df = log_service.load_logs(
            limit=limit,
            start_date=filters.get("start_date"),
            end_date=filters.get("end_date"),
            action_type=str(filters.get("action_type", "")).strip() or None,
            level=str(filters.get("level", "ALL")),
            keyword=str(filters.get("keyword", "")).strip() or None,
        )
    except TypeError:
        df = log_service.load_logs(limit=int(filters.get("page_size", 500) or 500))
    if df is None:
        df = pd.DataFrame()
    return {"ok": True, "df": df, "total_rows": len(df), "page": 1, "page_size": int(filters.get("page_size", 500) or 500), "total_pages": 1, "elapsed_seconds": 0, "fallback": True}


def _delete_logs_safely(start_date, end_date, username: str) -> int:
    if not hasattr(log_service, "delete_logs_by_date_range"):
        st.error("目前 services/log_service.py 尚未更新，缺少 delete_logs_by_date_range。")
        return 0
    return int(log_service.delete_logs_by_date_range(start_date, end_date, user_name=username) or 0)


if "log_query_filters" not in st.session_state:
    st.session_state["log_query_filters"] = _default_filters()

st.markdown("### 操作紀錄查詢 / Operation Log Search")
st.caption("V189：本頁改為 SQL 後端分頁。切換頁次只查目前頁，不載入全量 LOG；Excel 下載為目前頁資料。")
with st.form("log_query_filter_form", clear_on_submit=False):
    f = st.session_state["log_query_filters"]
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    start_date = c1.date_input("開始日期 / Start Date", value=f.get("start_date") or today_date())
    end_date = c2.date_input("結束日期 / End Date", value=f.get("end_date") or today_date())
    page_size = c3.number_input("每頁筆數 / Page Size", min_value=100, max_value=5000, value=int(f.get("page_size", 500)), step=100)
    page = c4.number_input("頁次 / Page", min_value=1, max_value=999999, value=int(f.get("page", 1)), step=1)

    c5, c6, c7 = st.columns([1, 1, 2])
    action_type = c5.text_input("動作類型 / Action Type", value=str(f.get("action_type", "")), placeholder="START_WORK、INSERT、DELETE")
    levels = ["ALL", "INFO", "WARN", "ERROR", "FAIL", "SUCCESS"]
    current_level = str(f.get("level", "ALL"))
    level = c6.selectbox("等級 / Level", levels, index=levels.index(current_level) if current_level in levels else 0)
    keyword = c7.text_input("關鍵字 / Keyword", value=str(f.get("keyword", "")))

    c8, c9 = st.columns([1, 1])
    apply_filter = c8.form_submit_button("⌕ 套用查詢 / Apply Query", use_container_width=True)
    clear_filter = c9.form_submit_button("↺ 清除條件 / Clear", use_container_width=True)

if clear_filter:
    st.session_state["log_query_filters"] = _default_filters()
    st.rerun()

if apply_filter:
    if start_date > end_date:
        st.error("開始日期不可大於結束日期。")
        st.stop()
    st.session_state["log_query_filters"] = {
        "start_date": start_date,
        "end_date": end_date,
        "page_size": int(page_size),
        "page": int(page),
        "action_type": action_type.strip(),
        "level": level,
        "keyword": keyword.strip(),
    }
    st.rerun()

filters = st.session_state["log_query_filters"]
result = _load_logs_safely(filters)
df = result.get("df") if isinstance(result, dict) else pd.DataFrame()
if df is None:
    df = pd.DataFrame()
try:
    total_pages = int(result.get("total_pages", 1) or 1)
except Exception:
    total_pages = 1

st.caption(
    f"目前查詢日期：{filters.get('start_date')} ~ {filters.get('end_date')}｜"
    f"目前頁筆數：{len(df)}｜總筆數：{int(result.get('total_rows', len(df)) or 0):,}｜"
    f"頁次：{int(result.get('page', filters.get('page', 1)) or 1)} / {total_pages}｜"
    f"查詢秒數：{result.get('elapsed_seconds', 0)}"
)

pg1, pg2, pg3, pg4 = st.columns([1, 1, 1, 3])
if pg1.button("◀ 上一頁", use_container_width=True, disabled=int(filters.get("page", 1)) <= 1):
    st.session_state["log_query_filters"]["page"] = max(1, int(filters.get("page", 1)) - 1)
    st.rerun()
if pg2.button("下一頁 ▶", use_container_width=True, disabled=int(filters.get("page", 1)) >= total_pages):
    st.session_state["log_query_filters"]["page"] = int(filters.get("page", 1)) + 1
    st.rerun()
if pg3.button("回第 1 頁", use_container_width=True, disabled=int(filters.get("page", 1)) == 1):
    st.session_state["log_query_filters"]["page"] = 1
    st.rerun()
pg4.info("換頁只查目前頁；不會觸發刪除、不會重建權威檔。")

if not df.empty:
    display_df = log_service.format_logs_for_display(df) if hasattr(log_service, "format_logs_for_display") else df
    if "帳號 / User" in display_df.columns:
        legacy_count = int(display_df["帳號 / User"].astype(str).str.lower().isin(["appuser", "adminuser"]).sum())
        if legacy_count > 0:
            st.caption(f"注意：目前查詢內有 {legacy_count} 筆舊版 OS 帳號紀錄；V78 後新紀錄會寫入實際登入帳號。")

    st.download_button(
        "▣ 下載目前頁 LOG Excel / Download Current Page Excel",
        data=_make_logs_excel_bytes(df, display_df, filters),
        file_name=_safe_log_export_filename(filters),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    render_table(display_df, "system_logs", editable=False, height=620)
else:
    st.info("此條件下尚無 LOG / No logs for current filters")

st.divider()
st.markdown("### 刪除區間 LOG / Delete Logs by Date Range")
if check_permission("06_logs", "can_delete") or check_permission("06_logs", "can_manage"):
    st.warning("刪除 LOG 會建立 tombstone，避免 Reboot App 後舊 LOG 復活。請先確認日期，再勾選確認。")
    d1, d2 = st.columns(2)
    delete_start = d1.date_input("刪除開始日期 / Delete Start", value=filters.get("start_date") or today_date(), key="log_delete_start")
    delete_end = d2.date_input("刪除結束日期 / Delete End", value=filters.get("end_date") or today_date(), key="log_delete_end")
    preview_count = 0
    if callable(query_logs_backend_page) and delete_start <= delete_end:
        try:
            preview_count = int(query_logs_backend_page(start_date=delete_start, end_date=delete_end, page=1, page_size=1).get("total_rows", 0) or 0)
        except Exception:
            preview_count = 0
    st.info(f"此區間目前符合刪除條件的 LOG 筆數：約 {preview_count}")
    delete_token = int(st.session_state.get("log_delete_confirm_token", 0))
    confirm_key = f"confirm_delete_log_range_{delete_token}"
    confirm_delete = st.checkbox(
        "我確認要刪除上述日期區間的 LOG 紀錄 / I confirm deleting logs in this date range",
        key=confirm_key,
    )
    if st.button("⊖ 刪除指定日期區間 LOG / Delete Range", use_container_width=True, disabled=not confirm_delete):
        if delete_start > delete_end:
            st.error("刪除開始日期不可大於結束日期。")
        else:
            username = st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM"))
            deleted = _delete_logs_safely(delete_start, delete_end, username=username)
            st.session_state["log_delete_confirm_token"] = delete_token + 1
            st.success(f"已刪除 {deleted} 筆 LOG，並保留一筆刪除稽核紀錄。")
            st.rerun()
else:
    st.caption("你的帳號沒有 LOG 刪除權限；如需刪除區間 LOG，請請管理員在 10｜權限管理開啟 06 模組的刪除或管理權限。")
