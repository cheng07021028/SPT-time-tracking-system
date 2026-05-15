# -*- coding: utf-8 -*-
"""SPT Time Tracking System - Visual theme helpers.

V1.34
- Keep existing logo/header/sidebar breathing glow.
- Strengthen all input/editing text color to dark, especially st.data_editor active cells.
- Fix light input boxes where typed text appeared too pale/white.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable
import base64

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "logococo(黑字).png",
]

# Embedded logo fallback. This fixes environments where data/logo was not copied to GitHub/Cloud.
EMBEDDED_LOGO_B64 = "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Ff8AwoA5uiuk/wCFfeMf+hZ1X/wFf/Cj/hX3jH/oWdV/8BX/AMKAOborpP8AhX3jH/oWdV/8BX/wo/4V94x/6FnVf/AV/wDCgDm6+gfgZ8MsCLxdrMHzddPhcf8AkUj/ANB/P0rmfhn8HtU1jxCtx4k024stLtCHeO4jKG4bsgB7ep/DvX1EiLGioihUUYVVGAB6UAOooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP/Z"


def _find_logo() -> Path | None:
    for p in LOGO_CANDIDATES:
        if p.exists() and p.is_file():
            return p
    return None


def _logo_data_uri() -> str:
    p = _find_logo()
    if p:
        suffix = p.suffix.lower().replace(".", "") or "png"
        mime = "jpeg" if suffix in {"jpg", "jpeg"} else "png"
        try:
            raw = p.read_bytes()
            return f"data:image/{mime};base64," + base64.b64encode(raw).decode("ascii")
        except Exception:
            pass
    return "data:image/png;base64," + EMBEDDED_LOGO_B64


def apply_theme() -> None:
    """Apply global SPT dark-tech style."""
    st.markdown(
        """
<style>
:root {
  --spt-bg0:#050b16;
  --spt-bg1:#071426;
  --spt-panel:rgba(8,20,38,.94);
  --spt-panel2:rgba(11,43,68,.86);
  --spt-text:#f4fbff;
  --spt-muted:#a9bbcf;
  --spt-cyan:#34e8ff;
  --spt-blue:#1e86ff;
  --spt-purple:#ba5cff;
  --spt-green:#2df7b5;
}

@keyframes sptBreath {
  0%,100% {
    box-shadow:
      0 0 18px rgba(52,232,255,.20),
      0 0 42px rgba(52,232,255,.10),
      inset 0 0 18px rgba(52,232,255,.055);
    border-color: rgba(52,232,255,.34);
  }
  50% {
    box-shadow:
      0 0 34px rgba(52,232,255,.62),
      0 0 86px rgba(186,92,255,.30),
      inset 0 0 34px rgba(52,232,255,.18);
    border-color: rgba(52,232,255,.86);
  }
}

@keyframes sptScan {
  0% { transform: translateX(-125%); opacity: .04; }
  45% { opacity: .62; }
  100% { transform: translateX(125%); opacity: .02; }
}

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 7% 6%, rgba(103,58,183,.24), transparent 34%),
    radial-gradient(circle at 82% 9%, rgba(33,150,243,.22), transparent 37%),
    linear-gradient(135deg, #050914 0%, #071321 48%, #061729 100%) !important;
  color: var(--spt-text) !important;
}
[data-testid="stHeader"] {
  background: rgba(5,11,22,.78) !important;
}

/* Move every page away from the browser/Streamlit toolbar. */
.block-container {
  padding-top: 3.35rem !important;
  max-width: 1660px;
}

/* Sidebar */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #071426 0%, #05101d 100%) !important;
  border-right: 1px solid rgba(52,232,255,.30);
}
[data-testid="stSidebar"] * {
  color:#eefaff !important;
  font-weight:820 !important;
}
[data-testid="stSidebarNav"] a {
  color:#eefaff !important;
  border-radius:11px;
  margin:6px 8px;
  padding: 9px 10px !important;
  font-size: 17px !important;
  line-height: 1.35 !important;
}
[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNav"] p {
  font-size: 17px !important;
}
[data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: linear-gradient(90deg, rgba(52,232,255,.34), rgba(186,92,255,.25)) !important;
  box-shadow: inset 4px 0 0 var(--spt-cyan), 0 0 22px rgba(52,232,255,.30);
}

h1,h2,h3,h4,h5,h6,p,span,div,label { color: var(--spt-text); }
[data-testid="stCaptionContainer"] { color: var(--spt-muted) !important; }

.spt-hero {
  position: relative;
  overflow: hidden;
  min-height: 138px;
  border: 1px solid rgba(52,232,255,.42);
  border-radius: 24px;
  padding: 26px 30px;
  margin: 22px 0 30px 0;
  background:
    radial-gradient(circle at 98% 8%, rgba(52,232,255,.24), transparent 34%),
    linear-gradient(105deg, rgba(8,18,35,.98), rgba(11,48,75,.88));
  animation: sptBreath 3.0s ease-in-out infinite;
}
.spt-hero::after {
  content:"";
  position:absolute;
  top:0;
  left:0;
  width:46%;
  height:100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.12), transparent);
  animation: sptScan 4.2s ease-in-out infinite;
  pointer-events:none;
}
.spt-hero-inner {
  position: relative;
  z-index: 2;
  display: flex;
  gap: 28px;
  align-items: center;
}
.spt-logo-wrap {
  width: 270px;
  min-width: 270px;
  height: 88px;
  display:flex;
  align-items:center;
  justify-content:center;
  border-radius: 16px;
  background: rgba(255,255,255,.98);
  padding: 10px 16px;
  box-shadow: 0 0 26px rgba(52,232,255,.32);
}
.spt-logo-wrap img {
  max-width:100%;
  max-height:100%;
  object-fit:contain;
}
.spt-title-main {
  font-size: 38px;
  line-height: 1.18;
  font-weight: 960;
  letter-spacing: .5px;
  color: #f9fdff;
  text-shadow: 0 0 18px rgba(52,232,255,.42), 0 0 30px rgba(186,92,255,.22);
}
.spt-title-sub {
  margin-top: 12px;
  font-size: 16px;
  letter-spacing: .25px;
  color: #b5c7dc;
}
.spt-divider {
  height:1px;
  background: linear-gradient(90deg, rgba(52,232,255,.03), rgba(52,232,255,.65), rgba(186,92,255,.45), rgba(52,232,255,.03));
  margin: 6px 0 24px 0;
}
.spt-module-card {
  min-height: 132px;
  border:1px solid rgba(52,232,255,.34);
  border-radius:20px;
  padding:22px 22px;
  background: linear-gradient(145deg, rgba(9,22,42,.92), rgba(10,37,61,.76));
  animation: sptBreath 3.8s ease-in-out infinite;
}
.spt-module-no { color:#71f2ff; font-size:22px; font-weight:960; }
.spt-module-name { font-size:28px; font-weight:950; margin-top:6px; }
.spt-module-desc { color:#aebfd2; font-size:16px; margin-top:12px; line-height:1.45; }

/* Native containers / metrics also glow */
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 20px !important;
  border: 1px solid rgba(52,232,255,.30) !important;
  background: linear-gradient(145deg, rgba(9,22,42,.90), rgba(10,37,61,.70)) !important;
  animation: sptBreath 4.0s ease-in-out infinite;
}
[data-testid="stMetric"] {
  background: linear-gradient(145deg, rgba(9,22,42,.92), rgba(10,37,61,.74));
  border: 1px solid rgba(52,232,255,.22);
  border-radius: 18px;
  padding: 18px 20px;
  box-shadow: 0 0 24px rgba(52,232,255,.14);
}
[data-testid="stMetricLabel"] div { font-size: 16px !important; }
[data-testid="stMetricValue"] div { font-size: 34px !important; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  border: 1px solid rgba(52,232,255,.20);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 0 24px rgba(52,232,255,.12);
}
.stButton>button, .stDownloadButton>button {
  border-radius: 12px !important;
  border: 1px solid rgba(52,232,255,.38) !important;
  background: linear-gradient(90deg, rgba(10,35,60,.98), rgba(20,68,98,.96)) !important;
  color: #f4fbff !important;
  box-shadow: 0 0 16px rgba(52,232,255,.18);
  font-size: 16px !important;
  font-weight: 850 !important;
}
.stButton>button:hover, .stDownloadButton>button:hover {
  border-color: var(--spt-cyan) !important;
  box-shadow: 0 0 28px rgba(52,232,255,.42);
}



/* ===== V1.31 全系統輸入區淺色科技風 / Global Light Input Fields ===== */
/* Text input / Password / Number / Textarea */
div[data-baseweb="input"],
div[data-baseweb="base-input"],
div[data-baseweb="textarea"],
.stTextInput div[data-baseweb="input"],
.stNumberInput div[data-baseweb="input"],
.stTextArea div[data-baseweb="textarea"] {
  background: rgba(245, 250, 255, 0.94) !important;
  border: 1px solid rgba(80, 210, 255, 0.56) !important;
  border-radius: 14px !important;
  box-shadow:
    inset 0 0 0 1px rgba(0, 180, 255, 0.08),
    0 0 16px rgba(52, 232, 255, 0.10) !important;
  transition: all .18s ease-in-out !important;
}

div[data-baseweb="input"] input,
div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea,
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
textarea,
input[type="text"],
input[type="password"],
input[type="number"] {
  background: rgba(245, 250, 255, 0.94) !important;
  color: #06182a !important;
  caret-color: #006d92 !important;
  border-radius: 12px !important;
  font-weight: 760 !important;
  letter-spacing: .15px !important;
}

div[data-baseweb="input"] input::placeholder,
div[data-baseweb="base-input"] input::placeholder,
div[data-baseweb="textarea"] textarea::placeholder,
.stTextInput input::placeholder,
.stTextArea textarea::placeholder,
textarea::placeholder {
  color: rgba(18, 45, 68, 0.62) !important;
  font-weight: 650 !important;
}

/* Focus glow */
div[data-baseweb="input"]:focus-within,
div[data-baseweb="base-input"]:focus-within,
div[data-baseweb="textarea"]:focus-within,
.stTextInput:focus-within div[data-baseweb="input"],
.stNumberInput:focus-within div[data-baseweb="input"],
.stTextArea:focus-within div[data-baseweb="textarea"] {
  border-color: rgba(52, 232, 255, 0.95) !important;
  box-shadow:
    0 0 0 1px rgba(52, 232, 255, 0.55),
    0 0 18px rgba(52, 232, 255, 0.28),
    0 0 42px rgba(30, 134, 255, 0.16),
    inset 0 0 0 1px rgba(255,255,255,.18) !important;
}

/* Selectbox / Multiselect / Date / Time */
div[data-baseweb="select"] > div,
.stDateInput div[data-baseweb="input"],
.stTimeInput div[data-baseweb="input"] {
  background: rgba(245, 250, 255, 0.94) !important;
  color: #06182a !important;
  border: 1px solid rgba(80, 210, 255, 0.56) !important;
  border-radius: 14px !important;
  box-shadow:
    inset 0 0 0 1px rgba(0, 180, 255, 0.08),
    0 0 16px rgba(52, 232, 255, 0.10) !important;
}

div[data-baseweb="select"] span,
div[data-baseweb="select"] div,
div[data-baseweb="select"] input,
.stDateInput input,
.stTimeInput input {
  color: #06182a !important;
  font-weight: 760 !important;
}

div[data-baseweb="select"]:focus-within > div,
.stDateInput:focus-within div[data-baseweb="input"],
.stTimeInput:focus-within div[data-baseweb="input"] {
  border-color: rgba(52, 232, 255, 0.95) !important;
  box-shadow:
    0 0 0 1px rgba(52, 232, 255, 0.55),
    0 0 18px rgba(52, 232, 255, 0.28),
    0 0 42px rgba(30, 134, 255, 0.16) !important;
}

/* Dropdown menu */
ul[role="listbox"],
div[data-baseweb="popover"] {
  background: rgba(245, 250, 255, 0.98) !important;
  border: 1px solid rgba(52, 232, 255, 0.42) !important;
  border-radius: 14px !important;
  box-shadow: 0 16px 38px rgba(0, 0, 0, 0.36), 0 0 22px rgba(52,232,255,.18) !important;
}

ul[role="listbox"] li,
ul[role="listbox"] div,
div[role="option"],
div[role="option"] * {
  color: #06182a !important;
  font-weight: 760 !important;
}

div[role="option"]:hover,
li[role="option"]:hover {
  background: rgba(52, 232, 255, 0.16) !important;
}

/* Multiselect selected tags */
div[data-baseweb="tag"] {
  background: linear-gradient(90deg, rgba(52,232,255,.20), rgba(186,92,255,.14)) !important;
  border: 1px solid rgba(52,232,255,.42) !important;
  border-radius: 10px !important;
}

div[data-baseweb="tag"] span,
div[data-baseweb="tag"] svg {
  color: #06182a !important;
  fill: #06182a !important;
  font-weight: 850 !important;
}

/* Labels remain bright on dark background */
.stTextInput label,
.stTextArea label,
.stSelectbox label,
.stMultiSelect label,
.stDateInput label,
.stTimeInput label,
.stNumberInput label,
.stFileUploader label,
.stCheckbox label,
.stRadio label {
  color: #eaf8ff !important;
  font-weight: 850 !important;
  letter-spacing: .25px !important;
}

/* Data editor editable cells - keep table dark, but make active input readable */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] select {
  background: rgba(245, 250, 255, 0.98) !important;
  color: #06182a !important;
  border-radius: 8px !important;
  font-weight: 760 !important;
}

[data-testid="stDataEditor"] [role="gridcell"]:focus-within,
[data-testid="stDataFrame"] [role="gridcell"]:focus-within {
  box-shadow:
    inset 0 0 0 1px rgba(52, 232, 255, 0.76),
    0 0 14px rgba(52, 232, 255, 0.22) !important;
  border-radius: 6px !important;
}

/* File uploader / drag area */
[data-testid="stFileUploader"] section {
  background: rgba(245, 250, 255, 0.92) !important;
  border: 1px dashed rgba(52,232,255,.70) !important;
  border-radius: 16px !important;
  color: #06182a !important;
}
[data-testid="stFileUploader"] section * {
  color: #06182a !important;
  font-weight: 760 !important;
}

/* Disabled input */
input:disabled,
textarea:disabled,
div[aria-disabled="true"] input {
  background: rgba(220, 230, 238, 0.78) !important;
  color: rgba(20, 40, 60, 0.70) !important;
}

/* Login page specific visibility */
.stForm {
  border: 1px solid rgba(52,232,255,.28) !important;
  border-radius: 18px !important;
  padding: 14px 16px !important;
  background: rgba(7, 16, 30, .48) !important;
}

@media (max-width: 900px) {
  .block-container { padding-top: 2.2rem !important; }
  .spt-hero-inner { flex-direction: column; align-items: flex-start; }
  .spt-logo-wrap { width: 230px; min-width: 230px; height: 76px; }
  .spt-title-main { font-size: 28px; }
  [data-testid="stSidebarNav"] a { font-size: 15px !important; }
}


/* ===== V1.34 表格與全模組輸入文字強制深色 / Force dark text in editable inputs ===== */
/* Highest-priority rule for all actual input controls. Fixes Data Editor active cell text being white on light background. */
html body input,
html body textarea,
html body [contenteditable="true"],
html body [role="textbox"] {
  color: #06182a !important;
  -webkit-text-fill-color: #06182a !important;
  caret-color: #006d92 !important;
  text-shadow: none !important;
}

/* Streamlit Data Editor uses an overlay editor; this catches both normal and overlay inputs. */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] select,
[data-testid="stDataEditor"] [contenteditable="true"],
[data-testid="stDataEditor"] [role="textbox"],
[data-testid="stDataFrame"] input,
[data-testid="stDataFrame"] textarea,
[data-testid="stDataFrame"] [contenteditable="true"],
[data-testid="stDataFrame"] [role="textbox"],
.glide-data-editor input,
.glide-data-editor textarea,
.dvn-scroller input,
.dvn-scroller textarea,
.gdg-input,
.gdg-input input,
.gdg-cell-editing input,
.gdg-cell-editing textarea {
  background: rgba(245, 250, 255, 0.98) !important;
  color: #06182a !important;
  -webkit-text-fill-color: #06182a !important;
  caret-color: #006d92 !important;
  border: 1px solid rgba(52, 232, 255, 0.72) !important;
  border-radius: 8px !important;
  font-weight: 850 !important;
  text-shadow: none !important;
  opacity: 1 !important;
}

/* BaseWeb wrappers sometimes set inherited color; force descendants inside light input boxes to dark. */
div[data-baseweb="input"] *,
div[data-baseweb="base-input"] *,
div[data-baseweb="textarea"] *,
div[data-baseweb="select"] * {
  -webkit-text-fill-color: #06182a !important;
}

/* But keep labels and sidebar text bright. */
.stTextInput label *,
.stTextArea label *,
.stSelectbox label *,
.stMultiSelect label *,
.stDateInput label *,
.stTimeInput label *,
.stNumberInput label *,
.stFileUploader label *,
.stCheckbox label *,
.stRadio label *,
[data-testid="stSidebar"] * {
  -webkit-text-fill-color: unset !important;
}

/* Selected/active editable cell glow. */
[data-testid="stDataEditor"] [role="gridcell"]:focus-within,
[data-testid="stDataEditor"] [aria-selected="true"],
[data-testid="stDataFrame"] [role="gridcell"]:focus-within {
  box-shadow:
    inset 0 0 0 1px rgba(52, 232, 255, 0.92),
    0 0 18px rgba(52, 232, 255, 0.30) !important;
}

/* Placeholder and password dots remain visible on light background. */
html body input::placeholder,
html body textarea::placeholder {
  color: rgba(18, 45, 68, 0.62) !important;
  -webkit-text-fill-color: rgba(18, 45, 68, 0.62) !important;
}

</style>
        """,
        unsafe_allow_html=True,
    )


# Backward-compatible alias used by older pages.
def app_theme() -> None:
    apply_theme()


def render_header(title: str, subtitle: str = "", logo: bool = True) -> None:
    """Render SPT page header with embedded logo and breathing glow."""
    logo_uri = _logo_data_uri() if logo else _logo_data_uri()
    logo_html = f'<div class="spt-logo-wrap"><img src="{logo_uri}" alt="Super Plus Tech Logo"></div>'
    st.markdown(
        f"""
<div class="spt-hero">
  <div class="spt-hero-inner">
    {logo_html}
    <div>
      <div class="spt-title-main">{title}</div>
      <div class="spt-title-sub">{subtitle}</div>
    </div>
  </div>
</div>
<div class="spt-divider"></div>
        """,
        unsafe_allow_html=True,
    )


def render_home_header() -> None:
    render_header(
        "超慧科技製造部｜智慧工時紀錄系統",
        "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + Excel Import / Export",
        logo=True,
    )


def render_kpi_cards(items: list[tuple[str, str]]) -> None:
    if not items:
        return
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        with col:
            st.metric(label, value)


def render_module_cards(modules: Iterable[tuple[str, str, str]]) -> None:
    modules = list(modules)
    for i in range(0, len(modules), 4):
        cols = st.columns(4)
        for col, item in zip(cols, modules[i:i + 4]):
            no, name, desc = item
            with col:
                st.markdown(
                    f"""
<div class="spt-module-card">
  <div class="spt-module-no">{no}</div>
  <div class="spt-module-name">{name}</div>
  <div class="spt-module-desc">{desc}</div>
</div>
                    """,
                    unsafe_allow_html=True,
                )
