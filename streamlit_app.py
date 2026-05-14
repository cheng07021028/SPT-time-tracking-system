# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path
import streamlit as st

from services.theme_service import apply_theme, render_header, kpi_card

st.set_page_config(
    page_title="超慧科技製造部｜智慧工時紀錄系統",
    page_icon="🕒",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
render_header(
    "超慧科技製造部｜智慧工時紀錄系統",
    "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + Excel Import / Export",
)

DB_PATH = Path("data/database/spt_time_tracking.db")


def count_table(table: str) -> int:
    if not DB_PATH.exists():
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
            return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0

cols = st.columns(4)
with cols[0]:
    st.markdown(kpi_card("製令筆數 / Work Orders", count_table("work_orders")), unsafe_allow_html=True)
with cols[1]:
    st.markdown(kpi_card("人員筆數 / Employees", count_table("employees")), unsafe_allow_html=True)
with cols[2]:
    st.markdown(kpi_card("工時紀錄 / Time Records", count_table("time_records")), unsafe_allow_html=True)
with cols[3]:
    st.markdown(kpi_card("系統LOG / Logs", count_table("system_logs")), unsafe_allow_html=True)

st.success("系統初始化成功。請從左側選單進入各功能頁。")

st.markdown("### 系統模組")
modules = [
    ("01", "工時紀錄", "快速開始、暫停、下班、完工，並自動扣除休息時間"),
    ("02", "歷史紀錄", "完整工時明細查詢、編輯與 Excel 匯出"),
    ("03", "製令管理", "Excel 匯入、貼上資料、手動維護製令主檔"),
    ("04", "人員名單", "人員主檔、在廠狀態、今日出勤管理"),
    ("05", "製令工時分析", "製令累積工時與工段統計"),
    ("06", "LOG查詢", "追蹤系統操作、異常與資料修改紀錄"),
    ("07", "今日未紀錄名單", "即時顯示今日出勤但未記錄作業人員"),
    ("08", "人員每日工時", "統計今日每位人員累積工時與合理性"),
]
for code, name, desc in modules:
    st.markdown(f"**{code}. {name}**  ")
    st.caption(desc)
