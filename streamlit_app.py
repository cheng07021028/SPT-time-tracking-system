from __future__ import annotations

import plotly.express as px
import streamlit as st

from services.capacity_engine import calculate_capacity, summarize_manpower, validate_schedule
from services.config import SYSTEM_SUBTITLE
from services.data_loader import ensure_bootstrap, load_all_tables
from services.page_utils import render_configurable_view, render_module_report_download
from services.persistent_store import load_parameters
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.settings_service import load_ui_settings, save_ui_settings
from services.ui_theme import apply_tech_theme, render_hero, render_human_help, render_war_room_kpis, status_pill

st.set_page_config(
    page_title="00. 超慧科技製造部產能儀表板",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_tech_theme()
bootstrap_result = ensure_bootstrap()

st.sidebar.markdown("### 模組快速導覽")
st.sidebar.markdown(
    """
    <div class="sidebar-module-list">
      <div>00. 超慧科技製造部產能儀表板</div>
      <div>01. 超慧員工名單</div>
      <div>02. 派遣名單</div>
      <div>03. 製造部組織圖</div>
      <div>04. 產能負荷表</div>
      <div>05. 排程表</div>
      <div>06. 標準工時</div>
      <div>07. 工作天數設定</div>
      <div>08. 人力參數設定</div>
      <div>09. 情境模擬</div>
      <div>10. 資料匯入與版本管理</div>
      <div>11. 權限與系統設定</div>
    </div>
    """,
    unsafe_allow_html=True,
)

render_hero("00. 超慧科技製造部產能儀表板", SYSTEM_SUBTITLE)
render_human_help([
    "首頁圖表已套用 Power BI 風格：深色報表卡片、商務配色、清楚座標與低干擾圖例。",
    "資料仍只讀取已保存的權威資料與快取計算結果，不會每次切頁重新讀 Excel。",
    "頁面下方只保留『整個模組匯出』，匯出的 Excel 會包含資料表與可編輯圖表。",
])
if bootstrap_result:
    st.success(f"已建立或補齊權威資料：{bootstrap_result}")

tables = load_all_tables()
params = load_parameters()
capacity = calculate_capacity(
    tables["schedule"],
    tables["standard_hours"],
    tables["work_calendar"],
    tables["employees"],
    tables["dispatch"],
    params,
    tables.get("capacity_adjustments"),
)

month_options = capacity["月份"].astype(str).tolist() if not capacity.empty else []
ui_settings = load_ui_settings()
saved_month = str(ui_settings.get("home_month", month_options[0] if month_options else ""))
if saved_month not in month_options and month_options:
    saved_month = month_options[0]

st.sidebar.markdown('<div class="spt-sidebar-apply-card">', unsafe_allow_html=True)
st.sidebar.markdown("#### 首頁月份")
st.sidebar.markdown(f'<div class="spt-current-month">目前套用：{saved_month or "未設定"}</div>', unsafe_allow_html=True)
with st.sidebar.form("home_month_apply_form"):
    draft_month = st.selectbox("選擇首頁月份", month_options, index=month_options.index(saved_month) if saved_month in month_options else 0)
    apply_month = st.form_submit_button("套用並永久保存", type="primary", use_container_width=True)
if apply_month:
    ui_settings["home_month"] = draft_month
    save_ui_settings(ui_settings, user="streamlit")
    st.sidebar.success(f"已永久套用首頁月份：{draft_month}")
    st.rerun()
st.sidebar.markdown('</div>', unsafe_allow_html=True)

selected_month = saved_month
month_row = capacity[capacity["月份"].astype(str).eq(selected_month)].iloc[0] if selected_month else capacity.iloc[0]

st.sidebar.markdown("---")
st.sidebar.info("本系統使用 data/persistent/authority 作為權威資料區；GitHub 同步在第 10 頁手動執行。", icon="💾")

status = str(month_row["狀態"])
status_color = "red" if status == "紅燈" else "orange" if status == "橘燈" else "yellow" if status == "黃燈" else "green"
st.markdown(status_pill(f"{selected_month} 狀態：{status}", status_color), unsafe_allow_html=True)

render_war_room_kpis([
    {"title": "本月機台數", "subtitle": f"{selected_month} 排程總量", "value": f"{month_row['每月機台數']:,.0f}", "unit": "台", "delta": f"狀態：{status}", "kind": "machines", "color": status_color, "delta_class": "danger" if status_color == "red" else "warn" if status_color in {"yellow", "orange"} else ""},
    {"title": "需求總工時", "subtitle": "訂單 × 標準工時", "value": f"{month_row['需求總工時']:,.0f}", "unit": "h", "delta": "由權威排程即時計算", "kind": "hours", "color": "blue"},
    {"title": "含加班可用工時", "subtitle": "正常 + 平日/假日加班", "value": f"{month_row['含加班可用工時']:,.0f}", "unit": "h", "delta": "依人力參數與工作天數", "kind": "target", "color": "green"},
    {"title": "含加班稼動率", "subtitle": "需求 / 含加班產能", "value": f"{month_row['含加班稼動率']:.1%}", "unit": "", "delta": "紅/橘/黃/綠燈自動判斷", "kind": "risk", "color": status_color, "delta_class": "danger" if status_color == "red" else "warn" if status_color in {"yellow", "orange"} else ""},
    {"title": "含加班產能負荷", "subtitle": "可用工時 - 需求工時", "value": f"{month_row['含加班產能負荷']:,.0f}", "unit": "h", "delta": "正數代表仍有餘裕", "kind": "box", "color": "green" if month_row['含加班產能負荷'] >= 0 else "red", "delta_class": "danger" if month_row['含加班產能負荷'] < 0 else ""},
    {"title": "需求人力", "subtitle": "需求工時換算人力", "value": f"{month_row['需求人力']:,.1f}", "unit": "人", "delta": "依工作日與每日工時計算", "kind": "people", "color": "blue"},
    {"title": "人力差異", "subtitle": "現有人力 - 需求人力", "value": f"{month_row['人力差異']:,.1f}", "unit": "人", "delta": "負數代表需補人或加班", "kind": "people", "color": "green" if month_row['人力差異'] >= 0 else "red", "delta_class": "danger" if month_row['人力差異'] < 0 else ""},
    {"title": "缺工天數", "subtitle": "缺口工時換算天數", "value": f"{month_row['缺工天數']:,.1f}", "unit": "天", "delta": "0 天代表含加班後可承接", "kind": "risk", "color": "green" if month_row['缺工天數'] <= 0 else "orange", "delta_class": "warn" if month_row['缺工天數'] > 0 else ""},
])

st.markdown('<div class="spt-divider"></div>', unsafe_allow_html=True)

chart_df = capacity.copy()
chart_df["含加班稼動率%"] = chart_df["含加班稼動率"] * 100
left, right = st.columns([1.15, 1])
with left:
    fig = px.bar(
        chart_df,
        x="月份",
        y=["需求總工時", "正常可用工時", "含加班可用工時"],
        barmode="group",
        title="每月需求工時 vs 可用工時",
    )
    render_powerbi_chart(style_powerbi_figure(fig, height=430, legend_title="指標", yaxis_title="工時"), key="home_capacity_hours")
with right:
    fig2 = px.line(
        chart_df,
        x="月份",
        y="含加班稼動率%",
        markers=True,
        title="含加班稼動率趨勢",
    )
    fig2.add_hline(y=85, line_dash="dash", annotation_text="85% 警戒")
    fig2.add_hline(y=100, line_dash="dash", annotation_text="100% 滿載")
    render_powerbi_chart(style_powerbi_figure(fig2, height=430, yaxis_title="稼動率 %"), key="home_utilization")

st.subheader("人力結構摘要")
manpower = summarize_manpower(tables["employees"], tables["dispatch"])
if manpower.empty:
    st.warning("目前沒有可用人力資料。")
else:
    c1, c2 = st.columns([1, 1])
    with c1:
        group_summary = manpower.groupby("人力來源", as_index=False).agg(總人數=("總人數", "sum"), 有效人力=("有效人力", "sum"))
        fig3 = px.pie(group_summary, names="人力來源", values="有效人力", title="有效人力來源比例")
        render_powerbi_chart(style_powerbi_figure(fig3, height=360), key="home_manpower_mix")
    with c2:
        render_configurable_view(manpower, "home_manpower", "首頁人力摘要", height=360)

st.subheader("資料品質檢查")
checks = validate_schedule(tables["schedule"])
render_configurable_view(checks, "home_quality_checks", "首頁資料品質檢查", height=300)

st.subheader("首頁完整模組匯出")
render_module_report_download(
    "00.超慧科技製造部產能儀表板",
    {
        "產能摘要": capacity,
        "人力摘要": manpower,
        "資料品質檢查": checks,
    },
    chart_specs=[
        chart_spec("bar", "每月需求工時 vs 可用工時", "產能摘要", "月份", ["需求總工時", "正常可用工時", "含加班可用工時"]),
        chart_spec("line", "含加班稼動率趨勢", "產能摘要", "月份", ["含加班稼動率"]),
        chart_spec("pie", "有效人力來源比例", "人力摘要", "人力來源", ["有效人力"]),
    ],
    metadata={"模組": "00. 超慧科技製造部產能儀表板", "首頁月份": selected_month, "資料來源": "data/persistent/authority"},
    key="export_home_module",
)
