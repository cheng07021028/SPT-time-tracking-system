# -*- coding: utf-8 -*-
"""Global UI font-size settings service.

V2.18
- Extends V2.17 homepage-only font scaling into a global font scale.
- The same light-bar slider + numeric input now controls all modules.
- Stores the setting in independent permanent JSON files so updates do not reset it.
- Keeps V2.17 function names as aliases to avoid breaking older imports.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

try:
    from services.timezone_service import now_text
except Exception:  # pragma: no cover - safe fallback for old projects
    from datetime import datetime

    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Keep old filenames for backward compatibility. The content now means "global UI".
CONFIG_PATH = PROJECT_ROOT / "data" / "permanent_store" / "config" / "home_ui_settings.json"
STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_home_ui_settings.json"
MODULE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "00_home" / "home_ui_settings.json"

# New clearer filenames for V2.18. Both old and new paths are read/written.
GLOBAL_CONFIG_PATH = PROJECT_ROOT / "data" / "permanent_store" / "config" / "global_ui_settings.json"
GLOBAL_STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_global_ui_settings.json"
GLOBAL_MODULE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "00_global_ui" / "global_ui_settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "global_font_scale_percent": 100,
    "home_font_scale_percent": 100,  # backward compatible alias
    "updated_at": "",
    "note": "Global font size setting. 100 = default size. Applies to all modules.",
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _coerce_scale(value: Any, default: int = 100) -> int:
    try:
        ivalue = int(round(float(value)))
    except Exception:
        ivalue = default
    return max(80, min(220, ivalue))


def _normalize_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(payload, dict):
        settings.update(payload)
    scale = settings.get("global_font_scale_percent", settings.get("home_font_scale_percent", 100))
    scale = _coerce_scale(scale)
    settings["global_font_scale_percent"] = scale
    settings["home_font_scale_percent"] = scale
    return settings


def load_global_ui_settings() -> dict[str, Any]:
    """Load global UI settings from permanent files.

    Priority: new global permanent files -> old homepage files -> defaults.
    """
    for path in (
        GLOBAL_MODULE_PATH,
        GLOBAL_STATE_PATH,
        GLOBAL_CONFIG_PATH,
        MODULE_PATH,
        STATE_PATH,
        CONFIG_PATH,
    ):
        payload = _load_json(path)
        if payload:
            return _normalize_settings(payload)
    return dict(DEFAULT_SETTINGS)


def save_global_ui_settings(scale_percent: int, username: str = "SYSTEM") -> dict[str, Any]:
    scale = _coerce_scale(scale_percent)
    settings = dict(DEFAULT_SETTINGS)
    settings["global_font_scale_percent"] = scale
    settings["home_font_scale_percent"] = scale
    settings["updated_at"] = now_text()
    settings["updated_by"] = username or "SYSTEM"
    for path in (
        GLOBAL_CONFIG_PATH,
        GLOBAL_STATE_PATH,
        GLOBAL_MODULE_PATH,
        CONFIG_PATH,
        STATE_PATH,
        MODULE_PATH,
    ):
        _save_json(path, settings)
    return settings


def inject_global_font_scale(scale_percent: int | None = None) -> None:
    """Inject global font scaling CSS for every module page.

    Called from services.theme_service.apply_theme(), so it applies to all pages
    that use the common theme. It is visual only and does not touch data logic.
    """
    if scale_percent is None:
        scale_percent = load_global_ui_settings().get("global_font_scale_percent", 100)
    scale_percent = _coerce_scale(scale_percent)
    scale = scale_percent / 100.0

    def px(base: int, min_px: int | None = None) -> int:
        v = int(round(base * scale))
        return max(min_px or 1, v)

    st.markdown(
        f"""
<style>
/* ===== V2.18 Global font scaling: {scale_percent}% ===== */
:root {{ --spt-global-font-scale: {scale}; }}
html, body, [data-testid="stAppViewContainer"], .stApp {{
    font-size: {px(16, 13)}px !important;
}}
/* Markdown and normal text */
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li, .stMarkdown, p, li, span, label {{
    font-size: {px(16, 13)}px;
}}
h1, [data-testid="stMarkdownContainer"] h1 {{ font-size: {px(36, 24)}px !important; }}
h2, [data-testid="stMarkdownContainer"] h2 {{ font-size: {px(30, 22)}px !important; }}
h3, [data-testid="stMarkdownContainer"] h3 {{ font-size: {px(24, 19)}px !important; }}
h4, [data-testid="stMarkdownContainer"] h4 {{ font-size: {px(21, 17)}px !important; }}
/* Page headers and homepage cards */
.spt-header-title {{ font-size: {px(40, 28)}px !important; }}
.spt-header-subtitle {{ font-size: {px(18, 14)}px !important; }}
.spt-header-no {{ font-size: {px(44, 30)}px !important; min-width: {px(62, 42)}px !important; }}
.spt-module-title {{ font-size: {px(31, 22)}px !important; }}
.spt-module-no {{ font-size: {px(21, 16)}px !important; }}
.spt-module-desc {{ font-size: {px(17, 13)}px !important; }}
.spt-kpi-label {{ font-size: {px(16, 13)}px !important; }}
.spt-kpi-value {{ font-size: {px(38, 26)}px !important; }}
.spt-login-label {{ font-size: {px(13, 11)}px !important; }}
.spt-login-value {{ font-size: {px(30, 21)}px !important; }}
.spt-login-value span {{ font-size: {px(22, 16)}px !important; }}
/* Sidebar */
section[data-testid="stSidebar"] *, section[data-testid="stSidebar"] a,
section[data-testid="stSidebar"] [role="link"] {{
    font-size: {px(17, 13)}px !important;
}}
/* Inputs / widgets */
.stTextInput input, .stPasswordInput input, .stNumberInput input,
.stTextArea textarea, .stDateInput input, .stTimeInput input,
div[data-baseweb="input"] input, div[data-baseweb="base-input"] input,
div[data-baseweb="textarea"] textarea, input, textarea {{
    font-size: {px(18, 14)}px !important;
}}
.stNumberInput input {{ font-size: {px(28, 18)}px !important; min-height: {px(54, 42)}px !important; }}
.stTextArea textarea {{ font-size: {px(18, 14)}px !important; }}
.stButton > button, .stDownloadButton > button,
div[data-testid="stFormSubmitButton"] button, button[kind="secondary"], button[kind="primary"] {{
    font-size: {px(16, 13)}px !important;
}}
div[data-baseweb="select"] span, div[data-baseweb="select"] input,
div[data-baseweb="select"] div, div[data-baseweb="popover"] [role="option"],
div[data-baseweb="popover"] [role="option"] * {{
    font-size: {px(16, 13)}px !important;
}}
/* Tabs / expanders */
button[data-baseweb="tab"], button[data-baseweb="tab"] *,
div[data-testid="stExpander"] summary, div[data-testid="stExpander"] summary * {{
    font-size: {px(16, 13)}px !important;
}}
/* Dataframe and data editor text */
[data-testid="stDataFrame"], [data-testid="stDataFrame"] *,
[data-testid="stDataEditor"], [data-testid="stDataEditor"] *,
[data-testid="stTable"], [data-testid="stTable"] * {{
    font-size: {px(15, 12)}px !important;
}}
[data-testid="stDataEditor"] input, [data-testid="stDataEditor"] textarea,
[data-testid="stDataEditor"] select, [data-testid="stDataEditor"] [contenteditable="true"] {{
    font-size: {px(15, 12)}px !important;
}}
/* Metric widgets */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{ font-size: {px(15, 12)}px !important; }}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{ font-size: {px(32, 22)}px !important; }}
/* Global font toolbar */
.spt-global-font-toolbar {{
    border: 1px solid rgba(98, 244, 255, .58);
    border-radius: 18px;
    padding: 16px 18px;
    margin: 4px 0 16px 0;
    background: linear-gradient(110deg, rgba(4,22,38,.82), rgba(5,78,112,.48), rgba(42,25,98,.44));
    box-shadow: 0 0 0 1px rgba(35,230,255,.14) inset, 0 0 22px rgba(35,230,255,.20), 0 0 44px rgba(112,61,255,.12);
    animation: sptGlobalControlBreath 2.8s ease-in-out infinite;
}}
.spt-global-font-toolbar-title {{
    color: #ffffff;
    font-size: {px(20, 16)}px !important;
    font-weight: 1000;
    letter-spacing: .5px;
    text-shadow: 0 0 10px rgba(255,255,255,.22), 0 0 22px rgba(35,230,255,.36);
}}
.spt-global-font-toolbar-subtitle {{
    color: rgba(224, 248, 255, .82);
    font-size: {px(15, 12)}px !important;
    font-weight: 850;
    margin-top: 2px;
}}
@keyframes sptGlobalControlBreath {{
    0%,100% {{ box-shadow: 0 0 0 1px rgba(35,230,255,.12) inset, 0 0 14px rgba(35,230,255,.16), 0 0 26px rgba(112,61,255,.10); }}
    50% {{ box-shadow: 0 0 0 1px rgba(35,230,255,.34) inset, 0 0 28px rgba(35,230,255,.44), 0 0 58px rgba(112,61,255,.28); }}
}}
/* Tech light-bar slider */
.stSlider [data-baseweb="slider"] > div {{
    background: linear-gradient(90deg, rgba(35,230,255,.35), rgba(110,65,255,.42)) !important;
    box-shadow: 0 0 18px rgba(35,230,255,.28) !important;
}}
.stSlider [data-baseweb="slider"] div[role="slider"] {{
    background: #f5fbff !important;
    border: 2px solid #67f5ff !important;
    box-shadow: 0 0 16px rgba(35,230,255,.75), 0 0 34px rgba(112,61,255,.30) !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_global_font_controls(username: str = "SYSTEM") -> None:
    """Render global font-size control on the homepage."""
    settings = load_global_ui_settings()
    current = _coerce_scale(settings.get("global_font_scale_percent", 100))

    st.markdown(
        """
<div class="spt-global-font-toolbar">
  <div class="spt-global-font-toolbar-title">全系統字體放大控制 / Global Font Scale</div>
  <div class="spt-global-font-toolbar-subtitle">使用科技光棒滑桿或右側數字輸入調整；按下套用後永久記錄，套用到所有模組頁面。</div>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.form("global_font_scale_form", clear_on_submit=False):
        c1, c2, c3 = st.columns([4.2, 1.3, 1.2])
        with c1:
            slider_value = st.slider(
                "科技光棒字體倍率 / Light-Bar Scale",
                min_value=80,
                max_value=220,
                value=current,
                step=5,
                help="100 為原始大小；數值越大，所有模組的標題、表格、按鈕、輸入框與說明文字越大。",
            )
        with c2:
            number_value = st.number_input(
                "數字輸入 / %",
                min_value=80,
                max_value=220,
                value=current,
                step=1,
                help="可直接輸入精準百分比。若與滑桿不同，以此數字為準。",
            )
        with c3:
            st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("套用到所有模組並永久記錄")

    b1, b2, _ = st.columns([1.3, 1.3, 5])
    with b1:
        reset = st.button("恢復預設 100%", key="global_font_reset_100")
    with b2:
        rebuild = st.button("重建永久設定檔", key="global_font_rebuild_json")

    if submitted:
        final_value = _coerce_scale(number_value if number_value != current else slider_value)
        save_global_ui_settings(final_value, username=username)
        st.success(f"全系統字體倍率已永久記錄：{final_value}%")
        st.rerun()

    if reset:
        save_global_ui_settings(100, username=username)
        st.success("全系統字體倍率已恢復預設 100%。")
        st.rerun()

    if rebuild:
        save_global_ui_settings(current, username=username)
        st.success("全系統字體永久設定檔已重建。")
        st.rerun()


# ===== Backward-compatible V2.17 aliases =====
def load_home_ui_settings() -> dict[str, Any]:
    return load_global_ui_settings()


def save_home_ui_settings(scale_percent: int, username: str = "SYSTEM") -> dict[str, Any]:
    return save_global_ui_settings(scale_percent, username=username)


def inject_home_font_scale(scale_percent: int | None = None) -> None:
    inject_global_font_scale(scale_percent)


def render_home_font_controls(username: str = "SYSTEM") -> None:
    render_global_font_controls(username=username)
