# -*- coding: utf-8 -*-
"""SPT Time Tracking System - Visual theme helpers.

V1.9 important change:
- Do NOT render visible page headers or cards with raw HTML anymore.
- Previous versions could show <div> text when old files were mixed.
- This version uses native Streamlit elements for headers/cards, so HTML will not appear as text.
"""
from __future__ import annotations

from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATHS = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "logococo(黑字).png",
]


def _find_logo() -> Path | None:
    for p in LOGO_PATHS:
        if p.exists():
            return p
    return None


def apply_theme() -> None:
    """Apply global dark high-tech Streamlit styling.

    Only CSS is injected here; no visible HTML blocks are output.
    """
    st.markdown(
        """
<style>
:root {
    --spt-bg0: #050b16;
    --spt-bg1: #071426;
    --spt-panel: rgba(10, 25, 44, .92);
    --spt-text: #f4fbff;
    --spt-muted: #a9bacb;
    --spt-cyan: #35e7ff;
    --spt-purple: #b44dff;
}
html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 8% 8%, rgba(103, 58, 183, .23), transparent 34%),
        radial-gradient(circle at 78% 10%, rgba(21, 134, 177, .24), transparent 35%),
        linear-gradient(135deg, #050914 0%, #071321 48%, #061729 100%) !important;
    color: var(--spt-text) !important;
}
[data-testid="stHeader"] { background: rgba(5, 11, 22, .70) !important; }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #071426 0%, #05101d 100%) !important;
    border-right: 1px solid rgba(53, 231, 255, .20);
}
[data-testid="stSidebar"] * {
    color: #eaf8ff !important;
    font-weight: 750;
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
h1, h2, h3, h4, h5, h6, p, span, div, label { color: var(--spt-text); }
.block-container { padding-top: 2.0rem; }
[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(9,22,42,.90), rgba(10,37,61,.72));
    border: 1px solid rgba(53,231,255,.18);
    border-radius: 18px;
    padding: 16px 18px;
    box-shadow: 0 0 20px rgba(53,231,255,.08);
}
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
.spt-divider {
    height: 1px;
    background: linear-gradient(90deg, rgba(53,231,255,.05), rgba(53,231,255,.55), rgba(180,77,255,.40), rgba(53,231,255,.05));
    margin: 14px 0 24px 0;
}
</style>
        """,
        unsafe_allow_html=True,
    )


# Backward-compatible aliases used by older generated pages.
def app_theme() -> None:
    apply_theme()


def render_header(title: str, subtitle: str = "", logo: bool = True) -> None:
    """Render common header using native Streamlit widgets only."""
    with st.container(border=True):
        cols = st.columns([1.05, 5.0]) if logo else st.columns([1])
        if logo:
            logo_path = _find_logo()
            with cols[0]:
                if logo_path:
                    st.image(str(logo_path), use_container_width=True)
                else:
                    st.markdown("### SPT")
            main_col = cols[1]
        else:
            main_col = cols[0]
        with main_col:
            st.title(title)
            if subtitle:
                st.caption(subtitle)
    st.markdown('<div class="spt-divider"></div>', unsafe_allow_html=True)


def render_home_header() -> None:
    render_header(
        "超慧科技製造部｜智慧工時紀錄系統",
        "Super Plus Tech Manufacturing Time Tracking System｜Streamlit + SQLite + Excel Import / Export",
        logo=True,
    )


def render_kpi_cards(items: list[tuple[str, str]]) -> None:
    cols = st.columns(len(items) if items else 1)
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def render_module_cards(modules: list[tuple[str, str, str]]) -> None:
    """Render module list using native containers to avoid visible HTML issues."""
    for i in range(0, len(modules), 4):
        cols = st.columns(4)
        for col, item in zip(cols, modules[i:i+4]):
            no, name, desc = item
            with col:
                with st.container(border=True):
                    st.subheader(f"{no}. {name}")
                    st.caption(desc)
