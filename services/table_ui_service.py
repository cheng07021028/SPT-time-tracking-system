# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from typing import Iterable

import pandas as pd
import streamlit as st

from .db_service import execute, query_one
from .duration_service import hours_to_hms

COLUMN_LABELS: dict[str, str] = {
    "id": "ID / ID",
    "record_key": "紀錄鍵 / Record Key",
    "status": "狀態 / Status",
    "work_order": "製令 / Work Order",
    "part_no": "P/N / Part No.",
    "type_name": "機型 / Type",
    "process_name": "工段名稱 / Process",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "start_action": "開始動作 / Start Action",
    "start_timestamp": "開始時間戳 / Start Timestamp",
    "end_action": "結束動作 / End Action",
    "end_timestamp": "結束時間戳 / End Timestamp",
    "remark": "備註 / Remark",
    "start_date": "開始日期 / Start Date",
    "start_time": "開始時間 / Start Time",
    "end_date": "結束日期 / End Date",
    "end_time": "結束時間 / End Time",
    "work_hours": "工時小計 / Work Time",
    "assembly_location": "組立地點 / Assembly Location",
    "group_key": "群組鍵 / Group Key",
    "is_group_work": "同時作業 / Parallel Work",
    "source": "來源 / Source",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
    "customer": "客戶 / Customer",
    "note": "備註 / Note",
    "is_active": "啟用 / Active",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "今日出勤 / Today Attendance",
    "log_time": "LOG時間 / Log Time",
    "user_name": "使用者 / User",
    "action_type": "動作類型 / Action Type",
    "target_table": "目標資料表 / Target Table",
    "target_id": "目標ID / Target ID",
    "message": "訊息 / Message",
    "detail": "明細 / Detail",
    "level": "等級 / Level",
    "total_hours": "累積工時 / Total Time",
    "record_count": "紀錄筆數 / Record Count",
    "active_count": "作業中筆數 / Active Count",
    "today_record_count": "今日紀錄筆數 / Today Records",
    "last_start_time": "最後開始時間 / Last Start",
    "count": "筆數 / Count",
    "avg_hours": "平均工時 / Avg Time",
}

DEFAULT_WIDTHS: dict[str, int] = {
    "id": 70,
    "record_key": 280,
    "work_order": 150,
    "part_no": 170,
    "type_name": 230,
    "process_name": 140,
    "employee_id": 120,
    "employee_name": 130,
    "start_timestamp": 190,
    "end_timestamp": 190,
    "remark": 260,
    "note": 260,
    "message": 360,
    "detail": 420,
    "created_at": 180,
    "updated_at": 180,
}


BOOLEAN_COLUMNS = {"is_active", "is_in_factory", "is_today_attendance", "is_group_work", "刪除", "delete", "selected"}
NUMBER_COLUMNS = {"id", "record_count", "active_count", "today_record_count", "count", "sort_order", "order", "display_order"}


def _to_bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "啟用", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "否", ""}:
        return False
    return bool(value)


def _prepare_display_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dtypes before Streamlit data_editor renders.

    Streamlit 1.4x is stricter about column_config compatibility: a CheckboxColumn
    cannot render SQLite 0/1 integer columns, and a TextColumn cannot render numeric
    columns in editable mode.  This function keeps user-visible values stable while
    preventing StreamlitAPIException on system setting tables and admin edit tables.
    """
    out = df.copy()
    for col in out.columns:
        col_name = str(col)
        if col_name in BOOLEAN_COLUMNS:
            out[col] = out[col].map(_to_bool_value).astype(bool)
        elif col_name in NUMBER_COLUMNS:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


_TABLE_UI_SCHEMA_READY = False
_WIDTH_CACHE_TTL_SECONDS = 300


def label_for(col: str) -> str:
    return COLUMN_LABELS.get(col, f"{col} / {col}")


def ensure_table_ui_schema() -> None:
    global _TABLE_UI_SCHEMA_READY
    if _TABLE_UI_SCHEMA_READY:
        return
    execute(
        """
        CREATE TABLE IF NOT EXISTS table_ui_settings (
            table_key TEXT PRIMARY KEY,
            widths_json TEXT,
            order_json TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    try:
        execute("ALTER TABLE table_ui_settings ADD COLUMN order_json TEXT")
    except Exception:
        pass
    _TABLE_UI_SCHEMA_READY = True


def load_widths(table_key: str) -> dict[str, int]:
    ensure_table_ui_schema()
    cache_key = f"_spt_width_cache_{table_key}"
    try:
        cached = st.session_state.get(cache_key)
        if cached and time.time() - float(cached.get("ts", 0)) < _WIDTH_CACHE_TTL_SECONDS:
            return dict(cached.get("data", {}))
    except Exception:
        pass
    row = query_one("SELECT widths_json FROM table_ui_settings WHERE table_key=?", (table_key,))
    if not row or not row.get("widths_json"):
        widths = {}
    else:
        try:
            data = json.loads(row["widths_json"])
            widths = {str(k): int(v) for k, v in data.items() if str(v).isdigit() or isinstance(v, int)}
        except Exception:
            widths = {}
    try:
        st.session_state[cache_key] = {"ts": time.time(), "data": widths}
    except Exception:
        pass
    return widths


def save_widths(table_key: str, widths: dict[str, int]) -> None:
    ensure_table_ui_schema()
    execute(
        """
        INSERT INTO table_ui_settings(table_key, widths_json, updated_at)
        VALUES (?, ?, datetime('now','localtime'))
        ON CONFLICT(table_key) DO UPDATE SET
            widths_json=excluded.widths_json,
            updated_at=excluded.updated_at
        """,
        (table_key, json.dumps(widths, ensure_ascii=False)),
    )
    try:
        st.session_state[f"_spt_width_cache_{table_key}"] = {"ts": time.time(), "data": dict(widths)}
    except Exception:
        pass


def load_column_order(table_key: str) -> list[str]:
    ensure_table_ui_schema()
    row = query_one("SELECT order_json FROM table_ui_settings WHERE table_key=?", (table_key,))
    if not row or not row.get("order_json"):
        return []
    try:
        data = json.loads(row["order_json"])
        return [str(x) for x in data if str(x)] if isinstance(data, list) else []
    except Exception:
        return []


def save_column_order(table_key: str, order: Iterable[str]) -> None:
    ensure_table_ui_schema()
    cols = [str(c) for c in order if str(c)]
    execute(
        """
        INSERT INTO table_ui_settings(table_key, order_json, updated_at)
        VALUES (?, ?, datetime('now','localtime'))
        ON CONFLICT(table_key) DO UPDATE SET
            order_json=excluded.order_json,
            updated_at=excluded.updated_at
        """,
        (table_key, json.dumps(cols, ensure_ascii=False)),
    )


def apply_column_order(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    order = load_column_order(table_key)
    if not order:
        return df
    ordered = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in ordered]
    if not ordered:
        return df
    return df[ordered + rest]


def _column_config(col: str, width: int | None = None, series: pd.Series | None = None):
    label = label_for(col)
    w = int(width or DEFAULT_WIDTHS.get(col, 140))
    col_name = str(col)
    if col_name in BOOLEAN_COLUMNS:
        return st.column_config.CheckboxColumn(label, width=w)
    if col_name in {"work_hours", "total_hours", "avg_hours"}:
        return st.column_config.TextColumn(label, width=w)
    if col_name in NUMBER_COLUMNS:
        return st.column_config.NumberColumn(label, width=w)
    try:
        if series is not None and pd.api.types.is_bool_dtype(series):
            return st.column_config.CheckboxColumn(label, width=w)
        if series is not None and pd.api.types.is_numeric_dtype(series):
            return st.column_config.NumberColumn(label, width=w)
    except Exception:
        pass
    return st.column_config.TextColumn(label, width=w)

def build_column_config(table_key: str, df: pd.DataFrame) -> dict:
    widths = load_widths(table_key)
    return {col: _column_config(str(col), widths.get(str(col)), df[col] if col in df.columns else None) for col in df.columns}

def render_width_settings(table_key: str, df: pd.DataFrame, title: str = "欄寬設定 / Column Width Settings") -> None:
    """Lazy width editor.

    Streamlit executes widgets inside collapsed expanders, so the old version generated
    dozens of number_input widgets on every page load. This made module switching slow.
    V1.39 keeps the feature, but only renders the heavy controls when the user explicitly opens it.
    """
    if df is None or df.empty:
        return
    show_key = f"show_widths_{table_key}"
    show = st.toggle(f"⌬️ 顯示{title}", value=False, key=show_key)
    if not show:
        return
    widths = load_widths(table_key)
    with st.expander(title, expanded=True):
        st.caption("欄寬與欄位順序會永久保存。順序數字越小越靠左；平常保持關閉可加快模組載入速度。")
        saved_order = load_column_order(table_key)
        order_index = {c: i + 1 for i, c in enumerate(saved_order)}
        new_widths: dict[str, int] = {}
        new_orders: dict[str, int] = {}
        cols = st.columns(4)
        for idx, col in enumerate(df.columns):
            default_width = int(widths.get(col, DEFAULT_WIDTHS.get(col, 140)))
            default_order = int(order_index.get(str(col), idx + 1))
            with cols[idx % 4]:
                st.markdown(f"**{label_for(col)}**")
                new_widths[col] = st.number_input("欄寬", min_value=60, max_value=700, value=default_width, step=10, key=f"width_{table_key}_{col}")
                new_orders[col] = st.number_input("順序", min_value=1, max_value=max(len(df.columns), 1), value=default_order, step=1, key=f"order_{table_key}_{col}")
        if st.button("儲存欄位設定 / Save Column Settings", key=f"save_widths_{table_key}", use_container_width=True):
            save_widths(table_key, new_widths)
            ordered_cols = [c for c, _ in sorted(new_orders.items(), key=lambda kv: (kv[1], str(kv[0])))]
            save_column_order(table_key, ordered_cols)
            st.success("已永久儲存欄寬與欄位順序設定。")
            st.rerun()


def _format_duration_columns_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Return UI copy with duration columns formatted as HH:MM:SS."""
    out = df.copy()
    for col in ["work_hours", "total_hours", "avg_hours"]:
        if col in out.columns:
            out[col] = out[col].map(hours_to_hms)
    return out



def _inject_native_header_sort_style() -> None:
    """Style only: keep Streamlit's native table header sorting discoverable.

    We intentionally do not render a separate sort toolbar or extra buttons.
    Streamlit/Glide tables already sort from the original header row; this CSS only
    makes headers look clickable and preserves the existing table header location.
    """
    st.markdown(
        """
        <style>
        /* V2.91｜全模組表格標題列原地排序提示：不新增排序按鈕 */
        div[data-testid="stDataFrame"] [role="columnheader"],
        div[data-testid="stDataEditor"] [role="columnheader"],
        div[data-testid="stDataFrame"] [data-testid="stDataFrameResizableHeader"],
        div[data-testid="stDataEditor"] [data-testid="stDataFrameResizableHeader"] {
            cursor: pointer !important;
        }
        div[data-testid="stDataFrame"] [role="columnheader"]:hover,
        div[data-testid="stDataEditor"] [role="columnheader"]:hover {
            background: linear-gradient(90deg, rgba(58, 220, 255, .13), rgba(112, 119, 255, .10)) !important;
            box-shadow: inset 0 -1px 0 rgba(110, 236, 255, .55) !important;
        }
        div[data-testid="stDataFrame"] [role="columnheader"] *,
        div[data-testid="stDataEditor"] [role="columnheader"] * {
            user-select: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

def _apply_quick_header_sort(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """Compatibility no-op.

    Previous versions experimented with an extra quick-sort button bar above tables.
    The requested standard is now: keep the original table header row and use native
    left-click header sorting only.  Do not render any additional sort controls here.
    """
    return df


def _render_sort_controls(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """Compatibility no-op.

    Keep this function name so older imports do not fail, but do not show the old
    "排序設定 / Sort Settings" expander. Sorting must remain on the original
    table header row only.
    """
    return df


def render_table(
    df: pd.DataFrame,
    table_key: str,
    *,
    editable: bool = False,
    disabled: Iterable[str] | None = None,
    key: str | None = None,
    height: int | None = None,
    num_rows: str = "fixed",
) -> pd.DataFrame | None:
    if df is None or df.empty:
        st.info("目前沒有資料 / No data")
        return None
    _inject_native_header_sort_style()
    # V1.89: Editable tables are usually placed inside st.form so edits do not rerun
    # the entire page on every cell click. Do not render width controls inside
    # editable tables because normal buttons cannot live inside st.form and the
    # extra widgets slow down editing. Read-only tables keep the existing width tool.
    if not editable:
        render_width_settings(table_key, df)
    df = apply_column_order(table_key, df)
    display_df = _format_duration_columns_for_display(df)
    display_df = _prepare_display_dataframe(display_df)
    cfg = build_column_config(table_key, display_df)
    disabled_cols = list(disabled or [])
    if "work_hours" in display_df.columns and "work_hours" not in disabled_cols:
        disabled_cols.append("work_hours")
    if "total_hours" in display_df.columns and "total_hours" not in disabled_cols:
        disabled_cols.append("total_hours")
    if "avg_hours" in display_df.columns and "avg_hours" not in disabled_cols:
        disabled_cols.append("avg_hours")
    if editable:
        return st.data_editor(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config=cfg,
            disabled=disabled_cols,
            num_rows=num_rows,
            key=key or f"editor_{table_key}",
            height=height,
        )
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config=cfg,
        height=height,
        key=key or f"frame_{table_key}",
    )
    return None
