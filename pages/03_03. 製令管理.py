# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
import pandas as pd
import streamlit as st

try:
    from services.theme_service import apply_theme, render_header
except Exception:
    def apply_theme():
        pass
    def render_header(title: str, subtitle: str = ""):
        st.title(title)
        if subtitle:
            st.caption(subtitle)

from services.crud_table_service import load_work_orders, save_work_orders

try:
    from services.security_service import require_module_access
except Exception:
    def require_module_access(module_code: str):
        return True

st.set_page_config(page_title="03. 製令管理", page_icon="⧠", layout="wide")
apply_theme()
require_module_access("03_work_orders")
render_header("03｜製令管理", "Excel 匯入、貼上資料、手動新增、頁面編輯、刪除、全選與存檔")

STATE_KEY = "v138_work_orders_editor"
COLS = ["_delete", "id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLS:
        if c not in df.columns:
            df[c] = False if c in ["_delete", "is_active"] else ""
    return df[COLS]


def _normalize_text(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def _split_paste_line(line: str) -> list[str]:
    line = line.strip()
    if "\t" in line:
        return [x.strip() for x in line.split("\t")]
    if "," in line:
        return [x.strip() for x in line.split(",")]
    parts = [x.strip() for x in re.split(r"\s{2,}", line) if x.strip()]
    if len(parts) <= 1:
        parts = [x.strip() for x in line.split()]
    return parts


def _normalize_header_name(v) -> str:
    """Normalize pasted/Excel header names for robust mapping."""
    text = "" if pd.isna(v) else str(v)
    text = text.strip().lower()
    for ch in [" ", "\t", "\n", "\r", "_", "-", "－", "—", "/", "／", "\\", ".", "．", "：", ":", "（", "）", "(", ")"]:
        text = text.replace(ch, "")
    return text


def _is_truthy(v) -> bool:
    text = _normalize_text(v).lower()
    if text in ["", "0", "false", "否", "n", "no", "停用", "disabled", "inactive"]:
        return False
    return True


def _find_col(source: pd.DataFrame, aliases: list[str]):
    norm_to_col = {_normalize_header_name(c): c for c in source.columns}
    norm_aliases = [_normalize_header_name(a) for a in aliases]
    for alias in norm_aliases:
        if alias in norm_to_col:
            return norm_to_col[alias]
    # Fuzzy contains match for messy Excel headers like「製令 / Work Order」
    for alias in norm_aliases:
        for norm_col, real_col in norm_to_col.items():
            if alias and (alias in norm_col or norm_col in alias):
                return real_col
    return None


def _pick_series(source: pd.DataFrame, aliases: list[str], default=""):
    col = _find_col(source, aliases)
    if col is None:
        return default
    return source[col]


def _row_looks_like_header(row: list[str], alias_groups: dict[str, list[str]]) -> bool:
    norm_row = {_normalize_header_name(x) for x in row}
    hits = 0
    for aliases in alias_groups.values():
        norm_aliases = {_normalize_header_name(a) for a in aliases}
        if norm_row & norm_aliases:
            hits += 1
    return hits >= 1


def parse_pasted_work_orders(raw: str) -> tuple[pd.DataFrame, bool, list[str]]:
    """Parse pasted work order data by header names when a header row exists.

    支援有標題列依欄名自動對應，不再依欄位順序硬吃資料。
    可辨識範例：製令、P/N、料號、Type、機型、組立地點、客戶、備註、啟用。
    無標題列時才使用預設順序：製令、P/N、機型、組立地點、客戶、備註。
    """
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [_split_paste_line(line) for line in lines]
    warnings: list[str] = []
    if not rows:
        return ensure_cols(pd.DataFrame()), False, warnings

    alias_groups = {
        "work_order": ["製令", "工單", "工令", "製令號碼", "製令編號", "mo", "wo", "work order", "work_order", "工單號碼"],
        "part_no": ["p/n", "pn", "part no", "part_no", "part number", "料號", "品號", "圖號"],
        "type_name": ["type", "type name", "type_name", "機型", "型號", "機種", "model"],
        "assembly_location": ["組立地點", "組裝地點", "組立位置", "地點", "assembly location", "assembly_location", "location"],
        "customer": ["客戶", "客戶別", "customer", "client", "客戶名稱"],
        "note": ["備註", "note", "remark", "remarks", "說明", "memo"],
        "is_active": ["啟用", "active", "is active", "is_active", "狀態", "有效"],
    }

    has_header = _row_looks_like_header(rows[0], alias_groups)

    if has_header:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])

        work_order = _pick_series(source, alias_groups["work_order"])
        part_no = _pick_series(source, alias_groups["part_no"])
        type_name = _pick_series(source, alias_groups["type_name"])
        assembly_location = _pick_series(source, alias_groups["assembly_location"])
        customer = _pick_series(source, alias_groups["customer"])
        note = _pick_series(source, alias_groups["note"])
        active_series = _pick_series(source, alias_groups["is_active"], default=None)

        if isinstance(work_order, str):
            warnings.append("找不到『製令』欄位，資料將無法儲存。請確認標題列包含：製令 / 工單 / WO / MO。")

        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": work_order,
            "part_no": part_no,
            "type_name": type_name,
            "assembly_location": assembly_location,
            "customer": customer,
            "note": note,
            "is_active": True if active_series is None else active_series.map(_is_truthy),
            "created_at": "",
            "updated_at": "",
        })
    else:
        padded = [r + [""] * (6 - len(r)) for r in rows]
        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": [r[0] for r in padded],
            "part_no": [r[1] for r in padded],
            "type_name": [r[2] for r in padded],
            "assembly_location": [r[3] for r in padded],
            "customer": [r[4] for r in padded],
            "note": [r[5] for r in padded],
            "is_active": True,
            "created_at": "",
            "updated_at": "",
        })
        warnings.append("未偵測到標題列，已用預設順序解析：製令、P/N、機型、組立地點、客戶、備註。")

    for c in ["work_order", "part_no", "type_name", "assembly_location", "customer", "note"]:
        df[c] = df[c].map(_normalize_text)
    before = len(df)
    df = df[df["work_order"] != ""].copy()
    dropped = before - len(df)
    if dropped > 0:
        warnings.append(f"已略過 {dropped} 筆沒有製令的資料列。")
    return ensure_cols(df), has_header, warnings

def reload_data():
    df = load_work_orders()
    df.insert(0, "_delete", False)
    st.session_state[STATE_KEY] = ensure_cols(df)



def _excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe = str(name)[:31] or "Sheet1"
            df.to_excel(writer, index=False, sheet_name=safe)
    return bio.getvalue()

def _read_excel_source(uploaded=None, path_text: str = "") -> dict[str, pd.DataFrame]:
    if uploaded is not None:
        return pd.read_excel(uploaded, sheet_name=None)
    path_text = str(path_text or "").strip().strip('"')
    if not path_text:
        return {}
    path = Path(path_text)
    if path.is_dir():
        files = sorted(list(path.glob("*.xlsx")) + list(path.glob("*.xlsm")) + list(path.glob("*.xls")), key=lambda x: x.stat().st_mtime, reverse=True)
        if not files:
            return {}
        path = files[0]
    if not path.exists():
        return {}
    return pd.read_excel(path, sheet_name=None)

def _map_excel_work_orders(df_raw: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return ensure_cols(pd.DataFrame())
    out = pd.DataFrame()
    out["_delete"] = False
    out["id"] = ""
    for target, default in [("work_order", ""), ("part_no", ""), ("type_name", ""), ("assembly_location", ""), ("customer", ""), ("note", "")]:
        col = mapping.get(target, "")
        out[target] = df_raw[col].map(_normalize_text) if col in df_raw.columns else default
    active_col = mapping.get("is_active", "")
    out["is_active"] = df_raw[active_col].map(_is_truthy) if active_col in df_raw.columns else True
    out["created_at"] = ""
    out["updated_at"] = ""
    out = out[out["work_order"].astype(str).str.strip() != ""].copy()
    return ensure_cols(out)

def _compare_work_orders(incoming: pd.DataFrame, current: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inc = incoming.copy()
    cur = current.copy()
    inc_keys = set(inc["work_order"].astype(str).str.strip()) if not inc.empty else set()
    cur_keys = set(cur["work_order"].astype(str).str.strip()) if not cur.empty else set()
    add_df = inc[inc["work_order"].astype(str).str.strip().isin(inc_keys - cur_keys)].copy()
    del_df = cur[cur["work_order"].astype(str).str.strip().isin(cur_keys - inc_keys)].copy()
    upd_df = inc[inc["work_order"].astype(str).str.strip().isin(inc_keys & cur_keys)].copy()
    return add_df, upd_df, del_df

if STATE_KEY not in st.session_state:
    reload_data()


tab1, tab2, tab3, tab4 = st.tabs(["製令清單編輯", "Excel 匯入", "貼上資料", "OneDrive 對應更新"])

with tab1:
    st.subheader("製令清單編輯 / Editable Work Orders")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("⊕ 新增空白列", use_container_width=True):
        blank = pd.DataFrame([{
            "_delete": False, "id": "", "work_order": "", "part_no": "", "type_name": "",
            "assembly_location": "", "customer": "", "note": "", "is_active": True,
            "created_at": "", "updated_at": ""
        }])
        st.session_state[STATE_KEY] = pd.concat([blank, st.session_state[STATE_KEY]], ignore_index=True)
        rerun()
    if c2.button("◈ 啟用全選", use_container_width=True):
        st.session_state[STATE_KEY]["is_active"] = True
        rerun()
    if c3.button("◌ 啟用全取消", use_container_width=True):
        st.session_state[STATE_KEY]["is_active"] = False
        rerun()
    if c4.button("⊖ 刪除欄全選", use_container_width=True):
        st.session_state[STATE_KEY]["_delete"] = True
        rerun()
    if c5.button("◌ 刪除欄取消", use_container_width=True):
        st.session_state[STATE_KEY]["_delete"] = False
        rerun()
    if c6.button("⟳ 重新載入", use_container_width=True):
        reload_data()
        rerun()

    st.warning("勾選「刪除 / Delete」後按下儲存，才會真正刪除資料。製令 / Work Order 為必填。")
    cur_export_df = load_work_orders()
    dl1, dl2 = st.columns(2)
    dl1.download_button("⟰ 下載目前製令清單 / Export Work Orders", data=_excel_bytes({"work_orders": cur_export_df}), file_name="SPT_製令清單.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    tpl = pd.DataFrame(columns=["製令", "P/N", "機型", "組立地點", "客戶", "備註", "啟用"])
    dl2.download_button("⟰ 下載製令匯入範本 / Download Template", data=_excel_bytes({"template": tpl}), file_name="SPT_製令匯入範本.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    st.info("V1.89：製令清單已改成確認後才儲存。表格內輸入、勾選、換格不會立即觸發存檔或整頁重算。")
    with st.form("work_orders_commit_form", clear_on_submit=False):
        edited = st.data_editor(
            st.session_state[STATE_KEY],
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            height=560,
            column_order=COLS,
            column_config={
                "_delete": st.column_config.CheckboxColumn("刪除 / Delete", width="small"),
                "id": st.column_config.NumberColumn("ID / ID", disabled=True, width="small"),
                "work_order": st.column_config.TextColumn("製令 / Work Order", required=True, width="medium"),
                "part_no": st.column_config.TextColumn("P/N / Part No.", width="medium"),
                "type_name": st.column_config.TextColumn("機型 / Type", width="large"),
                "assembly_location": st.column_config.TextColumn("組立地點 / Assembly Location", width="medium"),
                "customer": st.column_config.TextColumn("客戶 / Customer", width="medium"),
                "note": st.column_config.TextColumn("備註 / Note", width="large"),
                "is_active": st.column_config.CheckboxColumn("啟用 / Active", width="small"),
                "created_at": st.column_config.TextColumn("建立時間 / Created At", disabled=True, width="medium"),
                "updated_at": st.column_config.TextColumn("更新時間 / Updated At", disabled=True, width="medium"),
            },
            key="work_orders_data_editor_v189",
        )
        submitted_work_orders = st.form_submit_button("▣ 確認儲存製令清單 / Save Work Orders", type="primary", use_container_width=True)

    if submitted_work_orders:
        st.session_state[STATE_KEY] = ensure_cols(edited)
        result = save_work_orders(st.session_state[STATE_KEY])
        reload_data()
        st.success(f"儲存完成：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}")
        rerun()

with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    uploaded = st.file_uploader("上傳製令 Excel", type=["xlsx", "xlsm", "xls"], key="wo_excel_upload_v243")
    if uploaded is not None:
        sheets = pd.read_excel(uploaded, sheet_name=None)
        sheet = st.selectbox("選擇活頁 / Select Sheet", list(sheets.keys()), key="wo_excel_sheet_v243")
        source_df = sheets[sheet]
        st.dataframe(source_df, use_container_width=True, height=280)
        parsed = parse_pasted_work_orders(source_df.to_csv(sep="\t", index=False))[0] if not source_df.empty else ensure_cols(pd.DataFrame())
        st.success(f"已解析 {len(parsed)} 筆製令資料。")
        st.dataframe(parsed[["work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active"]], use_container_width=True, height=300)
        if st.button("▣ 確認匯入 Excel 製令 / Import Excel Work Orders", type="primary", use_container_width=True, key="wo_excel_import_confirm_v243"):
            result = save_work_orders(parsed)
            reload_data()
            st.success(f"Excel 匯入完成：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}")
            rerun()

with tab3:
    st.subheader("貼上資料 / Paste Data")
    st.caption("V1.38 loaded｜支援『有標題列』貼上，系統會依標題列名稱自動對應欄位。")
    st.caption("有標題列支援：製令、P/N、料號、Type、機型、組立地點、客戶、備註、啟用。無標題列時才用預設順序。")
    raw = st.text_area("貼上 Excel 複製資料", height=260, key="work_orders_paste_raw_v138")

    if raw.strip():
        parsed, has_header, parse_warnings = parse_pasted_work_orders(raw)
        if parsed.empty:
            st.error("解析後沒有可儲存資料。請確認至少包含：製令。")
        else:
            if has_header:
                st.success(f"已偵測到標題列，並依標題列自動對應欄位；已解析 {len(parsed)} 筆製令資料。")
            else:
                st.success(f"已解析 {len(parsed)} 筆製令資料。請確認下方預覽後，可直接存檔或加入清單編輯。")
            for msg in parse_warnings:
                st.warning(msg)

            a1, a2 = st.columns(2)
            if a1.button("⊕ 加入清單編輯 / Add to Editor", type="secondary", use_container_width=True, key="add_pasted_work_orders_to_editor_v138"):
                st.session_state[STATE_KEY] = pd.concat([parsed, st.session_state[STATE_KEY]], ignore_index=True)
                st.success("已加入『製令清單編輯』頁，請切回第一個頁籤確認後按儲存。")

            if a2.button("▣ 直接儲存貼上資料 / Save Pasted Work Orders", type="primary", use_container_width=True, key="save_pasted_work_orders_v138"):
                result = save_work_orders(parsed)
                reload_data()
                st.success(f"貼上資料已儲存：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}")
                rerun()

            st.markdown("### 解析後資料預覽 / Parsed Preview")
            st.dataframe(
                parsed[["work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active"]],
                use_container_width=True,
                height=360,
            )
    else:
        st.info("請先貼上 Excel 資料。建議包含標題列，例如：製令、P/N、機型、組立地點、客戶、備註。")


with tab4:
    st.subheader("OneDrive 製令主檔對應更新 / OneDrive Work Order Sync")
    st.info("此功能不會一直連線；只有按下『讀取來源』或『確認套用對應更新』才執行。Streamlit Cloud 無法直接瀏覽公司電腦 OneDrive，若部署在公司電腦可輸入 OneDrive 檔案或資料夾路徑；Cloud 環境請用上傳檔案。")
    path_text = st.text_input("OneDrive 檔案或資料夾路徑 / OneDrive file or folder path", placeholder=r"D:\OneDrive - 超慧科技股份有限公司\...\製令.xlsx")
    uploaded_od = st.file_uploader("或上傳 OneDrive 匯出的製令 Excel", type=["xlsx", "xlsm", "xls"], key="wo_onedrive_upload_v243")
    if st.button("⌕ 讀取來源 / Load Source", use_container_width=True, key="wo_onedrive_load_v243"):
        sheets = _read_excel_source(uploaded_od, path_text)
        if not sheets:
            st.error("讀取不到 Excel 來源。請確認路徑、檔案存在，或改用上傳檔案。")
        else:
            st.session_state["wo_onedrive_sheets_v243"] = {k: v for k, v in sheets.items()}
            st.success(f"已讀取 {len(sheets)} 個活頁。")
    sheets = st.session_state.get("wo_onedrive_sheets_v243", {})
    if sheets:
        sheet = st.selectbox("選擇活頁 / Select Sheet", list(sheets.keys()), key="wo_onedrive_sheet_select_v243")
        src = sheets[sheet]
        st.dataframe(src.head(30), use_container_width=True, height=260)
        cols = [""] + list(src.columns.astype(str))
        st.markdown("### 欄位對應 / Column Mapping")
        m1, m2, m3 = st.columns(3)
        mapping = {
            "work_order": m1.selectbox("製令 / Work Order", cols, index=next((i for i,c in enumerate(cols) if '製令' in c or 'work order' in c.lower()), 0)),
            "part_no": m2.selectbox("P/N / Part No.", cols, index=next((i for i,c in enumerate(cols) if 'p/n' in c.lower() or '料號' in c), 0)),
            "type_name": m3.selectbox("機型 / Type", cols, index=next((i for i,c in enumerate(cols) if '機型' in c or 'type' in c.lower()), 0)),
            "assembly_location": m1.selectbox("組立地點 / Assembly Location", cols, index=next((i for i,c in enumerate(cols) if '組立' in c or 'assembly' in c.lower()), 0)),
            "customer": m2.selectbox("客戶 / Customer", cols, index=next((i for i,c in enumerate(cols) if '客戶' in c or 'customer' in c.lower()), 0)),
            "note": m3.selectbox("備註 / Note", cols, index=next((i for i,c in enumerate(cols) if '備註' in c or 'note' in c.lower()), 0)),
            "is_active": m1.selectbox("啟用 / Active", cols, index=next((i for i,c in enumerate(cols) if '啟用' in c or 'active' in c.lower()), 0)),
        }
        incoming = _map_excel_work_orders(src, mapping)
        current = load_work_orders()
        add_df, upd_df, del_df = _compare_work_orders(incoming, current)
        a, b, c = st.columns(3)
        a.metric("將新增 / New", len(add_df))
        b.metric("將更新 / Update", len(upd_df))
        c.metric("來源不存在 / Delete Candidates", len(del_df))
        with st.expander("新增製令預覽 / New Work Orders", expanded=False):
            st.dataframe(add_df, use_container_width=True, height=220)
        with st.expander("更新製令預覽 / Update Work Orders", expanded=False):
            st.dataframe(upd_df, use_container_width=True, height=220)
        with st.expander("可刪除製令預覽 / Delete Candidates", expanded=False):
            st.dataframe(del_df, use_container_width=True, height=220)
        do_delete = st.checkbox("同步刪除來源不存在的舊製令 / Delete old work orders not in source", value=False, key="wo_sync_delete_missing_v243")
        if st.button("▣ 確認套用對應更新 / Apply Mapped Sync", type="primary", use_container_width=True, key="wo_onedrive_apply_v243"):
            save_df = incoming.copy()
            if do_delete and not del_df.empty:
                del_mark = del_df.copy()
                del_mark["_delete"] = True
                save_df = pd.concat([save_df, del_mark], ignore_index=True)
            result = save_work_orders(save_df)
            reload_data()
            st.success(f"製令同步完成：新增/覆寫 {result['inserted']}，更新 {result['updated']}，刪除 {result['deleted']}，略過 {result['skipped']}。新增：{', '.join(add_df['work_order'].head(20).astype(str).tolist()) or '無'}；刪除：{', '.join(del_df['work_order'].head(20).astype(str).tolist()) if do_delete else '未執行刪除'}")
            rerun()
