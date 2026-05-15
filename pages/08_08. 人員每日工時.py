# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
import streamlit as st
import plotly.express as px

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.db_service import query_df
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms

st.set_page_config(page_title="08. 人員每日工時", page_icon="⏱️", layout="wide")
apply_theme()
require_module_access("08_daily_hours")
render_header("08｜人員每日工時", "每日應紀錄 7~7.5 小時｜支援工號、姓名、單位、職稱、狀態篩選")

STATUS_OPTIONS = ["作業中", "未紀錄", "偏低", "正常", "超時"]


def _status(total_hours, record_count, active_count) -> str:
    try:
        h = float(total_hours or 0)
    except Exception:
        h = 0.0
    try:
        cnt = int(record_count or 0)
    except Exception:
        cnt = 0
    try:
        active = int(active_count or 0)
    except Exception:
        active = 0

    if active > 0:
        return "作業中"
    if cnt == 0:
        return "未紀錄"
    if h < 7:
        return "偏低"
    if h <= 7.5:
        return "正常"
    return "超時"


def _contains_filter(series, keyword: str):
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return True
    return series.fillna("").astype(str).str.lower().str.contains(keyword, na=False)


# 先讀取單位選項，供篩選使用。只查人員主檔，不觸發工時計算。
department_options_df = query_df(
    """
    SELECT DISTINCT COALESCE(department, '') AS department
    FROM employees
    WHERE is_active=1
    ORDER BY department
    """
)
department_options = [
    str(v) for v in department_options_df.get("department", []).tolist() if str(v).strip()
]

st.info("V1.99：本頁已加入正式篩選功能；輸入工號、姓名、單位等條件後，按「套用篩選」才會查詢，避免每打一個字就運算。")

fc_a, fc_b = st.columns([1, 1])
with fc_b:
    if st.button("♻️ 清除篩選 / Reset Filters", use_container_width=True):
        for k in [
            "daily_hours_date", "daily_hours_employee_id", "daily_hours_employee_name",
            "daily_hours_departments", "daily_hours_title", "daily_hours_status",
            "daily_hours_no_record_only",
        ]:
            st.session_state.pop(k, None)
        st.rerun()

with st.expander("🔎 篩選條件 / Filters", expanded=True):
    with st.form("daily_hours_filter_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns(4)
        selected = c1.date_input("日期 / Date", value=st.session_state.get("daily_hours_date", date.today()))
        employee_id_keyword = c2.text_input("工號 / Employee ID", value=st.session_state.get("daily_hours_employee_id", ""))
        employee_name_keyword = c3.text_input("姓名 / Name", value=st.session_state.get("daily_hours_employee_name", ""))
        selected_departments = c4.multiselect(
            "單位 / Department",
            department_options,
            default=st.session_state.get("daily_hours_departments", []),
        )

        c5, c6, c7, c8 = st.columns(4)
        title_keyword = c5.text_input("職稱 / Title", value=st.session_state.get("daily_hours_title", ""))
        selected_status = c6.multiselect(
            "狀態 / Status",
            STATUS_OPTIONS,
            default=st.session_state.get("daily_hours_status", []),
        )
        show_only_no_record = c7.checkbox(
            "只看未紀錄 / No Record Only",
            value=bool(st.session_state.get("daily_hours_no_record_only", False)),
        )
        submitted = c8.form_submit_button("🔎 套用篩選 / Apply", use_container_width=True)

        if submitted:
            st.session_state["daily_hours_date"] = selected
            st.session_state["daily_hours_employee_id"] = employee_id_keyword
            st.session_state["daily_hours_employee_name"] = employee_name_keyword
            st.session_state["daily_hours_departments"] = selected_departments
            st.session_state["daily_hours_title"] = title_keyword
            st.session_state["daily_hours_status"] = selected_status
            st.session_state["daily_hours_no_record_only"] = show_only_no_record

# 以 session_state 的條件為準；避免使用者輸入到一半就立即改查詢。
selected = st.session_state.get("daily_hours_date", date.today())
employee_id_keyword = st.session_state.get("daily_hours_employee_id", "")
employee_name_keyword = st.session_state.get("daily_hours_employee_name", "")
selected_departments = st.session_state.get("daily_hours_departments", [])
title_keyword = st.session_state.get("daily_hours_title", "")
selected_status = st.session_state.get("daily_hours_status", [])
show_only_no_record = bool(st.session_state.get("daily_hours_no_record_only", False))

d = selected.strftime("%Y-%m-%d")

base_df = query_df(
    """
    SELECT e.employee_id, e.employee_name, e.department, e.title,
           COALESCE(SUM(t.work_hours), 0) AS total_hours,
           COUNT(t.id) AS record_count,
           SUM(CASE WHEN t.end_timestamp IS NULL THEN 1 ELSE 0 END) AS active_count
    FROM employees e
    LEFT JOIN time_records t
      ON e.employee_id=t.employee_id AND t.start_date=?
    WHERE e.is_active=1 AND e.is_in_factory=1 AND e.is_today_attendance=1
    GROUP BY e.employee_id, e.employee_name, e.department, e.title
    ORDER BY total_hours ASC, e.employee_id
    """,
    (d,),
)

if not base_df.empty:
    base_df["status"] = base_df.apply(
        lambda r: _status(r["total_hours"], r["record_count"], r["active_count"]), axis=1
    )
    base_df["累積工時 / Total Time"] = base_df["total_hours"].map(hours_to_hms)

    df = base_df.copy()
    if employee_id_keyword.strip():
        df = df[_contains_filter(df["employee_id"], employee_id_keyword)]
    if employee_name_keyword.strip():
        df = df[_contains_filter(df["employee_name"], employee_name_keyword)]
    if selected_departments:
        df = df[df["department"].fillna("").astype(str).isin(selected_departments)]
    if title_keyword.strip():
        df = df[_contains_filter(df["title"], title_keyword)]
    if selected_status:
        df = df[df["status"].isin(selected_status)]
    if show_only_no_record:
        df = df[df["status"] == "未紀錄"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("符合人數 / Filtered", f"{len(df):,}")
    c2.metric("原始出勤在廠 / Attendance", f"{len(base_df):,}")
    c3.metric("累積工時 / Total Time", hours_to_hms(df["total_hours"].sum() if not df.empty else 0))
    c4.metric("未紀錄 / No Record", f"{(df['status']=='未紀錄').sum() if not df.empty else 0:,}")
    c5.metric("偏低 / Low", f"{(df['status']=='偏低').sum() if not df.empty else 0:,}")

    if df.empty:
        st.warning("目前篩選條件沒有符合資料，請放寬工號、姓名、單位或狀態條件。")
    else:
        st.subheader("工時分布 / Time Distribution")
        chart_df = df.copy()
        fig = px.bar(
            chart_df.sort_values("total_hours", ascending=False),
            x="employee_name",
            y="total_hours",
            color="status",
            hover_data={
                "employee_id": True,
                "department": True,
                "title": True,
                "record_count": True,
                "active_count": True,
                "total_hours": ":.2f",
                "累積工時 / Total Time": True,
            },
            labels={"employee_name": "人員", "total_hours": "累積時數", "status": "狀態"},
            title="人員每日累積工時 / Daily Employee Time",
        )
        fig.update_layout(
            template="plotly_dark",
            height=420,
            margin=dict(l=20, r=20, t=60, b=80),
            yaxis_title="累積時數",
            xaxis_title="人員",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    df = base_df
    st.info("目前沒有符合條件的人員資料 / No employee data")

render_table(df, "daily_employee_hours", editable=False, height=620)
