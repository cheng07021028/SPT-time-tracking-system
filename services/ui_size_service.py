# -*- coding: utf-8 -*-
"""UI size-only helpers.

This module intentionally changes only dimensions, not colors, shadows, fonts,
or rendering style.  It is used for cases where Streamlit/BaseWeb dropdown menu
viewport is too short and forces unnecessary scrolling.
"""
from __future__ import annotations


def apply_dropdown_menu_size_only(max_height_px: int = 520) -> None:
    """Increase opened dropdown menu viewport height without changing style."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        h = max(220, min(int(max_height_px), 900))
    except Exception:
        h = 520
    st.markdown(
        f"""
        <style>
        /* V3.34 size-only dropdown menu height fix: no color/style changes. */
        div[data-baseweb="popover"] div[role="listbox"],
        div[data-baseweb="popover"] ul[role="listbox"],
        div[data-baseweb="menu"],
        ul[role="listbox"] {{
            max-height: {h}px !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
