# -*- coding: utf-8 -*-
"""Home UI font-size settings service.

V2.17
- Adds a homepage font scaling control with a tech-style slider + numeric input.
- Stores the setting in independent permanent JSON files so updates do not reset it.
- Kept isolated from other modules to avoid breaking table/editing logic.
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

CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "home_ui_settings.json"
STATE_PATH = PROJECT_ROOT / "data" / "persistent_state" / "spt_home_ui_settings.json"
MODULE_PATH = PROJECT_ROOT / "data" / "persistent_modules" / "00_home" / "home_ui_settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "home_font_scale_percent": 100,
    "updated_at": "",
    "note": "Homepage font size setting. 100 = default size.",
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


def load_home_ui_settings() -> dict[str, Any]:
    """Load homepage UI settings from permanent files.

    Priority: module permanent file -> persistent state -> config -> defaults.
    """
    for path in (MODULE_PATH, STATE_PATH, CONFIG_PATH):
        payload = _load_json(path)
        if payload:
            settings = dict(DEFAULT_SETTINGS)
            settings.update(payload)
            settings["home_font_scale_percent"] = _coerce_scale(settings.get("home_font_scale_percent"))
            return settings
    return dict(DEFAULT_SETTINGS)


def save_home_ui_settings(scale_percent: int, username: str = "SYSTEM") -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings["home_font_scale_percent"] = _coerce_scale(scale_percent)
    settings["updated_at"] = now_text()
    settings["updated_by"] = username or "SYSTEM"
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        _save_json(path, settings)
    return settings


def inject_home_font_scale(scale_percent: int | None = None) -> None:
    """Inject homepage-only font scaling CSS.

    This is called only from streamlit_app.py, so it does not alter other pages.
    """
    if scale_percent is None:
        scale_percent = load_home_ui_settings().get("home_font_scale_percent", 100)
    scale = _coerce_scale(scale_percent) / 100.0
    st.markdown(
        f"""
<style>
/* ===== V2.17 Homepage font scaling ===== */
.spt-home-font-toolbar {{
    border: 1px solid rgba(98, 244, 255, .58);
    border-radius: 18px;
    padding: 16px 18px;
    margin: 4px 0 16px 0;
    background: linear-gradient(110deg, rgba(4,22,38,.82), rgba(5,78,112,.48), rgba(42,25,98,.44));
    box-shadow: 0 0 0 1px rgba(35,230,255,.14) inset, 0 0 22px rgba(35,230,255,.20), 0 0 44px rgba(112,61,255,.12);
    animation: sptHomeControlBreath 2.8s ease-in-out infinite;
}}
.spt-home-font-toolbar-title {{
    color: #ffffff;
    font-size: {max(18, int(20 * scale))}px;
    font-weight: 1000;
    letter-spacing: .5px;
    text-shadow: 0 0 10px rgba(255,255,255,.22), 0 0 22px rgba(35,230,255,.36);
}}
.spt-home-font-toolbar-subtitle {{
    color: rgba(224, 248, 255, .82);
    font-size: {max(14, int(15 * scale))}px;
    font-weight: 850;
    margin-top: 2px;
}}
@keyframes sptHomeControlBreath {{
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
/* Homepage typography scaled after normal theme CSS. */
.spt-header-title {{ font-size: {int(40 * scale)}px !important; }}
.spt-header-subtitle {{ font-size: {int(18 * scale)}px !important; }}
.spt-header-no {{ font-size: {int(44 * scale)}px !important; min-width: {int(62 * scale)}px !important; }}
.spt-module-title {{ font-size: {int(31 * scale)}px !important; }}
.spt-module-no {{ font-size: {int(21 * scale)}px !important; }}
.spt-module-desc {{ font-size: {int(17 * scale)}px !important; }}
.spt-kpi-label {{ font-size: {int(16 * scale)}px !important; }}
.spt-kpi-value {{ font-size: {int(38 * scale)}px !important; }}
</style>
""",
        unsafe_allow_html=True,
    )


def render_home_font_controls(username: str = "SYSTEM") -> None:
    """Render the homepage font-size control.

    Uses st.form so dragging the slider or typing the number does not repeatedly
    trigger expensive page operations. Only Apply writes permanent files.
    """
    settings = load_home_ui_settings()
    current = _coerce_scale(settings.get("home_font_scale_percent", 100))

    st.markdown(
        """
<div class="spt-home-font-toolbar">
  <div class="spt-home-font-toolbar-title">首頁字體放大控制 / Home Font Scale</div>
  <div class="spt-home-font-toolbar-subtitle">使用科技光棒滑桿或右側數字輸入調整；按下套用後永久記錄。</div>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.form("home_font_scale_form", clear_on_submit=False):
        c1, c2, c3 = st.columns([4.2, 1.3, 1.2])
        with c1:
            slider_value = st.slider(
                "科技光棒字體倍率 / Light-Bar Scale",
                min_value=80,
                max_value=220,
                value=current,
                step=5,
                help="100 為原始大小；數值越大，首頁標題、模組卡片與 KPI 字體越大。",
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
            submitted = st.form_submit_button("套用並永久記錄")

    b1, b2, _ = st.columns([1.3, 1.3, 5])
    with b1:
        reset = st.button("恢復預設 100%", key="home_font_reset_100")
    with b2:
        rebuild = st.button("重建永久設定檔", key="home_font_rebuild_json")

    if submitted:
        final_value = _coerce_scale(number_value if number_value != current else slider_value)
        save_home_ui_settings(final_value, username=username)
        st.success(f"首頁字體倍率已永久記錄：{final_value}%")
        st.rerun()

    if reset:
        save_home_ui_settings(100, username=username)
        st.success("首頁字體倍率已恢復預設 100%。")
        st.rerun()

    if rebuild:
        save_home_ui_settings(current, username=username)
        st.success("首頁字體永久設定檔已重建。")
        st.rerun()
