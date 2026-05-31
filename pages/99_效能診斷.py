# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_login, get_current_user
from services.spt_speed_diagnostic_service import build_summary, write_report
from services.performance_profiler_service import read_events


def _safe_table(rows, *, max_rows: int = 200):
    """Render diagnostics without using st.dataframe.

    The project globally wraps st.dataframe/st.data_editor for column settings.
    The diagnostics page may show several tables in one run, which can trigger
    duplicate Streamlit element keys inside that wrapper.  HTML rendering avoids
    the wrapper and keeps this page read-only.
    """
    if not rows:
        st.caption("目前尚無資料。")
        return
    df = pd.DataFrame(rows).head(max_rows)
    html = df.to_html(index=False, escape=True)
    st.markdown(
        '<div style="overflow-x:auto; width:100%;">' + html + '</div>',
        unsafe_allow_html=True,
    )

st.set_page_config(page_title="99. 效能診斷", page_icon="⏱", layout="wide")
apply_theme()
require_login("99_speed_diagnostic")
render_header("99｜效能診斷", "V257.1 自動測速紀錄：登入、首頁、01工時紀錄、Neon/SQL、按鈕交易耗時")

st.info("請先正常操作一次：登入 → 進入 01 → 按開始/暫停/完工。再回到本頁按重新整理，即可下載測速報告。")

col1, col2, col3 = st.columns(3)
with col1:
    hours = st.number_input("統計最近幾小時", min_value=1, max_value=72, value=24, step=1)
with col2:
    limit = st.number_input("最多讀取事件數", min_value=100, max_value=20000, value=5000, step=100)
with col3:
    if st.button("重新整理測速報告", use_container_width=True):
        st.rerun()

summary = build_summary(last_hours=float(hours), limit=int(limit))
report_path = write_report(last_hours=float(hours))

st.subheader("總覽")
st.json({
    "目前使用者": get_current_user(),
    "事件數": summary.get("event_count", 0),
    "慢事件數": summary.get("slow_count", 0),
    "錯誤事件數": summary.get("error_count", 0),
    "報告檔": str(report_path),
})

for title, key in [("依函式/動作統計", "by_name"), ("依類別統計", "by_category"), ("熱點資料表/模組", "hot_tables_or_modules")]:
    rows = summary.get(key) or []
    st.subheader(title)
    if rows:
        _safe_table(rows)
    else:
        st.caption("目前尚無資料。")

st.subheader("最慢事件 Top")
top_events = summary.get("top_events") or []
if top_events:
    slim = []
    for ev in top_events[:80]:
        detail = ev.get("detail") or {}
        slim.append({
            "時間": ev.get("ts"),
            "類別": ev.get("category"),
            "名稱": ev.get("name"),
            "耗時ms": ev.get("duration_ms"),
            "頁面": ev.get("page", ""),
            "SQL表": detail.get("sql_table", ""),
            "SQL動作": detail.get("sql_action", ""),
            "錯誤": ev.get("error", ""),
            "摘要": detail.get("sql_preview") or detail.get("arg0") or "",
        })
    _safe_table(slim, max_rows=80)
else:
    st.caption("目前尚無慢事件。")

json_text = json.dumps(summary, ensure_ascii=False, indent=2)
st.download_button(
    "下載 V257.1 測速報告 JSON",
    data=json_text.encode("utf-8"),
    file_name="SPT_V257_1_speed_report.json",
    mime="application/json",
    use_container_width=True,
)

try:
    event_path = Path("data/performance/performance_events.jsonl")
    if event_path.exists():
        st.download_button(
            "下載原始測速事件 JSONL",
            data=event_path.read_bytes(),
            file_name="SPT_V257_1_performance_events.jsonl",
            mime="application/jsonl",
            use_container_width=True,
        )
except Exception:
    pass
