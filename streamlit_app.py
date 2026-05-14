# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from services.theme_service import apply_theme, render_home_header, render_kpi_cards

st.set_page_config(
    page_title="超慧科技製造部｜智慧工時紀錄系統",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
render_home_header()

st.success("系統初始化成功。請從左側選單進入各功能頁。")

render_kpi_cards([
    ("核心模組 / Modules", "08"),
    ("資料庫 / Database", "SQLite"),
    ("匯入匯出 / Excel", "Ready"),
    ("系統狀態 / Status", "Online"),
])

st.markdown('<div class="spt-section-title">系統模組</div>', unsafe_allow_html=True)

modules = [
    ("01", "工時紀錄", "快速開始、同步作業、暫停、下班、完工與工時計算"),
    ("02", "歷史紀錄", "完整工時明細查詢、編輯、儲存與 Excel 匯出"),
    ("03", "製令管理", "Excel 匯入、貼上資料、手動新增與製令主檔維護"),
    ("04", "人員名單", "人員主檔、在廠作業、今日出勤與名單維護"),
    ("05", "製令工時分析", "製令累積工時、工段分析與明細查詢"),
    ("06", "LOG查詢", "系統操作、異常與資料異動紀錄查詢"),
    ("07", "今日未紀錄名單", "出勤但尚未登錄工時的人員即時提示"),
    ("08", "人員每日工時", "每日累積工時、合理區間與異常提醒"),
]

html = '<div class="spt-module-grid">'
for no, name, desc in modules:
    html += f'''
    <div class="spt-module-card">
      <div class="spt-module-no">{no}</div>
      <div class="spt-module-name">{name}</div>
      <div class="spt-module-desc">{desc}</div>
    </div>
    '''
html += '</div>'
st.markdown(html, unsafe_allow_html=True)
