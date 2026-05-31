# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, get_current_user
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


def _clear_performance_records() -> dict:
    """Clear only 99. 效能診斷 performance files.

    This does not touch time records, history records, login logs, permissions,
    backups, or business data.  The JSONL event file is truncated instead of
    deleting the directory, so the profiler can keep writing after the clear.
    """
    try:
        from services.performance_profiler_service import EVENT_PATH, PERF_DIR
    except Exception:
        EVENT_PATH = Path("data/performance/performance_events.jsonl")
        PERF_DIR = EVENT_PATH.parent

    cleared: list[str] = []
    errors: list[str] = []
    try:
        PERF_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        errors.append(f"mkdir: {exc}")

    targets: set[Path] = set()
    try:
        targets.add(Path(EVENT_PATH))
        targets.add(Path(EVENT_PATH).with_suffix(".jsonl.1"))
    except Exception:
        pass
    for pattern in ("performance_events*.jsonl*", "spt_v*_speed_summary.json", "SPT_V*_speed_report.json"):
        try:
            targets.update(Path(PERF_DIR).glob(pattern))
        except Exception as exc:
            errors.append(f"glob {pattern}: {exc}")

    for path in sorted(targets, key=lambda x: str(x)):
        try:
            path = Path(path)
            if path.name == "performance_events.jsonl":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
                cleared.append(str(path))
            elif path.exists():
                path.unlink()
                cleared.append(str(path))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return {"ok": not errors, "cleared": cleared, "errors": errors}

st.set_page_config(page_title="99. 效能診斷", page_icon="⏱", layout="wide")
apply_theme()
require_module_access("99_speed_diagnostic", "can_view")
if not _is_system_admin():
    st.error("權限不足：99. 效能診斷只允許系統管理員進入。")
    st.stop()
render_header("99｜效能診斷", "V258 自動測速紀錄：登入、首頁、01工時紀錄、Neon/SQL、按鈕交易耗時｜限系統管理員")

st.info("請先正常操作一次：登入 → 進入 01 → 按開始/暫停/完工。再回到本頁按重新整理，即可下載測速報告。")

with st.expander("清除效能紀錄 / Clear Performance Records", expanded=False):
    st.warning("此功能只會清除 99. 效能診斷的測速 JSON/JSONL 檔，不會刪除 01/02 工時資料、登入紀錄或權限設定。")
    confirm_clear = st.checkbox("我確認要清除效能診斷紀錄", key="v3007_confirm_clear_performance_records")
    if st.button("清除效能紀錄", type="secondary", disabled=not confirm_clear, use_container_width=True):
        result = _clear_performance_records()
        if result.get("ok"):
            st.success(f"已清除效能紀錄：{len(result.get('cleared', []))} 個檔案。")
            st.rerun()
        else:
            st.error("清除效能紀錄時發生錯誤。")
            st.json(result)


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
