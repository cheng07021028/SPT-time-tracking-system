from __future__ import annotations

import plotly.express as px
import streamlit as st

from services.capacity_engine import summarize_manpower
from services.data_loader import load_table
from services.page_utils import render_configurable_view, render_module_report_download, render_saveable_table
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.ui_theme import apply_tech_theme, render_hero, render_human_help

st.set_page_config(page_title="02. 派遣名單", page_icon="🧑‍🏭", layout="wide")
apply_tech_theme()
render_hero("02. 派遣名單", "派遣與外包人力主檔、廠商、工段、可用比例、啟用狀態與備註永久保存。")
render_human_help([
    "離場人員可將『啟用』設為否或備註，不建議直接刪除歷史資料。",
    "可用比例會被折算到產能，派遣新人或支援人力可設定 0.3、0.5、0.8 等。",
    "修改到職日後，按「儲存資料」會自動重新計算並保存「累積年資」。",
    "本頁下方提供整個模組匯出，包含派遣資料、來源比例與摘要圖表。",
])

dispatch = render_saveable_table("dispatch", "02. 派遣名單", helper_text="派遣/外包人力是產能的重要彈性來源，建議維護工段與可用比例。")

_valid_dispatch = dispatch.dropna(how="all") if not dispatch.empty else dispatch
st.markdown(
    f"""
    <div class=\"people-total-card\">
      <div class=\"people-total-label\">派遣/外包總人數</div>
      <div class=\"people-total-value\">{len(_valid_dispatch):,}<span>人</span></div>
      <div class=\"people-total-note\">以目前權威資料表非空白列計算</div>
    </div>
    """,
    unsafe_allow_html=True,
)
employees = load_table("employees")

st.subheader("派遣/外包摘要")
summary = summarize_manpower(employees.iloc[0:0] if not employees.empty else employees, dispatch) if not dispatch.empty else dispatch.copy()
vendor = dispatch.iloc[0:0].copy()
if not dispatch.empty:
    c1, c2 = st.columns([1, 1.2])
    with c1:
        vendor_col = "部 門" if "部 門" in dispatch.columns else "人力來源"
        vendor = dispatch.groupby(vendor_col, dropna=False).size().reset_index(name="人數")
        fig = px.pie(vendor, names=vendor_col, values="人數", title="派遣/外包來源比例")
        render_powerbi_chart(style_powerbi_figure(fig, height=380), key="dispatch_vendor_mix")
    with c2:
        render_configurable_view(summary, "dispatch_summary", "02. 派遣外包摘要", height=380)
else:
    st.warning("目前沒有派遣資料，可直接按『新增空白列』建立派遣主檔。")

st.subheader("02. 模組完整匯出")
render_module_report_download(
    "02.派遣名單",
    {"派遣名單": dispatch, "派遣外包摘要": summary, "來源比例": vendor},
    chart_specs=[
        chart_spec("pie", "派遣/外包來源比例", "來源比例", "部 門" if "部 門" in vendor.columns else "人力來源", ["人數"]),
        chart_spec("bar", "派遣有效人力 by 工段", "派遣外包摘要", "工段", ["有效人力"]),
    ],
    metadata={"模組": "02. 派遣名單", "匯出內容": "派遣資料、摘要與圖表"},
    key="export_dispatch_module",
)
