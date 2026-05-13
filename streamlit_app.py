# -*- coding: utf-8 -*-
from __future__ import annotations
import streamlit as st
from services.theme_service import apply_theme, render_header
from services.db_service import DB_PATH, query_df

st.set_page_config(page_title="超慧科技製造部｜工時紀錄系統", page_icon="🕒", layout="wide")
apply_theme()
render_header("超慧科技製造部｜智慧工時紀錄系統")

st.markdown("""
<div class="spt-card">
本系統以 <b>快速記錄、準確計算、即時統計、完整追溯</b> 為核心，
將原 Excel 工時模型逐步轉換成 Streamlit + SQLite 架構。
</div>
""", unsafe_allow_html=True)

try:
    k1 = query_df("SELECT COUNT(*) AS c FROM work_orders").iloc[0]["c"]
    k2 = query_df("SELECT COUNT(*) AS c FROM employees").iloc[0]["c"]
    k3 = query_df("SELECT COUNT(*) AS c FROM time_records").iloc[0]["c"]
    k4 = query_df("SELECT COUNT(*) AS c FROM time_records WHERE end_timestamp IS NULL").iloc[0]["c"]
except Exception:
    st.warning("尚未初始化資料庫。請先執行：python tools\\init_database.py")
    k1 = k2 = k3 = k4 = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("製令主檔", f"{k1:,}")
c2.metric("人員名單", f"{k2:,}")
c3.metric("累積工時紀錄", f"{k3:,}")
c4.metric("目前作業中", f"{k4:,}")

st.divider()
st.subheader("系統模組")
cols = st.columns(4)
modules = [
    ("01 工時紀錄", "工程師快速開始 / 暫停 / 下班 / 完工"),
    ("02 歷史紀錄", "查詢、篩選、匯出 Excel"),
    ("03 製令管理", "Excel 匯入 / 貼上 / 手動維護"),
    ("04 人員名單", "出勤與在廠狀態管理"),
    ("05 製令工時分析", "製令、工段、人員工時統計"),
    ("06 LOG 查詢", "動作與異常追溯"),
    ("07 今日未紀錄名單", "即時找出出勤未記錄人員"),
    ("08 人員每日工時", "每日累積工時與異常燈號"),
]
for idx, (name, desc) in enumerate(modules):
    with cols[idx % 4]:
        st.markdown(f"<div class='spt-card'><h3>{name}</h3><p>{desc}</p></div>", unsafe_allow_html=True)

st.caption(f"資料庫位置：{DB_PATH}")
