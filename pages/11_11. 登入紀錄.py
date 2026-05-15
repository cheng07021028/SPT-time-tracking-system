# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.audit_log_service import (
    audit_state_status,
    clear_login_logs_by_date,
    export_audit_logs_to_state,
    load_login_logs,
    restore_audit_logs_from_state,
)

apply_theme()
render_header("11", "登入紀錄", "登入、登出、閒置自動登出、權限不足與安全事件查詢")

st.markdown("### 登入紀錄永久保存狀態 / Audit Log Permanent Status")
status = audit_state_status()
c1, c2, c3 = st.columns(3)
c1.metric("永久檔 / Permanent File", "Exists" if status.get("exists") else "Missing")
c2.metric("匯出時間 / Exported At", status.get("exported_at") or "-")
c3.metric("永久檔筆數 / Saved Logs", status.get("count", 0))

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("建立登入紀錄永久檔 / Create Audit Permanent File", use_container_width=True):
        payload = export_audit_logs_to_state()
        st.success(f"已建立登入紀錄永久檔，共 {payload.get('count', 0)} 筆。")
with b2:
    if st.button("從永久檔還原登入紀錄 / Restore Audit Logs", use_container_width=True):
        n = restore_audit_logs_from_state()
        st.success(f"已從永久檔還原 {n} 筆登入紀錄。")
with b3:
    st.caption("GitHub 雲端上傳請至 09｜資料永久保存與備份執行。")

st.divider()

st.markdown("### 登入紀錄查詢 / Login Log Search")
today = date.today()
def_start = today - timedelta(days=30)
f1, f2, f3 = st.columns([1, 1, 2])
with f1:
    start_date = st.date_input("開始日期 / Start Date", value=def_start)
with f2:
    end_date = st.date_input("結束日期 / End Date", value=today)
with f3:
    keyword = st.text_input("關鍵字 / Keyword", placeholder="帳號、姓名、事件、訊息...")
limit = st.slider("讀取筆數 / Limit", 100, 10000, 1000, step=100)

df = load_login_logs(limit=limit, start_date=str(start_date), end_date=str(end_date), keyword=keyword.strip())

m1, m2, m3 = st.columns(3)
m1.metric("筆數 / Records", len(df))
m2.metric("成功 / Success", int((df.get("result", pd.Series(dtype=str)).astype(str).str.upper() == "SUCCESS").sum()) if not df.empty else 0)
m3.metric("失敗 / Failed", int((df.get("result", pd.Series(dtype=str)).astype(str).str.upper() != "SUCCESS").sum()) if not df.empty else 0)

if df.empty:
    st.info("查無登入紀錄 / No login logs")
else:
    rename_map = {
        "id": "ID / ID",
        "username": "帳號 / Username",
        "display_name": "姓名 / Name",
        "event_type": "事件 / Event",
        "result": "結果 / Result",
        "message": "訊息 / Message",
        "module_code": "模組 / Module",
        "login_time": "登入時間 / Login Time",
        "logout_time": "登出時間 / Logout Time",
        "idle_minutes": "閒置分鐘 / Idle Minutes",
        "session_id": "Session / Session",
        "source": "來源 / Source",
        "created_at": "建立時間 / Created At",
    }
    st.dataframe(df.rename(columns=rename_map), use_container_width=True, height=430)

st.divider()
st.markdown("### 清除登入紀錄 / Clear Login Logs")
st.warning("刪除前建議先建立登入紀錄永久檔，避免稽核紀錄遺失。")
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    del_start = st.date_input("清除開始日期 / Delete Start", value=def_start, key="audit_del_start")
with c2:
    del_end = st.date_input("清除結束日期 / Delete End", value=today, key="audit_del_end")
with c3:
    confirm = st.text_input("若要清除，請輸入 DELETE / Type DELETE to confirm")
if st.button("🗑️ 清除日期區間登入紀錄 / Delete Logs in Date Range", use_container_width=True):
    if confirm != "DELETE":
        st.error("請輸入 DELETE 才能清除。")
    else:
        deleted = clear_login_logs_by_date(str(del_start), str(del_end))
        st.success(f"已清除 {deleted} 筆登入紀錄，並已更新永久檔。")
        st.rerun()
