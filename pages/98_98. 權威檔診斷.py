# -*- coding: utf-8 -*-
"""V300.15.1 all-module authority-file diagnostic page.

Admin-only diagnostic page. It inspects all 15 module authority paths and legacy
sources. It does not modify 01/02 logic and does not overwrite production data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

st.set_page_config(page_title="98. 權威檔診斷", layout="wide")


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
    render_markdown_report,
    save_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = ROOT / "data" / "permanent_store" / "authority_trace"
SNAPSHOT_PATH = TRACE_DIR / "v30015_latest_snapshot.json"
REPORT_PATH = TRACE_DIR / "V300_15_AUTHORITY_TRACE_REPORT.md"

st.title("98. 權威檔診斷 / Authority File Diagnostic")
st.caption("V300.15.1｜盤點 01～99 共 15 個模組的權威檔與舊來源。只診斷，不修改正式資料。")

st.warning(
    "這個頁面只做盤點與報告產生：不改動 01/02、權限帳號、系統設定、登入紀錄或 LOG 內容。",
    icon="⚠️",
)

module_count = len(MODULES_TO_TRACE)
st.info(f"本次盤點模組數：{module_count}。包含 01～14 與 99 效能診斷。", icon="📌")

col_run, col_open = st.columns([1, 1])
with col_run:
    run_trace = st.button("▶ 執行全模組權威檔盤點", type="primary", use_container_width=True)
with col_open:
    open_latest = st.button("📄 載入最新盤點結果", use_container_width=True)

snapshot: Dict[str, Any] | None = None
report_text = ""

if run_trace:
    with st.spinner("正在盤點 15 個模組的權威檔與舊來源..."):
        snapshot = save_snapshot(ROOT)
        report_text = render_markdown_report(snapshot)
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report_text, encoding="utf-8")
    st.success("全模組權威檔盤點完成，已產生報告。")
elif open_latest:
    if SNAPSHOT_PATH.exists():
        try:
            snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            if REPORT_PATH.exists():
                report_text = REPORT_PATH.read_text(encoding="utf-8")
            else:
                report_text = render_markdown_report(snapshot)
            st.success("已載入最新盤點結果。")
        except Exception as exc:
            st.error(f"讀取最新盤點結果失敗：{exc}")
    else:
        st.info("尚未有盤點結果，請先按『執行全模組權威檔盤點』。")

if snapshot is None and SNAPSHOT_PATH.exists():
    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        report_text = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else render_markdown_report(snapshot)
    except Exception:
        snapshot = None

st.divider()

if snapshot is None:
    st.subheader("待執行")
    st.write("請按上方『執行全模組權威檔盤點』。系統會產生 JSON 與 Markdown 報告供下載。")
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
        data=json.dumps(snapshot, ensure_ascii=False, indent=2),
        file_name="v30015_latest_snapshot.json",
        mime="application/json",
        use_container_width=True,
    )
with col_md:
    st.download_button(
        "⬇ 下載 Markdown report",
        data=report_text or render_markdown_report(snapshot),
        file_name="V300_15_AUTHORITY_TRACE_REPORT.md",
        mime="text/markdown",
        use_container_width=True,
    )

with st.expander("原始報告預覽", expanded=False):
    st.code(report_text or render_markdown_report(snapshot), language="markdown")
