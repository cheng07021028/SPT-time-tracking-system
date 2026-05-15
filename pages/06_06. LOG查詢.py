# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import check_permission, require_module_access
from services.log_service import count_logs_by_date_range, delete_logs_by_date_range, load_logs, write_log
from services.table_ui_service import render_table

st.set_page_config(page_title="06. LOG 查詢", page_icon="🧾", layout="wide")
apply_theme()
require_module_access("06_logs")
render_header("06｜LOG 查詢", "系統操作、異常與資料異動紀錄查詢｜支援日期篩選與區間刪除")

# 查詢條件採「按下套用才查詢」模式，避免每點一次日期/輸入文字就大量讀取 LOG。
def _default_filters() -> dict:
    today = date.today()
    return {
        "start_date": today - timedelta(days=7),
        "end_date": today,
        "limit": 1000,
        "action_type": "",
        "level": "ALL",
        "keyword": "",
    }

if "log_query_filters" not in st.session_state:
    st.session_state["log_query_filters"] = _default_filters()

st.markdown("### 查詢條件 / Query Filters")
with st.form("log_query_filter_form", clear_on_submit=False):
    f = st.session_state["log_query_filters"]
    c1, c2, c3 = st.columns([1, 1, 1])
    start_date = c1.date_input("開始日期 / Start Date", value=f.get("start_date") or date.today())
    end_date = c2.date_input("結束日期 / End Date", value=f.get("end_date") or date.today())
    limit = c3.number_input("讀取上限 / Limit", min_value=100, max_value=20000, value=int(f.get("limit", 1000)), step=100)

    c4, c5, c6 = st.columns([1, 1, 2])
    action_type = c4.text_input("動作類型 / Action Type", value=str(f.get("action_type", "")))
    level = c5.selectbox("等級 / Level", ["ALL", "INFO", "WARN", "ERROR", "FAIL", "SUCCESS"], index=["ALL", "INFO", "WARN", "ERROR", "FAIL", "SUCCESS"].index(str(f.get("level", "ALL"))) if str(f.get("level", "ALL")) in ["ALL", "INFO", "WARN", "ERROR", "FAIL", "SUCCESS"] else 0)
    keyword = c6.text_input("關鍵字 / Keyword", value=str(f.get("keyword", "")))

    c7, c8 = st.columns([1, 1])
    apply_filter = c7.form_submit_button("🔎 套用查詢 / Apply Query", use_container_width=True)
    clear_filter = c8.form_submit_button("🧹 清除條件 / Clear", use_container_width=True)

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
        "limit": int(limit),
        "action_type": action_type.strip(),
        "level": level,
        "keyword": keyword.strip(),
    }
    st.rerun()

filters = st.session_state["log_query_filters"]
df = load_logs(
    limit=int(filters.get("limit", 1000)),
    start_date=filters.get("start_date"),
    end_date=filters.get("end_date"),
    action_type=str(filters.get("action_type", "")).strip() or None,
    level=str(filters.get("level", "ALL")),
    keyword=str(filters.get("keyword", "")).strip() or None,
)

st.caption(
    f"目前查詢日期：{filters.get('start_date')} ~ {filters.get('end_date')}｜顯示筆數：{len(df)}｜上限：{filters.get('limit')}"
)

if not df.empty:
    render_table(df, "system_logs", editable=False, height=620)
else:
    st.info("此條件下尚無 LOG / No logs for current filters")

st.divider()
st.markdown("### 刪除區間 LOG / Delete Logs by Date Range")
if check_permission("06_logs", "can_delete") or check_permission("06_logs", "can_manage"):
    st.warning("刪除 LOG 會永久移除指定日期區間內的系統操作紀錄。請先確認日期，再勾選確認。")
    d1, d2 = st.columns(2)
    delete_start = d1.date_input("刪除開始日期 / Delete Start", value=filters.get("start_date") or date.today(), key="log_delete_start")
    delete_end = d2.date_input("刪除結束日期 / Delete End", value=filters.get("end_date") or date.today(), key="log_delete_end")
    preview_count = count_logs_by_date_range(delete_start, delete_end) if delete_start <= delete_end else 0
    st.info(f"此區間目前符合刪除條件的 LOG 筆數：{preview_count}")
    confirm_delete = st.checkbox("我確認要刪除上述日期區間的 LOG 紀錄 / I confirm deleting logs in this date range", key="confirm_delete_log_range")
    if st.button("🗑️ 刪除指定日期區間 LOG / Delete Range", use_container_width=True, disabled=not confirm_delete):
        if delete_start > delete_end:
            st.error("刪除開始日期不可大於結束日期。")
        else:
            username = st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM"))
            deleted = delete_logs_by_date_range(delete_start, delete_end, user_name=username)
            st.session_state["confirm_delete_log_range"] = False
            st.success(f"已刪除 {deleted} 筆 LOG，並保留一筆刪除稽核紀錄。")
            st.rerun()
else:
    st.caption("你的帳號沒有 LOG 刪除權限；如需刪除區間 LOG，請請管理員在 10｜權限管理開啟 06 模組的刪除或管理權限。")
