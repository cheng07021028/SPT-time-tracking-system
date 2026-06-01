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
        _v30040_install_01_url_rerun_component_guard()
    except Exception:
        pass
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


# ================= V300.40 01 URL-RERUN COMPONENT GUARD =================
# 2026-06-01
# 01.工時紀錄 has an old local components.html script that rewrites the browser
# URL query string (spt_wo_kw) while the page is rendering. On Streamlit Cloud
# this can leave the page in a permanent running/rerun state after login.
# We do not edit page layout/CSS/theme here; we only suppress that specific
# legacy URL-rerun component. Native Streamlit text_input still works normally.
_V30040_COMPONENT_GUARD_READY = False
_V30040_COMPONENT_GUARD_BLOCKED_COUNT = 0


def _v30040_install_01_url_rerun_component_guard() -> None:
    global _V30040_COMPONENT_GUARD_READY, _V30040_COMPONENT_GUARD_BLOCKED_COUNT
    if _V30040_COMPONENT_GUARD_READY:
        return
    try:
        try:
            import streamlit.components.v1 as components
        except Exception:
            import sys as _sys
            components = _sys.modules.get("streamlit.components.v1")
            if components is None:
                raise
        original_html = getattr(components, "html", None)
        if not callable(original_html) or getattr(original_html, "_spt_v30040_guard", False):
            _V30040_COMPONENT_GUARD_READY = True
            return

        def _guarded_html(body=None, *args, **kwargs):
            global _V30040_COMPONENT_GUARD_BLOCKED_COUNT
            try:
                text = str(body or "")
                if "spt_wo_kw" in text and "window.parent.location.replace" in text:
                    _V30040_COMPONENT_GUARD_BLOCKED_COUNT += 1
                    return None
            except Exception:
                pass
            return original_html(body, *args, **kwargs)

        setattr(_guarded_html, "_spt_v30040_guard", True)
        setattr(_guarded_html, "_spt_v30040_original", original_html)
        components.html = _guarded_html
        _V30040_COMPONENT_GUARD_READY = True
    except Exception:
        _V30040_COMPONENT_GUARD_READY = False


def audit_v30040_01_url_rerun_component_guard() -> dict:
    return {
        "version": "V300.40_01_URL_RERUN_COMPONENT_GUARD",
        "installed": bool(_V30040_COMPONENT_GUARD_READY),
        "blocked_count": int(_V30040_COMPONENT_GUARD_BLOCKED_COUNT),
        "changes_ui_css_theme": False,
        "changes_data_read_write_rules": False,
    }
# ================= END V300.40 01 URL-RERUN COMPONENT GUARD =================
