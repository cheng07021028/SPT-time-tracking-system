# -*- coding: utf-8 -*-
"""SPT Time Tracking System - visual theme service.
科技感 / 未來感 / AI 風格主題。各頁只要呼叫 apply_spt_theme() 即可。
"""
from __future__ import annotations

from pathlib import Path
import base64
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATHS = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "data" / "logo" / "logo.png",
]


def _find_logo() -> Path | None:
    for p in LOGO_PATHS:
        if p.exists():
            return p
    return None


def _logo_data_uri() -> str:
    p = _find_logo()
    if not p:
        return ""
    try:
        ext = p.suffix.lower().replace('.', '') or 'png'
        raw = base64.b64encode(p.read_bytes()).decode('utf-8')
        return f"data:image/{ext};base64,{raw}"
    except Exception:
        return ""


def apply_spt_theme() -> None:
    """套用全站主題。"""
    logo_uri = _logo_data_uri()
    logo_css = ""
    if logo_uri:
        logo_css = f"""
        [data-testid="stSidebar"]::before {{
            content: "";
            display: block;
            height: 72px;
            margin: 18px 20px 10px 20px;
            background-image: url('{logo_uri}');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: left center;
            filter: drop-shadow(0 0 10px rgba(0, 180, 255, .35));
        }}
        """

    st.markdown(
        f"""
        <style>
        :root {{
            --spt-bg: #07111f;
            --spt-panel: rgba(13, 28, 48, .88);
            --spt-panel-2: rgba(18, 42, 70, .92);
            --spt-line: rgba(80, 190, 255, .26);
            --spt-text: #eef7ff;
            --spt-muted: #a8b8ca;
            --spt-cyan: #31d7ff;
            --spt-blue: #2a90ff;
            --spt-red: #ff4968;
        }}

        html, body, [data-testid="stAppViewContainer"] {{
            background:
                radial-gradient(circle at 14% 0%, rgba(255, 0, 110, .18), transparent 30%),
                radial-gradient(circle at 86% 8%, rgba(0, 209, 255, .22), transparent 30%),
                linear-gradient(135deg, #050915 0%, #07111f 48%, #10243b 100%) !important;
            color: var(--spt-text) !important;
        }}

        [data-testid="stHeader"] {{
            background: rgba(5, 10, 20, .55) !important;
            backdrop-filter: blur(10px);
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #050b19 0%, #071122 60%, #0a1528 100%) !important;
            border-right: 1px solid rgba(49, 215, 255, .18);
            box-shadow: 8px 0 36px rgba(0, 0, 0, .35);
        }}

        {logo_css}

        [data-testid="stSidebar"] * {{
            color: #eaf6ff !important;
        }}

        [data-testid="stSidebar"] a {{
            color: #eaf6ff !important;
            font-weight: 800 !important;
            letter-spacing: .04em;
            border-radius: 14px !important;
            margin: 4px 8px !important;
            transition: .18s ease-in-out;
        }}

        [data-testid="stSidebar"] a:hover {{
            background: linear-gradient(90deg, rgba(49,215,255,.22), rgba(255,73,104,.16)) !important;
            box-shadow: 0 0 18px rgba(49,215,255,.18);
            transform: translateX(2px);
        }}

        [data-testid="stSidebar"] a[aria-current="page"] {{
            background: linear-gradient(90deg, rgba(49,215,255,.34), rgba(255,73,104,.20)) !important;
            box-shadow: inset 4px 0 0 #31d7ff, 0 0 22px rgba(49,215,255,.22);
        }}

        .block-container {{
            padding-top: 2.0rem !important;
            padding-bottom: 3rem !important;
            max-width: 1500px !important;
        }}

        h1, h2, h3, h4, h5, h6, p, label, span, div {{
            color: var(--spt-text);
        }}

        .spt-hero {{
            position: relative;
            padding: 28px 34px;
            border: 1px solid var(--spt-line);
            border-radius: 26px;
            background:
                linear-gradient(135deg, rgba(11, 25, 44, .94), rgba(21, 58, 86, .82)),
                radial-gradient(circle at 0% 0%, rgba(49, 215, 255, .20), transparent 38%);
            box-shadow: 0 0 32px rgba(49, 215, 255, .12), inset 0 0 24px rgba(255,255,255,.03);
            overflow: hidden;
            margin-bottom: 20px;
        }}
        .spt-hero::after {{
            content: "";
            position: absolute;
            inset: -2px;
            background: linear-gradient(90deg, transparent, rgba(49,215,255,.18), transparent);
            animation: sptSweep 5.5s infinite linear;
            pointer-events: none;
        }}
        @keyframes sptSweep {{
            0% {{ transform: translateX(-100%); }}
            100% {{ transform: translateX(100%); }}
        }}
        .spt-hero-inner {{ position: relative; z-index: 2; display: flex; gap: 22px; align-items: center; }}
        .spt-hero-logo {{
            width: 220px;
            min-width: 180px;
            padding: 12px 14px;
            border-radius: 18px;
            background: rgba(255,255,255,.92);
            box-shadow: 0 0 20px rgba(49,215,255,.18);
        }}
        .spt-title {{
            font-size: 34px;
            font-weight: 950;
            letter-spacing: .06em;
            margin: 0;
            color: #f7fbff !important;
            text-shadow: 0 0 18px rgba(49,215,255,.22);
        }}
        .spt-subtitle {{
            margin-top: 10px;
            color: var(--spt-muted) !important;
            font-size: 14px;
            letter-spacing: .04em;
        }}

        .spt-card {{
            border: 1px solid rgba(80, 190, 255, .22);
            border-radius: 22px;
            background: rgba(8, 20, 38, .82);
            padding: 20px 22px;
            box-shadow: 0 0 24px rgba(0, 0, 0, .18), inset 0 0 16px rgba(255,255,255,.025);
            min-height: 120px;
        }}
        .spt-card:hover {{
            border-color: rgba(49,215,255,.48);
            box-shadow: 0 0 28px rgba(49,215,255,.16);
        }}
        .spt-card-title {{ color: #bfefff !important; font-size: 14px; font-weight: 800; }}
        .spt-card-value {{ color: #ffffff !important; font-size: 32px; font-weight: 900; margin-top: 8px; }}
        .spt-card-desc {{ color: #9aacbe !important; font-size: 13px; margin-top: 4px; }}

        div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{
            border: 1px solid rgba(80, 190, 255, .18);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 0 18px rgba(49, 215, 255, .06);
        }}
        .stButton > button, .stDownloadButton > button {{
            background: linear-gradient(90deg, rgba(49,215,255,.22), rgba(255,73,104,.18)) !important;
            color: #f7fbff !important;
            border: 1px solid rgba(49,215,255,.34) !important;
            border-radius: 14px !important;
            font-weight: 900 !important;
            box-shadow: 0 0 14px rgba(49,215,255,.12);
        }}
        .stButton > button:hover, .stDownloadButton > button:hover {{
            border-color: rgba(49,215,255,.75) !important;
            box-shadow: 0 0 24px rgba(49,215,255,.22);
        }}
        .stAlert {{
            border-radius: 16px !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(title: str, subtitle: str = "", page_no: str | None = None) -> None:
    """各頁共用標題列。"""
    logo_uri = _logo_data_uri()
    page_prefix = f"{page_no}｜" if page_no else ""
    logo_html = f'<img class="spt-hero-logo" src="{logo_uri}" />' if logo_uri else ""
    st.markdown(
        f"""
        <div class="spt-hero">
          <div class="spt-hero-inner">
            {logo_html}
            <div>
              <div class="spt-title">{page_prefix}{title}</div>
              <div class="spt-subtitle">{subtitle}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(title: str, value: str | int | float, desc: str = "") -> None:
    st.markdown(
        f"""
        <div class="spt-card">
          <div class="spt-card-title">{title}</div>
          <div class="spt-card-value">{value}</div>
          <div class="spt-card-desc">{desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
