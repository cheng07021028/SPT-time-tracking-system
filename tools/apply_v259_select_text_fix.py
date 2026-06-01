# -*- coding: utf-8 -*-
"""V2.59 hotfix: append a robust Streamlit select/multiselect CSS fix to services/theme_service.py.
Run from project root:
    python tools/apply_v259_select_text_fix.py
This patch is append-only and keeps existing theme_service.py logic intact.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "services" / "theme_service.py"
MARKER_START = "# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX START ====="
MARKER_END = "# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX END ====="

PATCH = r'''
# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX START =====
def apply_v259_select_multiselect_text_fix():
    """Fix clipped text in Streamlit selectbox / multiselect after global font scaling.
    Safe to call multiple times. Does not change data, filters, permissions, or calculations.
    """
    try:
        import streamlit as st
    except Exception:
        return

    st.markdown(
        """
        <style>
        /* V2.59: BaseWeb select / multiselect text clipping final fix */
        .stSelectbox,
        .stMultiSelect {
            overflow: visible !important;
        }

        /* Outer select shell: keep enough height for larger global font scale */
        div[data-baseweb="select"] {
            min-height: 52px !important;
            height: auto !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        div[data-baseweb="select"] > div {
            min-height: 52px !important;
            height: auto !important;
            padding-top: 7px !important;
            padding-bottom: 7px !important;
            display: flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        /* Selected value / placeholder area */
        div[data-baseweb="select"] div[role="combobox"],
        div[data-baseweb="select"] div[aria-expanded],
        div[data-baseweb="select"] div[class*="valueContainer"] {
            min-height: 38px !important;
            height: auto !important;
            display: flex !important;
            align-items: center !important;
            flex-wrap: wrap !important;
            overflow: visible !important;
            line-height: 1.45 !important;
        }

        /* Selectbox visible text and placeholder */
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] p,
        div[data-baseweb="select"] div {
            line-height: 1.45 !important;
            white-space: nowrap !important;
            text-overflow: ellipsis !important;
            color: #061427 !important;
            font-weight: 800 !important;
        }

        /* Internal search input used by BaseWeb select; avoid cropped cursor / white block */
        div[data-baseweb="select"] input {
            min-height: 32px !important;
            height: 32px !important;
            line-height: 1.45 !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            color: #061427 !important;
            caret-color: #061427 !important;
            font-weight: 800 !important;
            background: transparent !important;
            box-shadow: none !important;
            overflow: visible !important;
        }

        /* Multiselect selected tags */
        div[data-baseweb="tag"] {
            min-height: 32px !important;
            height: auto !important;
            padding: 5px 10px !important;
            margin: 3px 4px 3px 0 !important;
            border-radius: 9px !important;
            display: inline-flex !important;
            align-items: center !important;
            overflow: visible !important;
            line-height: 1.45 !important;
            background: linear-gradient(135deg, #bff7ff 0%, #82e9ff 100%) !important;
            border: 1px solid rgba(36, 226, 255, 0.75) !important;
            color: #061427 !important;
            font-weight: 900 !important;
        }

        div[data-baseweb="tag"] span,
        div[data-baseweb="tag"] div {
            color: #061427 !important;
            font-weight: 900 !important;
            line-height: 1.45 !important;
            overflow: visible !important;
        }

        div[data-baseweb="tag"] svg {
            color: #061427 !important;
            fill: #061427 !important;
            stroke: #061427 !important;
        }

        /* Dropdown list options */
        ul[role="listbox"],
        div[role="listbox"] {
            overflow: auto !important;
        }

        ul[role="listbox"] li,
        div[role="option"] {
            min-height: 40px !important;
            height: auto !important;
            padding-top: 9px !important;
            padding-bottom: 9px !important;
            display: flex !important;
            align-items: center !important;
            line-height: 1.45 !important;
            font-weight: 800 !important;
        }

        /* Number input plus/minus should not inherit select fixes */
        div[data-testid="stNumberInput"] input {
            line-height: 1.35 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# Apply on import so every module that imports theme_service receives the fix.
try:
    apply_v259_select_multiselect_text_fix()
except Exception:
    pass
# ===== V2.59 SELECT / MULTISELECT TEXT CLIP FIX END =====
'''


def main() -> int:
    if not THEME.exists():
        raise SystemExit(f"找不到 {THEME}. 請在專案根目錄執行。")
    text = THEME.read_text(encoding="utf-8")
    if MARKER_START in text and MARKER_END in text:
        before = text.split(MARKER_START)[0].rstrip()
        after = text.split(MARKER_END, 1)[1].lstrip()
        text = before + "\n\n" + PATCH.strip() + "\n\n" + after
    else:
        text = text.rstrip() + "\n\n" + PATCH.strip() + "\n"
    THEME.write_text(text, encoding="utf-8")
    print("V2.59 select/multiselect text clipping fix applied to services/theme_service.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
