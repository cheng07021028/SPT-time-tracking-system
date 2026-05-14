# -*- coding: utf-8 -*-
"""SPT Time Tracking System - Visual theme helpers.

V1.12
- Force-render Super Plus Tech logo in every module header.
- Add visible high-tech breathing glow to headers/cards/sidebar.
- Keep backward compatibility: apply_theme / app_theme / render_header / render_home_header.
- Avoid raw <div> text by always using unsafe_allow_html=True inside this service.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Iterable

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "logococo(黑字).png",
]


def _find_logo() -> Path | None:
    for p in LOGO_CANDIDATES:
        if p.exists() and p.is_file():
            return p
    return None


def _logo_data_uri() -> str | None:
    p = _find_logo()
    if not p:
        return None
    suffix = p.suffix.lower().replace(".", "") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else "png"
    try:
        raw = p.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/{mime};base64,{b64}"
    except Exception:
        return None


def apply_theme() -> None:
    """Apply global SPT dark-tech style."""
    st.markdown(
        """
<style>
:root {
  --spt-bg0:#050b16;
  --spt-bg1:#071426;
  --spt-panel:rgba(8,20,38,.92);
  --spt-panel2:rgba(11,43,68,.82);
  --spt-text:#f4fbff;
  --spt-muted:#9fb2c7;
  --spt-cyan:#34e8ff;
  --spt-blue:#1e86ff;
  --spt-purple:#ba5cff;
  --spt-green:#2df7b5;
}

@keyframes sptBreath {
  0%,100% {
    box-shadow:
      0 0 16px rgba(52,232,255,.16),
      0 0 36px rgba(52,232,255,.07),
      inset 0 0 18px rgba(52,232,255,.045);
    border-color: rgba(52,232,255,.26);
    filter: saturate(1.00);
  }
  50% {
    box-shadow:
      0 0 26px rgba(52,232,255,.42),
      0 0 64px rgba(186,92,255,.20),
      inset 0 0 26px rgba(52,232,255,.12);
    border-color: rgba(52,232,255,.72);
    filter: saturate(1.18);
  }
}

@keyframes sptScan {
  0% { transform: translateX(-120%); opacity: .05; }
  45% { opacity: .55; }
  100% { transform: translateX(120%); opacity: .02; }
}

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 7% 6%, rgba(103,58,183,.24), transparent 34%),
    radial-gradient(circle at 82% 9%, rgba(33,150,243,.22), transparent 37%),
    linear-gradient(135deg, #050914 0%, #071321 48%, #061729 100%) !important;
  color: var(--spt-text) !important;
}
[data-testid="stHeader"] { background: rgba(5,11,22,.72) !important; }
.block-container { padding-top: 1.45rem; max-width: 1660px; }

/* Sidebar */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #071426 0%, #05101d 100%) !important;
  border-right: 1px solid rgba(52,232,255,.26);
}
[data-testid="stSidebar"] * { color:#eefaff !important; font-weight:780; }
[data-testid="stSidebarNav"] a {
  color:#eefaff !important;
  border-radius:10px;
  margin:4px 6px;
}
[data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: linear-gradient(90deg, rgba(52,232,255,.30), rgba(186,92,255,.22)) !important;
  box-shadow: inset 3px 0 0 var(--spt-cyan), 0 0 18px rgba(52,232,255,.24);
}

h1,h2,h3,h4,h5,h6,p,span,div,label { color: var(--spt-text); }
[data-testid="stCaptionContainer"] { color: var(--spt-muted) !important; }

.spt-hero {
  position: relative;
  overflow: hidden;
  min-height: 112px;
  border: 1px solid rgba(52,232,255,.34);
  border-radius: 22px;
  padding: 20px 24px;
  margin: 4px 0 24px 0;
  background:
    radial-gradient(circle at 98% 8%, rgba(52,232,255,.20), transparent 34%),
    linear-gradient(105deg, rgba(8,18,35,.96), rgba(11,48,75,.82));
  animation: sptBreath 3.4s ease-in-out infinite;
}
.spt-hero::after {
  content:"";
  position:absolute;
  top:0;
  left:0;
  width:44%;
  height:100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.09), transparent);
  animation: sptScan 4.8s ease-in-out infinite;
  pointer-events:none;
}
.spt-hero-inner {
  position: relative;
  z-index: 2;
  display: flex;
  gap: 24px;
  align-items: center;
}
.spt-logo-wrap {
  width: 205px;
  min-width: 205px;
  height: 72px;
  display:flex;
  align-items:center;
  justify-content:center;
  border-radius: 14px;
  background: rgba(255,255,255,.96);
  padding: 8px 12px;
  box-shadow: 0 0 18px rgba(52,232,255,.20);
}
.spt-logo-wrap img { max-width:100%; max-height:100%; object-fit:contain; }
.spt-logo-fallback {
  font-size: 28px;
  font-weight: 950;
  letter-spacing: 2px;
  color: #f4fbff;
  text-shadow: 0 0 16px rgba(52,232,255,.45);
}
.spt-title-main {
  font-size: 34px;
  line-height: 1.18;
  font-weight: 950;
  letter-spacing: .5px;
  color: #f9fdff;
  text-shadow: 0 0 16px rgba(52,232,255,.34), 0 0 26px rgba(186,92,255,.18);
}
.spt-title-sub {
  margin-top: 10px;
  font-size: 14px;
  letter-spacing: .25px;
  color: #abc0d5;
}
.spt-divider {
  height:1px;
  background: linear-gradient(90deg, rgba(52,232,255,.03), rgba(52,232,255,.58), rgba(186,92,255,.42), rgba(52,232,255,.03));
  margin: 6px 0 22px 0;
}
.spt-module-card {
  min-height: 118px;
  border:1px solid rgba(52,232,255,.24);
  border-radius:18px;
  padding:18px 18px;
  background: linear-gradient(145deg, rgba(9,22,42,.88), rgba(10,37,61,.72));
  animation: sptBreath 4.2s ease-in-out infinite;
}
.spt-module-no { color:#71f2ff; font-size:18px; font-weight:950; }
.spt-module-name { font-size:22px; font-weight:920; margin-top:4px; }
.spt-module-desc { color:#9fb2c7; font-size:13px; margin-top:10px; }

/* Native containers / metrics also glow */
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 20px !important;
  border: 1px solid rgba(52,232,255,.26) !important;
  background: linear-gradient(145deg, rgba(9,22,42,.88), rgba(10,37,61,.68)) !important;
  animation: sptBreath 4.0s ease-in-out infinite;
}
[data-testid="stMetric"] {
  background: linear-gradient(145deg, rgba(9,22,42,.90), rgba(10,37,61,.72));
  border: 1px solid rgba(52,232,255,.18);
  border-radius: 18px;
  padding: 16px 18px;
  box-shadow: 0 0 20px rgba(52,232,255,.10);
}
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  border: 1px solid rgba(52,232,255,.18);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 0 22px rgba(52,232,255,.10);
}
.stButton>button, .stDownloadButton>button {
  border-radius: 12px !important;
  border: 1px solid rgba(52,232,255,.35) !important;
  background: linear-gradient(90deg, rgba(10,35,60,.96), rgba(20,68,98,.94)) !important;
  color: #f4fbff !important;
  box-shadow: 0 0 14px rgba(52,232,255,.16);
}
.stButton>button:hover, .stDownloadButton>button:hover {
  border-color: var(--spt-cyan) !important;
  box-shadow: 0 0 24px rgba(52,232,255,.34);
}

@media (max-width: 900px) {
  .spt-hero-inner { flex-direction: column; align-items: flex-start; }
  .spt-logo-wrap { width: 190px; min-width: 190px; }
  .spt-title-main { font-size: 26px; }
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
    logo_uri = _logo_data_uri() if logo else None
    if logo_uri:
        logo_html = f'<div class="spt-logo-wrap"><img src="{logo_uri}" alt="Super Plus Tech Logo"></div>'
    else:
        logo_html = '<div class="spt-logo-fallback">SPT</div>'
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
