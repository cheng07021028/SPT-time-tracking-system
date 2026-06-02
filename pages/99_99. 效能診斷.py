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



def _is_system_admin() -> bool:
    """Allow diagnostics only for authoritative system admins.

    This page contains performance traces and SQL error summaries, so it must be
    stricter than normal module permissions. It intentionally mirrors the hard
    admin concept used by 10. 權限管理.
    """
    try:
        from services.security_service import _v142_is_permission_management_admin  # type: ignore
        if bool(_v142_is_permission_management_admin()):
            return True
    except Exception:
        pass
    user = get_current_user() or {}
    username = str(user.get("username") or user.get("帳號") or "").strip().lower()
    roles = [str(x).strip().lower() for x in (user.get("roles", []) or [])]
    role = str(user.get("role") or user.get("role_code") or "").strip().lower()
    return bool(username == "admin" or role == "admin" or "admin" in roles)


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
if not _is_system_admin():
    st.error("權限不足：99. 效能診斷只允許系統管理員進入。")
    st.stop()
render_header("99｜效能診斷", "V258 自動測速紀錄：登入、首頁、01工時紀錄、Neon/SQL、按鈕交易耗時｜限系統管理員")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("99", "效能診斷")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


st.info("請先正常操作一次：登入 → 進入 01 → 按開始/暫停/完工。再回到本頁按重新整理，即可下載測速報告。")

st.info("V39：診斷條件只會先暫存；按『重新整理測速報告』後才讀取/彙總效能事件，避免每次調整數字就重新運算。")
_default_perf_filters = {"hours": 24, "limit": 5000}
_applied_perf_filters = st.session_state.get("v39_perf_filters_applied", _default_perf_filters.copy())
with st.form("v39_perf_report_filter_form", clear_on_submit=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        pending_hours = st.number_input("統計最近幾小時", min_value=1, max_value=72, value=int(_applied_perf_filters.get("hours", 24)), step=1)
    with col2:
        pending_limit = st.number_input("最多讀取事件數", min_value=100, max_value=20000, value=int(_applied_perf_filters.get("limit", 5000)), step=100)
    with col3:
        st.write("")
        st.write("")
        refresh_report = st.form_submit_button("重新整理測速報告", use_container_width=True, type="primary")
if refresh_report:
    st.session_state["v39_perf_filters_applied"] = {"hours": int(pending_hours), "limit": int(pending_limit)}
    st.rerun()
_applied_perf_filters = st.session_state.get("v39_perf_filters_applied", _default_perf_filters.copy())
hours = int(_applied_perf_filters.get("hours", 24))
limit = int(_applied_perf_filters.get("limit", 5000))

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

st.divider()
st.subheader("V40 全模組頁面進入追蹤 / Page entry tracking")
st.caption("所有 pages/*.py 已加入輕量頁面耗時事件：類別 page、名稱 page.01/page.02/...。請先實際點進慢的模組，再回本頁按『重新整理測速報告』查看最慢頁面與 rerun 次數。")

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



st.divider()
st.subheader("V32 Neon 架構合規與效能快測")
st.caption("目標：20 台電腦、50 人以上同時記錄；每個常用按鈕/查詢 2~3 秒完成；所有正式資料以 Neon/PostgreSQL 為單一真實來源。")
try:
    from services.neon_performance_audit_service import module_architecture_audit, performance_probe, dataframe
    audit = module_architecture_audit()
    c1, c2, c3 = st.columns(3)
    c1.metric("資料權威", audit.get("backend", "unknown"))
    c2.metric("PostgreSQL", "ON" if audit.get("postgres_enabled") else "OFF")
    c3.metric("模組數", len(audit.get("modules", [])))
    st.markdown("##### 模組架構稽核 / Module architecture audit")
    _safe_table(audit.get("modules") or [], max_rows=30)
    if st.button("執行 2~3 秒效能快測 / Run performance probe", use_container_width=True):
        st.session_state["v32_perf_probe"] = performance_probe()
    probe = st.session_state.get("v32_perf_probe")
    if probe:
        st.markdown("##### 效能快測結果 / Performance probe")
        st.json({"backend": probe.get("backend"), "target_seconds": probe.get("target_seconds"), "ok": probe.get("ok")})
        _safe_table(probe.get("checks") or [], max_rows=30)
except Exception as exc:
    st.warning(f"V32 架構/效能快測暫時無法執行：{exc}")

json_text = json.dumps(summary, ensure_ascii=False, indent=2)
st.download_button(
    "下載 V258 測速報告 JSON",
    data=json_text.encode("utf-8"),
    file_name="SPT_V258_speed_report.json",
    mime="application/json",
    use_container_width=True,
)

try:
    event_path = Path("data/performance/performance_events.jsonl")
    if event_path.exists():
        st.download_button(
            "下載原始測速事件 JSONL",
            data=event_path.read_bytes(),
            file_name="SPT_V258_performance_events.jsonl",
            mime="application/jsonl",
            use_container_width=True,
        )
except Exception:
    pass

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

