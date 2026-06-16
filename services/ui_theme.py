from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st

from .config import ASSETS_DIR


def _asset_data_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    suffix = path.suffix.lower()
    mime = "image/svg+xml" if suffix == ".svg" else "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def apply_tech_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --spt-bg: #050A14;
            --spt-panel: rgba(10, 25, 45, 0.82);
            --spt-panel-2: rgba(7, 17, 31, 0.92);
            --spt-cyan: #00D4FF;
            --spt-violet: #8A5CFF;
            --spt-green: #39FF88;
            --spt-red: #FF4B6E;
            --spt-orange: #FFB547;
            --spt-text: #E8F6FF;
            --spt-muted: #9FB6C8;
        }
        @keyframes sptBreathingGlow {
            0% { box-shadow: 0 0 14px rgba(0,212,255,.12), inset 0 0 12px rgba(138,92,255,.05); border-color: rgba(0,212,255,.22); }
            50% { box-shadow: 0 0 34px rgba(0,212,255,.34), 0 0 54px rgba(138,92,255,.14), inset 0 0 18px rgba(0,212,255,.10); border-color: rgba(0,212,255,.58); }
            100% { box-shadow: 0 0 14px rgba(0,212,255,.12), inset 0 0 12px rgba(138,92,255,.05); border-color: rgba(0,212,255,.22); }
        }
        @keyframes sptPulseDot {
            0%, 100% { transform: scale(1); opacity: .65; }
            50% { transform: scale(1.22); opacity: 1; }
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(0, 212, 255, 0.16) 0%, transparent 28%),
                radial-gradient(circle at top right, rgba(138, 92, 255, 0.16) 0%, transparent 30%),
                linear-gradient(135deg, #050A14 0%, #07111F 52%, #02040A 100%);
            color: var(--spt-text);
        }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #06111F 0%, #030812 100%);
            border-right: 1px solid rgba(0, 212, 255, 0.25);
        }
        section[data-testid="stSidebar"] * { letter-spacing: .01em; }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] { padding-top: 1.1rem; }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul { gap: .18rem; }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a span,
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] div[role="button"] span {
            font-size: 1.03rem !important;
            line-height: 1.42 !important;
            font-weight: 760 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
            padding: .56rem .62rem !important;
            border-radius: 10px !important;
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
            background: rgba(0, 212, 255, 0.11) !important;
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] [aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
            background: rgba(0, 212, 255, 0.18) !important;
            color: #FFFFFF !important;
            box-shadow: inset 3px 0 0 rgba(0, 212, 255, 0.85);
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"]::before {
            content: "SPT Capacity System";
            display: block;
            margin: 0 0 .85rem .25rem;
            color: #8FDFFF;
            font-size: 1.02rem;
            font-weight: 850;
            letter-spacing: .04em;
        }
        div[data-testid="stMetric"] {
            background: var(--spt-panel);
            border: 1px solid rgba(0, 212, 255, 0.24);
            border-radius: 18px;
            padding: 16px 18px;
            box-shadow: 0 0 24px rgba(0, 212, 255, 0.10);
            animation: sptBreathingGlow 4.8s ease-in-out infinite;
        }
        div[data-testid="stMetric"] label {
            color: #8FDFFF !important;
            letter-spacing: .04em;
        }
        .block-container { padding-top: 3.8rem !important; padding-bottom: 3rem; max-width: 1560px; }
        h1, h2, h3 { letter-spacing: .02em; }
        .tech-hero {
            display: flex;
            align-items: center;
            gap: 18px;
            padding: 24px 26px;
            border: 1px solid rgba(0, 212, 255, 0.28);
            border-radius: 24px;
            background: linear-gradient(135deg, rgba(0, 212, 255, 0.10), rgba(138, 92, 255, 0.10));
            box-shadow: 0 0 36px rgba(0, 212, 255, 0.10);
            margin: 0 0 22px 0;
            position: relative;
            overflow: hidden;
        }
        .tech-hero::after {
            content: "";
            position: absolute;
            right: -60px;
            top: -80px;
            width: 220px;
            height: 220px;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(0,212,255,.18), transparent 62%);
            pointer-events: none;
        }
        .tech-hero.breathing-glow, .breathing-glow { animation: sptBreathingGlow 5.2s ease-in-out infinite; }
        .tech-logo { width: 220px; min-width: 220px; max-height: 86px; object-fit: contain; filter: drop-shadow(0 0 12px rgba(0,212,255,.28)); }
        .tech-title { font-size: 2.12rem; font-weight: 850; color: #FFFFFF; margin: 0; line-height: 1.15; }
        .tech-subtitle { color: var(--spt-muted); margin-top: 8px; }
        .tech-card, .human-card {
            background: var(--spt-panel);
            border: 1px solid rgba(0, 212, 255, 0.24);
            border-radius: 18px;
            padding: 16px 18px;
            box-shadow: 0 0 24px rgba(0, 212, 255, 0.08);
            margin: 8px 0 18px 0;
        }
        .human-card { background: rgba(10,25,45,.62); }
        .status-pill {
            display: inline-block;
            padding: 5px 12px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.85rem;
            border: 1px solid rgba(255,255,255,0.20);
        }
        .pill-green { color: #021207; background: rgba(57,255,136,0.92); }
        .pill-yellow { color: #171006; background: rgba(255,220,92,0.92); }
        .pill-orange { color: #1A0E00; background: rgba(255,181,71,0.92); }
        .pill-red { color: #FFFFFF; background: rgba(255,75,110,0.92); }
        .small-muted { color: var(--spt-muted); font-size: 0.9rem; }
        .spt-divider { height: 1px; background: linear-gradient(90deg, transparent, rgba(0,212,255,.45), transparent); margin: 1rem 0; }
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
            border: 1px solid rgba(0, 212, 255, 0.18);
            border-radius: 14px;
            overflow: hidden;
        }
        button[kind="primary"] { border: 1px solid rgba(0, 212, 255, 0.4); }
        .org-chart-wrap { display: flex; flex-direction: column; gap: 18px; }
        .org-dept-card { border: 1px solid rgba(0,212,255,.34); border-radius: 22px; padding: 16px; background: rgba(6,17,31,.78); }
        .org-dept-title { font-size: 1.35rem; font-weight: 850; color: #FFFFFF; margin-bottom: 14px; display:flex; justify-content:space-between; gap: 12px; }
        .org-dept-title span { color: #8FDFFF; font-size: .92rem; font-weight: 700; }
        .org-group-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
        .org-group-card { border: 1px solid rgba(138,92,255,.28); border-radius: 18px; padding: 12px; background: rgba(10,25,45,.72); }
        .org-group-title { color: #00D4FF; font-weight: 800; margin-bottom: 10px; display:flex; justify-content:space-between; gap:8px; }
        .org-group-title span { color: #9FB6C8; font-size: .82rem; }
        .org-person-card { border-left: 3px solid rgba(0,212,255,.75); background: rgba(255,255,255,.045); border-radius: 12px; padding: 9px 10px; margin: 7px 0; }
        .org-person-card.indirect { border-left-color: rgba(255,181,71,.82); opacity: .88; }
        .org-person-name { color:#FFFFFF; font-weight: 800; font-size: .98rem; }
        .org-person-meta { color:#9FB6C8; font-size: .78rem; margin-top: 2px; }
        .quick-help { border-left: 4px solid #00D4FF; }
        .pulse-dot { display:inline-block; width:10px; height:10px; border-radius:50%; background:#00D4FF; box-shadow:0 0 16px rgba(0,212,255,.75); animation:sptPulseDot 2.2s infinite; margin-right:8px; }
        [data-testid="stPlotlyChart"] {
            border: 1px solid rgba(17,141,255,.26);
            border-radius: 20px;
            background: linear-gradient(145deg, rgba(15,23,42,.92), rgba(17,24,39,.84));
            box-shadow: 0 0 28px rgba(17,141,255,.13), inset 0 0 16px rgba(255,255,255,.03);
            padding: 10px;
            margin: 8px 0 18px 0;
            overflow: hidden;
        }
        [data-testid="stPlotlyChart"] .js-plotly-plot, [data-testid="stPlotlyChart"] .plotly {
            border-radius: 16px;
        }

        .spt-status-board {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
            gap: 12px;
            margin: 14px 0 22px 0;
        }
        .spt-status-card {
            border: 1px solid rgba(17,141,255,.26);
            border-radius: 18px;
            padding: 12px 12px 11px 12px;
            background: linear-gradient(145deg, rgba(15,23,42,.96), rgba(2,8,23,.88));
            box-shadow: 0 0 20px rgba(17,141,255,.10), inset 0 0 12px rgba(255,255,255,.025);
        }
        .spt-status-month { color:#FFFFFF; font-weight:900; font-size:.98rem; display:flex; align-items:center; justify-content:space-between; }
        .spt-status-meta { color:var(--spt-muted); font-size:.76rem; margin-top:6px; line-height:1.35; }
        .spt-lamp {
            width: 21px; height: 21px; border-radius: 999px; display:inline-block;
            box-shadow: 0 0 18px currentColor, inset 0 0 7px rgba(255,255,255,.60);
            border:1px solid rgba(255,255,255,.35);
            animation: sptPulseDot 2.35s ease-in-out infinite;
        }
        .spt-lamp-green { color:#39FF88; background: radial-gradient(circle at 35% 30%, #FFFFFF, #39FF88 34%, #087C39 76%); }
        .spt-lamp-yellow { color:#FFE66D; background: radial-gradient(circle at 35% 30%, #FFFFFF, #FFE66D 34%, #B07A00 76%); }
        .spt-lamp-orange { color:#FFB547; background: radial-gradient(circle at 35% 30%, #FFFFFF, #FFB547 34%, #B04A00 76%); }
        .spt-lamp-red { color:#FF4B6E; background: radial-gradient(circle at 35% 30%, #FFFFFF, #FF4B6E 34%, #9E102F 76%); }
        .module-export-card {
            border: 1px solid rgba(17,141,255,.32);
            border-radius: 18px;
            padding: 14px 16px;
            margin: 18px 0;
            background: linear-gradient(135deg, rgba(17,141,255,.10), rgba(116,78,194,.10));
            box-shadow: 0 0 22px rgba(17,141,255,.10);
        }

        /* V2.1 usability and logo polish overrides */
        .sidebar-module-list {
            display:flex;
            flex-direction:column;
            gap:8px;
            margin: 8px 0 12px 0;
            font-size: 1.02rem;
            line-height: 1.32;
            font-weight: 850;
            color:#FFFFFF;
        }
        .sidebar-module-list div {
            padding: 2px 0;
            text-shadow: 0 0 8px rgba(0,212,255,.14);
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span {
            color: #F4FBFF !important;
        }
        section[data-testid="stSidebar"] .stSelectbox label,
        section[data-testid="stSidebar"] .stForm label {
            font-size: 1.02rem !important;
            font-weight: 850 !important;
            color: #FFFFFF !important;
        }
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
            min-height: 46px !important;
            border-radius: 14px !important;
            border: 1px solid rgba(0,212,255,.34) !important;
            background: linear-gradient(135deg, rgba(10,36,64,.96), rgba(12,22,42,.96)) !important;
            box-shadow: 0 0 18px rgba(0,212,255,.13), inset 0 0 12px rgba(255,255,255,.025);
        }
        .spt-sidebar-apply-card {
            border: 1px solid rgba(0,212,255,.30);
            border-radius: 18px;
            padding: 12px 12px 14px 12px;
            margin: 12px 0 16px 0;
            background: linear-gradient(145deg, rgba(17,141,255,.14), rgba(116,78,194,.10));
            box-shadow: 0 0 24px rgba(17,141,255,.13), inset 0 0 14px rgba(255,255,255,.025);
        }
        .spt-current-month {
            display:inline-flex;
            align-items:center;
            gap:8px;
            padding: 8px 12px;
            border-radius: 999px;
            margin: 4px 0 8px 0;
            color: #FFFFFF;
            font-weight: 900;
            background: rgba(0,212,255,.12);
            border: 1px solid rgba(0,212,255,.34);
            box-shadow: 0 0 14px rgba(0,212,255,.14);
        }
        .tech-hero {
            align-items: stretch;
            min-height: 118px;
            padding: 22px 28px 22px 26px;
            margin-top: 4px;
            background:
                radial-gradient(circle at 9% 30%, rgba(255,255,255,.10), transparent 24%),
                radial-gradient(circle at 87% 28%, rgba(116,78,194,.25), transparent 32%),
                linear-gradient(135deg, rgba(8,21,40,.96), rgba(17,24,56,.93) 55%, rgba(14,9,42,.86));
        }
        .tech-logo-shell {
            position: relative;
            display:flex;
            align-items:center;
            justify-content:center;
            width: 284px;
            min-width: 284px;
            max-width: 284px;
            min-height: 92px;
            padding: 10px 16px;
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(255,255,255,.98), rgba(238,247,255,.94));
            border: 1px solid rgba(255,255,255,.70);
            box-shadow:
                0 0 0 1px rgba(0,212,255,.20),
                0 0 24px rgba(0,212,255,.24),
                0 8px 28px rgba(0,0,0,.32),
                inset 0 0 16px rgba(0,212,255,.08);
            overflow: hidden;
        }
        .tech-logo-shell::before {
            content:"";
            position:absolute;
            inset:-70% -45%;
            background: linear-gradient(120deg, transparent 40%, rgba(0,212,255,.25) 50%, transparent 60%);
            transform: rotate(12deg);
            animation: sptLogoShine 6.4s ease-in-out infinite;
            pointer-events:none;
        }
        @keyframes sptLogoShine {
            0%, 72%, 100% { transform: translateX(-55%) rotate(12deg); opacity:.0; }
            82% { opacity:.95; }
            92% { transform: translateX(55%) rotate(12deg); opacity:.0; }
        }
        .tech-logo { width: 250px; min-width: 250px; max-height: 78px; object-fit: contain; filter: drop-shadow(0 0 2px rgba(0,0,0,.12)); position:relative; z-index:1; }
        .tech-title { font-size: clamp(1.85rem, 2.55vw, 2.72rem); text-shadow: 0 0 16px rgba(0,212,255,.28), 0 2px 0 rgba(0,0,0,.42); }
        .tech-subtitle { font-size: 1.02rem; color: #C8D7EA; }
        .org-scroll-wrap {
            max-height: 720px;
            overflow: auto;
            padding: 10px 10px 16px 10px;
            border: 1px solid rgba(0,212,255,.28);
            border-radius: 22px;
            background: linear-gradient(145deg, rgba(2,6,23,.88), rgba(8,13,27,.82));
            box-shadow: 0 0 30px rgba(17,141,255,.14), inset 0 0 18px rgba(255,255,255,.025);
        }
        .org-scroll-wrap::-webkit-scrollbar { height: 12px; width: 12px; }
        .org-scroll-wrap::-webkit-scrollbar-thumb { background: rgba(0,212,255,.35); border-radius: 999px; }
        .org-scroll-wrap::-webkit-scrollbar-track { background: rgba(255,255,255,.04); border-radius: 999px; }
        .chart-label-control {
            display:inline-block;
            padding: 6px 10px;
            border: 1px solid rgba(0,212,255,.28);
            border-radius: 999px;
            background: rgba(2,6,23,.60);
            box-shadow: 0 0 14px rgba(0,212,255,.10);
            margin: 2px 0 4px 0;
        }
        .chart-label-control label,
        .chart-label-control span { color:#FFFFFF !important; font-weight:800 !important; }
        .spt-status-card {
            background:
                radial-gradient(circle at 82% 16%, rgba(0,212,255,.18), transparent 26%),
                linear-gradient(145deg, rgba(15,23,42,.98), rgba(2,8,23,.90));
            transform: translateZ(0);
        }
        .spt-status-card:hover { border-color: rgba(0,212,255,.58); box-shadow: 0 0 26px rgba(0,212,255,.22), inset 0 0 14px rgba(255,255,255,.03); }
        .permission-panel {
            border: 1px solid rgba(0,212,255,.30);
            border-radius: 20px;
            padding: 16px;
            background: linear-gradient(145deg, rgba(10,25,45,.82), rgba(2,6,23,.78));
            box-shadow: 0 0 24px rgba(17,141,255,.12), inset 0 0 14px rgba(255,255,255,.025);
            margin: 10px 0 18px 0;
        }


        /* V2.2 manufacturing war-room visual language inspired by the uploaded reference image */
        .wr-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin: 12px 0 18px 0;
        }
        .wr-kpi-card {
            position: relative;
            min-height: 118px;
            padding: 16px 16px 14px 15px;
            border-radius: 18px;
            border: 1px solid rgba(56,189,248,.26);
            background:
                radial-gradient(circle at 17% 20%, rgba(56,189,248,.18), transparent 28%),
                radial-gradient(circle at 86% 20%, rgba(116,78,194,.15), transparent 28%),
                linear-gradient(145deg, rgba(15,23,42,.94), rgba(2,8,23,.90));
            box-shadow: 0 0 25px rgba(17,141,255,.12), inset 0 0 16px rgba(255,255,255,.025);
            overflow: hidden;
        }
        .wr-kpi-card::after {
            content:"";
            position:absolute;
            left:0; right:0; bottom:0;
            height: 3px;
            background: linear-gradient(90deg, rgba(56,189,248,.0), rgba(56,189,248,.9), rgba(116,78,194,.7), rgba(56,189,248,.0));
            opacity:.72;
        }
        .wr-kpi-top { display:flex; align-items:center; gap: 12px; min-width:0; }
        .wr-icon-wrap {
            width: 48px; height: 48px;
            min-width: 48px;
            border-radius: 16px;
            display:flex; align-items:center; justify-content:center;
            color:#AEEAFF;
            background: radial-gradient(circle at 35% 25%, rgba(255,255,255,.24), rgba(17,141,255,.22) 38%, rgba(2,8,23,.36) 100%);
            border: 1px solid rgba(125,211,252,.24);
            box-shadow: 0 0 22px rgba(17,141,255,.18), inset 0 0 12px rgba(255,255,255,.045);
        }
        .wr-icon-wrap svg { width: 28px; height: 28px; filter: drop-shadow(0 0 7px rgba(56,189,248,.55)); }
        .wr-kpi-title { color:#DFF7FF; font-size:.92rem; font-weight:900; letter-spacing:.04em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .wr-kpi-sub { color:#91A9C8; font-size:.77rem; margin-top:2px; }
        .wr-kpi-value { margin-top: 11px; display:flex; align-items:baseline; gap:7px; color:#FFFFFF; font-size: 2.05rem; font-weight: 950; line-height:1; text-shadow:0 0 16px rgba(56,189,248,.23); }
        .wr-kpi-unit { color:#AEEAFF; font-size:.95rem; font-weight:850; }
        .wr-kpi-delta { margin-top: 8px; color:#C8D7EA; font-size:.82rem; display:flex; align-items:center; gap:6px; }
        .wr-kpi-delta::before { content:""; width:8px; height:8px; border-radius:99px; background:#39FF88; box-shadow:0 0 12px #39FF88; display:inline-block; }
        .wr-kpi-delta.warn::before { background:#FFB547; box-shadow:0 0 12px #FFB547; }
        .wr-kpi-delta.danger::before { background:#FF4B6E; box-shadow:0 0 12px #FF4B6E; }
        .wr-kpi-card.green .wr-icon-wrap { background: radial-gradient(circle at 35% 25%, rgba(255,255,255,.24), rgba(57,255,136,.20) 38%, rgba(2,8,23,.36) 100%); }
        .wr-kpi-card.orange .wr-icon-wrap { background: radial-gradient(circle at 35% 25%, rgba(255,255,255,.24), rgba(255,181,71,.22) 38%, rgba(2,8,23,.36) 100%); }
        .wr-kpi-card.red .wr-icon-wrap { background: radial-gradient(circle at 35% 25%, rgba(255,255,255,.24), rgba(255,75,110,.24) 38%, rgba(2,8,23,.36) 100%); }
        .spt-status-board {
            grid-template-columns: repeat(6, minmax(0, 1fr)) !important;
            gap: 16px !important;
        }
        .spt-status-card {
            min-height: 154px;
            padding: 16px 16px 15px 16px !important;
            border-radius: 22px !important;
        }
        .spt-status-month { font-size: 1.28rem !important; }
        .spt-status-meta { font-size: .94rem !important; line-height: 1.56 !important; }
        .spt-lamp {
            width: 38px !important;
            height: 38px !important;
            box-shadow: 0 0 28px currentColor, inset 0 0 11px rgba(255,255,255,.70) !important;
        }
        .spt-lamp-label {
            display:inline-flex; align-items:center; gap:10px;
            font-size:.92rem; font-weight:900; color:#FFFFFF;
        }
        @media (max-width: 1400px) {
            .wr-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .spt-status-board { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 760px) {
            .wr-kpi-grid { grid-template-columns: 1fr; }
            .spt-status-board { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        }

        /* V2.3 operation polish */
        .people-total-card {
            display:flex; align-items:center; gap:18px; justify-content:space-between;
            margin: 12px 0 20px 0;
            padding: 18px 22px;
            border-radius: 22px;
            border: 1px solid rgba(0,212,255,.34);
            background:
                radial-gradient(circle at 12% 22%, rgba(0,212,255,.20), transparent 30%),
                linear-gradient(145deg, rgba(15,23,42,.92), rgba(2,8,23,.92));
            box-shadow: 0 0 28px rgba(17,141,255,.14), inset 0 0 18px rgba(255,255,255,.025);
        }
        .people-total-label { color:#AEEAFF; font-size:1.08rem; font-weight:900; letter-spacing:.04em; }
        .people-total-value { color:#FFFFFF; font-size:2.6rem; font-weight:950; line-height:1; text-shadow:0 0 18px rgba(56,189,248,.32); }
        .people-total-value span { color:#AEEAFF; font-size:1.05rem; margin-left:8px; }
        .people-total-note { color:#91A9C8; font-size:.88rem; }
        .manpower-gap-grid { display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:16px; margin: 14px 0 22px 0; }
        .manpower-gap-card { border-radius:20px; padding:18px; border:1px solid rgba(56,189,248,.28); background:linear-gradient(145deg, rgba(15,23,42,.94), rgba(2,8,23,.90)); box-shadow:0 0 24px rgba(17,141,255,.12); }
        .manpower-gap-card.good { border-color:rgba(57,255,136,.38); }
        .manpower-gap-card.bad { border-color:rgba(255,75,110,.42); }
        .manpower-gap-label { color:#AEEAFF; font-weight:900; font-size:.94rem; }
        .manpower-gap-value { color:#FFFFFF; font-size:2.15rem; font-weight:950; margin-top:8px; }
        .manpower-gap-sub { color:#91A9C8; font-size:.84rem; margin-top:6px; }
        .org-scroll-wrap { max-height: 780px; overflow:auto; padding-right:8px; }
        .org-scroll-wrap::-webkit-scrollbar { height:12px; width:12px; }
        .org-scroll-wrap::-webkit-scrollbar-thumb { background:rgba(0,212,255,.34); border-radius:999px; }
        .org-group-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)) !important; }
        .org-subgroup-title { display:flex; justify-content:space-between; gap:8px; margin:10px 0 5px; padding:5px 8px; border-radius:10px; background:rgba(0,212,255,.07); color:#AEEAFF; font-size:.84rem; font-weight:900; }
        .org-subgroup-title span { color:#91A9C8; font-size:.75rem; }
        .org-person-card { padding: 7px 10px !important; margin: 5px 0 !important; min-height:auto !important; }
        .org-person-name { font-size: .92rem !important; }
        .org-person-meta { font-size: .73rem !important; }
        @media (max-width: 1200px) { .manpower-gap-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        @media (max-width: 760px) { .manpower-gap-grid { grid-template-columns: 1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, subtitle: str | None = None, show_logo: bool = True) -> None:
    logo_uri = None
    if show_logo:
        logo_uri = _asset_data_uri(ASSETS_DIR / "spt_logo.png") or _asset_data_uri(ASSETS_DIR / "spt_logo.svg")
    logo_html = f'<div class="tech-logo-shell"><img class="tech-logo" src="{logo_uri}" alt="超慧 Logo" /></div>' if logo_uri else ""
    st.markdown(
        f"""
        <div class="tech-hero breathing-glow">
            {logo_html}
            <div style="display:flex; flex-direction:column; justify-content:center; min-width:0;">
              <div class="tech-title">{html.escape(title)}</div>
              <div class="tech-subtitle"><span class="pulse-dot"></span>{html.escape(subtitle or '')}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_human_help(lines: list[str], title: str = "操作提示") -> None:
    items = "".join(f"<li>{html.escape(x)}</li>" for x in lines)
    st.markdown(
        f"""
        <div class="human-card quick-help">
          <b>{html.escape(title)}</b>
          <ul>{items}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_pill(label: str, status: str) -> str:
    mapping = {
        "green": "pill-green",
        "yellow": "pill-yellow",
        "orange": "pill-orange",
        "red": "pill-red",
    }
    css = mapping.get(status, "pill-yellow")
    return f'<span class="status-pill {css}">{html.escape(label)}</span>'



def status_board_html(rows, *, max_items: int = 12) -> str:
    """Return a Power BI/tech style status lamp board for capacity rows."""
    color_map = {
        "綠燈": "green",
        "黃燈": "yellow",
        "橘燈": "orange",
        "紅燈": "red",
        "green": "green",
        "yellow": "yellow",
        "orange": "orange",
        "red": "red",
    }
    try:
        records = rows.to_dict(orient="records") if hasattr(rows, "to_dict") else list(rows or [])
    except Exception:
        records = []
    cards = []
    for row in records[:max_items]:
        month = html.escape(str(row.get("月份", "-")))
        status_text = str(row.get("狀態", "黃燈"))
        color = color_map.get(status_text, "yellow")
        util = row.get("含加班稼動率", 0)
        load = row.get("含加班產能負荷", 0)
        machines = row.get("每月機台數", 0)
        try:
            util_text = f"{float(util):.1%}"
        except Exception:
            util_text = str(util)
        try:
            load_text = f"{float(load):,.0f} h"
        except Exception:
            load_text = str(load)
        try:
            machines_text = f"{float(machines):,.0f} 台"
        except Exception:
            machines_text = str(machines)
        cards.append(
            f'<div class="spt-status-card">'
            f'<div class="spt-status-month"><span>{month}</span><span class="spt-lamp spt-lamp-{color}" title="{html.escape(status_text)}"></span></div>'
            f'<div class="spt-status-meta"><span class="spt-lamp-label">{html.escape(status_text)}</span><br/>含加班稼動率：{html.escape(util_text)}<br/>產能負荷：{html.escape(load_text)}<br/>每月機台數：{html.escape(machines_text)}</div>'
            f'</div>'
        )
    return '<div class="spt-status-board">' + ''.join(cards) + '</div>'



def _tech_icon_svg(kind: str) -> str:
    """Return a lightweight inline SVG icon inspired by the manufacturing war-room reference."""
    common = 'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"'
    icons = {
        "machines": f'<svg viewBox="0 0 24 24" aria-hidden="true"><path {common} d="M4 7h16M6 7v11h12V7M8 10h3v3H8zM13 10h3M13 14h3M8 17h8"/></svg>',
        "hours": f'<svg viewBox="0 0 24 24" aria-hidden="true"><circle {common} cx="12" cy="12" r="8"/><path {common} d="M12 7v5l3 2"/></svg>',
        "people": f'<svg viewBox="0 0 24 24" aria-hidden="true"><path {common} d="M16 18c0-2.2-1.8-4-4-4s-4 1.8-4 4"/><circle {common} cx="12" cy="9" r="3"/><path {common} d="M5 18c0-1.5.8-2.8 2-3.5M19 18c0-1.5-.8-2.8-2-3.5"/></svg>',
        "risk": f'<svg viewBox="0 0 24 24" aria-hidden="true"><path {common} d="M12 3 22 20H2L12 3z"/><path {common} d="M12 9v4M12 17h.01"/></svg>',
        "target": f'<svg viewBox="0 0 24 24" aria-hidden="true"><circle {common} cx="12" cy="12" r="8"/><circle {common} cx="12" cy="12" r="4"/><path {common} d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
        "box": f'<svg viewBox="0 0 24 24" aria-hidden="true"><path {common} d="M12 3 4 7v10l8 4 8-4V7l-8-4z"/><path {common} d="M4 7l8 4 8-4M12 11v10"/></svg>',
    }
    return icons.get(kind, icons["target"])



def render_manpower_gap_cards(df) -> None:
    """Render intuitive manpower shortage/surplus cards for scenario analysis."""
    try:
        if df is None or df.empty:
            return
        gap_col = "人力差異"
        add_col = "建議補人(人)"
        shortage_row = df.sort_values(gap_col, ascending=True).iloc[0] if gap_col in df.columns else df.iloc[0]
        surplus_row = df.sort_values(gap_col, ascending=False).iloc[0] if gap_col in df.columns else df.iloc[0]
        max_add_row = df.sort_values(add_col, ascending=False).iloc[0] if add_col in df.columns else shortage_row
        shortage = float(shortage_row.get(gap_col, 0))
        surplus = float(surplus_row.get(gap_col, 0))
        max_add = float(max_add_row.get(add_col, 0))
        shortage_text = f"缺少 {abs(shortage):.1f} 人" if shortage < 0 else "沒有缺口"
        surplus_text = f"多出 {surplus:.1f} 人" if surplus > 0 else "沒有餘裕"
        shortage_class = 'bad' if shortage < 0 else 'good'
        surplus_class = 'good' if surplus > 0 else ''
        max_add_class = 'bad' if max_add > 0 else 'good'
        html_cards = (
            '<div class="manpower-gap-grid">'
            f'<div class="manpower-gap-card {shortage_class}"><div class="manpower-gap-label">最大缺口月份</div><div class="manpower-gap-value">{html.escape(str(shortage_row.get("月份", "-")))}</div><div class="manpower-gap-sub">{html.escape(shortage_text)}</div></div>'
            f'<div class="manpower-gap-card {surplus_class}"><div class="manpower-gap-label">最大餘裕月份</div><div class="manpower-gap-value">{html.escape(str(surplus_row.get("月份", "-")))}</div><div class="manpower-gap-sub">{html.escape(surplus_text)}</div></div>'
            f'<div class="manpower-gap-card {max_add_class}"><div class="manpower-gap-label">建議最高補人</div><div class="manpower-gap-value">{max_add:.0f}<span style="font-size:1rem;color:#AEEAFF;margin-left:6px;">人</span></div><div class="manpower-gap-sub">月份：{html.escape(str(max_add_row.get("月份", "-")))}</div></div>'
            '<div class="manpower-gap-card"><div class="manpower-gap-label">判斷方式</div><div class="manpower-gap-value" style="font-size:1.42rem;">正數多出<br/>負數缺少</div><div class="manpower-gap-sub">依直接有效人力、需求人力與目標稼動率推估</div></div>'
            '</div>'
        )
        st.markdown(html_cards, unsafe_allow_html=True)
    except Exception:
        return

def render_war_room_kpis(cards: list[dict[str, object]]) -> None:
    """Render coded, technology-styled KPI cards based on the uploaded war-room visual reference."""
    card_html: list[str] = []
    for card in cards:
        title = html.escape(str(card.get("title", "")))
        value = html.escape(str(card.get("value", "")))
        unit = html.escape(str(card.get("unit", "")))
        subtitle = html.escape(str(card.get("subtitle", "")))
        delta = html.escape(str(card.get("delta", "")))
        kind = str(card.get("kind", "target"))
        color = html.escape(str(card.get("color", "blue")))
        delta_class = html.escape(str(card.get("delta_class", "")))
        card_html.append(
            f'<div class="wr-kpi-card {color}">'
            f'  <div class="wr-kpi-top"><div class="wr-icon-wrap">{_tech_icon_svg(kind)}</div>'
            f'    <div style="min-width:0;"><div class="wr-kpi-title">{title}</div><div class="wr-kpi-sub">{subtitle}</div></div>'
            f'  </div>'
            f'  <div class="wr-kpi-value"><span>{value}</span><span class="wr-kpi-unit">{unit}</span></div>'
            f'  <div class="wr-kpi-delta {delta_class}">{delta}</div>'
            f'</div>'
        )
    st.markdown('<div class="wr-kpi-grid">' + ''.join(card_html) + '</div>', unsafe_allow_html=True)
