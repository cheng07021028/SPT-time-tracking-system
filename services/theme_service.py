# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Unified Theme Service V1.59
Purpose:
- Restore unified Super Plus Tech logo header style.
- Force sidebar/page/menu font size larger and consistent.
- Fix module header ordering: 01｜工時紀錄, 11｜登入紀錄, 12｜模組永久紀錄中心.
- Preserve light input fields and readable dropdown contrast.
This file is self-contained and keeps backward-compatible function names used by old pages.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Iterable

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATHS = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    Path("data/logo/super_plus_logo.png"),
]

MODULE_TITLES = {
    "01": ("工時紀錄", "快速開始、同步作業、暫停、下班、完工與工時計算"),
    "02": ("歷史紀錄", "完整工時明細查詢、編輯、儲存與 Excel 匯出"),
    "03": ("製令管理", "Excel 匯入、貼上資料、手動新增、頁面編輯、刪除、全選與存檔"),
    "04": ("人員名單", "人員主檔、在廠狀態、今日出勤勾選、清單編輯、刪除與儲存"),
    "05": ("製令工時分析", "製令、工段、人員累積工時分析與明細"),
    "06": ("LOG查詢", "系統操作、異常與資料異動紀錄查詢"),
    "07": ("今日未紀錄名單", "出勤但尚未登工時的人員即時提示"),
    "08": ("人員每日工時", "每日累積工時、合理區間與異常提醒"),
    "09": ("資料永久保存與備份", "JSON 備份、GitHub 雲端永久保存與還原"),
    "10": ("權限管理", "帳號、角色、模組權限與閒置自動登出設定"),
    "11": ("登入紀錄", "登入、登出、閒置自動登出、權限不足與安全事件查詢"),
    "12": ("模組永久紀錄中心", "每個模組獨立 records、settings、audit 與 history 時間戳備份"),
}

MODULE_DESC_TO_NO = {
    "工時紀錄": "01", "歷史紀錄": "02", "製令管理": "03", "人員名單": "04",
    "製令工時分析": "05", "LOG查詢": "06", "今日未紀錄名單": "07", "人員每日工時": "08",
    "資料永久保存與備份": "09", "權限管理": "10", "登入紀錄": "11", "模組永久紀錄中心": "12",
}


def _logo_base64() -> str:
    for p in LOGO_PATHS:
        try:
            if p.exists():
                return base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception:
            pass
    return ""


def _safe_html(text: Any) -> str:
    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _normalize_module(module_no: Any = None, title: Any = None, subtitle: Any = None) -> tuple[str, str, str]:
    """Accept old/new call styles and always return module_no, title, subtitle."""
    a = "" if module_no is None else str(module_no).strip()
    b = "" if title is None else str(title).strip()
    c = "" if subtitle is None else str(subtitle).strip()

    # Old call style may be render_header(title, subtitle, module_no)
    # or render_header(module_no, title, subtitle). Normalize both.
    candidates = [a, b, c]
    found_no = ""
    for x in candidates:
        xx = x.replace("｜", "|").strip()
        if xx.isdigit() and len(xx) <= 2:
            found_no = xx.zfill(2)
            break
        if len(xx) >= 2 and xx[:2].isdigit():
            found_no = xx[:2]
            break

    # If any argument contains a known module title, use that module number.
    found_title = ""
    for x in candidates:
        for t, no in MODULE_DESC_TO_NO.items():
            if t in x:
                found_no = found_no or no
                found_title = t
                break
        if found_title:
            break

    if found_no in MODULE_TITLES:
        default_title, default_subtitle = MODULE_TITLES[found_no]
        # Prefer official title for consistency.
        final_title = default_title
        # Prefer an explicit non-number, non-title long description as subtitle.
        possible_subtitles = []
        for x in candidates:
            if not x:
                continue
            xx = x.replace("｜", "|").strip()
            if xx.isdigit() or (len(xx) >= 2 and xx[:2].isdigit()):
                continue
            if x == default_title or default_title in x:
                continue
            if x in MODULE_DESC_TO_NO:
                continue
            possible_subtitles.append(x)
        final_subtitle = possible_subtitles[-1] if possible_subtitles else default_subtitle
        return found_no, final_title, final_subtitle

    # Fallback for home or unknown custom page.
    final_title = b or a or "超慧科技製造部｜智慧工時紀錄系統"
    final_subtitle = c or "Super Plus Tech Manufacturing Time Tracking System"
    return "", final_title, final_subtitle


def _inject_css() -> None:
    st.markdown(
        """
<style>
:root {
    --spt-bg: #06111f;
    --spt-panel: rgba(7, 31, 50, 0.82);
    --spt-panel-2: rgba(6, 52, 75, 0.88);
    --spt-cyan: #23e6ff;
    --spt-cyan-soft: rgba(35, 230, 255, 0.55);
    --spt-text: #f4fbff;
    --spt-muted: #b8cad7;
}
html, body, [data-testid="stAppViewContainer"] {
    background: radial-gradient(circle at 12% 18%, rgba(64, 35, 130, 0.20), transparent 36%),
                linear-gradient(115deg, #070b1d 0%, #071522 45%, #062238 100%) !important;
    color: var(--spt-text) !important;
}
[data-testid="stHeader"] { background: rgba(4, 12, 23, 0.84) !important; }
.block-container { padding-top: 1.45rem !important; max-width: 1800px !important; }

/* ===== Sidebar: bigger font, smaller row gap, breathing glow ===== */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #071525 0%, #06111f 58%, #04101d 100%) !important;
    border-right: 1px solid rgba(35, 230, 255, 0.22) !important;
}
section[data-testid="stSidebar"] * {
    font-size: 17px !important;
    letter-spacing: .2px !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
    padding-top: 0.35rem !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li {
    margin: 2px 0 !important;
    padding: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
section[data-testid="stSidebar"] a,
section[data-testid="stSidebar"] [role="link"] {
    min-height: 34px !important;
    padding: 5px 12px !important;
    margin: 1px 7px !important;
    border-radius: 12px !important;
    color: #f6fbff !important;
    font-size: 17px !important;
    font-weight: 850 !important;
    text-shadow: 0 0 8px rgba(230, 250, 255, .30) !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover,
section[data-testid="stSidebar"] a:hover,
section[data-testid="stSidebar"] [role="link"]:hover {
    background: linear-gradient(90deg, rgba(0, 211, 255, .22), rgba(111, 62, 255, .34)) !important;
    box-shadow: 0 0 16px rgba(35,230,255,.42) !important;
    color: #ffffff !important;
}
section[data-testid="stSidebar"] [aria-current="page"],
section[data-testid="stSidebar"] a[aria-current="page"] {
    background: linear-gradient(90deg, rgba(0, 207, 255, .45), rgba(112, 61, 255, .62)) !important;
    box-shadow: 0 0 0 1px rgba(35,230,255,.75), 0 0 18px rgba(35,230,255,.50), 0 0 30px rgba(112,61,255,.30) !important;
    color: #ffffff !important;
    animation: sptSidebarBreath 2.4s ease-in-out infinite !important;
}
@keyframes sptSidebarBreath {
    0%, 100% { box-shadow: 0 0 0 1px rgba(35,230,255,.55), 0 0 12px rgba(35,230,255,.34), 0 0 22px rgba(112,61,255,.20); }
    50% { box-shadow: 0 0 0 1px rgba(35,230,255,.95), 0 0 24px rgba(35,230,255,.68), 0 0 44px rgba(112,61,255,.42); }
}

/* ===== Header ===== */
.spt-header-wrap {
    position: relative;
    display: flex;
    align-items: center;
    gap: 28px;
    padding: 26px 32px;
    margin: 18px 0 24px 0;
    border: 1px solid rgba(35, 230, 255, .58);
    border-radius: 24px;
    background: linear-gradient(100deg, rgba(4,18,32,.92), rgba(6,73,98,.74), rgba(5,29,48,.92));
    box-shadow: 0 0 0 1px rgba(35,230,255,.10) inset, 0 0 22px rgba(35,230,255,.20), 0 0 42px rgba(88,51,255,.10);
    overflow: hidden;
    animation: sptHeaderBreath 3s ease-in-out infinite;
}
.spt-header-wrap::after {
    content: "";
    position: absolute; inset: -2px;
    background: radial-gradient(circle at 18% 22%, rgba(35,230,255,.16), transparent 30%), radial-gradient(circle at 85% 80%, rgba(88,51,255,.16), transparent 32%);
    pointer-events: none;
}
@keyframes sptHeaderBreath {
    0%,100% { box-shadow: 0 0 0 1px rgba(35,230,255,.14) inset, 0 0 20px rgba(35,230,255,.20), 0 0 44px rgba(88,51,255,.10); }
    50% { box-shadow: 0 0 0 1px rgba(35,230,255,.32) inset, 0 0 32px rgba(35,230,255,.42), 0 0 70px rgba(88,51,255,.22); }
}
.spt-header-logo {
    position: relative; z-index: 1;
    width: 260px; min-width: 220px; max-width: 300px;
    background: rgba(255,255,255,.96);
    border-radius: 16px;
    padding: 10px 18px;
    box-shadow: 0 12px 28px rgba(0,0,0,.24);
}
.spt-header-logo img { width: 100%; height: auto; display: block; }
.spt-header-main { position: relative; z-index: 1; }
.spt-header-title {
    font-size: 40px !important;
    line-height: 1.12 !important;
    font-weight: 950 !important;
    color: #f7fcff !important;
    text-shadow: 0 0 12px rgba(255,255,255,.25), 0 0 24px rgba(35,230,255,.26) !important;
    letter-spacing: 1px !important;
    margin: 0 0 8px 0 !important;
}
.spt-header-subtitle {
    font-size: 18px !important;
    font-weight: 700 !important;
    color: rgba(235,248,255,.80) !important;
    text-shadow: 0 0 8px rgba(35,230,255,.15) !important;
}
.spt-header-no { color: #72f6ff; margin-right: 12px; }
.spt-sep { color: rgba(255,255,255,.55); margin: 0 12px; }

/* ===== Module cards / KPI cards: larger and consistent ===== */
.spt-module-grid { display:grid; grid-template-columns: repeat(4, minmax(230px, 1fr)); gap:16px; margin: 16px 0 24px; }
.spt-module-card, .spt-kpi-card {
    border: 1px solid rgba(35,230,255,.28);
    border-radius: 16px;
    padding: 20px 22px;
    background: rgba(6, 22, 36, .72);
    box-shadow: 0 0 18px rgba(35,230,255,.08) inset;
}
.spt-module-no { font-size: 16px; color:#5ef4ff; font-weight:900; margin-bottom:8px; }
.spt-module-title { font-size: 27px; color:#fff; font-weight:950; margin-bottom:8px; text-shadow:0 0 8px rgba(255,255,255,.18); }
.spt-module-desc { font-size: 16px; color:rgba(235,248,255,.78); font-weight:700; line-height:1.55; }
.spt-kpi-label { font-size: 16px; font-weight:850; color:rgba(235,248,255,.85); }
.spt-kpi-value { font-size: 32px; font-weight:950; color:#fff; margin-top:8px; }

/* ===== Inputs: light background + dark text ===== */
div[data-baseweb="input"] input,
div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea,
textarea,
input[type="text"], input[type="password"], input[type="number"], input[type="email"] {
    background: rgba(246, 251, 255, 0.96) !important;
    color: #071523 !important;
    -webkit-text-fill-color: #071523 !important;
    border: 1px solid rgba(84, 218, 255, .72) !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
}
div[data-baseweb="input"] input::placeholder,
div[data-baseweb="textarea"] textarea::placeholder,
textarea::placeholder { color: rgba(35,55,74,.62) !important; -webkit-text-fill-color: rgba(35,55,74,.62) !important; }
div[data-baseweb="input"]:focus-within,
div[data-baseweb="textarea"]:focus-within {
    box-shadow: 0 0 0 1px rgba(35,230,255,.65), 0 0 18px rgba(35,230,255,.28) !important;
    border-radius: 14px !important;
}

/* ===== Select/dropdown contrast ===== */
div[data-baseweb="select"] > div {
    background: rgba(246,251,255,.96) !important;
    color: #071523 !important;
    border: 1px solid rgba(84,218,255,.70) !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
}
div[data-baseweb="select"] span,
div[data-baseweb="select"] input,
div[data-baseweb="select"] div { color: #071523 !important; -webkit-text-fill-color: #071523 !important; font-weight: 800 !important; }
ul[role="listbox"], div[role="listbox"] {
    background: #061423 !important;
    border: 1px solid rgba(35,230,255,.42) !important;
    border-radius: 12px !important;
    box-shadow: 0 10px 28px rgba(0,0,0,.38), 0 0 18px rgba(35,230,255,.16) !important;
}
ul[role="listbox"] li, div[role="option"], div[role="listbox"] * {
    color: #ecfbff !important;
    -webkit-text-fill-color: #ecfbff !important;
    font-weight: 850 !important;
}
ul[role="listbox"] li:hover, div[role="option"]:hover,
ul[role="listbox"] li[aria-selected="true"], div[role="option"][aria-selected="true"] {
    background: #36e7f7 !important;
    color: #04101d !important;
    -webkit-text-fill-color: #04101d !important;
}

/* ===== Data editor editable cell inputs ===== */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] select {
    background: rgba(246,251,255,.98) !important;
    color: #071523 !important;
    -webkit-text-fill-color: #071523 !important;
    border-radius: 8px !important;
    font-weight: 850 !important;
}
[data-testid="stDataEditor"] [role="gridcell"] input { color:#071523 !important; -webkit-text-fill-color:#071523 !important; }

/* Streamlit button consistency */
.stButton > button {
    border: 1px solid rgba(35,230,255,.46) !important;
    background: rgba(3, 61, 87, .62) !important;
    color: #f6fbff !important;
    border-radius: 12px !important;
    font-weight: 850 !important;
    font-size: 16px !important;
}
.stButton > button:hover { box-shadow: 0 0 16px rgba(35,230,255,.38) !important; border-color: rgba(35,230,255,.90) !important; }
</style>
""",
        unsafe_allow_html=True,
    )


def apply_theme() -> None:
    _inject_css()


def app_theme() -> None:
    apply_theme()


def render_header(module_no: Any = None, title: Any = None, subtitle: Any = None) -> None:
    apply_theme()
    no, final_title, final_subtitle = _normalize_module(module_no, title, subtitle)
    logo_b64 = _logo_base64()
    logo_html = (
        f'<img src="data:image/png;base64,{logo_b64}" alt="Super Plus Tech" />'
        if logo_b64 else '<div style="font-size:32px;font-weight:950;color:#06111f;text-align:center;letter-spacing:8px;">SPT</div>'
    )
    title_html = f'<span class="spt-header-no">{_safe_html(no)}</span><span class="spt-sep">｜</span>{_safe_html(final_title)}' if no else _safe_html(final_title)
    st.markdown(
        f"""
<div class="spt-header-wrap">
  <div class="spt-header-logo">{logo_html}</div>
  <div class="spt-header-main">
    <div class="spt-header-title">{title_html}</div>
    <div class="spt-header-subtitle">{_safe_html(final_subtitle)}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_home_header() -> None:
    render_header("", "超慧科技製造部｜智慧工時紀錄系統", "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + GitHub Cloud Storage")


def render_kpi_cards(cards: Iterable[Any] | None = None) -> None:
    apply_theme()
    default_cards = [
        ("核心模組 / Modules", "12"),
        ("資料庫 / Database", "SQLite"),
        ("GitHub 雲端 / Cloud", "Ready"),
        ("系統狀態 / Status", "Online"),
    ]
    cards = list(cards or default_cards)
    html = ['<div class="spt-module-grid">']
    for item in cards:
        if isinstance(item, dict):
            label = item.get("label") or item.get("title") or item.get("name") or ""
            value = item.get("value") or item.get("metric") or item.get("count") or ""
        elif isinstance(item, (list, tuple)):
            label = item[0] if len(item) > 0 else ""
            value = item[1] if len(item) > 1 else ""
        else:
            label, value = str(item), ""
        html.append(f'<div class="spt-kpi-card"><div class="spt-kpi-label">{_safe_html(label)}</div><div class="spt-kpi-value">{_safe_html(value)}</div></div>')
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def render_module_cards(modules: Iterable[Any] | None = None) -> None:
    apply_theme()
    if modules is None:
        modules = [(no, title, subtitle) for no, (title, subtitle) in MODULE_TITLES.items()]
    html = ['<div class="spt-module-grid">']
    for item in modules:
        if isinstance(item, dict):
            no = item.get("no") or item.get("module_no") or item.get("id") or ""
            title = item.get("title") or item.get("name") or ""
            desc = item.get("desc") or item.get("description") or item.get("subtitle") or ""
        elif isinstance(item, (list, tuple)):
            no = item[0] if len(item) > 0 else ""
            title = item[1] if len(item) > 1 else ""
            desc = item[2] if len(item) > 2 else ""
        else:
            no, title, desc = "", str(item), ""
        html.append(
            f'<div class="spt-module-card"><div class="spt-module-no">{_safe_html(no)}</div>'
            f'<div class="spt-module-title">{_safe_html(title)}</div>'
            f'<div class="spt-module-desc">{_safe_html(desc)}</div></div>'
        )
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


# Backward-compatible aliases used by older pages.
def render_page_header(module_no: Any = None, title: Any = None, subtitle: Any = None) -> None:
    render_header(module_no, title, subtitle)


def render_title(module_no: Any = None, title: Any = None, subtitle: Any = None) -> None:
    render_header(module_no, title, subtitle)


def render_section_title(title: str, subtitle: str | None = None) -> None:
    apply_theme()
    st.markdown(f"### {_safe_html(title)}" + (f"\n{_safe_html(subtitle)}" if subtitle else ""))
