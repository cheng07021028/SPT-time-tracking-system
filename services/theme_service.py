# -*- coding: utf-8 -*-
"""SPT Time Tracking visual theme helpers.
V1.6 keeps backward compatibility for pages that still import
apply_theme / render_header, while also supporting apply_app_theme /
render_page_header used by newer files.
"""
from __future__ import annotations

from pathlib import Path
import base64
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "logococo(黑字).png",
]


def _logo_base64() -> str:
    for p in LOGO_CANDIDATES:
        if p.exists():
            try:
                return base64.b64encode(p.read_bytes()).decode("utf-8")
            except Exception:
                return ""
    return ""


def apply_app_theme() -> None:
    """Apply global dark tech style."""
    css = """
    <style>
    :root{
      --spt-bg:#07111f;
      --spt-panel:#0d1b2d;
      --spt-panel2:#102944;
      --spt-text:#eaf6ff;
      --spt-muted:#9fb5c9;
      --spt-cyan:#38d6ff;
      --spt-blue:#1d7fff;
      --spt-red:#ff385c;
    }
    html, body, [data-testid="stAppViewContainer"]{
      background:
        radial-gradient(circle at 8% 8%, rgba(255, 56, 92, .12), transparent 28%),
        radial-gradient(circle at 86% 12%, rgba(56, 214, 255, .16), transparent 30%),
        linear-gradient(135deg, #050b16 0%, #07111f 45%, #0a1b2f 100%) !important;
      color: var(--spt-text) !important;
    }
    [data-testid="stHeader"]{background: rgba(5,11,22,.28) !important;}
    [data-testid="stSidebar"]{
      background: linear-gradient(180deg,#07111f 0%,#091827 60%,#07111f 100%) !important;
      border-right:1px solid rgba(56,214,255,.22);
      box-shadow: 8px 0 30px rgba(0,0,0,.25);
    }
    [data-testid="stSidebar"] *{
      color:#eaf6ff !important;
      font-weight:700;
    }
    [data-testid="stSidebarNav"] a{
      color:#eaf6ff !important;
      border-radius:10px;
      margin:3px 8px;
    }
    [data-testid="stSidebarNav"] a:hover{
      background: linear-gradient(90deg, rgba(56,214,255,.20), rgba(255,56,92,.12)) !important;
      box-shadow: inset 3px 0 0 rgba(56,214,255,.85);
    }
    [data-testid="stSidebarNav"] a[aria-current="page"]{
      background: linear-gradient(90deg, rgba(56,214,255,.28), rgba(255,56,92,.18)) !important;
      box-shadow: 0 0 18px rgba(56,214,255,.20), inset 4px 0 0 rgba(56,214,255,.95);
    }
    h1,h2,h3,h4,h5,h6,p,span,div,label{color:var(--spt-text);}
    .stDataFrame, [data-testid="stDataFrame"]{
      border:1px solid rgba(56,214,255,.18);
      border-radius:14px;
      overflow:hidden;
      box-shadow:0 0 26px rgba(56,214,255,.08);
    }
    .spt-hero{
      margin: 0 0 1.35rem 0;
      padding: 1.25rem 1.45rem;
      border-radius: 22px;
      border: 1px solid rgba(56,214,255,.25);
      background: linear-gradient(135deg, rgba(14,29,48,.92), rgba(17,62,90,.76));
      box-shadow: 0 0 26px rgba(56,214,255,.13), inset 0 0 34px rgba(56,214,255,.05);
      position: relative;
      overflow:hidden;
    }
    .spt-hero:before{
      content:"";
      position:absolute;
      inset:-2px;
      background: linear-gradient(90deg, transparent, rgba(56,214,255,.12), transparent);
      animation:sptGlow 3.6s ease-in-out infinite;
    }
    @keyframes sptGlow{0%,100%{opacity:.30;}50%{opacity:.85;}}
    .spt-hero-inner{position:relative; z-index:1; display:flex; align-items:center; gap:22px;}
    .spt-logo{width:150px; max-height:58px; object-fit:contain; background:rgba(255,255,255,.94); padding:7px 12px; border-radius:12px;}
    .spt-title{font-size:2rem; font-weight:900; letter-spacing:.04em; margin-bottom:.35rem; color:#f4fbff;}
    .spt-subtitle{font-size:.95rem; color:#a9bfd2; letter-spacing:.03em;}
    .spt-kpi-card{
      border:1px solid rgba(56,214,255,.18);
      background:rgba(11,24,40,.72);
      border-radius:18px;
      padding:1.05rem 1.15rem;
      box-shadow:0 0 24px rgba(56,214,255,.07);
    }
    .spt-kpi-label{font-size:.9rem;color:#9fb5c9;font-weight:700;}
    .spt-kpi-value{font-size:1.75rem;color:#f4fbff;font-weight:900;margin-top:.3rem;}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str = "", page_code: str | None = None) -> None:
    """Render a common page header. HTML must be rendered, not printed as code."""
    logo64 = _logo_base64()
    code_html = f"<span style='color:#38d6ff;margin-right:.45rem'>{page_code}</span>" if page_code else ""
    logo_html = f"<img class='spt-logo' src='data:image/png;base64,{logo64}' />" if logo64 else ""
    st.markdown(
        f"""
        <div class="spt-hero">
          <div class="spt-hero-inner">
            {logo_html}
            <div>
              <div class="spt-title">{code_html}{title}</div>
              <div class="spt-subtitle">{subtitle}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Backward-compatible names used by older V1.3 pages.
def apply_theme() -> None:
    apply_app_theme()


def render_header(title: str, subtitle: str = "", page_code: str | None = None) -> None:
    render_page_header(title=title, subtitle=subtitle, page_code=page_code)


def kpi_card(label: str, value: str | int | float) -> str:
    return f"""
    <div class='spt-kpi-card'>
      <div class='spt-kpi-label'>{label}</div>
      <div class='spt-kpi-value'>{value}</div>
    </div>
    """
