# -*- coding: utf-8 -*-
"""SPT Time Tracking System - visual theme helpers.

V1.7 fixes HTML being displayed as plain text by always rendering shared
headers/styles with unsafe_allow_html=True.  This module intentionally keeps
old function names used by earlier pages: apply_theme, app_theme, render_header.
"""
from __future__ import annotations

from pathlib import Path
import base64
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATHS = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "logococo(黑字).png",
]


def _logo_data_uri() -> str:
    for p in LOGO_PATHS:
        if p.exists():
            try:
                ext = p.suffix.lower().replace('.', '') or 'png'
                data = base64.b64encode(p.read_bytes()).decode('utf-8')
                return f"data:image/{ext};base64,{data}"
            except Exception:
                continue
    return ""


def apply_theme() -> None:
    """Apply global dark high-tech Streamlit styling."""
    st.markdown(
        """
<style>
:root {
    --spt-bg0: #050b16;
    --spt-bg1: #071426;
    --spt-panel: rgba(10, 25, 44, .86);
    --spt-panel2: rgba(14, 41, 66, .78);
    --spt-text: #f4fbff;
    --spt-muted: #a9bacb;
    --spt-cyan: #35e7ff;
    --spt-blue: #1e86ff;
    --spt-purple: #b44dff;
    --spt-red: #ff4d66;
}

html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 8% 8%, rgba(103, 58, 183, .24), transparent 34%),
        radial-gradient(circle at 78% 10%, rgba(21, 134, 177, .25), transparent 35%),
        linear-gradient(135deg, #050914 0%, #071321 48%, #061729 100%) !important;
    color: var(--spt-text) !important;
}

[data-testid="stHeader"] { background: rgba(5, 11, 22, .70) !important; }
[data-testid="stToolbar"] { color: var(--spt-text) !important; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #071426 0%, #05101d 100%) !important;
    border-right: 1px solid rgba(53, 231, 255, .20);
}
[data-testid="stSidebar"] * {
    color: #eaf8ff !important;
    font-weight: 700;
}
[data-testid="stSidebarNav"] a {
    color: #eaf8ff !important;
    border-radius: 10px;
    margin: 4px 6px;
}
[data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: linear-gradient(90deg, rgba(53,231,255,.28), rgba(180,77,255,.20)) !important;
    box-shadow: inset 3px 0 0 var(--spt-cyan), 0 0 16px rgba(53,231,255,.20);
}

/* General text */
h1, h2, h3, h4, h5, h6, p, span, div, label {
    color: var(--spt-text);
}
.small-muted, .spt-subtitle { color: var(--spt-muted) !important; }

/* Inputs and tables */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: 1px solid rgba(53, 231, 255, .16);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 0 22px rgba(53, 231, 255, .08);
}
.stButton>button, .stDownloadButton>button {
    border-radius: 12px !important;
    border: 1px solid rgba(53,231,255,.35) !important;
    background: linear-gradient(90deg, rgba(10,35,60,.96), rgba(20,68,98,.94)) !important;
    color: #f4fbff !important;
    box-shadow: 0 0 14px rgba(53,231,255,.14);
}
.stButton>button:hover, .stDownloadButton>button:hover {
    border-color: var(--spt-cyan) !important;
    box-shadow: 0 0 22px rgba(53,231,255,.30);
}

.spt-hero {
    position: relative;
    padding: 22px 26px;
    margin: 10px 0 24px 0;
    border-radius: 22px;
    border: 1px solid rgba(53, 231, 255, .24);
    background:
        linear-gradient(100deg, rgba(8, 18, 35, .96), rgba(15, 68, 96, .76)),
        radial-gradient(circle at 100% 0%, rgba(53, 231, 255, .18), transparent 45%);
    box-shadow: 0 0 32px rgba(53, 231, 255, .10), inset 0 0 38px rgba(53,231,255,.05);
    overflow: hidden;
}
.spt-hero:before {
    content: "";
    position: absolute;
    inset: -2px;
    background: linear-gradient(90deg, transparent, rgba(53,231,255,.18), transparent);
    animation: spt-breathe 3.6s ease-in-out infinite;
    pointer-events: none;
}
@keyframes spt-breathe {
    0%, 100% { opacity: .25; }
    50% { opacity: .85; }
}
.spt-hero-inner { position: relative; z-index: 1; display:flex; gap:22px; align-items:center; }
.spt-logo-box {
    width: 180px;
    min-width: 180px;
    height: 72px;
    display:flex;
    align-items:center;
    justify-content:center;
    background: rgba(255,255,255,.96);
    border-radius: 14px;
    padding: 8px 12px;
    box-shadow: 0 0 18px rgba(53,231,255,.16);
}
.spt-logo-box img { max-width: 100%; max-height: 58px; object-fit: contain; }
.spt-title { font-size: 30px; line-height: 1.25; font-weight: 900; letter-spacing: .5px; color: #f8fcff; }
.spt-subtitle { margin-top: 8px; font-size: 14px; letter-spacing: .4px; color: #aec5d9 !important; }
.spt-kpi-grid { display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:16px; margin: 12px 0 22px; }
.spt-kpi-card {
    padding: 18px 20px;
    border-radius: 18px;
    border: 1px solid rgba(53,231,255,.18);
    background: linear-gradient(145deg, rgba(9,22,42,.90), rgba(10,37,61,.72));
    box-shadow: 0 0 20px rgba(53,231,255,.08);
}
.spt-kpi-label { color:#a9bacb; font-size:13px; font-weight:700; }
.spt-kpi-value { color:#ffffff; font-size:30px; font-weight:900; margin-top:8px; }
.spt-section-title { font-size: 22px; font-weight: 900; margin: 22px 0 12px; color:#ffffff; }
.spt-module-grid { display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:14px; }
.spt-module-card {
    padding: 18px;
    border-radius: 18px;
    border: 1px solid rgba(53,231,255,.16);
    background: rgba(8,20,38,.78);
    min-height: 100px;
}
.spt-module-no { color: var(--spt-cyan); font-size: 20px; font-weight: 900; }
.spt-module-name { color: #fff; font-size: 18px; font-weight: 900; margin-top: 6px; }
.spt-module-desc { color: #a9bacb; font-size: 13px; margin-top: 8px; }
@media (max-width: 1000px) {
    .spt-kpi-grid, .spt-module-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .spt-hero-inner { flex-direction: column; align-items:flex-start; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


# Backward-compatible aliases used by older generated pages.
def app_theme() -> None:
    apply_theme()


def render_header(title: str, subtitle: str = "", logo: bool = True) -> None:
    """Render the common page header.  Do not return HTML; render it directly."""
    logo_uri = _logo_data_uri() if logo else ""
    logo_html = f'<div class="spt-logo-box"><img src="{logo_uri}" /></div>' if logo_uri else ""
    st.markdown(
        f"""
<div class="spt-hero">
  <div class="spt-hero-inner">
    {logo_html}
    <div>
      <div class="spt-title">{title}</div>
      <div class="spt-subtitle">{subtitle}</div>
    </div>
  </div>
</div>
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
    html = '<div class="spt-kpi-grid">'
    for label, value in items:
        html += f'<div class="spt-kpi-card"><div class="spt-kpi-label">{label}</div><div class="spt-kpi-value">{value}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)
