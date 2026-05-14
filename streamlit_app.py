# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path
import streamlit as st

try:
    from services.theme_service import apply_spt_theme, render_page_header, metric_card
except Exception:
    apply_spt_theme = None
    render_page_header = None
    metric_card = None

st.set_page_config(
    page_title="超慧科技製造部｜智慧工時紀錄系統",
    page_icon="🕒",
    layout="wide",
    initial_sidebar_state="expanded",
)

if apply_spt_theme:
    apply_spt_theme()

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"


def _safe_count(table: str) -> int:
    if not DB_PATH.exists():
        return 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0


def _safe_sum_hours() -> float:
    if not DB_PATH.exists():
        return 0.0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(work_hours), 0) FROM time_records")
            return float(cur.fetchone()[0] or 0)
    except Exception:
        return 0.0

if render_page_header:
    render_page_header(
        "超慧科技製造部｜智慧工時紀錄系統",
        "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + Excel Import / Export",
    )
else:
    st.title("超慧科技製造部｜智慧工時紀錄系統")
    st.caption("Super Plus Tech Manufacturing Time Tracking System")

st.success("系統初始化成功。請從左側選單進入各功能頁。")

c1, c2, c3, c4 = st.columns(4)
with c1:
    if metric_card:
        metric_card("製令主檔 / Work Orders", _safe_count("work_orders"), "目前已建立製令數")
    else:
        st.metric("製令主檔", _safe_count("work_orders"))
with c2:
    if metric_card:
        metric_card("人員主檔 / Employees", _safe_count("employees"), "目前已建立人員數")
    else:
        st.metric("人員主檔", _safe_count("employees"))
with c3:
    if metric_card:
        metric_card("工時紀錄 / Records", _safe_count("time_records"), "目前累積紀錄筆數")
    else:
        st.metric("工時紀錄", _safe_count("time_records"))
with c4:
    if metric_card:
        metric_card("累積工時 / Total Hours", f"{_safe_sum_hours():.2f}", "已結束並計算工時")
    else:
        st.metric("累積工時", f"{_safe_sum_hours():.2f}")

st.markdown("### 系統模組 / System Modules")

modules = [
    ("01", "工時紀錄", "Time Record", "工程師快速開始、暫停、下班、完工，並自動扣除休息時間。"),
    ("02", "歷史紀錄", "History Records", "完整工時明細查詢、編輯、儲存與 Excel 匯出。"),
    ("03", "製令管理", "Work Order Management", "製令主檔匯入、貼上、新增、編輯與維護。"),
    ("04", "人員名單", "Employee Master", "人員主檔、在廠狀態、今日出勤與名單維護。"),
    ("05", "製令工時分析", "Work Order Analysis", "製令累積工時、工段工時與人員工時分析。"),
    ("06", "LOG查詢", "System Logs", "追蹤人員操作、系統異常與資料異動紀錄。"),
    ("07", "今日未紀錄名單", "Missing Records Today", "顯示今日出勤但尚未建立工時紀錄的人員。"),
    ("08", "人員每日工時", "Daily Employee Hours", "追蹤每日每人累積工時與合理工時差異。"),
]

for i in range(0, len(modules), 2):
    cols = st.columns(2)
    for col, item in zip(cols, modules[i:i+2]):
        no, zh, en, desc = item
        with col:
            st.markdown(
                f"""
                <div class="spt-card">
                  <div class="spt-card-title">{no}. {zh} / {en}</div>
                  <div class="spt-card-desc">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
