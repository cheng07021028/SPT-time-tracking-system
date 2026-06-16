from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MONTH_ORDER = [f"{i}月" for i in range(1, 13)]


def _to_float(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def normalize_month(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "未設定"
    text = str(value).strip()
    if text.endswith("月"):
        return text
    try:
        num = int(float(text))
        if 1 <= num <= 12:
            return f"{num}月"
    except Exception:
        pass
    return text


def prepare_schedule(schedule: pd.DataFrame, standard_hours: pd.DataFrame | None = None) -> pd.DataFrame:
    if schedule is None or schedule.empty:
        return pd.DataFrame(columns=["月份", "台數", "標準工時", "需求工時"])
    df = schedule.copy()
    if "M" in df.columns and "月份" not in df.columns:
        df = df.rename(columns={"M": "月份"})
    if "月份" not in df.columns:
        df["月份"] = df.get("台數_raw", "未設定")
    df["月份"] = df["月份"].map(normalize_month)
    if "台數" not in df.columns:
        df["台數"] = 1
    df["台數"] = _to_float(df["台數"], 1).clip(lower=0)
    if "標準工時" not in df.columns:
        df["標準工時"] = np.nan
    df["標準工時"] = _to_float(df["標準工時"], np.nan)
    if standard_hours is not None and not standard_hours.empty and df["標準工時"].isna().any():
        keys = [k for k in ["客戶", "P/N", "Type"] if k in df.columns and k in standard_hours.columns]
        if keys and "標準工時" in standard_hours.columns:
            lookup_cols = keys + ["標準工時"]
            lookup = standard_hours[lookup_cols].dropna(subset=["標準工時"]).drop_duplicates(keys)
            df = df.merge(lookup, on=keys, how="left", suffixes=("", "_lookup"))
            df["標準工時"] = df["標準工時"].fillna(df.get("標準工時_lookup"))
            if "標準工時_lookup" in df.columns:
                df = df.drop(columns=["標準工時_lookup"])
    df["標準工時"] = _to_float(df["標準工時"], 0)
    df["需求工時"] = df["台數"] * df["標準工時"]
    return df


def summarize_manpower(employees: pd.DataFrame, dispatch: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for source, df in [("超慧正職", employees), ("派遣/外包", dispatch)]:
        if df is None or df.empty:
            continue
        temp = df.copy()
        if "啟用" in temp.columns:
            active = temp["啟用"].fillna("是").astype(str).str.strip()
            temp = temp[~active.isin(["否", "N", "n", "False", "false", "0", "停用", "離場"])]
        temp["人力來源"] = temp.get("人力來源", source)
        if "是否直接人力" not in temp.columns:
            temp["是否直接人力"] = "是"
        if "可用比例" not in temp.columns:
            temp["可用比例"] = np.where(temp["是否直接人力"].eq("是"), 1.0, 0.0)
        temp["可用比例"] = _to_float(temp["可用比例"], 1.0)
        temp["有效人力"] = np.where(temp["是否直接人力"].astype(str).eq("是"), temp["可用比例"], 0)
        frames.append(temp)
    if not frames:
        return pd.DataFrame(columns=["課別", "工段", "人力來源", "總人數", "直接人力", "有效人力"])
    all_people = pd.concat(frames, ignore_index=True)
    for col in ["課別", "工段", "人力來源"]:
        if col not in all_people.columns:
            all_people[col] = "未設定"
        all_people[col] = all_people[col].fillna("未設定").astype(str).str.strip().replace("", "未設定")
    result = all_people.groupby(["課別", "工段", "人力來源"], as_index=False).agg(
        總人數=("姓名", "count"),
        直接人力=("是否直接人力", lambda s: (s.astype(str) == "是").sum()),
        有效人力=("有效人力", "sum"),
    )
    return result.sort_values(["課別", "工段", "人力來源"])


def calculate_capacity(
    schedule: pd.DataFrame,
    standard_hours: pd.DataFrame,
    work_calendar: pd.DataFrame,
    employees: pd.DataFrame,
    dispatch: pd.DataFrame,
    params: dict[str, Any],
    adjustments: pd.DataFrame | None = None,
) -> pd.DataFrame:
    schedule2 = prepare_schedule(schedule, standard_hours)
    demand = schedule2.groupby("月份", as_index=False).agg(
        每月機台數=("台數", "sum"),
        需求總工時=("需求工時", "sum"),
        工單筆數=("需求工時", "size"),
    )
    if work_calendar is None or work_calendar.empty:
        work_calendar = pd.DataFrame({"月份": MONTH_ORDER, "正常工作日": [21] * 12, "週六天數": [4] * 12, "週日天數": [4] * 12, "法定假日": [0] * 12})
    calendar = work_calendar.copy()
    calendar["月份"] = calendar["月份"].map(normalize_month)
    for col in ["正常工作日", "週六天數", "週日天數", "法定假日"]:
        if col not in calendar.columns:
            calendar[col] = 0
        calendar[col] = _to_float(calendar[col], 0)

    manpower_summary = summarize_manpower(employees, dispatch)
    effective_people = float(manpower_summary["有效人力"].sum()) if not manpower_summary.empty else 0.0
    if bool(params.get("use_direct_people_override", False)):
        effective_people = float(params.get("direct_people_override", effective_people))

    daily_hours = float(params.get("daily_hours", 7.0))
    efficiency = float(params.get("efficiency", 1.0))
    weekday_ot_hours = float(params.get("weekday_overtime_hours", 2.0))
    sat_ot_hours = float(params.get("saturday_overtime_hours", 7.0))
    sun_ot_hours = float(params.get("sunday_overtime_hours", 7.0))
    holiday_ot_hours = float(params.get("holiday_overtime_hours", 7.0))
    weekday_ot_ratio = float(params.get("weekday_overtime_ratio", 0.3))
    holiday_ot_ratio = float(params.get("holiday_overtime_ratio", 0.3))

    calendar["直接有效人力"] = effective_people
    calendar["正常可用工時"] = effective_people * calendar["正常工作日"] * daily_hours * efficiency
    calendar["平日加班工時"] = effective_people * weekday_ot_ratio * calendar["正常工作日"] * weekday_ot_hours * efficiency
    calendar["週六加班工時"] = effective_people * holiday_ot_ratio * calendar["週六天數"] * sat_ot_hours * efficiency
    calendar["週日加班工時"] = effective_people * holiday_ot_ratio * calendar["週日天數"] * sun_ot_hours * efficiency
    calendar["法定假日加班工時"] = effective_people * holiday_ot_ratio * calendar["法定假日"] * holiday_ot_hours * efficiency
    calendar["含加班可用工時"] = calendar[["正常可用工時", "平日加班工時", "週六加班工時", "週日加班工時", "法定假日加班工時"]].sum(axis=1)

    result = pd.DataFrame({"月份": MONTH_ORDER}).merge(calendar, on="月份", how="left").merge(demand, on="月份", how="left")
    for col in ["每月機台數", "需求總工時", "工單筆數"]:
        result[col] = _to_float(result[col], 0)

    # Manual monthly adjustment hours are persisted in 04. 產能負荷表.
    # They are added to demand hours before utilization, manpower gap, and load are calculated.
    result["原始需求工時"] = result["需求總工時"]
    result["調整工時"] = 0.0
    if adjustments is not None and not adjustments.empty:
        adj = adjustments.copy()
        if "月份" in adj.columns and "調整工時" in adj.columns:
            adj["月份"] = adj["月份"].map(normalize_month)
            adj["調整工時"] = _to_float(adj["調整工時"], 0)
            adj_sum = adj.groupby("月份", as_index=False).agg(調整工時=("調整工時", "sum"))
            result = result.merge(adj_sum, on="月份", how="left", suffixes=("", "_手動"))
            result["調整工時"] = _to_float(result.get("調整工時_手動", result["調整工時"]), 0)
            if "調整工時_手動" in result.columns:
                result = result.drop(columns=["調整工時_手動"])
    result["需求總工時"] = result["原始需求工時"] + result["調整工時"]

    result["正常產能負荷"] = result["正常可用工時"] - result["需求總工時"]
    result["含加班產能負荷"] = result["含加班可用工時"] - result["需求總工時"]
    result["正常稼動率"] = np.where(result["正常可用工時"] > 0, result["需求總工時"] / result["正常可用工時"], 0)
    result["含加班稼動率"] = np.where(result["含加班可用工時"] > 0, result["需求總工時"] / result["含加班可用工時"], 0)
    result["需求人力"] = np.where(result["正常工作日"] * daily_hours * efficiency > 0, result["需求總工時"] / (result["正常工作日"] * daily_hours * efficiency), 0)
    result["人力差異"] = effective_people - result["需求人力"]
    result["缺工工時"] = np.maximum(0, result["需求總工時"] - result["含加班可用工時"])
    result["缺工天數"] = np.where(effective_people * daily_hours > 0, result["缺工工時"] / (effective_people * daily_hours), 0)
    warning_utilization = float(params.get("warning_utilization", 0.85))
    danger_utilization = float(params.get("danger_utilization", 1.0))
    red_utilization = float(params.get("red_utilization", 1.1))
    result["狀態"] = result["含加班稼動率"].map(lambda x: "紅燈" if x >= red_utilization else "橘燈" if x >= danger_utilization else "黃燈" if x >= warning_utilization else "綠燈")
    return result


def validate_schedule(schedule: pd.DataFrame) -> pd.DataFrame:
    if schedule is None or schedule.empty:
        return pd.DataFrame([{"類型": "排程", "狀態": "警示", "訊息": "排程表沒有資料"}])
    checks = []
    required = ["WO", "客戶", "P/N", "Type", "月份", "標準工時"]
    for col in required:
        if col not in schedule.columns:
            checks.append({"類型": "欄位", "狀態": "錯誤", "訊息": f"排程表缺少欄位：{col}"})
    if "標準工時" in schedule.columns:
        missing = pd.to_numeric(schedule["標準工時"], errors="coerce").isna().sum()
        checks.append({"類型": "標準工時", "狀態": "警示" if missing else "正常", "訊息": f"標準工時缺漏 {int(missing)} 筆"})
    if "WO" in schedule.columns:
        dup = schedule["WO"].duplicated().sum()
        checks.append({"類型": "WO", "狀態": "警示" if dup else "正常", "訊息": f"WO 重複 {int(dup)} 筆"})
    return pd.DataFrame(checks)
