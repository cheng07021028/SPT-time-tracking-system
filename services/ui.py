# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import streamlit as st

from services.app_config import MODULE_BY_KEY, TABLE_COLUMNS
from services.auth_service import current_user, logout, check_permission
from services.permanent_store import load_records, save_records, load_settings, save_settings, log_event, STORE_ROOT


def apply_theme() -> None:
    st.markdown("""
<style>
:root { --spt-cyan:#22d3ee; --spt-blue:#38bdf8; --spt-bg:#07111f; }
[data-testid="stAppViewContainer"] { background: radial-gradient(circle at 15% 10%, rgba(34,211,238,.16), transparent 28%), linear-gradient(135deg,#06101d,#0b1b2f 48%,#08111f); }
[data-testid="stSidebar"] { background: linear-gradient(180deg, rgba(9,24,43,.96), rgba(5,11,21,.98)); border-right:1px solid rgba(34,211,238,.22); }
.spt-hero { padding:20px 24px; border:1px solid rgba(34,211,238,.45); border-radius:24px; background:linear-gradient(135deg, rgba(8,28,51,.90), rgba(7,17,31,.72)); box-shadow:0 0 32px rgba(34,211,238,.17), inset 0 0 18px rgba(34,211,238,.06); margin-bottom:18px; }
.spt-title { font-size:30px; font-weight:900; color:#e5f7ff; letter-spacing:.04em; }
.spt-sub { color:#9de7ff; font-size:15px; margin-top:4px; }
.spt-card { border:1px solid rgba(34,211,238,.24); border-radius:20px; padding:16px; background:rgba(8,24,43,.72); box-shadow:0 0 18px rgba(34,211,238,.10); }
.stTextInput input, .stNumberInput input, textarea { background:#eef8ff !important; color:#06101d !important; border:1px solid #22d3ee !important; min-height:42px !important; }
[data-baseweb="select"] div { color:#06101d !important; }
.stMultiSelect [data-baseweb="tag"] { background:#0ea5e9 !important; }
button[kind="primary"] { border:1px solid #22d3ee !important; box-shadow:0 0 12px rgba(34,211,238,.30); }
</style>
""", unsafe_allow_html=True)


def page_header(module_key: str, subtitle: str | None = None) -> None:
    m = MODULE_BY_KEY.get(module_key)
    title = f"{m.no}｜{m.title}" if m else module_key
    sub = subtitle or (m.desc if m else "")
    st.markdown(f"<div class='spt-hero'><div class='spt-title'>{title}</div><div class='spt-sub'>{sub}</div><div class='spt-sub'>永久資料源：<code>data/permanent_store</code></div></div>", unsafe_allow_html=True)
    with st.sidebar:
        st.caption(f"登入：{current_user()}")
        if st.button("登出", use_container_width=True):
            logout(); st.rerun()


def to_df(rows: list[dict[str, Any]], columns: list[str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if columns:
        for c in columns:
            if c not in df.columns:
                df[c] = ""
        extra = [c for c in df.columns if c not in columns]
        df = df[columns + extra]
    return df


def df_to_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None:
        return []
    out = df.copy()
    out = out.where(pd.notna(out), "")
    return out.to_dict("records")


def table_settings_key(module_key: str, table_id: str) -> str:
    return f"table::{table_id}"


def configurable_editor(module_key: str, table_id: str, df: pd.DataFrame, *, allow_edit: bool = True, allow_delete: bool = True, height: int = 520) -> pd.DataFrame:
    settings = load_settings(module_key, {})
    tkey = table_settings_key(module_key, table_id)
    ts = settings.get(tkey, {}) if isinstance(settings.get(tkey, {}), dict) else {}
    all_cols = list(df.columns)
    default_order = ts.get("column_order") if isinstance(ts.get("column_order"), list) else all_cols
    order = [c for c in default_order if c in all_cols] + [c for c in all_cols if c not in default_order]
    visible = ts.get("visible_columns") if isinstance(ts.get("visible_columns"), list) else order
    visible = [c for c in visible if c in order] or order

    with st.expander("欄位顯示 / 順序設定（永久保存）", expanded=False):
        c1, c2 = st.columns([2, 1])
        with c1:
            new_order = st.multiselect("欄位順序：由左到右", options=order, default=order, key=f"{module_key}_{table_id}_order")
            new_visible = st.multiselect("顯示欄位", options=new_order, default=[c for c in visible if c in new_order] or new_order, key=f"{module_key}_{table_id}_visible")
        with c2:
            st.write("")
            st.write("")
            if st.button("套用並永久記錄欄位設定", key=f"{module_key}_{table_id}_save_cols", use_container_width=True):
                settings[tkey] = {"column_order": new_order, "visible_columns": new_visible}
                save_settings(module_key, settings, current_user(), "save_table_settings")
                st.success("欄位設定已永久保存。")
                st.rerun()
            if st.button("恢復此表格欄位預設", key=f"{module_key}_{table_id}_reset_cols", use_container_width=True):
                settings.pop(tkey, None)
                save_settings(module_key, settings, current_user(), "reset_table_settings")
                st.rerun()

    use_cols = [c for c in order if c in visible]
    view = df[use_cols].copy() if use_cols else df.copy()
    if allow_delete and allow_edit and "刪除" not in view.columns:
        view.insert(0, "刪除", False)
    edited = st.data_editor(view, use_container_width=True, hide_index=True, num_rows="dynamic" if allow_edit else "fixed", disabled=not allow_edit, height=height, key=f"editor_{module_key}_{table_id}")
    if allow_delete and allow_edit and "刪除" in edited.columns:
        edited = edited[~edited["刪除"].astype(str).str.lower().isin(["true", "1", "yes", "是", "勾選"])]
        edited = edited.drop(columns=["刪除"])
    # restore hidden columns from original by index where possible
    for c in df.columns:
        if c not in edited.columns:
            edited[c] = df[c] if len(df) == len(edited) else ""
    final_cols = [c for c in order if c in edited.columns] + [c for c in edited.columns if c not in order]
    return edited[final_cols]


def records_page(module_key: str, *, title: str | None = None, default_columns: list[str] | None = None, recalc_func=None) -> None:
    page_header(module_key, title)
    rows = load_records(module_key, [])
    df = to_df(rows, default_columns or TABLE_COLUMNS.get(module_key, []))
    can_edit = check_permission(module_key, "edit")
    edited = configurable_editor(module_key, "main", df, allow_edit=can_edit, allow_delete=check_permission(module_key, "delete"))
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("套用並永久儲存", type="primary", use_container_width=True, disabled=not can_edit):
            rows2 = df_to_rows(edited)
            if recalc_func:
                rows2 = recalc_func(rows2)
            save_records(module_key, rows2, current_user(), "save_main_table")
            st.success("已寫入唯一永久路徑，Reboot App 後仍會讀取此版本。")
            st.rerun()
    with c2:
        if st.button("重新載入永久檔", use_container_width=True):
            st.rerun()
    with c3:
        excel_download_button(edited, f"{module_key}.xlsx")


def excel_download_button(df: pd.DataFrame, filename: str) -> None:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="data")
    st.download_button("匯出 Excel", bio.getvalue(), file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)


def paste_import_box(module_key: str, columns: list[str]) -> None:
    with st.expander("貼上資料匯入 / Paste Import", expanded=False):
        text = st.text_area("可直接從 Excel 複製含標題列資料貼上", height=180, key=f"paste_{module_key}")
        if st.button("解析貼上資料並永久加入", key=f"paste_btn_{module_key}") and text.strip():
            import io
            df = pd.read_csv(io.StringIO(text), sep="\t")
            rows = load_records(module_key, []) + df_to_rows(df)
            save_records(module_key, rows, current_user(), "paste_import")
            st.success(f"已加入 {len(df)} 筆。")
            st.rerun()


def delete_by_date_range_jsonl(path, start: str, end: str) -> int:
    from services.permanent_store import read_jsonl
    rows = read_jsonl(path)
    keep = []
    deleted = 0
    for r in rows:
        t = str(r.get("時間", ""))[:10]
        if start <= t <= end:
            deleted += 1
        else:
            keep.append(r)
    path.write_text("\n".join(__import__('json').dumps(x, ensure_ascii=False) for x in keep) + ("\n" if keep else ""), encoding="utf-8")
    return deleted
