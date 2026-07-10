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

try:
    from services.security_service import require_module_access
except Exception:
    def require_module_access(module_code: str):
        return True

from services.finished_machine_service import (
    FINISHED_MACHINE_COLS,
    load_finished_machines,
    save_finished_machines,
    make_delete_missing_rows,
)

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
    from services.work_order_sync_settings_service import get_sheet_setting, save_sheet_setting
except Exception:
    def get_sheet_setting(sheet_name: str):
        return {"header_row": 1, "mapping": {}, "delete_missing": False}
    def save_sheet_setting(sheet_name: str, header_row: int, mapping: dict, delete_missing: bool = False, **_):
        return {}

st.set_page_config(page_title="16. 完工機台", page_icon="▣", layout="wide")
apply_theme()
require_module_access("16_finished_machines")
render_header("16｜完工機台", "已完工製令資訊查詢、Excel 匯入、貼上資料與 OneDrive 對應更新；01 工時紀錄會自動隱藏已完工製令")

STATE_KEY = "v16_finished_machines_editor"
EDITOR_VERSION_KEY = "v16_finished_machines_editor_version"
EDITOR_IGNORE_RETURN_KEY = "v16_finished_machines_ignore_next_editor_return"
BASELINE_KEY = "v16_finished_machines_editor_save_baseline"
TABLE_KEY = "16_finished_machines_editor_main"

COLS = list(FINISHED_MACHINE_COLS)
DISPLAY_COLUMNS = {
    "_delete": "刪除 / Delete",
    "id": "ID / ID",
    "work_order": "製令 / Work Order",
    "part_no": "P/N / Part No.",
    "type_name": "機型 / Type",
    "category": "類別 / Category",
    "assembly_location": "組立地點 / Assembly Location",
    "customer": "客戶 / Customer",
    "finished_date": "完工日期 / Finished Date",
    "note": "備註 / Note",
    "is_active": "啟用 / Active",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
}
DISPLAY_TO_INTERNAL = {v: k for k, v in DISPLAY_COLUMNS.items()}
EDITOR_COLS = [DISPLAY_COLUMNS[c] for c in COLS]
BOOL_INTERNAL_COLS = ["_delete", "is_active"]
BOOL_DISPLAY_COLS = [DISPLAY_COLUMNS[c] for c in BOOL_INTERNAL_COLS]


def _normalize_text(v) -> str:
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v if v is not None else "").strip()
    return "" if text.lower() in {"none", "nan", "nat"} else text


def _to_bool_value(v) -> bool:
    if isinstance(v, bool):
        return v
    text = _normalize_text(v).lower()
    if text in {"1", "true", "yes", "y", "on", "啟用", "是", "勾選", "active"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "否", "", "inactive"}:
        return False
    return bool(v)


def _date_text(v) -> str:
    text = _normalize_text(v)
    if not text:
        return ""
    try:
        ts = pd.to_datetime(text, errors="coerce")
        if pd.notna(ts):
            return ts.strftime("%Y-%m-%d")
    except Exception:
        pass
    return text


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    df = df.rename(columns={c: DISPLAY_TO_INTERNAL.get(c, c) for c in df.columns})
    for c in COLS:
        if c not in df.columns:
            df[c] = False if c == "_delete" else True if c == "is_active" else ""
    for c in BOOL_INTERNAL_COLS:
        df[c] = df[c].map(_to_bool_value).fillna(False if c == "_delete" else True).astype(bool)
    for c in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note", "created_at", "updated_at"]:
        df[c] = df[c].map(_normalize_text)
    df["finished_date"] = df["finished_date"].map(_date_text)
    return df[COLS]


def _to_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_cols(df).rename(columns=DISPLAY_COLUMNS)[EDITOR_COLS]


def _from_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_cols(df)


def _safe_widget_part(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", str(text or "table")).strip("_") or "table"


def _width(table_key: str, col: str, default: str = "medium"):
    try:
        widths = load_widths(table_key)
        raw = widths.get(str(col), default) if isinstance(widths, dict) else default
        if isinstance(raw, (int, float)):
            return max(60, min(1200, int(raw)))
        val = str(raw or default).strip()
        if val in {"small", "medium", "large"}:
            return val
        if val.replace(".", "", 1).isdigit():
            return max(60, min(1200, int(float(val))))
        return default
    except Exception:
        return default


def _column_config(table_key: str) -> dict:
    return {
        DISPLAY_COLUMNS["_delete"]: st.column_config.CheckboxColumn("刪除 / Delete", width=_width(table_key, DISPLAY_COLUMNS["_delete"], "small")),
        DISPLAY_COLUMNS["id"]: st.column_config.NumberColumn("ID / ID", disabled=True, width=_width(table_key, DISPLAY_COLUMNS["id"], "small")),
        DISPLAY_COLUMNS["work_order"]: st.column_config.TextColumn("製令 / Work Order", required=True, width=_width(table_key, DISPLAY_COLUMNS["work_order"], "medium")),
        DISPLAY_COLUMNS["part_no"]: st.column_config.TextColumn("P/N / Part No.", width=_width(table_key, DISPLAY_COLUMNS["part_no"], "medium")),
        DISPLAY_COLUMNS["type_name"]: st.column_config.TextColumn("機型 / Type", width=_width(table_key, DISPLAY_COLUMNS["type_name"], "large")),
        DISPLAY_COLUMNS["category"]: st.column_config.TextColumn("類別 / Category", width=_width(table_key, DISPLAY_COLUMNS["category"], "medium")),
        DISPLAY_COLUMNS["assembly_location"]: st.column_config.TextColumn("組立地點 / Assembly Location", width=_width(table_key, DISPLAY_COLUMNS["assembly_location"], "medium")),
        DISPLAY_COLUMNS["customer"]: st.column_config.TextColumn("客戶 / Customer", width=_width(table_key, DISPLAY_COLUMNS["customer"], "medium")),
        DISPLAY_COLUMNS["finished_date"]: st.column_config.TextColumn("完工日期 / Finished Date", width=_width(table_key, DISPLAY_COLUMNS["finished_date"], "medium")),
        DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width=_width(table_key, DISPLAY_COLUMNS["note"], "large")),
        DISPLAY_COLUMNS["is_active"]: st.column_config.CheckboxColumn("啟用 / Active", width=_width(table_key, DISPLAY_COLUMNS["is_active"], "small")),
        DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", disabled=True, width=_width(table_key, DISPLAY_COLUMNS["created_at"], "medium")),
        DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", disabled=True, width=_width(table_key, DISPLAY_COLUMNS["updated_at"], "medium")),
    }


def _editor_key() -> str:
    if EDITOR_VERSION_KEY not in st.session_state:
        st.session_state[EDITOR_VERSION_KEY] = 0
    return f"finished_machines_data_editor_v16_{st.session_state[EDITOR_VERSION_KEY]}"


def _refresh_editor_widget() -> None:
    try:
        for k in list(st.session_state.keys()):
            if str(k).startswith("finished_machines_data_editor_v16_"):
                st.session_state.pop(k, None)
    except Exception:
        pass
    st.session_state[EDITOR_IGNORE_RETURN_KEY] = True
    st.session_state[EDITOR_VERSION_KEY] = int(st.session_state.get(EDITOR_VERSION_KEY, 0)) + 1


def rerun():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def _current_internal_df() -> pd.DataFrame:
    return ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))


def reload_data() -> pd.DataFrame:
    df = load_finished_machines(active_only=None)
    st.session_state[STATE_KEY] = ensure_cols(df)
    _set_save_baseline(st.session_state[STATE_KEY])
    return st.session_state[STATE_KEY]


def _set_save_baseline(df: pd.DataFrame) -> None:
    base = ensure_cols(df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame())
    base["_delete"] = False
    st.session_state[BASELINE_KEY] = base


def _row_key(row) -> str:
    return _normalize_text(row.get("work_order")).upper()


def _row_changed(in_row: pd.Series, cur_row: pd.Series) -> bool:
    for c in ["part_no", "type_name", "category", "assembly_location", "customer", "finished_date", "note"]:
        if _normalize_text(in_row.get(c, "")) != _normalize_text(cur_row.get(c, "")):
            return True
    return _to_bool_value(in_row.get("is_active", True)) != _to_bool_value(cur_row.get("is_active", True))


def _build_save_delta(current_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    current = ensure_cols(current_df).copy()
    current = current[current["work_order"].map(_normalize_text) != ""].copy()
    baseline = ensure_cols(st.session_state.get(BASELINE_KEY, pd.DataFrame())).copy()
    base_map = {_row_key(r): r for _, r in baseline.iterrows() if _row_key(r)}
    rows = []
    stats = {"deleted": 0, "new_or_changed": 0, "skipped_empty": 0}
    seen: set[str] = set()
    for _, row in current.iterrows():
        key = _row_key(row)
        if not key:
            stats["skipped_empty"] += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        if _to_bool_value(row.get("_delete")):
            rows.append(row.to_dict())
            stats["deleted"] += 1
            continue
        old = base_map.get(key)
        if old is None or _row_changed(row, old):
            rows.append(row.to_dict())
            stats["new_or_changed"] += 1
    return ensure_cols(pd.DataFrame(rows)), stats


def _display_after_save(current_df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_cols(current_df).copy()
    if not df.empty:
        delete_mask = df["_delete"].map(_to_bool_value).fillna(False).astype(bool)
        df = df.loc[~delete_mask].copy()
        df["_delete"] = False
        df = df[df["work_order"].map(_normalize_text) != ""].drop_duplicates(subset=["work_order"], keep="last").reset_index(drop=True)
    return ensure_cols(df)


def _excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe = str(name)[:31] or "Sheet1"
            df.to_excel(writer, index=False, sheet_name=safe)
    return bio.getvalue()


def _template_bytes() -> bytes:
    key = "v16_finished_machine_template_bytes"
    if key not in st.session_state:
        tpl = pd.DataFrame(columns=["製令", "P/N", "機型", "Category", "組立地點", "客戶", "完工日期", "備註", "啟用"])
        st.session_state[key] = _excel_bytes({"template": tpl})
    return st.session_state[key]


def _current_column_order(table_key: str, df: pd.DataFrame) -> list[str]:
    current = [str(c) for c in df.columns]
    current_set = set(current)
    try:
        saved = [str(c) for c in (load_column_order(table_key) or [])]
    except Exception:
        saved = []
    out, seen = [], set()
    for col in saved:
        if col in current_set and col not in seen:
            out.append(col); seen.add(col)
    for col in current:
        if col not in seen:
            out.append(col); seen.add(col)
    return out


def _render_column_settings(table_key: str, df: pd.DataFrame, title: str) -> None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return
    safe_key = _safe_widget_part(table_key)
    current_cols = [str(c) for c in df.columns]
    with st.expander(title, expanded=False):
        st.caption("此區只管理 16 完工機台表格欄位順序與欄寬；不會修改完工資料。")
        open_editor = st.checkbox("開啟欄位設定編輯器 / Open column settings editor", value=False, key=f"v16_column_settings_open_{safe_key}")
        if not open_editor:
            st.caption(f"目前表格共有 {len(current_cols)} 個欄位。需要調整時再開啟，避免每次重建設定編輯器。")
            return
        try:
            widths = {str(k): int(float(v)) for k, v in (load_widths(table_key) or {}).items() if str(k) in current_cols}
        except Exception:
            widths = {}
        ordered = _current_column_order(table_key, df)
        settings_rows = [{"欄位 / Column": c, "欄寬 / Width": int(widths.get(c, 150))} for c in ordered]
        with st.form(f"v16_column_settings_form_{safe_key}", clear_on_submit=False):
            order_text = st.text_area("欄位順序 / Column order（每行一個欄位）", value="\n".join([r["欄位 / Column"] for r in settings_rows]), height=190, key=f"v16_column_order_text_{safe_key}")
            width_df = st.data_editor(
                pd.DataFrame(settings_rows),
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key=f"v16_width_editor_{safe_key}",
                column_config={
                    "欄位 / Column": st.column_config.Column("欄位 / Column"),
                    "欄寬 / Width": st.column_config.NumberColumn("欄寬 / Width", min_value=60, max_value=1200, step=10),
                },
                disabled=["欄位 / Column"],
                height=260,
            )
            b1, b2 = st.columns([1.5, 1])
            apply_settings = b1.form_submit_button("✅ 套用並永久儲存欄位設定 / Apply & Save", type="primary", use_container_width=True)
            reset_settings = b2.form_submit_button("↺ 恢復預設順序 / Reset order", use_container_width=True)
        if apply_settings:
            raw_order = [x.strip() for x in str(order_text or "").splitlines() if x.strip()]
            clean_order, seen = [], set()
            for col in raw_order + current_cols:
                if col in current_cols and col not in seen:
                    clean_order.append(col); seen.add(col)
            clean_widths = {}
            for _, row in width_df.iterrows():
                col = str(row.get("欄位 / Column", "")).strip()
                if col in current_cols:
                    try:
                        clean_widths[col] = max(60, min(1200, int(float(row.get("欄寬 / Width", 150)))))
                    except Exception:
                        clean_widths[col] = 150
            save_widths(table_key, clean_widths)
            save_column_order(table_key, clean_order)
            st.success("16 完工機台欄位設定已套用並永久儲存。")
            rerun()
        elif reset_settings:
            save_column_order(table_key, current_cols)
            save_widths(table_key, {c: int(widths.get(c, 150)) for c in current_cols})
            st.success("已恢復 16 完工機台預設欄位順序。")
            rerun()


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
    text = _normalize_text(v).lower()
    for ch in [" ", "\t", "\n", "\r", "_", "-", "－", "—", "/", "／", "\\", ".", "．", "：", ":", "（", "）", "(", ")"]:
        text = text.replace(ch, "")
    return text


ALIAS_GROUPS = {
    "work_order": ["製令", "工單", "工令", "製令號碼", "製令編號", "mo", "wo", "work order", "work_order", "工單號碼"],
    "part_no": ["p/n", "pn", "part no", "part_no", "part number", "料號", "品號", "圖號"],
    "type_name": ["type", "type name", "type_name", "機型", "型號", "機種", "model"],
    "category": ["category", "cat", "類別", "分類", "show category", "show_category", "機型類別", "產品類別", "製令類別"],
    "assembly_location": ["組立地點", "組裝地點", "組立位置", "地點", "assembly location", "assembly_location", "location"],
    "customer": ["客戶", "客戶別", "customer", "client", "客戶名稱"],
    "finished_date": ["完工日期", "完成日期", "入庫日", "入庫日期", "出貨日", "出貨日期", "finish date", "finished date", "completion date", "done date", "完工日"],
    "note": ["備註", "note", "remark", "remarks", "說明", "memo"],
    "is_active": ["啟用", "active", "is active", "is_active", "狀態", "有效"],
}


def _row_looks_like_header(row: list[str]) -> bool:
    norm_row = {_normalize_header_name(x) for x in row}
    hits = 0
    for aliases in ALIAS_GROUPS.values():
        norm_aliases = {_normalize_header_name(a) for a in aliases}
        if norm_row & norm_aliases:
            hits += 1
    return hits >= 1


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


def _pick_series(source: pd.DataFrame, aliases: list[str], default=""):
    col = _find_col(source, aliases)
    if col is None:
        return default
    return source[col]


def parse_pasted_finished_machines(raw: str) -> tuple[pd.DataFrame, bool, list[str]]:
    lines = [line for line in raw.splitlines() if line.strip()]
    rows = [_split_paste_line(line) for line in lines]
    warnings: list[str] = []
    if not rows:
        return ensure_cols(pd.DataFrame()), False, warnings
    has_header = _row_looks_like_header(rows[0])
    if has_header:
        width = max(len(r) for r in rows)
        padded_rows = [r + [""] * (width - len(r)) for r in rows]
        source = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])
        work_order = _pick_series(source, ALIAS_GROUPS["work_order"])
        if isinstance(work_order, str):
            warnings.append("找不到『製令』欄位，資料將無法儲存。請確認標題列包含：製令 / 工單 / WO / MO。")
            return ensure_cols(pd.DataFrame()), has_header, warnings
        active_series = _pick_series(source, ALIAS_GROUPS["is_active"], default=None)
        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": work_order,
            "part_no": _pick_series(source, ALIAS_GROUPS["part_no"]),
            "type_name": _pick_series(source, ALIAS_GROUPS["type_name"]),
            "category": _pick_series(source, ALIAS_GROUPS["category"]),
            "assembly_location": _pick_series(source, ALIAS_GROUPS["assembly_location"]),
            "customer": _pick_series(source, ALIAS_GROUPS["customer"]),
            "finished_date": _pick_series(source, ALIAS_GROUPS["finished_date"]),
            "note": _pick_series(source, ALIAS_GROUPS["note"]),
            "is_active": True if active_series is None else active_series.map(_to_bool_value),
            "created_at": "",
            "updated_at": "",
        })
    else:
        # Old simple order: 製令、P/N、機型、Category、組立地點、客戶、完工日期、備註
        padded = [r + [""] * (8 - len(r)) for r in rows]
        df = pd.DataFrame({
            "_delete": False,
            "id": "",
            "work_order": [r[0] for r in padded],
            "part_no": [r[1] for r in padded],
            "type_name": [r[2] for r in padded],
            "category": [r[3] for r in padded],
            "assembly_location": [r[4] for r in padded],
            "customer": [r[5] for r in padded],
            "finished_date": [r[6] for r in padded],
            "note": [r[7] for r in padded],
            "is_active": True,
            "created_at": "",
            "updated_at": "",
        })
        warnings.append("未偵測到標題列，已用預設順序解析：製令、P/N、機型、Category、組立地點、客戶、完工日期、備註。")
    for c in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "note"]:
        df[c] = df[c].map(_normalize_text)
    df["finished_date"] = df["finished_date"].map(_date_text)
    before = len(df)
    df = df[df["work_order"] != ""].copy()
    dropped = before - len(df)
    if dropped > 0:
        warnings.append(f"已略過 {dropped} 筆沒有製令的資料列。")
    return ensure_cols(df), has_header, warnings


def _make_unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    seen: dict[str, int] = {}
    cols: list[str] = []
    for idx, col in enumerate(out.columns):
        name = _normalize_text(col)
        if not name or name.lower().startswith("unnamed"):
            name = f"欄位{idx + 1}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        if count:
            name = f"{name}__{count + 1}"
        cols.append(name)
    out.columns = cols
    return out


def _read_excel_source(uploaded=None, path_text: str = "") -> dict[str, pd.DataFrame]:
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
    if df_raw is None or df_raw.empty:
        return 1
    tokens = ["製令", "work order", "p/n", "料號", "part", "機型", "type", "category", "類別", "分類", "完工", "finished", "completion", "客戶", "customer", "備註", "note"]
    best_row = 1
    best_score = -1
    for i in range(min(len(df_raw), max_scan_rows)):
        vals = [_normalize_text(v).lower() for v in df_raw.iloc[i].tolist() if _normalize_text(v)]
        joined = " | ".join(vals)
        score = sum(1 for t in tokens if t in joined) * 10 + min(len(vals), 9)
        if score > best_score:
            best_score = score
            best_row = i + 1
    return max(1, best_row)


def _apply_header_row(df_raw: pd.DataFrame, header_row_1based: int) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
    idx = max(0, min(int(header_row_1based or 1) - 1, len(df_raw) - 1))
    headers = df_raw.iloc[idx].tolist()
    data = df_raw.iloc[idx + 1:].copy()
    data.columns = headers
    data = data.dropna(how="all").reset_index(drop=True)
    return _make_unique_columns(data)


def _map_finished_machines(df_raw: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return ensure_cols(pd.DataFrame())
    out = pd.DataFrame()
    out["_delete"] = False
    out["id"] = ""
    for target in ["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "finished_date", "note"]:
        col = mapping.get(target, "")
        out[target] = df_raw[col].map(_normalize_text) if col in df_raw.columns else ""
    active_col = mapping.get("is_active", "")
    out["is_active"] = df_raw[active_col].map(_to_bool_value) if active_col in df_raw.columns else True
    out["created_at"] = ""
    out["updated_at"] = ""
    out["finished_date"] = out["finished_date"].map(_date_text)
    out = out[out["work_order"].astype(str).str.strip() != ""].copy()
    return ensure_cols(out)


def _mapping_index(cols: list[str], target: str, fallback_predicate) -> int:
    cfg = st.session_state.get("v16_finished_current_mapping", {}) or {}
    saved = str(cfg.get(target, "") or "")
    # V16.1: do not reuse an invalid saved mapping for boolean Active.
    # If a previous run accidentally saved a date column such as「入庫日」as Active,
    # all imported rows become False.  Ignore that stale mapping and fall back to blank.
    if saved in cols:
        if target == "is_active" and saved and not fallback_predicate(saved):
            saved = ""
        else:
            return cols.index(saved)
    for i, c in enumerate(cols):
        if fallback_predicate(str(c)):
            return i
    return 0


def _apply_import_delta(parsed: pd.DataFrame, label: str) -> dict:
    parsed = ensure_cols(parsed)
    current = load_finished_machines(active_only=None)
    current_map = {_normalize_text(r.get("work_order")).upper(): r for _, r in current.iterrows()} if isinstance(current, pd.DataFrame) and not current.empty else {}
    rows = []
    unchanged = 0
    planned_new = 0
    planned_update = 0
    for _, row in parsed.iterrows():
        key = _normalize_text(row.get("work_order")).upper()
        if not key:
            continue
        old = current_map.get(key)
        if old is None:
            planned_new += 1
            rows.append(row.to_dict())
        elif _row_changed(row, old):
            planned_update += 1
            rows.append(row.to_dict())
        else:
            unchanged += 1
    payload = ensure_cols(pd.DataFrame(rows))
    result = save_finished_machines(payload) if not payload.empty else {"inserted": 0, "updated": 0, "deleted": 0, "skipped": 0}
    result.update({"planned_count": len(payload), "planned_new": planned_new, "planned_update": planned_update, "unchanged": unchanged, "source": label})
    return result


if STATE_KEY not in st.session_state:
    reload_data()

base_df = ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))
total = int((base_df["work_order"].map(_normalize_text) != "").sum()) if not base_df.empty else 0
active = int(base_df["is_active"].map(_to_bool_value).sum()) if not base_df.empty else 0
inactive = total - active
pending_delete = int(base_df["_delete"].map(_to_bool_value).sum()) if not base_df.empty else 0
m1, m2, m3, m4 = st.columns(4)
m1.metric("完工製令數 / Finished", total)
m2.metric("啟用隱藏 / Active Hidden", active)
m3.metric("停用不隱藏 / Inactive", inactive)
m4.metric("待刪除 / Pending Delete", pending_delete)

st.info("01｜工時紀錄的製令下拉會用快取的完工製令集合過濾，不會每次輸入或展開下拉都逐筆查 Neon。停用本頁資料即可讓該製令重新出現在 01 下拉。")

tab1, tab2, tab3, tab4 = st.tabs(["製令清單編輯", "Excel 匯入", "貼上資料", "OneDrive 對應更新"])

with tab1:
    st.subheader("完工機台清單編輯 / Finished Machine Editor")
    e1, e2, e3 = st.columns([1, 1, 3])
    edit_enabled = bool(st.session_state.get("v16_finished_edit_enabled", False))
    if e1.button("◌ 啟動編輯 / Unlock Edit", use_container_width=True, disabled=edit_enabled, key="v16_enable_edit"):
        st.session_state["v16_finished_edit_enabled"] = True
        _refresh_editor_widget()
        rerun()
    if e2.button("◌ 停止編輯 / Lock Edit", use_container_width=True, disabled=not edit_enabled, key="v16_disable_edit"):
        st.session_state["v16_finished_edit_enabled"] = False
        reload_data()
        _refresh_editor_widget()
        rerun()
    if edit_enabled:
        e3.success("目前：已啟動編輯。修改後請按儲存才會正式寫入。")
    else:
        e3.info("目前：唯讀保護。請先啟動編輯，再新增、修改、刪除、匯入或貼上完工製令。")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("⊕ 新增空白列 / Add Row", use_container_width=True, disabled=not edit_enabled, key="v16_add_row"):
        blank = pd.DataFrame([{"_delete": False, "id": "", "work_order": "", "part_no": "", "type_name": "", "category": "", "assembly_location": "", "customer": "", "finished_date": "", "note": "", "is_active": True, "created_at": "", "updated_at": ""}])
        st.session_state[STATE_KEY] = pd.concat([blank, _current_internal_df()], ignore_index=True)
        _refresh_editor_widget()
        rerun()
    if c2.button("☑ 啟用全選 / Active All", use_container_width=True, disabled=not edit_enabled, key="v16_active_all_on"):
        df = _current_internal_df(); df["is_active"] = True; st.session_state[STATE_KEY] = df; _refresh_editor_widget(); rerun()
    if c3.button("☐ 啟用取消 / Inactive All", use_container_width=True, disabled=not edit_enabled, key="v16_active_all_off"):
        df = _current_internal_df(); df["is_active"] = False; st.session_state[STATE_KEY] = df; _refresh_editor_widget(); rerun()
    if c4.button("☑ 刪除全選 / Select Delete", use_container_width=True, disabled=not edit_enabled, key="v16_delete_all_on"):
        df = _current_internal_df(); df["_delete"] = True; st.session_state[STATE_KEY] = df; _refresh_editor_widget(); rerun()
    if c5.button("☐ 刪除取消 / Clear Delete", use_container_width=True, disabled=not edit_enabled, key="v16_delete_all_off"):
        df = _current_internal_df(); df["_delete"] = False; st.session_state[STATE_KEY] = df; _refresh_editor_widget(); rerun()
    if c6.button("⟳ 重新載入 / Reload", use_container_width=True, key="v16_reload"):
        reload_data(); _refresh_editor_widget(); rerun()

    st.warning("勾選『刪除 / Delete』後按下儲存，才會真正將資料標示刪除。『啟用 / Active』控制是否在 01 製令下拉中隱藏。")
    dl1, dl2 = st.columns(2)
    if dl1.button("⟰ 準備目前完工清單下載 / Prepare Export", use_container_width=True, key="v16_prepare_export"):
        export_df = _current_internal_df().drop(columns=["_delete"], errors="ignore")
        st.session_state["v16_finished_export_bytes"] = _excel_bytes({"finished_machines": export_df})
        st.session_state["v16_finished_export_rows"] = len(export_df)
    if "v16_finished_export_bytes" in st.session_state:
        dl1.download_button("下載目前完工清單 / Download Finished Machines", data=st.session_state["v16_finished_export_bytes"], file_name="SPT_完工機台清單.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="v16_download_export")
        dl1.caption(f"已準備 {st.session_state.get('v16_finished_export_rows', 0)} 筆。")
    dl2.download_button("⟰ 下載完工機台匯入範本 / Download Template", data=_template_bytes(), file_name="SPT_完工機台匯入範本.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="v16_download_template")

    editor_df = apply_column_order(TABLE_KEY, _to_editor_df(st.session_state[STATE_KEY]))
    _render_column_settings(TABLE_KEY, editor_df, "▤ 16 完工機台欄位設定 / Finished Machine Column Settings")
    if not edit_enabled:
        st.dataframe(editor_df, hide_index=True, use_container_width=True, height=560, key="v16_readonly_preview", column_order=[c for c in EDITOR_COLS if c in editor_df.columns], column_config=_column_config(TABLE_KEY))
    else:
        with st.form("v16_finished_editor_form", clear_on_submit=False):
            edited = st.data_editor(editor_df, hide_index=True, use_container_width=True, num_rows="dynamic", height=560, column_order=[c for c in EDITOR_COLS if c in editor_df.columns], column_config=_column_config(TABLE_KEY), key=_editor_key(), disabled=False)
            submitted = st.form_submit_button("▣ 確認儲存完工機台清單 / Save Finished Machines", type="primary", use_container_width=True)
        ignore = bool(st.session_state.pop(EDITOR_IGNORE_RETURN_KEY, False))
        if isinstance(edited, pd.DataFrame) and not ignore:
            st.session_state[STATE_KEY] = _from_editor_df(edited.copy())
        if submitted:
            current_df = _current_internal_df()
            delta_df, stats = _build_save_delta(current_df)
            if delta_df.empty:
                display_df = _display_after_save(current_df)
                st.session_state[STATE_KEY] = display_df
                _set_save_baseline(display_df)
                _refresh_editor_widget()
                st.session_state["v16_finished_edit_enabled"] = False
                st.info("沒有偵測到需要寫入 Neon 的完工機台變更；已停止編輯。")
                rerun()
            result = save_finished_machines(delta_df)
            display_df = _display_after_save(current_df)
            st.session_state[STATE_KEY] = display_df
            _set_save_baseline(display_df)
            _refresh_editor_widget()
            st.session_state["v16_finished_edit_enabled"] = False
            st.success(f"儲存完成：送出新增/異動 {stats.get('new_or_changed', 0)} 筆、刪除 {stats.get('deleted', 0)} 筆；實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、刪除 {result.get('deleted', 0)}、略過 {result.get('skipped', 0)}。")
            rerun()

with tab2:
    st.subheader("Excel 匯入 / Excel Import")
    uploaded = st.file_uploader("上傳完工機台 Excel", type=["xlsx", "xlsm", "xls"], key="v16_excel_upload")
    if uploaded is not None:
        sheets = pd.read_excel(uploaded, sheet_name=None)
        sheet = st.selectbox("選擇活頁 / Select Sheet", list(sheets.keys()), key="v16_excel_sheet")
        source_df = sheets[sheet]
        st.dataframe(source_df, use_container_width=True, height=280)
        parsed = parse_pasted_finished_machines(source_df.to_csv(sep="\t", index=False))[0] if not source_df.empty else ensure_cols(pd.DataFrame())
        st.success(f"已解析 {len(parsed)} 筆完工機台資料。")
        st.dataframe(parsed[["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "finished_date", "note", "is_active"]], use_container_width=True, height=300)
        if st.button("▣ 確認匯入 Excel 完工機台 / Import Excel Finished Machines", type="primary", use_container_width=True, key="v16_excel_import_confirm", disabled=not st.session_state.get("v16_finished_edit_enabled", False)):
            result = _apply_import_delta(parsed, "excel")
            st.success(f"Excel 匯入完成：本次送出新增 {result.get('planned_new', 0)}、更新 {result.get('planned_update', 0)}；實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、刪除 {result.get('deleted', 0)}、略過 {result.get('skipped', 0)}；未變更 {result.get('unchanged', 0)}。")
            reload_data(); _refresh_editor_widget(); rerun()
    else:
        st.info("請上傳 Excel。建議欄位：製令、P/N、機型、Category、組立地點、客戶、完工日期、備註、啟用。")

with tab3:
    st.subheader("貼上資料 / Paste Data")
    st.caption("有標題列時會依欄位名稱自動對應；無標題列時使用：製令、P/N、機型、Category、組立地點、客戶、完工日期、備註。")
    raw = st.text_area("貼上 Excel 複製資料", height=260, key="v16_paste_raw")
    if raw.strip():
        parsed, has_header, warnings = parse_pasted_finished_machines(raw)
        if parsed.empty:
            st.error("解析後沒有可儲存資料。請確認至少包含：製令。")
        else:
            st.success(f"已解析 {len(parsed)} 筆完工機台資料。" + ("已偵測標題列。" if has_header else ""))
            for msg in warnings:
                st.warning(msg)
            a1, a2 = st.columns(2)
            if a1.button("⊕ 加入清單編輯 / Add to Editor", type="secondary", use_container_width=True, key="v16_add_paste_to_editor", disabled=not st.session_state.get("v16_finished_edit_enabled", False)):
                st.session_state[STATE_KEY] = pd.concat([parsed, _current_internal_df()], ignore_index=True)
                st.success("已加入『完工機台清單編輯』頁，請切回第一個頁籤確認後按儲存。")
            if a2.button("▣ 直接儲存貼上資料 / Save Pasted Finished Machines", type="primary", use_container_width=True, key="v16_save_paste", disabled=not st.session_state.get("v16_finished_edit_enabled", False)):
                result = _apply_import_delta(parsed, "paste")
                st.success(f"貼上資料已儲存：送出新增 {result.get('planned_new', 0)}、更新 {result.get('planned_update', 0)}；實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、刪除 {result.get('deleted', 0)}、略過 {result.get('skipped', 0)}；未變更 {result.get('unchanged', 0)}。")
                reload_data(); _refresh_editor_widget(); rerun()
            st.markdown("### 解析後資料預覽 / Parsed Preview")
            st.dataframe(parsed[["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "finished_date", "note", "is_active"]], use_container_width=True, height=320)
    else:
        st.info("請先貼上 Excel 資料。建議包含標題列，例如：製令、P/N、機型、Category、組立地點、客戶、完工日期、備註。")

with tab4:
    st.subheader("OneDrive 對應更新 / OneDrive Mapped Read Import")
    st.caption("此功能比照 03｜製令管理：先讀取 OneDrive/Excel 來源，選擇標題列與欄位對應，按下套用後才寫入 16 完工機台權威表。")
    src1, src2 = st.columns([1, 2])
    uploaded_od = src1.file_uploader("上傳來源 Excel / Upload Source", type=["xlsx", "xlsm", "xls"], key="v16_onedrive_upload")
    path_text = src2.text_input("OneDrive Excel 檔案路徑或資料夾 / Source path", key="v16_onedrive_path", placeholder="例如 C:\\Users\\...\\OneDrive\\完工機台.xlsx；若填資料夾會讀取最新 Excel")
    if st.button("讀取來源 / Read Source", type="secondary", use_container_width=True, key="v16_read_onedrive_source"):
        try:
            sheets_raw = _read_excel_source(uploaded_od, path_text)
            if sheets_raw:
                st.session_state["v16_onedrive_sheets_raw"] = sheets_raw
                st.success(f"已讀取 {len(sheets_raw)} 個活頁。")
            else:
                st.warning("沒有讀到 Excel 來源。請確認檔案或路徑。")
        except Exception as exc:
            st.error(f"讀取來源失敗：{exc}")

    sheets_raw = st.session_state.get("v16_onedrive_sheets_raw", {})
    if sheets_raw:
        sheet_names = list(sheets_raw.keys())
        sheet = st.selectbox("選擇活頁 / Select Sheet", sheet_names, key="v16_onedrive_sheet")
        setting_key = f"16_finished_machines::{sheet}"
        cfg = get_sheet_setting(setting_key)
        raw_df = sheets_raw.get(sheet, pd.DataFrame())
        guessed = _guess_header_row(raw_df)
        default_header = int(cfg.get("header_row", guessed) or guessed)
        h1, h2 = st.columns([1, 3])
        header_row = h1.number_input("標題欄是第幾列 / Header row", min_value=1, max_value=max(1, len(raw_df)), value=max(1, min(default_header, max(1, len(raw_df)))), step=1, key=f"v16_header_row_{sheet}")
        h2.caption(f"系統建議標題列：第 {guessed} 列。調整後下方會以該列作為欄位名稱。")
        source_df = _apply_header_row(raw_df, int(header_row))
        st.dataframe(source_df.head(20), use_container_width=True, height=260)
        cols = [""] + list(source_df.columns)
        saved_mapping = cfg.get("mapping", {}) if isinstance(cfg.get("mapping", {}), dict) else {}
        st.session_state["v16_finished_current_mapping"] = saved_mapping
        st.markdown("### 欄位對應 / Column Mapping")
        m1, m2, m3 = st.columns(3)
        mapping = {
            "work_order": m1.selectbox("製令 / Work Order", cols, index=_mapping_index(cols, "work_order", lambda c: "製令" in c or "work" in c.lower() or c.lower() in {"wo", "mo"}), key=f"v16_map_work_order_{sheet}"),
            "part_no": m2.selectbox("P/N / Part No.", cols, index=_mapping_index(cols, "part_no", lambda c: "p/n" in c.lower() or "pn" == c.lower() or "part" in c.lower() or "料號" in c), key=f"v16_map_part_no_{sheet}"),
            "type_name": m3.selectbox("機型 / Type", cols, index=_mapping_index(cols, "type_name", lambda c: "type" in c.lower() or "機型" in c or "型號" in c), key=f"v16_map_type_name_{sheet}"),
            "category": m1.selectbox("類別 / Category", cols, index=_mapping_index(cols, "category", lambda c: "category" in c.lower() or "類別" in c or "分類" in c), key=f"v16_map_category_{sheet}"),
            "assembly_location": m2.selectbox("組立地點 / Assembly Location", cols, index=_mapping_index(cols, "assembly_location", lambda c: "組立" in c or "組裝" in c or "assembly" in c.lower() or "location" in c.lower()), key=f"v16_map_location_{sheet}"),
            "customer": m3.selectbox("客戶 / Customer", cols, index=_mapping_index(cols, "customer", lambda c: "客戶" in c or "customer" in c.lower() or "client" in c.lower()), key=f"v16_map_customer_{sheet}"),
            "finished_date": m1.selectbox("完工日期 / Finished Date", cols, index=_mapping_index(cols, "finished_date", lambda c: "完工" in c or "完成" in c or "入庫" in c or "出貨" in c or "finish" in c.lower() or "completion" in c.lower()), key=f"v16_map_finished_date_{sheet}"),
            "note": m2.selectbox("備註 / Note", cols, index=_mapping_index(cols, "note", lambda c: "備註" in c or "note" in c.lower() or "remark" in c.lower()), key=f"v16_map_note_{sheet}"),
            "is_active": m3.selectbox("啟用 / Active", cols, index=_mapping_index(cols, "is_active", lambda c: "啟用" in c or "active" in c.lower() or "狀態" in c), key=f"v16_map_active_{sheet}"),
        }
        delete_missing = st.checkbox("套用時刪除本模組中『來源不存在』的完工製令 / Delete missing from source", value=bool(cfg.get("delete_missing", False)), key=f"v16_delete_missing_{sheet}")
        parsed = _map_finished_machines(source_df, mapping)
        st.success(f"依目前欄位對應可解析 {len(parsed)} 筆完工機台資料。")
        st.dataframe(parsed[["work_order", "part_no", "type_name", "category", "assembly_location", "customer", "finished_date", "note", "is_active"]].head(200), use_container_width=True, height=320)
        b1, b2 = st.columns(2)
        # V16.1: OneDrive read import writes through its own explicit Apply button.
        # It should not be disabled by the manual table edit lock; otherwise users can
        # read and preview 1,800+ rows but cannot import them.  Keep only data-safety
        # guards: a source work-order mapping and at least one parsed row.
        apply_disabled = parsed.empty or not str(mapping.get("work_order", "") or "").strip()
        if not st.session_state.get("v16_finished_edit_enabled", False):
            st.caption("OneDrive 讀取匯入不需要先啟動『製令清單編輯』；按下套用後才會寫入 16 完工機台權威資料。")
        if str(mapping.get("is_active", "") or "").strip() == "":
            st.caption("未指定『啟用 / Active』欄位時，匯入資料會預設為啟用，用來隱藏 01 工時紀錄下拉中的完工製令。")
        if b1.button("儲存此活頁欄位對應 / Save Mapping", use_container_width=True, key=f"v16_save_mapping_{sheet}"):
            save_sheet_setting(setting_key, int(header_row), mapping, bool(delete_missing), import_mode="finished_machines", row_key_col="work_order")
            st.success("OneDrive 欄位對應已永久保存。")
        if b2.button("▣ 套用讀取結果匯入完工機台 / Apply Read Import", type="primary", use_container_width=True, key=f"v16_apply_onedrive_{sheet}", disabled=apply_disabled):
            save_sheet_setting(setting_key, int(header_row), mapping, bool(delete_missing), import_mode="finished_machines", row_key_col="work_order")
            payload = parsed
            if delete_missing:
                missing = make_delete_missing_rows(parsed, load_finished_machines(active_only=None))
                if not missing.empty:
                    payload = pd.concat([payload, missing], ignore_index=True)
            result = _apply_import_delta(payload, "onedrive") if not payload.empty else {"planned_count": 0, "planned_new": 0, "planned_update": 0, "inserted": 0, "updated": 0, "deleted": 0, "skipped": 0, "unchanged": 0}
            st.success(f"OneDrive 對應更新完成：送出新增 {result.get('planned_new', 0)}、更新 {result.get('planned_update', 0)}；實際新增 {result.get('inserted', 0)}、更新 {result.get('updated', 0)}、刪除 {result.get('deleted', 0)}、略過 {result.get('skipped', 0)}；未變更 {result.get('unchanged', 0)}。")
            reload_data(); _refresh_editor_widget(); rerun()
    else:
        st.info("請先上傳來源 Excel，或輸入 OneDrive 同步到本機的 Excel 檔案路徑後按『讀取來源』。")
