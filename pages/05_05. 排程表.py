from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from services.capacity_engine import (
    ASSEMBLY_EXCLUSION_PARAM_KEY,
    ASSEMBLY_LOCATION_HOURS_PARAM_KEY,
    CATEGORY_EXCLUSION_PARAM_KEY,
    calculate_capacity_by_years,
    prepare_schedule,
    recalculate_schedule_demand,
    upsert_capacity_results,
    validate_schedule,
)
from services.data_loader import clear_data_cache, load_table
from services.page_utils import SELECT_COL, render_configurable_view, render_module_report_download
from services.persistent_store import load_parameters, save_authority_df
from services.ui_theme import apply_tech_theme, render_hero, render_human_help
from services.year_service import DEFAULT_YEAR, available_years_from_frames, ensure_year_column, normalize_year

st.set_page_config(page_title="05. 排程表", page_icon="🗓️", layout="wide")
apply_tech_theme()
render_hero("05. 排程表", "訂單、WO、客戶、P/N、月份、台數與標準工時；查詢結果可直接穩定編輯、刪除、儲存並串聯產能。")
render_human_help([
    "排程表已合併『穩定編輯模式』與『日期區間明細查詢』：先選日期區間，再直接在查詢結果內編輯或刪除。",
    "『需求工時』是系統計算欄位，儲存時會自動重算：需求工時 = 台數 × 標準工時。",
    "每月機台數會依官方 Excel 排程表 J 欄『台數』的月份標記計算，例如 J 欄為 6月 的筆數就是 6月機台數。",
    "若標準工時空白，系統會優先依 06. 標準工時主檔補齊，再重新計算需求工時。",
    "若 06. 標準工時設定排除組立地點，需求工時 = 台數 × 該組立地點調整工時/台；若調整工時/台未設定或為 0，需求工時 = 0。若設定排除 Category，該筆排程需求工時保留但機台計數歸 0。",
    "按『儲存查詢結果並重新計算』後會同步更新 04. 產能負荷表的系統計算結果，09. 情境模擬也會讀取最新排程。",
])

ROW_ID_COL = "_row_id"
SCHEDULE_STATE_KEY = "schedule_query_edit_working_df"
SCHEDULE_SIGNATURE_KEY = "schedule_query_edit_source_signature"
SCHEDULE_WINDOW_KEY = "schedule_query_edit_window"
SCHEDULE_LAST_QUERY_KEY = "schedule_query_edit_last_detail"


def _frame_for_compare(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Return a stable, comparable frame for one schedule year."""
    if df is None or df.empty:
        return pd.DataFrame()
    temp = ensure_year_column("schedule", df.copy(), DEFAULT_YEAR)
    temp["年份"] = temp["年份"].map(lambda value: normalize_year(value, DEFAULT_YEAR))
    temp = temp[temp["年份"].eq(int(year))].copy()
    if temp.empty:
        return pd.DataFrame()
    temp = temp.drop(columns=[SELECT_COL, ROW_ID_COL], errors="ignore")
    cols = sorted([str(c) for c in temp.columns])
    temp = temp.reindex(columns=cols)
    temp = temp.fillna("").astype(str)
    return temp.sort_values(cols).reset_index(drop=True)


def _changed_schedule_years(old_df: pd.DataFrame, new_df: pd.DataFrame) -> list[int]:
    """Detect which years actually changed, so save does not recalculate all years."""
    old_norm = ensure_year_column("schedule", old_df.copy() if old_df is not None else pd.DataFrame(), DEFAULT_YEAR)
    new_norm = ensure_year_column("schedule", new_df.copy() if new_df is not None else pd.DataFrame(), DEFAULT_YEAR)
    old_years = set(old_norm["年份"].map(lambda value: normalize_year(value, DEFAULT_YEAR)).dropna().astype(int).tolist()) if "年份" in old_norm.columns else set()
    new_years = set(new_norm["年份"].map(lambda value: normalize_year(value, DEFAULT_YEAR)).dropna().astype(int).tolist()) if "年份" in new_norm.columns else set()
    changed: list[int] = []
    for year in sorted(old_years | new_years):
        old_part = _frame_for_compare(old_norm, int(year))
        new_part = _frame_for_compare(new_norm, int(year))
        if old_part.shape != new_part.shape or not old_part.equals(new_part):
            changed.append(int(year))
    return changed


def _schedule_detail_date_columns(df: pd.DataFrame) -> list[str]:
    """Find real schedule date columns for date-range detail lookup."""
    if df is None or df.empty:
        return []
    preferred_order = ["機台入庫日", "MOVE IN", "排程日期", "入庫日", "出貨日", "交期", "預計完成日", "完成日", "日期"]
    allowed_tokens = ["日期", "入庫日", "出貨日", "交期", "完成日", "move in", "movein", "date"]
    excluded = {"年份", "月份", "M", "台數", "台數_raw", "機台計數", "PO", "工期", "標準工時", "需求工時"}
    found: list[str] = []
    for col in df.columns:
        col_text = str(col).strip()
        if col_text in excluded or col_text.startswith("_"):
            continue
        norm = col_text.lower().replace(" ", "")
        is_candidate = col_text in preferred_order or any(token in col_text for token in allowed_tokens) or any(token in norm for token in allowed_tokens)
        if not is_candidate:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        if int(parsed.notna().sum()) > 0:
            found.append(col_text)
    ordered = [col for col in preferred_order if col in found]
    ordered += [col for col in found if col not in ordered]
    return ordered


def _format_detail_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the detail table readable without changing the source data."""
    out = df.copy()
    integer_like = ["年份", "台數", "機台計數"]
    for col in integer_like:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(0).astype("Int64")
    for col in ["標準工時", "需求工時", "工期"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(0).astype("Int64")
    return out


def _normalize_month_label(value: object) -> str | None:
    """Normalize schedule month values into labels like '7月'."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            month = int(value)
        except Exception:
            month = 0
        if 1 <= month <= 12:
            return f"{month}月"
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    compact = text.replace("月", "").strip()
    if compact.isdigit():
        month = int(compact)
        if 1 <= month <= 12:
            return f"{month}月"
    date_value = pd.to_datetime(text, errors="coerce")
    if pd.notna(date_value):
        return f"{int(date_value.month)}月"
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        month = int(digits)
    except Exception:
        return None
    if 1 <= month <= 12:
        return f"{month}月"
    return None


def _month_sort_key(label: object) -> int:
    normalized = _normalize_month_label(label)
    if not normalized:
        return 99
    return int(str(normalized).replace("月", ""))


def _available_month_labels(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty or "月份" not in df.columns:
        return []
    labels = [label for label in df["月份"].map(_normalize_month_label).dropna().unique().tolist() if label]
    return sorted(labels, key=_month_sort_key)


def _build_monthly_demand_chart_frame(prepared: pd.DataFrame, machine_col: str, selected_year: int) -> tuple[pd.DataFrame, int]:
    """Build a clean 1~12 month chart frame for monthly demand hours.

    The schedule table may contain legacy month values such as 0, None, 未設定, or text
    that sorts alphabetically.  The chart must show only real months in calendar order.
    """
    month_order = [f"{m}月" for m in range(1, 13)]
    if prepared is None or prepared.empty:
        empty = pd.DataFrame({
            "年份": [int(selected_year)] * 12,
            "年份顯示": [str(int(selected_year))] * 12,
            "月別數字": list(range(1, 13)),
            "月份": month_order,
            "機台數": [0.0] * 12,
            "需求工時": [0.0] * 12,
        })
        return empty, 0

    temp = prepared.copy()
    temp["月別數字"] = temp.get("月份", pd.Series(dtype=object)).map(_month_sort_key)
    invalid_count = int((pd.to_numeric(temp["月別數字"], errors="coerce").fillna(99).astype(int) > 12).sum())
    temp = temp[pd.to_numeric(temp["月別數字"], errors="coerce").between(1, 12)].copy()

    if temp.empty:
        empty = pd.DataFrame({
            "年份": [int(selected_year)] * 12,
            "年份顯示": [str(int(selected_year))] * 12,
            "月別數字": list(range(1, 13)),
            "月份": month_order,
            "機台數": [0.0] * 12,
            "需求工時": [0.0] * 12,
        })
        return empty, invalid_count

    if "年份" not in temp.columns:
        temp["年份"] = int(selected_year)
    temp["年份"] = temp["年份"].map(lambda value: normalize_year(value, selected_year)).fillna(int(selected_year)).astype(int)
    temp["月別數字"] = pd.to_numeric(temp["月別數字"], errors="coerce").fillna(0).astype(int)
    temp["需求工時"] = pd.to_numeric(temp.get("需求工時", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    temp[machine_col] = pd.to_numeric(temp.get(machine_col, pd.Series(dtype=float)), errors="coerce").fillna(0.0)

    monthly = (
        temp.groupby(["年份", "月別數字"], as_index=False)
        .agg(機台數=(machine_col, "sum"), 需求工時=("需求工時", "sum"))
    )

    # Fill missing calendar months with 0 so the x-axis always stays 1月~12月.
    completed_frames: list[pd.DataFrame] = []
    years_to_show = sorted(monthly["年份"].dropna().astype(int).unique().tolist()) or [int(selected_year)]
    for year in years_to_show:
        base = pd.DataFrame({"年份": [int(year)] * 12, "月別數字": list(range(1, 13))})
        merged = base.merge(monthly, on=["年份", "月別數字"], how="left")
        completed_frames.append(merged)
    monthly = pd.concat(completed_frames, ignore_index=True) if completed_frames else monthly
    monthly["機台數"] = pd.to_numeric(monthly.get("機台數", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    monthly["需求工時"] = pd.to_numeric(monthly.get("需求工時", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    monthly["月份"] = monthly["月別數字"].map(lambda value: f"{int(value)}月")
    monthly["年份顯示"] = monthly["年份"].map(lambda value: str(int(value)))
    monthly = monthly.sort_values(["年份", "月別數字"]).reset_index(drop=True)
    return monthly, invalid_count


def _default_one_month_range(df: pd.DataFrame, date_col: str | None, selected_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return a one-month default date range for analysis filters."""
    today = pd.Timestamp.today().normalize()
    fallback_start = pd.Timestamp(int(selected_year), 1, 1)
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not dates.empty:
            year_dates = dates[dates.dt.year.eq(int(selected_year))]
            if not year_dates.empty:
                current_month = year_dates[(year_dates.dt.year.eq(today.year)) & (year_dates.dt.month.eq(today.month))]
                if not current_month.empty:
                    start = pd.Timestamp(today.year, today.month, 1)
                else:
                    start = pd.Timestamp(year_dates.min().year, year_dates.min().month, 1)
                end = start + pd.offsets.MonthEnd(0)
                return start, end
    month_labels = _available_month_labels(df)
    if month_labels:
        first_month = _month_sort_key(month_labels[0])
        fallback_start = pd.Timestamp(int(selected_year), int(first_month), 1)
    return fallback_start, fallback_start + pd.offsets.MonthEnd(0)


def _format_date_caption(start_ts: pd.Timestamp | None, end_ts: pd.Timestamp | None) -> str:
    if start_ts is None or end_ts is None:
        return "未套用日期區間"
    return f"{start_ts.strftime('%Y/%m/%d')} ~ {end_ts.strftime('%Y/%m/%d')}"



def _build_assembly_location_analysis_frame(prepared: pd.DataFrame, selected_month: str = "全部") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate scheduled machine allocation and demand hours by assembly location.

    This is a read-only analysis helper.  It does not change schedule values or the
    underlying calculation rules.  The persisted source column remains ``組立地點``;
    the analysis display name is ``組裝地點`` for clearer management reporting.
    """
    if prepared is None or prepared.empty or "組立地點" not in prepared.columns:
        return pd.DataFrame(), pd.DataFrame()

    detail = prepared.copy()
    if selected_month != "全部" and "月份" in detail.columns:
        detail = detail[detail["月份"].map(_normalize_month_label).eq(selected_month)].copy()
    if detail.empty:
        return pd.DataFrame(), detail

    detail["組裝地點"] = (
        detail["組立地點"]
        .fillna("未設定")
        .astype(str)
        .str.strip()
        .replace({"": "未設定", "nan": "未設定", "None": "未設定"})
    )
    machine_source = "機台計數" if "機台計數" in detail.columns else "台數"
    detail["_analysis_machine_count"] = pd.to_numeric(detail.get(machine_source, 0), errors="coerce").fillna(0.0)
    detail["_analysis_demand_hours"] = pd.to_numeric(detail.get("需求工時", 0), errors="coerce").fillna(0.0)

    if "Category" not in detail.columns:
        detail["Category"] = "未分類"
    detail["Category"] = detail["Category"].fillna("未分類").astype(str).str.strip().replace("", "未分類")

    if "產能計算排除" in detail.columns:
        excluded_flag = detail["產能計算排除"].fillna("").astype(str).str.strip().str.lower()
        detail["_analysis_excluded"] = excluded_flag.isin({"是", "yes", "y", "true", "1"})
    else:
        detail["_analysis_excluded"] = False

    summary = (
        detail.groupby("組裝地點", as_index=False)
        .agg(
            排程筆數=("組裝地點", "size"),
            機台數=("_analysis_machine_count", "sum"),
            需求工時=("_analysis_demand_hours", "sum"),
            Category數=("Category", "nunique"),
            排除筆數=("_analysis_excluded", "sum"),
        )
    )
    total_machines = float(summary["機台數"].sum()) if not summary.empty else 0.0
    total_hours = float(summary["需求工時"].sum()) if not summary.empty else 0.0
    summary["平均工時/台"] = summary.apply(
        lambda row: float(row["需求工時"]) / float(row["機台數"]) if float(row["機台數"]) > 0 else 0.0,
        axis=1,
    )
    summary["機台占比(%)"] = summary["機台數"].map(lambda value: float(value) / total_machines * 100.0 if total_machines > 0 else 0.0)
    summary["工時占比(%)"] = summary["需求工時"].map(lambda value: float(value) / total_hours * 100.0 if total_hours > 0 else 0.0)
    summary = summary[
        ["組裝地點", "排程筆數", "Category數", "機台數", "需求工時", "平均工時/台", "機台占比(%)", "工時占比(%)", "排除筆數"]
    ].sort_values(["需求工時", "機台數", "排程筆數"], ascending=[False, False, False]).reset_index(drop=True)
    return summary, detail


def _render_assembly_location_allocation_analysis(prepared: pd.DataFrame, selected_year: int) -> dict[str, pd.DataFrame]:
    """Render professional assembly-location allocation table and dual-axis chart."""
    st.subheader("組裝地點機台配置與需求工時分析")
    st.markdown(
        """
        <div class="stable-editor-card">
          <b>分析目的：掌握各組裝地點承接的機台配置量與需求工時</b><br/>
          <span class="small-muted">本區直接讀取 05 排程表已計算完成的機台計數與需求工時，只做統計分析，不修改排程、標準工時或 04 產能負荷計算。底層資料欄位仍維持「組立地點」。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if prepared is None or prepared.empty:
        st.info(f"目前沒有 {selected_year} 年可分析的排程資料。")
        return {"assembly_location_summary": pd.DataFrame(), "assembly_location_detail": pd.DataFrame()}
    if "組立地點" not in prepared.columns:
        st.warning("目前排程資料沒有『組立地點』欄位，因此無法產生組裝地點配置分析。")
        return {"assembly_location_summary": pd.DataFrame(), "assembly_location_detail": pd.DataFrame()}

    month_options = ["全部"] + _available_month_labels(prepared)
    filter_cols = st.columns([1.1, 1.1, 1.2, 3.0])
    with filter_cols[0]:
        selected_month = st.selectbox(
            "分析月份",
            month_options,
            index=0,
            key=f"schedule_assembly_location_month_{selected_year}",
            help="選擇全部或單一月份，分析各組裝地點的機台與需求工時配置。",
        )
    with filter_cols[1]:
        sort_metric = st.selectbox(
            "圖表排序",
            ["需求工時", "機台數", "平均工時/台"],
            index=0,
            key=f"schedule_assembly_location_sort_{selected_year}",
        )
    with filter_cols[2]:
        selected_top_n = st.selectbox(
            "圖表顯示地點數",
            [8, 10, 15, 20, "全部"],
            index=2,
            key=f"schedule_assembly_location_topn_{selected_year}",
        )
        top_n = 9999 if selected_top_n == "全部" else int(selected_top_n)
    with filter_cols[3]:
        st.info("機台數採『機台計數』欄位；需求工時採目前 05 已重算結果。排除設定造成的 0 台或 0 工時會如實反映。", icon="📊")

    summary, detail = _build_assembly_location_analysis_frame(prepared, selected_month)
    if summary.empty:
        st.info(f"{selected_year} 年 {selected_month}目前沒有可分析的組裝地點資料。")
        return {"assembly_location_summary": summary, "assembly_location_detail": detail}

    total_machines = float(pd.to_numeric(summary["機台數"], errors="coerce").fillna(0).sum())
    total_hours = float(pd.to_numeric(summary["需求工時"], errors="coerce").fillna(0).sum())
    avg_hours_per_machine = total_hours / total_machines if total_machines > 0 else 0.0
    busiest_location = str(summary.sort_values(["需求工時", "機台數"], ascending=False).iloc[0]["組裝地點"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("組裝地點數", f"{summary['組裝地點'].nunique():,} 處")
    m2.metric("分配機台數", f"{total_machines:,.0f} 台")
    m3.metric("需求工時", f"{total_hours:,.0f} h")
    m4.metric("平均工時/台", f"{avg_hours_per_machine:,.1f} h", help=f"需求工時最高地點：{busiest_location}")
    st.caption(f"分析範圍：{selected_year} 年｜月份：{selected_month}｜需求工時最高配置地點：{busiest_location}")

    display_summary = summary.copy()
    display_summary["排程筆數"] = pd.to_numeric(display_summary["排程筆數"], errors="coerce").fillna(0).round(0).astype("Int64")
    display_summary["Category數"] = pd.to_numeric(display_summary["Category數"], errors="coerce").fillna(0).round(0).astype("Int64")
    display_summary["機台數"] = pd.to_numeric(display_summary["機台數"], errors="coerce").fillna(0).round(0).astype("Int64")
    display_summary["需求工時"] = pd.to_numeric(display_summary["需求工時"], errors="coerce").fillna(0).round(0).astype("Int64")
    display_summary["平均工時/台"] = pd.to_numeric(display_summary["平均工時/台"], errors="coerce").fillna(0).round(1)
    display_summary["機台占比(%)"] = pd.to_numeric(display_summary["機台占比(%)"], errors="coerce").fillna(0).round(1)
    display_summary["工時占比(%)"] = pd.to_numeric(display_summary["工時占比(%)"], errors="coerce").fillna(0).round(1)
    display_summary["排除筆數"] = pd.to_numeric(display_summary["排除筆數"], errors="coerce").fillna(0).round(0).astype("Int64")
    render_configurable_view(display_summary, "schedule_assembly_location_allocation_summary", "組裝地點機台配置與需求工時分析表", height=390)

    chart_df = summary.sort_values([sort_metric, "需求工時", "機台數"], ascending=False).head(top_n).copy()
    chart_df = chart_df.sort_values(sort_metric, ascending=False).reset_index(drop=True)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=chart_df["組裝地點"],
            y=chart_df["機台數"],
            name="分配機台數",
            text=chart_df["機台數"].map(lambda value: f"{float(value):,.0f}"),
            textposition="outside",
            hovertemplate="組裝地點：%{x}<br>分配機台數：%{y:,.0f} 台<extra></extra>",
            marker_line_width=0,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["組裝地點"],
            y=chart_df["需求工時"],
            name="需求工時",
            mode="lines+markers+text",
            text=chart_df["需求工時"].map(lambda value: f"{float(value):,.0f}"),
            textposition="top center",
            hovertemplate="組裝地點：%{x}<br>需求工時：%{y:,.0f} h<extra></extra>",
            line={"width": 3},
            marker={"size": 9, "line": {"width": 1}},
        ),
        secondary_y=True,
    )
    fig.update_layout(
        template="plotly_dark",
        title=f"{selected_year} 年 {selected_month}組裝地點機台與工時配置",
        height=500,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 45, "r": 55, "t": 90, "b": 80},
        xaxis={"title": "組裝地點", "tickangle": -25, "categoryorder": "array", "categoryarray": chart_df["組裝地點"].tolist()},
        bargap=0.35,
    )
    fig.update_yaxes(title_text="分配機台數（台）", tickformat=",.0f", rangemode="tozero", secondary_y=False)
    fig.update_yaxes(title_text="需求工時（h）", tickformat=",.0f", rangemode="tozero", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)

    export_detail = detail.drop(columns=["_analysis_machine_count", "_analysis_demand_hours", "_analysis_excluded"], errors="ignore")
    return {"assembly_location_summary": display_summary, "assembly_location_detail": export_detail}

def _render_category_machine_count_analysis(
    schedule_df: pd.DataFrame,
    standard: pd.DataFrame,
    prepared_current_year: pd.DataFrame,
    years: list[int],
    selected_year: int,
    excluded_assembly_locations: list[str],
    excluded_categories: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Render Category machine-count analysis with explicit year/month/date filters."""
    st.subheader("05 排程表 Category 機台計數 >= 1 統計與分析")
    st.markdown(
        """
        <div class="stable-editor-card">
          <b>統計篩選條件：年度 / 月份 / 日期區間</b><br/>
          <span class="small-muted">可依年度、月份、日期欄位、開始日期與結束日期篩選後顯示統計。預設會帶入所選年度第一個有資料月份的一個月區間；此區只改變畫面統計，不會寫入 05 排程表，也不會觸發 04 重新計算。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    year_options = sorted({int(y) for y in years}) if years else [int(selected_year)]
    default_year_index = year_options.index(int(selected_year)) if int(selected_year) in year_options else len(year_options) - 1

    filter_cols = st.columns([0.85, 0.85, 1.25, 1.0, 1.0])
    with filter_cols[0]:
        selected_analysis_year = int(
            st.selectbox(
                "統計年度",
                year_options,
                index=default_year_index,
                key="schedule_category_analysis_year_v2",
                help="選擇要統計的排程年度。",
            )
        )

    if int(selected_analysis_year) == int(selected_year):
        year_base = prepared_current_year.copy() if isinstance(prepared_current_year, pd.DataFrame) else pd.DataFrame()
    else:
        year_base = prepare_schedule(
            schedule_df,
            standard,
            target_year=selected_analysis_year,
            excluded_assembly_locations=excluded_assembly_locations,
            excluded_categories=excluded_categories,
            assembly_location_hours=assembly_location_hours,
        )
    if year_base is None:
        year_base = pd.DataFrame()

    year_date_columns = _schedule_detail_date_columns(year_base)
    date_col_options = year_date_columns or ["無日期欄位"]
    preferred_date_col = "機台入庫日" if "機台入庫日" in year_date_columns else (year_date_columns[0] if year_date_columns else "無日期欄位")
    with filter_cols[2]:
        selected_date_col = st.selectbox(
            "日期欄位",
            date_col_options,
            index=date_col_options.index(preferred_date_col),
            key=f"schedule_category_date_col_v2_{selected_analysis_year}",
            help="選擇要用來判斷日期區間的欄位，例如機台入庫日或 MOVE IN。",
        )
    if selected_date_col == "無日期欄位":
        selected_date_col = None

    one_month_start, one_month_end = _default_one_month_range(year_base, selected_date_col, selected_analysis_year)
    month_options = ["全部"] + _available_month_labels(year_base)
    default_month = _normalize_month_label(one_month_start.month)
    default_month_index = month_options.index(default_month) if default_month in month_options else 0
    with filter_cols[1]:
        selected_month = st.selectbox(
            "統計月份",
            month_options,
            index=default_month_index,
            key=f"schedule_category_month_v2_{selected_analysis_year}",
            help="選擇月份後，統計會同時套用月份條件；日期區間仍可進一步縮小範圍。",
        )

    if selected_month != "全部":
        month_number = _month_sort_key(selected_month)
        month_start = pd.Timestamp(int(selected_analysis_year), int(month_number), 1)
        month_end = month_start + pd.offsets.MonthEnd(0)
        default_start_date = month_start.date()
        default_end_date = month_end.date()
    else:
        default_start_date = one_month_start.date()
        default_end_date = one_month_end.date()

    date_key_suffix = f"{selected_analysis_year}_{selected_month}_{selected_date_col or 'none'}".replace("/", "_").replace(" ", "_")
    with filter_cols[3]:
        start_date = st.date_input(
            "開始日期",
            value=default_start_date,
            key=f"schedule_category_start_v2_{date_key_suffix}",
        )
    with filter_cols[4]:
        end_date = st.date_input(
            "結束日期",
            value=default_end_date,
            key=f"schedule_category_end_v2_{date_key_suffix}",
        )

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts
    end_ts_inclusive = end_ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    st.caption(
        f"目前已套用：統計年度 {selected_analysis_year}｜統計月份 {selected_month}｜日期欄位 {selected_date_col or '無'}｜日期區間 {_format_date_caption(start_ts, end_ts)}"
    )

    if year_base.empty:
        st.info(f"目前沒有 {selected_analysis_year} 年可分析排程資料。")
        return {"category_summary": pd.DataFrame(), "category_detail": pd.DataFrame()}

    analysis_df = year_base.copy()
    if "月份" in analysis_df.columns and selected_month != "全部":
        analysis_df = analysis_df[analysis_df["月份"].map(_normalize_month_label).eq(selected_month)].copy()

    if selected_date_col and selected_date_col in analysis_df.columns:
        parsed_dates = pd.to_datetime(analysis_df[selected_date_col], errors="coerce")
        analysis_df = analysis_df[parsed_dates.ge(start_ts) & parsed_dates.le(end_ts_inclusive)].copy()

    machine_col = "機台計數" if "機台計數" in analysis_df.columns else "台數"
    analysis_df["_machine_count_for_category"] = pd.to_numeric(analysis_df.get(machine_col, 0), errors="coerce").fillna(0)
    if "需求工時" not in analysis_df.columns:
        analysis_df["需求工時"] = 0
    if "Category" not in analysis_df.columns:
        analysis_df["Category"] = "未分類"
    analysis_df["Category"] = analysis_df["Category"].fillna("未分類").astype(str).str.strip().replace("", "未分類")

    included = analysis_df[analysis_df["_machine_count_for_category"].ge(1)].copy()
    excluded_count = int(len(analysis_df) - len(included))
    total_machine_count = float(included["_machine_count_for_category"].sum()) if not included.empty else 0.0
    total_demand_hours = float(pd.to_numeric(included.get("需求工時", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not included.empty else 0.0
    category_count = int(included["Category"].nunique()) if not included.empty else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("統計排程筆數", f"{len(included):,} 筆")
    m2.metric("Category 數", f"{category_count:,} 類")
    m3.metric("機台計數合計", f"{total_machine_count:,.0f} 台")
    m4.metric("需求工時合計", f"{total_demand_hours:,.0f} h")
    st.caption(f"目前條件：年度 {selected_analysis_year}｜月份 {selected_month}｜日期 {_format_date_caption(start_ts, end_ts)}｜已排除機台計數 < 1 的資料 {excluded_count:,} 筆。")

    if included.empty:
        st.info("目前篩選條件下沒有機台計數 >= 1 的 Category 資料。")
        return {"category_summary": pd.DataFrame(), "category_detail": pd.DataFrame()}

    category_summary = (
        included.groupby("Category", as_index=False)
        .agg(
            排程筆數=("Category", "size"),
            機台計數=("_machine_count_for_category", "sum"),
            需求工時=("需求工時", "sum"),
        )
        .sort_values(["機台計數", "需求工時", "排程筆數"], ascending=[False, False, False])
        .reset_index(drop=True)
    )

    chart_df = category_summary.head(20).copy()
    fig = px.bar(chart_df, y="Category", x="機台計數", orientation="h", title="Category 機台計數 >= 1 統計", hover_data=["排程筆數", "需求工時"])
    fig.update_layout(template="plotly_dark", height=max(380, min(720, 260 + len(chart_df) * 22)), yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

    render_configurable_view(_format_detail_numbers(category_summary), "schedule_category_ge1_summary", "Category 機台計數 >= 1 統計表", height=320)

    detail_cols = [
        "年份",
        selected_date_col,
        "月份",
        "WO",
        "客戶",
        "P/N",
        "Type",
        "Category",
        "組立地點",
        "台數",
        "機台計數",
        "標準工時",
        "需求工時",
        "產能計算排除",
        "工時計算排除",
        "台數計算排除",
        "產能計算排除原因",
    ]
    detail_cols = [col for col in detail_cols if col and col in included.columns]
    detail_df = included.drop(columns=["_machine_count_for_category"], errors="ignore").reindex(columns=detail_cols + [c for c in included.columns if c not in detail_cols and c != "_machine_count_for_category"])
    render_configurable_view(_format_detail_numbers(detail_df), "schedule_category_ge1_detail", "Category 機台計數 >= 1 明細", height=360)
    return {"category_summary": category_summary, "category_detail": detail_df}

def _schedule_source_signature(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "empty"
    temp = df.copy().drop(columns=[SELECT_COL, ROW_ID_COL], errors="ignore")
    temp = temp.fillna("").astype(str)
    return f"{temp.shape}-{int(pd.util.hash_pandas_object(temp, index=True).sum())}"


def _initial_schedule_working_df(source_df: pd.DataFrame) -> pd.DataFrame:
    df = source_df.copy() if isinstance(source_df, pd.DataFrame) else pd.DataFrame()
    if SELECT_COL in df.columns:
        df = df.drop(columns=[SELECT_COL])
    if ROW_ID_COL in df.columns:
        df = df.drop(columns=[ROW_ID_COL])
    df = df.reset_index(drop=True)
    df.insert(0, ROW_ID_COL, range(len(df)))
    df.insert(0, SELECT_COL, False)
    return df


def _get_schedule_working_df(source_df: pd.DataFrame) -> pd.DataFrame:
    """Keep an editable working copy for query editing without losing non-visible rows."""
    signature = _schedule_source_signature(source_df)
    if SCHEDULE_STATE_KEY not in st.session_state or SCHEDULE_SIGNATURE_KEY not in st.session_state:
        st.session_state[SCHEDULE_STATE_KEY] = _initial_schedule_working_df(source_df)
        st.session_state[SCHEDULE_SIGNATURE_KEY] = signature
    return st.session_state[SCHEDULE_STATE_KEY].copy()


def _reset_schedule_working_df(df: pd.DataFrame) -> None:
    st.session_state[SCHEDULE_STATE_KEY] = _initial_schedule_working_df(df)
    st.session_state[SCHEDULE_SIGNATURE_KEY] = _schedule_source_signature(df)


def _schedule_column_config() -> dict[str, object]:
    config: dict[str, object] = {
        SELECT_COL: st.column_config.CheckboxColumn("刪除", help="勾選後可按『刪除勾選並儲存』永久刪除。"),
        ROW_ID_COL: None,
        "年份": st.column_config.NumberColumn("年份", min_value=2000, max_value=2100, step=1, format="%d", help="用於多年度比較。"),
        "月份": st.column_config.TextColumn("月份", help="可填 1月~12月，系統會自動標準化。"),
        "台數": st.column_config.NumberColumn("台數", min_value=0.0, step=1.0, format="%.0f", help="需求工時 = 台數 × 標準工時。"),
        "機台計數": st.column_config.NumberColumn("機台計數", min_value=0.0, step=1.0, format="%.0f", help="系統欄位：每月機台數使用此欄彙總。"),
        "標準工時": st.column_config.NumberColumn("標準工時", min_value=0.0, step=0.1, format="%g", help="可手動填；空白時系統會從 06. 標準工時補齊。"),
        "需求工時": st.column_config.NumberColumn("需求工時", min_value=0.0, step=0.1, format="%g", help="系統欄位：儲存時自動重算為 台數 × 標準工時。"),
        "產能計算排除": st.column_config.TextColumn("產能計算排除", help="系統欄位：由 06. 標準工時的組立地點與 Category 排除設定決定。"),
        "工時計算排除": st.column_config.TextColumn("工時計算排除", help="系統欄位：組立地點排除時為是；需求工時歸 0，但機台計數保留。"),
        "台數計算排除": st.column_config.TextColumn("台數計算排除", help="系統欄位：Category 排除時為是；機台計數歸 0，但需求工時保留。"),
        "產能計算排除原因": st.column_config.TextColumn("產能計算排除原因", help="系統欄位：說明排除原因與影響欄位。"),
    }
    return config


def _preferred_schedule_columns(df: pd.DataFrame) -> list[str]:
    preferred = [
        SELECT_COL,
        ROW_ID_COL,
        "年份",
        "機台入庫日",
        "月份",
        "WO",
        "客戶",
        "P/N",
        "Type",
        "Category",
        "組立地點",
        "台數_raw",
        "台數",
        "機台計數",
        "標準工時",
        "需求工時",
        "產能計算排除",
        "工時計算排除",
        "台數計算排除",
        "產能計算排除原因",
        "排除前機台計數",
        "排除前需求工時",
        "工期",
        "PO",
    ]
    ordered = [c for c in preferred if c in df.columns]
    ordered += [c for c in df.columns if c not in ordered]
    return ordered


def _render_query_controls(working_df: pd.DataFrame, selected_year: int) -> tuple[pd.DataFrame, str | None, pd.Timestamp | None, pd.Timestamp | None]:
    st.subheader("排程查詢與穩定編輯")
    st.markdown(
        """
        <div class="stable-editor-card">
          <b>排程表穩定編輯模式 + 日期區間明細查詢</b><br/>
          <span class="small-muted">先查詢年/月/日～年/月/日區間，再直接在查詢結果中編輯、刪除、儲存；系統只在按儲存後重新計算並同步 04/09。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if working_df.empty:
        return working_df.copy(), None, None, None

    df = ensure_year_column("schedule", working_df.copy(), DEFAULT_YEAR)
    df["_year_norm"] = df["年份"].map(lambda value: normalize_year(value, DEFAULT_YEAR))
    year_df = df[df["_year_norm"].eq(int(selected_year))].copy()
    if year_df.empty:
        st.info(f"目前沒有 {selected_year} 年排程資料。可按『新增空白列到查詢年度』建立新資料。")
        return year_df.drop(columns=["_year_norm"], errors="ignore"), None, None, None

    date_columns = _schedule_detail_date_columns(year_df.drop(columns=[ROW_ID_COL, SELECT_COL, "_year_norm"], errors="ignore"))
    date_col: str | None = None
    start_ts: pd.Timestamp | None = None
    end_ts: pd.Timestamp | None = None
    keyword = ""
    only_show_no_date = False

    with st.form("schedule_query_filter_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns([1.25, 1, 1, 1.5])
        if date_columns:
            default_col_index = date_columns.index("機台入庫日") if "機台入庫日" in date_columns else 0
            with c1:
                date_col = st.selectbox("日期欄位", date_columns, index=default_col_index, key="schedule_query_date_col")
            parsed = pd.to_datetime(year_df[date_col], errors="coerce")
            valid_dates = parsed.dropna()
            min_date = valid_dates.min().date() if not valid_dates.empty else pd.Timestamp.today().date()
            max_date = valid_dates.max().date() if not valid_dates.empty else pd.Timestamp.today().date()
            with c2:
                start_date = st.date_input("開始日期", value=min_date, key=f"schedule_query_start_{date_col}")
            with c3:
                end_date = st.date_input("結束日期", value=max_date, key=f"schedule_query_end_{date_col}")
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            start_ts = pd.Timestamp(start_date)
            end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        else:
            with c1:
                st.warning("找不到可辨識日期欄位，暫時顯示整年度資料。")
            with c2:
                start_ts = None
            with c3:
                end_ts = None
        with c4:
            keyword = st.text_input("關鍵字（WO / 客戶 / P/N，可空白）", value="", key="schedule_query_keyword")
        d1, d2, d3 = st.columns([1.2, 1.2, 3.6])
        with d1:
            only_show_no_date = st.checkbox("只看日期空白", value=False, key="schedule_query_only_blank_date") if date_col else False
        with d2:
            st.form_submit_button("套用查詢條件", type="primary", use_container_width=True)
        with d3:
            st.info("查詢本身不寫入資料；查詢結果表格按『儲存查詢結果並重新計算』後才會更新 05 並同步 04. 產能負荷表。", icon="🔎")

    filtered = year_df.copy()
    if date_col:
        parsed = pd.to_datetime(filtered[date_col], errors="coerce")
        if only_show_no_date:
            filtered = filtered[parsed.isna()].copy()
        elif start_ts is not None and end_ts is not None:
            filtered = filtered[parsed.ge(start_ts) & parsed.le(end_ts)].copy()
    keyword = str(keyword or "").strip()
    if keyword:
        search_cols = [c for c in ["WO", "客戶", "P/N", "Type", "Category", "PO"] if c in filtered.columns]
        if search_cols:
            joined = filtered[search_cols].fillna("").astype(str).agg(" ".join, axis=1)
            filtered = filtered[joined.str.contains(keyword, case=False, na=False, regex=False)].copy()
    filtered = filtered.drop(columns=["_year_norm"], errors="ignore")
    if date_col and date_col in filtered.columns:
        sort_cols = [date_col]
        if "WO" in filtered.columns:
            sort_cols.append("WO")
        filtered = filtered.sort_values(sort_cols, kind="stable")
    return filtered, date_col, start_ts, end_ts


def _current_query_default_for_new_row(selected_year: int, working_df: pd.DataFrame) -> tuple[str | None, pd.Timestamp]:
    """Use current query date settings to make a new row immediately visible in the query editor."""
    date_col = st.session_state.get("schedule_query_date_col")
    if not date_col or date_col not in working_df.columns:
        candidates = _schedule_detail_date_columns(working_df.drop(columns=[ROW_ID_COL, SELECT_COL], errors="ignore"))
        date_col = candidates[0] if candidates else None

    date_value = None
    if date_col:
        # 新增空白列時優先使用目前查詢結束日，讓列排序後出現在查詢結果尾端，較容易看見。
        date_value = st.session_state.get(f"schedule_query_end_{date_col}")
        if date_value is None:
            date_value = st.session_state.get(f"schedule_query_start_{date_col}")
    try:
        date_ts = pd.Timestamp(date_value)
        if pd.isna(date_ts):
            raise ValueError("empty date")
    except Exception:
        date_ts = pd.Timestamp(int(selected_year), 1, 1)
    return date_col, date_ts


def _render_window_controls(total_rows: int) -> tuple[int, int]:
    if total_rows <= 0:
        return 0, 0
    state = st.session_state.get(SCHEDULE_WINDOW_KEY, {"start": 0, "size": 80})
    size_options = [30, 50, 80, 120, 200, 500]
    try:
        size = int(state.get("size", 80))
    except Exception:
        size = 80
    if size not in size_options:
        size = 80
    try:
        start = int(state.get("start", 0))
    except Exception:
        start = 0
    start = max(0, min(start, max(total_rows - 1, 0)))

    c0, c1, c2, c3, c4 = st.columns([1.1, 1.2, 1, 1, 2.2])
    with c0:
        size = st.selectbox("每次顯示筆數", size_options, index=size_options.index(size), key="schedule_query_page_size")
    with c1:
        row_number = st.number_input("跳到查詢結果第幾筆", min_value=1, max_value=max(total_rows, 1), value=min(start + 1, max(total_rows, 1)), step=1, key="schedule_query_row_number")
    if c2.button("上一段", key="schedule_query_prev", use_container_width=True):
        start = max(0, start - int(size))
    if c3.button("下一段", key="schedule_query_next", use_container_width=True):
        start = min(max(total_rows - 1, 0), start + int(size))
    jump_start = max(0, min(int(row_number) - 1, max(total_rows - 1, 0)))
    if jump_start != start and st.session_state.get("schedule_query_row_number_last") != int(row_number):
        start = jump_start
    st.session_state["schedule_query_row_number_last"] = int(row_number)
    end = min(start + int(size), total_rows)
    with c4:
        st.info(f"目前顯示查詢結果第 {start + 1:,} ～ {end:,} 筆，共 {total_rows:,} 筆。", icon="📍")
    st.session_state[SCHEDULE_WINDOW_KEY] = {"start": int(start), "size": int(size)}
    return int(start), int(end)


def _set_schedule_selection_by_row_ids(row_ids: list[int], selected: bool) -> int:
    """Set delete checkbox state in the working copy without writing authority data."""
    if SCHEDULE_STATE_KEY not in st.session_state:
        return 0
    latest_working = st.session_state[SCHEDULE_STATE_KEY].copy()
    if latest_working.empty or ROW_ID_COL not in latest_working.columns:
        return 0
    if SELECT_COL not in latest_working.columns:
        latest_working[SELECT_COL] = False
    normalized_ids = pd.to_numeric(pd.Series(row_ids), errors="coerce").dropna().astype(int).tolist()
    if not normalized_ids:
        return 0
    row_id_series = pd.to_numeric(latest_working[ROW_ID_COL], errors="coerce")
    mask = row_id_series.isin(normalized_ids)
    latest_working.loc[mask, SELECT_COL] = bool(selected)
    st.session_state[SCHEDULE_STATE_KEY] = latest_working
    return int(mask.sum())


def _clear_all_schedule_selection() -> int:
    """Clear all temporary delete selections in the working copy."""
    if SCHEDULE_STATE_KEY not in st.session_state:
        return 0
    latest_working = st.session_state[SCHEDULE_STATE_KEY].copy()
    if latest_working.empty:
        return 0
    if SELECT_COL not in latest_working.columns:
        latest_working[SELECT_COL] = False
        st.session_state[SCHEDULE_STATE_KEY] = latest_working
        return 0
    selected_count = int(latest_working[SELECT_COL].fillna(False).astype(bool).sum())
    latest_working[SELECT_COL] = False
    st.session_state[SCHEDULE_STATE_KEY] = latest_working
    return selected_count


def _count_schedule_selection(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or SELECT_COL not in df.columns:
        return 0
    return int(df[SELECT_COL].fillna(False).astype(bool).sum())


def _render_bulk_delete_selection_controls(filtered: pd.DataFrame, working_df: pd.DataFrame) -> None:
    """Render select-all / clear-all controls for delete checkboxes."""
    if filtered is None or filtered.empty or ROW_ID_COL not in filtered.columns:
        return
    query_selected_count = _count_schedule_selection(filtered)
    total_selected_count = _count_schedule_selection(working_df)
    row_ids = pd.to_numeric(filtered[ROW_ID_COL], errors="coerce").dropna().astype(int).tolist()

    st.markdown(
        """
        <div class="stable-editor-card">
          <b>批次刪除勾選</b><br/>
          <span class="small-muted">全選只會勾選目前查詢條件下的資料，不會立即刪除；必須再按「刪除勾選並儲存」才會正式刪除並重新計算。取消全部勾選會清除目前編輯暫存內所有刪除勾選。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    b1, b2, b3 = st.columns([1.2, 1.2, 3.2])
    with b1:
        if st.button("全選目前查詢結果", key="schedule_select_all_filtered_for_delete", use_container_width=True):
            count = _set_schedule_selection_by_row_ids(row_ids, True)
            st.success(f"已勾選目前查詢結果 {count:,} 筆；請再按『刪除勾選並儲存』才會正式刪除。")
            st.rerun()
    with b2:
        if st.button("取消全部勾選", key="schedule_clear_all_delete_selection", use_container_width=True):
            count = _clear_all_schedule_selection()
            st.success(f"已取消 {count:,} 筆刪除勾選。")
            st.rerun()
    with b3:
        st.info(
            f"目前查詢結果已勾選 {query_selected_count:,} 筆；全部暫存資料共已勾選 {total_selected_count:,} 筆。按刪除前仍可在表格內逐筆取消。",
            icon="☑️",
        )


def _sync_capacity_results(recalculated_schedule: pd.DataFrame) -> None:
    """Recalculate and persist only affected 04 capacity years after schedule save."""
    try:
        changed_years = st.session_state.pop("schedule_changed_years_for_capacity", None)
        if not changed_years:
            st.info("排程資料已保存；系統未偵測到年度內容差異，因此略過 04. 產能負荷表重算。", icon="⚡")
            return

        standard = load_table("standard_hours")
        work_calendar = load_table("work_calendar")
        employees = load_table("employees")
        dispatch = load_table("dispatch")
        adjustments = load_table("capacity_adjustments")
        existing_results = load_table("capacity_results")
        params = load_parameters()

        calculated = calculate_capacity_by_years(
            recalculated_schedule,
            standard,
            work_calendar,
            employees,
            dispatch,
            params,
            adjustments=adjustments,
            years=[int(y) for y in changed_years],
        )
        merged = upsert_capacity_results(existing_results, calculated)
        save_authority_df("capacity_results", merged, user="schedule_save_recalculate_capacity")
        st.success(f"已同步重算 04. 產能負荷表：{', '.join(str(y) for y in changed_years)} 年。")
    except Exception as exc:
        # 排程本身仍可保存；同步失敗時讓使用者知道需回 04 手動重算。
        st.warning(f"排程已保存，但同步 04. 產能負荷表時計算失敗，請至 04 按重新計算。原因：{exc}")


def _save_schedule_working_df(working_df: pd.DataFrame, old_schedule: pd.DataFrame, standard: pd.DataFrame, *, user: str) -> pd.DataFrame:
    clean = working_df.copy().drop(columns=[SELECT_COL, ROW_ID_COL], errors="ignore")
    clean = clean.dropna(how="all")
    params = load_parameters()
    recalculated = recalculate_schedule_demand(
        clean,
        standard_hours=standard,
        target_year=None,
        excluded_assembly_locations=params.get(ASSEMBLY_EXCLUSION_PARAM_KEY, []),
        excluded_categories=params.get(CATEGORY_EXCLUSION_PARAM_KEY, []),
        assembly_location_hours=params.get(ASSEMBLY_LOCATION_HOURS_PARAM_KEY, {}),
    )
    st.session_state["schedule_changed_years_for_capacity"] = _changed_schedule_years(old_schedule, recalculated)
    save_authority_df("schedule", recalculated, user=user)
    _sync_capacity_results(recalculated)
    clear_data_cache()
    for _key in list(st.session_state.keys()):
        if str(_key).endswith("_prepared_bytes") or str(_key).endswith("_prepared_name"):
            del st.session_state[_key]
    _reset_schedule_working_df(recalculated)
    return recalculated


def _render_schedule_query_editor(source_df: pd.DataFrame, standard: pd.DataFrame, selected_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    old_schedule = source_df.copy() if isinstance(source_df, pd.DataFrame) else pd.DataFrame()
    working_df = _get_schedule_working_df(old_schedule)

    action_cols = st.columns([1.2, 1.2, 1.4, 3.2])
    if action_cols[0].button("新增空白列到查詢年度", key="schedule_query_add_row", use_container_width=True):
        new_df = st.session_state[SCHEDULE_STATE_KEY].copy()
        if new_df.empty:
            base_cols = [SELECT_COL, ROW_ID_COL, "年份", "機台入庫日", "月份", "WO", "客戶", "P/N", "Type", "Category", "台數_raw", "台數", "機台計數", "標準工時", "需求工時"]
            new_df = pd.DataFrame(columns=base_cols)
        next_id = int(pd.to_numeric(new_df.get(ROW_ID_COL, pd.Series([-1])), errors="coerce").fillna(-1).max()) + 1 if not new_df.empty else 0
        blank = {col: None for col in new_df.columns}
        blank[SELECT_COL] = False
        blank[ROW_ID_COL] = next_id
        blank["年份"] = int(selected_year)

        # 讓新增列直接落在目前查詢區間內，不會因日期篩選而看不到。
        date_col, date_ts = _current_query_default_for_new_row(int(selected_year), new_df)
        if date_col:
            if date_col not in new_df.columns:
                new_df[date_col] = None
                blank[date_col] = None
            blank[date_col] = date_ts.date()
            st.session_state[f"schedule_query_start_{date_col}"] = date_ts.date()
            existing_end = st.session_state.get(f"schedule_query_end_{date_col}", date_ts.date())
            try:
                end_date = pd.Timestamp(existing_end).date()
            except Exception:
                end_date = date_ts.date()
            if end_date < date_ts.date():
                end_date = date_ts.date()
            st.session_state[f"schedule_query_end_{date_col}"] = end_date
        blank["月份"] = f"{int(date_ts.month)}月"
        if "台數" in new_df.columns:
            blank["台數"] = 0
        if "機台計數" in new_df.columns:
            blank["機台計數"] = 0
        if "標準工時" in new_df.columns:
            blank["標準工時"] = 0
        if "需求工時" in new_df.columns:
            blank["需求工時"] = 0

        # 清除會把空白新增列排除掉的查詢條件。
        if "schedule_query_keyword" in st.session_state:
            st.session_state["schedule_query_keyword"] = ""
        if "schedule_query_only_blank_date" in st.session_state:
            st.session_state["schedule_query_only_blank_date"] = False

        new_df.loc[len(new_df)] = blank
        st.session_state[SCHEDULE_STATE_KEY] = new_df
        st.session_state[SCHEDULE_WINDOW_KEY] = {"start": max(len(new_df) - 1, 0), "size": st.session_state.get(SCHEDULE_WINDOW_KEY, {}).get("size", 80)}
        st.success("已新增空白列到目前查詢年度與日期區間；請在查詢結果內編輯後按儲存。")
        st.rerun()
    if action_cols[1].button("重新載入權威資料", key="schedule_query_reload", use_container_width=True):
        _reset_schedule_working_df(old_schedule)
        st.success("已重新載入目前權威排程資料。")
        st.rerun()
    with action_cols[2]:
        st.caption("編輯中不會即時寫入。")
    with action_cols[3]:
        st.info("若你剛從 10 匯入或其他頁面更新排程，可按『重新載入權威資料』同步畫面暫存。", icon="🔄")

    working_df = st.session_state[SCHEDULE_STATE_KEY].copy()
    filtered, date_col, start_ts, end_ts = _render_query_controls(working_df, selected_year)

    if filtered.empty:
        st.info("目前查詢條件下沒有排程明細。")
        st.session_state[SCHEDULE_LAST_QUERY_KEY] = pd.DataFrame()
        return working_df.drop(columns=[SELECT_COL, ROW_ID_COL], errors="ignore"), pd.DataFrame()

    # 批次勾選刪除只更新畫面暫存，不會寫入權威資料；正式刪除仍需按「刪除勾選並儲存」。
    _render_bulk_delete_selection_controls(filtered, st.session_state[SCHEDULE_STATE_KEY])

    total_machines = float(pd.to_numeric(filtered.get("機台計數", filtered.get("台數", pd.Series(dtype=float))), errors="coerce").fillna(0).sum())
    total_hours = float(pd.to_numeric(filtered.get("需求工時", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    customer_count = int(filtered["客戶"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()) if "客戶" in filtered.columns else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("查詢明細筆數", f"{len(filtered):,} 筆")
    m2.metric("查詢機台數", f"{total_machines:,.0f} 台")
    m3.metric("查詢需求工時", f"{total_hours:,.0f} h")
    m4.metric("客戶數", f"{customer_count:,} 家")

    window_start, window_end = _render_window_controls(len(filtered))
    visible = filtered.iloc[window_start:window_end].copy()
    visible = visible.reindex(columns=_preferred_schedule_columns(visible))

    disabled_columns = [ROW_ID_COL]
    for system_col in ["需求工時", "機台計數", "標準工時來源", "產能計算排除", "工時計算排除", "台數計算排除", "產能計算排除原因", "排除前機台計數", "排除前需求工時"]:
        if system_col in visible.columns:
            disabled_columns.append(system_col)

    editor_key = f"schedule_query_editor_{selected_year}_{window_start}_{window_end}"
    save_clicked = False
    delete_clicked = False
    edited = visible.copy()
    with st.form(key=f"form_{editor_key}", clear_on_submit=False):
        st.caption("固定游標編輯：表格內連續輸入不會每格重新整理；按下方按鈕後才儲存、刪除、重新計算並同步 04/09。")
        edited = st.data_editor(
            visible,
            use_container_width=True,
            height=560,
            num_rows="fixed",
            key=editor_key,
            column_config=_schedule_column_config(),
            disabled=disabled_columns,
            hide_index=True,
        )
        s1, s2, s3 = st.columns([1.35, 1.35, 3.3])
        with s1:
            save_clicked = st.form_submit_button("儲存查詢結果並重新計算", type="primary", use_container_width=True)
        with s2:
            delete_clicked = st.form_submit_button("刪除勾選並儲存", use_container_width=True)
        with s3:
            st.info("儲存後：05 排程表權威資料更新 → 需求工時重算 → 04 產能負荷表重算 → 09 情境模擬讀取最新資料。", icon="✅")

    if ROW_ID_COL not in edited.columns and ROW_ID_COL in visible.columns:
        edited = edited.copy()
        edited[ROW_ID_COL] = visible[ROW_ID_COL].to_numpy()

    if save_clicked or delete_clicked:
        latest_working = st.session_state[SCHEDULE_STATE_KEY].copy()
        if ROW_ID_COL not in edited.columns:
            st.error("系統列識別欄位遺失，請重新載入權威資料後再試。")
        else:
            for _, row in edited.iterrows():
                row_id = row.get(ROW_ID_COL)
                try:
                    row_id_int = int(row_id)
                except Exception:
                    continue
                target_idx = latest_working.index[pd.to_numeric(latest_working[ROW_ID_COL], errors="coerce").eq(row_id_int)]
                if len(target_idx) == 0:
                    continue
                idx = target_idx[0]
                for col in edited.columns:
                    if col == ROW_ID_COL:
                        continue
                    if col not in latest_working.columns:
                        latest_working[col] = None
                    latest_working.loc[idx, col] = row[col]

            deleted_count = 0
            if delete_clicked:
                selected_ids = []
                if SELECT_COL in latest_working.columns:
                    selected_mask = latest_working[SELECT_COL].fillna(False).astype(bool)
                    selected_ids = pd.to_numeric(latest_working.loc[selected_mask, ROW_ID_COL], errors="coerce").dropna().astype(int).tolist()
                if selected_ids:
                    latest_working = latest_working[~pd.to_numeric(latest_working[ROW_ID_COL], errors="coerce").isin(selected_ids)].reset_index(drop=True)
                    deleted_count = len(selected_ids)
                else:
                    st.warning("目前尚未勾選要刪除的資料。")

            st.session_state[SCHEDULE_STATE_KEY] = latest_working
            saved = _save_schedule_working_df(latest_working, old_schedule, standard, user="schedule_query_editor_save")
            if delete_clicked:
                st.success(f"已刪除 {deleted_count:,} 筆查詢結果勾選資料，並已重新計算 05 與同步更新 04. 產能負荷表。")
            else:
                st.success("已儲存目前查詢結果修改，並已重新計算 05 與同步更新 04. 產能負荷表。")
            st.session_state[SCHEDULE_LAST_QUERY_KEY] = pd.DataFrame()
            return saved, pd.DataFrame()

    detail_for_export = edited.copy().drop(columns=[ROW_ID_COL, SELECT_COL], errors="ignore")
    if date_col and date_col in detail_for_export.columns:
        detail_for_export[date_col] = pd.to_datetime(detail_for_export[date_col], errors="coerce").dt.strftime("%Y/%m/%d")
    detail_for_export = _format_detail_numbers(detail_for_export)
    st.session_state[SCHEDULE_LAST_QUERY_KEY] = detail_for_export
    return working_df.drop(columns=[SELECT_COL, ROW_ID_COL], errors="ignore"), detail_for_export


raw_schedule = load_table("schedule")
standard = load_table("standard_hours")
params = load_parameters()
excluded_assembly_locations = params.get(ASSEMBLY_EXCLUSION_PARAM_KEY, [])
excluded_categories = params.get(CATEGORY_EXCLUSION_PARAM_KEY, [])
assembly_location_hours = params.get(ASSEMBLY_LOCATION_HOURS_PARAM_KEY, {})
years = available_years_from_frames([raw_schedule, standard])
selected_year = st.selectbox("顯示/分析年份", years, index=len(years) - 1, key="schedule_year_filter")

schedule, query_detail = _render_schedule_query_editor(raw_schedule, standard, int(selected_year))
prepared = prepare_schedule(
    schedule,
    standard,
    target_year=selected_year,
    excluded_assembly_locations=excluded_assembly_locations,
    excluded_categories=excluded_categories,
    assembly_location_hours=assembly_location_hours,
)

c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
with c1:
    if st.button("重新計算需求工時", type="primary", key="recalc_schedule_demand_preview"):
        old_schedule = load_table("schedule")
        recalculated = recalculate_schedule_demand(
            schedule,
            standard_hours=standard,
            target_year=None,
            excluded_assembly_locations=excluded_assembly_locations,
            excluded_categories=excluded_categories,
            assembly_location_hours=assembly_location_hours,
        )
        st.session_state["schedule_changed_years_for_capacity"] = _changed_schedule_years(old_schedule, recalculated)
        save_authority_df("schedule", recalculated, user="manual_recalculate_schedule_demand")
        _sync_capacity_results(recalculated)
        clear_data_cache()
        _reset_schedule_working_df(recalculated)
        st.success("已重新計算排程需求工時，並已同步更新 04. 產能負荷表計算結果。")
        st.rerun()
with c2:
    missing_std = int((pd.to_numeric(prepared.get("標準工時", pd.Series(dtype=float)), errors="coerce").fillna(0) <= 0).sum()) if not prepared.empty else 0
    st.metric("標準工時缺漏", f"{missing_std} 筆")
with c3:
    total_hours = float(pd.to_numeric(prepared.get("需求工時", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not prepared.empty else 0.0
    st.metric("年度需求工時", f"{total_hours:,.0f} h")
with c4:
    st.info("重新計算按鈕可在不進入 04 的情況下，直接將排程變更串聯到產能負荷與情境模擬。", icon="🔄")

st.subheader("排程資料品質")
checks = validate_schedule(prepared, excluded_assembly_locations=excluded_assembly_locations, excluded_categories=excluded_categories)
render_configurable_view(checks, "schedule_quality", "05. 排程資料品質", height=260)

if not prepared.empty:
    c1, c2 = st.columns([1, 1])
    with c1:
        machine_col = "機台計數" if "機台計數" in prepared.columns else "台數"
        monthly, invalid_month_count = _build_monthly_demand_chart_frame(prepared, machine_col, int(selected_year))
        if invalid_month_count > 0:
            st.caption(f"已排除 {invalid_month_count:,} 筆無效月份資料（例如 0、空白、未設定），圖表只顯示 1月~12月。")
        fig = px.bar(
            monthly,
            x="月份",
            y="需求工時",
            title=f"{selected_year}年月別訂單需求工時",
            category_orders={"月份": [f"{m}月" for m in range(1, 13)]},
            custom_data=["機台數", "年份顯示"],
            labels={"需求工時": "需求工時", "月份": "月份", "年份顯示": "年份"},
        )
        fig.update_traces(
            hovertemplate="月份：%{x}<br>需求工時：%{y:,.0f} h<br>機台數：%{customdata[0]:,.0f} 台<extra></extra>"
        )
        fig.update_layout(
            template="plotly_dark",
            height=380,
            xaxis={"categoryorder": "array", "categoryarray": [f"{m}月" for m in range(1, 13)]},
            yaxis={"tickformat": ",.0f", "title": "需求工時"},
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        if "客戶" in prepared.columns:
            customer = prepared.groupby("客戶", as_index=False).agg(需求工時=("需求工時", "sum")).sort_values("需求工時", ascending=False).head(15)
            fig2 = px.bar(customer, y="客戶", x="需求工時", orientation="h", title="客戶需求工時 Top 15")
            fig2.update_layout(template="plotly_dark", height=380)
            st.plotly_chart(fig2, use_container_width=True)

assembly_location_analysis = _render_assembly_location_allocation_analysis(prepared, int(selected_year))

category_analysis = _render_category_machine_count_analysis(
    schedule,
    standard,
    prepared,
    years,
    int(selected_year),
    excluded_assembly_locations,
    excluded_categories,
)

st.subheader(f"{selected_year}年排程分析匯出")
render_module_report_download(
    "05.排程表",
    {
        "排程權威資料": schedule,
        "排程計算結果": prepared,
        "查詢編輯區明細": query_detail,
        "組裝地點配置分析": assembly_location_analysis.get("assembly_location_summary", pd.DataFrame()),
        "組裝地點配置明細": assembly_location_analysis.get("assembly_location_detail", pd.DataFrame()),
        "Category 機台計數>=1統計": category_analysis.get("category_summary", pd.DataFrame()),
        "Category 機台計數>=1明細": category_analysis.get("category_detail", pd.DataFrame()),
        "資料品質": checks,
    },
    chart_specs=[
        {
            "type": "bar",
            "data_sheet": "組裝地點配置分析",
            "category_col": "組裝地點",
            "value_cols": ["機台數"],
            "title": f"{selected_year}年組裝地點機台配置",
            "anchor": "A7",
        },
        {
            "type": "line",
            "data_sheet": "組裝地點配置分析",
            "category_col": "組裝地點",
            "value_cols": ["需求工時"],
            "title": f"{selected_year}年組裝地點需求工時",
            "anchor": "J7",
        },
    ],
    metadata={
        "計算規則": "需求工時 = 台數 × 標準工時；每月機台數 = 排程表 J 欄台數/月別標記計數；標準工時空白時由 06. 標準工時主檔補齊；06 組立地點排除時需求工時 = 台數 × 組立地點調整工時/台，未設定則為 0；06 Category 排除時機台計數歸 0 但需求工時保留。",
        "組裝地點分析口徑": "依 05 排程表組立地點彙總機台計數與需求工時；僅供分析，不修改原排程與計算。",
        "分析年份": selected_year,
    },
    label="匯出 05. 排程表完整 Excel",
    key="export_schedule_module_report",
)
