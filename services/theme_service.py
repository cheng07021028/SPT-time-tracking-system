# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Unified Theme Service
V1.55 stable no-bat theme patch

目的：
1. 不再需要另外執行 apply_xxx.bat。
2. 所有頁面只要 import 本檔，即可套用一致 Logo、標題、Sidebar、輸入框與下拉選單樣式。
3. 保留舊版相容函式名稱，避免 streamlit_app.py 或各頁面 ImportError。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "data" / "logo" / "logo.png",
]


def _read_logo_base64() -> str:
    for p in LOGO_CANDIDATES:
        try:
            if p.exists() and p.stat().st_size > 0:
                return base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception:
            continue
    return ""


def _html_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def apply_theme() -> None:
    """全系統共用樣式。每個頁面可重複呼叫，不會破壞功能。"""
    st.markdown(
        """
<style>
:root {
    --spt-bg-0: #050b16;
    --spt-bg-1: #071322;
    --spt-bg-2: #092033;
    --spt-panel: rgba(8, 30, 48, 0.88);
    --spt-panel-2: rgba(11, 46, 68, 0.82);
    --spt-cyan: #20e6ff;
    --spt-cyan-soft: rgba(32, 230, 255, 0.38);
    --spt-text: #f2fbff;
    --spt-muted: #9eb4c7;
    --spt-input-bg: #edf7ff;
    --spt-input-text: #071827;
}

/* ===== Base ===== */
html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 18% 8%, rgba(69, 42, 140, 0.28), transparent 30%),
        radial-gradient(circle at 88% 12%, rgba(0, 170, 210, 0.18), transparent 34%),
        linear-gradient(135deg, #070b1d 0%, #06182a 42%, #071323 100%) !important;
    color: var(--spt-text) !important;
}

[data-testid="stHeader"] {
    background: rgba(4, 10, 20, 0.88) !important;
    border-bottom: 1px solid rgba(42, 220, 255, 0.10) !important;
}

.block-container {
    padding-top: 2.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1700px !important;
}

/* ===== Sidebar ===== */
[data-testid="stSidebar"] {
    background:
        linear-gradient(180deg, rgba(5, 13, 26, 0.98), rgba(6, 20, 34, 0.98)) !important;
    border-right: 1px solid rgba(32, 230, 255, 0.18) !important;
    box-shadow: 10px 0 26px rgba(0, 0, 0, 0.26) !important;
}

[data-testid="stSidebar"] * {
    color: #f2fbff !important;
    font-weight: 700 !important;
}

[data-testid="stSidebarNav"] a {
    border-radius: 12px !important;
    margin: 5px 10px !important;
    padding: 9px 12px !important;
    font-size: 1.02rem !important;
    letter-spacing: 0.2px !important;
}

[data-testid="stSidebarNav"] a:hover {
    background: rgba(32, 230, 255, 0.12) !important;
    box-shadow: 0 0 16px rgba(32, 230, 255, 0.16) !important;
}

[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNav"] li div[aria-current="page"] {
    background: linear-gradient(90deg, rgba(28, 208, 230, 0.34), rgba(96, 63, 190, 0.60)) !important;
    border-left: 3px solid #20e6ff !important;
    box-shadow: 0 0 18px rgba(32, 230, 255, 0.34) !important;
}

/* ===== Unified Header ===== */
.spt-header {
    display: flex;
    align-items: center;
    gap: 30px;
    padding: 24px 30px;
    margin: 0 0 30px 0;
    min-height: 118px;
    border: 1px solid rgba(32, 230, 255, 0.58);
    border-radius: 22px;
    background:
        radial-gradient(circle at 16% 50%, rgba(32, 230, 255, 0.12), transparent 34%),
        linear-gradient(90deg, rgba(8, 25, 42, 0.98), rgba(8, 70, 95, 0.84), rgba(6, 24, 38, 0.96));
    box-shadow:
        0 0 0 1px rgba(32, 230, 255, 0.08) inset,
        0 0 28px rgba(32, 230, 255, 0.22),
        0 18px 44px rgba(0, 0, 0, 0.36);
    animation: sptBreath 3.2s ease-in-out infinite;
}

@keyframes sptBreath {
    0%, 100% {
        box-shadow:
            0 0 0 1px rgba(32, 230, 255, 0.08) inset,
            0 0 18px rgba(32, 230, 255, 0.18),
            0 18px 44px rgba(0, 0, 0, 0.32);
    }
    50% {
        box-shadow:
            0 0 0 1px rgba(32, 230, 255, 0.16) inset,
            0 0 34px rgba(32, 230, 255, 0.38),
            0 20px 52px rgba(0, 0, 0, 0.42);
    }
}

.spt-logo-wrap {
    flex: 0 0 auto;
    width: 300px;
    height: 92px;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.96);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    box-shadow: 0 0 20px rgba(255,255,255,0.10);
}

.spt-logo-wrap img {
    max-width: 94%;
    max-height: 86%;
    object-fit: contain;
}

.spt-logo-fallback {
    font-size: 2rem;
    letter-spacing: 0.28rem;
    color: #071827;
    font-weight: 900;
}

.spt-header-text {
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.spt-title {
    font-size: clamp(2.0rem, 3.0vw, 3.15rem);
    line-height: 1.12;
    font-weight: 900;
    color: #f5fbff;
    text-shadow: 0 0 14px rgba(190, 245, 255, 0.52);
    letter-spacing: 1px;
    white-space: normal;
}

.spt-subtitle {
    margin-top: 10px;
    font-size: clamp(0.98rem, 1.15vw, 1.25rem);
    line-height: 1.4;
    color: #c4d9e8;
    font-weight: 700;
    letter-spacing: 0.2px;
}

/* ===== KPI / Cards ===== */
.spt-card-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(180px, 1fr));
    gap: 16px;
    margin: 18px 0 28px 0;
}

.spt-kpi-card, .spt-module-card {
    border: 1px solid rgba(32, 230, 255, 0.28);
    border-radius: 16px;
    background: rgba(8, 27, 45, 0.84);
    padding: 18px 20px;
    box-shadow: 0 0 18px rgba(32, 230, 255, 0.08);
}

.spt-kpi-label, .spt-module-desc {
    font-size: 0.92rem;
    color: #b9cddd;
    font-weight: 700;
}

.spt-kpi-value {
    font-size: 2.0rem;
    color: #ffffff;
    font-weight: 900;
    margin-top: 6px;
}

.spt-module-no {
    color: #20e6ff;
    font-size: 0.95rem;
    font-weight: 900;
    margin-bottom: 4px;
}

.spt-module-name {
    font-size: 1.32rem;
    color: #ffffff;
    font-weight: 900;
    margin-bottom: 8px;
}

.spt-module-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(220px, 1fr));
    gap: 18px;
    margin-top: 16px;
}

.spt-module-card {
    min-height: 112px;
}

/* ===== Inputs: light background + dark text ===== */
.stTextInput input,
.stNumberInput input,
.stPasswordInput input,
.stDateInput input,
.stTimeInput input,
.stTextArea textarea,
textarea,
input[type="text"],
input[type="password"],
input[type="number"] {
    background: var(--spt-input-bg) !important;
    color: var(--spt-input-text) !important;
    border: 1px solid rgba(32, 230, 255, 0.58) !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    caret-color: #071827 !important;
}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: rgba(7, 24, 39, 0.62) !important;
    font-weight: 700 !important;
}

.stTextInput input:focus,
.stNumberInput input:focus,
.stPasswordInput input:focus,
.stDateInput input:focus,
.stTimeInput input:focus,
.stTextArea textarea:focus {
    box-shadow: 0 0 0 1px rgba(32,230,255,0.75), 0 0 18px rgba(32,230,255,0.32) !important;
}

/* Selectbox closed state */
div[data-baseweb="select"] > div {
    background: var(--spt-input-bg) !important;
    color: var(--spt-input-text) !important;
    border: 1px solid rgba(32, 230, 255, 0.58) !important;
    border-radius: 12px !important;
}

div[data-baseweb="select"] > div * {
    color: var(--spt-input-text) !important;
    font-weight: 800 !important;
}

/* Select dropdown opened state */
div[data-baseweb="popover"],
div[data-baseweb="popover"] > div,
ul[role="listbox"] {
    background: #061827 !important;
    border: 1px solid rgba(32, 230, 255, 0.45) !important;
    border-radius: 10px !important;
    box-shadow: 0 18px 40px rgba(0,0,0,0.48), 0 0 18px rgba(32,230,255,0.18) !important;
}

ul[role="listbox"] li,
ul[role="listbox"] li *,
div[role="option"],
div[role="option"] * {
    background: transparent !important;
    color: #f4fbff !important;
    font-weight: 850 !important;
}

ul[role="listbox"] li:hover,
div[role="option"]:hover {
    background: rgba(32, 230, 255, 0.18) !important;
}

ul[role="listbox"] li[aria-selected="true"],
div[role="option"][aria-selected="true"] {
    background: #22e5f5 !important;
}

ul[role="listbox"] li[aria-selected="true"] *,
div[role="option"][aria-selected="true"] * {
    color: #061827 !important;
    font-weight: 900 !important;
}

/* st.data_editor editable cells */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] select {
    background: var(--spt-input-bg) !important;
    color: var(--spt-input-text) !important;
    border-radius: 8px !important;
    font-weight: 850 !important;
}

/* Labels */
.stTextInput label, .stTextArea label, .stSelectbox label,
.stMultiSelect label, .stDateInput label, .stTimeInput label,
.stNumberInput label, .stPasswordInput label {
    color: #effaff !important;
    font-weight: 800 !important;
}

/* Buttons */
.stButton > button {
    border: 1px solid rgba(32, 230, 255, 0.55) !important;
    background: rgba(7, 55, 82, 0.70) !important;
    color: #f4fbff !important;
    border-radius: 12px !important;
    font-weight: 850 !important;
    min-height: 42px !important;
    box-shadow: 0 0 14px rgba(32,230,255,0.10) !important;
}

.stButton > button:hover {
    border-color: rgba(32, 230, 255, 0.92) !important;
    box-shadow: 0 0 20px rgba(32,230,255,0.28) !important;
}

/* Dataframe headers */
[data-testid="stDataFrame"] div[role="columnheader"],
[data-testid="stDataEditor"] div[role="columnheader"] {
    background: rgba(255, 255, 255, 0.07) !important;
    color: #f4fbff !important;
    font-weight: 850 !important;
}



/* ===== V1.56 Sidebar Restore: larger font + breathing glow ===== */
[data-testid="stSidebar"] {
    background:
        radial-gradient(circle at 20% 8%, rgba(32,230,255,0.11), transparent 34%),
        linear-gradient(180deg, rgba(4, 12, 25, 0.99), rgba(5, 20, 36, 0.99)) !important;
    border-right: 1px solid rgba(32, 230, 255, 0.34) !important;
    box-shadow:
        10px 0 30px rgba(0, 0, 0, 0.34),
        0 0 22px rgba(32, 230, 255, 0.12) !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarHeader"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    color: #f4fbff !important;
}

[data-testid="stSidebarNav"] {
    padding-top: 0.5rem !important;
}

[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNav"] li a,
[data-testid="stSidebarNav"] a span,
[data-testid="stSidebarNav"] a p,
[data-testid="stSidebarNav"] li span,
[data-testid="stSidebarNav"] li p {
    color: #f4fbff !important;
    font-size: 1.14rem !important;
    font-weight: 900 !important;
    letter-spacing: 0.25px !important;
    text-shadow: 0 0 8px rgba(190, 245, 255, 0.18) !important;
}

[data-testid="stSidebarNav"] a {
    min-height: 42px !important;
    padding: 10px 14px !important;
    margin: 7px 10px !important;
    border-radius: 13px !important;
    border: 1px solid rgba(32, 230, 255, 0.00) !important;
    transition: all 0.18s ease-in-out !important;
}

[data-testid="stSidebarNav"] a:hover {
    background: linear-gradient(90deg, rgba(32,230,255,0.18), rgba(98,70,190,0.20)) !important;
    border-color: rgba(32,230,255,0.28) !important;
    box-shadow:
        0 0 14px rgba(32,230,255,0.22),
        inset 0 0 12px rgba(32,230,255,0.08) !important;
    transform: translateX(1px) !important;
}

[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNav"] li div[aria-current="page"],
[data-testid="stSidebarNav"] li:has(a[aria-current="page"]) a {
    background: linear-gradient(90deg, rgba(28, 208, 230, 0.42), rgba(92, 65, 190, 0.68)) !important;
    border-left: 4px solid #20e6ff !important;
    border-top: 1px solid rgba(32,230,255,0.38) !important;
    border-bottom: 1px solid rgba(32,230,255,0.18) !important;
    box-shadow:
        0 0 16px rgba(32, 230, 255, 0.42),
        0 0 34px rgba(108, 75, 210, 0.18),
        inset 0 0 16px rgba(32,230,255,0.12) !important;
    animation: sptSidebarBreath 2.8s ease-in-out infinite !important;
}

[data-testid="stSidebarNav"] a[aria-current="page"] span,
[data-testid="stSidebarNav"] a[aria-current="page"] p,
[data-testid="stSidebarNav"] li:has(a[aria-current="page"]) a span,
[data-testid="stSidebarNav"] li:has(a[aria-current="page"]) a p {
    color: #ffffff !important;
    text-shadow: 0 0 10px rgba(255,255,255,0.40), 0 0 18px rgba(32,230,255,0.26) !important;
}

@keyframes sptSidebarBreath {
    0%, 100% {
        box-shadow:
            0 0 12px rgba(32,230,255,0.28),
            0 0 24px rgba(108,75,210,0.12),
            inset 0 0 12px rgba(32,230,255,0.08);
    }
    50% {
        box-shadow:
            0 0 22px rgba(32,230,255,0.50),
            0 0 38px rgba(108,75,210,0.24),
            inset 0 0 18px rgba(32,230,255,0.16);
    }
}

/* Sidebar collapse arrow and app label clarity */
[data-testid="stSidebar"] button,
[data-testid="stSidebar"] button * {
    color: #f4fbff !important;
}

[data-testid="stSidebar"] small,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div {
    font-weight: 800 !important;
}

@media (max-width: 900px) {
    .spt-header { flex-direction: column; align-items: flex-start; }
    .spt-logo-wrap { width: 260px; }
    .spt-card-grid, .spt-module-grid { grid-template-columns: 1fr; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


# 舊版函式相容：有些頁面 import app_theme
app_theme = apply_theme


def _logo_html() -> str:
    b64 = _read_logo_base64()
    if b64:
        return f'<img src="data:image/png;base64,{b64}" alt="Super Plus Tech Logo" />'
    return '<div class="spt-logo-fallback">SPT</div>'


def render_home_header(
    title: str = "超慧科技製造部｜智慧工時紀錄系統",
    subtitle: str = "Super Plus Tech Manufacturing Time Tracking System | Streamlit + SQLite + Github Cloud Storage",
    *args: Any,
    **kwargs: Any,
) -> None:
    """首頁標題。"""
    apply_theme()
    st.markdown(
        f"""
<div class="spt-header">
  <div class="spt-logo-wrap">{_logo_html()}</div>
  <div class="spt-header-text">
    <div class="spt-title">{_html_escape(title)}</div>
    <div class="spt-subtitle">{_html_escape(subtitle)}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_header(
    title: str = "",
    subtitle: str = "",
    module_no: str | int | None = None,
    *args: Any,
    **kwargs: Any,
) -> None:
    """各模組標題。相容多種舊版呼叫方式。"""
    apply_theme()

    # 相容 render_header("01", "工時紀錄", "說明") 這類舊呼叫
    if module_no is None and args:
        # 若 title 很像數字，則 title=module_no, subtitle=module title, args[0]=desc
        t = str(title).strip()
        if t.replace(".", "").isdigit():
            module_no = t
            title = str(subtitle)
            subtitle = str(args[0]) if args else ""

    no = "" if module_no is None else str(module_no).strip()
    clean_title = str(title).strip()
    if no and not clean_title.startswith(no):
        full_title = f"{no}｜{clean_title}"
    else:
        full_title = clean_title or "超慧科技製造部｜智慧工時紀錄系統"

    st.markdown(
        f"""
<div class="spt-header">
  <div class="spt-logo-wrap">{_logo_html()}</div>
  <div class="spt-header-text">
    <div class="spt-title">{_html_escape(full_title)}</div>
    <div class="spt-subtitle">{_html_escape(subtitle)}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_cards(cards: Any = None, *args: Any, **kwargs: Any) -> None:
    """
    首頁 KPI 卡片。
    相容：
    - list[dict]: [{"label": "...", "value": "..."}]
    - list[tuple]: [("label", "value")]
    - dict: {"label": "value"}
    """
    apply_theme()
    if cards is None:
        cards = [
            {"label": "核心模組 / Modules", "value": "12"},
            {"label": "資料庫 / Database", "value": "SQLite"},
            {"label": "雲端保存 / Cloud", "value": "GitHub"},
            {"label": "系統狀態 / Status", "value": "Online"},
        ]

    normalized: list[tuple[str, str]] = []
    try:
        if isinstance(cards, Mapping):
            normalized = [(str(k), str(v)) for k, v in cards.items()]
        else:
            for item in cards:
                if isinstance(item, Mapping):
                    label = item.get("label") or item.get("title") or item.get("name") or ""
                    value = item.get("value") or item.get("metric") or item.get("count") or ""
                    normalized.append((str(label), str(value)))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    normalized.append((str(item[0]), str(item[1])))
    except Exception:
        normalized = []

    if not normalized:
        normalized = [("系統狀態 / Status", "Online")]

    html = ['<div class="spt-card-grid">']
    for label, value in normalized:
        html.append(
            f"""
<div class="spt-kpi-card">
  <div class="spt-kpi-label">{_html_escape(label)}</div>
  <div class="spt-kpi-value">{_html_escape(value)}</div>
</div>
            """
        )
    html.append("</div>")
    st.markdown("\n".join(html), unsafe_allow_html=True)


def render_module_cards(modules: Any = None, *args: Any, **kwargs: Any) -> None:
    """首頁模組卡片。"""
    apply_theme()
    if modules is None:
        modules = [
            ("01", "工時紀錄", "快速開始、同步作業、暫停、下班、完工與工時計算"),
            ("02", "歷史紀錄", "完整工時明細查詢、編輯、儲存與 Excel 匯出"),
            ("03", "製令管理", "Excel 匯入、貼上資料、手動新增與製令主檔維護"),
            ("04", "人員名單", "人員主檔、在廠狀態、今日出勤勾選與清單維護"),
            ("05", "製令工時分析", "製令累積工時、工段分析與明細查詢"),
            ("06", "LOG查詢", "系統操作、異常與資料異動紀錄查詢"),
            ("07", "今日未紀錄名單", "出勤但未登錄工時的人員即時提示"),
            ("08", "人員每日工時", "每日累積工時、合理區間與異常提醒"),
            ("09", "資料永久保存與備份", "永久檔、GitHub 雲端保存與還原"),
            ("10", "權限管理", "帳號、角色與模組權限設定"),
            ("11", "登入紀錄", "登入、登出、閒置與權限事件查詢"),
            ("12", "模組永久紀錄中心", "各模組獨立永久紀錄與設定檔管理"),
        ]

    normalized: list[tuple[str, str, str]] = []
    try:
        for idx, item in enumerate(modules, start=1):
            if isinstance(item, Mapping):
                no = str(item.get("no") or item.get("module_no") or f"{idx:02d}")
                name = str(item.get("name") or item.get("title") or "")
                desc = str(item.get("desc") or item.get("description") or "")
                normalized.append((no, name, desc))
            elif isinstance(item, (list, tuple)):
                no = str(item[0]) if len(item) > 0 else f"{idx:02d}"
                name = str(item[1]) if len(item) > 1 else ""
                desc = str(item[2]) if len(item) > 2 else ""
                normalized.append((no, name, desc))
    except Exception:
        normalized = []

    html = ['<div class="spt-module-grid">']
    for no, name, desc in normalized:
        html.append(
            f"""
<div class="spt-module-card">
  <div class="spt-module-no">{_html_escape(no)}</div>
  <div class="spt-module-name">{_html_escape(name)}</div>
  <div class="spt-module-desc">{_html_escape(desc)}</div>
</div>
            """
        )
    html.append("</div>")
    st.markdown("\n".join(html), unsafe_allow_html=True)


def render_page_title(*args: Any, **kwargs: Any) -> None:
    """部分舊頁可能使用此名稱。"""
    render_header(*args, **kwargs)


def spt_divider() -> None:
    st.markdown(
        '<hr style="border:0;border-top:1px solid rgba(32,230,255,0.18);margin:26px 0;">',
        unsafe_allow_html=True,
    )
