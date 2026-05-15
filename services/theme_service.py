# -*- coding: utf-8 -*-
"""
SPT Time Tracking - Unified Theme Service
V1.53: restore legacy visual style, fix render_kpi_cards compatibility,
restore logo rendering, sidebar styling and dropdown/input contrast.

This file is intentionally self-contained and backwards-compatible.
It provides the function names used by old and new pages:
- apply_theme / app_theme
- render_home_header
- render_header
- render_kpi_cards
- render_module_cards
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import base64
import html

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_CANDIDATES = [
    PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png",
    PROJECT_ROOT / "data" / "logo" / "logococo(黑字).png",
    PROJECT_ROOT / "super_plus_logo.png",
]


def _logo_base64() -> str:
    """Return base64 for logo if available; otherwise empty string."""
    for p in LOGO_CANDIDATES:
        try:
            if p.exists() and p.is_file():
                return base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception:
            continue
    return ""


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def apply_theme() -> None:
    """Apply global Streamlit visual theme. Safe to call repeatedly."""
    logo_b64 = _logo_base64()
    st.markdown(
        f"""
<style>
/* =========================================================
   SPT Unified War-Room Theme V1.53
   ========================================================= */

:root {{
    --spt-bg: #06111f;
    --spt-bg-2: #071a2c;
    --spt-card: rgba(7, 26, 44, 0.82);
    --spt-card-2: rgba(10, 41, 64, 0.74);
    --spt-cyan: #20e6ff;
    --spt-cyan-2: #63f3ff;
    --spt-blue: #1a74ff;
    --spt-purple: #34205f;
    --spt-text: #f3fbff;
    --spt-muted: rgba(215, 232, 245, .72);
    --spt-line: rgba(32, 230, 255, .30);
}}

html, body, [data-testid="stAppViewContainer"] {{
    background:
      radial-gradient(circle at 12% 0%, rgba(80, 54, 140, .26), transparent 30%),
      radial-gradient(circle at 92% 12%, rgba(0, 180, 255, .18), transparent 28%),
      linear-gradient(135deg, #050b18 0%, #071524 45%, #082238 100%) !important;
    color: var(--spt-text) !important;
}}

[data-testid="stHeader"] {{
    background: rgba(4, 10, 18, .78) !important;
    border-bottom: 1px solid rgba(32, 230, 255, .08) !important;
}}

.block-container {{
    padding-top: 2.1rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 96rem !important;
}}

/* Sidebar restored style */
[data-testid="stSidebar"] {{
    background:
      radial-gradient(circle at 0% 15%, rgba(47, 34, 95, .35), transparent 28%),
      linear-gradient(180deg, #07111f 0%, #061827 100%) !important;
    border-right: 1px solid rgba(32, 230, 255, .20) !important;
}}

[data-testid="stSidebar"] * {{
    color: #f5fbff !important;
    font-weight: 700 !important;
}}

[data-testid="stSidebar"] [data-testid="stSidebarNav"] {{
    padding-top: 1.2rem !important;
}}

[data-testid="stSidebar"] a {{
    border-radius: 11px !important;
    margin: 4px 8px !important;
    padding: 8px 10px !important;
    transition: all .16s ease-in-out !important;
}}

[data-testid="stSidebar"] a:hover {{
    background: linear-gradient(90deg, rgba(32,230,255,.22), rgba(80,54,140,.28)) !important;
    box-shadow: 0 0 16px rgba(32, 230, 255, .12) !important;
}}

[data-testid="stSidebar"] a[aria-current="page"] {{
    background: linear-gradient(90deg, rgba(32,230,255,.38), rgba(80,54,140,.55)) !important;
    box-shadow:
      inset 3px 0 0 var(--spt-cyan),
      0 0 22px rgba(32, 230, 255, .18) !important;
}}

/* Unified module header */
.spt-header {{
    position: relative;
    display: flex;
    align-items: center;
    gap: 26px;
    min-height: 128px;
    padding: 22px 30px;
    margin: 18px 0 28px 0;
    border: 1px solid rgba(32, 230, 255, .55);
    border-radius: 22px;
    background:
       linear-gradient(90deg, rgba(7, 18, 32, .92), rgba(8, 72, 98, .70)),
       radial-gradient(circle at 80% 35%, rgba(32, 230, 255, .14), transparent 30%);
    box-shadow:
       0 0 0 1px rgba(32, 230, 255, .08) inset,
       0 0 28px rgba(32, 230, 255, .15),
       0 0 55px rgba(49, 76, 255, .10);
    overflow: hidden;
}}

.spt-header::before {{
    content: "";
    position: absolute;
    inset: -2px;
    border-radius: 24px;
    background: linear-gradient(120deg, transparent, rgba(32,230,255,.22), transparent);
    opacity: .50;
    animation: sptBreath 3.2s ease-in-out infinite;
    pointer-events: none;
}}

@keyframes sptBreath {{
    0%,100% {{ opacity: .23; filter: blur(.2px); }}
    50% {{ opacity: .75; filter: blur(1px); }}
}}

.spt-logo-box {{
    flex: 0 0 238px;
    width: 238px;
    height: 86px;
    border-radius: 14px;
    background: rgba(255,255,255,.96);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    box-shadow: 0 10px 35px rgba(0,0,0,.28);
}}

.spt-logo-box img {{
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}}

.spt-logo-fallback {{
    font-size: 1.7rem;
    letter-spacing: .28rem;
    color: #071524 !important;
    font-weight: 900 !important;
}}

.spt-header-main {{
    position: relative;
    z-index: 1;
}}

.spt-header-title {{
    font-size: clamp(2.0rem, 3vw, 3.0rem);
    line-height: 1.08;
    font-weight: 950;
    letter-spacing: .05rem;
    color: #f7fdff;
    text-shadow: 0 0 14px rgba(32,230,255,.24);
}}

.spt-header-subtitle {{
    margin-top: .65rem;
    font-size: 1.08rem;
    font-weight: 700;
    color: rgba(230, 244, 255, .72);
}}

/* KPI cards */
.spt-kpi-grid {{
    display: grid;
    grid-template-columns: repeat(4, minmax(180px, 1fr));
    gap: 14px;
    margin: 14px 0 22px 0;
}}

.spt-kpi-card {{
    border: 1px solid rgba(32, 230, 255, .30);
    border-radius: 16px;
    background: rgba(7, 26, 44, .72);
    padding: 16px 18px;
    min-height: 94px;
    box-shadow: 0 0 20px rgba(32, 230, 255, .08);
}}

.spt-kpi-label {{
    font-size: .95rem;
    color: rgba(225, 242, 255, .82);
    font-weight: 800;
}}

.spt-kpi-value {{
    margin-top: .5rem;
    font-size: 2rem;
    line-height: 1.0;
    color: #ffffff;
    font-weight: 900;
    letter-spacing: .03rem;
}}

/* Module cards */
.spt-module-grid {{
    display: grid;
    grid-template-columns: repeat(4, minmax(220px, 1fr));
    gap: 16px;
    margin: 16px 0 26px 0;
}}

.spt-module-card {{
    border: 1px solid rgba(32, 230, 255, .23);
    border-radius: 14px;
    background: rgba(7, 18, 32, .74);
    padding: 20px 18px;
    min-height: 112px;
    box-shadow: 0 0 18px rgba(32, 230, 255, .06);
}}

.spt-module-no {{
    color: var(--spt-cyan-2);
    font-size: .95rem;
    font-weight: 900;
}}

.spt-module-name {{
    color: #ffffff;
    font-size: 1.55rem;
    font-weight: 950;
    margin-top: .18rem;
}}

.spt-module-desc {{
    color: rgba(224, 239, 250, .70);
    font-size: .92rem;
    margin-top: .55rem;
    font-weight: 650;
}}

/* Inputs - light background and dark text */
div[data-baseweb="input"] input,
div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea,
textarea,
input[type="text"],
input[type="password"],
input[type="number"] {{
    background: rgba(245, 250, 255, .94) !important;
    color: #081827 !important;
    -webkit-text-fill-color: #081827 !important;
    border: 1px solid rgba(93, 218, 255, .55) !important;
    border-radius: 12px !important;
    font-weight: 750 !important;
}}

div[data-baseweb="input"] input::placeholder,
div[data-baseweb="textarea"] textarea::placeholder,
textarea::placeholder {{
    color: rgba(30, 60, 86, .62) !important;
    -webkit-text-fill-color: rgba(30, 60, 86, .62) !important;
}}

/* Select closed state */
div[data-baseweb="select"] > div {{
    background: rgba(245, 250, 255, .94) !important;
    border: 1px solid rgba(93, 218, 255, .55) !important;
    border-radius: 12px !important;
}}

div[data-baseweb="select"] > div * {{
    color: #081827 !important;
    -webkit-text-fill-color: #081827 !important;
    font-weight: 800 !important;
}}

/* Select dropdown menu: dark background + light text */
div[data-baseweb="popover"],
div[data-baseweb="popover"] > div,
ul[role="listbox"],
[role="listbox"] {{
    background: #06111f !important;
    border: 1px solid rgba(32, 230, 255, .38) !important;
    border-radius: 12px !important;
    box-shadow: 0 16px 34px rgba(0,0,0,.45) !important;
}}

ul[role="listbox"] li,
ul[role="listbox"] div,
[role="option"],
[role="option"] * {{
    background: transparent !important;
    color: #f5fbff !important;
    -webkit-text-fill-color: #f5fbff !important;
    font-weight: 850 !important;
}}

ul[role="listbox"] li:hover,
[role="option"]:hover {{
    background: rgba(32, 230, 255, .18) !important;
}}

ul[role="listbox"] li[aria-selected="true"],
[role="option"][aria-selected="true"] {{
    background: #27e6f2 !important;
}}

ul[role="listbox"] li[aria-selected="true"] *,
[role="option"][aria-selected="true"] * {{
    color: #06111f !important;
    -webkit-text-fill-color: #06111f !important;
}}

/* Data editor */
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] [contenteditable="true"] {{
    background: rgba(245, 250, 255, .96) !important;
    color: #081827 !important;
    -webkit-text-fill-color: #081827 !important;
    font-weight: 850 !important;
}}

[data-testid="stDataEditor"] [role="gridcell"] {{
    color: #f3fbff !important;
    font-weight: 700 !important;
}}

[data-testid="stDataEditor"] [role="columnheader"] {{
    background: rgba(255,255,255,.08) !important;
    color: #eaf8ff !important;
    font-weight: 850 !important;
}}

/* Buttons */
.stButton > button {{
    border: 1px solid rgba(32, 230, 255, .48) !important;
    border-radius: 12px !important;
    background: rgba(8, 61, 91, .72) !important;
    color: #f5fbff !important;
    font-weight: 850 !important;
    box-shadow: 0 0 14px rgba(32,230,255,.08) !important;
}}

.stButton > button:hover {{
    border-color: rgba(32, 230, 255, .85) !important;
    box-shadow: 0 0 20px rgba(32,230,255,.20) !important;
}}

/* Alert readability */
.stAlert {{
    border-radius: 12px !important;
}}

/* Prevent raw code-like header boxes from previous bad HTML */
pre, code {{
    white-space: pre-wrap !important;
}}

@media (max-width: 1000px) {{
    .spt-header {{
        flex-direction: column;
        align-items: flex-start;
    }}
    .spt-logo-box {{
        width: 220px;
        flex-basis: 78px;
    }}
    .spt-kpi-grid,
    .spt-module-grid {{
        grid-template-columns: repeat(2, minmax(180px, 1fr));
    }}
}}
</style>
        """,
        unsafe_allow_html=True,
    )


def app_theme() -> None:
    apply_theme()


def _render_header_html(title: str, subtitle: str = "", number: str | None = None) -> None:
    logo_b64 = _logo_base64()
    if logo_b64:
        logo_html = f'<img src="data:image/png;base64,{logo_b64}" alt="SPT Logo" />'
    else:
        logo_html = '<div class="spt-logo-fallback">SPT</div>'

    prefix = f"{_safe_text(number)}｜" if number else ""
    st.markdown(
        f"""
<div class="spt-header">
  <div class="spt-logo-box">{logo_html}</div>
  <div class="spt-header-main">
    <div class="spt-header-title">{prefix}{_safe_text(title)}</div>
    <div class="spt-header-subtitle">{_safe_text(subtitle)}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_home_header(
    title: str = "超慧科技製造部｜智慧工時紀錄系統",
    subtitle: str = "Super Plus Tech Manufacturing Time Tracking System | Streamlit + SQLite + Github Cloud Storage",
    *args: Any,
    **kwargs: Any,
) -> None:
    _render_header_html(title=title, subtitle=subtitle, number=None)


def render_header(
    title: str = "",
    subtitle: str = "",
    number: str | None = None,
    module_no: str | None = None,
    module_number: str | None = None,
    *args: Any,
    **kwargs: Any,
) -> None:
    no = module_no or module_number or number
    _render_header_html(title=title, subtitle=subtitle, number=no)


def _normalise_kpi_item(item: Any) -> tuple[str, str]:
    """Accept dicts, tuples/lists, or scalar labels without crashing."""
    if isinstance(item, dict):
        label = item.get("label") or item.get("name") or item.get("title") or item.get("key") or ""
        value = item.get("value") or item.get("count") or item.get("text") or ""
        return str(label), str(value)
    if isinstance(item, (list, tuple)):
        if len(item) >= 2:
            return str(item[0]), str(item[1])
        if len(item) == 1:
            return str(item[0]), ""
        return "", ""
    return str(item), ""


def render_kpi_cards(*items: Any, **kwargs: Any) -> None:
    """
    Backward-compatible KPI renderer.
    Supports:
      render_kpi_cards([("label", "value"), ...])
      render_kpi_cards(("label", "value"), ...)
      render_kpi_cards(cards=[...])
      render_kpi_cards({"label": "...", "value": "..."})
    """
    cards = kwargs.get("cards", None)
    if cards is None and len(items) == 1 and isinstance(items[0], (list, tuple)) and not (
        len(items[0]) >= 2 and not isinstance(items[0][0], (list, tuple, dict))
    ):
        cards = items[0]
    elif cards is None:
        cards = items

    normalised = [_normalise_kpi_item(x) for x in list(cards or [])]
    if not normalised:
        return

    html_cards = []
    for label, value in normalised:
        html_cards.append(
            f"""
<div class="spt-kpi-card">
  <div class="spt-kpi-label">{_safe_text(label)}</div>
  <div class="spt-kpi-value">{_safe_text(value)}</div>
</div>
            """
        )

    st.markdown(
        '<div class="spt-kpi-grid">' + "\n".join(html_cards) + "</div>",
        unsafe_allow_html=True,
    )


def _normalise_module_item(item: Any) -> tuple[str, str, str]:
    if isinstance(item, dict):
        no = item.get("no") or item.get("number") or item.get("module_no") or ""
        name = item.get("name") or item.get("title") or ""
        desc = item.get("desc") or item.get("description") or item.get("subtitle") or ""
        return str(no), str(name), str(desc)
    if isinstance(item, (list, tuple)):
        no = str(item[0]) if len(item) > 0 else ""
        name = str(item[1]) if len(item) > 1 else ""
        desc = str(item[2]) if len(item) > 2 else ""
        return no, name, desc
    return "", str(item), ""


def render_module_cards(modules: Iterable[Any] | None = None, *args: Any, **kwargs: Any) -> None:
    if modules is None:
        modules = kwargs.get("cards") or kwargs.get("items") or []

    normalised = [_normalise_module_item(m) for m in modules]
    if not normalised:
        return

    html_cards = []
    for no, name, desc in normalised:
        html_cards.append(
            f"""
<div class="spt-module-card">
  <div class="spt-module-no">{_safe_text(no)}</div>
  <div class="spt-module-name">{_safe_text(name)}</div>
  <div class="spt-module-desc">{_safe_text(desc)}</div>
</div>
            """
        )

    st.markdown(
        '<div class="spt-module-grid">' + "\n".join(html_cards) + "</div>",
        unsafe_allow_html=True,
    )
