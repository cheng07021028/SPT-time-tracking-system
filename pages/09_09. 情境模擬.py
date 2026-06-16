from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from services.capacity_engine import calculate_capacity
from services.config import PERSISTENT_DIR
from services.data_loader import load_all_tables
from services.page_utils import render_configurable_view, render_module_report_download
from services.persistent_store import load_json, load_parameters, save_json
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.ui_theme import apply_tech_theme, render_hero, render_human_help, render_manpower_gap_cards

st.set_page_config(page_title="09. 情境模擬", page_icon="🧪", layout="wide")
apply_tech_theme()
render_hero("09. 情境模擬", "調整加班比例、效率、人力投入與風險條件，快速比較需求、人力需求與可用工時。")
render_human_help([
    "滑桿與輸入框不會立即寫入資料，按『執行情境模擬』才計算。",
    "人力模擬可分別輸入新增正職、派遣、外包與專案/間接扣除，系統會推估需求人力與建議補人數。",
    "勾選保存後，模擬結果會寫入 scenario_runs.json，可離開頁面後繼續查看。",
    "本頁下方整個模組匯出會包含已保存情境、最後情境結果、人力需求判斷與圖表。",
])

tables = load_all_tables()
base_params = load_parameters()

with st.form("scenario_form"):
    scenario_name = st.text_input("情境名稱", value=f"Scenario {datetime.now().strftime('%m%d_%H%M')}")
    st.markdown("### 基礎產能條件")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        daily_hours = st.number_input("每日正常工時", 1.0, 12.0, float(base_params.get("daily_hours", 7.0)), 0.5)
        efficiency = st.number_input("工作效率", 0.1, 2.0, float(base_params.get("efficiency", 1.0)), 0.05)
    with c2:
        weekday_ratio = st.slider("平日加班人數比例", 0, 100, int(float(base_params.get("weekday_overtime_ratio", 0.3)) * 100)) / 100
        holiday_ratio = st.slider("假日加班人數比例", 0, 100, int(float(base_params.get("holiday_overtime_ratio", 0.3)) * 100)) / 100
    with c3:
        standard_hour_factor = st.number_input("標準工時倍率", 0.5, 2.0, 1.0, 0.05)
        order_factor = st.number_input("訂單需求倍率", 0.5, 2.0, 1.0, 0.05)
    with c4:
        target_utilization = st.slider("目標含加班稼動率", 60, 120, 90, 5) / 100
        save_run = st.checkbox("儲存本次模擬結果", value=True)

    st.markdown("### 人力模擬")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        add_regular_people = st.number_input("新增正職有效人力(人)", -50.0, 100.0, 0.0, 1.0)
    with m2:
        add_dispatch_people = st.number_input("新增派遣有效人力(人)", -50.0, 100.0, 0.0, 1.0)
    with m3:
        add_outsource_people = st.number_input("新增外包有效人力(人)", -50.0, 100.0, 0.0, 1.0)
    with m4:
        project_deduct_people = st.number_input("專案/間接扣除人力(人)", 0.0, 100.0, 0.0, 1.0)
    extra_people = add_regular_people + add_dispatch_people + add_outsource_people - project_deduct_people
    st.caption(f"本次模擬淨增有效人力：{extra_people:+.1f} 人。只有按下『執行情境模擬』才會計算，不會立即改正式資料。")
    run = st.form_submit_button("執行情境模擬", type="primary")

params = dict(base_params)
params.update({
    "daily_hours": daily_hours,
    "efficiency": efficiency,
    "weekday_overtime_ratio": weekday_ratio,
    "holiday_overtime_ratio": holiday_ratio,
})

base_capacity = calculate_capacity(
    tables["schedule"],
    tables["standard_hours"],
    tables["work_calendar"],
    tables["employees"],
    tables["dispatch"],
    base_params,
    tables.get("capacity_adjustments"),
)

dispatch = tables["dispatch"].copy()
if extra_people != 0:
    dispatch = dispatch.copy()
    dispatch.loc[len(dispatch)] = {
        "姓名": "情境模擬淨增/扣除有效人力",
        "課別": "情境",
        "工段": "情境",
        "人力來源": "情境模擬",
        "是否直接人力": "是",
        "可用比例": extra_people,
        "啟用": "是",
    }

schedule = tables["schedule"].copy()
if order_factor != 1.0 and "台數" in schedule.columns:
    schedule["台數"] = pd.to_numeric(schedule["台數"], errors="coerce").fillna(1) * order_factor
standard = tables["standard_hours"].copy()
if standard_hour_factor != 1.0 and "標準工時" in standard.columns:
    standard["標準工時"] = pd.to_numeric(standard["標準工時"], errors="coerce").fillna(0) * standard_hour_factor

result = pd.DataFrame()
manpower_analysis = pd.DataFrame()
comparison = pd.DataFrame()

if run:
    result = calculate_capacity(schedule, standard, tables["work_calendar"], tables["employees"], dispatch, params, tables.get("capacity_adjustments"))
    comparison = base_capacity[["月份", "需求總工時", "含加班可用工時", "含加班稼動率", "人力差異", "缺工天數"]].copy()
    comparison = comparison.rename(columns={
        "需求總工時": "原始需求總工時",
        "含加班可用工時": "原始含加班可用工時",
        "含加班稼動率": "原始含加班稼動率",
        "人力差異": "原始人力差異",
        "缺工天數": "原始缺工天數",
    }).merge(
        result[["月份", "需求總工時", "含加班可用工時", "含加班稼動率", "需求人力", "直接有效人力", "人力差異", "缺工天數", "狀態"]],
        on="月份",
        how="left",
    )

    analysis = result.copy()
    per_person_capacity = analysis["含加班可用工時"] / analysis["直接有效人力"].replace(0, pd.NA)
    analysis["目標達標需求人力"] = (analysis["需求總工時"] / (per_person_capacity * target_utilization)).fillna(0)
    analysis["建議補人(人)"] = (analysis["目標達標需求人力"] - analysis["直接有效人力"]).clip(lower=0)
    analysis["建議補人(人)"] = analysis["建議補人(人)"].apply(lambda x: int(x) if abs(x - int(x)) < 0.01 else int(x) + 1)
    analysis["含加班稼動率(%)"] = analysis["含加班稼動率"] * 100
    manpower_analysis = analysis[["月份", "直接有效人力", "需求人力", "目標達標需求人力", "建議補人(人)", "人力差異", "缺工天數", "含加班稼動率(%)", "狀態"]].copy()

    st.subheader("人力需求判斷")
    if not manpower_analysis.empty:
        peak = manpower_analysis.sort_values("建議補人(人)", ascending=False).iloc[0]
        surplus = manpower_analysis.sort_values("人力差異", ascending=False).iloc[0]
        st.info(f"最大人力缺口月份：{peak['月份']}；依目標含加班稼動率 {target_utilization:.0%} 推估，建議補人 {peak['建議補人(人)']} 人。", icon="🧠")
        render_manpower_gap_cards(manpower_analysis)
    fig_people = px.bar(manpower_analysis, x="月份", y=["直接有效人力", "需求人力", "目標達標需求人力"], barmode="group", title="人力需求模擬（人）")
    render_powerbi_chart(style_powerbi_figure(fig_people, height=430, yaxis_title="人力(人)", legend_title="指標"), key="scenario_people_chart")
    gap_fig = px.bar(manpower_analysis, x="月份", y="人力差異", color="人力差異", title="每月人力差異：正數為多出、負數為缺少")
    render_powerbi_chart(style_powerbi_figure(gap_fig, height=380, yaxis_title="人力差異(人)", legend_title="缺口/餘裕"), key="scenario_gap_chart")
    render_configurable_view(manpower_analysis, "scenario_manpower_analysis", "09. 人力需求判斷", height=420)

    st.subheader("情境與原始差異")
    render_configurable_view(comparison, "scenario_comparison", "09. 情境與原始差異", height=360)

    fig = px.line(result, x="月份", y=["需求總工時", "含加班可用工時"], markers=True, title=f"{scenario_name}：需求 vs 可用工時")
    render_powerbi_chart(style_powerbi_figure(fig, height=430, yaxis_title="工時", legend_title="指標"), key="scenario_result_chart")
    render_configurable_view(result, "scenario_result", "09. 情境模擬結果", height=420)

    if save_run:
        path = PERSISTENT_DIR / "scenario_runs.json"
        runs = load_json(path, default=[]) or []
        runs.append({
            "name": scenario_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "params": params,
            "add_regular_people": add_regular_people,
            "add_dispatch_people": add_dispatch_people,
            "add_outsource_people": add_outsource_people,
            "project_deduct_people": project_deduct_people,
            "extra_people": extra_people,
            "target_utilization": target_utilization,
            "standard_hour_factor": standard_hour_factor,
            "order_factor": order_factor,
            "result": result.to_dict(orient="records"),
            "manpower_analysis": manpower_analysis.to_dict(orient="records"),
        })
        save_json(path, runs)
        st.success("本次情境模擬已永久保存到 data/persistent/scenario_runs.json。")
else:
    st.info("請調整參數後按『執行情境模擬』，避免滑桿每次變動就重算。", icon="⚡")

st.subheader("已保存情境")
runs = load_json(PERSISTENT_DIR / "scenario_runs.json", default=[]) or []
latest_result = result.copy()
if runs:
    runs_df = pd.DataFrame([
        {
            "名稱": r.get("name"),
            "建立時間": r.get("created_at"),
            "新增正職": r.get("add_regular_people", 0),
            "新增派遣": r.get("add_dispatch_people", 0),
            "新增外包": r.get("add_outsource_people", 0),
            "扣除人力": r.get("project_deduct_people", 0),
            "淨增有效人力": r.get("extra_people"),
            "目標稼動率": r.get("target_utilization", 0),
            "工時倍率": r.get("standard_hour_factor", 1),
            "訂單倍率": r.get("order_factor", 1),
        }
        for r in runs
    ])
    render_configurable_view(runs_df, "scenario_saved", "09. 已保存情境", height=320)
    if latest_result.empty:
        latest_result = pd.DataFrame(runs[-1].get("result", [])) if runs[-1].get("result") else pd.DataFrame()
    if manpower_analysis.empty and runs[-1].get("manpower_analysis"):
        manpower_analysis = pd.DataFrame(runs[-1].get("manpower_analysis", []))
else:
    runs_df = pd.DataFrame()
    st.caption("目前尚未保存情境。")

st.subheader("09. 模組完整匯出")
export_sheets = {"已保存情境": runs_df, "最後情境結果": latest_result, "人力需求判斷": manpower_analysis}
chart_specs = []
if not manpower_analysis.empty and "月份" in manpower_analysis.columns:
    chart_specs.append(chart_spec("bar", "人力需求模擬", "人力需求判斷", "月份", ["直接有效人力", "需求人力", "目標達標需求人力"]))
if not latest_result.empty and "月份" in latest_result.columns:
    chart_specs.append(chart_spec("line", "最後情境需求 vs 可用工時", "最後情境結果", "月份", ["需求總工時", "含加班可用工時"]))
    chart_specs.append(chart_spec("bar", "最後情境人力差異", "最後情境結果", "月份", ["人力差異"]))
render_module_report_download(
    "09.情境模擬",
    export_sheets,
    chart_specs=chart_specs,
    metadata={"模組": "09. 情境模擬", "目前情境名稱": scenario_name, "目標含加班稼動率": f"{target_utilization:.0%}"},
    key="export_scenario_module",
)
