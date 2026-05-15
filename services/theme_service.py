# -*- coding: utf-8 -*-
"""SPT Time Tracking - Unified theme service V1.49.

Goals:
- One unified module header style for every page.
- Keep Super Plus Tech logo, breathing glow, dark technology theme.
- Keep compatibility with old page calls: apply_theme(), app_theme(), render_header(...).
- Improve input/dropdown/table editor contrast globally.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "logococo(黑字).png",
]


def _logo_data_uri() -> str:
    for path in LOGO_CANDIDATES:
        try:
            if path.exists() and path.stat().st_size > 0:
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                ext = path.suffix.lower().replace('.', '') or 'png'
                if ext == 'jpg':
                    ext = 'jpeg'
                return f"data:image/{ext};base64,{data}"
        except Exception:
            pass
    return ""


def apply_theme() -> None:
    """Apply global SPT dark/technology theme once per rerun."""
    st.markdown(
        """
<style>
:root {
  --spt-bg-0: #050b18;
  --spt-bg-1: #071426;
  --spt-panel: rgba(7, 26, 45, 0.86);
  --spt-panel-2: rgba(10, 43, 70, 0.82);
  --spt-cyan: #16e6ff;
  --spt-cyan-soft: rgba(22, 230, 255, 0.36);
  --spt-text: #f2f8ff;
  --spt-muted: #a9bad0;
}
html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 12% 5%, rgba(55, 32, 112, .35), transparent 30%),
    radial-gradient(circle at 88% 0%, rgba(0, 178, 255, .18), transparent 32%),
    linear-gradient(135deg, #060b1b 0%, #06182a 46%, #062137 100%) !important;
  color: var(--spt-text) !important;
}
[data-testid="stHeader"] { background: rgba(2, 8, 18, 0.78) !important; }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #07162a 0%, #04101f 100%) !important;
  border-right: 1px solid rgba(22,230,255,.18) !important;
}
[data-testid="stSidebar"] * { color: #eef8ff !important; font-weight: 700 !important; }
[data-testid="stSidebarNav"] a { font-size: 1.05rem !important; }
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNav"] a:hover {
  background: linear-gradient(90deg, rgba(22,230,255,.26), rgba(109,76,255,.28)) !important;
  border-radius: 10px !important;
  box-shadow: 0 0 18px rgba(22,230,255,.22) !important;
}
.spt-header-wrap {
  margin: 28px 0 30px 0;
  padding: 20px 28px;
  border-radius: 22px;
  border: 1px solid rgba(22,230,255,.56);
  background: linear-gradient(105deg, rgba(8,31,50,.92), rgba(8,76,101,.72));
  box-shadow: 0 0 0 1px rgba(22,230,255,.08) inset, 0 0 28px rgba(22,230,255,.22), 0 0 58px rgba(92,67,255,.12);
  animation: sptBreath 3.6s ease-in-out infinite;
}
@keyframes sptBreath {
  0%, 100% { box-shadow: 0 0 0 1px rgba(22,230,255,.08) inset, 0 0 20px rgba(22,230,255,.18), 0 0 42px rgba(92,67,255,.10); }
  50% { box-shadow: 0 0 0 1px rgba(22,230,255,.18) inset, 0 0 34px rgba(22,230,255,.32), 0 0 72px rgba(92,67,255,.20); }
}
.spt-header-flex { display:flex; align-items:center; gap:28px; }
.spt-logo-box {
  background: rgba(255,255,255,.96);
  border-radius: 15px;
  padding: 10px 16px;
  min-width: 250px;
  max-width: 320px;
  height: 86px;
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow: 0 12px 26px rgba(0,0,0,.20);
}
.spt-logo-box img { max-height: 70px; max-width: 285px; object-fit: contain; }
.spt-logo-fallback { font-size: 2rem; font-weight: 900; color:#0b1f33; letter-spacing:.08em; }
.spt-header-no { font-size: 2.65rem; font-weight: 900; letter-spacing: .03em; color: #ffffff; text-shadow: 0 0 20px rgba(22,230,255,.34); line-height:1; }
.spt-header-title { font-size: 2.45rem; font-weight: 900; color: #f6fbff; text-shadow: 0 0 22px rgba(22,230,255,.30); line-height:1.12; }
.spt-header-subtitle { margin-top: 12px; font-size: 1.08rem; font-weight: 700; color: rgba(225,238,250,.78); }
@media (max-width: 900px) {
  .spt-header-flex { flex-direction:column; align-items:flex-start; }
  .spt-logo-box { min-width: 220px; height: 76px; }
  .spt-header-title { font-size: 2rem; }
  .spt-header-no { font-size: 2.15rem; }
}
/* cards/buttons */
.stButton > button, .stDownloadButton > button {
  border: 1px solid rgba(22,230,255,.55) !important;
  background: rgba(8, 57, 87, .72) !important;
  color: #f5fbff !important;
  border-radius: 11px !important;
  font-weight: 800 !important;
  box-shadow: 0 0 16px rgba(22,230,255,.10) !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: rgba(22,230,255,.90) !important;
  box-shadow: 0 0 22px rgba(22,230,255,.24) !important;
  transform: translateY(-1px);
}
/* input light mode for visibility */
div[data-baseweb="input"] input,
div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea,
textarea,
input[type="text"], input[type="password"], input[type="number"] {
  background: rgba(245,250,255,.96) !important;
  color: #07192a !important;
  -webkit-text-fill-color: #07192a !important;
  caret-color: #07192a !important;
  border: 1px solid rgba(61,210,255,.70) !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
}
input::placeholder, textarea::placeholder { color: rgba(34,67,92,.62) !important; -webkit-text-fill-color: rgba(34,67,92,.62) !important; }
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within {
  box-shadow: 0 0 0 1px rgba(22,230,255,.65), 0 0 20px rgba(22,230,255,.20) !important;
  border-radius: 14px !important;
}
/* select closed state: light box, dark text */
div[data-baseweb="select"] > div {
  background: rgba(245,250,255,.96) !important;
  color: #07192a !important;
  border: 1px solid rgba(61,210,255,.70) !important;
  border-radius: 12px !important;
}
div[data-baseweb="select"] > div * { color: #07192a !important; -webkit-text-fill-color: #07192a !important; font-weight: 800 !important; }
/* select dropdown: dark background, light text; selected cyan */
ul[role="listbox"], div[role="listbox"] {
  background: #061426 !important;
  border: 1px solid rgba(22,230,255,.55) !important;
  border-radius: 12px !important;
  box-shadow: 0 12px 32px rgba(0,0,0,.45), 0 0 22px rgba(22,230,255,.18) !important;
}
ul[role="listbox"] li, div[role="option"], div[role="listbox"] * {
  color: #f2fbff !important;
  -webkit-text-fill-color: #f2fbff !important;
  font-weight: 800 !important;
}
ul[role="listbox"] li[aria-selected="true"], div[role="option"][aria-selected="true"] {
  background: #23e9ff !important;
  color: #061426 !important;
  -webkit-text-fill-color: #061426 !important;
}
/* date / time / number */
.stDateInput input, .stTimeInput input, .stNumberInput input { background: rgba(245,250,255,.96) !important; color:#07192a !important; -webkit-text-fill-color:#07192a !important; }
/* data editor */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] select {
  background: rgba(245,250,255,.98) !important;
  color: #07192a !important;
  -webkit-text-fill-color: #07192a !important;
  font-weight: 800 !important;
}
[data-testid="stDataEditor"] [role="gridcell"] { color:#f4fbff !important; font-weight:700 !important; }
[data-testid="stDataEditor"] [role="columnheader"] { color:#d9eaff !important; font-weight:900 !important; }
/* metric cards */
[data-testid="stMetric"] {
  background: rgba(8, 30, 50, .78);
  border: 1px solid rgba(22,230,255,.24);
  border-radius: 15px;
  padding: 14px 18px;
}
hr { border-color: rgba(22,230,255,.16) !important; }
</style>
        """,
        unsafe_allow_html=True,
    )


app_theme = apply_theme
inject_global_css = apply_theme


def _parse_header_args(*args: Any, **kwargs: Any) -> tuple[str, str, str]:
    module_no = str(kwargs.get("module_no", "") or "")
    title = str(kwargs.get("title", "") or "")
    subtitle = str(kwargs.get("subtitle", "") or "")

    if len(args) >= 3:
        module_no = str(args[0] or module_no)
        title = str(args[1] or title)
        subtitle = str(args[2] or subtitle)
    elif len(args) == 2:
        a0, a1 = str(args[0] or ""), str(args[1] or "")
        if "|" in a0:
            left, right = [x.strip() for x in a0.split("|", 1)]
            module_no = left or module_no
            title = right or title
            subtitle = a1 or subtitle
        else:
            title = a0 or title
            subtitle = a1 or subtitle
    elif len(args) == 1:
        a0 = str(args[0] or "")
        if "|" in a0:
            left, right = [x.strip() for x in a0.split("|", 1)]
            module_no = left or module_no
            title = right or title
        elif a0.strip().isdigit():
            module_no = a0
        else:
            title = a0 or title

    # normalize forms like "09_09. 資料永久保存與備份" or "09. 資料..."
    if module_no and not module_no[:2].isdigit() and len(module_no) >= 2:
        pass
    if title and title[:2].isdigit() and ("." in title[:5] or "|" in title[:5]):
        raw = title.replace("|", ".", 1)
        parts = raw.split(".", 1)
        if parts[0].strip().isdigit():
            module_no = parts[0].strip().zfill(2)
            title = parts[1].strip() if len(parts) > 1 else title
    if module_no:
        module_no = module_no.strip().replace(".", "").zfill(2) if module_no.strip().isdigit() else module_no.strip()
    return module_no, title, subtitle


def render_header(*args: Any, **kwargs: Any) -> None:
    """Render the unified SPT page header.

    Compatible call styles:
    - render_header("04", "人員名單", "...")
    - render_header("04 | 人員名單", "...")
    - render_header(title="人員名單", module_no="04", subtitle="...")
    """
    module_no, title, subtitle = _parse_header_args(*args, **kwargs)
    logo = _logo_data_uri()
    logo_html = f'<img src="{logo}" alt="SPT Logo" />' if logo else '<div class="spt-logo-fallback">SPT</div>'
    no_html = f'<div class="spt-header-no">{module_no}</div>' if module_no else ''
    title_html = f'<div class="spt-header-title">{title}</div>' if title else ''
    subtitle_html = f'<div class="spt-header-subtitle">{subtitle}</div>' if subtitle else ''
    st.markdown(
        f"""
<div class="spt-header-wrap">
  <div class="spt-header-flex">
    <div class="spt-logo-box">{logo_html}</div>
    <div>
      <div style="display:flex; align-items:center; gap:18px; flex-wrap:wrap;">
        {no_html}
        {title_html}
      </div>
      {subtitle_html}
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


render_page_header = render_header


def render_home_header(*args: Any, **kwargs: Any) -> None:
    subtitle = kwargs.get("subtitle") or "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + GitHub Cloud Storage"
    render_header("", "超慧科技製造部｜智慧工時紀錄系統", subtitle)


def render_kpi_cards(items: list[tuple[str, Any]] | None = None) -> None:
    if not items:
        return
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value = item
        with col:
            st.metric(label, value)

# ===== SPT V1.51 COMPATIBILITY FIX START =====
def render_module_cards(items=None):
    """Render home module cards. Compatibility function required by streamlit_app.py.

    Accepts either a list of tuples/lists/dicts, or uses the standard SPT module list.
    This function intentionally uses Streamlit native columns + markdown so it is robust
    across Streamlit Cloud versions and will not display raw HTML as text.
    """
    import streamlit as st

    default_items = [
        ("01", "工時紀錄", "Time Records", "快速開始、暫停、下班、完工與工時計算"),
        ("02", "歷史紀錄", "History", "完整工時明細查詢、編輯、儲存與 Excel 匯出"),
        ("03", "製令管理", "Work Orders", "Excel 匯入、貼上資料、手動新增、頁面編輯"),
        ("04", "人員名單", "Employees", "人員主檔、在廠狀態、今日出勤勾選"),
        ("05", "製令工時分析", "Analysis", "製令累積工時、工段分析與明細查詢"),
        ("06", "LOG查詢", "Logs", "系統操作、異常與資料異動紀錄查詢"),
        ("07", "今日未紀錄名單", "Missing Today", "出勤但未登錄工時的人員即時提示"),
        ("08", "人員每日工時", "Daily Hours", "每日累積工時與合理區間異常提醒"),
        ("09", "資料永久保存與備份", "Persistence", "永久檔、GitHub 雲端、還原與備份"),
        ("10", "權限管理", "Permission", "帳號、密碼、角色與模組權限設定"),
        ("11", "登入紀錄", "Audit Logs", "登入、登出、權限不足與安全事件查詢"),
        ("12", "模組永久紀錄中心", "Module Persistence", "各模組獨立紀錄檔與設定檔管理"),
    ]
    if not items:
        items = default_items

    normalized = []
    for item in items:
        if isinstance(item, dict):
            no = str(item.get("no") or item.get("module_no") or item.get("id") or "")
            name = str(item.get("name") or item.get("title") or "")
            en = str(item.get("en") or item.get("english") or item.get("subtitle") or "")
            desc = str(item.get("desc") or item.get("description") or "")
        else:
            seq = list(item) if isinstance(item, (tuple, list)) else [str(item)]
            no = str(seq[0]) if len(seq) > 0 else ""
            name = str(seq[1]) if len(seq) > 1 else ""
            en = str(seq[2]) if len(seq) > 2 else ""
            desc = str(seq[3]) if len(seq) > 3 else ""
        normalized.append((no, name, en, desc))

    st.markdown("### 系統模組 / System Modules")
    for row_start in range(0, len(normalized), 4):
        cols = st.columns(4)
        for col, (no, name, en, desc) in zip(cols, normalized[row_start:row_start + 4]):
            with col:
                st.markdown(
                    f"""
                    <div class="spt-module-card">
                        <div class="spt-module-no">{no}</div>
                        <div class="spt-module-name">{name}</div>
                        <div class="spt-module-en">{en}</div>
                        <div class="spt-module-desc">{desc}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# Strong dropdown contrast CSS, kept in the final theme file instead of injection-only patch.
def apply_dropdown_contrast_fix():
    import streamlit as st
    st.markdown(r'''
    <style>
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] input,
    div[data-baseweb="base-input"] input,
    div[data-baseweb="textarea"] textarea,
    textarea,
    input[type="text"],
    input[type="password"],
    input[type="number"] {
        background-color: #eef7ff !important;
        color: #071827 !important;
        caret-color: #071827 !important;
        border: 1px solid rgba(34, 211, 238, 0.85) !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        text-shadow: none !important;
    }
    div[data-baseweb="select"] span,
    div[data-baseweb="select"] div {
        color: #071827 !important;
        text-shadow: none !important;
    }
    div[data-baseweb="popover"],
    div[data-baseweb="popover"] > div,
    div[data-baseweb="menu"],
    ul[role="listbox"],
    div[role="listbox"] {
        background-color: #071322 !important;
        color: #f2fbff !important;
        border: 1px solid rgba(34, 211, 238, 0.72) !important;
        border-radius: 12px !important;
        box-shadow: 0 14px 36px rgba(0,0,0,.58), 0 0 22px rgba(34,211,238,.18) !important;
    }
    ul[role="listbox"] li,
    ul[role="listbox"] li *,
    div[role="option"],
    div[role="option"] *,
    div[data-baseweb="menu"] li,
    div[data-baseweb="menu"] li *,
    div[data-baseweb="popover"] div[role="option"],
    div[data-baseweb="popover"] div[role="option"] * {
        background-color: transparent !important;
        color: #f2fbff !important;
        font-weight: 750 !important;
        text-shadow: none !important;
    }
    ul[role="listbox"] li:hover,
    ul[role="listbox"] li[aria-selected="true"],
    div[role="option"]:hover,
    div[role="option"][aria-selected="true"],
    div[data-baseweb="popover"] div[role="option"]:hover,
    div[data-baseweb="popover"] div[role="option"][aria-selected="true"] {
        background-color: #22d3ee !important;
        color: #03121f !important;
    }
    ul[role="listbox"] li:hover *,
    ul[role="listbox"] li[aria-selected="true"] *,
    div[role="option"]:hover *,
    div[role="option"][aria-selected="true"] *,
    div[data-baseweb="popover"] div[role="option"]:hover *,
    div[data-baseweb="popover"] div[role="option"][aria-selected="true"] * {
        color: #03121f !important;
        font-weight: 850 !important;
    }
    [data-testid="stDataEditor"] input,
    [data-testid="stDataEditor"] textarea,
    [data-testid="stDataEditor"] [contenteditable="true"] {
        background-color: #eef7ff !important;
        color: #071827 !important;
        caret-color: #071827 !important;
        font-weight: 700 !important;
        text-shadow: none !important;
    }
    div[data-baseweb="tag"] {
        background-color: rgba(34, 211, 238, 0.25) !important;
        border: 1px solid rgba(34, 211, 238, 0.65) !important;
        border-radius: 9px !important;
    }
    div[data-baseweb="tag"] span,
    div[data-baseweb="tag"] svg,
    div[data-baseweb="select"] svg {
        color: #071827 !important;
        fill: #071827 !important;
    }
    </style>
    ''', unsafe_allow_html=True)

# Wrap existing theme functions once, without recursive redefinition.
try:
    _spt_v151_original_apply_theme = apply_theme
    def apply_theme(*args, **kwargs):
        result = _spt_v151_original_apply_theme(*args, **kwargs)
        apply_dropdown_contrast_fix()
        return result
except Exception:
    pass

try:
    _spt_v151_original_app_theme = app_theme
    def app_theme(*args, **kwargs):
        result = _spt_v151_original_app_theme(*args, **kwargs)
        apply_dropdown_contrast_fix()
        return result
except Exception:
    def app_theme(*args, **kwargs):
        return apply_theme(*args, **kwargs)
# ===== SPT V1.51 COMPATIBILITY FIX END =====
