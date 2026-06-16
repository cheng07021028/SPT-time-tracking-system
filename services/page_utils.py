from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Sequence, Any

import pandas as pd
import streamlit as st

from .data_loader import clear_data_cache, load_table
from .export_service import dataframe_to_excel_bytes, module_report_excel_bytes, multi_sheet_excel_bytes
from .persistent_store import save_authority_df
from .schema_service import canonical_column_name, normalize_columns, schema_for_table
from .settings_service import load_table_settings, save_table_settings


SELECT_COL = "_選取"
USER_ROLE_OPTIONS = ["製造部經理", "系統管理員", "課長", "組長", "生管", "工時管理者", "訪客"]






def _column_config_for_table(table_name: str) -> dict[str, object]:
    config: dict[str, object] = {
        SELECT_COL: st.column_config.CheckboxColumn("選取", help="可用於全選、刪除選取資料。")
    }
    if table_name == "users":
        config["角色"] = st.column_config.SelectboxColumn("角色", options=USER_ROLE_OPTIONS, required=True, help="選擇系統預設角色。")
        config["啟用"] = st.column_config.SelectboxColumn("啟用", options=["是", "否"], required=True)
    if table_name in {"employees", "dispatch"}:
        config["是否直接人力"] = st.column_config.SelectboxColumn("是否直接人力", options=["是", "否"], required=False)
        config["啟用"] = st.column_config.SelectboxColumn("啟用", options=["是", "否"], required=False)
        config["可用比例"] = st.column_config.NumberColumn("可用比例", min_value=-100.0, max_value=100.0, step=0.1, format="%.2f")
    return config

def _canonicalize_table_columns(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename_map = {col: canonical_column_name(table_name, col) for col in out.columns}
    out = out.rename(columns=rename_map)
    if out.columns.duplicated().any():
        merged = pd.DataFrame(index=out.index)
        for col in dict.fromkeys(out.columns):
            same = out.loc[:, out.columns == col]
            merged[col] = same.bfill(axis=1).iloc[:, 0] if same.shape[1] > 1 else same.iloc[:, 0]
        out = merged
    return out


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return None
    try:
        parsed = pd.to_datetime(text, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _tenure_text(start_value: object, today: date | None = None) -> str:
    start = _parse_date(start_value)
    if start is None:
        return ""
    today = today or date.today()
    if start > today:
        return "0年0月0天"
    years = today.year - start.year
    months = today.month - start.month
    days = today.day - start.day
    if days < 0:
        first_of_month = date(today.year, today.month, 1)
        prev_month_last = first_of_month - timedelta(days=1)
        days += prev_month_last.day
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    return f"{max(years, 0)}年{max(months, 0)}月{max(days, 0)}天"


def recalculate_manpower_tenure(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    out = _canonicalize_table_columns(table_name, df)
    if table_name not in {"employees", "dispatch"}:
        return out
    if "到職日" not in out.columns:
        return out
    out["累積年資"] = out["到職日"].apply(_tenure_text)
    # Keep the system-owned tenure column next to 到職日 for readability.
    ordered = []
    for col in out.columns:
        if col == "累積年資":
            continue
        ordered.append(col)
        if col == "到職日":
            ordered.append("累積年資")
    if "累積年資" not in ordered:
        ordered.append("累積年資")
    return out[[c for c in ordered if c in out.columns]]

def _table_state_key(table_name: str) -> str:
    return f"managed_table_df_{table_name}"


def _ensure_state_df(table_name: str, source_df: pd.DataFrame) -> pd.DataFrame:
    key = _table_state_key(table_name)
    source_df = _canonicalize_table_columns(table_name, source_df.copy())
    if table_name in {"employees", "dispatch"}:
        source_df = recalculate_manpower_tenure(table_name, source_df)
    if SELECT_COL in source_df.columns:
        source_df = source_df.drop(columns=[SELECT_COL])
    for col in schema_for_table(table_name):
        if col not in source_df.columns:
            source_df[col] = None
    source_df = source_df[normalize_columns(table_name, list(source_df.columns))]
    if key not in st.session_state:
        state_df = source_df.copy()
        state_df.insert(0, SELECT_COL, False)
        st.session_state[key] = state_df
    return st.session_state[key]


def _replace_state_df(table_name: str, df: pd.DataFrame) -> None:
    key = _table_state_key(table_name)
    st.session_state[key] = df.copy()


def clear_managed_table_state(table_name: str) -> None:
    """Clear cached editor state so newly saved authority data appears immediately after rerun."""
    key = _table_state_key(table_name)
    if key in st.session_state:
        del st.session_state[key]



def clean_table_for_save(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if SELECT_COL in out.columns:
        out = out.drop(columns=[SELECT_COL])
    return out.dropna(how="all")


def _safe_file_prefix(file_prefix: str) -> str:
    return str(file_prefix).replace("/", "_").replace("\\", "_").replace(" ", "_")


def render_excel_download(df: pd.DataFrame, file_prefix: str, label: str = "匯出目前資料 Excel", key: str | None = None) -> None:
    """Backward-compatible single-section Excel download.

    New module pages should not call this directly. Use render_module_report_download instead,
    so the export contains the whole module and charts.
    """
    export_df = clean_table_for_save(df)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prefix = _safe_file_prefix(file_prefix)
    st.download_button(
        label=label,
        data=dataframe_to_excel_bytes(export_df, sheet_name=str(file_prefix)[:31]),
        file_name=f"{safe_prefix}_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"download_{safe_prefix}_{stamp}",
    )


def render_multi_sheet_download(sheets: dict[str, pd.DataFrame], file_prefix: str, label: str = "匯出 Excel", key: str | None = None) -> None:
    """Backward-compatible multi-sheet download.

    New module pages should use render_module_report_download for full module reports with charts.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prefix = _safe_file_prefix(file_prefix)
    st.download_button(
        label=label,
        data=multi_sheet_excel_bytes(sheets),
        file_name=f"{safe_prefix}_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"download_multi_{safe_prefix}_{stamp}",
    )


def render_module_report_download(
    module_title: str,
    sheets: Mapping[str, pd.DataFrame],
    *,
    chart_specs: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
    label: str = "匯出整個模組 Excel（含完整資料與圖表）",
    key: str | None = None,
) -> None:
    """Render one module-level Excel export button.

    This replaces the old per-table export buttons. The generated workbook contains a report dashboard,
    module data sheets, and editable Excel charts.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prefix = _safe_file_prefix(module_title)
    st.markdown(
        """
        <div class="module-export-card">
          <b>整個模組匯出</b><br/>
          <span class="small-muted">這裡只提供本模組完整匯出：包含完整資料、摘要表與 Power BI 風格可編輯 Excel 圖表；已移除單一表格區塊匯出。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.download_button(
        label=label,
        data=module_report_excel_bytes(module_title, sheets, chart_specs=chart_specs, metadata=metadata),
        file_name=f"{safe_prefix}_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"download_module_{safe_prefix}_{stamp}",
        type="primary",
    )


def _column_settings_ui(table_name: str, all_columns: list[str]) -> tuple[list[str], int, bool]:
    settings = load_table_settings(table_name)
    actual_cols = [c for c in all_columns if c != SELECT_COL]
    saved_visible = [c for c in settings.get("visible_columns", actual_cols) if c in actual_cols]
    if not saved_visible:
        saved_visible = actual_cols
    saved_order = [c for c in settings.get("column_order", saved_visible) if c in actual_cols]
    saved_order += [c for c in saved_visible if c not in saved_order]
    default_height = int(settings.get("height", 520))
    with st.expander("表格欄位、順序與操作設定", expanded=False):
        st.caption("這裡的顯示欄位、欄位順序與表格高度，按下『套用設定』後會永久保存；按『恢復設定』會恢復預設欄位並永久保存。")
        visible = st.multiselect("顯示欄位", actual_cols, default=saved_visible, key=f"visible_cols_{table_name}")
        order = st.multiselect("欄位順序（先選的排前面）", actual_cols, default=saved_order, key=f"order_cols_{table_name}")
        height = st.slider("表格高度", min_value=320, max_value=900, value=default_height, step=20, key=f"height_{table_name}")
        c1, c2, c3 = st.columns([1, 1, 4])
        apply = c1.button("套用設定", type="primary", key=f"apply_col_settings_{table_name}")
        reset = c2.button("恢復設定", key=f"reset_col_settings_{table_name}")
        if reset:
            visible = actual_cols
            order = actual_cols
            height = 520
            save_table_settings(table_name, {"visible_columns": visible, "column_order": order, "height": height}, user="streamlit")
            st.success("已恢復預設設定，並已永久保存。")
            st.rerun()
        if apply:
            final_order = [c for c in order if c in visible] + [c for c in visible if c not in order]
            save_table_settings(table_name, {"visible_columns": visible, "column_order": final_order, "height": height}, user="streamlit")
            st.success("設定已永久套用。")
            st.rerun()
        final_order = [c for c in order if c in visible] + [c for c in visible if c not in order]
        return final_order, height, apply


def render_saveable_table(table_name: str, title: str, height: int = 520, helper_text: str | None = None) -> pd.DataFrame:
    source_df = load_table(table_name)
    state_df = _ensure_state_df(table_name, source_df)
    if helper_text:
        st.info(helper_text, icon="💡")
    st.caption(f"資料來源：data/persistent/authority/{table_name}.json。畫面編輯後需按『儲存資料』才會永久寫入權威資料。")

    display_cols, table_height, _ = _column_settings_ui(table_name, list(state_df.columns))
    display_cols = [c for c in display_cols if c in state_df.columns]
    editor_cols = [SELECT_COL] + display_cols
    editor_source = state_df.reindex(columns=editor_cols)

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.2, 2.8])
    if c1.button("新增空白列", key=f"add_row_{table_name}"):
        new_df = st.session_state[_table_state_key(table_name)].copy()
        blank = {col: None for col in new_df.columns}
        blank[SELECT_COL] = False
        new_df.loc[len(new_df)] = blank
        _replace_state_df(table_name, new_df)
        st.rerun()
    if c2.button("全選資料", key=f"select_all_{table_name}"):
        new_df = st.session_state[_table_state_key(table_name)].copy()
        new_df[SELECT_COL] = True
        _replace_state_df(table_name, new_df)
        st.rerun()
    if c3.button("取消全選", key=f"unselect_all_{table_name}"):
        new_df = st.session_state[_table_state_key(table_name)].copy()
        new_df[SELECT_COL] = False
        _replace_state_df(table_name, new_df)
        st.rerun()
    if c4.button("刪除選取資料", key=f"delete_selected_{table_name}"):
        new_df = st.session_state[_table_state_key(table_name)].copy()
        selected = new_df[SELECT_COL].fillna(False).astype(bool) if SELECT_COL in new_df.columns else pd.Series(False, index=new_df.index)
        if selected.any():
            new_df = new_df.loc[~selected].reset_index(drop=True)
            if SELECT_COL not in new_df.columns:
                new_df.insert(0, SELECT_COL, False)
            _replace_state_df(table_name, new_df)
            st.success(f"已從畫面移除 {int(selected.sum())} 筆，請按『儲存資料』才會永久生效。")
            st.rerun()
        else:
            st.warning("尚未選取資料。")
    with c5:
        st.info("單一表格匯出已移除；請使用頁面下方『整個模組匯出』下載完整資料與圖表。", icon="📘")

    edited = st.data_editor(
        editor_source,
        use_container_width=True,
        height=table_height or height,
        num_rows="dynamic",
        key=f"editor_{table_name}",
        column_config=_column_config_for_table(table_name),
    )

    current = st.session_state[_table_state_key(table_name)].copy()
    new_full = pd.DataFrame(index=range(len(edited)))
    for col in current.columns:
        if col in edited.columns:
            new_full[col] = edited[col].values
        else:
            new_full[col] = current[col].reindex(range(len(edited))).values
    for col in edited.columns:
        if col not in new_full.columns:
            new_full[col] = edited[col].values
    if SELECT_COL not in new_full.columns:
        new_full.insert(0, SELECT_COL, False)
    st.session_state[_table_state_key(table_name)] = new_full

    c1, c2 = st.columns([1, 5])
    if c1.button("儲存資料", type="primary", key=f"save_{table_name}"):
        clean = clean_table_for_save(st.session_state[_table_state_key(table_name)])
        clean = recalculate_manpower_tenure(table_name, clean)
        save_authority_df(table_name, clean, user="streamlit")
        clear_data_cache()
        refreshed = clean.copy()
        refreshed.insert(0, SELECT_COL, False)
        _replace_state_df(table_name, refreshed)
        if table_name in {"employees", "dispatch"}:
            st.success(f"{title} 已永久保存，並已依到職日自動更新『累積年資』。")
        else:
            st.success(f"{title} 已永久保存。")
        st.rerun()
    with c2:
        st.info("人性化操作：可先調欄位、全選/取消全選、刪除選取、編輯資料；只有按『儲存資料』才會寫入權威資料。", icon="✅")

    return clean_table_for_save(st.session_state[_table_state_key(table_name)])


def render_filter_hint() -> None:
    st.caption("速度設計：篩選條件在表單內調整，只有按下套用/儲存/執行才會重新計算或寫入資料。")


def render_configurable_view(df: pd.DataFrame, table_key: str, title: str, height: int = 460) -> pd.DataFrame:
    view = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
    if view.empty:
        st.info(f"{title} 目前沒有資料。")
        return view
    display_cols, table_height, _ = _column_settings_ui(f"view_{table_key}", list(view.columns))
    display_cols = [c for c in display_cols if c in view.columns]
    shown = view[display_cols] if display_cols else view
    st.dataframe(shown, use_container_width=True, hide_index=True, height=table_height or height)
    st.caption("本表格屬於模組內容的一部分；可在上方按『套用設定 / 恢復設定』永久保存顯示方式，完整資料與圖表請使用頁面下方『整個模組匯出』。")
    return shown
