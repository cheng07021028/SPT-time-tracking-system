# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import re
import pandas as pd
from services.timezone_service import today_date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.time_record_service import (
    load_records,
    save_time_records,
    delete_time_records,
    recalculate_time_records,
    import_time_records,
)
from services.master_data_service import load_employees, load_work_orders
from services.table_ui_service import render_table
from services.duration_service import hours_to_hms

st.set_page_config(page_title="02. 歷史紀錄", page_icon="📚", layout="wide")
apply_theme()
require_module_access("02_history")
render_header("02｜歷史紀錄", "完整工時明細查詢、資料編輯、刪除、重新計算、Excel 匯入、貼上資料與 Excel 匯出")

HISTORY_IMPORT_PREVIEW_KEY = "v197_history_import_preview"
HISTORY_PASTE_RAW_KEY = "v197_history_paste_raw"


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def _normalize_text(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _normalize_header_name(v) -> str:
    text = _normalize_text(v).lower()
    for ch in [" ", "\t", "\n", "\r", "_", "-", "－", "—", "/", "／", "\\", ".", "．", "：", ":", "（", "）", "(", ")"]:
        text = text.replace(ch, "")
    return text


def _split_paste_line(line: str) -> list[str]:
    line = line.rstrip("\n")
    if "\t" in line:
        return [x.strip() for x in line.split("\t")]
    if "," in line:
        return [x.strip() for x in line.split(",")]
    parts = [x.strip() for x in re.split(r"\s{2,}", line) if x.strip()]
    if len(parts) <= 1:
        parts = [x.strip() for x in line.split()]
    return parts


HISTORY_ALIAS_GROUPS = {
    "id": ["id", "編號"],
    "record_key": ["record key", "record_key", "紀錄鍵", "唯一鍵", "key"],
    "status": ["狀態", "status"],
    "work_order": ["製令", "工單", "工令", "製令號碼", "work order", "work_order", "wo", "mo"],
    "part_no": ["p/n", "pn", "part no", "part_no", "料號", "品號"],
    "type_name": ["機型", "type", "type name", "type_name", "model", "型號"],
    "process_name": ["工段名稱", "工段", "process", "process name", "process_name", "作業工段"],
    "employee_id": ["工號", "employee id", "employee_id", "emp id", "人員工號"],
    "employee_name": ["姓名", "name", "employee name", "employee_name", "人員姓名"],
    "start_action": ["開始動作", "start action", "start_action"],
    "start_timestamp": ["開始時間戳", "開始時間", "start timestamp", "start_timestamp", "start datetime", "開始日期時間"],
    "end_action": ["結束動作", "end action", "end_action"],
    "end_timestamp": ["結束時間戳", "結束時間", "end timestamp", "end_timestamp", "end datetime", "結束日期時間"],
    "remark": ["備註", "remark", "note", "memo"],
    "start_date": ["開始日期", "start date", "start_date"],
    "start_time": ["開始時間", "start time", "start_time"],
    "end_date": ["結束日期", "end date", "end_date"],
    "end_time": ["結束時間", "end time", "end_time"],
    "work_hours": ["工時小計", "工時", "work time", "work hours", "work_hours", "total hours"],
    "assembly_location": ["組立地點", "組裝地點", "assembly location", "assembly_location", "location"],
    "group_key": ["群組", "群組鍵", "group key", "group_key"],
    "is_group_work": ["同時作業", "群組作業", "parallel work", "is_group_work"],
    "source": ["來源", "source"],
}

HISTORY_COLS = [
    "id", "record_key", "status", "work_order", "part_no", "type_name", "process_name",
    "employee_id", "employee_name", "start_action", "start_timestamp", "end_action", "end_timestamp",
    "remark", "start_date", "start_time", "end_date", "end_time", "work_hours", "assembly_location",
    "group_key", "is_group_work", "source",
]

DEFAULT_PASTE_ORDER = [
    "status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name",
    "start_timestamp", "end_timestamp", "remark", "assembly_location",
]


def _find_col(source: pd.DataFrame, aliases: list[str]):
    norm_to_col = {_normalize_header_name(c): c for c in source.columns}
    norm_aliases = [_normalize_header_name(a) for a in aliases]
    for alias in norm_aliases:
        if alias in norm_to_col:
            return norm_to_col[alias]
    for alias in norm_aliases:
        for norm_col, real_col in norm_to_col.items():
            if alias and (alias in norm_col or norm_col in alias):
                return real_col
    return None


def _row_looks_like_header(row: list[str]) -> bool:
    norm_row = {_normalize_header_name(x) for x in row}
    hits = 0
    for aliases in HISTORY_ALIAS_GROUPS.values():
        norm_aliases = {_normalize_header_name(a) for a in aliases}
        if norm_row & norm_aliases:
            hits += 1
    return hits >= 2


def _pick_series(source: pd.DataFrame, target: str, default=""):
    col = _find_col(source, HISTORY_ALIAS_GROUPS[target])
    if col is None:
        return default
    return source[col]


def _ensure_history_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in HISTORY_COLS:
        if c not in df.columns:
            if c == "is_group_work":
                df[c] = False
            else:
                df[c] = ""
    return df[HISTORY_COLS].copy()


def parse_history_dataframe(source: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if source is None or source.empty:
        return _ensure_history_cols(pd.DataFrame()), ["來源資料為空。"]

    source = source.copy()
    # Some Excel exports have completely blank rows/columns.
    source = source.dropna(how="all").dropna(axis=1, how="all")
    if source.empty:
        return _ensure_history_cols(pd.DataFrame()), ["來源資料沒有有效列。"]

    data = {}
    for c in HISTORY_COLS:
        picked = _pick_series(source, c, default="")
        data[c] = picked
    parsed = pd.DataFrame(data)

    # If no recognizable headers were found, preserve the original columns by position.
    if parsed[["work_order", "process_name", "employee_id", "start_timestamp"]].astype(str).replace("", pd.NA).isna().all().all():
        warnings.append("未偵測到可辨識標題，已依預設順序解析：狀態、製令、P/N、機型、工段、工號、姓名、開始時間戳、結束時間戳、備註、組立地點。")
        rows = source.astype(str).fillna("").values.tolist()
        normalized = []
        for row in rows:
            item = {c: "" for c in HISTORY_COLS}
            for idx, col_name in enumerate(DEFAULT_PASTE_ORDER):
                if idx < len(row):
                    item[col_name] = row[idx]
            normalized.append(item)
        parsed = pd.DataFrame(normalized)

    for c in HISTORY_COLS:
        if c not in parsed.columns:
            parsed[c] = ""
    for c in ["status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name", "start_action", "end_action", "remark", "assembly_location", "group_key", "source"]:
        parsed[c] = parsed[c].map(_normalize_text)
    if "is_group_work" in parsed.columns:
        parsed["is_group_work"] = parsed["is_group_work"].map(lambda x: str(x).strip().lower() in ["1", "true", "是", "y", "yes", "群組", "同時作業"])

    before = len(parsed)
    required_blank = (
        parsed["employee_id"].map(_normalize_text).eq("")
        | parsed["work_order"].map(_normalize_text).eq("")
        | parsed["process_name"].map(_normalize_text).eq("")
        | (parsed["start_timestamp"].map(_normalize_text).eq("") & (parsed["start_date"].map(_normalize_text).eq("") | parsed["start_time"].map(_normalize_text).eq("")))
    )
    parsed = parsed[~required_blank].copy()
    dropped = before - len(parsed)
    if dropped > 0:
        warnings.append(f"已略過 {dropped} 筆缺少工號、製令、工段或開始時間的資料列。")
    return _ensure_history_cols(parsed), warnings


def parse_pasted_history(raw: str) -> tuple[pd.DataFrame, bool, list[str]]:
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [_split_paste_line(line) for line in lines]
    if not rows:
        return _ensure_history_cols(pd.DataFrame()), False, ["尚未貼上資料。"]
    has_header = _row_looks_like_header(rows[0])
    if has_header:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])
    else:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows)
    parsed, warnings = parse_history_dataframe(source)
    if not has_header:
        # parse_history_dataframe already adds default-order warning if needed; make it explicit for paste users.
        if not any("預設順序" in w for w in warnings):
            warnings.append("未偵測到標題列，已用預設順序解析。")
    return parsed, has_header, warnings


def _download_history_template():
    template = pd.DataFrame([
        {
            "狀態 / Status": "已結束",
            "製令 / Work Order": "21M0241-01",
            "P/N / Part No.": "4TRSC020-004-02",
            "機型 / Type": "NTB 3 PORT",
            "工段名稱 / Process": "配電",
            "工號 / Employee ID": "B002",
            "姓名 / Name": "張文品",
            "開始時間戳 / Start Timestamp": "2026-05-15 08:30:00",
            "結束時間戳 / End Timestamp": "2026-05-15 10:30:00",
            "備註 / Remark": "Excel 匯入範例",
            "組立地點 / Assembly Location": "竹東",
        }
    ])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        template.to_excel(writer, index=False, sheet_name="歷史紀錄匯入範本")
    return bio.getvalue()


employees = load_employees(active_only=False)
work_orders = load_work_orders(active_only=False)

c1, c2, c3, c4 = st.columns(4)
start = c1.date_input("開始日期 / Start Date", value=today_date() - timedelta(days=7))
end = c2.date_input("結束日期 / End Date", value=today_date())
emp_opts = [""] + ([] if employees.empty else employees["employee_id"].astype(str).tolist())
wo_opts = [""] + ([] if work_orders.empty else work_orders["work_order"].astype(str).tolist())
emp = c3.selectbox("工號 / Employee ID", emp_opts)
wo = c4.selectbox("製令 / Work Order", wo_opts)

df = load_records(str(start), str(end), emp or None, wo or None)

m1, m2, m3, m4 = st.columns(4)
m1.metric("筆數 / Records", f"{len(df):,}")
m2.metric("總工時 / Total Time", hours_to_hms(df['work_hours'].sum()) if not df.empty else "00:00:00")
m3.metric("作業中 / Active", f"{(df['end_timestamp'].isna()).sum():,}" if not df.empty else "0")
m4.metric("人員數 / Employees", f"{df['employee_id'].nunique():,}" if not df.empty else "0")

can_edit = check_permission("02_history", "can_edit")
can_delete = check_permission("02_history", "can_delete")

tab1, tab2, tab3 = st.tabs(["歷史明細編輯", "Excel 匯入", "貼上資料"])

with tab1:
    st.subheader("歷史明細編輯 / Editable History")
    if not can_edit:
        st.info("目前帳號只有查詢權限；若需修改或刪除歷史紀錄，請由管理員在權限管理開放 02 歷史紀錄的編輯/刪除權限。")
        render_table(df, "history_records", editable=False, height=520)
    else:
        edit_key = "history_edit_enabled"
        if edit_key not in st.session_state:
            st.session_state[edit_key] = False
        ec1, ec2, ec3 = st.columns([1, 1, 2])
        if ec1.button("✏️ 啟動編輯 / Enable Edit", use_container_width=True, key="history_enable_edit"):
            st.session_state[edit_key] = True
            rerun()
        if ec2.button("🔒 停止編輯 / Stop Edit", use_container_width=True, key="history_stop_edit"):
            st.session_state[edit_key] = False
            rerun()
        ec3.info("編輯啟動後可修改資料；勾選『刪除』後可整列刪除。刪除需具備 can_delete 權限。")

        if st.session_state[edit_key]:
            edit_df = df.copy()
            if "刪除" not in edit_df.columns:
                edit_df.insert(0, "刪除", False)
            st.info("V1.97：表格內輸入或勾選不會立即重算；選擇動作後按確認執行才會儲存、重算或刪除。")
            with st.form("history_records_commit_form", clear_on_submit=False):
                edited = render_table(edit_df, "history_records", editable=True, disabled=["id", "record_key", "created_at", "updated_at"], key="history_editor", height=560)
                history_action = st.radio(
                    "確認後執行動作",
                    ["儲存編輯", "重新計算勾選紀錄工時", "刪除勾選整列紀錄"],
                    horizontal=True,
                    key="history_action",
                )
                submitted_history = st.form_submit_button("✅ 確認執行 / Confirm", type="primary", use_container_width=True)

            if submitted_history and edited is not None:
                try:
                    delete_rows = edited[edited["刪除"].astype(bool)] if "刪除" in edited.columns else pd.DataFrame()
                    delete_ids = [int(x) for x in delete_rows["id"].dropna().tolist()]
                except Exception:
                    delete_ids = []

                if history_action == "儲存編輯":
                    save_df = edited.drop(columns=["刪除"], errors="ignore")
                    count = save_time_records(save_df)
                    st.success(f"已儲存 {count} 筆歷史紀錄。")
                    rerun()
                elif history_action == "重新計算勾選紀錄工時":
                    if not delete_ids:
                        st.warning("請先在『刪除』勾選欄勾選要重新計算的紀錄，再按確認執行。")
                    else:
                        count = recalculate_time_records(delete_ids)
                        st.success(f"已重新計算 {count} 筆工時。")
                        rerun()
                else:
                    if not can_delete:
                        st.error("權限不足：你沒有刪除歷史紀錄權限。")
                    elif not delete_ids:
                        st.warning("請先在『刪除』勾選欄勾選要刪除的紀錄，再按確認執行。")
                    else:
                        count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")
                        st.success(f"已刪除 {count} 筆歷史紀錄。")
                        rerun()
        else:
            render_table(df, "history_records", editable=False, height=520)

    if not df.empty:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="歷史紀錄")
        st.download_button("下載 Excel / Export Excel", data=bio.getvalue(), file_name=f"SPT_歷史紀錄_{start}_{end}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    if not can_edit:
        st.warning("目前帳號沒有 02 歷史紀錄編輯權限，不能匯入歷史資料。")
    else:
        st.download_button(
            "下載歷史紀錄匯入範本 / Download Template",
            data=_download_history_template(),
            file_name="SPT_歷史紀錄匯入範本.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        uploaded = st.file_uploader("上傳歷史紀錄 Excel", type=["xlsx", "xlsm", "xls"], key="history_excel_upload_v197")
        recalc_excel = st.checkbox("匯入時依 13｜系統設定休息時間重新計算工時", value=True, key="history_excel_recalc_v197")
        if uploaded is not None:
            try:
                source_df = pd.read_excel(uploaded)
                parsed, warnings = parse_history_dataframe(source_df)
                st.caption("原始 Excel 預覽 / Source Preview")
                st.dataframe(source_df.head(30), use_container_width=True, height=220)
                for msg in warnings:
                    st.warning(msg)
                if parsed.empty:
                    st.error("解析後沒有可匯入資料。請確認至少包含：工號、製令、工段、開始時間。")
                else:
                    st.success(f"已解析 {len(parsed)} 筆歷史工時資料。")
                    st.dataframe(parsed, use_container_width=True, height=360)
                    if st.button("💾 確認匯入 Excel 歷史紀錄 / Import Excel History", type="primary", use_container_width=True, key="history_excel_import_save_v197"):
                        result = import_time_records(parsed, recalc=recalc_excel, source="history_excel_import")
                        st.success(f"匯入完成：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。")
                        for msg in result.get("errors", [])[:10]:
                            st.warning(msg)
                        rerun()
            except Exception as exc:
                st.error(f"Excel 匯入失敗：{exc}")

with tab3:
    st.subheader("貼上資料 / Paste Data")
    if not can_edit:
        st.warning("目前帳號沒有 02 歷史紀錄編輯權限，不能貼上匯入歷史資料。")
    else:
        st.caption("支援從 Excel 複製整批資料貼上。建議包含標題列：狀態、製令、P/N、機型、工段名稱、工號、姓名、開始時間戳、結束時間戳、備註、組立地點。")
        raw = st.text_area("貼上 Excel 複製的歷史紀錄資料", height=260, key=HISTORY_PASTE_RAW_KEY)
        recalc_paste = st.checkbox("貼上匯入時依 13｜系統設定休息時間重新計算工時", value=True, key="history_paste_recalc_v197")
        if raw.strip():
            parsed, has_header, warnings = parse_pasted_history(raw)
            if has_header:
                st.success("已偵測到標題列，並依標題列自動對應欄位。")
            for msg in warnings:
                st.warning(msg)
            if parsed.empty:
                st.error("解析後沒有可匯入資料。請確認至少包含：工號、製令、工段、開始時間。")
            else:
                st.success(f"已解析 {len(parsed)} 筆歷史工時資料。")
                st.dataframe(parsed, use_container_width=True, height=360)
                if st.button("💾 直接儲存貼上歷史紀錄 / Save Pasted History", type="primary", use_container_width=True, key="history_paste_save_v197"):
                    result = import_time_records(parsed, recalc=recalc_paste, source="history_paste_import")
                    st.success(f"貼上資料已匯入：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}。")
                    for msg in result.get("errors", [])[:10]:
                        st.warning(msg)
                    rerun()
        else:
            st.info("請先貼上 Excel 資料。")
