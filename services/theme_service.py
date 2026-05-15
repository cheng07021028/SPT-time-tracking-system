# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Unified Theme Service
V1.52
- Restore Super Plus Tech logo rendering.
- Prevent raw <div> HTML text from appearing.
- Restore unified module header style.
- Restore sidebar visual style.
- Keep backward compatible functions used by older pages.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Iterable

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "data" / "logo" / "logo.png",
]


def _file_to_base64(path: Path) -> str:
    try:
        if path.exists() and path.is_file():
            return base64.b64encode(path.read_bytes()).decode("utf-8")
    except Exception:
        pass
    return ""


def _logo_base64() -> str:
    for p in LOGO_CANDIDATES:
        b64 = _file_to_base64(p)
        if b64:
            return b64
    return ""


def _logo_html() -> str:
    b64 = _logo_base64()
    if b64:
        return f'<img class="spt-logo-img" src="data:image/png;base64,{b64}" alt="Super Plus Tech Logo" />'
    return '<div class="spt-logo-fallback">SPT</div>'


def apply_theme() -> None:
    """Apply global dark-tech theme and component fixes."""
    st.markdown(
        """
<style>
:root {
    --spt-bg-0: #050b18;
    --spt-bg-1: #071626;
    --spt-bg-2: #09233a;
    --spt-card: rgba(8, 28, 48, 0.86);
    --spt-card-2: rgba(10, 43, 70, 0.72);
    --spt-cyan: #23e6ff;
    --spt-cyan-soft: rgba(35, 230, 255, 0.32);
    --spt-blue: #3ea7ff;
    --spt-purple: #5431a8;
    --spt-text: #f2fbff;
    --spt-muted: rgba(226, 243, 255, .72);
    --spt-border: rgba(35, 230, 255, .42);
}

/* App background */
.stApp {
    background:
        radial-gradient(circle at 12% 10%, rgba(78, 47, 163, .28), transparent 28%),
        radial-gradient(circle at 88% 0%, rgba(20, 166, 210, .20), transparent 28%),
        linear-gradient(135deg, #06091a 0%, #071728 48%, #081d2d 100%) !important;
    color: var(--spt-text) !important;
}

/* Main block width and spacing */
.block-container {
    padding-top: 2.0rem !important;
    padding-bottom: 3rem !important;
    max-width: 1680px !important;
}

/* Hide Streamlit default noise a bit */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* Typography */
html, body, [class*="css"], .stMarkdown, .stText, p, label, span, div {
    font-family: "Microsoft JhengHei", "Noto Sans TC", "Segoe UI", Arial, sans-serif;
}

h1, h2, h3 {
    color: var(--spt-text) !important;
    letter-spacing: .4px;
}

/* ===== Unified SPT header ===== */
.spt-header-wrap {
    width: 100%;
    margin: 1.0rem 0 1.55rem 0;
    padding: 1.25rem 1.45rem;
    border: 1px solid var(--spt-border);
    border-radius: 20px;
    background:
        linear-gradient(105deg, rgba(4, 17, 33, .96), rgba(9, 78, 104, .72) 74%, rgba(3, 31, 53, .86)),
        radial-gradient(circle at 14% 0%, rgba(35, 230, 255, .22), transparent 34%);
    box-shadow:
        0 0 0 1px rgba(35, 230, 255, .08) inset,
        0 0 22px rgba(35, 230, 255, .20),
        0 0 52px rgba(51, 88, 255, .10);
    animation: sptBreath 3.8s ease-in-out infinite;
}

.spt-header-inner {
    display: flex;
    align-items: center;
    gap: 2.0rem;
}

.spt-logo-box {
    width: 285px;
    min-width: 230px;
    height: 96px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 14px;
    background: rgba(255, 255, 255, .96);
    box-shadow:
        0 8px 18px rgba(0, 0, 0, .22),
        0 0 18px rgba(255, 255, 255, .12);
    overflow: hidden;
}

.spt-logo-img {
    max-width: 93%;
    max-height: 82%;
    object-fit: contain;
}

.spt-logo-fallback {
    font-size: 2.0rem;
    letter-spacing: 10px;
    font-weight: 900;
    color: #071728;
}

.spt-header-text {
    min-width: 0;
    flex: 1;
}

.spt-header-title {
    color: #f6fbff;
    font-size: 2.55rem;
    line-height: 1.15;
    font-weight: 900;
    letter-spacing: .8px;
    text-shadow:
        0 0 10px rgba(255,255,255,.26),
        0 0 22px rgba(35,230,255,.28);
    white-space: nowrap;
}

.spt-header-subtitle {
    color: rgba(230, 243, 255, .74);
    margin-top: .45rem;
    font-size: 1.08rem;
    font-weight: 650;
    letter-spacing: .15px;
}

@keyframes sptBreath {
    0%, 100% {
        box-shadow:
            0 0 0 1px rgba(35, 230, 255, .08) inset,
            0 0 18px rgba(35, 230, 255, .16),
            0 0 46px rgba(51, 88, 255, .09);
    }
    50% {
        box-shadow:
            0 0 0 1px rgba(35, 230, 255, .18) inset,
            0 0 28px rgba(35, 230, 255, .32),
            0 0 70px rgba(51, 88, 255, .18);
    }
}

/* ===== KPI / Cards ===== */
.spt-kpi-grid, .spt-module-grid {
    display: grid;
    gap: 1rem;
    margin: 1rem 0 1.5rem 0;
}
.spt-kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.spt-module-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }

.spt-kpi-card, .spt-module-card {
    border: 1px solid rgba(35, 230, 255, .28);
    border-radius: 14px;
    background: rgba(6, 22, 39, .78);
    padding: 1.08rem 1.15rem;
    box-shadow: 0 0 18px rgba(35, 230, 255, .08);
}
.spt-kpi-label, .spt-module-desc {
    color: rgba(232, 246, 255, .70);
    font-weight: 650;
    font-size: .95rem;
}
.spt-kpi-value {
    color: #fff;
    font-size: 2rem;
    font-weight: 850;
    margin-top: .35rem;
}
.spt-module-name {
    color: #fff;
    font-size: 1.45rem;
    font-weight: 900;
    margin-bottom: .45rem;
}

/* ===== Sidebar restore ===== */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #071223 0%, #071827 52%, #06111d 100%) !important;
    border-right: 1px solid rgba(35, 230, 255, .18);
}

section[data-testid="stSidebar"] * {
    color: #f1fbff !important;
    font-weight: 760 !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
section[data-testid="stSidebar"] a {
    font-size: 1.02rem !important;
    border-radius: 10px !important;
    margin: .18rem .25rem !important;
    padding: .42rem .55rem !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
    background: rgba(35, 230, 255, .10) !important;
}

section[data-testid="stSidebar"] [aria-current="page"],
section[data-testid="stSidebar"] a[aria-current="page"] {
    background: linear-gradient(90deg, rgba(35, 230, 255, .34), rgba(80, 45, 150, .58)) !important;
    box-shadow: 0 0 16px rgba(35, 230, 255, .20) !important;
}

/* ===== Buttons ===== */
.stButton > button, button[kind="primary"], button[kind="secondary"] {
    border-radius: 11px !important;
    border: 1px solid rgba(35, 230, 255, .55) !important;
    background: rgba(8, 61, 91, .68) !important;
    color: #f7fdff !important;
    font-weight: 800 !important;
    box-shadow: 0 0 12px rgba(35, 230, 255, .10) !important;
}
.stButton > button:hover {
    border-color: rgba(35, 230, 255, .92) !important;
    box-shadow: 0 0 22px rgba(35, 230, 255, .22) !important;
}

/* ===== Inputs: light background + dark text ===== */
div[data-baseweb="input"] input,
div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea,
textarea,
input[type="text"],
input[type="password"],
input[type="number"] {
    background: rgba(245, 250, 255, 0.95) !important;
    color: #071827 !important;
    -webkit-text-fill-color: #071827 !important;
    caret-color: #071827 !important;
    border: 1px solid rgba(80, 220, 255, .62) !important;
    border-radius: 11px !important;
    font-weight: 800 !important;
}

/* Select input collapsed */
div[data-baseweb="select"] > div {
    background: rgba(245, 250, 255, .95) !important;
    border: 1px solid rgba(80, 220, 255, .62) !important;
    border-radius: 11px !important;
}
div[data-baseweb="select"] > div * {
    color: #071827 !important;
    -webkit-text-fill-color: #071827 !important;
    font-weight: 820 !important;
}

/* Select dropdown menu: dark bg + light text */
div[data-baseweb="popover"],
div[data-baseweb="popover"] > div,
ul[role="listbox"],
div[role="listbox"] {
    background: #061522 !important;
    border: 1px solid rgba(35, 230, 255, .42) !important;
    box-shadow: 0 14px 34px rgba(0,0,0,.45), 0 0 22px rgba(35,230,255,.16) !important;
}
ul[role="listbox"] li,
div[role="option"],
div[data-baseweb="menu"] li,
div[data-baseweb="menu"] div {
    color: #f4fbff !important;
    -webkit-text-fill-color: #f4fbff !important;
    background: #061522 !important;
    font-weight: 850 !important;
}
ul[role="listbox"] li:hover,
div[role="option"]:hover,
div[aria-selected="true"] {
    background: #26e6ff !important;
    color: #061522 !important;
    -webkit-text-fill-color: #061522 !important;
    font-weight: 900 !important;
}

/* Data editor editing widgets */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea {
    background: rgba(245, 250, 255, .96) !important;
    color: #071827 !important;
    -webkit-text-fill-color: #071827 !important;
    font-weight: 850 !important;
}

/* Tables */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: 1px solid rgba(35, 230, 255, .32) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* Expander */
.streamlit-expanderHeader {
    color: #f1fbff !important;
    font-weight: 850 !important;
    border-radius: 10px !important;
}

/* Responsive */
@media (max-width: 1100px) {
    .spt-header-inner { gap: 1rem; }
    .spt-logo-box { width: 220px; min-width: 190px; height: 78px; }
    .spt-header-title { font-size: 2.0rem; white-space: normal; }
    .spt-kpi-grid, .spt-module-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def app_theme() -> None:
    """Backward compatible alias."""
    apply_theme()


def render_header(title: str, subtitle: str = "", module_no: str | int | None = None, **_: Any) -> None:
    """Render unified module header. Always uses unsafe_allow_html=True."""
    apply_theme()

    no = ""
    if module_no is not None and str(module_no).strip():
        raw = str(module_no).strip()
        no = raw.zfill(2) if raw.isdigit() else raw

    if no:
        header_title = f"{no}｜{title}"
    else:
        header_title = str(title)

    st.markdown(
        f"""
<div class="spt-header-wrap">
  <div class="spt-header-inner">
    <div class="spt-logo-box">{_logo_html()}</div>
    <div class="spt-header-text">
      <div class="spt-header-title">{header_title}</div>
      <div class="spt-header-subtitle">{subtitle or ""}</div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_home_header(
    title: str = "超慧科技製造部｜智慧工時紀錄系統",
    subtitle: str = "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + GitHub Cloud Storage",
    **_: Any,
) -> None:
    """Home page header."""
    render_header(title=title, subtitle=subtitle, module_no=None)


def render_kpi_cards(items: Any | None = None, **_: Any) -> None:
    """Render KPI cards. Accepts list[dict], dict, or None."""
    if not items:
        items = [
            {"label": "核心模組 / Modules", "value": "12"},
            {"label": "資料庫 / Database", "value": "SQLite"},
            {"label": "雲端保存 / Cloud Storage", "value": "GitHub"},
            {"label": "系統狀態 / Status", "value": "Online"},
        ]

    if isinstance(items, dict):
        items = [{"label": k, "value": v} for k, v in items.items()]

    html = ['<div class="spt-kpi-grid">']
    for item in items:
        label = str(item.get("label", ""))
        value = str(item.get("value", ""))
        html.append(f"""
<div class="spt-kpi-card">
  <div class="spt-kpi-label">{label}</div>
  <div class="spt-kpi-value">{value}</div>
</div>
""")
    html.append("</div>")
    st.markdown("\n".join(html), unsafe_allow_html=True)


def render_module_cards(modules: Any | None = None, **_: Any) -> None:
    """Render home module cards. Kept for streamlit_app.py compatibility."""
    if not modules:
        modules = [
            ("01. 工時紀錄", "快速開始、暫停、下班、完工與工時計算"),
            ("02. 歷史紀錄", "完整工時明細查詢、編輯、儲存與匯出"),
            ("03. 製令管理", "Excel 匯入、貼上資料、頁面編輯與儲存"),
            ("04. 人員名單", "人員主檔、在廠狀態、今日出勤勾選"),
            ("05. 製令工時分析", "製令、工段、人員累積工時分析"),
            ("06. LOG查詢", "系統操作、異常與資料異動紀錄"),
            ("07. 今日未紀錄名單", "出勤但未登錄工時的人員即時提示"),
            ("08. 人員每日工時", "每日累積工時、合理區間與異常提醒"),
            ("09. 資料永久保存與備份", "GitHub 雲端永久保存、還原與防遺失"),
            ("10. 權限管理", "帳號、密碼、角色與模組權限設定"),
            ("11. 登入紀錄", "登入、登出、權限不足與安全事件查詢"),
            ("12. 模組永久紀錄中心", "各模組獨立紀錄檔、設定檔與歷史備份"),
        ]

    html = ['<div class="spt-module-grid">']
    for mod in modules:
        if isinstance(mod, dict):
            name = str(mod.get("name") or mod.get("title") or "")
            desc = str(mod.get("desc") or mod.get("description") or "")
        else:
            name = str(mod[0]) if len(mod) > 0 else ""
            desc = str(mod[1]) if len(mod) > 1 else ""
        html.append(f"""
<div class="spt-module-card">
  <div class="spt-module-name">{name}</div>
  <div class="spt-module-desc">{desc}</div>
</div>
""")
    html.append("</div>")
    st.markdown("\n".join(html), unsafe_allow_html=True)


def render_section_title(title: str, subtitle: str = "") -> None:
    st.markdown(f"### {title}")
    if subtitle:
        st.caption(subtitle)


# Additional backward-compatible names used by earlier patches
def render_page_header(title: str, subtitle: str = "", module_no: str | int | None = None, **kwargs: Any) -> None:
    render_header(title=title, subtitle=subtitle, module_no=module_no, **kwargs)


def spt_header(title: str, subtitle: str = "", module_no: str | int | None = None, **kwargs: Any) -> None:
    render_header(title=title, subtitle=subtitle, module_no=module_no, **kwargs)


def inject_global_css() -> None:
    apply_theme()
