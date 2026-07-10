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

from services.crud_table_service import load_work_orders, save_work_orders, get_conn, ensure_tables, now_text
try:
    from services.table_ui_service import apply_column_order, load_widths, load_column_order, save_widths, save_column_order
except Exception:
    def apply_column_order(table_key, df):
        return df
    def load_widths(table_key):
        return {}
    def load_column_order(table_key):
        return []
    def save_widths(table_key, widths):
        return None
    def save_column_order(table_key, order):
        return None

try:
    from services.work_order_sync_settings_service import (
        get_sheet_setting,
        save_sheet_setting,
        clear_work_order_sync_settings,
    )
except Exception:
    def get_sheet_setting(sheet_name: str):
        return {"header_row": 1, "mapping": {}, "delete_missing": False}
    def save_sheet_setting(sheet_name: str, header_row: int, mapping: dict, delete_missing: bool = False):
        return {}
    def clear_work_order_sync_settings():
        return None

try:
    from services.security_service import require_module_access
except Exception:
    def require_module_access(module_code: str):
        return True

st.set_page_config(page_title="03. 製令管理", page_icon="⧠", layout="wide")
apply_theme()
require_module_access("03_work_orders")
render_header("03｜製令管理", "Excel 匯入、貼上資料、手動新增、頁面編輯、刪除、全選與存檔")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("03", "製令管理")
except Exception:
    _SPT_V40_PAGE_TOKEN = None

STATE_KEY = "v138_work_orders_editor"
EDITOR_VERSION_KEY = "v253_work_orders_editor_version"
EDITOR_IGNORE_RETURN_KEY = "v263_work_orders_ignore_next_editor_return"
BASELINE_KEY = "v30073_work_orders_editor_save_baseline"
COLS = ["_delete", "id", "work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]

# V61：表格實際欄名也改成與 10｜權限管理相同的中英雙語欄名。
# 內部儲存仍維持 canonical 欄位，避免影響其他模組串接。
DISPLAY_COLUMNS = {
    "_delete": "刪除 / Delete",
    "id": "ID / ID",
    "work_order": "製令 / Work Order",
    "part_no": "P/N / Part No.",
    "type_name": "機型 / Type",
    "category": "類別 / Category",
    "assembly_location": "組立地點 / Assembly Location",
    "customer": "客戶 / Customer",
    "note": "備註 / Note",
    "is_active": "啟用 / Active",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
}
DISPLAY_TO_INTERNAL = {v: k for k, v in DISPLAY_COLUMNS.items()}
EDITOR_COLS = [DISPLAY_COLUMNS[c] for c in COLS]
V30067_WORK_ORDER_TABLE_KEY = "03_work_order_editor_main_v30067"

def _v30067_width(table_key: str, col: str, default: str = "medium"):
    try:
        widths = load_widths(table_key)
        raw = widths.get(str(col), default) if isinstance(widths, dict) else default
        if isinstance(raw, (int, float)):
            return max(60, min(700, int(raw)))
        val = str(raw or default).strip()
        if val in {"small", "medium", "large"}:
            return val
        if val.replace(".", "", 1).isdigit():
            return max(60, min(700, int(float(val))))
        return default
    except Exception:
        return default


def _v30071_safe_widget_part(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", str(text or "table")).strip("_") or "table"


def _v30071_current_column_order(table_key: str, df: pd.DataFrame) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    current = [str(c) for c in df.columns]
    current_set = set(current)
    try:
        saved = [str(c) for c in (load_column_order(table_key) or [])]
    except Exception:
        saved = []
    out: list[str] = []
    seen: set[str] = set()
    for col in saved:
        if col in current_set and col not in seen:
            out.append(col)
            seen.add(col)
    for col in current:
        if col not in seen:
            out.append(col)
            seen.add(col)
    return out


def _v30071_render_work_order_column_settings(table_key: str, df: pd.DataFrame, title: str) -> None:
    """03 page-local column settings using the same lightweight style as 02 History.

    The old 03 panel rendered every column as width/order number inputs immediately.
    This version keeps only one page-owned panel, shows a lightweight header by
    default, and builds the editor only after the user explicitly opens it.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return
    safe_key = _v30071_safe_widget_part(table_key)
    current_cols = [str(c) for c in df.columns]
    with st.expander(title, expanded=False):
        st.caption("此區只管理 03 製令清單表格的欄位順序與欄寬；不會修改製令資料。只有按下『套用並永久儲存欄位設定』才會寫入。")
        open_editor = st.checkbox(
            "開啟欄位設定編輯器 / Open column settings editor",
            value=False,
            key=f"v30071_work_order_column_settings_open_{safe_key}",
        )
        if not open_editor:
            st.caption(f"目前表格共有 {len(current_cols)} 個欄位。為避免每次開啟製令管理都重建欄位設定編輯器，請需要調整時再開啟。")
            return

        try:
            widths = {str(k): int(float(v)) for k, v in (load_widths(table_key) or {}).items() if str(k) in current_cols}
        except Exception:
            widths = {}
        ordered = _v30071_current_column_order(table_key, df) or current_cols
        settings_rows = []
        for col in ordered:
            if col in current_cols:
                settings_rows.append({"欄位 / Column": col, "欄寬 / Width": int(widths.get(col, 140))})
        if not settings_rows:
            settings_rows = [{"欄位 / Column": c, "欄寬 / Width": int(widths.get(c, 140))} for c in current_cols]

        with st.form(f"v30071_work_order_column_settings_form_{safe_key}", clear_on_submit=False):
            order_text = st.text_area(
                "欄位順序 / Column order（每行一個欄位；上方越前面越靠左）",
                value="\n".join([str(r["欄位 / Column"]) for r in settings_rows]),
                height=190,
                key=f"v30071_work_order_column_order_text_{safe_key}",
            )
            try:
                width_df = st.data_editor(
                    pd.DataFrame(settings_rows),
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed",
                    key=f"v30071_work_order_width_editor_{safe_key}",
                    column_config={
                        "欄位 / Column": st.column_config.Column("欄位 / Column"),
                        "欄寬 / Width": st.column_config.NumberColumn("欄寬 / Width", min_value=60, max_value=700, step=10),
                    },
                    disabled=["欄位 / Column"],
                    height=260,
                )
            except Exception:
                width_df = pd.DataFrame(settings_rows)
                st.caption("欄寬表格暫時無法載入，將沿用目前欄寬。")
            b1, b2 = st.columns([1.5, 1])
            apply_settings = b1.form_submit_button("✅ 套用並永久儲存欄位設定 / Apply & Save", type="primary", use_container_width=True)
            reset_settings = b2.form_submit_button("↺ 恢復預設順序 / Reset order", use_container_width=True)

        if apply_settings:
            raw_order = [x.strip() for x in str(order_text or "").splitlines() if x.strip()]
            seen: set[str] = set()
            clean_order: list[str] = []
            for col in raw_order:
                if col in current_cols and col not in seen:
                    clean_order.append(col)
                    seen.add(col)
            for col in current_cols:
                if col not in seen:
                    clean_order.append(col)
                    seen.add(col)
            clean_widths: dict[str, int] = {}
            try:
                for _, row in width_df.iterrows():
                    col = str(row.get("欄位 / Column", "")).strip()
                    if col not in current_cols:
                        continue
                    try:
                        width = int(float(row.get("欄寬 / Width", 140)))
                    except Exception:
                        width = 140
                    clean_widths[col] = max(60, min(700, width))
            except Exception:
                clean_widths = {c: int(widths.get(c, 140)) for c in current_cols}
            try:
                save_widths(table_key, clean_widths)
                save_column_order(table_key, clean_order)
                st.success("03 製令清單欄位設定已套用並永久儲存。")
                rerun()
            except Exception as exc:
                st.error(f"欄位設定儲存失敗：{exc}")
        elif reset_settings:
            try:
                save_column_order(table_key, current_cols)
                save_widths(table_key, {c: int(widths.get(c, 140)) for c in current_cols})
                st.success("已恢復 03 製令清單預設欄位順序。")
                rerun()
            except Exception as exc:
                st.error(f"恢復預設失敗：{exc}")

BOOL_INTERNAL_COLS = ["_delete", "is_active"]
BOOL_DISPLAY_COLS = [DISPLAY_COLUMNS[c] for c in BOOL_INTERNAL_COLS]


def _editor_key() -> str:
    if EDITOR_VERSION_KEY not in st.session_state:
        st.session_state[EDITOR_VERSION_KEY] = 0
    return f"work_orders_data_editor_v253_{st.session_state[EDITOR_VERSION_KEY]}"


def _refresh_editor_widget() -> None:
    # V63：與 10｜權限管理同樣清除全域 column_settings_service 的 data_editor 草稿。
    # 原因：全域 wrapper 會用 _spt_editor_draft 保存舊畫面，若只換 key，
    # 仍可能出現「按鈕已執行、KPI 已更新，但 checkbox 畫面沒跟著變」的顯示問題。
    try:
        for _k0 in list(st.session_state.keys()):
            sk = str(_k0)
            if sk.startswith("work_orders_data_editor_v253_") or "work_orders_data_editor" in sk:
                st.session_state.pop(_k0, None)
    except Exception:
        pass
    try:
        from services.column_settings_service import clear_editor_draft
        clear_editor_draft("work_orders_data_editor")
        clear_editor_draft("work_orders")
    except Exception:
        pass
    st.session_state[EDITOR_IGNORE_RETURN_KEY] = True
    st.session_state[EDITOR_VERSION_KEY] = int(st.session_state.get(EDITOR_VERSION_KEY, 0)) + 1


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    # Accept both internal columns and bilingual editor columns, then normalize back.
    df = df.rename(columns={c: DISPLAY_TO_INTERNAL.get(c, c) for c in df.columns})
    for c in COLS:
        if c not in df.columns:
            df[c] = False if c in ["_delete", "is_active"] else ""
    for c in BOOL_INTERNAL_COLS:
        df[c] = df[c].map(_to_bool_value).fillna(False).astype(bool) if c in df.columns else False
    # V300.76: keep text fields display-safe.  Existing DB rows may contain NULL/None
    # before Category was added; do not show literal None and do not let blank
    # values hide real Category changes during delta comparison.
    for c in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "created_at", "updated_at"]:
        if c in df.columns:
            df[c] = df[c].map(_normalize_text)
    return df[COLS]


def _to_bool_value(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    text = str(v).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "啟用", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "否", ""}:
        return False
    return bool(v)


def _to_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_cols(df)
    return work.rename(columns=DISPLAY_COLUMNS)[EDITOR_COLS]


def _from_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_cols(df)


def _v30067_work_order_column_config(table_key: str) -> dict:
    """03 page-owned column configuration tied to the page-local Column Settings panel."""
    return {
        DISPLAY_COLUMNS["_delete"]: st.column_config.CheckboxColumn("刪除 / Delete", width=_v30067_width(table_key, DISPLAY_COLUMNS["_delete"], "medium")),
        DISPLAY_COLUMNS["id"]: st.column_config.NumberColumn("ID / ID", disabled=True, width=_v30067_width(table_key, DISPLAY_COLUMNS["id"], "small")),
        DISPLAY_COLUMNS["work_order"]: st.column_config.TextColumn("製令 / Work Order", required=True, width=_v30067_width(table_key, DISPLAY_COLUMNS["work_order"], "medium")),
        DISPLAY_COLUMNS["part_no"]: st.column_config.TextColumn("P/N / Part No.", width=_v30067_width(table_key, DISPLAY_COLUMNS["part_no"], "medium")),
        DISPLAY_COLUMNS["type_name"]: st.column_config.TextColumn("機型 / Type", width=_v30067_width(table_key, DISPLAY_COLUMNS["type_name"], "large")),
        DISPLAY_COLUMNS["category"]: st.column_config.TextColumn("類別 / Category", width=_v30067_width(table_key, DISPLAY_COLUMNS["category"], "medium")),
        DISPLAY_COLUMNS["assembly_location"]: st.column_config.TextColumn("組立地點 / Assembly Location", width=_v30067_width(table_key, DISPLAY_COLUMNS["assembly_location"], "medium")),
        DISPLAY_COLUMNS["customer"]: st.column_config.TextColumn("客戶 / Customer", width=_v30067_width(table_key, DISPLAY_COLUMNS["customer"], "medium")),
        DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width=_v30067_width(table_key, DISPLAY_COLUMNS["note"], "large")),
        DISPLAY_COLUMNS["is_active"]: st.column_config.CheckboxColumn("啟用 / Active", width=_v30067_width(table_key, DISPLAY_COLUMNS["is_active"], "medium")),
        DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", disabled=True, width=_v30067_width(table_key, DISPLAY_COLUMNS["created_at"], "medium")),
        DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", disabled=True, width=_v30067_width(table_key, DISPLAY_COLUMNS["updated_at"], "medium")),
    }


def _commit_current_editor_widget_state() -> None:
    """V67: commit data_editor widget delta into this page draft before any buttons/KPI read it.

    Streamlit reruns top-to-bottom.  Buttons above the table can run before the
    editor return value is copied back to STATE_KEY, so checkbox/text edits may
    appear to disappear.  This only synchronizes the in-memory draft; it does not
    save business data or change any other feature.
    """
    try:
        from services.data_editor_state_service import commit_editor_widget_state_to_session
        commit_editor_widget_state_to_session(
            state_key=STATE_KEY,
            editor_key=_editor_key(),
            to_editor_df=_to_editor_df,
            from_editor_df=_from_editor_df,
            ensure_df=ensure_cols,
        )
    except Exception:
        pass


def _current_internal_df() -> pd.DataFrame:
    _commit_current_editor_widget_state()
    return ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))


def _bulk_set_bool_column(col: str, value: bool) -> None:
    """V64: 批次按鈕必須重新指定整份 DataFrame，避免只做 in-place 修改時 Streamlit session_state / data_editor 舊草稿把畫面蓋回。"""
    df = _current_internal_df().copy()
    if col not in df.columns:
        df[col] = False
    df[col] = bool(value)
    st.session_state[STATE_KEY] = ensure_cols(df)
    _refresh_editor_widget()
    rerun()


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
    if isinstance(v, bool):
        return v
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    text = _normalize_text(v).lower()
    if text in ["", "0", "false", "否", "n", "no", "off", "unchecked", "☐", "□", "停用", "離職", "不在", "未出勤", "disabled", "inactive", "none", "nan"]:
        return False
    if text in ["1", "true", "是", "y", "yes", "on", "checked", "☑", "✅", "啟用", "在廠", "出勤", "勾選"]:
        return True
    return False


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
    可辨識範例：製令、P/N、料號、Type、機型、Category、類別、組立地點、客戶、備註、啟用。
    無標題列時保留舊順序：製令、P/N、機型、組立地點、客戶、備註；若每列有 7 欄以上，會使用：製令、P/N、機型、Category、組立地點、客戶、備註。
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
        "category": ["category", "cat", "類別", "類別/category", "類別 / category", "show category", "show_category", "分類", "機型類別", "產品類別", "製令類別"],
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
        category = _pick_series(source, alias_groups["category"])
        assembly_location = _pick_series(source, alias_groups["assembly_location"])
        customer = _pick_series(source, alias_groups["customer"])
        note = _pick_series(source, alias_groups["note"])
        active_series = _pick_series(source, alias_groups["is_active"], default=None)

        if isinstance(work_order, str):
            warnings.append("找不到『製令』欄位，資料將無法儲存。請確認標題列包含：製令 / 工單 / WO / MO。")
            return ensure_cols(pd.DataFrame()), has_header, warnings

        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": work_order,
            "part_no": part_no,
            "type_name": type_name,
            "category": category,
            "assembly_location": assembly_location,
            "customer": customer,
            "note": note,
            "is_active": True if active_series is None else active_series.map(_is_truthy),
            "created_at": "",
            "updated_at": "",
        })
    else:
        max_width = max(len(r) for r in rows)
        if max_width >= 7:
            padded = [r + [""] * (7 - len(r)) for r in rows]
            df = pd.DataFrame({
                "_delete": False,
                "id": "",
                "work_order": [r[0] for r in padded],
                "part_no": [r[1] for r in padded],
                "type_name": [r[2] for r in padded],
                "category": [r[3] for r in padded],
                "assembly_location": [r[4] for r in padded],
                "customer": [r[5] for r in padded],
                "note": [r[6] for r in padded],
                "is_active": True,
                "created_at": "",
                "updated_at": "",
            })
            warnings.append("未偵測到標題列，已用 7 欄順序解析：製令、P/N、機型、Category、組立地點、客戶、備註。")
        else:
            padded = [r + [""] * (6 - len(r)) for r in rows]
            df = pd.DataFrame({
                "_delete": False,
                "id": "",
                "work_order": [r[0] for r in padded],
                "part_no": [r[1] for r in padded],
                "type_name": [r[2] for r in padded],
                "category": "",
                "assembly_location": [r[3] for r in padded],
                "customer": [r[4] for r in padded],
                "note": [r[5] for r in padded],
                "is_active": True,
                "created_at": "",
                "updated_at": "",
            })
            warnings.append("未偵測到標題列，已用舊 6 欄順序解析：製令、P/N、機型、組立地點、客戶、備註；若要匯入 Category，建議貼上標題列或使用 7 欄順序。")

    for c in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note"]:
        df[c] = df[c].map(_normalize_text)
    before = len(df)
    df = df[df["work_order"] != ""].copy()
    dropped = before - len(df)
    if dropped > 0:
        warnings.append(f"已略過 {dropped} 筆沒有製令的資料列。")
    return ensure_cols(df), has_header, warnings

def _v30073_set_save_baseline(df: pd.DataFrame) -> None:
    """Keep a clean editor baseline so manual Save only writes changed rows.

    Before V300.73 the 03 manual editor submitted the whole work-order table to
    save_work_orders(), then immediately reloaded the table from Neon.  With a
    large master list this made one small edit feel like a full-table sync.
    This baseline is page-local only; Neon remains the authority.
    """
    base = ensure_cols(df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame())
    base["_delete"] = False
    st.session_state[BASELINE_KEY] = base.copy().reset_index(drop=True)


def reload_data():
    df = load_work_orders()
    df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
    # V66: load_work_orders() may already include the editor helper column.
    # Do not insert _delete twice; reset it and keep it as the first column.
    if "_delete" in df.columns:
        df = df.drop(columns=["_delete"])
    df.insert(0, "_delete", False)
    df = ensure_cols(df)
    st.session_state[STATE_KEY] = df
    _v30073_set_save_baseline(df)


def _v30073_row_key(row) -> str:
    rid = _normalize_text(row.get("id"))
    if rid and rid.lower() not in {"0", "none", "nan", "nat"}:
        return f"id:{rid}"
    wo = _normalize_text(row.get("work_order"))
    if wo:
        return f"wo:{wo}"
    return ""


def _v30073_same_work_order_row(new_row, old_row) -> bool:
    for col in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note"]:
        if _normalize_text(new_row.get(col)) != _normalize_text(old_row.get(col)):
            return False
    return bool(_is_truthy(new_row.get("is_active"))) == bool(_is_truthy(old_row.get("is_active")))


def _v30073_build_work_order_save_delta(current_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return only new/changed/deleted rows from the 03 manual editor.

    The data_editor contains the full master table.  Saving that whole frame is
    safe but slow on Neon because unchanged rows still need to be inspected.
    This function compares the current draft with the last authority-loaded
    baseline and sends only the real delta to the persistence service.
    """
    cur = ensure_cols(current_df.copy() if isinstance(current_df, pd.DataFrame) else pd.DataFrame())
    base = ensure_cols(st.session_state.get(BASELINE_KEY, pd.DataFrame()))
    base_by_key = {}
    base_by_wo = {}
    if not base.empty:
        for _, old in base.iterrows():
            key = _v30073_row_key(old)
            wo = _normalize_text(old.get("work_order"))
            if key:
                base_by_key[key] = old
            if wo:
                base_by_wo[wo] = old

    rows = []
    stats = {"new_or_changed": 0, "deleted": 0, "skipped_empty": 0, "unchanged": 0}
    for _, row in cur.iterrows():
        row = row.copy()
        wo = _normalize_text(row.get("work_order"))
        key = _v30073_row_key(row)
        marked_delete = bool(_is_truthy(row.get("_delete")))
        if marked_delete:
            if key or wo:
                row["_delete"] = True
                rows.append(row)
                stats["deleted"] += 1
            else:
                stats["skipped_empty"] += 1
            continue
        if not wo:
            stats["skipped_empty"] += 1
            continue
        old = base_by_key.get(key) if key else None
        if old is None:
            old = base_by_wo.get(wo)
        if old is None or not _v30073_same_work_order_row(row, old):
            row["_delete"] = False
            rows.append(row)
            stats["new_or_changed"] += 1
        else:
            stats["unchanged"] += 1
    delta = ensure_cols(pd.DataFrame(rows)) if rows else ensure_cols(pd.DataFrame())
    return delta, stats


def _v30073_editor_display_after_save(current_df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_cols(current_df.copy() if isinstance(current_df, pd.DataFrame) else pd.DataFrame())
    if not df.empty:
        delete_mask = df["_delete"].map(_to_bool_value).fillna(False).astype(bool)
        df = df.loc[~delete_mask].copy()
        df["_delete"] = False
        df = df[df["work_order"].map(_normalize_text) != ""].drop_duplicates(subset=["work_order"], keep="last").reset_index(drop=True)
    return ensure_cols(df)


def render_work_order_summary(df: pd.DataFrame):
    """Render concise work-order KPIs for 03 module.

    以目前畫面資料為準顯示總製令數，避免使用者匯入或 OneDrive 同步後
    不知道目前製令主檔到底有幾筆。
    """
    if df is None or df.empty:
        total = active = inactive = pending_delete = 0
    else:
        work_orders = df.get("work_order", pd.Series(dtype=str)).map(_normalize_text)
        valid = work_orders != ""
        total = int(valid.sum())
        active_col = df.get("is_active", pd.Series([True] * len(df)))
        active_bool = active_col.map(_is_truthy) if hasattr(active_col, "map") else pd.Series([True] * len(df))
        active = int((valid & active_bool).sum())
        inactive = int(total - active)
        delete_col = df.get("_delete", pd.Series([False] * len(df)))
        delete_bool = delete_col.map(_is_truthy) if hasattr(delete_col, "map") else pd.Series([False] * len(df))
        pending_delete = int((valid & delete_bool).sum())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("總製令數 / Total Work Orders", total)
    k2.metric("啟用製令 / Active", active)
    k3.metric("停用製令 / Inactive", inactive)
    k4.metric("待刪除 / Pending Delete", pending_delete)


def _excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe = str(name)[:31] or "Sheet1"
            df.to_excel(writer, index=False, sheet_name=safe)
    return bio.getvalue()


def _v30028_work_order_template_bytes() -> bytes:
    """Cache the static 03 import template in session to avoid rebuilding Excel bytes on every rerun."""
    key = "v30028_work_order_template_bytes"
    if key not in st.session_state:
        tpl = pd.DataFrame(columns=["製令", "P/N", "機型", "Category", "組立地點", "客戶", "備註", "啟用"])
        st.session_state[key] = _excel_bytes({"template": tpl})
    return st.session_state[key]


def _v30028_sheet_setting_cache_key(sheet_name: str) -> str:
    return f"v30028_work_order_sheet_setting::{str(sheet_name)}"


def _v30028_get_sheet_setting(sheet_name: str) -> dict:
    """Read OneDrive mapping settings once per session until the user saves/clears them."""
    key = _v30028_sheet_setting_cache_key(sheet_name)
    if key not in st.session_state:
        cfg = get_sheet_setting(sheet_name)
        st.session_state[key] = cfg if isinstance(cfg, dict) else {"header_row": 1, "mapping": {}, "delete_missing": False}
    return dict(st.session_state.get(key) or {})


def _v30028_set_sheet_setting_cache(sheet_name: str, cfg: dict | None) -> None:
    key = _v30028_sheet_setting_cache_key(sheet_name)
    if cfg is None:
        st.session_state.pop(key, None)
    else:
        st.session_state[key] = dict(cfg)


def _make_unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Excel column names to unique strings for Streamlit and mapping."""
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    seen: dict[str, int] = {}
    cols: list[str] = []
    for idx, col in enumerate(out.columns):
        name = "" if pd.isna(col) else str(col)
        name = name.replace("\u3000", " ").replace("\xa0", " ").strip()
        if not name or name.lower().startswith("unnamed"):
            name = f"欄位{idx + 1}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        if count:
            name = f"{name}__{count + 1}"
        cols.append(name)
    out.columns = cols
    return out


def _normalize_excel_sheets(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {str(k): _make_unique_columns(v) for k, v in (sheets or {}).items()}


def _read_excel_source(uploaded=None, path_text: str = "") -> dict[str, pd.DataFrame]:
    """Read Excel source as raw rows so user can choose which row is the header.

    V2.45: OneDrive / exported schedules often have titles, notes, or blank rows
    before the real header. Reading with header=None preserves the original row
    numbers and lets the user select 「標題欄是第幾列」 safely.
    """
    read_kwargs = {"sheet_name": None, "header": None, "dtype": object}
    if uploaded is not None:
        return {str(k): v for k, v in pd.read_excel(uploaded, **read_kwargs).items()}
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
    return {str(k): v for k, v in pd.read_excel(path, **read_kwargs).items()}

def _guess_header_row(df_raw: pd.DataFrame, max_scan_rows: int = 80) -> int:
    """Guess 1-based header row for messy Excel exports."""
    if df_raw is None or df_raw.empty:
        return 1
    tokens = ["製令", "work order", "p/n", "料號", "part", "機型", "type", "category", "類別", "分類", "組立", "assembly", "客戶", "customer", "備註", "note", "啟用", "active"]
    best_row = 1
    best_score = -1
    limit = min(len(df_raw), max_scan_rows)
    for i in range(limit):
        vals = [str(v).replace("\u3000", " ").replace("\xa0", " ").strip().lower() for v in df_raw.iloc[i].tolist() if str(v).strip() and str(v).lower() != "nan"]
        joined = " | ".join(vals)
        score = sum(1 for t in tokens if t in joined)
        # Prefer rows with several non-empty cells when score ties.
        score = score * 10 + min(len(vals), 9)
        if score > best_score:
            best_score = score
            best_row = i + 1
    return max(1, best_row)

def _apply_header_row(df_raw: pd.DataFrame, header_row_1based: int) -> pd.DataFrame:
    """Build a dataframe using the selected Excel row as column header."""
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
    idx = max(0, min(int(header_row_1based or 1) - 1, len(df_raw) - 1))
    headers = df_raw.iloc[idx].tolist()
    data = df_raw.iloc[idx + 1:].copy()
    data.columns = headers
    data = data.dropna(how="all").reset_index(drop=True)
    return _make_unique_columns(data)

def _map_excel_work_orders(df_raw: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return ensure_cols(pd.DataFrame())
    out = pd.DataFrame()
    out["_delete"] = False
    out["id"] = ""
    for target, default in [("work_order", ""), ("part_no", ""), ("type_name", ""), ("category", ""), ("assembly_location", ""), ("customer", ""), ("note", "")]:
        col = mapping.get(target, "")
        out[target] = df_raw[col].map(_normalize_text) if col in df_raw.columns else default
    active_col = mapping.get("is_active", "")
    out["is_active"] = df_raw[active_col].map(_is_truthy) if active_col in df_raw.columns else True
    out["created_at"] = ""
    out["updated_at"] = ""
    out = out[out["work_order"].astype(str).str.strip() != ""].copy()
    return ensure_cols(out)

def _make_unique_work_order_keys(incoming: pd.DataFrame, src: pd.DataFrame | None = None, row_key_col: str = "", header_row: int = 1) -> tuple[pd.DataFrame, dict]:
    """Make row-level unique work_order keys when the source has repeated work orders.

    製令管理的資料庫 work_order 欄位是唯一鍵。若來源排程每一列都要保留，
    就不能只用「製令」欄；本函式會優先使用來源列唯一鍵，例如「製令&出現次數」。
    若仍重複，才附加 Excel 來源列號，確保每一列都能寫入。
    """
    out = incoming.copy()
    if out.empty:
        return out, {"source_rows": 0, "base_unique": 0, "final_unique": 0, "duplicate_extra": 0}
    base = None
    if src is not None and row_key_col and row_key_col in src.columns:
        try:
            base = src.loc[out.index, row_key_col].map(_normalize_text).reset_index(drop=True)
        except Exception:
            base = src[row_key_col].map(_normalize_text).head(len(out)).reset_index(drop=True)
    if base is None:
        base = out["work_order"].map(_normalize_text).reset_index(drop=True)
    base = base.fillna("").astype(str).str.strip()
    fallback = out["work_order"].map(_normalize_text).reset_index(drop=True)
    base = base.where(base != "", fallback)

    counts = base.value_counts(dropna=False).to_dict()
    seen: dict[str, int] = {}
    final_keys: list[str] = []
    duplicate_extra = 0
    for i, key in enumerate(base.tolist()):
        key = _normalize_text(key)
        if not key:
            final_keys.append("")
            continue
        seen[key] = seen.get(key, 0) + 1
        if counts.get(key, 0) > 1:
            duplicate_extra += 1 if seen[key] > 1 else 0
            excel_row = int(header_row or 1) + 1 + i
            final_keys.append(f"{key}#R{excel_row}")
        else:
            final_keys.append(key)
    out["work_order"] = final_keys
    return out, {
        "source_rows": len(out),
        "base_unique": len(set([x for x in base.tolist() if _normalize_text(x)])),
        "final_unique": len(set([x for x in final_keys if _normalize_text(x)])),
        "duplicate_extra": duplicate_extra,
    }


WORK_ORDER_COMPARE_COLS = ["part_no", "type_name", "category", "assembly_location", "customer", "note", "is_active"]


def _work_order_row_changed(in_row: pd.Series, cur_row: pd.Series) -> bool:
    """Return True only when OneDrive source values really differ from authority.

    V300.72: The old OneDrive compare treated every existing work_order as an
    update candidate. Pressing Apply on an unchanged 1,000-row source therefore
    generated 1,000 Neon UPDATE statements and could run for minutes.
    """
    for col in WORK_ORDER_COMPARE_COLS:
        if col == "is_active":
            if _to_bool_value(in_row.get(col, True)) != _to_bool_value(cur_row.get(col, True)):
                return True
        else:
            if _normalize_text(in_row.get(col, "")) != _normalize_text(cur_row.get(col, "")):
                return True
    return False


def _compare_work_orders(incoming: pd.DataFrame, current: pd.DataFrame, collapse_duplicates: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inc = incoming.copy()
    cur = current.copy()
    if inc.empty:
        return ensure_cols(pd.DataFrame()), ensure_cols(pd.DataFrame()), ensure_cols(pd.DataFrame())
    inc["work_order"] = inc["work_order"].map(_normalize_text)
    cur["work_order"] = cur["work_order"].map(_normalize_text) if "work_order" in cur.columns else ""
    inc = inc[inc["work_order"] != ""].copy()
    if collapse_duplicates:
        # 製令主檔模式：相同製令只保留最後一筆，避免同一製令重複出現在下拉清單。
        inc = inc.drop_duplicates(subset=["work_order"], keep="last").reset_index(drop=True)
    else:
        # 來源列模式：work_order 已被轉成唯一列鍵，只防止完全相同鍵造成 DB 衝突。
        inc = inc.drop_duplicates(subset=["work_order"], keep="last").reset_index(drop=True)
    cur_keys = set(cur["work_order"].astype(str).str.strip()) if not cur.empty else set()
    inc_keys = set(inc["work_order"].astype(str).str.strip()) if not inc.empty else set()
    add_df = inc[inc["work_order"].astype(str).str.strip().isin(inc_keys - cur_keys)].copy()
    del_df = cur[cur["work_order"].astype(str).str.strip().isin(cur_keys - inc_keys)].copy()

    # V300.72: only rows whose mapped values actually changed are update candidates.
    # This is the main fix for OneDrive Apply taking several minutes when the source
    # file is unchanged or mostly unchanged.
    if not cur.empty and not inc.empty:
        cur_one = cur.drop_duplicates(subset=["work_order"], keep="last").set_index("work_order", drop=False)
        changed_mask = []
        for _, row in inc.iterrows():
            key = _normalize_text(row.get("work_order", ""))
            if key not in cur_keys:
                changed_mask.append(False)
                continue
            try:
                changed_mask.append(_work_order_row_changed(row, cur_one.loc[key]))
            except Exception:
                changed_mask.append(True)
        upd_df = inc[pd.Series(changed_mask, index=inc.index)].copy()
    else:
        upd_df = ensure_cols(pd.DataFrame())
    return ensure_cols(add_df), ensure_cols(upd_df), ensure_cols(del_df)


def _safe_join(values, limit: int = 30) -> str:
    vals = [str(x) for x in list(values)[:limit] if str(x).strip()]
    return "、".join(vals) if vals else "無"


def _build_work_order_sync_save_df(add_df: pd.DataFrame, upd_df: pd.DataFrame, del_df: pd.DataFrame, do_delete: bool) -> pd.DataFrame:
    parts = []
    if add_df is not None and not add_df.empty:
        parts.append(add_df.copy())
    if upd_df is not None and not upd_df.empty:
        parts.append(upd_df.copy())
    if do_delete and del_df is not None and not del_df.empty:
        d = del_df.copy()
        d["_delete"] = True
        parts.append(d)
    if not parts:
        return ensure_cols(pd.DataFrame())
    out = pd.concat(parts, ignore_index=True)
    out["work_order"] = out["work_order"].map(_normalize_text)
    out = out[out["work_order"] != ""].copy()
    # 儲存前再次去除新增/更新重複，刪除列保留。
    if "_delete" in out.columns:
        normal = out[~out["_delete"].astype(bool)].drop_duplicates(subset=["work_order"], keep="last")
        deletes = out[out["_delete"].astype(bool)]
        out = pd.concat([normal, deletes], ignore_index=True)
    return ensure_cols(out)



WORK_ORDER_CANONICAL_COLS = ["id", "work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]


def _v136_load_work_orders_from_sqlite_direct() -> pd.DataFrame:
    """V63: Neon/runtime-authority compatibility wrapper.

    The previous implementation read local SQLite directly. In the Neon
    consolidated runtime this must read the official DB service instead.
    """
    return ensure_cols(load_work_orders()).drop(columns=["_delete"], errors="ignore")


def _v136_sync_work_order_authority_from_sqlite(reason: str = "v136_work_order_sync") -> dict:
    """V63: no local/GitHub authority sync on page hot path.

    Neon/PostgreSQL is already the runtime authority; page 09/14 can create
    backup snapshots manually.
    """
    df = load_work_orders()
    return {"ok": True, "rows": len(df), "error": "", "backend": "neon_runtime"}


def _apply_work_order_sync_direct(add_df: pd.DataFrame, upd_df: pd.DataFrame, del_df: pd.DataFrame, do_delete: bool) -> dict:
    """Apply mapped sync through the Neon/PostgreSQL authority.

    V300.72 removes two post-write re-reads from this hot path. The caller already
    has the current table plus add/update/delete frames, so it can refresh the
    visible editor from memory and let the next manual reload read authority if needed.
    """
    parts = []
    if add_df is not None and not add_df.empty:
        a = ensure_cols(add_df.copy())
        a["_delete"] = False
        parts.append(a)
    if upd_df is not None and not upd_df.empty:
        u = ensure_cols(upd_df.copy())
        u["_delete"] = False
        parts.append(u)
    if do_delete and del_df is not None and not del_df.empty:
        d = ensure_cols(del_df.copy())
        d["_delete"] = True
        parts.append(d)
    if not parts:
        return {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0, "inserted_keys": [], "updated_keys": [], "deleted_keys": [], "authority_ok": True, "authority_rows": 0, "authority_error": ""}
    merged = pd.concat(parts, ignore_index=True)
    result = save_work_orders(merged)
    return {
        "inserted": int(result.get("inserted", 0)),
        "updated": int(result.get("updated", 0)),
        "deleted": int(result.get("deleted", 0)),
        "skipped": int(result.get("skipped", 0)),
        "inserted_keys": add_df.get("work_order", pd.Series(dtype=str)).dropna().astype(str).head(30).tolist() if add_df is not None and not add_df.empty else [],
        "updated_keys": upd_df.get("work_order", pd.Series(dtype=str)).dropna().astype(str).head(30).tolist() if upd_df is not None and not upd_df.empty else [],
        "deleted_keys": del_df.get("work_order", pd.Series(dtype=str)).dropna().astype(str).head(30).tolist() if do_delete and del_df is not None and not del_df.empty else [],
        "authority_ok": True,
        "authority_rows": int(result.get("authority_rows", 0) or 0),
        "authority_error": "",
    }


def _v30072_merge_sync_result_for_editor(current: pd.DataFrame, add_df: pd.DataFrame, upd_df: pd.DataFrame, del_df: pd.DataFrame, do_delete: bool) -> pd.DataFrame:
    """Refresh the 03 editor from in-memory sync frames without re-reading Neon."""
    cur = ensure_cols(current.copy()) if isinstance(current, pd.DataFrame) else ensure_cols(pd.DataFrame())
    cur["work_order"] = cur["work_order"].map(_normalize_text)
    if do_delete and del_df is not None and not del_df.empty:
        delete_keys = set(del_df.get("work_order", pd.Series(dtype=str)).map(_normalize_text).tolist())
        cur = cur[~cur["work_order"].isin(delete_keys)].copy()
    if upd_df is not None and not upd_df.empty:
        upd = ensure_cols(upd_df.copy())
        upd["work_order"] = upd["work_order"].map(_normalize_text)
        upd_by_key = {str(row.get("work_order", "")): row for _, row in upd.iterrows()}
        for idx, row in cur.iterrows():
            key = str(row.get("work_order", ""))
            if key in upd_by_key:
                for col in ["part_no", "type_name", "category", "assembly_location", "customer", "note", "is_active"]:
                    cur.at[idx, col] = upd_by_key[key].get(col, cur.at[idx, col])
                cur.at[idx, "updated_at"] = now_text()
    if add_df is not None and not add_df.empty:
        add = ensure_cols(add_df.copy())
        add["_delete"] = False
        add["work_order"] = add["work_order"].map(_normalize_text)
        cur = pd.concat([cur, add], ignore_index=True)
    if not cur.empty:
        cur = cur[cur["work_order"].map(_normalize_text) != ""].drop_duplicates(subset=["work_order"], keep="last").sort_values("work_order").reset_index(drop=True)
    return ensure_cols(cur)


def _v30074_apply_import_delta(parsed: pd.DataFrame, source_label: str = "import") -> dict:
    """Save Excel/Paste imports using the same delta path as OneDrive and manual edit.

    Before V300.74, the Excel import and pasted-data direct-save buttons still
    called save_work_orders(parsed) and then reload_data().  On a large master
    table that meant an import with many unchanged rows still performed a full
    service comparison and immediately re-read all work orders from Neon.

    This helper compares the incoming rows with the current page baseline first,
    writes only truly new/changed rows, and refreshes the editor from memory.
    It does not delete any existing work order because Excel/Paste import is an
    add/update workflow, not a source-of-truth replacement sync.
    """
    incoming = ensure_cols(parsed.copy() if isinstance(parsed, pd.DataFrame) else pd.DataFrame())
    current = _current_internal_df()
    add_df, upd_df, _ = _compare_work_orders(incoming, current, collapse_duplicates=True)
    planned_count = int(len(add_df) + len(upd_df))
    if planned_count <= 0:
        return {
            "inserted": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "planned_new": 0,
            "planned_update": 0,
            "planned_count": 0,
            "unchanged": int(len(incoming)),
            "authority_ok": True,
            "authority_rows": 0,
            "source_label": source_label,
        }

    result = _apply_work_order_sync_direct(add_df, upd_df, ensure_cols(pd.DataFrame()), False)
    try:
        merged = _v30072_merge_sync_result_for_editor(current, add_df, upd_df, ensure_cols(pd.DataFrame()), False)
        st.session_state[STATE_KEY] = merged
        _v30073_set_save_baseline(merged)
    except Exception:
        # Fallback keeps correctness if the in-memory merge ever fails; normal path
        # intentionally avoids this full authority read for speed.
        reload_data()
    _refresh_editor_widget()
    result["planned_new"] = int(len(add_df))
    result["planned_update"] = int(len(upd_df))
    result["planned_count"] = planned_count
    result["unchanged"] = int(max(0, len(incoming) - planned_count))
    result["source_label"] = source_label
    return result


if STATE_KEY not in st.session_state:
    reload_data()


tab1, tab2, tab3, tab4 = st.tabs(["製令清單編輯", "Excel 匯入", "貼上資料", "OneDrive 對應更新"])

with tab1:
    st.subheader("製令清單編輯 / Editable Work Orders")
    render_work_order_summary(st.session_state.get(STATE_KEY, pd.DataFrame()))

    if "v253_work_order_edit_enabled" not in st.session_state:
        st.session_state["v253_work_order_edit_enabled"] = False
    work_order_edit_enabled = bool(st.session_state.get("v253_work_order_edit_enabled", False))
    ec1, ec2, ec3 = st.columns([1.2, 1.2, 3])
    with ec1:
        if st.button("◇ 啟動編輯 / Enable Edit", use_container_width=True, disabled=work_order_edit_enabled, key="v253_enable_work_order_edit"):
            st.session_state["v253_work_order_edit_enabled"] = True
            _refresh_editor_widget()
            rerun()
    with ec2:
        if st.button("◌ 停止編輯 / Lock Edit", use_container_width=True, disabled=not work_order_edit_enabled, key="v253_disable_work_order_edit"):
            st.session_state["v253_work_order_edit_enabled"] = False
            reload_data()
            _refresh_editor_widget()
            rerun()
    with ec3:
        if work_order_edit_enabled:
            st.success("目前：已啟動編輯。修改後請按儲存才會正式寫入。")
        else:
            st.info("目前：唯讀保護。請先啟動編輯，再新增、修改、刪除、匯入或貼上製令。")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("⊕ 新增空白列 / Add Row", use_container_width=True, disabled=not work_order_edit_enabled):
        blank = pd.DataFrame([{
            "_delete": False, "id": "", "work_order": "", "part_no": "", "type_name": "", "category": "",
            "assembly_location": "", "customer": "", "note": "", "is_active": True,
            "created_at": "", "updated_at": ""
        }])
        st.session_state[STATE_KEY] = pd.concat([blank, _current_internal_df()], ignore_index=True)
        _refresh_editor_widget()
        rerun()
    if c2.button("☑ 啟用全選 / Active All", use_container_width=True, disabled=not work_order_edit_enabled, key="v64_work_order_active_all_on"):
        _bulk_set_bool_column("is_active", True)
    if c3.button("☐ 啟用取消 / Inactive All", use_container_width=True, disabled=not work_order_edit_enabled, key="v64_work_order_active_all_off"):
        _bulk_set_bool_column("is_active", False)
    if c4.button("☑ 刪除全選 / Select Delete", use_container_width=True, disabled=not work_order_edit_enabled, key="v64_work_order_delete_all_on"):
        _bulk_set_bool_column("_delete", True)
    if c5.button("☐ 刪除取消 / Clear Delete", use_container_width=True, disabled=not work_order_edit_enabled, key="v64_work_order_delete_all_off"):
        _bulk_set_bool_column("_delete", False)
    if c6.button("⟳ 重新載入 / Reload", use_container_width=True):
        reload_data()
        _refresh_editor_widget()
        rerun()

    st.warning("勾選「刪除 / Delete」後按下儲存，才會真正刪除資料。製令 / Work Order 為必填。")
    dl1, dl2 = st.columns(2)
    if dl1.button("⟰ 準備目前製令清單下載 / Prepare Export", use_container_width=True, key="v68_prepare_work_order_export"):
        export_df = _current_internal_df().drop(columns=["_delete"], errors="ignore")
        st.session_state["v68_work_order_export_bytes"] = _excel_bytes({"work_orders": export_df})
        st.session_state["v68_work_order_export_rows"] = len(export_df)
    if "v68_work_order_export_bytes" in st.session_state:
        dl1.download_button("下載目前製令清單 / Download Work Orders", data=st.session_state["v68_work_order_export_bytes"], file_name="SPT_製令清單.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="v68_download_work_order_export")
        dl1.caption(f"已準備 {st.session_state.get('v68_work_order_export_rows', 0)} 筆。")
    dl2.download_button("⟰ 下載製令匯入範本 / Download Template", data=_v30028_work_order_template_bytes(), file_name="SPT_製令匯入範本.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    st.info("V68：唯讀模式改用輕量表格顯示；按『啟動編輯』後才載入可編輯 data_editor，避免每次選擇都重繪大型編輯器。")
    if work_order_edit_enabled:
        _commit_current_editor_widget_state()
        st.session_state[STATE_KEY] = _current_internal_df()
    editor_df = _to_editor_df(st.session_state[STATE_KEY])
    editor_df = apply_column_order(V30067_WORK_ORDER_TABLE_KEY, editor_df)
    _v30071_render_work_order_column_settings(V30067_WORK_ORDER_TABLE_KEY, editor_df, title="▤ 03 製令清單欄位設定 / Work Order Column Settings")
    submitted_work_orders = False
    edited = None
    if not work_order_edit_enabled:
        st.dataframe(
            editor_df,
            hide_index=True,
            use_container_width=True,
            height=560,
            key="v30067_work_order_readonly_preview",
            column_order=[c for c in EDITOR_COLS if c in editor_df.columns],
            column_config=_v30067_work_order_column_config(V30067_WORK_ORDER_TABLE_KEY),
        )
    else:
        # V120：穩定編輯模式。把 data_editor 與儲存按鈕放在同一個 form，
        # 避免每修改一格就 rerun 跳回頁面上方；批次按鈕與原儲存邏輯不變。
        # V300.67：03 改用與 01/04/07 同概念的頁面本地欄位設定，只保留一組欄位設定面板。
        with st.form("v120_work_order_stable_editor_form", clear_on_submit=False):
            edited = st.data_editor(
                editor_df,
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                height=560,
                column_order=[c for c in EDITOR_COLS if c in editor_df.columns],
                column_config=_v30067_work_order_column_config(V30067_WORK_ORDER_TABLE_KEY),
                key=_editor_key(),
                disabled=False,
            )
            submitted_work_orders = st.form_submit_button("▣ 確認儲存製令清單 / Save Work Orders", type="primary", use_container_width=True)
        ignore_editor_return = bool(st.session_state.pop(EDITOR_IGNORE_RETURN_KEY, False))
        if isinstance(edited, pd.DataFrame) and not ignore_editor_return:
            st.session_state[STATE_KEY] = _from_editor_df(edited.copy())

    if submitted_work_orders:
        current_df = _current_internal_df()
        delta_df, delta_stats = _v30073_build_work_order_save_delta(current_df)
        deleted_count = int(delta_stats.get("deleted", 0))
        changed_count = int(delta_stats.get("new_or_changed", 0))
        skipped_empty = int(delta_stats.get("skipped_empty", 0))
        if delta_df.empty:
            display_df = _v30073_editor_display_after_save(current_df)
            st.session_state[STATE_KEY] = display_df
            _v30073_set_save_baseline(display_df)
            _refresh_editor_widget()
            st.session_state["v253_work_order_edit_enabled"] = False
            st.info("沒有偵測到需要寫入 Neon 的製令變更；已停止編輯。")
            rerun()
        else:
            result = save_work_orders(delta_df)
            # V300.73：不要在同一次儲存後 reload_data() 重新全表讀取 Neon。
            # 本次畫面資料已包含使用者剛完成的變更；下一次手動重新載入仍會讀取權威。
            display_df = _v30073_editor_display_after_save(current_df)
            st.session_state[STATE_KEY] = display_df
            _v30073_set_save_baseline(display_df)
            _refresh_editor_widget()
            st.session_state["v253_work_order_edit_enabled"] = False
            st.success(
                f"儲存完成：本次送出新增/異動 {changed_count} 筆、刪除 {deleted_count} 筆，"
                f"略過空白 {skipped_empty + int(result.get('skipped', 0) or 0)} 筆；"
                f"實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、刪除 {result.get('deleted', 0)}。"
            )
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
        st.dataframe(parsed[["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "is_active"]], use_container_width=True, height=300)
        if st.button("▣ 確認匯入 Excel 製令 / Import Excel Work Orders", type="primary", use_container_width=True, key="wo_excel_import_confirm_v243", disabled=not st.session_state.get("v253_work_order_edit_enabled", False)):
            result = _v30074_apply_import_delta(parsed, "excel")
            if int(result.get("planned_count", 0) or 0) <= 0:
                st.info(f"Excel 匯入完成：沒有偵測到需要寫入 Neon 的新增或異動製令；已略過未變更 {result.get('unchanged', 0)} 筆。")
            else:
                st.success(
                    f"Excel 匯入完成：本次送出新增 {result.get('planned_new', 0)}、更新 {result.get('planned_update', 0)}；"
                    f"實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、"
                    f"刪除 {result.get('deleted', 0)}、略過 {result.get('skipped', 0)}；"
                    f"未變更 {result.get('unchanged', 0)}。"
                )
            rerun()

with tab3:
    st.subheader("貼上資料 / Paste Data")
    st.caption("V1.38 loaded｜支援『有標題列』貼上，系統會依標題列名稱自動對應欄位。")
    st.caption("有標題列支援：製令、P/N、料號、Type、機型、Category、類別、組立地點、客戶、備註、啟用。無標題列時保留舊 6 欄順序；若有 7 欄以上可用：製令、P/N、機型、Category、組立地點、客戶、備註。")
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
            if a1.button("⊕ 加入清單編輯 / Add to Editor", type="secondary", use_container_width=True, key="add_pasted_work_orders_to_editor_v138", disabled=not st.session_state.get("v253_work_order_edit_enabled", False)):
                st.session_state[STATE_KEY] = pd.concat([parsed, _current_internal_df()], ignore_index=True)
                st.success("已加入『製令清單編輯』頁，請切回第一個頁籤確認後按儲存。")

            if a2.button("▣ 直接儲存貼上資料 / Save Pasted Work Orders", type="primary", use_container_width=True, key="save_pasted_work_orders_v138", disabled=not st.session_state.get("v253_work_order_edit_enabled", False)):
                result = _v30074_apply_import_delta(parsed, "paste")
                if int(result.get("planned_count", 0) or 0) <= 0:
                    st.info(f"貼上資料已檢查：沒有偵測到需要寫入 Neon 的新增或異動製令；已略過未變更 {result.get('unchanged', 0)} 筆。")
                else:
                    st.success(
                        f"貼上資料已儲存：本次送出新增 {result.get('planned_new', 0)}、更新 {result.get('planned_update', 0)}；"
                        f"實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、"
                        f"刪除 {result.get('deleted', 0)}、略過 {result.get('skipped', 0)}；"
                        f"未變更 {result.get('unchanged', 0)}。"
                    )
                rerun()

            st.markdown("### 解析後資料預覽 / Parsed Preview")
            st.dataframe(
                parsed[["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "is_active"]],
                use_container_width=True,
                height=360,
            )
    else:
        st.info("請先貼上 Excel 資料。建議包含標題列，例如：製令、P/N、機型、Category、組立地點、客戶、備註。")


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
        raw_src = sheets[sheet]
        saved_cfg = _v30028_get_sheet_setting(sheet)
        saved_mapping = saved_cfg.get("mapping", {}) if isinstance(saved_cfg.get("mapping"), dict) else {}
        guess_row = _guess_header_row(raw_src)
        try:
            saved_header_row = int(saved_cfg.get("header_row") or guess_row or 1)
        except Exception:
            saved_header_row = guess_row
        max_header_row = max(1, min(len(raw_src), 300))
        h1, h2 = st.columns([1, 2])
        header_row = h1.number_input(
            "標題欄是第幾列 / Header row number",
            min_value=1,
            max_value=max_header_row,
            value=min(max(saved_header_row, 1), max_header_row),
            step=1,
            key=f"wo_onedrive_header_row_v246_{sheet}",
            help="請輸入來源 Excel 真正欄位標題所在列數。若前面有標題、說明、空白列，請改成實際標題列。此設定會永久記錄。",
        )
        h2.info("系統會用你指定的那一列當欄位標題，下一列開始才視為製令資料；標題列與欄位對應在確認套用後會永久記錄，下次不用重新設定。")
        src = _apply_header_row(raw_src, int(header_row))
        st.caption(f"目前使用第 {int(header_row)} 列作為標題欄；已取得 {len(src)} 筆資料列。")
        st.dataframe(
            src.head(30),
            use_container_width=True,
            height=260,
            key=f"wo_onedrive_source_preview_v246_{sheet}_{int(header_row)}",
            column_order=list(src.columns.astype(str)),
        )
        cols = [""] + list(src.columns.astype(str))

        def _mapping_index(target: str, predicate):
            saved_col = str(saved_mapping.get(target, "") or "")
            if saved_col in cols:
                return cols.index(saved_col)
            return next((i for i, c in enumerate(cols) if predicate(str(c))), 0)

        st.markdown("### 欄位對應 / Column Mapping（確認套用後永久記錄）")
        st.caption("若來源活頁格式固定，只要設定一次；之後讀取相同活頁會自動帶入標題欄列號與所有欄位對應。")
        m1, m2, m3 = st.columns(3)
        mapping = {
            "work_order": m1.selectbox("製令 / Work Order", cols, index=_mapping_index("work_order", lambda c: '製令' in c or 'work order' in c.lower()), key=f"wo_map_work_order_v246_{sheet}"),
            "part_no": m2.selectbox("P/N / Part No.", cols, index=_mapping_index("part_no", lambda c: 'p/n' in c.lower() or '料號' in c), key=f"wo_map_part_no_v246_{sheet}"),
            "type_name": m3.selectbox("機型 / Type", cols, index=_mapping_index("type_name", lambda c: '機型' in c or 'type' in c.lower()), key=f"wo_map_type_name_v246_{sheet}"),
            "category": m1.selectbox("類別 / Category", cols, index=_mapping_index("category", lambda c: 'category' in c.lower() or '類別' in c or '分類' in c), key=f"wo_map_category_v246_{sheet}"),
            "assembly_location": m2.selectbox("組立地點 / Assembly Location", cols, index=_mapping_index("assembly_location", lambda c: '組立' in c or 'assembly' in c.lower()), key=f"wo_map_assembly_location_v246_{sheet}"),
            "customer": m3.selectbox("客戶 / Customer", cols, index=_mapping_index("customer", lambda c: '客戶' in c or 'customer' in c.lower()), key=f"wo_map_customer_v246_{sheet}"),
            "note": m1.selectbox("備註 / Note", cols, index=_mapping_index("note", lambda c: '備註' in c or 'note' in c.lower()), key=f"wo_map_note_v246_{sheet}"),
            "is_active": m2.selectbox("啟用 / Active", cols, index=_mapping_index("is_active", lambda c: '啟用' in c or 'active' in c.lower()), key=f"wo_map_is_active_v246_{sheet}"),
        }
        st.markdown("### 匯入模式 / Import Mode")
        mode_options = {
            "master": "製令主檔模式：相同製令只保留一筆（建議給 01 下拉選單使用）",
            "source_rows": "來源列模式：保留來源每一列（重複製令會用來源列唯一鍵，必要時加 #R列號）",
        }
        saved_import_mode = str(saved_cfg.get("import_mode", "master") or "master")
        mode_keys = list(mode_options.keys())
        import_mode_label = st.radio(
            "重複製令處理方式 / Duplicate work order handling",
            [mode_options[k] for k in mode_keys],
            index=mode_keys.index(saved_import_mode) if saved_import_mode in mode_keys else 0,
            horizontal=False,
            key=f"wo_import_mode_v250_{sheet}",
        )
        import_mode = mode_keys[[mode_options[k] for k in mode_keys].index(import_mode_label)]

        def _row_key_default_index() -> int:
            preferred = ["製令&出現次數", "製令出現次數", "製令&時間", "row key", "source key"]
            saved_col = str(saved_cfg.get("row_key_col", "") or "")
            if saved_col in cols:
                return cols.index(saved_col)
            for ptn in preferred:
                for i, col in enumerate(cols):
                    if ptn.lower() in str(col).lower():
                        return i
            return cols.index(mapping.get("work_order", "")) if mapping.get("work_order", "") in cols else 0

        row_key_col = ""
        if import_mode == "source_rows":
            row_key_col = st.selectbox(
                "來源列唯一鍵 / Source row key",
                cols,
                index=_row_key_default_index(),
                key=f"wo_row_key_col_v250_{sheet}",
                help="若要保留來源每一列，建議選『製令&出現次數』；若仍有重複，系統會自動附加來源列號。",
            )

        incoming_raw = _map_excel_work_orders(src, mapping)
        source_valid_rows = len(incoming_raw)
        source_unique_work_orders = incoming_raw["work_order"].map(_normalize_text).replace("", pd.NA).dropna().nunique() if not incoming_raw.empty else 0
        duplicate_extra = max(0, source_valid_rows - source_unique_work_orders)
        if import_mode == "source_rows":
            incoming, row_mode_stats = _make_unique_work_order_keys(incoming_raw, src=src, row_key_col=row_key_col, header_row=int(header_row))
            compare_collapse = False
        else:
            incoming = incoming_raw
            row_mode_stats = {"source_rows": source_valid_rows, "base_unique": source_unique_work_orders, "final_unique": source_unique_work_orders, "duplicate_extra": duplicate_extra}
            compare_collapse = True

        current = load_work_orders()
        add_df, upd_df, del_df = _compare_work_orders(incoming, current, collapse_duplicates=compare_collapse)
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("來源有效列 / Source Rows", source_valid_rows)
        d2.metric("唯一製令 / Unique W/O", source_unique_work_orders)
        d3.metric("重複列 / Duplicate Rows", duplicate_extra)
        d4.metric("本次寫入鍵 / Import Keys", row_mode_stats.get("final_unique", 0))
        if duplicate_extra > 0 and import_mode == "master":
            st.warning(f"來源有 {source_valid_rows} 筆有效列，但只有 {source_unique_work_orders} 個唯一製令；製令主檔模式會合併 {duplicate_extra} 筆重複製令，所以寫入筆數會少於 Excel 列數。若要每一列都進入製令清單，請改選『來源列模式』。")
        elif import_mode == "source_rows":
            st.info(f"來源列模式已啟用：會嘗試保留 {source_valid_rows} 筆來源列；本次產生 {row_mode_stats.get('final_unique', 0)} 個唯一寫入鍵。")

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
        do_delete = st.checkbox(
            "同步刪除來源不存在的舊製令 / Delete old work orders not in source",
            value=bool(saved_cfg.get("delete_missing", False)),
            key=f"wo_sync_delete_missing_v246_{sheet}",
        )
        sc1, sc2 = st.columns(2)
        if sc1.button("▣ 永久記錄目前欄位對應 / Save Mapping Only", use_container_width=True, key=f"wo_save_mapping_only_v246_{sheet}"):
            save_sheet_setting(sheet, int(header_row), mapping, bool(do_delete), import_mode=import_mode, row_key_col=row_key_col)
            _v30028_set_sheet_setting_cache(sheet, {"header_row": int(header_row), "mapping": mapping, "delete_missing": bool(do_delete), "import_mode": import_mode, "row_key_col": row_key_col})
            st.success("已永久記錄目前 OneDrive 製令欄位對應設定與匯入模式。下次進入此活頁會自動帶入。")
        if sc2.button("◌ 清除本頁欄位對應設定 / Clear Mapping", use_container_width=True, key=f"wo_clear_mapping_v246_{sheet}"):
            clear_work_order_sync_settings()
            _v30028_set_sheet_setting_cache(sheet, None)
            st.warning("已清除 OneDrive 製令欄位對應永久設定；重新讀取後會回到自動判斷。")
            rerun()

        last_msg = st.session_state.get("wo_onedrive_sync_last_message_v248", "")
        if last_msg:
            st.success(last_msg)

        st.info("按下確認後才會正式新增、更新或刪除製令；只按『永久記錄目前欄位對應』不會寫入製令清單。")
        if st.button("▣ 確認套用對應更新 / Apply Mapped Sync", type="primary", use_container_width=True, key=f"wo_onedrive_apply_v249_{sheet}"):
            if not mapping.get("work_order"):
                st.error("請先對應『製令 / Work Order』欄位，否則無法新增或更新製令。")
            elif incoming.empty:
                st.error("來源資料沒有可寫入的製令。請確認標題列號與製令欄位對應。")
            else:
                save_sheet_setting(sheet, int(header_row), mapping, bool(do_delete), import_mode=import_mode, row_key_col=row_key_col)
                _v30028_set_sheet_setting_cache(sheet, {"header_row": int(header_row), "mapping": mapping, "delete_missing": bool(do_delete), "import_mode": import_mode, "row_key_col": row_key_col})
                planned_count = len(add_df) + len(upd_df) + (len(del_df) if do_delete else 0)
                if planned_count <= 0:
                    msg = "製令同步完成：沒有需要新增、更新或刪除的製令。欄位對應已永久記錄。"
                    st.session_state["wo_onedrive_sync_last_message_v248"] = msg
                    st.info(msg)
                else:
                    result = _apply_work_order_sync_direct(add_df, upd_df, del_df, bool(do_delete))
                    # V300.72：避免套用後又立即重讀 Neon。這裡直接用本次差異結果刷新畫面；
                    # 下一次手動重新載入仍會讀取 Neon 權威。
                    try:
                        st.session_state[STATE_KEY] = _v30072_merge_sync_result_for_editor(current, add_df, upd_df, del_df, bool(do_delete))
                    except Exception:
                        reload_data()
                    msg = (
                        f"製令同步完成，且已永久記錄欄位對應與匯入模式："
                        f"應新增 {len(add_df)}、應更新 {len(upd_df)}、"
                        f"應刪除 {len(del_df) if do_delete else 0}；"
                        f"實際新增 {result.get('inserted', 0)}、"
                        f"實際更新 {result.get('updated', 0)}、"
                        f"實際刪除 {result.get('deleted', 0)}、"
                        f"略過 {result.get('skipped', 0)}；"
                        f"03 權威檔同步 {result.get('authority_rows', 0)} 筆。"
                        f"新增：{_safe_join(result.get('inserted_keys', []))}；"
                        f"更新：{_safe_join(result.get('updated_keys', []))}；"
                        f"刪除：{_safe_join(result.get('deleted_keys', []))}"
                    )
                    st.session_state["wo_onedrive_sync_last_message_v248"] = msg
                    if result.get("authority_ok", False):
                        st.success(msg)
                    else:
                        st.warning(msg)
                        st.error(f"製令已寫入 SQLite，但 03 權威檔同步失敗：{result.get('authority_error', '')}")
                    # 清掉編輯頁舊 data_editor 草稿，回到製令清單可直接看到最新資料。
                    _refresh_editor_widget()
                    rerun()

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

