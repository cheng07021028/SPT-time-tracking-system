# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from services.app_config import APP_TITLE, APP_SUBTITLE, MODULES
from services.auth_service import require_login, check_permission, current_user, current_role, logout
from services.ui import apply_theme
from services.permanent_store import STORE_ROOT, store_health

st.set_page_config(page_title=APP_TITLE, page_icon="▣", layout="wide", initial_sidebar_state="expanded")
apply_theme()
require_login()

st.markdown(f"""
<div class='spt-hero'>
  <div class='spt-title'>{APP_TITLE}</div>
  <div class='spt-sub'>{APP_SUBTITLE}｜Clean Architecture｜單一路徑永久保存版</div>
  <div class='spt-sub'>正式資料源：<code>data/permanent_store</code>｜登入：{current_user()}｜角色：{current_role()}</div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.caption(f"使用者：{current_user()}")
    if st.button("登出", use_container_width=True):
        logout(); st.rerun()

st.success("系統已使用乾淨版永久保存架構啟動。所有模組資料與欄位設定只讀寫 data/permanent_store。")

c1, c2, c3, c4 = st.columns(4)
health = store_health()
c1.metric("模組數", len(MODULES))
c2.metric("永久根目錄", "唯一")
c3.metric("資料模組", len(health.get("modules", [])))
c4.metric("權限", "Enabled")

st.subheader("系統模組 / Modules")
cols = st.columns(3)
for i, m in enumerate(MODULES):
    with cols[i % 3]:
        allowed = check_permission(m.key, "view")
        st.markdown(f"<div class='spt-card'><b>{m.no}｜{m.title}</b><br><span style='color:#9de7ff'>{m.title_en}</span><br>{m.desc}<br><br>狀態：{'可進入' if allowed else '無權限'}</div>", unsafe_allow_html=True)

st.info("請從左側選單進入各模組。預設管理員：admin / admin123，正式使用前請到 10 權限管理修改密碼。")
