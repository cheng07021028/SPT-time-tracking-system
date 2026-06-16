from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from services.capacity_engine import MONTH_ORDER, calculate_capacity
from services.data_loader import clear_data_cache, load_all_tables, load_table
from services.page_utils import render_configurable_view, render_module_report_download, render_saveable_table
from services.persistent_store import load_parameters, save_authority_df
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.ui_theme import apply_tech_theme, render_hero, render_human_help, status_board_html, status_pill

st.set_page_config(page_title="04. 產能負荷表", page_icon="📊", layout="wide")
apply_tech_theme()
render_hero("04. 產能負荷表", "月別需求工時(h)、可用工時(h)、稼動率(%)、產能負荷(h)、人力差異(人)與缺工天數(天)。")
render_human_help([
    "篩選條件放在表單內，按『套用查詢』後才更新畫面，避免滑動選項就重算。",
    "圖表已改成 Power BI 風格視覺，且每張圖都可勾選顯示數據標籤。",
    "本頁下方整個模組匯出會包含產能資料、排程、工作天數與 Excel 圖表。",
])

tables = load_all_tables()
params = load_parameters()

# 04. 手動調整工時：永久保存，並加總到需求總工時後再計算稼動率、人力差異與缺工。
adjustments_source = load_table("capacity_adjustments")
if adjustments_source.empty:
    adjustments_source = pd.DataFrame({"月份": MONTH_ORDER, "調整工時": [0.0] * 12, "備註": [""] * 12})
    save_authority_df("capacity_adjustments", adjustments_source, user="auto_schema")
    clear_data_cache()
with st.expander("月別調整工時（永久保存，會加總到需求總工時）", expanded=False):
    st.info("可在這裡手動增加或扣減每月需求工時。按『儲存資料』後，調整工時會永久保存，並立即納入本頁與首頁產能計算。", icon="🛠️")
    adjustments = render_saveable_table("capacity_adjustments", "04. 月別調整工時", height=320, helper_text="例：某月臨時增加 300h 支援工時，就在該月份填入 300；若要扣減，填負數。")

capacity = calculate_capacity(tables["schedule"], tables["standard_hours"], tables["work_calendar"], tables["employees"], tables["dispatch"], params, adjustments)

with st.form("capacity_filter"):
    months = st.multiselect("顯示月份", capacity["月份"].tolist(), default=capacity["月份"].tolist())
    st.form_submit_button("套用查詢", type="primary")
capacity_view = capacity[capacity["月份"].isin(months)].copy() if months else capacity.copy()

max_util = capacity_view["含加班稼動率"].max() if not capacity_view.empty else 0
status = "red" if max_util >= 1.1 else "orange" if max_util >= 1 else "yellow" if max_util >= 0.85 else "green"
st.markdown(status_pill(f"最高含加班稼動率：{max_util:.1%}", status), unsafe_allow_html=True)
st.subheader("月別科技狀態燈")
st.markdown(status_board_html(capacity_view), unsafe_allow_html=True)

chart_view = capacity_view.copy()
chart_view["含加班稼動率%"] = chart_view["含加班稼動率"] * 100
c1, c2 = st.columns([1.2, 1])
with c1:
    fig = px.bar(chart_view, x="月份", y=["需求總工時", "正常可用工時", "含加班可用工時"], barmode="group", title="產能負荷月趨勢（h）")
    render_powerbi_chart(style_powerbi_figure(fig, height=440, legend_title="指標", yaxis_title="工時(h)"), key="capacity_hours_chart")
with c2:
    fig2 = px.line(chart_view, x="月份", y="含加班稼動率%", markers=True, title="含加班稼動率（%）")
    fig2.add_hline(y=85, line_dash="dash", annotation_text="85%")
    fig2.add_hline(y=100, line_dash="dash", annotation_text="100%")
    render_powerbi_chart(style_powerbi_figure(fig2, height=440, yaxis_title="稼動率(%)"), key="capacity_util_chart")

cols = ["月份", "每月機台數", "正常工作日", "原始需求工時", "調整工時", "需求總工時", "正常可用工時", "含加班可用工時", "正常稼動率", "含加班稼動率", "含加班產能負荷", "需求人力", "人力差異", "缺工天數", "狀態"]
existing = [c for c in cols if c in capacity_view.columns]
unit_columns = {
    "每月機台數": "每月機台數(台)",
    "正常工作日": "正常工作日(天)",
    "原始需求工時": "原始需求工時(h)",
    "調整工時": "調整工時(h)",
    "需求總工時": "需求總工時(h)",
    "正常可用工時": "正常可用工時(h)",
    "含加班可用工時": "含加班可用工時(h)",
    "正常稼動率": "正常稼動率(%)",
    "含加班稼動率": "含加班稼動率(%)",
    "含加班產能負荷": "含加班產能負荷(h)",
    "需求人力": "需求人力(人)",
    "人力差異": "人力差異(人)",
    "缺工天數": "缺工天數(天)",
}
capacity_table = capacity_view[existing].copy()
for pct_col in ["正常稼動率", "含加班稼動率"]:
    if pct_col in capacity_table.columns:
        capacity_table[pct_col] = capacity_table[pct_col] * 100
capacity_table = capacity_table.rename(columns=unit_columns)
render_configurable_view(capacity_table, "capacity", "04. 產能負荷表", height=430)

capacity_export = capacity_table.copy()
st.subheader("04. 模組完整匯出")
render_module_report_download(
    "04.產能負荷表",
    {"產能負荷": capacity_export, "月別調整工時": adjustments, "原始排程": tables["schedule"], "工作天數": tables["work_calendar"]},
    chart_specs=[
        chart_spec("bar", "產能負荷月趨勢（h）", "產能負荷", "月份", ["需求總工時(h)", "正常可用工時(h)", "含加班可用工時(h)"]),
        chart_spec("line", "含加班稼動率趨勢（%）", "產能負荷", "月份", ["含加班稼動率(%)"]),
        chart_spec("bar", "月別人力差異（人）", "產能負荷", "月份", ["人力差異(人)"]),
    ],
    metadata={"模組": "04. 產能負荷表", "最高含加班稼動率": f"{max_util:.1%}"},
    key="export_capacity_module",
)
