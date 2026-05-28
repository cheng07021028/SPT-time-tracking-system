# -*- coding: utf-8 -*-
from __future__ import annotations

# === V160 Taiwan timezone bootstrap ===
# Streamlit Cloud system logs may display UTC, but all application records, LOG rows,
# exports, date filters, and daily reset calculations must use Taiwan time.
try:
    from services.timezone_bootstrap_service import apply_app_timezone
    apply_app_timezone()
except Exception:
    pass
# === /V160 Taiwan timezone bootstrap ===

# === V-PERSIST-ROOT: single permanent store bootstrap ===
try:
    from services.permanent_store_service import ensure_permanent_store
    ensure_permanent_store()
except Exception:
    pass
# === /V-PERSIST-ROOT ===


import streamlit as st

from services.theme_service import apply_theme, render_home_header, render_kpi_cards, render_module_cards
from services.security_service import require_login, check_permission
from services.home_ui_settings_service import inject_global_font_scale, render_global_font_controls, load_global_ui_settings

st.set_page_config(
    page_title="超慧科技製造部｜智慧工時紀錄系統",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
require_login("home")
# V3.64: login/home must stay fast.
# Do NOT run restore/export/GitHub/persistence migration immediately after login.
# Each module loads its own lightweight settings when opened; this prevents login spinning.
if not st.session_state.get("_spt_v364_login_fast_path_ready"):
    st.session_state["_spt_v364_login_fast_path_ready"] = True
_global_ui_settings = load_global_ui_settings()
inject_global_font_scale(_global_ui_settings.get("global_font_scale_percent", 100))
render_home_header()

_current_user = st.session_state.get("username") or st.session_state.get("current_user") or "SYSTEM"
render_global_font_controls(username=str(_current_user))

st.success("系統初始化成功。請從左側選單進入各功能頁。")

render_kpi_cards([
    ("核心模組 / Modules", "13"),
    ("資料庫 / Database", "SQLite"),
    ("雲端保存 / GitHub", "Ready"),
    ("權限系統 / Permission", "Enabled"),
])

st.header("系統模組 / System Modules")

all_modules = [
    ("01", "工時紀錄", "快速開始、同步作業、暫停、下班、完工與工時計算", "01_time_record"),
    ("02", "歷史紀錄", "完整工時明細查詢、編輯、儲存與 Excel 匯出", "02_history"),
    ("03", "製令管理", "Excel 匯入、貼上資料、手動新增與製令主檔維護", "03_work_orders"),
    ("04", "人員名單", "人員主檔、在廠作業、今日出勤與名單維護", "04_employees"),
    ("05", "製令工時分析", "製令累積工時、工段分析與明細查詢", "05_analysis"),
    ("06", "LOG查詢", "系統操作、異常與資料異動紀錄查詢", "06_logs"),
    ("07", "今日未紀錄名單", "出勤但尚未登錄工時的人員即時提示", "07_missing"),
    ("08", "人員每日工時", "每日累積工時、合理區間與異常提醒", "08_daily_hours"),
    ("09", "資料永久保存與備份", "JSON 備份、GitHub 雲端永久保存與還原", "09_persistence"),
    ("10", "權限管理", "帳號、角色、模組權限與閒置自動登出設定", "10_permissions"),
    ("11", "登入紀錄", "登入、登出、權限不足與安全事件查詢", "11_login_logs"),
    ("12", "模組永久紀錄中心", "每個模組獨立 records、settings、audit 與 history 時間戳備份", "12_module_persistence"),
    ("13", "系統設定", "工段名稱、休息時間與跨模組共用設定", "13_system_settings"),
]
modules = [(no, name, desc) for no, name, desc, code in all_modules if check_permission(code, "can_view")]
if modules:
    render_module_cards(modules)
else:
    st.warning("你的帳號目前沒有任何模組瀏覽權限，請聯絡系統管理員。")
