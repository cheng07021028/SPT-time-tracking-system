from __future__ import annotations

import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from services.capacity_engine import summarize_manpower
from services.data_loader import load_table
from services.org_chart_service import build_people_frame, render_org_component_html, render_org_html
from services.page_utils import render_configurable_view, render_module_report_download
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.ui_theme import apply_tech_theme, render_hero, render_human_help

st.set_page_config(page_title="03. 製造部組織圖", page_icon="🛰️", layout="wide")
apply_tech_theme()
render_hero("03. 製造部組織圖", "依 Excel 組織圖概念呈現每個課別、每個工段、每位人員，清楚看出人力結構。")
render_human_help([
    "本頁提供樹枝圖組織圖：製造部 → 製一課 / 製二課 → 工段 → 人員；可拖拉課別、工段與人員卡片調整展示位置。",
    "拖拉版面可保存於瀏覽器方便開會展示；正式人員歸屬仍以 01/02 頁的課別、工段欄位為權威。",
    "上方可篩選課別、工段與人力來源；下方整個模組匯出會包含組織明細、摘要與圖表。",
    "若要更改人員歸屬，請回 01 或 02 頁修改並儲存，組織圖會讀取最新權威資料。",
])

employees = load_table("employees")
dispatch = load_table("dispatch")
people = build_people_frame(employees, dispatch)
summary = summarize_manpower(employees, dispatch)

with st.form("org_filter_form"):
    c1, c2, c3 = st.columns(3)
    dept_options = sorted([x for x in people.get("課別", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    group_options = sorted([x for x in people.get("工段", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    source_options = sorted([x for x in people.get("人力來源", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    selected_depts = c1.multiselect("課別", dept_options, default=dept_options)
    selected_groups = c2.multiselect("工段", group_options, default=group_options)
    selected_sources = c3.multiselect("人力來源", source_options, default=source_options)
    st.form_submit_button("套用組織圖篩選", type="primary")

view = people.copy()
if selected_depts:
    view = view[view["課別"].astype(str).isin(selected_depts)]
if selected_groups:
    view = view[view["工段"].astype(str).isin(selected_groups)]
if selected_sources:
    view = view[view["人力來源"].astype(str).isin(selected_sources)]

if view.empty:
    st.warning("目前篩選條件下沒有組織人力資料。")
else:
    view_mode = st.radio("組織圖顯示模式", ["樹枝圖（可拖拉卡片）", "原先卷軸式"], horizontal=True, index=0)
    if view_mode == "樹枝圖（可拖拉卡片）":
        components.html(render_org_component_html(view), height=900, scrolling=False)
        st.caption("樹枝圖可拖拉課別、工段、人員卡片，也可將課別放大檢視；正式課別/工段歸屬請在 01/02 頁修改並儲存，避免拖拉畫面誤改權威資料。")
    else:
        st.markdown(f'<div class="org-scroll-wrap">{render_org_html(view)}</div>', unsafe_allow_html=True)

st.subheader("組織 Power BI 風格摘要")
if not summary.empty:
    c1, c2 = st.columns([1, 1])
    with c1:
        fig = px.bar(summary, x="工段", y="有效人力", color="課別", title="工段有效人力")
        render_powerbi_chart(style_powerbi_figure(fig, height=360, yaxis_title="有效人力"), key="org_effective_people")
    with c2:
        src = summary.groupby("人力來源", as_index=False).agg(有效人力=("有效人力", "sum"))
        fig2 = px.pie(src, names="人力來源", values="有效人力", title="人力來源占比")
        render_powerbi_chart(style_powerbi_figure(fig2, height=360), key="org_source_mix")
else:
    src = summary.copy()

st.subheader("組織摘要表")
render_configurable_view(summary, "org_summary", "03. 組織人力摘要", height=420)

st.subheader("03. 模組完整匯出")
source_mix = summary.groupby("人力來源", as_index=False).agg(有效人力=("有效人力", "sum")) if not summary.empty and "人力來源" in summary.columns else summary.copy()
render_module_report_download(
    "03.製造部組織圖",
    {"組織明細": view, "組織摘要": summary, "人力來源占比": source_mix},
    chart_specs=[
        chart_spec("bar", "工段有效人力", "組織摘要", "工段", ["有效人力"]),
        chart_spec("pie", "人力來源占比", "人力來源占比", "人力來源", ["有效人力"]),
    ],
    metadata={"模組": "03. 製造部組織圖", "匯出內容": "組織明細、摘要與圖表"},
    key="export_org_module",
)
