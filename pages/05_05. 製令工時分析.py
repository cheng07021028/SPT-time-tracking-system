# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.time_record_service import load_records, save_time_records
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms
from services.timezone_service import today_date
from services.analysis_filter_service import load_analysis_filters, save_analysis_filters
from services.master_data_service import load_work_orders, load_employees

st.set_page_config(page_title="05. 製令工時分析", page_icon="📊", layout="wide")
apply_theme()
require_module_access("05_analysis")
render_header("05｜製令工時分析", "製令、工段、人員累積工時分析與明細編輯")

FILTER_KEY = "_spt_05_analysis_filters"
if FILTER_KEY not in st.session_state:
    st.session_state[FILTER_KEY] = load_analysis_filters()
filters = dict(st.session_state[FILTER_KEY])

DATE_PRESETS = ["今日", "近7天", "近30天", "本月", "上月", "自訂區間"]
STATUS_OPTIONS = ["全部", "作業中", "暫停", "完工", "下班", "未結束", "已結束"]
ANOMALY_OPTIONS = ["全部", "工時 = 0", "工時小於5分鐘", "工時大於8小時", "工時大於12小時", "未按結束", "跨日紀錄", "有開始無結束", "有結束無開始"]
TOP_OPTIONS = ["Top 10", "Top 20", "Top 50", "全部"]
SORT_OPTIONS = ["累積工時由大到小", "製令由新到舊", "工段數量", "人數", "紀錄筆數", "平均工時"]


def _parse_date(value, fallback: date) -> date:
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return fallback


def _date_range_from_preset(preset: str, start_value: date, end_value: date) -> tuple[date, date]:
    today = today_date()
    if preset == "今日":
        return today, today
    if preset == "近7天":
        return today - timedelta(days=7), today
    if preset == "近30天":
        return today - timedelta(days=30), today
    if preset == "本月":
        return today.replace(day=1), today
    if preset == "上月":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    return start_value, end_value


def _safe_unique(df: pd.DataFrame, col: str, selected: list[str] | None = None) -> list[str]:
    selected = selected or []
    vals: list[str] = []
    if df is not None and not df.empty and col in df.columns:
        vals = sorted({str(x).strip() for x in df[col].dropna().tolist() if str(x).strip() and str(x).strip().lower() != "none"})
    for x in selected:
        if x and x not in vals:
            vals.append(x)
    return vals


def _clean_filter_list(values) -> list[str]:
    if values is None:
        return []
    return [str(x).strip() for x in list(values) if str(x).strip()]


def _enrich_records(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    # 補入製令主檔欄位：客戶、組立地點、P/N、機型。
    try:
        wo = load_work_orders(active_only=False)
        if wo is not None and not wo.empty and "work_order" in wo.columns and "work_order" in out.columns:
            keep = [c for c in ["work_order", "customer", "assembly_location", "part_no", "type_name"] if c in wo.columns]
            wo2 = wo[keep].drop_duplicates("work_order").copy()
            rename = {c: f"wo_{c}" for c in keep if c != "work_order"}
            wo2 = wo2.rename(columns=rename)
            out = out.merge(wo2, on="work_order", how="left")
            for c in ["customer", "assembly_location", "part_no", "type_name"]:
                wc = f"wo_{c}"
                if wc in out.columns:
                    if c not in out.columns:
                        out[c] = out[wc]
                    else:
                        out[c] = out[c].fillna("")
                        out[c] = out[c].astype(str)
                        mask = out[c].str.strip().isin(["", "None", "nan"])
                        out.loc[mask, c] = out.loc[mask, wc]
                    out = out.drop(columns=[wc])
    except Exception:
        pass

    # 補入人員主檔欄位：單位、職稱。
    try:
        emp = load_employees(active_only=False)
        if emp is not None and not emp.empty and "employee_id" in emp.columns and "employee_id" in out.columns:
            keep = [c for c in ["employee_id", "department", "title"] if c in emp.columns]
            emp2 = emp[keep].drop_duplicates("employee_id").copy()
            out = out.merge(emp2, on="employee_id", how="left")
    except Exception:
        pass

    for col in ["customer", "assembly_location", "department", "title"]:
        if col not in out.columns:
            out[col] = ""
    return out


def _apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df.copy()
    exact_map = {
        "work_orders": "work_order",
        "part_nos": "part_no",
        "type_names": "type_name",
        "customers": "customer",
        "assembly_locations": "assembly_location",
        "process_names": "process_name",
        "employee_ids": "employee_id",
        "employee_names": "employee_name",
        "departments": "department",
        "titles": "title",
    }
    for key, col in exact_map.items():
        vals = _clean_filter_list(f.get(key, []))
        if vals and col in out.columns:
            out = out[out[col].fillna("").astype(str).isin(vals)]

    status = str(f.get("status_filter") or "全部")
    if "status" in out.columns:
        st_series = out["status"].fillna("").astype(str)
        end_ts = out.get("end_timestamp", pd.Series([""] * len(out))).fillna("").astype(str).str.strip()
        if status in {"作業中", "暫停", "完工", "下班"}:
            out = out[st_series == status]
        elif status == "未結束":
            out = out[(st_series == "作業中") & (end_ts.isin(["", "None", "none", "nan"]))]
        elif status == "已結束":
            out = out[~((st_series == "作業中") & (end_ts.isin(["", "None", "none", "nan"])))]

    if "work_hours" in out.columns:
        out["work_hours"] = pd.to_numeric(out["work_hours"], errors="coerce").fillna(0)
    else:
        out["work_hours"] = 0.0

    anomaly = str(f.get("anomaly_filter") or "全部")
    end_ts = out.get("end_timestamp", pd.Series([""] * len(out))).fillna("").astype(str).str.strip()
    start_ts = out.get("start_timestamp", pd.Series([""] * len(out))).fillna("").astype(str).str.strip()
    start_date = out.get("start_date", pd.Series([""] * len(out))).fillna("").astype(str)
    end_date = out.get("end_date", pd.Series([""] * len(out))).fillna("").astype(str)
    if anomaly == "工時 = 0":
        out = out[out["work_hours"] == 0]
    elif anomaly == "工時小於5分鐘":
        out = out[(out["work_hours"] > 0) & (out["work_hours"] < (5 / 60))]
    elif anomaly == "工時大於8小時":
        out = out[out["work_hours"] > 8]
    elif anomaly == "工時大於12小時":
        out = out[out["work_hours"] > 12]
    elif anomaly in {"未按結束", "有開始無結束"}:
        out = out[(start_ts != "") & (end_ts.isin(["", "None", "none", "nan"]))]
    elif anomaly == "有結束無開始":
        out = out[(start_ts.isin(["", "None", "none", "nan"])) & (~end_ts.isin(["", "None", "none", "nan"]))]
    elif anomaly == "跨日紀錄":
        out = out[(start_date != "") & (end_date != "") & (start_date != end_date)]
    return out


def _sort_summary(df: pd.DataFrame, mode: str, key_col: str = "work_order") -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if mode == "製令由新到舊" and key_col in df.columns:
        return df.sort_values(key_col, ascending=False, na_position="last").reset_index(drop=True)
    if mode == "紀錄筆數" and "count" in df.columns:
        return df.sort_values("count", ascending=False, na_position="last").reset_index(drop=True)
    if mode == "平均工時" and "avg_hours" in df.columns:
        return df.sort_values("avg_hours", ascending=False, na_position="last").reset_index(drop=True)
    return df.sort_values("total_hours", ascending=False, na_position="last").reset_index(drop=True)


def _apply_top(df: pd.DataFrame, top_n: str) -> pd.DataFrame:
    if top_n == "全部":
        return df
    try:
        n = int(str(top_n).replace("Top", "").strip())
        return df.head(n)
    except Exception:
        return df.head(20)


start_saved = _parse_date(filters.get("start_date"), today_date() - timedelta(days=30))
end_saved = _parse_date(filters.get("end_date"), today_date())
base_df = _enrich_records(load_records(str(start_saved), str(end_saved)))

with st.expander("🔎 專業 BI 篩選 / Professional BI Filters", expanded=True):
    st.caption("所有條件按「套用篩選」後才重新運算，避免每點一下就卡頓；條件會永久記錄。")
    with st.form("analysis_filter_form", clear_on_submit=False):
        r1c1, r1c2, r1c3, r1c4 = st.columns([1.2, 1, 1, 1])
        preset = r1c1.selectbox("快速日期 / Quick Date", DATE_PRESETS, index=DATE_PRESETS.index(filters.get("date_preset", "近30天")) if filters.get("date_preset", "近30天") in DATE_PRESETS else 2)
        start_input = r1c2.date_input("開始日期 / Start Date", value=start_saved)
        end_input = r1c3.date_input("結束日期 / End Date", value=end_saved)
        top_n = r1c4.selectbox("Top N", TOP_OPTIONS, index=TOP_OPTIONS.index(filters.get("top_n", "Top 20")) if filters.get("top_n", "Top 20") in TOP_OPTIONS else 1)

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        selected_wo = r2c1.multiselect("製令 / Work Order", _safe_unique(base_df, "work_order", filters.get("work_orders")), default=filters.get("work_orders", []))
        selected_pn = r2c2.multiselect("P/N", _safe_unique(base_df, "part_no", filters.get("part_nos")), default=filters.get("part_nos", []))
        selected_type = r2c3.multiselect("機型 / Type", _safe_unique(base_df, "type_name", filters.get("type_names")), default=filters.get("type_names", []))
        selected_customer = r2c4.multiselect("客戶 / Customer", _safe_unique(base_df, "customer", filters.get("customers")), default=filters.get("customers", []))

        r3c1, r3c2, r3c3, r3c4 = st.columns(4)
        selected_loc = r3c1.multiselect("組立地點 / Assembly", _safe_unique(base_df, "assembly_location", filters.get("assembly_locations")), default=filters.get("assembly_locations", []))
        selected_process = r3c2.multiselect("工段名稱 / Process", _safe_unique(base_df, "process_name", filters.get("process_names")), default=filters.get("process_names", []))
        selected_emp_id = r3c3.multiselect("工號 / Employee ID", _safe_unique(base_df, "employee_id", filters.get("employee_ids")), default=filters.get("employee_ids", []))
        selected_emp_name = r3c4.multiselect("姓名 / Name", _safe_unique(base_df, "employee_name", filters.get("employee_names")), default=filters.get("employee_names", []))

        r4c1, r4c2, r4c3, r4c4 = st.columns(4)
        selected_dept = r4c1.multiselect("單位 / Department", _safe_unique(base_df, "department", filters.get("departments")), default=filters.get("departments", []))
        selected_title = r4c2.multiselect("職稱 / Title", _safe_unique(base_df, "title", filters.get("titles")), default=filters.get("titles", []))
        status_filter = r4c3.selectbox("狀態 / Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(filters.get("status_filter", "全部")) if filters.get("status_filter", "全部") in STATUS_OPTIONS else 0)
        anomaly_filter = r4c4.selectbox("異常篩選 / Exception", ANOMALY_OPTIONS, index=ANOMALY_OPTIONS.index(filters.get("anomaly_filter", "全部")) if filters.get("anomaly_filter", "全部") in ANOMALY_OPTIONS else 0)

        r5c1, r5c2, r5c3 = st.columns([1.4, 1, 1])
        sort_by = r5c1.selectbox("圖表排序 / Sort", SORT_OPTIONS, index=SORT_OPTIONS.index(filters.get("sort_by", "累積工時由大到小")) if filters.get("sort_by", "累積工時由大到小") in SORT_OPTIONS else 0)
        detail_limit = r5c2.number_input("明細讀取上限 / Detail Limit", min_value=100, max_value=20000, value=int(filters.get("detail_limit", 1000) or 1000), step=100)
        clear_filter = r5c3.checkbox("清除所有篩選 / Clear", value=False)

        apply_filter = st.form_submit_button("🔎 套用篩選並永久記錄 / Apply Filters", type="primary", use_container_width=True)

    if apply_filter:
        if clear_filter:
            new_filters = load_analysis_filters()
            new_filters.update({
                "date_preset": "近30天",
                "start_date": str(today_date() - timedelta(days=30)),
                "end_date": str(today_date()),
                "work_orders": [], "part_nos": [], "type_names": [], "customers": [], "assembly_locations": [],
                "process_names": [], "employee_ids": [], "employee_names": [], "departments": [], "titles": [],
                "status_filter": "全部", "anomaly_filter": "全部", "top_n": "Top 20", "sort_by": "累積工時由大到小", "detail_limit": 1000,
            })
        else:
            new_start, new_end = _date_range_from_preset(preset, start_input, end_input)
            new_filters = {
                "date_preset": preset,
                "start_date": str(new_start),
                "end_date": str(new_end),
                "work_orders": _clean_filter_list(selected_wo),
                "part_nos": _clean_filter_list(selected_pn),
                "type_names": _clean_filter_list(selected_type),
                "customers": _clean_filter_list(selected_customer),
                "assembly_locations": _clean_filter_list(selected_loc),
                "process_names": _clean_filter_list(selected_process),
                "employee_ids": _clean_filter_list(selected_emp_id),
                "employee_names": _clean_filter_list(selected_emp_name),
                "departments": _clean_filter_list(selected_dept),
                "titles": _clean_filter_list(selected_title),
                "status_filter": status_filter,
                "anomaly_filter": anomaly_filter,
                "top_n": top_n,
                "sort_by": sort_by,
                "detail_limit": int(detail_limit),
            }
        st.session_state[FILTER_KEY] = new_filters
        save_analysis_filters(new_filters)
        st.success("已套用並永久記錄 05 分析篩選條件。")
        st.rerun()

# 依已套用條件重新查詢與分析。
filters = dict(st.session_state[FILTER_KEY])
start = _parse_date(filters.get("start_date"), today_date() - timedelta(days=30))
end = _parse_date(filters.get("end_date"), today_date())
df = _enrich_records(load_records(str(start), str(end)))

if df.empty:
    st.info("查無工時資料 / No records")
    st.stop()

df = _apply_filters(df, filters)
if df.empty:
    st.warning("目前篩選條件下查無資料，請調整篩選條件後再套用。")
    st.stop()

if "work_hours" not in df.columns:
    df["work_hours"] = 0.0
df["work_hours"] = pd.to_numeric(df["work_hours"], errors="coerce").fillna(0)
df["work_time_text"] = df["work_hours"].map(hours_to_hms)

end_ts = df.get("end_timestamp", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
status_series = df.get("status", pd.Series([""] * len(df))).fillna("").astype(str)
unfinished_mask = (status_series == "作業中") & (end_ts.isin(["", "None", "none", "nan"]))
abnormal_mask = (df["work_hours"] == 0) | (df["work_hours"] > 12) | unfinished_mask
avg_hours = df["work_hours"].mean() if len(df) else 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("累積工時 / Total Time", hours_to_hms(df["work_hours"].sum()))
m2.metric("製令數 / Work Orders", f"{df['work_order'].nunique():,}" if "work_order" in df.columns else "0")
m3.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}" if "employee_id" in df.columns else "0")
m4.metric("工段數 / Processes", f"{df['process_name'].nunique():,}" if "process_name" in df.columns else "0")

k1, k2, k3, k4 = st.columns(4)
k1.metric("平均每筆工時 / Avg", hours_to_hms(avg_hours))
k2.metric("未結束筆數 / Unfinished", f"{int(unfinished_mask.sum()):,}")
k3.metric("異常筆數 / Exceptions", f"{int(abnormal_mask.sum()):,}")
max_wo = "-"
if "work_order" in df.columns and not df.empty:
    tmp = df.groupby("work_order", dropna=False)["work_hours"].sum().sort_values(ascending=False)
    max_wo = str(tmp.index[0]) if len(tmp) else "-"
k4.metric("最大工時製令 / Top WO", max_wo)

sort_by = filters.get("sort_by", "累積工時由大到小")
top_n = filters.get("top_n", "Top 20")

by_wo = (
    df.groupby("work_order", dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"), avg_hours=("work_hours", "mean"), employee_count=("employee_id", "nunique"), process_count=("process_name", "nunique"))
    .reset_index()
)
by_wo = _sort_summary(by_wo, sort_by, "work_order")
by_wo["工時 / Time"] = by_wo["total_hours"].map(hours_to_hms)
by_wo["平均 / Avg"] = by_wo["avg_hours"].map(hours_to_hms)

by_proc = (
    df.groupby("process_name", dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"), avg_hours=("work_hours", "mean"), employee_count=("employee_id", "nunique"), work_order_count=("work_order", "nunique"))
    .reset_index()
)
by_proc = _sort_summary(by_proc, sort_by, "process_name")
by_proc["工時 / Time"] = by_proc["total_hours"].map(hours_to_hms)
by_proc["平均 / Avg"] = by_proc["avg_hours"].map(hours_to_hms)

by_emp = (
    df.groupby(["employee_id", "employee_name", "department"], dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"), avg_hours=("work_hours", "mean"), work_order_count=("work_order", "nunique"), process_count=("process_name", "nunique"))
    .reset_index()
)
by_emp = _sort_summary(by_emp, sort_by, "employee_name")
by_emp["工時 / Time"] = by_emp["total_hours"].map(hours_to_hms)
by_emp["平均 / Avg"] = by_emp["avg_hours"].map(hours_to_hms)

trend = (
    df.groupby("start_date", dropna=False)
    .agg(total_hours=("work_hours", "sum"), count=("id", "count"), work_order_count=("work_order", "nunique"), employee_count=("employee_id", "nunique"))
    .reset_index()
    .sort_values("start_date")
)
trend["工時 / Time"] = trend["total_hours"].map(hours_to_hms)

plotly_template = "plotly_dark"


def style_fig(fig, height: int = 430):
    fig.update_layout(
        template=plotly_template,
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=60, b=80),
        font=dict(size=13),
        yaxis_title="累積時數",
    )
    fig.update_traces(marker_line_width=0.8)
    return fig


tab1, tab2, tab3, tab4, tab5 = st.tabs(["製令分析", "工段分析", "人員分析", "趨勢分析", "明細編輯"])

with tab1:
    st.subheader("製令累積工時 / Work Order Time")
    plot_df = _apply_top(by_wo, top_n)
    fig = px.bar(
        plot_df,
        x="work_order",
        y="total_hours",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "employee_count": True, "process_count": True},
        labels={"work_order": "製令 / Work Order", "total_hours": "累積時數 / Total Hours", "count": "筆數"},
        title=f"{top_n} 製令累積工時 / Work Order Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 460), use_container_width=True)
    render_table(by_wo.drop(columns=["工時 / Time", "平均 / Avg"], errors="ignore"), "analysis_by_work_order", editable=False, height=380)

with tab2:
    st.subheader("工段累積工時 / Process Time")
    plot_df = _apply_top(by_proc, top_n)
    fig = px.bar(
        plot_df,
        x="process_name",
        y="total_hours",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "employee_count": True, "work_order_count": True},
        labels={"process_name": "工段 / Process", "total_hours": "累積時數 / Total Hours", "count": "筆數"},
        title=f"{top_n} 工段累積工時 / Process Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 460), use_container_width=True)
    render_table(by_proc.drop(columns=["工時 / Time", "平均 / Avg"], errors="ignore"), "analysis_by_process", editable=False, height=380)

with tab3:
    st.subheader("人員累積工時 / Employee Time")
    plot_df = _apply_top(by_emp, top_n)
    fig = px.bar(
        plot_df,
        x="employee_name",
        y="total_hours",
        color="employee_id",
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "department": True},
        labels={"employee_name": "人員 / Employee", "total_hours": "累積時數 / Total Hours", "employee_id": "工號"},
        title=f"{top_n} 人員累積工時 / Employee Time",
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(style_fig(fig, 480), use_container_width=True)
    render_table(by_emp.drop(columns=["工時 / Time", "平均 / Avg"], errors="ignore"), "analysis_by_employee", editable=False, height=380)

with tab4:
    st.subheader("每日趨勢 / Daily Trend")
    fig = px.line(
        trend,
        x="start_date",
        y="total_hours",
        markers=True,
        text="工時 / Time",
        hover_data={"total_hours": ":.2f", "工時 / Time": True, "count": True, "work_order_count": True, "employee_count": True},
        labels={"start_date": "日期 / Date", "total_hours": "累積時數 / Total Hours"},
        title="每日累積工時趨勢 / Daily Time Trend",
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(style_fig(fig, 430), use_container_width=True)
    render_table(trend.drop(columns=["工時 / Time"], errors="ignore"), "analysis_daily_trend", editable=False, height=320)

with tab5:
    st.caption("此處編輯的是分析來源明細，儲存後會影響歷史紀錄與後續統計。工時欄位以 00:00:00 顯示，需調整時請改開始/結束時間後重新計算。")
    detail_limit = int(filters.get("detail_limit", 1000) or 1000)
    detail_df = df.head(detail_limit).drop(columns=["work_time_text"], errors="ignore")
    st.info("明細編輯採確認後才儲存；表格內輸入不會立即寫入。")
    with st.form("analysis_detail_commit_form", clear_on_submit=False):
        edited = render_table(detail_df, "analysis_detail_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at", "work_hours"], key="analysis_detail_editor", height=520)
        submitted_analysis_detail = st.form_submit_button("💾 確認儲存分析明細 / Save Detail Records", type="primary", use_container_width=True)
    if submitted_analysis_detail and edited is not None:
        count = save_time_records(edited)
        st.success(f"已儲存 {count} 筆明細。")
        st.rerun()
