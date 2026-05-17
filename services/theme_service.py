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
/* Data editor checkbox cells: keep clickable checkbox visible on dark table. */
[data-testid="stDataEditor"] input[type="checkbox"],
[data-testid="stDataEditor"] [role="checkbox"] {
    accent-color: #dffaff !important;
    outline: 1px solid rgba(223,250,255,.70) !important;
    box-shadow: 0 0 8px rgba(35,230,255,.22) !important;
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

# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX START =====
def apply_v259_select_multiselect_text_fix():
    """Fix clipped text in Streamlit selectbox / multiselect after global font scaling.
    Safe to call multiple times. Does not change data, filters, permissions, or calculations.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.59: BaseWeb select / multiselect text clipping final fix */
        .stSelectbox,
        .stMultiSelect {
            overflow: visible !important;
        }

        /* Outer select shell: keep enough height for larger global font scale */
        div[data-baseweb="select"] {
            min-height: 52px !important;
            height: auto !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        div[data-baseweb="select"] > div {
            min-height: 52px !important;
            height: auto !important;
            padding-top: 7px !important;
            padding-bottom: 7px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        /* Selected value / placeholder area */
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"] {
            min-height: 38px !important;
            height: auto !important;
            display: flex !important;
            align-items: center !important;
            flex-wrap: wrap !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        /* Selectbox visible text and placeholder */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] div {
            line-height: 1.45 !important;
            white-space: nowrap !important;
            text-overflow: ellipsis !important;
            color: #061427 !important;
            font-weight: 800 !important;
        }

        /* Internal search input used by BaseWeb select; avoid cropped cursor / white block */
        div[data-baseweb="select"] input {
            min-height: 32px !important;
            height: 32px !important;
            line-height: 1.45 !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: #061427 !important;
            caret-color: #061427 !important;
            font-weight: 800 !important;
            background: transparent !important;
            box-shadow: none !important;
            overflow: visible !important;
        }

        /* Multiselect selected tags */
        div[data-baseweb="tag"] {
            min-height: 32px !important;
            height: auto !important;
            padding: 5px 10px !important;
            margin: 3px 4px 3px 0 !important;
            border-radius: 9px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 1.45 !important;
            background: linear-gradient(135deg, #bff7ff 0%, #82e9ff 100%) !important;
            border: 1px solid rgba(36, 226, 255, 0.75) !important;
            color: #061427 !important;
            font-weight: 900 !important;
        }

        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            color: #061427 !important;
            font-weight: 900 !important;
            line-height: 1.45 !important;
            overflow: visible !important;
        }

        div[data-baseweb="tag"] svg {
            color: #061427 !important;
            fill: #061427 !important;
            stroke: #061427 !important;
        }

        /* Dropdown list options */
        ul[role="listbox"],
        div[role="listbox"] {
            overflow: auto !important;
        }

        ul[role="listbox"] li,
        div[role="option"] {
            min-height: 40px !important;
            height: auto !important;
            padding-top: 9px !important;
            padding-bottom: 9px !important;
            display: flex !important;
            align-items: center !important;
            line-height: 1.45 !important;
            font-weight: 800 !important;
        }

        /* Number input plus/minus should not inherit select fixes */
        div[data-testid="stNumberInput"] input {
            line-height: 1.35 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# Apply on import so every module that imports theme_service receives the fix.
try:
    apply_v259_select_multiselect_text_fix()
except Exception:
    pass
# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX END =====

# ===== V2.61 SELECT / MULTISELECT HEIGHT FINAL OVERRIDE START =====
def apply_v261_select_multiselect_height_final_fix():
    """Final override: increase select/multiselect vertical space to prevent clipped text."""
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.61: 下拉式選單高度加大，避免 Choose options / No options to select 被上下切掉 */
        .stSelectbox,
        .stMultiSelect {
            overflow: visible !important;
        }

        .stSelectbox div[data-baseweb="select"],
        .stMultiSelect div[data-baseweb="select"] {
            min-height: 62px !important;
            height: auto !important;
            overflow: visible !important;
        }

        .stSelectbox div[data-baseweb="select"] > div,
        .stMultiSelect div[data-baseweb="select"] > div {
            min-height: 62px !important;
            height: auto !important;
            padding-top: 12px !important;
            padding-bottom: 12px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
        }

        /* BaseWeb 內層文字容器：給足高度與行高 */
        .stSelectbox div[data-baseweb="select"] div[role="combobox"],
        .stMultiSelect div[data-baseweb="select"] div[role="combobox"],
        .stSelectbox div[data-baseweb="select"] div[aria-expanded],
        .stMultiSelect div[data-baseweb="select"] div[aria-expanded] {
            min-height: 38px !important;
            height: auto !important;
            line-height: 38px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
        }

        /* 顯示文字本體：不要被裁切 */
        .stSelectbox div[data-baseweb="select"] span,
        .stMultiSelect div[data-baseweb="select"] span,
        .stSelectbox div[data-baseweb="select"] p,
        .stMultiSelect div[data-baseweb="select"] p {
            line-height: 34px !important;
            min-height: 34px !important;
            height: auto !important;
            overflow: visible !important;
            display: inline-flex !important;
            align-items: center !important;
            color: #061427 !important;
            font-weight: 850 !important;
            white-space: nowrap !important;
        }

        /* 隱藏搜尋 input 不要露出白點，但保留足夠高度 */
        .stSelectbox div[data-baseweb="select"] input,
        .stMultiSelect div[data-baseweb="select"] input {
            min-height: 34px !important;
            height: 34px !important;
            line-height: 34px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: #061427 !important;
            caret-color: transparent !important;
            background: transparent !important;
            box-shadow: none !important;
            border: none !important;
            outline: none !important;
            overflow: hidden !important;
        }

        /* 多選已選標籤高度加大 */
        .stMultiSelect div[data-baseweb="tag"] {
            min-height: 36px !important;
            height: auto !important;
            padding: 7px 12px !important;
            margin: 4px 5px 4px 0 !important;
            border-radius: 10px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 1.55 !important;
            background: linear-gradient(135deg, #c9fbff 0%, #86eeff 100%) !important;
            border: 1px solid rgba(36, 226, 255, 0.85) !important;
            color: #061427 !important;
            font-weight: 900 !important;
        }

        .stMultiSelect div[data-baseweb="tag"] span,
        .stMultiSelect div[data-baseweb="tag"] div {
            line-height: 1.55 !important;
            min-height: 24px !important;
            overflow: visible !important;
            display: inline-flex !important;
            align-items: center !important;
            color: #061427 !important;
            font-weight: 900 !important;
        }

        /* 下拉選單展開後的選項高度 */
        ul[role="listbox"] li,
        div[role="option"] {
            min-height: 44px !important;
            height: auto !important;
            padding-top: 10px !important;
            padding-bottom: 10px !important;
            line-height: 1.55 !important;
            display: flex !important;
            align-items: center !important;
            font-weight: 800 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v261_select_multiselect_height_final_fix()
except Exception:
    pass
# ===== V2.61 SELECT / MULTISELECT HEIGHT FINAL OVERRIDE END =====

# === V2.62 dropdown menu light readable patch ===
def _spt_v262_dropdown_menu_light_css():
    """Force Streamlit/BaseWeb dropdown option panels to light background + dark text."""
    try:
        import streamlit as st
        st.markdown(
            """
            <style>
            /* V2.62｜權限管理與全系統下拉選單清晰化
               修正：下拉展開選單背景太深、字太暗看不到。
               範圍：selectbox / multiselect / data_editor 內 select 下拉清單。 */

            /* 下拉選單彈出層 */
            div[data-baseweb="popover"],
            div[data-baseweb="menu"],
            ul[role="listbox"] {
                background: #eaf8ff !important;
                color: #03121f !important;
                border: 1px solid rgba(102, 232, 249, .95) !important;
                box-shadow: 0 0 0 1px rgba(102, 232, 249, .35), 0 12px 32px rgba(0, 255, 255, .22) !important;
                border-radius: 12px !important;
                overflow: hidden !important;
                z-index: 999999 !important;
            }

            /* 下拉選項 */
            div[role="option"],
            li[role="option"],
            ul[role="listbox"] li,
            div[data-baseweb="menu"] div {
                background: #eaf8ff !important;
                color: #03121f !important;
                font-weight: 800 !important;
                min-height: 38px !important;
                line-height: 1.45 !important;
                padding-top: 8px !important;
                padding-bottom: 8px !important;
                text-shadow: none !important;
            }

            /* hover / focus */
            div[role="option"]:hover,
            li[role="option"]:hover,
            ul[role="listbox"] li:hover,
            div[data-baseweb="menu"] div:hover {
                background: linear-gradient(90deg, #99f6ff, #d9fbff) !important;
                color: #03121f !important;
            }

            /* selected option */
            div[aria-selected="true"],
            li[aria-selected="true"],
            div[role="option"][aria-selected="true"],
            li[role="option"][aria-selected="true"] {
                background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
                color: #020817 !important;
                font-weight: 900 !important;
            }

            /* 選項內所有文字與 icon 強制深色 */
            div[data-baseweb="popover"] *,
            div[data-baseweb="menu"] *,
            ul[role="listbox"] *,
            div[role="option"] * {
                color: #03121f !important;
                fill: #03121f !important;
                text-shadow: none !important;
            }

            /* 關閉 disabled 選項過暗問題 */
            div[aria-disabled="true"],
            li[aria-disabled="true"] {
                color: #475569 !important;
                opacity: .75 !important;
            }

            /* 保留輸入框本體淺底深字，不影響高度修正 */
            div[data-baseweb="select"] > div {
                background: #edf8ff !important;
                color: #03121f !important;
                min-height: 52px !important;
                height: auto !important;
                align-items: center !important;
                overflow: hidden !important;
            }
            div[data-baseweb="select"] input,
            div[data-baseweb="select"] span,
            div[data-baseweb="select"] div {
                color: #03121f !important;
                font-weight: 800 !important;
                line-height: 1.55 !important;
            }

            /* data_editor 下拉選單也套用 */
            [data-testid="stDataFrame"] div[role="listbox"],
            [data-testid="stDataFrame"] div[role="option"] {
                background: #eaf8ff !important;
                color: #03121f !important;
                font-weight: 800 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        pass

# Execute once at import; also wrap common theme functions if present.
_spt_v262_dropdown_menu_light_css()
for _spt_v262_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v262_func = globals().get(_spt_v262_name)
    if callable(_spt_v262_func) and not getattr(_spt_v262_func, "_spt_v262_wrapped", False):
        def _spt_v262_make_wrapper(_original):
            def _spt_v262_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                _spt_v262_dropdown_menu_light_css()
                return result
            _spt_v262_wrapper._spt_v262_wrapped = True
            return _spt_v262_wrapper
        globals()[_spt_v262_name] = _spt_v262_make_wrapper(_spt_v262_func)
# === End V2.62 dropdown menu light readable patch ===



# ===== V2.63 SELECT / MULTISELECT BOX HEIGHT ALIGN PATCH START =====
def apply_v263_select_box_left_size_fix():
    """Match the larger readable dropdown box height so text is no longer clipped."""
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.63｜讓所有下拉式選單本體高度比照左側較大的樣式，避免文字被上下裁切 */
        .stSelectbox,
        .stMultiSelect {
            overflow: visible !important;
        }

        .stSelectbox div[data-baseweb="select"],
        .stMultiSelect div[data-baseweb="select"] {
            min-height: 72px !important;
            height: auto !important;
            overflow: visible !important;
        }

        .stSelectbox div[data-baseweb="select"] > div,
        .stMultiSelect div[data-baseweb="select"] > div {
            min-height: 72px !important;
            height: auto !important;
            padding-top: 14px !important;
            padding-bottom: 14px !important;
            padding-left: 16px !important;
            padding-right: 16px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            border-radius: 14px !important;
        }

        .stSelectbox div[data-baseweb="select"] div[role="combobox"],
        .stMultiSelect div[data-baseweb="select"] div[role="combobox"],
        .stSelectbox div[data-baseweb="select"] div[aria-expanded],
        .stMultiSelect div[data-baseweb="select"] div[aria-expanded] {
            min-height: 42px !important;
            height: auto !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 42px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }

        .stSelectbox div[data-baseweb="select"] span,
        .stMultiSelect div[data-baseweb="select"] span,
        .stSelectbox div[data-baseweb="select"] p,
        .stMultiSelect div[data-baseweb="select"] p,
        .stSelectbox div[data-baseweb="select"] div,
        .stMultiSelect div[data-baseweb="select"] div {
            min-height: 42px !important;
            line-height: 42px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            white-space: nowrap !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 800 !important;
        }

        .stSelectbox div[data-baseweb="select"] input,
        .stMultiSelect div[data-baseweb="select"] input,
        .stSelectbox div[data-baseweb="select"] input[type="text"],
        .stMultiSelect div[data-baseweb="select"] input[type="text"] {
            min-height: 42px !important;
            height: 42px !important;
            line-height: 42px !important;
            margin: 0 !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }

        .stMultiSelect div[data-baseweb="tag"] {
            min-height: 38px !important;
            padding-top: 7px !important;
            padding-bottom: 7px !important;
            display: inline-flex !important;
            align-items: center !important;
        }

        .stMultiSelect div[data-baseweb="tag"] span,
        .stMultiSelect div[data-baseweb="tag"] div {
            min-height: 24px !important;
            line-height: 24px !important;
            display: inline-flex !important;
            align-items: center !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v263_select_box_left_size_fix()
except Exception:
    pass
# ===== V2.63 SELECT / MULTISELECT BOX HEIGHT ALIGN PATCH END =====


# ===== V2.64 GLOBAL SELECTBOX / MULTISELECT UNIFIED FINAL CSS START =====
def apply_v264_global_select_unified_final_css():
    """V2.64: 全系統下拉框統一高度、淺色背景、深色清楚字體，不裁切文字。"""
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.64｜所有模組 selectbox / multiselect 統一高度 + 統一淺色字體完整版 */
        .stSelectbox,
        .stMultiSelect {
            overflow: visible !important;
            min-height: 78px !important;
        }

        .stSelectbox > div,
        .stMultiSelect > div {
            overflow: visible !important;
        }

        .stSelectbox div[data-baseweb="select"],
        .stMultiSelect div[data-baseweb="select"] {
            min-height: 74px !important;
            height: auto !important;
            overflow: visible !important;
            background: transparent !important;
        }

        .stSelectbox div[data-baseweb="select"] > div,
        .stMultiSelect div[data-baseweb="select"] > div {
            min-height: 74px !important;
            height: auto !important;
            padding: 15px 18px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            border-radius: 14px !important;
            background: #edf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            border: 1px solid rgba(98, 232, 249, .65) !important;
            box-shadow: 0 0 0 1px rgba(98,232,249,.12), 0 0 12px rgba(35,230,255,.12) !important;
        }

        .stSelectbox div[data-baseweb="select"] div[role="combobox"],
        .stMultiSelect div[data-baseweb="select"] div[role="combobox"],
        .stSelectbox div[data-baseweb="select"] div[aria-expanded],
        .stMultiSelect div[data-baseweb="select"] div[aria-expanded],
        .stSelectbox div[data-baseweb="select"] div[class*="control"],
        .stMultiSelect div[data-baseweb="select"] div[class*="control"],
        .stSelectbox div[data-baseweb="select"] div[class*="valueContainer"],
        .stMultiSelect div[data-baseweb="select"] div[class*="valueContainer"] {
            min-height: 44px !important;
            height: auto !important;
            line-height: 44px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
        }

        .stSelectbox div[data-baseweb="select"] span,
        .stMultiSelect div[data-baseweb="select"] span,
        .stSelectbox div[data-baseweb="select"] p,
        .stMultiSelect div[data-baseweb="select"] p,
        .stSelectbox div[data-baseweb="select"] div,
        .stMultiSelect div[data-baseweb="select"] div {
            min-height: 44px !important;
            line-height: 44px !important;
            height: auto !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            white-space: nowrap !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-size: 17px !important;
            font-weight: 850 !important;
            text-shadow: none !important;
        }

        .stSelectbox div[data-baseweb="select"] input,
        .stMultiSelect div[data-baseweb="select"] input,
        .stSelectbox div[data-baseweb="select"] input[type="text"],
        .stMultiSelect div[data-baseweb="select"] input[type="text"] {
            min-height: 44px !important;
            height: 44px !important;
            line-height: 44px !important;
            margin: 0 !important;
            padding: 0 !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-size: 17px !important;
            font-weight: 850 !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
            caret-color: transparent !important;
        }

        .stSelectbox div[data-baseweb="select"] svg,
        .stMultiSelect div[data-baseweb="select"] svg {
            color: #03121f !important;
            fill: #03121f !important;
            width: 20px !important;
            height: 20px !important;
        }

        .stMultiSelect div[data-baseweb="tag"] {
            min-height: 40px !important;
            height: auto !important;
            padding: 8px 12px !important;
            margin: 4px 6px 4px 0 !important;
            border-radius: 10px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 24px !important;
            background: linear-gradient(135deg, #c9fbff 0%, #7ee8ff 100%) !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
            border: 1px solid rgba(36,226,255,.90) !important;
        }

        .stMultiSelect div[data-baseweb="tag"] span,
        .stMultiSelect div[data-baseweb="tag"] div {
            min-height: 24px !important;
            height: auto !important;
            line-height: 24px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
        }

        /* 展開下拉選單：淺色底、深色字、足夠高度 */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background: #eaf8ff !important;
            color: #03121f !important;
            border: 1px solid rgba(102,232,249,.95) !important;
            border-radius: 12px !important;
            box-shadow: 0 12px 32px rgba(0,255,255,.22) !important;
            overflow: hidden !important;
            z-index: 999999 !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li,
        div[data-baseweb="menu"] div {
            min-height: 44px !important;
            height: auto !important;
            padding: 10px 14px !important;
            line-height: 24px !important;
            display: flex !important;
            align-items: center !important;
            background: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-size: 16px !important;
            font-weight: 850 !important;
            text-shadow: none !important;
        }

        div[role="option"] *,
        li[role="option"] *,
        ul[role="listbox"] li *,
        div[data-baseweb="menu"] div * {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            fill: #03121f !important;
            text-shadow: none !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[data-baseweb="menu"] div:hover {
            background: linear-gradient(90deg, #99f6ff, #d9fbff) !important;
            color: #03121f !important;
        }

        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"],
        ul[role="listbox"] li[aria-selected="true"] {
            background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            font-weight: 950 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v264_global_select_unified_final_css()
except Exception:
    pass
# ===== V2.64 GLOBAL SELECTBOX / MULTISELECT UNIFIED FINAL CSS END =====


# ===== V2.65 SELECT DISPLAY ABSOLUTE HEIGHT OVERRIDE START =====
def apply_v265_select_display_absolute_height_fix():
    """Force selectbox/multiselect visible field height so text is centered and never clipped."""
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /*
          V2.65｜下拉選單顯示框高度最終覆蓋
          目的：
          1. 讓所有 selectbox / multiselect 顯示框高度一致放大
          2. 修正 Choose options / No options to select 被上下裁切
          3. 保留展開選單淺色背景與深色文字
          4. 不恢復訊息重播面板，不影響任何資料邏輯
        */

        /* 外層元件保留可見空間 */
        .stSelectbox,
        .stMultiSelect,
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"] {
            min-height: 92px !important;
            height: auto !important;
            overflow: visible !important;
        }

        /* BaseWeb select 根容器 */
        div[data-baseweb="select"] {
            min-height: 66px !important;
            height: 66px !important;
            overflow: visible !important;
            display: flex !important;
            align-items: center !important;
        }

        /* BaseWeb select 可視輸入框 */
        div[data-baseweb="select"] > div {
            min-height: 66px !important;
            height: 66px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            padding-left: 16px !important;
            padding-right: 14px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            box-sizing: border-box !important;
            border-radius: 13px !important;
            background: #edf8ff !important;
            color: #03121f !important;
        }

        /* 內層所有 flex / combobox / value container 強制置中 */
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"],
        div[data-baseweb="select"] div[class*="ValueContainer"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"] {
            min-height: 64px !important;
            height: 64px !important;
            line-height: 64px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            box-sizing: border-box !important;
        }

        /* 顯示文字本體：不要被裁切 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p {
            min-height: 32px !important;
            height: auto !important;
            line-height: 32px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            white-space: nowrap !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 850 !important;
            text-shadow: none !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }

        /* input 搜尋文字與 placeholder */
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"] {
            min-height: 36px !important;
            height: 36px !important;
            line-height: 36px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            caret-color: transparent !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
            font-weight: 850 !important;
        }

        /* 下拉箭頭置中 */
        div[data-baseweb="select"] svg {
            color: #03121f !important;
            fill: #03121f !important;
            flex-shrink: 0 !important;
        }

        /* multiselect tag 置中顯示 */
        div[data-baseweb="tag"] {
            min-height: 38px !important;
            height: 38px !important;
            padding: 0 12px !important;
            margin: 4px 6px 4px 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            line-height: 38px !important;
            overflow: visible !important;
            background: linear-gradient(135deg, #c9fbff 0%, #83edff 100%) !important;
            border: 1px solid rgba(36, 226, 255, 0.85) !important;
            border-radius: 10px !important;
            color: #03121f !important;
            font-weight: 900 !important;
        }

        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            min-height: 24px !important;
            line-height: 24px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
        }

        /* 展開選單保持淺色，文字清楚 */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background: #eaf8ff !important;
            color: #03121f !important;
            border: 1px solid rgba(102, 232, 249, .95) !important;
            box-shadow: 0 0 0 1px rgba(102, 232, 249, .35), 0 12px 32px rgba(0, 255, 255, .22) !important;
            border-radius: 12px !important;
            overflow: hidden !important;
            z-index: 999999 !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li {
            min-height: 44px !important;
            height: 44px !important;
            line-height: 44px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            background: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 850 !important;
            text-shadow: none !important;
        }

        div[role="option"] *,
        li[role="option"] *,
        ul[role="listbox"] li * {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            fill: #03121f !important;
            font-weight: 850 !important;
            text-shadow: none !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"],
        ul[role="listbox"] li[aria-selected="true"] {
            background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            font-weight: 950 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v265_select_display_absolute_height_fix()
except Exception:
    pass
# ===== V2.65 SELECT DISPLAY ABSOLUTE HEIGHT OVERRIDE END =====


# ===== V2.66 STATUS HEIGHT UNIFY ALL FILTER FIELDS START =====
def apply_v266_status_height_unify_all_filter_fields():
    """
    Use the readable Status / 狀態 field height as the system standard.
    Target: selectbox, multiselect, date input, text input, number input visible fields.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /*
          V2.66｜以「狀態 / Status」欄位高度為基準，統一所有篩選格高度
          狀態欄目前可讀高度基準：
          - 外框高度：66px
          - 內層容器：64px
          - 文字行高：32px~36px
        */
        :root {
            --spt-filter-field-height: 66px;
            --spt-filter-inner-height: 64px;
            --spt-filter-text-line: 36px;
        }

        /* Streamlit 欄位外層：給足垂直空間 */
        .stSelectbox,
        .stMultiSelect,
        .stTextInput,
        .stDateInput,
        .stNumberInput,
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"],
        div[data-testid="stTextInput"],
        div[data-testid="stDateInput"],
        div[data-testid="stNumberInput"] {
            min-height: 94px !important;
            height: auto !important;
            overflow: visible !important;
        }

        /* Select / Multiselect 可視欄位：全部比照 Status 欄位高度 */
        div[data-baseweb="select"] {
            min-height: var(--spt-filter-field-height) !important;
            height: var(--spt-filter-field-height) !important;
            overflow: visible !important;
            display: flex !important;
            align-items: center !important;
        }

        div[data-baseweb="select"] > div {
            min-height: var(--spt-filter-field-height) !important;
            height: var(--spt-filter-field-height) !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            padding-left: 16px !important;
            padding-right: 16px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            box-sizing: border-box !important;
            border-radius: 13px !important;
            background: #edf8ff !important;
            color: #03121f !important;
        }

        /* BaseWeb 內層容器：修正文字像凹進去、被裁切 */
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"],
        div[data-baseweb="select"] div[class*="ValueContainer"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"] {
            min-height: var(--spt-filter-inner-height) !important;
            height: var(--spt-filter-inner-height) !important;
            line-height: var(--spt-filter-inner-height) !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            box-sizing: border-box !important;
        }

        /* Select / Multiselect 顯示文字 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p {
            min-height: var(--spt-filter-text-line) !important;
            line-height: var(--spt-filter-text-line) !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            white-space: nowrap !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 850 !important;
            text-shadow: none !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }

        /* Select / Multiselect 內部搜尋 input */
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"] {
            min-height: var(--spt-filter-text-line) !important;
            height: var(--spt-filter-text-line) !important;
            line-height: var(--spt-filter-text-line) !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            caret-color: transparent !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
            font-weight: 850 !important;
        }

        /* Text / Date / Number input 也統一高度 */
        div[data-baseweb="input"],
        div[data-baseweb="base-input"] {
            min-height: var(--spt-filter-field-height) !important;
            height: var(--spt-filter-field-height) !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            border-radius: 13px !important;
            background: #edf8ff !important;
        }

        div[data-baseweb="input"] input,
        div[data-baseweb="base-input"] input,
        .stTextInput input,
        .stDateInput input,
        .stNumberInput input {
            min-height: var(--spt-filter-text-line) !important;
            height: var(--spt-filter-text-line) !important;
            line-height: var(--spt-filter-text-line) !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 850 !important;
        }

        /* Multiselect 已選標籤高度 */
        div[data-baseweb="tag"] {
            min-height: 40px !important;
            height: 40px !important;
            padding: 0 12px !important;
            margin: 4px 6px 4px 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            line-height: 40px !important;
            overflow: visible !important;
            background: linear-gradient(135deg, #c9fbff 0%, #83edff 100%) !important;
            border: 1px solid rgba(36, 226, 255, 0.85) !important;
            border-radius: 10px !important;
            color: #03121f !important;
            font-weight: 900 !important;
        }

        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            min-height: 24px !important;
            line-height: 24px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
        }

        /* 下拉展開選單：淺色背景，字清楚 */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background: #eaf8ff !important;
            color: #03121f !important;
            border: 1px solid rgba(102, 232, 249, .95) !important;
            box-shadow: 0 0 0 1px rgba(102, 232, 249, .35), 0 12px 32px rgba(0, 255, 255, .22) !important;
            border-radius: 12px !important;
            overflow: hidden !important;
            z-index: 999999 !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li {
            min-height: 44px !important;
            height: 44px !important;
            line-height: 44px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            background: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 850 !important;
            text-shadow: none !important;
        }

        div[role="option"] *,
        li[role="option"] *,
        ul[role="listbox"] li * {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            fill: #03121f !important;
            font-weight: 850 !important;
            text-shadow: none !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"],
        ul[role="listbox"] li[aria-selected="true"] {
            background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            font-weight: 950 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v266_status_height_unify_all_filter_fields()
except Exception:
    pass
# ===== V2.66 STATUS HEIGHT UNIFY ALL FILTER FIELDS END =====


# ===== V2.67 SELECT HEIGHT 70 MENU TEXT VISIBLE FINAL START =====
def apply_v267_select_height_70_menu_text_visible_final():
    """
    Final override requested:
    - Outer select/multiselect frame height: 70px
    - Inner container height: 66px
    - Text line-height: 36px
    - Placeholder text layer brought to front
    - Dropdown option panel forced to light background + dark readable text
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /*
          V2.67｜下拉框尺寸指定版
          製令、P/N、機型、組立地點、工段、工號、姓名等篩選欄位統一：
          外框高度 70px｜內層容器 66px｜文字行高 36px
        */
        :root {
            --spt-select-outer-h: 70px;
            --spt-select-inner-h: 66px;
            --spt-select-line-h: 36px;
        }

        /* 元件外層：避免 labels 與欄位互相壓縮 */
        .stSelectbox,
        .stMultiSelect,
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"] {
            min-height: 96px !important;
            height: auto !important;
            overflow: visible !important;
        }

        /* select / multiselect 根容器 */
        div[data-baseweb="select"] {
            min-height: var(--spt-select-outer-h) !important;
            height: var(--spt-select-outer-h) !important;
            overflow: visible !important;
            display: flex !important;
            align-items: center !important;
            position: relative !important;
            z-index: 2 !important;
        }

        /* select / multiselect 可視外框 */
        div[data-baseweb="select"] > div {
            min-height: var(--spt-select-outer-h) !important;
            height: var(--spt-select-outer-h) !important;
            padding-top: 2px !important;
            padding-bottom: 2px !important;
            padding-left: 16px !important;
            padding-right: 16px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            box-sizing: border-box !important;
            border-radius: 13px !important;
            background: #edf8ff !important;
            color: #03121f !important;
            position: relative !important;
            z-index: 2 !important;
        }

        /* BaseWeb 內層容器：使用 66px，讓文字不再凹陷或被切 */
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"],
        div[data-baseweb="select"] div[class*="ValueContainer"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"] {
            min-height: var(--spt-select-inner-h) !important;
            height: var(--spt-select-inner-h) !important;
            line-height: var(--spt-select-inner-h) !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            box-sizing: border-box !important;
            position: relative !important;
            z-index: 5 !important;
        }

        /* 預設文字 Choose options / No options to select：提高圖層，避免被蓋住 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"] {
            min-height: var(--spt-select-line-h) !important;
            height: var(--spt-select-line-h) !important;
            line-height: var(--spt-select-line-h) !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            white-space: nowrap !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
            text-shadow: none !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            position: relative !important;
            z-index: 20 !important;
            opacity: 1 !important;
        }

        /* input 搜尋層：透明但保留高度，不擋住文字 */
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete="list"] {
            min-height: var(--spt-select-line-h) !important;
            height: var(--spt-select-line-h) !important;
            line-height: var(--spt-select-line-h) !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            caret-color: transparent !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
            font-weight: 900 !important;
            position: relative !important;
            z-index: 10 !important;
        }

        /* 下拉箭頭置中 */
        div[data-baseweb="select"] svg {
            color: #03121f !important;
            fill: #03121f !important;
            flex-shrink: 0 !important;
            position: relative !important;
            z-index: 25 !important;
        }

        /* multiselect 已選標籤 */
        div[data-baseweb="tag"] {
            min-height: 40px !important;
            height: 40px !important;
            padding: 0 12px !important;
            margin: 4px 6px 4px 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            line-height: 40px !important;
            overflow: visible !important;
            background: linear-gradient(135deg, #c9fbff 0%, #83edff 100%) !important;
            border: 1px solid rgba(36, 226, 255, 0.85) !important;
            border-radius: 10px !important;
            color: #03121f !important;
            font-weight: 900 !important;
            position: relative !important;
            z-index: 18 !important;
        }

        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            min-height: 24px !important;
            line-height: 24px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
            opacity: 1 !important;
        }

        /*
          展開後的下拉清單：
          你截圖裡選項文字看不到，是因為 popover/menu 內部仍吃到深色或透明樣式。
          這裡強制所有選項與子元素為淺底深字。
        */
        div[data-baseweb="popover"],
        div[data-baseweb="popover"] > div,
        div[data-baseweb="menu"],
        div[data-baseweb="menu"] > div,
        ul[role="listbox"],
        ul[role="listbox"] > div {
            background: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            border-color: rgba(102, 232, 249, .95) !important;
            text-shadow: none !important;
            opacity: 1 !important;
            z-index: 999999 !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li,
        div[data-baseweb="menu"] div[role="option"] {
            min-height: 46px !important;
            height: 46px !important;
            line-height: 46px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            padding-left: 14px !important;
            padding-right: 14px !important;
            display: flex !important;
            align-items: center !important;
            background: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
            text-shadow: none !important;
            opacity: 1 !important;
        }

        div[role="option"] *,
        li[role="option"] *,
        ul[role="listbox"] li *,
        div[data-baseweb="menu"] *,
        div[data-baseweb="popover"] * {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            fill: #03121f !important;
            font-weight: 900 !important;
            text-shadow: none !important;
            opacity: 1 !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"],
        ul[role="listbox"] li[aria-selected="true"] {
            background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            font-weight: 950 !important;
        }

        div[role="option"]:hover *,
        li[role="option"]:hover *,
        ul[role="listbox"] li:hover *,
        div[role="option"][aria-selected="true"] *,
        li[role="option"][aria-selected="true"] *,
        ul[role="listbox"] li[aria-selected="true"] * {
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            fill: #020817 !important;
            font-weight: 950 !important;
            opacity: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v267_select_height_70_menu_text_visible_final()
except Exception:
    pass
# ===== V2.67 SELECT HEIGHT 70 MENU TEXT VISIBLE FINAL END =====


# ===== V2.68 FORCE DROPDOWN REAL DOM FIX START =====
def apply_v268_force_dropdown_real_dom_fix():
    """
    V2.68 hard override for Streamlit/BaseWeb dropdowns.
    This version targets the real nested BaseWeb structure more aggressively:
    - div[data-baseweb="select"] and every direct child layer
    - role="combobox"
    - aria-haspopup="listbox"
    - input and placeholder layers
    - popover/listbox/option text layers
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style id="spt-v268-force-dropdown-real-dom-fix">
        /*
        V2.68｜真正強制下拉框高度與文字可見
        原因：前版只改部分層級，BaseWeb 內層 valueContainer/inputContainer 仍維持原高度，
        所以外觀看起來沒變，文字仍被裁切。這版直接鎖定所有 real DOM 層級。
        */

        /* 先避免舊版 CSS 的 overflow:hidden 繼續裁切 */
        .stSelectbox, .stMultiSelect,
        div[data-testid="stSelectbox"], div[data-testid="stMultiSelect"],
        div[data-testid="stSelectbox"] *, div[data-testid="stMultiSelect"] * {
            overflow: visible !important;
        }

        /* Streamlit widget wrapper 給足高度 */
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"] {
            min-height: 104px !important;
            height: auto !important;
        }

        /* Select 根元件與可點擊框：真正設定 70px */
        div[data-baseweb="select"],
        div[data-testid="stSelectbox"] div[data-baseweb="select"],
        div[data-testid="stMultiSelect"] div[data-baseweb="select"] {
            min-height: 70px !important;
            height: 70px !important;
            max-height: none !important;
            display: flex !important;
            align-items: center !important;
            background: #edf8ff !important;
            border-radius: 14px !important;
            box-sizing: border-box !important;
            overflow: visible !important;
        }

        div[data-baseweb="select"] > div,
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] > div > div > div,
        div[data-baseweb="select"] div[aria-haspopup="listbox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[role="combobox"] {
            min-height: 66px !important;
            height: 66px !important;
            max-height: none !important;
            line-height: 66px !important;
            display: flex !important;
            align-items: center !important;
            align-content: center !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            box-sizing: border-box !important;
            background: #edf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            overflow: visible !important;
        }

        /* BaseWeb 常用 class 名會變動，用 class* 抓 value / placeholder / input container */
        div[data-baseweb="select"] div[class*="Value"],
        div[data-baseweb="select"] div[class*="value"],
        div[data-baseweb="select"] div[class*="Placeholder"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Input"],
        div[data-baseweb="select"] div[class*="input"] {
            min-height: 66px !important;
            height: 66px !important;
            max-height: none !important;
            line-height: 66px !important;
            display: flex !important;
            align-items: center !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            overflow: visible !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            background: transparent !important;
        }

        /* 顯示文字：36px 行高，深色粗體 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] label {
            min-height: 36px !important;
            height: 36px !important;
            line-height: 36px !important;
            display: inline-flex !important;
            align-items: center !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-size: 16px !important;
            font-weight: 900 !important;
            text-shadow: none !important;
            opacity: 1 !important;
            transform: none !important;
            position: relative !important;
            top: 0 !important;
            z-index: 50 !important;
            overflow: visible !important;
        }

        /* 搜尋 input 不得把 placeholder 蓋黑或裁切 */
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete],
        div[data-baseweb="select"] input[role="combobox"] {
            min-height: 36px !important;
            height: 36px !important;
            line-height: 36px !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-size: 16px !important;
            font-weight: 900 !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            outline: none !important;
            opacity: 1 !important;
            caret-color: transparent !important;
            z-index: 40 !important;
            overflow: visible !important;
        }

        div[data-baseweb="select"] input::placeholder {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            opacity: 1 !important;
            font-size: 16px !important;
            font-weight: 900 !important;
        }

        /* 箭頭 */
        div[data-baseweb="select"] svg,
        div[data-baseweb="select"] [role="button"] svg {
            color: #03121f !important;
            fill: #03121f !important;
            z-index: 80 !important;
        }

        /* MultiSelect tag */
        div[data-baseweb="tag"] {
            min-height: 42px !important;
            height: 42px !important;
            line-height: 42px !important;
            padding: 0 12px !important;
            margin: 4px 6px 4px 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            background: linear-gradient(135deg, #c9fbff, #83edff) !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-weight: 900 !important;
            border: 1px solid rgba(36, 226, 255, 0.85) !important;
            border-radius: 10px !important;
            opacity: 1 !important;
            overflow: visible !important;
        }

        div[data-baseweb="tag"] * {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            fill: #03121f !important;
            font-weight: 900 !important;
            opacity: 1 !important;
        }

        /* 展開後的下拉選單：強制淺底深字 */
        div[data-baseweb="popover"],
        div[data-baseweb="popover"] *,
        div[data-baseweb="menu"],
        div[data-baseweb="menu"] *,
        ul[role="listbox"],
        ul[role="listbox"] * {
            background-color: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            text-shadow: none !important;
            opacity: 1 !important;
        }

        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            border: 1px solid rgba(102, 232, 249, .95) !important;
            border-radius: 12px !important;
            box-shadow: 0 0 0 1px rgba(102,232,249,.35), 0 12px 32px rgba(0,255,255,.22) !important;
            z-index: 999999 !important;
            overflow-y: auto !important;
        }

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li {
            min-height: 46px !important;
            height: 46px !important;
            line-height: 46px !important;
            display: flex !important;
            align-items: center !important;
            padding: 0 14px !important;
            background: #eaf8ff !important;
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            font-size: 16px !important;
            font-weight: 900 !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }

        div[role="option"] *,
        li[role="option"] * {
            color: #03121f !important;
            -webkit-text-fill-color: #03121f !important;
            fill: #03121f !important;
            font-size: 16px !important;
            font-weight: 900 !important;
            opacity: 1 !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"] {
            background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
        }

        div[role="option"]:hover *,
        li[role="option"]:hover *,
        div[role="option"][aria-selected="true"] *,
        li[role="option"][aria-selected="true"] * {
            background: transparent !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            fill: #020817 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v268_force_dropdown_real_dom_fix()
except Exception:
    pass
# ===== V2.68 FORCE DROPDOWN REAL DOM FIX END =====


# ===== V2.69 USER CONFIGURABLE DROPDOWN SIZE START =====
from pathlib import Path as _SPTPath
import json as _spt_json

_SPT_UI_DROPDOWN_DEFAULTS = {
    "enabled": True,
    "outer_height": 70,
    "inner_height": 66,
    "text_line_height": 36,
    "font_size": 16,
    "option_height": 46,
    "tag_height": 40,
    "panel_bg": "#eaf8ff",
    "field_bg": "#edf8ff",
    "text_color": "#03121f",
}

def _spt_dropdown_settings_paths():
    try:
        root = PROJECT_ROOT
    except Exception:
        root = _SPTPath(__file__).resolve().parents[1]
    return [
        root / "data" / "config" / "ui_dropdown_settings.json",
        root / "data" / "persistent_state" / "ui_dropdown_settings.json",
        root / "data" / "persistent_modules" / "13_system_settings" / "ui_dropdown_settings.json",
    ]

def _spt_load_dropdown_settings():
    cfg = dict(_SPT_UI_DROPDOWN_DEFAULTS)
    for p in _spt_dropdown_settings_paths():
        try:
            if p.exists():
                raw = _spt_json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg.update(raw)
                    break
        except Exception:
            pass
    # Clamp values to safe ranges.
    def _int(name, lo, hi):
        try:
            v = int(cfg.get(name, _SPT_UI_DROPDOWN_DEFAULTS[name]))
        except Exception:
            v = _SPT_UI_DROPDOWN_DEFAULTS[name]
        return max(lo, min(hi, v))
    cfg["outer_height"] = _int("outer_height", 48, 120)
    cfg["inner_height"] = _int("inner_height", 42, 116)
    cfg["text_line_height"] = _int("text_line_height", 24, 72)
    cfg["font_size"] = _int("font_size", 12, 28)
    cfg["option_height"] = _int("option_height", 32, 90)
    cfg["tag_height"] = _int("tag_height", 28, 72)
    cfg["enabled"] = bool(cfg.get("enabled", True))
    return cfg

def _spt_save_dropdown_settings(cfg):
    for p in _spt_dropdown_settings_paths():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_spt_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

def apply_v269_configurable_dropdown_css():
    """Apply dropdown size CSS from persistent settings."""
    try:
        import streamlit as st
    except Exception:
        return
    cfg = _spt_load_dropdown_settings()
    if not cfg.get("enabled", True):
        return
    outer = int(cfg["outer_height"])
    inner = int(cfg["inner_height"])
    line = int(cfg["text_line_height"])
    font = int(cfg["font_size"])
    option = int(cfg["option_height"])
    tag = int(cfg["tag_height"])
    field_bg = str(cfg.get("field_bg", "#edf8ff"))
    panel_bg = str(cfg.get("panel_bg", "#eaf8ff"))
    text_color = str(cfg.get("text_color", "#03121f"))

    st.markdown(
        f"""
        <style id="spt-v269-configurable-dropdown-css">
        /*
          V2.69｜可自行設定下拉選單尺寸
          目前設定：外框 {outer}px｜內層 {inner}px｜文字行高 {line}px｜字體 {font}px
        */
        .stSelectbox,
        .stMultiSelect,
        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"] {{
            min-height: {outer + 28}px !important;
            height: auto !important;
            overflow: visible !important;
        }}

        div[data-baseweb="select"],
        div[data-testid="stSelectbox"] div[data-baseweb="select"],
        div[data-testid="stMultiSelect"] div[data-baseweb="select"] {{
            min-height: {outer}px !important;
            height: {outer}px !important;
            max-height: none !important;
            display: flex !important;
            align-items: center !important;
            background: {field_bg} !important;
            border-radius: 14px !important;
            box-sizing: border-box !important;
            overflow: visible !important;
        }}

        div[data-baseweb="select"] > div,
        div[data-baseweb="select"] > div > div,
        div[data-baseweb="select"] > div > div > div,
        div[data-baseweb="select"] div[aria-haspopup="listbox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[class*="Value"],
        div[data-baseweb="select"] div[class*="value"],
        div[data-baseweb="select"] div[class*="Placeholder"],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Input"],
        div[data-baseweb="select"] div[class*="input"] {{
            min-height: {inner}px !important;
            height: {inner}px !important;
            max-height: none !important;
            line-height: {inner}px !important;
            display: flex !important;
            align-items: center !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            background: {field_bg} !important;
            overflow: visible !important;
            box-sizing: border-box !important;
        }}

        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] label,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input[type="text"],
        div[data-baseweb="select"] input[aria-autocomplete],
        div[data-baseweb="select"] input[role="combobox"] {{
            min-height: {line}px !important;
            height: {line}px !important;
            line-height: {line}px !important;
            display: inline-flex !important;
            align-items: center !important;
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            font-size: {font}px !important;
            font-weight: 900 !important;
            text-shadow: none !important;
            opacity: 1 !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            outline: none !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            overflow: visible !important;
            white-space: nowrap !important;
            position: relative !important;
            z-index: 80 !important;
        }}

        div[data-baseweb="select"] input::placeholder {{
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            opacity: 1 !important;
            font-size: {font}px !important;
            font-weight: 900 !important;
        }}

        div[data-baseweb="select"] svg,
        div[data-baseweb="select"] [role="button"] svg {{
            color: {text_color} !important;
            fill: {text_color} !important;
            z-index: 90 !important;
        }}

        div[data-baseweb="tag"] {{
            min-height: {tag}px !important;
            height: {tag}px !important;
            line-height: {tag}px !important;
            padding: 0 12px !important;
            margin: 4px 6px 4px 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            background: linear-gradient(135deg, #c9fbff, #83edff) !important;
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            font-weight: 900 !important;
            border: 1px solid rgba(36, 226, 255, 0.85) !important;
            border-radius: 10px !important;
            opacity: 1 !important;
            overflow: visible !important;
        }}

        div[data-baseweb="tag"] * {{
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            fill: {text_color} !important;
            font-weight: 900 !important;
            opacity: 1 !important;
            background: transparent !important;
        }}

        div[data-baseweb="popover"],
        div[data-baseweb="popover"] *,
        div[data-baseweb="menu"],
        div[data-baseweb="menu"] *,
        ul[role="listbox"],
        ul[role="listbox"] * {{
            background-color: {panel_bg} !important;
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            text-shadow: none !important;
            opacity: 1 !important;
        }}

        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {{
            border: 1px solid rgba(102, 232, 249, .95) !important;
            border-radius: 12px !important;
            box-shadow: 0 0 0 1px rgba(102,232,249,.35), 0 12px 32px rgba(0,255,255,.22) !important;
            z-index: 999999 !important;
            overflow-y: auto !important;
        }}

        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li {{
            min-height: {option}px !important;
            height: {option}px !important;
            line-height: {option}px !important;
            display: flex !important;
            align-items: center !important;
            padding: 0 14px !important;
            background: {panel_bg} !important;
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            font-size: {font}px !important;
            font-weight: 900 !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }}

        div[role="option"] *,
        li[role="option"] * {{
            color: {text_color} !important;
            -webkit-text-fill-color: {text_color} !important;
            fill: {text_color} !important;
            font-size: {font}px !important;
            font-weight: 900 !important;
            opacity: 1 !important;
            background: transparent !important;
        }}

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"] {{
            background: linear-gradient(90deg, #67e8f9, #c4f7ff) !important;
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
        }}

        div[role="option"]:hover *,
        li[role="option"]:hover *,
        div[role="option"][aria-selected="true"] *,
        li[role="option"][aria-selected="true"] * {{
            color: #020817 !important;
            -webkit-text-fill-color: #020817 !important;
            fill: #020817 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def render_dropdown_size_settings_panel():
    """Hidden admin-style panel for tuning dropdown sizes. Safe to call on every page."""
    try:
        import streamlit as st
    except Exception:
        return

    # 避免同一頁多次 render。
    if st.session_state.get("_spt_v269_dropdown_panel_rendered"):
        return
    st.session_state["_spt_v269_dropdown_panel_rendered"] = True

    cfg = _spt_load_dropdown_settings()
    with st.sidebar.expander("▾ 下拉選單尺寸設定", expanded=False):
        st.caption("隱藏設定區｜調整後按永久套用，所有模組共用。")
        enabled = st.checkbox("啟用自訂下拉尺寸", value=bool(cfg.get("enabled", True)), key="spt_dd_enabled")
        outer = st.slider("外框高度 px", 48, 120, int(cfg["outer_height"]), 1, key="spt_dd_outer")
        inner = st.slider("內層容器 px", 42, 116, int(cfg["inner_height"]), 1, key="spt_dd_inner")
        line = st.slider("文字行高 px", 24, 72, int(cfg["text_line_height"]), 1, key="spt_dd_line")
        font = st.slider("字體大小 px", 12, 28, int(cfg["font_size"]), 1, key="spt_dd_font")
        option = st.slider("展開選項高度 px", 32, 90, int(cfg["option_height"]), 1, key="spt_dd_option")
        tag = st.slider("多選標籤高度 px", 28, 72, int(cfg["tag_height"]), 1, key="spt_dd_tag")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("▣ 永久套用", key="spt_dd_save", use_container_width=True):
                new_cfg = {
                    "enabled": enabled,
                    "outer_height": int(outer),
                    "inner_height": int(inner),
                    "text_line_height": int(line),
                    "font_size": int(font),
                    "option_height": int(option),
                    "tag_height": int(tag),
                    "panel_bg": "#eaf8ff",
                    "field_bg": "#edf8ff",
                    "text_color": "#03121f",
                }
                _spt_save_dropdown_settings(new_cfg)
                st.success("下拉選單尺寸已永久記錄。請重新整理或切換頁面後套用。")
        with col2:
            if st.button("↺ 預設值", key="spt_dd_reset", use_container_width=True):
                _spt_save_dropdown_settings(dict(_SPT_UI_DROPDOWN_DEFAULTS))
                st.success("已恢復下拉選單預設尺寸。請重新整理或切換頁面後套用。")

# Apply CSS and render hidden panel on import.
try:
    apply_v269_configurable_dropdown_css()
except Exception:
    pass

try:
    render_dropdown_size_settings_panel()
except Exception:
    pass
# ===== V2.69 USER CONFIGURABLE DROPDOWN SIZE END =====


# ===== V2.70 MAIN PAGE DROPDOWN SIZE PANEL FALLBACK START =====
def render_dropdown_size_settings_panel_main_fallback():
    """
    V2.70:
    Some Streamlit deployments do not show widgets rendered in st.sidebar from imported theme modules.
    This fallback renders a collapsed panel in the main page so the setting is always visible.
    """
    try:
        import streamlit as st
    except Exception:
        return

    # One panel per page render.
    if st.session_state.get("_spt_v270_dropdown_main_panel_rendered"):
        return
    st.session_state["_spt_v270_dropdown_main_panel_rendered"] = True

    cfg = _spt_load_dropdown_settings()

    with st.expander("⚙ 下拉選單尺寸設定 / Dropdown Size Settings（收合）", expanded=False):
        st.caption("此設定會永久保存，所有模組共用。若下拉文字被切掉，先把外框高度與內層容器調大。")

        c1, c2, c3 = st.columns(3)
        with c1:
            enabled = st.checkbox("啟用自訂尺寸", value=bool(cfg.get("enabled", True)), key="spt_v270_dd_enabled")
            outer = st.number_input("外框高度 px", min_value=48, max_value=140, value=int(cfg.get("outer_height", 70)), step=1, key="spt_v270_dd_outer")
            inner = st.number_input("內層容器 px", min_value=42, max_value=136, value=int(cfg.get("inner_height", 66)), step=1, key="spt_v270_dd_inner")
        with c2:
            line = st.number_input("文字行高 px", min_value=24, max_value=90, value=int(cfg.get("text_line_height", 36)), step=1, key="spt_v270_dd_line")
            font = st.number_input("字體大小 px", min_value=12, max_value=32, value=int(cfg.get("font_size", 16)), step=1, key="spt_v270_dd_font")
            option = st.number_input("展開選項高度 px", min_value=32, max_value=110, value=int(cfg.get("option_height", 46)), step=1, key="spt_v270_dd_option")
        with c3:
            tag = st.number_input("多選標籤高度 px", min_value=28, max_value=90, value=int(cfg.get("tag_height", 40)), step=1, key="spt_v270_dd_tag")
            st.markdown(
                f"""
                <div style="margin-top:8px;padding:12px;border-radius:12px;background:#edf8ff;color:#03121f;font-weight:900;">
                    預覽高度：外框 {int(outer)}px｜內層 {int(inner)}px｜文字 {int(line)}px
                </div>
                """,
                unsafe_allow_html=True,
            )

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("▣ 永久套用下拉尺寸", key="spt_v270_dd_save", use_container_width=True):
                new_cfg = {
                    "enabled": bool(enabled),
                    "outer_height": int(outer),
                    "inner_height": int(inner),
                    "text_line_height": int(line),
                    "font_size": int(font),
                    "option_height": int(option),
                    "tag_height": int(tag),
                    "panel_bg": "#eaf8ff",
                    "field_bg": "#edf8ff",
                    "text_color": "#03121f",
                }
                _spt_save_dropdown_settings(new_cfg)
                st.success("下拉選單尺寸已永久保存。請按重新整理或切換頁面後生效。")
        with b2:
            if st.button("↺ 恢復建議值", key="spt_v270_dd_recommended", use_container_width=True):
                new_cfg = dict(_SPT_UI_DROPDOWN_DEFAULTS)
                new_cfg.update({
                    "outer_height": 80,
                    "inner_height": 76,
                    "text_line_height": 40,
                    "font_size": 17,
                    "option_height": 50,
                    "tag_height": 42,
                })
                _spt_save_dropdown_settings(new_cfg)
                st.success("已套用建議值：外框80、內層76、文字40、字體17。請重新整理或切換頁面後生效。")
        with b3:
            if st.button("↺ 恢復預設值", key="spt_v270_dd_reset", use_container_width=True):
                _spt_save_dropdown_settings(dict(_SPT_UI_DROPDOWN_DEFAULTS))
                st.success("已恢復預設值。請重新整理或切換頁面後生效。")

# Render the main-page fallback after CSS is applied.
try:
    render_dropdown_size_settings_panel_main_fallback()
except Exception:
    pass
# ===== V2.70 MAIN PAGE DROPDOWN SIZE PANEL FALLBACK END =====


# ===== V2.79 FUTURE CYBER FIELD UI START =====
def apply_v279_future_cyber_field_ui():
    """Future-cyber UI for select / multiselect / input fields.
    Goal: reduce flat white blocks, restore professional futuristic glass look,
    while preserving strong text contrast and readable dropdown options.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.79｜Future cyber field UI */
        :root {
            --spt-v279-field-bg1: rgba(7, 20, 44, 0.92);
            --spt-v279-field-bg2: rgba(13, 34, 68, 0.88);
            --spt-v279-field-bg3: rgba(8, 18, 39, 0.95);
            --spt-v279-text: #eefbff;
            --spt-v279-text-soft: #bfefff;
            --spt-v279-text-dim: #85b9d8;
            --spt-v279-border: rgba(84, 221, 255, 0.78);
            --spt-v279-border-soft: rgba(84, 221, 255, 0.32);
            --spt-v279-glow-1: rgba(0, 225, 255, 0.20);
            --spt-v279-glow-2: rgba(75, 122, 255, 0.18);
            --spt-v279-menu-bg: rgba(7, 19, 41, 0.96);
            --spt-v279-menu-bg-2: rgba(11, 29, 56, 0.98);
            --spt-v279-active: linear-gradient(90deg, rgba(79, 233, 255, 0.94), rgba(108, 144, 255, 0.94));
        }

        @keyframes sptV279Breath {
            0% {
                box-shadow:
                    inset 0 1px 0 rgba(255,255,255,0.08),
                    0 0 0 1px rgba(84, 221, 255, 0.18),
                    0 0 10px rgba(0, 225, 255, 0.10),
                    0 0 24px rgba(57, 112, 255, 0.08),
                    0 10px 22px rgba(0, 0, 0, 0.26);
            }
            50% {
                box-shadow:
                    inset 0 1px 0 rgba(255,255,255,0.14),
                    0 0 0 1px rgba(84, 221, 255, 0.34),
                    0 0 16px rgba(0, 225, 255, 0.16),
                    0 0 30px rgba(57, 112, 255, 0.14),
                    0 14px 28px rgba(0, 0, 0, 0.30);
            }
            100% {
                box-shadow:
                    inset 0 1px 0 rgba(255,255,255,0.08),
                    0 0 0 1px rgba(84, 221, 255, 0.18),
                    0 0 10px rgba(0, 225, 255, 0.10),
                    0 0 24px rgba(57, 112, 255, 0.08),
                    0 10px 22px rgba(0, 0, 0, 0.26);
            }
        }

        /* 外層保留空間，讓光暈不被切掉 */
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

        /* Select / multiselect 可視欄位 */
        div[data-baseweb="select"] > div {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.01) 16%, rgba(255,255,255,0.00) 17%),
                linear-gradient(135deg, var(--spt-v279-field-bg1) 0%, var(--spt-v279-field-bg2) 56%, var(--spt-v279-field-bg3) 100%) !important;
            border: 1px solid var(--spt-v279-border) !important;
            border-radius: 16px !important;
            color: var(--spt-v279-text) !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.08),
                0 0 0 1px var(--spt-v279-border-soft),
                0 0 14px var(--spt-v279-glow-1),
                0 0 28px var(--spt-v279-glow-2),
                0 10px 24px rgba(0,0,0,0.28) !important;
            animation: sptV279Breath 3.6s ease-in-out infinite !important;
            backdrop-filter: blur(10px) saturate(125%) !important;
            -webkit-backdrop-filter: blur(10px) saturate(125%) !important;
        }

        div[data-baseweb="select"] > div:hover {
            border-color: rgba(112, 236, 255, 0.95) !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.12),
                0 0 0 1px rgba(112, 236, 255, 0.28),
                0 0 18px rgba(0, 225, 255, 0.18),
                0 0 36px rgba(74, 119, 255, 0.16),
                0 14px 28px rgba(0,0,0,0.32) !important;
        }

        div[data-baseweb="select"] > div:focus-within {
            border-color: #72f5ff !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.14),
                0 0 0 1px rgba(114, 245, 255, 0.30),
                0 0 20px rgba(0, 235, 255, 0.22),
                0 0 40px rgba(92, 133, 255, 0.20),
                0 14px 28px rgba(0,0,0,0.34) !important;
        }

        /* 內部文字 / placeholder / input 全部改為淺色，避免慘白外框效果 */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] input,
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="placeholder"],
        div[data-baseweb="select"] div[class*="Placeholder"],
        div[data-baseweb="select"] div[class*="singleValue"],
        div[data-baseweb="select"] div[class*="SingleValue"],
        div[data-baseweb="select"] div[class*="valueContainer"],
        div[data-baseweb="select"] div[class*="ValueContainer"] {
            background: transparent !important;
            color: var(--spt-v279-text) !important;
            -webkit-text-fill-color: var(--spt-v279-text) !important;
            text-shadow: 0 0 12px rgba(120, 234, 255, 0.06) !important;
        }

        div[data-baseweb="select"] input::placeholder,
        .stTextInput input::placeholder,
        .stTextArea textarea::placeholder,
        .stDateInput input::placeholder,
        .stNumberInput input::placeholder {
            color: var(--spt-v279-text-dim) !important;
            -webkit-text-fill-color: var(--spt-v279-text-dim) !important;
            opacity: 1 !important;
        }

        div[data-baseweb="select"] svg {
            fill: #93f2ff !important;
            color: #93f2ff !important;
            filter: drop-shadow(0 0 6px rgba(0, 225, 255, 0.18));
        }

        /* multiselect 標籤採亮色科技籤，不用大片白底 */
        div[data-baseweb="tag"] {
            background: linear-gradient(135deg, rgba(110, 237, 255, 0.92) 0%, rgba(148, 197, 255, 0.92) 100%) !important;
            border: 1px solid rgba(183, 243, 255, 0.95) !important;
            border-radius: 11px !important;
            box-shadow: 0 0 10px rgba(0, 225, 255, 0.16) !important;
            color: #071523 !important;
        }
        div[data-baseweb="tag"] *,
        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            color: #071523 !important;
            -webkit-text-fill-color: #071523 !important;
            font-weight: 900 !important;
        }

        /* 文字 / 日期 / 數字 / 備註輸入框 */
        .stTextInput input,
        .stDateInput input,
        .stNumberInput input,
        .stTextArea textarea,
        div[data-testid="stTextInputRootElement"] input,
        div[data-testid="stNumberInputRootElement"] input,
        div[data-testid="stDateInputField"] input {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.01) 16%, rgba(255,255,255,0.00) 17%),
                linear-gradient(135deg, var(--spt-v279-field-bg1) 0%, var(--spt-v279-field-bg2) 56%, var(--spt-v279-field-bg3) 100%) !important;
            color: var(--spt-v279-text) !important;
            -webkit-text-fill-color: var(--spt-v279-text) !important;
            border: 1px solid var(--spt-v279-border) !important;
            border-radius: 16px !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.08),
                0 0 0 1px var(--spt-v279-border-soft),
                0 0 14px var(--spt-v279-glow-1),
                0 0 28px var(--spt-v279-glow-2),
                0 10px 24px rgba(0,0,0,0.28) !important;
            animation: sptV279Breath 3.6s ease-in-out infinite !important;
            caret-color: #aef7ff !important;
        }

        .stTextInput input:focus,
        .stDateInput input:focus,
        .stNumberInput input:focus,
        .stTextArea textarea:focus {
            border-color: #72f5ff !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.12),
                0 0 0 1px rgba(114,245,255,0.28),
                0 0 18px rgba(0,235,255,0.18),
                0 0 34px rgba(92,133,255,0.16),
                0 12px 28px rgba(0,0,0,0.32) !important;
        }

        /* 數字輸入外框右側 +/- 區 */
        .stNumberInput button,
        div[data-testid="stNumberInputStepUp"],
        div[data-testid="stNumberInputStepDown"] {
            background: linear-gradient(135deg, rgba(8, 22, 46, 0.96), rgba(18, 40, 76, 0.94)) !important;
            color: #c7f8ff !important;
            border: 1px solid rgba(84, 221, 255, 0.42) !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 0 10px rgba(0,225,255,0.10) !important;
        }

        /* 展開下拉選單面板：深色玻璃科技感 */
        div[data-baseweb="popover"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.01) 14%, rgba(255,255,255,0.00) 15%),
                linear-gradient(135deg, var(--spt-v279-menu-bg) 0%, var(--spt-v279-menu-bg-2) 100%) !important;
            border: 1px solid rgba(104, 232, 255, 0.62) !important;
            border-radius: 16px !important;
            box-shadow:
                inset 0 1px 0 rgba(255,255,255,0.08),
                0 0 0 1px rgba(84,221,255,0.22),
                0 0 18px rgba(0,225,255,0.18),
                0 0 32px rgba(74,119,255,0.14),
                0 16px 40px rgba(0,0,0,0.42) !important;
            backdrop-filter: blur(14px) saturate(135%) !important;
            -webkit-backdrop-filter: blur(14px) saturate(135%) !important;
            overflow: hidden !important;
        }

        /* 選項文字：預設就看得到，不必 hover 才看見 */
        div[role="option"],
        li[role="option"],
        ul[role="listbox"] li,
        div[data-baseweb="menu"] div {
            background: transparent !important;
            color: var(--spt-v279-text) !important;
            -webkit-text-fill-color: var(--spt-v279-text) !important;
            font-weight: 800 !important;
            border-radius: 10px !important;
            margin: 4px 6px !important;
            padding-top: 10px !important;
            padding-bottom: 10px !important;
            text-shadow: none !important;
        }
        div[data-baseweb="popover"] *,
        div[data-baseweb="menu"] *,
        ul[role="listbox"] * {
            color: var(--spt-v279-text) !important;
            -webkit-text-fill-color: var(--spt-v279-text) !important;
        }

        div[role="option"]:hover,
        li[role="option"]:hover,
        ul[role="listbox"] li:hover,
        div[data-baseweb="menu"] div:hover {
            background: linear-gradient(90deg, rgba(70, 233, 255, 0.16), rgba(104, 134, 255, 0.22)) !important;
            color: #f9feff !important;
            -webkit-text-fill-color: #f9feff !important;
            box-shadow: inset 0 0 0 1px rgba(107, 232, 255, 0.18) !important;
        }

        div[aria-selected="true"],
        li[aria-selected="true"],
        div[role="option"][aria-selected="true"],
        li[role="option"][aria-selected="true"] {
            background: var(--spt-v279-active) !important;
            color: #051321 !important;
            -webkit-text-fill-color: #051321 !important;
            font-weight: 950 !important;
            box-shadow: 0 0 12px rgba(87, 223, 255, 0.20) !important;
        }

        div[aria-disabled="true"],
        li[aria-disabled="true"] {
            color: #86a9bf !important;
            -webkit-text-fill-color: #86a9bf !important;
            opacity: 0.82 !important;
        }

        /* 讓欄位標籤更俐落但維持可讀 */
        .stSelectbox label,
        .stMultiSelect label,
        .stTextInput label,
        .stDateInput label,
        .stNumberInput label,
        .stTextArea label,
        div[data-testid="stWidgetLabel"] label {
            color: #eefcff !important;
            text-shadow: 0 0 12px rgba(82, 219, 255, 0.14) !important;
            letter-spacing: 0.3px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

try:
    apply_v279_future_cyber_field_ui()
except Exception:
    pass

for _spt_v279_name in (
    "apply_theme",
    "apply_global_theme",
    "apply_warroom_theme",
    "inject_theme",
    "inject_global_css",
    "inject_common_css",
    "render_global_css",
    "apply_app_theme",
):
    _spt_v279_func = globals().get(_spt_v279_name)
    if callable(_spt_v279_func) and not getattr(_spt_v279_func, "_spt_v279_wrapped", False):
        def _spt_v279_make_wrapper(_original):
            def _spt_v279_wrapper(*args, **kwargs):
                result = _original(*args, **kwargs)
                try:
                    apply_v279_future_cyber_field_ui()
                except Exception:
                    pass
                return result
            _spt_v279_wrapper._spt_v279_wrapped = True
            return _spt_v279_wrapper
        globals()[_spt_v279_name] = _spt_v279_make_wrapper(_spt_v279_func)
# ===== V2.79 FUTURE CYBER FIELD UI END =====


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
