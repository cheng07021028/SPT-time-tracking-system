# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "services" / "theme_service.py"

CSS_MARK = "/* SPT V1.42 DROPDOWN FONT CONSISTENCY */"
WRAP_MARK = "# SPT V1.42 audit auto-record wrapper"

CSS = r'''
/* SPT V1.42 DROPDOWN FONT CONSISTENCY */
<style>
/* 統一標題字體大小，避免同頁不同大小 */
.spt-title, .spt-header-title, h1, h2, h3 {
    letter-spacing: 0.5px !important;
}

/* BaseWeb 下拉選單：深色底、淺色字，選中才用亮色底深色字 */
div[data-baseweb="select"] div,
div[data-baseweb="select"] span,
div[data-baseweb="select"] input {
    color: #eaf7ff !important;
    font-weight: 700 !important;
}

ul[role="listbox"],
div[role="listbox"] {
    background: #071524 !important;
    border: 1px solid rgba(0, 220, 255, 0.55) !important;
    box-shadow: 0 14px 36px rgba(0, 0, 0, 0.42), 0 0 22px rgba(0, 220, 255, 0.15) !important;
}

ul[role="listbox"] li,
div[role="option"],
div[data-baseweb="menu"] div,
div[data-baseweb="popover"] div[role="option"] {
    background: #071524 !important;
    color: #eaf7ff !important;
    font-weight: 700 !important;
    font-size: 15px !important;
}

ul[role="listbox"] li:hover,
div[role="option"]:hover,
div[data-baseweb="menu"] div:hover {
    background: rgba(0, 220, 255, 0.18) !important;
    color: #ffffff !important;
}

ul[role="listbox"] li[aria-selected="true"],
div[role="option"][aria-selected="true"] {
    background: #28e7ff !important;
    color: #06131f !important;
    font-weight: 900 !important;
}

/* data_editor 內的下拉 */
[data-testid="stDataEditor"] div[role="listbox"],
[data-testid="stDataEditor"] div[role="option"] {
    background: #071524 !important;
    color: #eaf7ff !important;
}
[data-testid="stDataEditor"] div[role="option"][aria-selected="true"] {
    background: #28e7ff !important;
    color: #06131f !important;
}

/* 淺色輸入格文字固定深色 */
input, textarea, [contenteditable="true"] {
    color: #071524 !important;
}
</style>
'''

WRAP = r'''

# SPT V1.42 audit auto-record wrapper
try:
    _spt_v142_old_apply_theme = apply_theme
    def apply_theme(*args, **kwargs):
        try:
            from services.audit_log_service import auto_record_current_session_login_once
            auto_record_current_session_login_once()
        except Exception:
            pass
        result = _spt_v142_old_apply_theme(*args, **kwargs)
        try:
            import streamlit as st
            st.markdown("""''' + CSS.replace('"""', '\"\"\"') + r'''""", unsafe_allow_html=True)
        except Exception:
            pass
        return result
except Exception:
    pass

try:
    _spt_v142_old_render_header = render_header
    def render_header(*args, **kwargs):
        try:
            from services.audit_log_service import auto_record_current_session_login_once
            auto_record_current_session_login_once()
        except Exception:
            pass
        return _spt_v142_old_render_header(*args, **kwargs)
except Exception:
    pass
'''

def backup(path: Path) -> None:
    if path.exists():
        bak = path.with_suffix(path.suffix + ".v142.bak")
        if not bak.exists():
            bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def patch_theme():
    if not THEME.exists():
        print(f"WARN: theme_service.py not found: {THEME}")
        return
    backup(THEME)
    text = THEME.read_text(encoding="utf-8")
    if WRAP_MARK not in text:
        text += WRAP
    THEME.write_text(text, encoding="utf-8")
    print("OK: theme_service.py patched with V1.42 audit wrapper and dropdown CSS")

if __name__ == "__main__":
    patch_theme()
    print("V1.42 apply completed.")
