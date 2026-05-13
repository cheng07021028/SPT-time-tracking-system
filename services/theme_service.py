# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import base64
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATH = PROJECT_ROOT / "data" / "logo" / "super_plus_logo.png"


def _logo_base64() -> str:
    if not LOGO_PATH.exists():
        return ""
    return base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")


def apply_theme() -> None:
    st.markdown(
        """
<style>
:root {
  --spt-red:#e31b2f;
  --spt-dark:#090d16;
  --spt-card:rgba(15,23,42,.86);
  --spt-line:rgba(148,163,184,.22);
  --spt-cyan:#38bdf8;
  --spt-green:#22c55e;
  --spt-yellow:#f59e0b;
}
.stApp {
  background:
    radial-gradient(circle at 12% 10%, rgba(227,27,47,.18), transparent 28%),
    radial-gradient(circle at 90% 6%, rgba(56,189,248,.16), transparent 30%),
    linear-gradient(135deg, #06111f 0%, #0b1220 44%, #111827 100%);
  color:#e5e7eb;
}
.block-container { padding-top: 1.1rem; max-width: 1500px; }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(2,6,23,.96), rgba(15,23,42,.92));
  border-right: 1px solid rgba(56,189,248,.16);
}
.spt-hero {
  position:relative;
  display:flex; align-items:center; gap:20px;
  padding:18px 22px; border-radius:24px;
  background: linear-gradient(135deg, rgba(15,23,42,.92), rgba(30,41,59,.70));
  border:1px solid rgba(56,189,248,.24);
  box-shadow: 0 0 32px rgba(56,189,248,.14), inset 0 0 28px rgba(227,27,47,.08);
  overflow:hidden;
  margin-bottom:18px;
}
.spt-hero:before{
  content:""; position:absolute; inset:-2px;
  background: linear-gradient(90deg, transparent, rgba(56,189,248,.18), transparent);
  animation: sptScan 5s linear infinite;
}
@keyframes sptScan { 0%{transform:translateX(-95%)} 100%{transform:translateX(95%)} }
.spt-hero img { position:relative; z-index:1; max-width:260px; background:#fff; border-radius:14px; padding:7px 12px; }
.spt-title { position:relative; z-index:1; }
.spt-title h1 { margin:0; font-size:30px; letter-spacing:1px; color:#f8fafc; }
.spt-title p { margin:.3rem 0 0; color:#94a3b8; }
.spt-card, div[data-testid="stMetric"] {
  background: var(--spt-card);
  border:1px solid var(--spt-line);
  border-radius:20px;
  padding:16px 18px;
  box-shadow: 0 0 24px rgba(56,189,248,.08);
}
div[data-testid="stMetric"] { min-height: 110px; }
div[data-testid="stMetric"] label { color:#cbd5e1 !important; }
.spt-glow {
  animation: pulseGlow 2.6s ease-in-out infinite;
}
@keyframes pulseGlow {
  0%,100% { box-shadow:0 0 14px rgba(56,189,248,.12), inset 0 0 10px rgba(56,189,248,.05); }
  50% { box-shadow:0 0 34px rgba(56,189,248,.34), inset 0 0 20px rgba(227,27,47,.10); }
}
.stButton>button {
  border-radius:14px; border:1px solid rgba(56,189,248,.32);
  background:linear-gradient(135deg, rgba(14,165,233,.20), rgba(227,27,47,.18));
  color:#f8fafc; font-weight:700;
}
.stButton>button:hover { border-color:rgba(56,189,248,.85); box-shadow:0 0 16px rgba(56,189,248,.28); }
[data-testid="stDataFrame"] { border-radius:16px; overflow:hidden; }
hr { border-color: rgba(148,163,184,.2); }
</style>
""",
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str = "Super Plus Tech Manufacturing Time Tracking System") -> None:
    logo64 = _logo_base64()
    img = f'<img src="data:image/png;base64,{logo64}">' if logo64 else ""
    st.markdown(
        f"""
<div class="spt-hero spt-glow">
  {img}
  <div class="spt-title">
    <h1>{title}</h1>
    <p>{subtitle}</p>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
