# -*- coding: utf-8 -*-
"""V300.41 authority-file diagnostic page.

Admin-only diagnostic page. It inspects authority paths and legacy sources.
It does not modify 01/02 logic and does not overwrite production data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from services.theme_service import apply_theme, render_header, render_kpi_cards

st.set_page_config(page_title="98. 權威檔診斷", page_icon="🧭", layout="wide")
apply_theme()


def _admin_guard() -> None:
    try:
        from services.security_service import require_module_access

        require_module_access("10_permissions", "can_manage")
        return
    except SystemExit:
        raise
    except Exception:
        pass

    user = st.session_state.get("user") or st.session_state.get("current_user") or {}
    username = str(user.get("username") or user.get("account") or "").strip().lower() if isinstance(user, dict) else ""
    role = str(user.get("role_code") or user.get("role") or user.get("role_name") or "").strip().lower() if isinstance(user, dict) else ""
    roles = user.get("roles") if isinstance(user, dict) else []
    roles_text = " ".join(str(x).lower() for x in roles) if isinstance(roles, (list, tuple, set)) else str(roles).lower()
    if username == "admin" or role == "admin" or "admin" in roles_text or "系統管理" in roles_text:
        return

    st.error("權限不足：權威檔診斷只允許系統管理員使用。")
    st.stop()


_admin_guard()

from services.authority_trace_service import (  # noqa: E402
    MODULES_TO_TRACE,
    clear_authority_trace_cache,
    render_markdown_report,
    save_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = ROOT / "data" / "permanent_store" / "authority_trace"
SNAPSHOT_PATH = TRACE_DIR / "v30015_latest_snapshot.json"
REPORT_PATH = TRACE_DIR / "V300_15_AUTHORITY_TRACE_REPORT.md"

V30041_SNAPSHOT_KEY = "v30041_authority_snapshot"
V30041_REPORT_KEY = "v30041_authority_report"
V30041_SOURCE_KEY = "v30041_authority_source_sig"
V30041_JSON_BYTES_KEY = "v30041_authority_json_bytes"
V30041_MD_BYTES_KEY = "v30041_authority_md_bytes"


def _snapshot_file_sig() -> str:
    try:
        if not SNAPSHOT_PATH.exists():
            return "missing"
        stt = SNAPSHOT_PATH.stat()
        return f"{stt.st_size}:{int(stt.st_mtime)}"
    except Exception:
        return "unknown"


def _clear_page_cache() -> None:
    for key in (
        V30041_SNAPSHOT_KEY,
        V30041_REPORT_KEY,
        V30041_SOURCE_KEY,
        V30041_JSON_BYTES_KEY,
        V30041_MD_BYTES_KEY,
    ):
        st.session_state.pop(key, None)


def _load_latest_snapshot_cached() -> tuple[Dict[str, Any] | None, str]:
    sig = _snapshot_file_sig()
    if sig != "missing" and st.session_state.get(V30041_SOURCE_KEY) == sig:
        cached_snapshot = st.session_state.get(V30041_SNAPSHOT_KEY)
        cached_report = st.session_state.get(V30041_REPORT_KEY, "")
        if isinstance(cached_snapshot, dict):
            return cached_snapshot, str(cached_report or "")
    if not SNAPSHOT_PATH.exists():
        return None, ""
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if REPORT_PATH.exists():
        report_text = REPORT_PATH.read_text(encoding="utf-8")
    else:
        report_text = render_markdown_report(snapshot)
    st.session_state[V30041_SOURCE_KEY] = sig
    st.session_state[V30041_SNAPSHOT_KEY] = snapshot
    st.session_state[V30041_REPORT_KEY] = report_text
    st.session_state.pop(V30041_JSON_BYTES_KEY, None)
    st.session_state.pop(V30041_MD_BYTES_KEY, None)
    return snapshot, report_text


def _download_json_bytes(snapshot: Dict[str, Any]) -> bytes:
    cached = st.session_state.get(V30041_JSON_BYTES_KEY)
    if isinstance(cached, bytes):
        return cached
    data = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8-sig")
    st.session_state[V30041_JSON_BYTES_KEY] = data
    return data


def _download_md_bytes(report_text: str) -> bytes:
    cached = st.session_state.get(V30041_MD_BYTES_KEY)
    if isinstance(cached, bytes):
        return cached
    data = (report_text or "").encode("utf-8-sig")
    st.session_state[V30041_MD_BYTES_KEY] = data
    return data


render_header(
    "98",
    "權威檔診斷",
    "Authority File Diagnostic｜盤點各模組權威檔、舊來源與資料保存狀態，只診斷不覆蓋正式資料",
)

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("98", "權威檔診斷")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


module_count = len(MODULES_TO_TRACE)
render_kpi_cards([
    ("診斷版本 / Version", "V300.41"),
    ("盤點模組 / Modules", str(module_count)),
    ("執行模式 / Mode", "Read Only"),
    ("資料保護 / Safety", "No overwrite"),
])

st.warning(
    "這個頁面只做盤點與報告產生：不改動 01/02、權限帳號、系統設定、登入紀錄或 LOG 內容。",
    icon="⚠️",
)

st.caption(
    "V300.41：預設使用淺層盤點，只檢查檔案存在、大小與修改時間，不解析大型 JSON / JSONL 內容；需要最新結果時請手動載入或執行。"
)

col_run, col_open, col_clear = st.columns([1, 1, 1])
with col_run:
    run_trace = st.button("▶ 執行全模組權威檔盤點", type="primary", use_container_width=True)
with col_open:
    open_latest = st.button("📄 載入最新盤點結果", use_container_width=True)
with col_clear:
    clear_cache = st.button("🧹 清除本頁快取", use_container_width=True)

if clear_cache:
    clear_authority_trace_cache()
    _clear_page_cache()
    st.success("已清除本頁診斷快取。")

snapshot: Dict[str, Any] | None = st.session_state.get(V30041_SNAPSHOT_KEY)
report_text = str(st.session_state.get(V30041_REPORT_KEY, "") or "")

if run_trace:
    with st.spinner("正在盤點各模組權威檔與舊來源（淺層模式，不解析大型 JSON）..."):
        clear_authority_trace_cache()
        snapshot = save_snapshot(ROOT, parse_json=False, use_cache=False)
        report_text = render_markdown_report(snapshot)
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report_text, encoding="utf-8")
        st.session_state[V30041_SOURCE_KEY] = _snapshot_file_sig()
        st.session_state[V30041_SNAPSHOT_KEY] = snapshot
        st.session_state[V30041_REPORT_KEY] = report_text
        st.session_state.pop(V30041_JSON_BYTES_KEY, None)
        st.session_state.pop(V30041_MD_BYTES_KEY, None)
    st.success("全模組權威檔盤點完成，已產生報告。")
elif open_latest:
    try:
        snapshot, report_text = _load_latest_snapshot_cached()
        if snapshot is None:
            st.info("尚未有盤點結果，請先按『執行全模組權威檔盤點』。")
        else:
            st.success("已載入最新盤點結果。")
    except Exception as exc:
        st.error(f"讀取最新盤點結果失敗：{exc}")

st.divider()

if snapshot is None:
    st.subheader("待執行")
    st.write("請按上方『執行全模組權威檔盤點』或『載入最新盤點結果』。系統不會在進入頁面時自動讀取大型 snapshot。")
    try:
        _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
    except Exception:
        pass
    st.stop()

modules = snapshot.get("modules", {}) or {}

st.subheader("盤點摘要")
summary_lines: List[str] = []
summary_lines.append("| 模組 | 權威檔存在 | 舊來源存在 | 警告數 |")
summary_lines.append("|---|---:|---:|---:|")
for key, info in sorted(modules.items(), key=lambda kv: str(kv[1].get("module_no", ""))):
    module_label = f"{info.get('module_no')}. {info.get('title')}"
    authority_files = info.get("authority_files", {}) or {}
    legacy_candidates = info.get("legacy_candidates", {}) or {}
    auth_count = sum(1 for v in authority_files.values() if v.get("exists"))
    legacy_count = sum(1 for v in legacy_candidates.values() if v.get("exists"))
    warn_count = len(info.get("warnings") or [])
    summary_lines.append(f"| {module_label} | {auth_count} | {legacy_count} | {warn_count} |")
st.markdown("\n".join(summary_lines))

st.subheader("模組細節")
for key, info in sorted(modules.items(), key=lambda kv: str(kv[1].get("module_no", ""))):
    module_label = f"{info.get('module_no')}. {info.get('title')} ({key})"
    with st.expander(module_label, expanded=bool(info.get("warnings"))):
        st.markdown(f"**Expected mode:** `{info.get('expected_mode')}`")
        ad = info.get("authority_dir", {}) or {}
        st.markdown(f"**Authority dir:** `{ad.get('path')}` ｜ exists=`{ad.get('exists')}`")

        st.markdown("#### Authority files")
        file_lines = ["| 檔案 | 存在 | 大小 | 列數/鍵數 | 修改時間 |", "|---|---:|---:|---:|---|"]
        for name, finfo in (info.get("authority_files", {}) or {}).items():
            counts = []
            for count_key, val in finfo.items():
                if count_key.endswith("_count") or count_key.endswith("_keys_count") or count_key == "row_count":
                    counts.append(f"{count_key}={val}")
            if finfo.get("json_summary_mode"):
                counts.append(str(finfo.get("json_summary_mode")))
            file_lines.append(
                f"| `{name}` | {finfo.get('exists')} | {finfo.get('size_bytes', '')} | {'<br>'.join(counts)} | {finfo.get('modified_at', '')} |"
            )
        st.markdown("\n".join(file_lines), unsafe_allow_html=True)

        st.markdown("#### Legacy candidates")
        legacy_lines = ["| 路徑 | 存在 | 類型 | 大小 | 修改時間 |", "|---|---:|---|---:|---|"]
        for rel, finfo in (info.get("legacy_candidates", {}) or {}).items():
            typ = "dir" if finfo.get("is_dir") else "file" if finfo.get("is_file") else "-"
            legacy_lines.append(
                f"| `{rel}` | {finfo.get('exists')} | {typ} | {finfo.get('size_bytes', '')} | {finfo.get('modified_at', '')} |"
            )
        st.markdown("\n".join(legacy_lines))

        warnings = info.get("warnings") or []
        if warnings:
            st.markdown("#### Warnings")
            for w in warnings:
                st.warning(w)

st.subheader("下載診斷結果")
col_json, col_md = st.columns(2)
with col_json:
    st.download_button(
        "⬇ 下載 JSON snapshot",
        data=_download_json_bytes(snapshot),
        file_name="v30041_latest_snapshot.json",
        mime="application/json",
        use_container_width=True,
    )
with col_md:
    report_text = report_text or render_markdown_report(snapshot)
    st.download_button(
        "⬇ 下載 Markdown report",
        data=_download_md_bytes(report_text),
        file_name="V300_41_AUTHORITY_TRACE_REPORT.md",
        mime="text/markdown",
        use_container_width=True,
    )

with st.expander("原始報告預覽", expanded=False):
    st.code(report_text or render_markdown_report(snapshot), language="markdown")

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass
