# -*- coding: utf-8 -*-
"""SPT Time Tracking V1.40 - dropdown/input contrast fix.

This script patches services/theme_service.py without overwriting existing features.
It appends a small compatibility wrapper so every existing apply_theme()/app_theme()
call also injects global dropdown contrast CSS.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "services" / "theme_service.py"
MARKER = "# === SPT V1.40 DROPDOWN CONTRAST FIX START ==="

APPEND_BLOCK = r'''

# === SPT V1.40 DROPDOWN CONTRAST FIX START ===
def inject_dropdown_contrast_css_v1_40():
    """Global selectbox/data-editor dropdown contrast fix.
    深色下拉底色搭配淺色文字；淺色輸入格搭配深色文字。
    """
    try:
        import streamlit as st
    except Exception:
        return
    st.markdown("""
    <style>
    /* =========================================================
       SPT V1.40 - 全模組下拉式選單 / 表格輸入對比修正
       原則：
       1) 下拉選單展開時：深色底 + 淺色字
       2) 一般輸入框 / 表格編輯格：淺色底 + 深色字
       3) 套用全系統，不逐頁修改
       ========================================================= */

    /* ---------- Selectbox / Multiselect 原始顯示區 ---------- */
    div[data-baseweb="select"] > div,
    div[data-baseweb="select"] div[role="combobox"] {
        background: rgba(235, 246, 255, 0.95) !important;
        color: #061527 !important;
        border: 1px solid rgba(64, 220, 255, 0.55) !important;
        border-radius: 10px !important;
        box-shadow: inset 0 0 0 1px rgba(0, 180, 255, 0.08), 0 0 10px rgba(0, 220, 255, 0.08) !important;
    }
    div[data-baseweb="select"] span,
    div[data-baseweb="select"] input,
    div[data-baseweb="select"] [class*="singleValue"],
    div[data-baseweb="select"] [class*="placeholder"] {
        color: #061527 !important;
        -webkit-text-fill-color: #061527 !important;
        font-weight: 700 !important;
    }

    /* ---------- 下拉展開選單：深色底 + 淺色字 ---------- */
    div[data-baseweb="popover"],
    div[data-baseweb="popover"] > div,
    div[data-baseweb="menu"],
    ul[role="listbox"] {
        background: #061527 !important;
        border: 1px solid rgba(64, 220, 255, 0.55) !important;
        border-radius: 12px !important;
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.55), 0 0 22px rgba(0, 220, 255, 0.16) !important;
    }
    ul[role="listbox"] li,
    ul[role="listbox"] div,
    div[data-baseweb="menu"] div,
    div[data-baseweb="popover"] div[role="option"] {
        background-color: #061527 !important;
        color: #eaf7ff !important;
        -webkit-text-fill-color: #eaf7ff !important;
        font-weight: 700 !important;
    }
    ul[role="listbox"] li:hover,
    div[data-baseweb="menu"] div:hover,
    div[data-baseweb="popover"] div[role="option"]:hover {
        background: rgba(0, 224, 255, 0.22) !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    div[data-baseweb="popover"] div[aria-selected="true"],
    ul[role="listbox"] li[aria-selected="true"] {
        background: #26e6ff !important;
        color: #001522 !important;
        -webkit-text-fill-color: #001522 !important;
        font-weight: 900 !important;
    }

    /* ---------- 一般輸入框：淺色底 + 深色字 ---------- */
    div[data-baseweb="input"] input,
    div[data-baseweb="base-input"] input,
    div[data-baseweb="textarea"] textarea,
    input[type="text"],
    input[type="password"],
    input[type="number"],
    textarea {
        background: rgba(235, 246, 255, 0.96) !important;
        color: #061527 !important;
        -webkit-text-fill-color: #061527 !important;
        caret-color: #061527 !important;
        font-weight: 700 !important;
    }
    div[data-baseweb="input"] input::placeholder,
    div[data-baseweb="textarea"] textarea::placeholder,
    input::placeholder,
    textarea::placeholder {
        color: rgba(6, 21, 39, 0.62) !important;
        -webkit-text-fill-color: rgba(6, 21, 39, 0.62) !important;
    }

    /* ---------- Date / Time / Number 外層修正 ---------- */
    .stDateInput input,
    .stTimeInput input,
    .stNumberInput input {
        background: rgba(235, 246, 255, 0.96) !important;
        color: #061527 !important;
        -webkit-text-fill-color: #061527 !important;
        font-weight: 700 !important;
    }

    /* ---------- st.data_editor 表格編輯中輸入格 ---------- */
    [data-testid="stDataEditor"] input,
    [data-testid="stDataEditor"] textarea,
    [data-testid="stDataEditor"] select,
    [data-testid="stDataEditor"] [contenteditable="true"] {
        background: rgba(235, 246, 255, 0.96) !important;
        color: #061527 !important;
        -webkit-text-fill-color: #061527 !important;
        caret-color: #061527 !important;
        font-weight: 800 !important;
    }
    [data-testid="stDataEditor"] [role="gridcell"] input,
    [data-testid="stDataEditor"] [role="gridcell"] textarea {
        background: rgba(235, 246, 255, 0.98) !important;
        color: #061527 !important;
        -webkit-text-fill-color: #061527 !important;
    }
    [data-testid="stDataEditor"] [role="gridcell"]:focus-within {
        box-shadow: inset 0 0 0 1px rgba(0, 220, 255, 0.85), 0 0 14px rgba(0, 220, 255, 0.18) !important;
    }

    /* ---------- 表格內下拉展開時，也強制深底淺字 ---------- */
    [data-testid="stDataEditor"] div[data-baseweb="popover"],
    [data-testid="stDataEditor"] div[data-baseweb="menu"],
    [data-testid="stDataEditor"] ul[role="listbox"] {
        background: #061527 !important;
        color: #eaf7ff !important;
    }

    /* ---------- 深色欄位區內的 disabled / read-only 文字仍可讀 ---------- */
    input:disabled,
    textarea:disabled,
    [aria-disabled="true"] input {
        background: rgba(210, 226, 238, 0.78) !important;
        color: rgba(6, 21, 39, 0.78) !important;
        -webkit-text-fill-color: rgba(6, 21, 39, 0.78) !important;
    }
    </style>
    """, unsafe_allow_html=True)

# Wrap existing theme entry points without removing old functions.
try:
    _spt_v1_40_original_apply_theme
except NameError:
    try:
        _spt_v1_40_original_apply_theme = apply_theme
        def apply_theme(*args, **kwargs):
            result = _spt_v1_40_original_apply_theme(*args, **kwargs)
            inject_dropdown_contrast_css_v1_40()
            return result
    except NameError:
        def apply_theme(*args, **kwargs):
            inject_dropdown_contrast_css_v1_40()

try:
    _spt_v1_40_original_app_theme
except NameError:
    try:
        _spt_v1_40_original_app_theme = app_theme
        def app_theme(*args, **kwargs):
            result = _spt_v1_40_original_app_theme(*args, **kwargs)
            inject_dropdown_contrast_css_v1_40()
            return result
    except NameError:
        pass
# === SPT V1.40 DROPDOWN CONTRAST FIX END ===
'''


def main() -> int:
    if not THEME.exists():
        print(f"ERROR: not found: {THEME}")
        return 1
    text = THEME.read_text(encoding="utf-8")
    if MARKER in text:
        print("OK: V1.40 dropdown contrast fix already exists.")
        return 0
    THEME.write_text(text.rstrip() + APPEND_BLOCK + "\n", encoding="utf-8")
    print("OK: V1.40 dropdown contrast CSS appended to services/theme_service.py")
    print("全模組下拉式選單：深色底 + 淺色字；輸入框：淺色底 + 深色字。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
