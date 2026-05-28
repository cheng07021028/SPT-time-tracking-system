# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Unified Theme Service V1.59 / V2.57 patch
Purpose:
- Restore unified Super Plus Tech logo header style.
- Force sidebar/page/menu font size larger and consistent.
- Fix module header ordering: 01｜工時紀錄, 11｜登入紀錄, 12｜模組永久紀錄中心.
- Preserve light input fields and readable dropdown contrast.
This file is self-contained and keeps backward-compatible function names used by old pages.
"""
from __future__ import annotations

import base64
from datetime import datetime
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
    "13": ("系統設定", "工段名稱、休息時間與跨模組共用設定"),
}

MODULE_DESC_TO_NO = {
    "工時紀錄": "01", "歷史紀錄": "02", "製令管理": "03", "人員名單": "04",
    "製令工時分析": "05", "LOG查詢": "06", "今日未紀錄名單": "07", "人員每日工時": "08",
    "資料永久保存與備份": "09", "權限管理": "10", "登入紀錄": "11", "模組永久紀錄中心": "12",
    "系統設定": "13",
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


/* ===== V1.60 stable UI fixes: user bar, header numbers, module numbers, large inputs ===== */
.block-container { padding-top: 2.6rem !important; }
.spt-user-bar {
    display: grid; grid-template-columns: 1.4fr 1.4fr; gap: 14px; align-items: center;
    min-height: 44px; padding: 10px 14px 6px 14px; margin: 8px 0 14px 0;
    color: rgba(235,248,255,.88); font-size: 16px !important; line-height: 1.55 !important;
    font-weight: 800 !important; letter-spacing: .35px !important;
    text-shadow: 0 0 8px rgba(35,230,255,.14);
}
.spt-user-bar b { color:#ffffff; font-weight:950; }
.spt-user-meta { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.spt-header-no {
    display: inline-block !important; font-size: 44px !important; line-height: 1 !important;
    min-width: 62px !important; text-align: center !important; color: #72f6ff !important;
    font-weight: 1000 !important; margin-right: 10px !important;
    text-shadow: 0 0 12px rgba(114,246,255,.55), 0 0 28px rgba(35,230,255,.25) !important;
}
.spt-module-no { font-size: 21px !important; line-height: 1.05 !important; color:#5ef4ff !important; font-weight:1000 !important; margin-bottom:10px !important; letter-spacing:.6px !important; }
.spt-module-title { font-size: 31px !important; line-height: 1.15 !important; }
.spt-module-desc { font-size: 17px !important; line-height: 1.58 !important; }
.spt-kpi-value { font-size: 38px !important; line-height: 1.1 !important; font-weight: 950 !important; }
.stNumberInput input, div[data-baseweb="input"] input[type="number"] {
    font-size:24px !important; min-height:48px !important; padding-top:8px !important; padding-bottom:8px !important; font-weight:950 !important;
}
.stDateInput input, .stTimeInput input, .stTextInput input, .stTextArea textarea { font-size:18px !important; line-height:1.45 !important; }
div[data-baseweb="popover"] div[role="listbox"], div[data-baseweb="popover"] ul[role="listbox"] { background:#061423 !important; color:#ecfbff !important; }
div[data-baseweb="popover"] div[role="option"], div[data-baseweb="popover"] li[role="option"], div[data-baseweb="popover"] [role="option"] * {
    color:#ecfbff !important; -webkit-text-fill-color:#ecfbff !important; font-size:16px !important; font-weight:850 !important;
}
div[data-baseweb="popover"] div[role="option"][aria-selected="true"], div[data-baseweb="popover"] li[role="option"][aria-selected="true"] {
    background:#36e7f7 !important; color:#04101d !important; -webkit-text-fill-color:#04101d !important;
}


/* ===== V1.61 permanent readability + sizing fixes ===== */
/* 強制所有可輸入區：淺色底、深色字。放在 CSS 最後，避免後續主題覆蓋。 */
.stTextInput input, .stPasswordInput input, .stNumberInput input,
.stTextArea textarea, .stDateInput input, .stTimeInput input,
div[data-baseweb="input"] input, div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea, input, textarea {
    background-color: #f3f9ff !important;
    color: #061423 !important;
    -webkit-text-fill-color: #061423 !important;
    caret-color: #061423 !important;
    font-weight: 850 !important;
}
.stTextInput input::placeholder, .stPasswordInput input::placeholder, .stTextArea textarea::placeholder,
input::placeholder, textarea::placeholder {
    color: rgba(20, 42, 62, .62) !important;
    -webkit-text-fill-color: rgba(20, 42, 62, .62) !important;
}
/* Chrome/Edge autofill 造成深色字消失時強制修正 */
input:-webkit-autofill, input:-webkit-autofill:hover, input:-webkit-autofill:focus {
    -webkit-box-shadow: 0 0 0 1000px #f3f9ff inset !important;
    -webkit-text-fill-color: #061423 !important;
}
/* Data editor 編輯中的儲存格與表格下拉 */
[data-testid="stDataEditor"] input, [data-testid="stDataEditor"] textarea, [data-testid="stDataEditor"] select,
[data-testid="stDataEditor"] [contenteditable="true"] {
    background-color: #f3f9ff !important;
    color: #061423 !important;
    -webkit-text-fill-color: #061423 !important;
    caret-color: #061423 !important;
    font-weight: 850 !important;
}
/* 下拉選單：展開深底淺字，選中亮底深字 */
div[data-baseweb="popover"], div[data-baseweb="popover"] ul, div[data-baseweb="popover"] div[role="listbox"],
ul[role="listbox"], div[role="listbox"] {
    background: #061423 !important;
    color: #ecfbff !important;
}
div[data-baseweb="popover"] [role="option"], div[data-baseweb="popover"] [role="option"] *,
ul[role="listbox"] li, ul[role="listbox"] li *, div[role="option"], div[role="option"] * {
    color: #ecfbff !important;
    -webkit-text-fill-color: #ecfbff !important;
    font-weight: 850 !important;
}
div[data-baseweb="popover"] [role="option"][aria-selected="true"],
ul[role="listbox"] li[aria-selected="true"], div[role="option"][aria-selected="true"] {
    background: #36e7f7 !important;
    color: #04101d !important;
    -webkit-text-fill-color: #04101d !important;
}
div[data-baseweb="popover"] [role="option"][aria-selected="true"] *,
ul[role="listbox"] li[aria-selected="true"] *, div[role="option"][aria-selected="true"] * {
    color: #04101d !important;
    -webkit-text-fill-color: #04101d !important;
}
/* 欄位順序大型輸入框 */
.stTextArea textarea {
    min-height: 180px !important;
    line-height: 1.55 !important;
    font-size: 18px !important;
}
/* 安全設定數字輸入比例 */
.stNumberInput input {
    font-size: 28px !important;
    min-height: 54px !important;
    font-weight: 950 !important;
}


/* ===== V1.96 clickable controls readability fix =====
   所有可點選控制項改成淺色底、深色字，避免深色主題下看不到文字。
   Covers: buttons, radio options, checkbox labels, toggles, download buttons, form submit buttons.
*/
.stButton > button,
.stDownloadButton > button,
div[data-testid="stFormSubmitButton"] button,
button[kind="secondary"],
button[kind="primary"],
button[data-testid="baseButton-secondary"],
button[data-testid="baseButton-primary"] {
    background: linear-gradient(180deg, #f4fbff 0%, #d9f5ff 100%) !important;
    color: #04101d !important;
    -webkit-text-fill-color: #04101d !important;
    border: 1px solid rgba(35, 230, 255, .92) !important;
    border-radius: 12px !important;
    font-weight: 950 !important;
    text-shadow: none !important;
    box-shadow: 0 0 0 1px rgba(35,230,255,.20) inset, 0 0 14px rgba(35,230,255,.18) !important;
}
.stButton > button:hover,
.stDownloadButton > button:hover,
div[data-testid="stFormSubmitButton"] button:hover,
button[kind="secondary"]:hover,
button[kind="primary"]:hover,
button[data-testid="baseButton-secondary"]:hover,
button[data-testid="baseButton-primary"]:hover {
    background: linear-gradient(180deg, #ffffff 0%, #bdf2ff 100%) !important;
    color: #020914 !important;
    -webkit-text-fill-color: #020914 !important;
    border-color: #63f4ff !important;
    box-shadow: 0 0 0 1px rgba(35,230,255,.50) inset, 0 0 22px rgba(35,230,255,.46) !important;
}
.stButton > button:disabled,
.stDownloadButton > button:disabled,
div[data-testid="stFormSubmitButton"] button:disabled,
button:disabled {
    background: rgba(190, 203, 214, .72) !important;
    color: rgba(20, 35, 48, .72) !important;
    -webkit-text-fill-color: rgba(20, 35, 48, .72) !important;
    border-color: rgba(170, 190, 205, .62) !important;
    opacity: .70 !important;
}
/* Radio / Checkbox / Toggle: make the whole clickable row readable. */
div[role="radiogroup"] label,
.stRadio label,
.stCheckbox label,
.stToggle label,
label[data-baseweb="radio"],
label[data-baseweb="checkbox"] {
    color: #f5fbff !important;
    -webkit-text-fill-color: #f5fbff !important;
    font-weight: 900 !important;
    text-shadow: 0 0 8px rgba(35,230,255,.22) !important;
}
div[role="radiogroup"] label > div,
.stRadio label > div,
.stCheckbox label > div,
.stToggle label > div,
label[data-baseweb="radio"] > div,
label[data-baseweb="checkbox"] > div {
    color: #f5fbff !important;
    -webkit-text-fill-color: #f5fbff !important;
}
/* Give option text a subtle light chip so Delete / Recalculate choices stay visible. */
div[role="radiogroup"] label span,
.stRadio label span,
.stCheckbox label span,
.stToggle label span,
label[data-baseweb="radio"] span,
label[data-baseweb="checkbox"] span {
    color: #f5fbff !important;
    -webkit-text-fill-color: #f5fbff !important;
    font-weight: 900 !important;
}
/* Checked controls use light cyan fill and dark check mark for contrast. */
div[data-baseweb="checkbox"] [aria-checked="true"],
div[data-baseweb="radio"] [aria-checked="true"] {
    background-color: #dffaff !important;
    border-color: #67f5ff !important;
    color: #04101d !important;
}
/* Data editor checkbox cells: always visible on dark table, without hover. */
[data-testid="stDataEditor"] [data-baseweb="checkbox"],
[data-testid="stDataEditor"] [data-baseweb="checkbox"] *,
[data-testid="stDataEditor"] input[type="checkbox"],
[data-testid="stDataEditor"] [role="checkbox"] {
    opacity: 1 !important;
    visibility: visible !important;
}

/* Native checkbox fallback used by some Streamlit/Glide cells. */
[data-testid="stDataEditor"] input[type="checkbox"] {
    appearance: auto !important;
    -webkit-appearance: checkbox !important;
    accent-color: #18d7f0 !important;
    width: 16px !important;
    height: 16px !important;
    min-width: 16px !important;
    min-height: 16px !important;
    background: #f5fbff !important;
    border: 2px solid #67f5ff !important;
    outline: 1px solid rgba(223,250,255,.92) !important;
    box-shadow: 0 0 0 1px rgba(255,255,255,.65) inset, 0 0 10px rgba(35,230,255,.35) !important;
}

/* BaseWeb checkbox fallback used inside st.data_editor cells. */
[data-testid="stDataEditor"] [data-baseweb="checkbox"] > div,
[data-testid="stDataEditor"] [data-baseweb="checkbox"] div[role="checkbox"],
[data-testid="stDataEditor"] [role="checkbox"] {
    width: 16px !important;
    height: 16px !important;
    min-width: 16px !important;
    min-height: 16px !important;
    background: linear-gradient(180deg, #f5fbff 0%, #dff7ff 100%) !important;
    border: 2px solid rgba(103,245,255,.98) !important;
    border-radius: 4px !important;
    outline: 1px solid rgba(223,250,255,.92) !important;
    box-shadow: 0 0 0 1px rgba(255,255,255,.70) inset, 0 0 10px rgba(35,230,255,.35) !important;
    color: #04101d !important;
}

/* Checked state: keep the cyan fill and dark tick clearly visible. */
[data-testid="stDataEditor"] input[type="checkbox"]:checked,
[data-testid="stDataEditor"] [data-baseweb="checkbox"] [aria-checked="true"],
[data-testid="stDataEditor"] [role="checkbox"][aria-checked="true"] {
    background: linear-gradient(180deg, #dffaff 0%, #b9f6ff 100%) !important;
    border-color: #18d7f0 !important;
    box-shadow: 0 0 0 1px rgba(255,255,255,.80) inset, 0 0 13px rgba(35,230,255,.48) !important;
    color: #04101d !important;
}
[data-testid="stDataEditor"] [data-baseweb="checkbox"] svg,
[data-testid="stDataEditor"] [data-baseweb="checkbox"] path,
[data-testid="stDataEditor"] [role="checkbox"] svg,
[data-testid="stDataEditor"] [role="checkbox"] path {
    fill: #04101d !important;
    stroke: #04101d !important;
    opacity: 1 !important;
}

/* Disabled/read-only tables must not fade the checkbox into the dark cell background. */
[data-testid="stDataEditor"] [aria-disabled="true"],
[data-testid="stDataEditor"] [disabled],
[data-testid="stDataEditor"] [data-disabled="true"] {
    opacity: 1 !important;
}

/* V2.03: checkbox/radio/toggle rows use light background so confirmations are clearly visible. */
[data-testid="stCheckbox"] > label,
[data-testid="stRadio"] label,
[data-testid="stToggle"] > label {
    background: linear-gradient(180deg, #f5fbff 0%, #dff7ff 100%) !important;
    color: #04101d !important;
    -webkit-text-fill-color: #04101d !important;
    border: 1px solid rgba(35, 230, 255, .78) !important;
    border-radius: 10px !important;
    padding: 8px 12px !important;
    box-shadow: 0 0 0 1px rgba(35,230,255,.12) inset, 0 0 12px rgba(35,230,255,.16) !important;
}
[data-testid="stCheckbox"] > label *,
[data-testid="stRadio"] label *,
[data-testid="stToggle"] > label * {
    color: #04101d !important;
    -webkit-text-fill-color: #04101d !important;
    text-shadow: none !important;
    font-weight: 950 !important;
}
[data-testid="stCheckbox"] input[type="checkbox"],
[data-testid="stCheckbox"] [role="checkbox"] {
    accent-color: #18d7f0 !important;
    outline: 2px solid rgba(4,16,29,.55) !important;
    box-shadow: 0 0 0 2px rgba(255,255,255,.8), 0 0 10px rgba(35,230,255,.35) !important;
}

/* Expander headers and clickable captions should stay bright. */
div[data-testid="stExpander"] summary,
div[data-testid="stExpander"] summary * {
    color: #f4fbff !important;
    -webkit-text-fill-color: #f4fbff !important;
    font-weight: 900 !important;
}


/* ===== V2.02 login user bar: larger, clear, tech breathing glow ===== */
.spt-login-pill {
    min-height: 58px;
    padding: 10px 18px;
    margin: 4px 0 10px 0;
    border: 1px solid rgba(98, 244, 255, .65);
    border-radius: 16px;
    background: linear-gradient(105deg, rgba(4, 32, 54, .92), rgba(5, 74, 105, .70), rgba(39, 24, 90, .58));
    box-shadow: 0 0 0 1px rgba(35,230,255,.18) inset, 0 0 18px rgba(35,230,255,.28), 0 0 34px rgba(112,61,255,.14);
    animation: sptLoginBreath 2.6s ease-in-out infinite;
}
.spt-login-label {
    color: rgba(207, 246, 255, .88);
    font-size: 13px;
    font-weight: 900;
    letter-spacing: .7px;
    text-transform: uppercase;
    margin-bottom: 2px;
}
.spt-login-value {
    color: #ffffff;
    font-size: 30px;
    line-height: 1.18;
    font-weight: 1000;
    letter-spacing: .4px;
    text-shadow: 0 0 10px rgba(255,255,255,.28), 0 0 22px rgba(35,230,255,.38);
}
.spt-login-value span {
    color: #aef7ff;
    font-size: 22px;
    font-weight: 950;
}
@keyframes sptLoginBreath {
    0%,100% { box-shadow: 0 0 0 1px rgba(35,230,255,.18) inset, 0 0 14px rgba(35,230,255,.22), 0 0 28px rgba(112,61,255,.12); }
    50% { box-shadow: 0 0 0 1px rgba(35,230,255,.42) inset, 0 0 30px rgba(35,230,255,.55), 0 0 58px rgba(112,61,255,.30); }
}

</style>
""",
        unsafe_allow_html=True,
    )


# ===== V2.57 operation message persistence removed =====
# User requirement: do not replay or retain success/info/warning/error messages
# across reruns.  Keep native Streamlit messages only for the current execution.
def _current_page_id_for_messages() -> str:
    try:
        import inspect
        for frame in inspect.stack():
            fn = str(getattr(frame, "filename", "") or "").replace("\\", "/")
            if "/pages/" in fn:
                return fn.rsplit("/", 1)[-1]
        return "streamlit_app.py"
    except Exception:
        return "streamlit_app.py"


def _message_store_key(page_id: str | None = None) -> str:
    return f"_spt_persistent_messages::{page_id or _current_page_id_for_messages()}"


def _clear_all_persistent_message_state() -> None:
    try:
        for k in list(st.session_state.keys()):
            if str(k).startswith("_spt_persistent_messages::"):
                st.session_state.pop(k, None)
    except Exception:
        pass


def _install_persistent_message_patch() -> None:
    # No-op since V2.57. Do not monkey-patch st.success/info/warning/error.
    _clear_all_persistent_message_state()


def _render_persistent_operation_messages() -> None:
    # No-op since V2.57. Prevent old replay panel / replay banners.
    _clear_all_persistent_message_state()


def _clear_transient_selection_on_page_change() -> None:
    """Clear batch-selection checkboxes when the user leaves a module page.

    Selection checkboxes are operational state, not persistent settings.  Keep them
    while the editor stays on the same page, but clear them automatically when the
    page changes so the next module never inherits stale selected rows.
    """
    try:
        import inspect
        current = ""
        for frame in inspect.stack():
            fn = str(getattr(frame, "filename", "") or "")
            if "/pages/" in fn.replace("\\", "/"):
                current = fn.rsplit("/", 1)[-1]
                break
        if not current:
            current = "streamlit_app.py"
        prev = st.session_state.get("_spt_current_page_for_selection")
        if prev and prev != current:
            for k in list(st.session_state.keys()):
                if str(k).startswith("_spt_select_"):
                    st.session_state.pop(k, None)
        st.session_state["_spt_current_page_for_selection"] = current
    except Exception:
        pass



def _inject_multiselect_tag_height_fix() -> None:
    """V2.57: keep select/multiselect text readable without white-dot artifacts."""
    try:
        st.markdown(
            """
            <style>
            /* V2.57｜修正下拉/多選文字被切掉，同時去除白點 */
            .stSelectbox,
            .stMultiSelect {
                overflow: visible !important;
            }

            .stSelectbox div[data-baseweb="select"],
            .stMultiSelect div[data-baseweb="select"] {
                min-height: 48px !important;
                height: auto !important;
                border-radius: 10px !important;
                background: #eef7fb !important;
                overflow: visible !important;
            }

            .stSelectbox div[data-baseweb="select"] > div,
            .stMultiSelect div[data-baseweb="select"] > div {
                min-height: 48px !important;
                height: auto !important;
                padding-top: 6px !important;
                padding-bottom: 6px !important;
                align-items: center !important;
                overflow: visible !important;
            }

            /* Selectbox / multiselect display text and placeholder */
            div[data-baseweb="select"] span,
            div[data-baseweb="select"] div,
            div[data-baseweb="select"] input,
            div[data-baseweb="select"] input[type="text"] {
                color: #03121f !important;
                -webkit-text-fill-color: #03121f !important;
                font-weight: 850 !important;
                font-size: inherit !important;
                line-height: 1.45 !important;
                text-shadow: none !important;
            }

            div[data-baseweb="select"] input,
            div[data-baseweb="select"] input[type="text"],
            div[data-baseweb="select"] input[aria-autocomplete="list"] {
                background: transparent !important;
                background-color: transparent !important;
                border: 0 !important;
                outline: 0 !important;
                box-shadow: none !important;
                min-height: 28px !important;
                height: 28px !important;
                line-height: 28px !important;
                padding: 0 !important;
                margin: 0 !important;
                caret-color: #03121f !important;
            }

            div[data-baseweb="select"] input::placeholder {
                color: rgba(3,18,31,.78) !important;
                -webkit-text-fill-color: rgba(3,18,31,.78) !important;
                opacity: 1 !important;
            }

            /* Multiselect selected tags */
            div[data-baseweb="tag"] {
                min-height: 32px !important;
                height: auto !important;
                padding: 6px 10px !important;
                border-radius: 9px !important;
                line-height: 1.35 !important;
                display: inline-flex !important;
                align-items: center !important;
                background: linear-gradient(135deg, #bff7ff, #7ee8ff) !important;
                color: #03121f !important;
                -webkit-text-fill-color: #03121f !important;
                font-weight: 900 !important;
                overflow: visible !important;
                white-space: nowrap !important;
                margin-top: 2px !important;
                margin-bottom: 2px !important;
            }

            div[data-baseweb="tag"] span,
            div[data-baseweb="tag"] div {
                color: #03121f !important;
                -webkit-text-fill-color: #03121f !important;
                font-weight: 900 !important;
                line-height: 1.35 !important;
                overflow: visible !important;
            }

            div[data-baseweb="tag"] svg,
            div[data-baseweb="select"] svg,
            div[data-baseweb="select"] [role="button"] svg {
                color: #03121f !important;
                fill: #03121f !important;
            }

            /* Dropdown list options */
            ul[role="listbox"] li,
            div[role="option"] {
                min-height: 38px !important;
                line-height: 1.45 !important;
                padding-top: 8px !important;
                padding-bottom: 8px !important;
                color: #03121f !important;
                -webkit-text-fill-color: #03121f !important;
                font-weight: 800 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def render_operation_results() -> None:
    """V2.57: legacy helper kept for compatibility; intentionally renders nothing."""
    _clear_all_persistent_message_state()


def clear_operation_results() -> None:
    _clear_all_persistent_message_state()

def apply_theme() -> None:
    _inject_css()
    _inject_multiselect_tag_height_fix()
    _clear_all_persistent_message_state()
    _clear_transient_selection_on_page_change()
    # V2.18: apply global font scale to every module page.
    # Best-effort only; visual theme must never break a page.
    try:
        from services.home_ui_settings_service import inject_global_font_scale
        inject_global_font_scale()
    except Exception:
        pass
    # V1.60: install global table column settings once.
    # Best-effort only; visual theme must never break a page.
    try:
        from services.column_settings_service import install_column_settings_patch
        install_column_settings_patch()
    except Exception:
        pass


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


# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX REMOVED IN V2.88 FAST BOOT =====



# ===== V2.61 SELECT / MULTISELECT HEIGHT FINAL OVERRIDE REMOVED IN V2.88 FAST BOOT =====



# ===== V2.62 dropdown menu light readable patch REMOVED IN V2.88 FAST BOOT =====





# ===== V2.63 SELECT / MULTISELECT BOX HEIGHT ALIGN PATCH REMOVED IN V2.88 FAST BOOT =====




# ===== V2.64 GLOBAL SELECTBOX / MULTISELECT UNIFIED FINAL CSS REMOVED IN V2.88 FAST BOOT =====




# ===== V2.65 SELECT DISPLAY ABSOLUTE HEIGHT OVERRIDE REMOVED IN V2.88 FAST BOOT =====




# ===== V2.66 STATUS HEIGHT UNIFY ALL FILTER FIELDS REMOVED IN V2.88 FAST BOOT =====




# ===== V2.67 SELECT HEIGHT 70 MENU TEXT VISIBLE FINAL REMOVED IN V2.88 FAST BOOT =====




# ===== V2.68 FORCE DROPDOWN REAL DOM FIX REMOVED IN V2.88 FAST BOOT =====




# ===== V2.69 USER CONFIGURABLE DROPDOWN SIZE REMOVED IN V2.88 FAST BOOT =====




# ===== V2.70 MAIN PAGE DROPDOWN SIZE PANEL FALLBACK REMOVED IN V2.88 FAST BOOT =====




# ===== V2.79 FUTURE CYBER FIELD UI REMOVED IN V2.88 FAST BOOT =====





# ===== V2.88 FAST BOOT LEGACY COMPAT NO-OPS START =====
def apply_v259_select_multiselect_text_fix():
    return

def apply_v261_select_multiselect_height_final_fix():
    return

def _spt_v262_dropdown_menu_light_css():
    return

def apply_v263_select_box_left_size_fix():
    return

def apply_v264_global_select_unified_final_css():
    return

def apply_v265_select_display_absolute_height_fix():
    return

def apply_v266_status_height_unify_all_filter_fields():
    return

def apply_v267_select_height_70_menu_text_visible_final():
    return

def apply_v268_force_dropdown_real_dom_fix():
    return

def apply_v269_configurable_dropdown_css():
    return

def render_dropdown_size_settings_panel():
    return

def render_dropdown_size_settings_panel_main_fallback():
    return
# ===== V2.88 FAST BOOT LEGACY COMPAT NO-OPS END =====

# ===== V2.80 WAR-ROOM FUTURE FORM HUD UI START =====
def apply_v280_warroom_future_form_hud_ui():
    """War-room level future HUD styling for Streamlit form widgets.
    Keeps readability as first priority, then adds refined scanline, glow, active focus layer,
    and a less-flat professional panel feel. Pure CSS only; no data / permission logic touched.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.80｜戰情中心級未來科技表單 HUD */
        :root {
            --spt-v280-bg-a: rgba(5, 17, 38, 0.96);
            --spt-v280-bg-b: rgba(10, 30, 62, 0.92);
            --spt-v280-bg-c: rgba(13, 23, 54, 0.96);
            --spt-v280-cyan: rgba(79, 229, 255, 0.90);
            --spt-v280-cyan-soft: rgba(79, 229, 255, 0.34);
            --spt-v280-blue: rgba(87, 120, 255, 0.28);
            --spt-v280-text: #f1fcff;
            --spt-v280-soft: #c7f5ff;
            --spt-v280-muted: #8fb8cf;
            --spt-v280-dark-text: #04131f;
        }

        @keyframes sptV280FieldBreath {
            0%, 100% {
                box-shadow:
                    inset 0 1px 0 rgba(255,255,255,0.10),
                    inset 0 -1px 0 rgba(79,229,255,0.08),
                    0 0 0 1px rgba(79,229,255,0.18),
                    0 0 12px rgba(79,229,255,0.08),
                    0 0 24px rgba(87,120,255,0.08),
                    0 12px 26px rgba(0,0,0,0.34);
            }
            50% {
                box-shadow:
                    inset 0 1px 0 rgba(255,255,255,0.15),
                    inset 0 -1px 0 rgba(79,229,255,0.14),
                    0 0 0 1px rgba(79,229,255,0.30),
                    0 0 18px rgba(79,229,255,0.16),
                    0 0 36px rgba(87,120,255,0.14),
                    0 15px 30px rgba(0,0,0,0.38);
            }
        }

        @keyframes sptV280Sweep {
            0% { background-position: -180% 0, 0 0, 0 0; }
            100% { background-position: 180% 0, 0 0, 0 0; }
        }

        .stSelectbox,
        .stMultiSelect,
        .stTextInput,
        .stDateInput,
        .stNumberInput,
        .stTextArea,
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"],
        div[data-testid="stTextInput"],
        div[data-testid="stDateInput"],
        div[data-testid="stNumberInput"],
        div[data-testid="stTextArea"] {
            overflow: visible !important;
        }

        /* 欄位容器加一點間距，避免光暈被上下切掉 */
        div[data-testid="stVerticalBlock"] > div:has(.stSelectbox),
        div[data-testid="stVerticalBlock"] > div:has(.stMultiSelect),
        div[data-testid="stVerticalBlock"] > div:has(.stTextInput),
        div[data-testid="stVerticalBlock"] > div:has(.stDateInput),
        div[data-testid="stVerticalBlock"] > div:has(.stNumberInput),
        div[data-testid="stVerticalBlock"] > div:has(.stTextArea) {
            overflow: visible !important;
        }

        /* SELECT / MULTISELECT 主體：暗色玻璃、細光條、掃描感 */
        div[data-baseweb="select"] > div {
            position: relative !important;
            isolation: isolate !important;
            background:
                linear-gradient(100deg, transparent 0%, rgba(133, 245, 255, 0.12) 45%, transparent 70%) -180% 0 / 180% 100% no-repeat,
                linear-gradient(180deg, rgba(255,255,255,0.075) 0%, rgba(255,255,255,0.018) 17%, rgba(255,255,255,0.00) 18%),
                linear-gradient(135deg, var(--spt-v280-bg-a) 0%, var(--spt-v280-bg-b) 52%, var(--spt-v280-bg-c) 100%) !important;
            border: 1px solid var(--spt-v280-cyan) !important;
            border-radius: 16px !important;
            color: var(--spt-v280-text) !important;
            animation: sptV280FieldBreath 3.4s ease-in-out infinite, sptV280Sweep 6.5s linear infinite !important;
            backdrop-filter: blur(12px) saturate(140%) !important;
            -webkit-backdrop-filter: blur(12px) saturate(140%) !important;
            outline: 1px solid rgba(255,255,255,0.035) !important;
        }

        div[data-baseweb="select"] > div::before {
            content: "";
            position: absolute;
            left: 12px;
            right: 12px;
            top: 5px;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(161,247,255,0.74), transparent);
            z-index: 0;
            pointer-events: none;
            opacity: 0.82;
        }

        div[data-baseweb="select"] > div::after {
            content: "";
            position: absolute;
            left: 10px;
            bottom: 5px;
            width: 34%;
            height: 1px;
            background: linear-gradient(90deg, rgba(80,229,255,0.66), transparent);
            z-index: 0;
            pointer-events: none;
            opacity: 0.72;
        }

        div[data-baseweb="select"] > div:hover,
        div[data-baseweb="select"] > div:focus-within {
            border-color: rgba(141, 247, 255, 0.98) !important;
            transform: translateY(-1px) !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.16),
                inset 0 -1px 0 rgba(79,229,255,0.16),
                0 0 0 1px rgba(141,247,255,0.32),
                0 0 20px rgba(79,229,255,0.19),
                0 0 40px rgba(87,120,255,0.18),
                0 16px 34px rgba(0,0,0,0.42) !important;
        }

        /* select 文字：全部淺色，解決深色框可讀性 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] div,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded] {
            color: var(--spt-v280-text) !important;
            -webkit-text-fill-color: var(--spt-v280-text) !important;
            text-shadow: 0 0 10px rgba(121, 237, 255, 0.12) !important;
            background: transparent !important;
            z-index: 1 !important;
        }

        div[data-baseweb="select"] input::placeholder {
            color: var(--spt-v280-muted) !important;
            -webkit-text-fill-color: var(--spt-v280-muted) !important;
            opacity: 1 !important;
        }

        div[data-baseweb="select"] svg {
            fill: #a9f7ff !important;
            color: #a9f7ff !important;
            filter: drop-shadow(0 0 7px rgba(79,229,255,0.35));
        }

        /* 文字、日期、數字、備註欄同樣科技化 */
        .stTextInput input,
        .stDateInput input,
        .stNumberInput input,
        .stTextArea textarea,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stNumberInputRootElement"] input,
        div[data-testid="stDateInputField"] input {
            background:
                linear-gradient(100deg, transparent 0%, rgba(133, 245, 255, 0.10) 45%, transparent 70%) -180% 0 / 180% 100% no-repeat,
                linear-gradient(180deg, rgba(255,255,255,0.075) 0%, rgba(255,255,255,0.018) 17%, rgba(255,255,255,0.00) 18%),
                linear-gradient(135deg, var(--spt-v280-bg-a) 0%, var(--spt-v280-bg-b) 52%, var(--spt-v280-bg-c) 100%) !important;
            color: var(--spt-v280-text) !important;
            -webkit-text-fill-color: var(--spt-v280-text) !important;
            border: 1px solid var(--spt-v280-cyan) !important;
            border-radius: 16px !important;
            animation: sptV280FieldBreath 3.4s ease-in-out infinite, sptV280Sweep 6.5s linear infinite !important;
            caret-color: #b9fbff !important;
            text-shadow: 0 0 10px rgba(121,237,255,0.10) !important;
        }

        .stTextInput input::placeholder,
        .stDateInput input::placeholder,
        .stNumberInput input::placeholder,
        .stTextArea textarea::placeholder {
            color: var(--spt-v280-muted) !important;
            -webkit-text-fill-color: var(--spt-v280-muted) !important;
            opacity: 1 !important;
        }

        .stTextInput input:focus,
        .stDateInput input:focus,
        .stNumberInput input:focus,
        .stTextArea textarea:focus {
            border-color: rgba(141,247,255,0.98) !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.16),
                0 0 0 1px rgba(141,247,255,0.28),
                0 0 20px rgba(79,229,255,0.20),
                0 0 42px rgba(87,120,255,0.18),
                0 16px 34px rgba(0,0,0,0.42) !important;
        }

        /* 數字輸入 +/- 按鈕 */
        .stNumberInput button,
        div[data-testid="stNumberInputStepUp"],
        div[data-testid="stNumberInputStepDown"] {
            background: linear-gradient(135deg, rgba(5,17,38,0.98), rgba(17,42,79,0.96)) !important;
            color: #dffcff !important;
            border-color: rgba(79,229,255,0.42) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 0 12px rgba(79,229,255,0.14) !important;
        }
        .stNumberInput button *,
        div[data-testid="stNumberInputStepUp"] *,
        div[data-testid="stNumberInputStepDown"] * {
            color: #dffcff !important;
            fill: #dffcff !important;
        }

        /* multiselect tag */
        div[data-baseweb="tag"] {
            background: linear-gradient(135deg, rgba(80,236,255,0.92), rgba(141,177,255,0.94)) !important;
            border: 1px solid rgba(210, 251, 255, 0.98) !important;
            border-radius: 11px !important;
            color: var(--spt-v280-dark-text) !important;
            box-shadow: 0 0 12px rgba(79,229,255,0.20) !important;
        }
        div[data-baseweb="tag"] *,
        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            color: var(--spt-v280-dark-text) !important;
            -webkit-text-fill-color: var(--spt-v280-dark-text) !important;
            font-weight: 950 !important;
        }

        /* 下拉展開面板 */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.012) 18%, rgba(255,255,255,0.00) 19%),
                linear-gradient(135deg, rgba(4,15,34,0.98), rgba(11,31,65,0.98)) !important;
            border: 1px solid rgba(93,233,255,0.66) !important;
            border-radius: 16px !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.10),
                0 0 0 1px rgba(79,229,255,0.20),
                0 0 20px rgba(79,229,255,0.18),
                0 0 42px rgba(87,120,255,0.16),
                0 18px 46px rgba(0,0,0,0.50) !important;
            backdrop-filter: blur(16px) saturate(145%) !important;
            -webkit-backdrop-filter: blur(16px) saturate(145%) !important;
            overflow: hidden !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li,
        div[data-baseweb="menu"] div {
            background: transparent !important;
            color: var(--spt-v280-text) !important;
            -webkit-text-fill-color: var(--spt-v280-text) !important;
            font-weight: 850 !important;
            text-shadow: none !important;
            border-radius: 10px !important;
            margin: 4px 7px !important;
            padding-top: 10px !important;
            padding-bottom: 10px !important;
        }
        div[data-baseweb="popover"] *,
        div[data-baseweb="menu"] *,
        ul[role="listbox"] * {
            color: var(--spt-v280-text) !important;
            -webkit-text-fill-color: var(--spt-v280-text) !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[data-baseweb="menu"] div:hover {
            background: linear-gradient(90deg, rgba(79,229,255,0.18), rgba(108,137,255,0.24)) !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            box-shadow: inset 0 0 0 1px rgba(130,241,255,0.20), 0 0 12px rgba(79,229,255,0.10) !important;
        }

        div[aria-selected="true"],
        li[aria-selected="true"],
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"] {
            background: linear-gradient(90deg, rgba(80,236,255,0.94), rgba(139,176,255,0.94)) !important;
            color: var(--spt-v280-dark-text) !important;
            -webkit-text-fill-color: var(--spt-v280-dark-text) !important;
            font-weight: 950 !important;
            box-shadow: inset 0 0 0 1px rgba(236,253,255,0.35), 0 0 16px rgba(79,229,255,0.18) !important;
        }
        div[aria-selected="true"] *,
        li[aria-selected="true"] * {
            color: var(--spt-v280-dark-text) !important;
            -webkit-text-fill-color: var(--spt-v280-dark-text) !important;
        }

        div[aria-disabled="true"],
        li[aria-disabled="true"] {
            color: #8db2c7 !important;
            -webkit-text-fill-color: #8db2c7 !important;
            opacity: 0.82 !important;
        }

        .stSelectbox label,
        .stMultiSelect label,
        .stTextInput label,
        .stDateInput label,
        .stNumberInput label,
        .stTextArea label,
        div[data-testid="stWidgetLabel"] label {
            color: #f0fcff !important;
            text-shadow: 0 0 12px rgba(79,229,255,0.20) !important;
            letter-spacing: 0.35px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v280_warroom_future_form_hud_ui()
except Exception:
    pass

for _spt_v280_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v280_func = globals().get(_spt_v280_name)
    if callable(_spt_v280_func) and not getattr(_spt_v280_func, "_spt_v280_wrapped", False):
        def _spt_v280_make_wrapper(_original):
            def _spt_v280_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v280_warroom_future_form_hud_ui()
                except Exception:
                    pass
                return result
            _spt_v280_wrapper._spt_v280_wrapped = True
            return _spt_v280_wrapper
        globals()[_spt_v280_name] = _spt_v280_make_wrapper(_spt_v280_func)
# ===== V2.80 WAR-ROOM FUTURE FORM HUD UI END =====


# ===== V2.81 STABLE SPACING GUARD - DO NOT REMOVE START =====
def apply_v281_stable_spacing_guard():
    """Restore and lock form field spacing after V2.80 HUD styling.
    This patch deliberately preserves V2.80 cyber/HUD colors and only fixes layout gaps,
    glow clipping, and textarea/button contrast. Do not remove in later visual upgrades.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.81｜穩定欄位間距防回退補丁
           原則：只修間距與裁切，不覆蓋 V2.80 深色 HUD 主視覺。 */

        :root {
            --spt-v281-widget-gap-y: 18px;
            --spt-v281-label-gap: 8px;
            --spt-v281-field-min-h: 58px;
            --spt-v281-field-pad-x: 16px;
        }

        /* 每個 Streamlit 表單元件都保留足夠外距，避免光暈與下一個欄位互相貼住 */
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"],
        div[data-testid="stTextInput"],
        div[data-testid="stTextArea"],
        div[data-testid="stDateInput"],
        div[data-testid="stNumberInput"],
        .stSelectbox,
        .stMultiSelect,
        .stTextInput,
        .stTextArea,
        .stDateInput,
        .stNumberInput {
            margin-top: 4px !important;
            margin-bottom: var(--spt-v281-widget-gap-y) !important;
            padding-top: 2px !important;
            padding-bottom: 4px !important;
            overflow: visible !important;
        }

        /* 欄位 label 與輸入框之間固定留距，不可被後續版本吃掉 */
        div[data-testid="stWidgetLabel"],
        div[data-testid="stWidgetLabel"] > label,
        .stSelectbox label,
        .stMultiSelect label,
        .stTextInput label,
        .stTextArea label,
        .stDateInput label,
        .stNumberInput label {
            margin-bottom: var(--spt-v281-label-gap) !important;
            padding-bottom: 0 !important;
            line-height: 1.35 !important;
        }

        /* Select / multiselect 外層需要額外空間，避免藍框光暈被切掉 */
        div[data-baseweb="select"] {
            margin-top: 2px !important;
            margin-bottom: 6px !important;
            min-height: var(--spt-v281-field-min-h) !important;
            overflow: visible !important;
        }

        div[data-baseweb="select"] > div {
            min-height: var(--spt-v281-field-min-h) !important;
            height: var(--spt-v281-field-min-h) !important;
            padding-left: var(--spt-v281-field-pad-x) !important;
            padding-right: var(--spt-v281-field-pad-x) !important;
            overflow: visible !important;
            box-sizing: border-box !important;
        }

        /* 內層文字容器置中；只修高度，不改 V2.80 顏色 */
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"],
        div[data-baseweb="select"] div[class*="ValueContainer"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"] {
            min-height: calc(var(--spt-v281-field-min-h) - 4px) !important;
            height: calc(var(--spt-v281-field-min-h) - 4px) !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] input {
            line-height: 1.45 !important;
            min-height: 28px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
        }

        /* Text / date / number / textarea：恢復上下間距與光暈外露 */
        .stTextInput input,
        .stDateInput input,
        .stNumberInput input,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stNumberInputRootElement"] input,
        div[data-testid="stDateInputField"] input {
            min-height: var(--spt-v281-field-min-h) !important;
            height: var(--spt-v281-field-min-h) !important;
            padding-left: var(--spt-v281-field-pad-x) !important;
            padding-right: var(--spt-v281-field-pad-x) !important;
            box-sizing: border-box !important;
            overflow: visible !important;
        }

        /* TextArea 不要被前版白底規則吃回去，也不要貼上下元件 */
        .stTextArea textarea,
        div[data-testid="stTextArea"] textarea {
            min-height: 138px !important;
            padding: 14px 16px !important;
            box-sizing: border-box !important;
            overflow: auto !important;
        }

        /* Checkbox 與按鈕和上一個大欄位分開，不再貼住 */
        .stCheckbox,
        div[data-testid="stCheckbox"] {
            margin-top: 8px !important;
            margin-bottom: 18px !important;
            overflow: visible !important;
        }

        .stButton,
        div[data-testid="stButton"] {
            margin-top: 8px !important;
            margin-bottom: 18px !important;
            overflow: visible !important;
        }

        .stButton > button,
        div[data-testid="stButton"] button {
            min-height: 46px !important;
            border-radius: 14px !important;
        }

        /* 欄位分組在 columns 內時，保留一致行距 */
        div[data-testid="column"] > div {
            overflow: visible !important;
        }

        /* 防止最底部分隔線或下一區塊壓到光暈 */
        hr,
        [data-testid="stMarkdownContainer"] hr {
            margin-top: 22px !important;
            margin-bottom: 20px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v281_stable_spacing_guard()
except Exception:
    pass

for _spt_v281_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v281_func = globals().get(_spt_v281_name)
    if callable(_spt_v281_func) and not getattr(_spt_v281_func, "_spt_v281_wrapped", False):
        def _spt_v281_make_wrapper(_original):
            def _spt_v281_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v281_stable_spacing_guard()
                except Exception:
                    pass
                return result
            _spt_v281_wrapper._spt_v281_wrapped = True
            return _spt_v281_wrapper
        globals()[_spt_v281_name] = _spt_v281_make_wrapper(_spt_v281_func)
# ===== V2.81 STABLE SPACING GUARD - DO NOT REMOVE END =====


# ===== V2.82 SELECT TEXT VISIBILITY GUARD START =====
def apply_v282_select_text_visibility_guard():
    """Final guard: keep V2.80/V2.81 cyber style, but force visible selected/placeholder text.
    This patch prevents dark text being restored on dark glass fields and prevents vertical clipping.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.82｜下拉欄位文字可視性防回退：DO NOT REMOVE
           保留深色科技感欄位，強制欄位內文字使用淺色，且不被裁切。 */

        :root {
            --spt-v282-field-text: #eafcff;
            --spt-v282-field-text-strong: #f7feff;
            --spt-v282-field-text-dim: #aeeeff;
            --spt-v282-field-text-muted: #8dccdf;
            --spt-v282-selected-text-dark: #03121f;
        }

        /* Selectbox / Multiselect 顯示框本體維持深色科技感，不回到慘白 */
        div[data-baseweb="select"] > div {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.014) 17%, rgba(255,255,255,0.00) 18%),
                linear-gradient(135deg, rgba(8, 20, 44, 0.94) 0%, rgba(16, 34, 69, 0.90) 54%, rgba(7, 16, 36, 0.96) 100%) !important;
            border: 1px solid rgba(104, 232, 255, 0.82) !important;
            color: var(--spt-v282-field-text) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text) !important;
            overflow: visible !important;
        }

        /* 關鍵：BaseWeb value/placeholder 容器不要繼承黑字，也不要被裁切 */
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"],
        div[data-baseweb="select"] div[class*="ValueContainer"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"] {
            color: var(--spt-v282-field-text) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text) !important;
            opacity: 1 !important;
            text-shadow: 0 0 8px rgba(107, 232, 255, 0.10) !important;
            background: transparent !important;
            overflow: visible !important;
            line-height: 1.35 !important;
            display: flex !important;
            align-items: center !important;
            min-height: 40px !important;
            height: auto !important;
        }

        /* 關鍵：顯示文字、placeholder、No options to select 都改淺色 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"] {
            color: var(--spt-v282-field-text-strong) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text-strong) !important;
            opacity: 1 !important;
            font-weight: 850 !important;
            line-height: 1.35 !important;
            min-height: 28px !important;
            height: auto !important;
            background: transparent !important;
            text-shadow: 0 0 8px rgba(107, 232, 255, 0.08) !important;
            overflow: visible !important;
            transform: none !important;
            filter: none !important;
        }

        div[data-baseweb="select"] input::placeholder {
            color: var(--spt-v282-field-text-dim) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text-dim) !important;
            opacity: 1 !important;
        }

        /* disabled / 無選項狀態仍要看得到 */
        div[data-baseweb="select"] [aria-disabled="true"],
        div[data-baseweb="select"] [disabled],
        div[data-baseweb="select"] [aria-disabled="true"] *,
        div[data-baseweb="select"] [disabled] * {
            color: var(--spt-v282-field-text-muted) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text-muted) !important;
            opacity: 0.86 !important;
        }

        /* 下拉展開清單：深底淺字，預設即清楚，不靠 hover */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.012) 15%, rgba(255,255,255,0.00) 16%),
                linear-gradient(135deg, rgba(6, 18, 40, 0.97) 0%, rgba(12, 30, 59, 0.98) 100%) !important;
            color: var(--spt-v282-field-text) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text) !important;
            overflow: hidden !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li,
        div[data-baseweb="menu"] div {
            color: var(--spt-v282-field-text) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text) !important;
            opacity: 1 !important;
            text-shadow: none !important;
            overflow: visible !important;
        }

        div[data-baseweb="popover"] *,
        div[data-baseweb="menu"] *,
        ul[role="listbox"] * {
            color: var(--spt-v282-field-text) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text) !important;
            opacity: 1 !important;
        }

        /* hover 保持淺字，不再切回黑字 */
        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[data-baseweb="menu"] div:hover {
            background: linear-gradient(90deg, rgba(68, 232, 255, 0.18), rgba(102, 135, 255, 0.24)) !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }

        /* 已選取項目用亮底，所以改深色字 */
        div[aria-selected="true"],
        li[aria-selected="true"],
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"] {
            background: linear-gradient(90deg, rgba(104, 235, 255, 0.96), rgba(140, 174, 255, 0.96)) !important;
            color: var(--spt-v282-selected-text-dark) !important;
            -webkit-text-fill-color: var(--spt-v282-selected-text-dark) !important;
            font-weight: 950 !important;
        }
        div[aria-selected="true"] *,
        li[aria-selected="true"] *,
        div[role="option"][aria-selected="true"] *,
        li[role="option"][aria-selected="true"] * {
            color: var(--spt-v282-selected-text-dark) !important;
            -webkit-text-fill-color: var(--spt-v282-selected-text-dark) !important;
        }

        /* 多選標籤維持亮底深字，避免標籤文字失真 */
        div[data-baseweb="tag"],
        div[data-baseweb="tag"] *,
        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            color: #061427 !important;
            -webkit-text-fill-color: #061427 !important;
            opacity: 1 !important;
        }

        /* 文字輸入 / 日期 / 數字 / 備註也強制淺字，避免被深色欄位吃掉 */
        .stTextInput input,
        .stDateInput input,
        .stNumberInput input,
        .stTextArea textarea,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stNumberInputRootElement"] input,
        div[data-testid="stDateInputField"] input {
            color: var(--spt-v282-field-text-strong) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text-strong) !important;
            opacity: 1 !important;
            text-shadow: 0 0 8px rgba(107, 232, 255, 0.08) !important;
            overflow: visible !important;
        }
        .stTextInput input::placeholder,
        .stDateInput input::placeholder,
        .stNumberInput input::placeholder,
        .stTextArea textarea::placeholder {
            color: var(--spt-v282-field-text-dim) !important;
            -webkit-text-fill-color: var(--spt-v282-field-text-dim) !important;
            opacity: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v282_select_text_visibility_guard()
except Exception:
    pass

for _spt_v282_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v282_func = globals().get(_spt_v282_name)
    if callable(_spt_v282_func) and not getattr(_spt_v282_func, "_spt_v282_wrapped", False):
        def _spt_v282_make_wrapper(_original):
            def _spt_v282_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v282_select_text_visibility_guard()
                except Exception:
                    pass
                return result
            _spt_v282_wrapper._spt_v282_wrapped = True
            return _spt_v282_wrapper
        globals()[_spt_v282_name] = _spt_v282_make_wrapper(_spt_v282_func)
# ===== V2.82 SELECT TEXT VISIBILITY GUARD END =====


# ===== V2.83 COLLAPSED SELECT DARK TEXT GUARD START =====
def apply_v283_collapsed_select_dark_text_guard():
    """Keep collapsed select/multiselect field text dark and readable on light glass fields.
    This intentionally targets only the visible field, not the opened dropdown popover.
    DO NOT REMOVE: prevents selected/placeholder text from being washed out by later HUD effects.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.83｜下拉欄位起始文字深色防回退
           目標：欄位收合狀態的已選文字 / placeholder / No options 必須清楚可見。
           注意：只鎖定欄位本體，不覆蓋展開選單面板。 */

        :root {
            --spt-v283-collapsed-select-text: #071523;
            --spt-v283-collapsed-select-muted: #19324a;
        }

        /* 收合狀態欄位本體：維持淺玻璃底時，文字必須是深色 */
        div[data-baseweb="select"] > div,
        div[data-baseweb="select"] > div:hover,
        div[data-baseweb="select"] > div:focus-within {
            color: var(--spt-v283-collapsed-select-text) !important;
            -webkit-text-fill-color: var(--spt-v283-collapsed-select-text) !important;
        }

        /* 選取值、placeholder、No options to select、value container */
        div[data-baseweb="select"] > div span,
        div[data-baseweb="select"] > div p,
        div[data-baseweb="select"] > div div[role="combobox"],
        div[data-baseweb="select"] > div div[aria-expanded],
        div[data-baseweb="select"] > div div[class*="placeholder"],
        div[data-baseweb="select"] > div div[class*="Placeholder"],
        div[data-baseweb="select"] > div div[class*="singleValue"],
        div[data-baseweb="select"] > div div[class*="SingleValue"],
        div[data-baseweb="select"] > div div[class*="valueContainer"],
        div[data-baseweb="select"] > div div[class*="ValueContainer"],
        div[data-baseweb="select"] > div div[class*="inputContainer"],
        div[data-baseweb="select"] > div div[class*="InputContainer"] {
            color: var(--spt-v283-collapsed-select-text) !important;
            -webkit-text-fill-color: var(--spt-v283-collapsed-select-text) !important;
            opacity: 1 !important;
            text-shadow: none !important;
            filter: none !important;
            mix-blend-mode: normal !important;
        }

        /* BaseWeb 內部搜尋 input / placeholder，避免被 HUD 淺色字覆蓋 */
        div[data-baseweb="select"] > div input,
        div[data-baseweb="select"] > div input[type="text"],
        div[data-baseweb="select"] > div input[aria-autocomplete="list"] {
            color: var(--spt-v283-collapsed-select-text) !important;
            -webkit-text-fill-color: var(--spt-v283-collapsed-select-text) !important;
            caret-color: var(--spt-v283-collapsed-select-text) !important;
            opacity: 1 !important;
            text-shadow: none !important;
            background: transparent !important;
        }

        div[data-baseweb="select"] > div input::placeholder {
            color: var(--spt-v283-collapsed-select-muted) !important;
            -webkit-text-fill-color: var(--spt-v283-collapsed-select-muted) !important;
            opacity: 1 !important;
        }

        /* 下拉箭頭仍維持科技感藍色，不跟著文字變黑 */
        div[data-baseweb="select"] > div svg {
            color: #8df7ff !important;
            fill: #8df7ff !important;
            opacity: 1 !important;
            filter: drop-shadow(0 0 6px rgba(0, 225, 255, 0.35)) !important;
        }

        /* 已選 multiselect tag 維持亮底深字 */
        div[data-baseweb="select"] div[data-baseweb="tag"],
        div[data-baseweb="select"] div[data-baseweb="tag"] * {
            color: #061427 !important;
            -webkit-text-fill-color: #061427 !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* 展開選單仍由 V2.82/V2.80 控制；這裡只補強選單內字不透明 */
        div[data-baseweb="popover"] *,
        div[data-baseweb="menu"] *,
        ul[role="listbox"] * {
            opacity: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v283_collapsed_select_dark_text_guard()
except Exception:
    pass

for _spt_v283_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v283_func = globals().get(_spt_v283_name)
    if callable(_spt_v283_func) and not getattr(_spt_v283_func, "_spt_v283_wrapped", False):
        def _spt_v283_make_wrapper(_original):
            def _spt_v283_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v283_collapsed_select_dark_text_guard()
                except Exception:
                    pass
                return result
            _spt_v283_wrapper._spt_v283_wrapped = True
            return _spt_v283_wrapper
        globals()[_spt_v283_name] = _spt_v283_make_wrapper(_spt_v283_func)
# ===== V2.83 COLLAPSED SELECT DARK TEXT GUARD END =====


# ===== V2.84 INPUT FRAME CLIP GUARD START =====
def apply_v284_input_frame_clip_guard():
    """Fix clipped outer frame on text/password inputs.
    Preserve current cyber style while ensuring the full rounded border/glow is visible.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        :root {
            --spt-v284-login-frame-gap-top: 8px;
            --spt-v284-login-frame-gap-side: 4px;
            --spt-v284-login-frame-gap-bottom: 8px;
        }

        /* 讓文字/密碼輸入元件外層不要裁切光暈與圓角 */
        .stTextInput,
        .stTextInput > div,
        .stTextInput > div > div,
        div[data-testid="stTextInput"],
        div[data-testid="stTextInput"] > div,
        div[data-testid="stTextInputRootElement"],
        div[data-testid="stTextInputRootElement"] > div,
        div[data-testid="stPasswordInput"],
        div[data-testid="stPasswordInput"] > div {
            overflow: visible !important;
            box-sizing: border-box !important;
        }

        /* 給足上/下/左右緩衝，避免外框被容器邊界切掉 */
        .stTextInput,
        div[data-testid="stTextInput"],
        div[data-testid="stPasswordInput"] {
            padding-top: var(--spt-v284-login-frame-gap-top) !important;
            padding-right: var(--spt-v284-login-frame-gap-side) !important;
            padding-bottom: var(--spt-v284-login-frame-gap-bottom) !important;
            padding-left: var(--spt-v284-login-frame-gap-side) !important;
            margin-top: 0 !important;
            margin-bottom: 10px !important;
        }

        /* 實際輸入框根容器：不再貼邊，也不裁切圓角與光暈 */
        div[data-testid="stTextInputRootElement"] {
            padding: 2px !important;
            border-radius: 18px !important;
            overflow: visible !important;
            background: transparent !important;
        }

        div[data-testid="stTextInputRootElement"] > div {
            border-radius: 18px !important;
            overflow: visible !important;
            background: transparent !important;
        }

        /* 眼睛按鈕容器也不要把右上圓角切掉 */
        div[data-testid="stTextInputRootElement"] button,
        div[data-testid="stPasswordInput"] button,
        .stTextInput button {
            overflow: visible !important;
            border-top-right-radius: 16px !important;
            border-bottom-right-radius: 16px !important;
        }

        /* 輸入框本體：移除任何會把外框推到裁切區的負位移感 */
        .stTextInput input,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stPasswordInput"] input {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            position: relative !important;
            top: 0 !important;
            left: 0 !important;
            box-sizing: border-box !important;
        }

        /* label 與欄位之間多一點距離，避免看起來外框被標籤壓住 */
        .stTextInput label,
        div[data-testid="stWidgetLabel"] label {
            margin-bottom: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v284_input_frame_clip_guard()
except Exception:
    pass

for _spt_v284_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v284_func = globals().get(_spt_v284_name)
    if callable(_spt_v284_func) and not getattr(_spt_v284_func, "_spt_v284_wrapped", False):
        def _spt_v284_make_wrapper(_original):
            def _spt_v284_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v284_input_frame_clip_guard()
                except Exception:
                    pass
                return result
            _spt_v284_wrapper._spt_v284_wrapped = True
            return _spt_v284_wrapper
        globals()[_spt_v284_name] = _spt_v284_make_wrapper(_spt_v284_func)
# ===== V2.84 INPUT FRAME CLIP GUARD END =====


# ===== V2.87 REMOVE DROPDOWN SIZE SETTINGS PANEL START =====
# The legacy dropdown tuning visual panel is intentionally hidden.
# Keep configuration loader/saver and CSS functions for compatibility, but do not render the UI.
def render_dropdown_size_settings_panel():
    return

def render_dropdown_size_settings_panel_main_fallback():
    return
# ===== V2.87 REMOVE DROPDOWN SIZE SETTINGS PANEL END =====


# ===== V2.88 FAST BOOT GUARD START =====
def apply_v288_fast_boot_guard():
    """Compatibility guard for faster Streamlit reboot.
    The obsolete V2.59-V2.70 and V2.79 CSS layers were removed from this file.
    Keep deleted visual panels hidden and preserve V2.80+V2.81+V2.82+V2.83+V2.84 UI stack.
    """
    return

def render_operation_results() -> None:
    return

def clear_operation_results() -> None:
    return

def render_dropdown_size_settings_panel():
    return

def render_dropdown_size_settings_panel_main_fallback():
    return
# ===== V2.88 FAST BOOT GUARD END =====


# ===== V2.89 PERMISSION BUTTON STANDARD GUARD START =====
def apply_v289_permission_button_standard_guard():
    """Force every Streamlit button/download/form-submit button to use the same
    visual language as 10｜權限管理: light cyber button, dark readable text,
    full-width friendly height, clear hover/disabled state, no clipped label.
    """
    try:
        import streamlit as st
    except Exception:
        return
    st.markdown(
        """
        <style>
        :root {
            --spt-btn-bg-top: #f8fdff;
            --spt-btn-bg-bottom: #d9f7ff;
            --spt-btn-primary-top: #eaffff;
            --spt-btn-primary-bottom: #bdf3ff;
            --spt-btn-text: #031220;
            --spt-btn-border: rgba(35, 230, 255, .96);
            --spt-btn-glow: rgba(35, 230, 255, .30);
            --spt-btn-hover-glow: rgba(35, 230, 255, .60);
        }

        /* All normal buttons, column buttons, form submit buttons and download buttons. */
        div[data-testid="stButton"] > button,
        .stButton > button,
        div[data-testid="stDownloadButton"] > button,
        .stDownloadButton > button,
        div[data-testid="stFormSubmitButton"] > button,
        div[data-testid="stFormSubmitButton"] button,
        button[data-testid="baseButton-secondary"],
        button[data-testid="baseButton-primary"],
        button[kind="secondary"],
        button[kind="primary"] {
            min-height: 44px !important;
            height: auto !important;
            width: 100% !important;
            padding: 8px 12px !important;
            border-radius: 13px !important;
            border: 1px solid var(--spt-btn-border) !important;
            background: linear-gradient(180deg, var(--spt-btn-bg-top) 0%, var(--spt-btn-bg-bottom) 100%) !important;
            color: var(--spt-btn-text) !important;
            -webkit-text-fill-color: var(--spt-btn-text) !important;
            font-size: 14.5px !important;
            font-weight: 950 !important;
            letter-spacing: .2px !important;
            line-height: 1.28 !important;
            text-align: center !important;
            white-space: normal !important;
            word-break: keep-all !important;
            overflow: visible !important;
            text-shadow: none !important;
            box-shadow:
                0 0 0 1px rgba(255,255,255,.72) inset,
                0 0 0 2px rgba(35,230,255,.14) inset,
                0 0 16px var(--spt-btn-glow) !important;
            transition: transform .10s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease !important;
        }

        div[data-testid="stButton"] > button *,
        .stButton > button *,
        div[data-testid="stDownloadButton"] > button *,
        .stDownloadButton > button *,
        div[data-testid="stFormSubmitButton"] button *,
        button[data-testid="baseButton-secondary"] *,
        button[data-testid="baseButton-primary"] * {
            color: var(--spt-btn-text) !important;
            -webkit-text-fill-color: var(--spt-btn-text) !important;
            font-weight: 950 !important;
            text-shadow: none !important;
        }

        /* Primary buttons keep the same readable style, with slightly stronger cyan body. */
        button[kind="primary"],
        button[data-testid="baseButton-primary"],
        div[data-testid="stFormSubmitButton"] button[kind="primary"] {
            background: linear-gradient(180deg, var(--spt-btn-primary-top) 0%, var(--spt-btn-primary-bottom) 100%) !important;
            border-color: #62f6ff !important;
            box-shadow:
                0 0 0 1px rgba(255,255,255,.86) inset,
                0 0 0 2px rgba(35,230,255,.22) inset,
                0 0 22px rgba(35,230,255,.42) !important;
        }

        div[data-testid="stButton"] > button:hover,
        .stButton > button:hover,
        div[data-testid="stDownloadButton"] > button:hover,
        .stDownloadButton > button:hover,
        div[data-testid="stFormSubmitButton"] button:hover,
        button[data-testid="baseButton-secondary"]:hover,
        button[data-testid="baseButton-primary"]:hover,
        button[kind="secondary"]:hover,
        button[kind="primary"]:hover {
            background: linear-gradient(180deg, #ffffff 0%, #bdf4ff 100%) !important;
            color: #020b14 !important;
            -webkit-text-fill-color: #020b14 !important;
            border-color: #8bfbff !important;
            transform: translateY(-1px) !important;
            box-shadow:
                0 0 0 1px rgba(255,255,255,.94) inset,
                0 0 0 2px rgba(35,230,255,.38) inset,
                0 0 26px var(--spt-btn-hover-glow),
                0 0 46px rgba(112,61,255,.18) !important;
        }

        div[data-testid="stButton"] > button:active,
        .stButton > button:active,
        div[data-testid="stDownloadButton"] > button:active,
        .stDownloadButton > button:active,
        div[data-testid="stFormSubmitButton"] button:active {
            transform: translateY(0) scale(.995) !important;
        }

        div[data-testid="stButton"] > button:disabled,
        .stButton > button:disabled,
        div[data-testid="stDownloadButton"] > button:disabled,
        .stDownloadButton > button:disabled,
        div[data-testid="stFormSubmitButton"] button:disabled,
        button:disabled {
            background: linear-gradient(180deg, rgba(210,222,232,.78) 0%, rgba(175,194,208,.70) 100%) !important;
            color: rgba(15,31,45,.68) !important;
            -webkit-text-fill-color: rgba(15,31,45,.68) !important;
            border-color: rgba(145,171,188,.70) !important;
            box-shadow: 0 0 0 1px rgba(255,255,255,.48) inset !important;
            opacity: .72 !important;
            transform: none !important;
            cursor: not-allowed !important;
        }

        /* Keep column groups compact and aligned like 10｜權限管理. */
        div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton,
        div[data-testid="stHorizontalBlock"] div[data-testid="column"] [data-testid="stButton"],
        div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stDownloadButton,
        div[data-testid="stHorizontalBlock"] div[data-testid="column"] [data-testid="stFormSubmitButton"] {
            margin-top: 0 !important;
            margin-bottom: 6px !important;
            overflow: visible !important;
        }

        /* Older Streamlit sometimes clips buttons inside forms/expanders. */
        div[data-testid="stForm"],
        div[data-testid="stForm"] > div,
        div[data-testid="stExpander"],
        div[data-testid="stExpander"] > div {
            overflow: visible !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v289_permission_button_standard_guard()
except Exception:
    pass

for _spt_v289_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v289_func = globals().get(_spt_v289_name)
    if callable(_spt_v289_func) and not getattr(_spt_v289_func, "_spt_v289_wrapped", False):
        def _spt_v289_make_wrapper(_original):
            def _spt_v289_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v289_permission_button_standard_guard()
                except Exception:
                    pass
                return result
            _spt_v289_wrapper._spt_v289_wrapped = True
            return _spt_v289_wrapper
        globals()[_spt_v289_name] = _spt_v289_make_wrapper(_spt_v289_func)
# ===== V2.89 PERMISSION BUTTON STANDARD GUARD END =====

# ===== V2.90 LIGHT INPUT DARK TEXT GUARD START =====
def apply_v290_light_input_dark_text_guard():
    """Keep normal text/date/number/password inputs readable on light or white fields.

    Scope is intentionally limited to native input widgets only. It does not target
    selectbox/multiselect BaseWeb select containers, data editors, buttons, or tables.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.90｜白底/淺色底輸入框文字深色防回退
           只處理一般輸入框：Text / Date / Number / Password / TextArea。
           不碰 selectbox / multiselect、表格、按鈕，避免影響既有 V2.84 下拉風格。 */

        :root {
            --spt-v290-light-input-text: #061427;
            --spt-v290-light-input-placeholder: #3c536a;
            --spt-v290-light-input-caret: #061427;
        }

        .stTextInput input,
        .stDateInput input,
        .stNumberInput input,
        .stPasswordInput input,
        .stTextArea textarea,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stNumberInputRootElement"] input,
        div[data-testid="stDateInputField"] input,
        div[data-testid="stPasswordInput"] input,
        div[data-testid="stTextArea"] textarea {
            color: var(--spt-v290-light-input-text) !important;
            -webkit-text-fill-color: var(--spt-v290-light-input-text) !important;
            caret-color: var(--spt-v290-light-input-caret) !important;
            text-shadow: none !important;
            opacity: 1 !important;
            mix-blend-mode: normal !important;
        }

        .stTextInput input::placeholder,
        .stDateInput input::placeholder,
        .stNumberInput input::placeholder,
        .stPasswordInput input::placeholder,
        .stTextArea textarea::placeholder,
        div[data-testid="stTextInputRootElement"] input::placeholder,
        div[data-testid="stNumberInputRootElement"] input::placeholder,
        div[data-testid="stDateInputField"] input::placeholder,
        div[data-testid="stPasswordInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder {
            color: var(--spt-v290-light-input-placeholder) !important;
            -webkit-text-fill-color: var(--spt-v290-light-input-placeholder) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* 明確排除 selectbox / multiselect 內部搜尋 input，維持下拉選單既有淺色顯示修正。 */
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"] {
            caret-color: #8df7ff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v290_light_input_dark_text_guard()
except Exception:
    pass

for _spt_v290_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v290_func = globals().get(_spt_v290_name)
    if callable(_spt_v290_func) and not getattr(_spt_v290_func, "_spt_v290_wrapped", False):
        def _spt_v290_make_wrapper(_original):
            def _spt_v290_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v290_light_input_dark_text_guard()
                except Exception:
                    pass
                return result
            _spt_v290_wrapper._spt_v290_wrapped = True
            return _spt_v290_wrapper
        globals()[_spt_v290_name] = _spt_v290_make_wrapper(_spt_v290_func)
# ===== V2.90 LIGHT INPUT DARK TEXT GUARD END =====

# ===== V2.91 INPUT CONTRAST AUTO GUARD START =====
def apply_v291_input_contrast_auto_guard():
    """V2.91: keep input text readable by matching field background tone.

    Rule applied conservatively:
    - Technology/dark text inputs and textareas use light text.
    - Explicit light date/number fields use dark text.
    - Data editor editable cells keep light background + dark text.
    - Selectbox/multiselect are not changed; V2.82/V2.84/V2.88/V2.90 select guards remain in charge.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.91｜輸入框依底色調整文字顏色
           深色科技底：淺色字；白底/淺色底：深色字。
           只修 input/textarea 可讀性，不動 selectbox/multiselect、按鈕、表格邏輯、權威檔讀寫。 */
        :root {
            --spt-v291-dark-field-bg-a: rgba(12, 22, 50, 0.96);
            --spt-v291-dark-field-bg-b: rgba(39, 32, 91, 0.92);
            --spt-v291-dark-field-text: #f4fdff;
            --spt-v291-dark-field-placeholder: rgba(214, 245, 255, 0.62);
            --spt-v291-light-field-bg: #f3f9ff;
            --spt-v291-light-field-text: #061427;
            --spt-v291-light-field-placeholder: rgba(20, 42, 62, 0.62);
        }

        /* 一般文字/密碼/備註輸入框：維持深色科技底，因此文字強制淺色。
           這會修正 02 關鍵字搜尋這種深底黑字看不到的問題。 */
        .stTextInput input,
        .stPasswordInput input,
        .stTextArea textarea,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stPasswordInput"] input,
        div[data-testid="stTextArea"] textarea,
        input[type="text"]:not([aria-autocomplete="list"]),
        input[type="password"],
        textarea {
            background:
                linear-gradient(100deg, transparent 0%, rgba(133,245,255,0.10) 45%, transparent 70%) -180% 0 / 180% 100% no-repeat,
                linear-gradient(135deg, var(--spt-v291-dark-field-bg-a) 0%, var(--spt-v291-dark-field-bg-b) 100%) !important;
            color: var(--spt-v291-dark-field-text) !important;
            -webkit-text-fill-color: var(--spt-v291-dark-field-text) !important;
            caret-color: #b9fbff !important;
            text-shadow: 0 0 8px rgba(107, 232, 255, 0.16) !important;
            opacity: 1 !important;
            mix-blend-mode: normal !important;
            border-color: rgba(84, 218, 255, 0.78) !important;
        }

        .stTextInput input::placeholder,
        .stPasswordInput input::placeholder,
        .stTextArea textarea::placeholder,
        div[data-testid="stTextInputRootElement"] input::placeholder,
        div[data-testid="stPasswordInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder,
        input[type="text"]:not([aria-autocomplete="list"])::placeholder,
        input[type="password"]::placeholder,
        textarea::placeholder {
            color: var(--spt-v291-dark-field-placeholder) !important;
            -webkit-text-fill-color: var(--spt-v291-dark-field-placeholder) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* 日期/數字欄通常是白底或淺色底，文字維持深色。 */
        .stDateInput input,
        .stTimeInput input,
        .stNumberInput input,
        div[data-testid="stDateInputField"] input,
        div[data-testid="stNumberInputRootElement"] input,
        input[type="date"],
        input[type="time"],
        input[type="number"] {
            background: var(--spt-v291-light-field-bg) !important;
            color: var(--spt-v291-light-field-text) !important;
            -webkit-text-fill-color: var(--spt-v291-light-field-text) !important;
            caret-color: var(--spt-v291-light-field-text) !important;
            text-shadow: none !important;
            opacity: 1 !important;
            mix-blend-mode: normal !important;
        }

        .stDateInput input::placeholder,
        .stTimeInput input::placeholder,
        .stNumberInput input::placeholder,
        div[data-testid="stDateInputField"] input::placeholder,
        div[data-testid="stNumberInputRootElement"] input::placeholder,
        input[type="date"]::placeholder,
        input[type="time"]::placeholder,
        input[type="number"]::placeholder {
            color: var(--spt-v291-light-field-placeholder) !important;
            -webkit-text-fill-color: var(--spt-v291-light-field-placeholder) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* Data editor 編輯格維持淺底深字，避免表格輸入時看不到。 */
        [data-testid="stDataEditor"] input,
        [data-testid="stDataEditor"] textarea,
        [data-testid="stDataEditor"] select,
        [data-testid="stDataEditor"] [contenteditable="true"] {
            background: var(--spt-v291-light-field-bg) !important;
            color: var(--spt-v291-light-field-text) !important;
            -webkit-text-fill-color: var(--spt-v291-light-field-text) !important;
            caret-color: var(--spt-v291-light-field-text) !important;
            text-shadow: none !important;
        }

        /* selectbox / multiselect 內部搜尋 input 不套用文字輸入框規則，保留既有下拉深底淺字修正。 */
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"] {
            background: transparent !important;
            color: #f4fdff !important;
            -webkit-text-fill-color: #f4fdff !important;
            caret-color: #8df7ff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v291_input_contrast_auto_guard()
except Exception:
    pass

for _spt_v291_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v291_func = globals().get(_spt_v291_name)
    if callable(_spt_v291_func) and not getattr(_spt_v291_func, "_spt_v291_wrapped", False):
        def _spt_v291_make_wrapper(_original):
            def _spt_v291_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v291_input_contrast_auto_guard()
                except Exception:
                    pass
                return result
            _spt_v291_wrapper._spt_v291_wrapped = True
            return _spt_v291_wrapper
        globals()[_spt_v291_name] = _spt_v291_make_wrapper(_spt_v291_func)
# ===== V2.91 INPUT CONTRAST AUTO GUARD END =====


# ===== V2.92 / V130 FINAL TEXT-COLOR ONLY CONTRAST GUARD START =====
def apply_v292_final_text_color_only_guard() -> None:
    """V130: final text-color-only guard.

    Scope:
    - Dark/glass normal inputs and all selectbox/multiselect display/search text: light text.
    - Light table/date/number editing fields: dark text.
    - No background, layout, button, data, authority-file, or table behavior changes.
    """
    st.markdown(
        """
        <style>
        /* ===== V130｜只修字色：深底淺字、淺底深字，不改功能/底色/尺寸 ===== */
        :root {
            --spt-v130-light-text: #f2fdff;
            --spt-v130-light-text-strong: #ffffff;
            --spt-v130-light-placeholder: rgba(226, 250, 255, 0.72);
            --spt-v130-dark-text: #071523;
            --spt-v130-dark-placeholder: rgba(35, 55, 74, 0.68);
            --spt-v130-caret: #8df7ff;
        }

        /* 一般深色科技感輸入框：文字改淺色。
           覆蓋 05/06/10 等頁的 text/password/textarea，不動背景、不動功能。 */
        .stTextInput input,
        .stPasswordInput input,
        .stTextArea textarea,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stPasswordInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-baseweb="input"] input:not([type="number"]):not([type="date"]):not([type="time"]),
        div[data-baseweb="textarea"] textarea,
        input[type="text"]:not([aria-autocomplete="list"]),
        input[type="password"],
        textarea {
            color: var(--spt-v130-light-text) !important;
            -webkit-text-fill-color: var(--spt-v130-light-text) !important;
            caret-color: var(--spt-v130-caret) !important;
            opacity: 1 !important;
            text-shadow: none !important;
            mix-blend-mode: normal !important;
        }

        .stTextInput input::placeholder,
        .stPasswordInput input::placeholder,
        .stTextArea textarea::placeholder,
        div[data-testid="stTextInputRootElement"] input::placeholder,
        div[data-testid="stPasswordInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder,
        div[data-baseweb="input"] input::placeholder,
        div[data-baseweb="textarea"] textarea::placeholder,
        input[type="text"]::placeholder,
        input[type="password"]::placeholder,
        textarea::placeholder {
            color: var(--spt-v130-light-placeholder) !important;
            -webkit-text-fill-color: var(--spt-v130-light-placeholder) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* selectbox / multiselect：關閉狀態已選文字、placeholder、內部搜尋文字全部改淺色。
           對應 05 製令工時分析、06 LOG查詢 Action Type、各模組下拉選單。 */
        .stSelectbox div[data-baseweb="select"],
        .stMultiSelect div[data-baseweb="select"],
        .stSelectbox div[data-baseweb="select"] *,
        .stMultiSelect div[data-baseweb="select"] *,
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] div,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"],
        div[data-baseweb="select"] [data-testid],
        div[data-baseweb="select"] [role="button"],
        div[data-baseweb="select"] [role="combobox"] {
            color: var(--spt-v130-light-text) !important;
            -webkit-text-fill-color: var(--spt-v130-light-text) !important;
            caret-color: var(--spt-v130-caret) !important;
            opacity: 1 !important;
            text-shadow: none !important;
            mix-blend-mode: normal !important;
        }

        /* 下拉箭頭 / X icon 只改顏色，不改功能。 */
        div[data-baseweb="select"] svg,
        div[data-baseweb="select"] svg path,
        div[data-baseweb="select"] [aria-label="open"] svg,
        div[data-baseweb="select"] [aria-label="clear value"] svg {
            color: var(--spt-v130-light-text) !important;
            fill: var(--spt-v130-light-text) !important;
            stroke: var(--spt-v130-light-text) !important;
        }

        /* 多選已選標籤文字改淺色。 */
        div[data-baseweb="tag"],
        div[data-baseweb="tag"] *,
        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div,
        div[data-baseweb="tag"] svg,
        div[data-baseweb="tag"] svg path {
            color: var(--spt-v130-light-text-strong) !important;
            -webkit-text-fill-color: var(--spt-v130-light-text-strong) !important;
            fill: var(--spt-v130-light-text-strong) !important;
            stroke: var(--spt-v130-light-text-strong) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* 展開後選單文字改淺色。 */
        div[data-baseweb="popover"] [role="listbox"],
        div[data-baseweb="popover"] [role="option"],
        div[data-baseweb="popover"] [role="option"] *,
        ul[role="listbox"],
        ul[role="listbox"] li,
        ul[role="listbox"] li *,
        div[role="listbox"],
        div[role="listbox"] *,
        div[role="option"],
        div[role="option"] * {
            color: var(--spt-v130-light-text) !important;
            -webkit-text-fill-color: var(--spt-v130-light-text) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        /* 淺色底欄位維持深色文字：日期/時間/數字與表格編輯格。 */
        .stDateInput input,
        .stTimeInput input,
        .stNumberInput input,
        div[data-testid="stDateInputField"] input,
        div[data-testid="stTimeInput"] input,
        div[data-testid="stNumberInputRootElement"] input,
        input[type="date"],
        input[type="time"],
        input[type="number"],
        [data-testid="stDataEditor"] input,
        [data-testid="stDataEditor"] textarea,
        [data-testid="stDataEditor"] select,
        [data-testid="stDataEditor"] [contenteditable="true"] {
            color: var(--spt-v130-dark-text) !important;
            -webkit-text-fill-color: var(--spt-v130-dark-text) !important;
            caret-color: var(--spt-v130-dark-text) !important;
            opacity: 1 !important;
            text-shadow: none !important;
            mix-blend-mode: normal !important;
        }

        .stDateInput input::placeholder,
        .stTimeInput input::placeholder,
        .stNumberInput input::placeholder,
        div[data-testid="stDateInputField"] input::placeholder,
        div[data-testid="stTimeInput"] input::placeholder,
        div[data-testid="stNumberInputRootElement"] input::placeholder,
        input[type="date"]::placeholder,
        input[type="time"]::placeholder,
        input[type="number"]::placeholder,
        [data-testid="stDataEditor"] input::placeholder,
        [data-testid="stDataEditor"] textarea::placeholder {
            color: var(--spt-v130-dark-placeholder) !important;
            -webkit-text-fill-color: var(--spt-v130-dark-placeholder) !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v292_final_text_color_only_guard()
except Exception:
    pass

for _spt_v292_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v292_func = globals().get(_spt_v292_name)
    if callable(_spt_v292_func) and not getattr(_spt_v292_func, "_spt_v292_wrapped", False):
        def _spt_v292_make_wrapper(_original):
            def _spt_v292_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v292_final_text_color_only_guard()
                except Exception:
                    pass
                return result
            _spt_v292_wrapper._spt_v292_wrapped = True
            return _spt_v292_wrapper
        globals()[_spt_v292_name] = _spt_v292_make_wrapper(_spt_v292_func)
# ===== V2.92 / V130 FINAL TEXT-COLOR ONLY CONTRAST GUARD END =====


# ===================== V167 LOGIN THEME FAST PATH FINAL OVERRIDE =====================
# 登入畫面只需要 CSS，不需要載入全域表格欄位 monkey patch。
# 進入系統後才安裝 column_settings，避免登入頁先 import pandas / 掃表格設定造成等待。
try:
    _v167_previous_apply_theme = apply_theme
except Exception:
    _v167_previous_apply_theme = None


def _v167_logged_in_for_theme() -> bool:
    try:
        return bool(st.session_state.get("auth_logged_in"))
    except Exception:
        return False


def apply_theme() -> None:  # type: ignore[override]
    _inject_css()
    _inject_multiselect_tag_height_fix()
    _clear_all_persistent_message_state()
    try:
        from services.home_ui_settings_service import inject_global_font_scale
        inject_global_font_scale()
    except Exception:
        pass
    if not _v167_logged_in_for_theme():
        return
    try:
        _clear_transient_selection_on_page_change()
    except Exception:
        pass
    try:
        from services.column_settings_service import install_column_settings_patch
        install_column_settings_patch()
    except Exception:
        pass


def app_theme() -> None:  # type: ignore[override]
    apply_theme()
# =================== END V167 LOGIN THEME FAST PATH FINAL OVERRIDE ===================
