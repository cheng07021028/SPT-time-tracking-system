from __future__ import annotations

import plotly.express as px
import streamlit as st

from services.capacity_engine import summarize_manpower
from services.data_loader import load_table
from services.page_utils import render_configurable_view, render_module_report_download, render_saveable_table
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.ui_theme import apply_tech_theme, render_hero, render_human_help

st.set_page_config(page_title="01. 超慧員工名單", page_icon="👥", layout="wide")
apply_tech_theme()
render_hero("01. 超慧員工名單", "正職人力主檔、直接/間接人力、可用比例、工段與備註都可在系統內永久維護。")
render_human_help([
    "可直接在表格新增、修改、刪除人員，不必每次回 Excel 修改後再匯入。",
    "欄位顯示與欄位順序可按『套用設定』永久保存。",
    "修改到職日後，按「儲存資料」會自動重新計算並保存「累積年資」。",
    "本頁下方提供整個模組匯出，包含員工資料、摘要資料與 Power BI 風格 Excel 圖表。",
])

employees = render_saveable_table("employees", "01. 超慧員工名單", helper_text="建議維護『是否直接人力』與『可用比例』，這會影響產能可用工時。")

_valid_employees = employees.dropna(how="all") if not employees.empty else employees
st.markdown(
    f"""
    <div class=\"people-total-card\">
      <div class=\"people-total-label\">正職總人數</div>
      <div class=\"people-total-value\">{len(_valid_employees):,}<span>人</span></div>
      <div class=\"people-total-note\">以目前權威資料表非空白列計算</div>
    </div>
    """,
    unsafe_allow_html=True,
)
dispatch = load_table("dispatch")

st.subheader("正職人力摘要")
summary = summarize_manpower(employees, dispatch.iloc[0:0] if not dispatch.empty else dispatch) if not employees.empty else load_table("employees").iloc[0:0]
if not employees.empty:
    c1, c2 = st.columns([1, 1.2])
    with c1:
        fig = px.bar(summary, x="工段", y="有效人力", color="課別", title="正職有效人力 by 工段")
        render_powerbi_chart(style_powerbi_figure(fig, height=380, yaxis_title="有效人力", xaxis_title="工段"), key="employees_summary_chart")
    with c2:
        render_configurable_view(summary, "employees_summary", "01. 正職人力摘要", height=380)
else:
    st.warning("目前沒有員工資料，可直接按『新增空白列』建立人員主檔。")

st.subheader("01. 模組完整匯出")
render_module_report_download(
    "01.超慧員工名單",
    {"員工名單": employees, "正職人力摘要": summary},
    chart_specs=[
        chart_spec("bar", "正職有效人力 by 工段", "正職人力摘要", "工段", ["有效人力"]),
        chart_spec("pie", "正職人力來源比例", "正職人力摘要", "課別", ["有效人力"]),
    ],
    metadata={"模組": "01. 超慧員工名單", "匯出內容": "員工資料、摘要與圖表"},
    key="export_employees_module",
)
