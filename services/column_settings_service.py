# -*- coding: utf-8 -*-
"""
V1.72 Column Settings Service
全系統表格欄位設定：顯示/隱藏、順序、欄寬、中文/英文標題，永久保存到 JSON。

設計原則：
- 不修改各頁邏輯，透過 monkey patch 包裝 st.dataframe / st.data_editor。
- 不刪除原始欄位；data_editor 隱藏欄位會在返回值時自動合併回來，避免資料遺失。
- 設定檔保存於 data/persistent_state/spt_table_column_settings.json，可納入 GitHub 永久保存。
"""
from __future__ import annotations

import inspect
import json
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
SETTINGS_PATH = STATE_DIR / "spt_table_column_settings.json"

_ORIGINAL_DATAFRAME = None
_ORIGINAL_DATA_EDITOR = None


# 常見欄位中文/英文對照；找不到時仍保留原欄位名
COLUMN_LABELS = {
    "id": "ID / ID",
    "record_key": "紀錄鍵 / Record Key",
    "status": "狀態 / Status",
    "work_order": "製令 / Work Order",
    "part_no": "P/N / Part No.",
    "type_name": "機型 / Type",
    "process_name": "工段 / Process",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "start_action": "開始動作 / Start Action",
    "start_timestamp": "開始時間戳 / Start Timestamp",
    "end_action": "結束動作 / End Action",
    "end_timestamp": "結束時間戳 / End Timestamp",
    "remark": "備註 / Note",
    "start_date": "開始日期 / Start Date",
    "start_time": "開始時間 / Start Time",
    "end_date": "結束日期 / End Date",
    "end_time": "結束時間 / End Time",
    "work_hours": "工時小計 / Work Hours",
    "work_hours_hms": "工時小計 / Work Hours",
    "total_hours": "累積工時 / Total Hours",
    "total_hours_hms": "累積工時 / Total Hours",
    "assembly_location": "組立地點 / Assembly Location",
    "group_key": "同時作業鍵 / Parallel Key",
    "is_group_work": "同時作業 / Parallel Work",
    "is_parallel_work": "同時作業 / Parallel Work",
    "source": "來源 / Source",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
    "username": "帳號 / Username",
    "display_name": "姓名 / Display Name",
    "password_status": "密碼狀態 / Password Status",
    "new_password": "新密碼 / New Password",
    "email": "Email / Email",
    "roles": "角色 / Role",
    "role": "角色 / Role",
    "is_active": "啟用 / Active",
    "force_password_change": "強制改密碼 / Force Change",
    "delete": "刪除 / Delete",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "今日出勤 / Today Attendance",
    "customer": "客戶 / Customer",
    "note": "備註 / Note",
    "log_time": "紀錄時間 / Log Time",
    "user_name": "使用者 / User",
    "action_type": "動作 / Action",
    "target_table": "目標表 / Target Table",
    "target_id": "目標ID / Target ID",
    "message": "訊息 / Message",
    "detail": "詳細 / Detail",
    "level": "等級 / Level",
    "event_type": "事件 / Event",
    "result": "結果 / Result",
    "module_code": "模組代碼 / Module Code",
    "login_time": "登入時間 / Login Time",
    "logout_time": "登出時間 / Logout Time",
    "idle_minutes": "閒置分鐘 / Idle Minutes",
}

WIDTH_OPTIONS = {
    "小 / Small": "small",
    "中 / Medium": "medium",
    "大 / Large": "large",
}


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    gitkeep = STATE_DIR / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("keep persistent state files\n", encoding="utf-8")


def load_settings() -> Dict[str, Any]:
    _ensure_state_dir()
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_settings(settings: Dict[str, Any]) -> None:
    _ensure_state_dir()
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_df(data: Any) -> pd.DataFrame | None:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    try:
        return pd.DataFrame(data).copy()
    except Exception:
        return None


def _current_page_name() -> str:
    try:
        # Streamlit page script is usually the last user file in stack under /pages or root
        for frame in reversed(inspect.stack()):
            filename = str(frame.filename).replace("\\", "/")
            if "/pages/" in filename or filename.endswith("streamlit_app.py"):
                return Path(filename).stem
    except Exception:
        pass
    return "unknown_page"


def _callsite_signature() -> str:
    """Return a stable page call-site signature to avoid duplicate widget keys.

    Several pages render different tables through the same shared helper.  If the
    column settings wrapper only uses the dataframe columns, two tables with the
    same structure can receive the same Streamlit widget key and crash with
    StreamlitDuplicateElementKey.  We include the real page filename + line number
    that called the helper, while ignoring this service and Streamlit internals.
    """
    try:
        frames = inspect.stack()
        candidates = []
        for frame in frames:
            filename = str(frame.filename).replace("\\", "/")
            if "/site-packages/" in filename or filename.endswith("column_settings_service.py"):
                continue
            if filename.endswith("table_ui_service.py"):
                continue
            if "/pages/" in filename or filename.endswith("streamlit_app.py"):
                candidates.append(f"{Path(filename).stem}:{frame.lineno}")
        if candidates:
            return candidates[-1]
    except Exception:
        pass
    return "unknown_callsite"


def _safe_widget_suffix(value: str) -> str:
    return hashlib.md5(str(value).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _stable_table_id(df: pd.DataFrame, key: Any = None, kind: str = "table") -> str:
    page = _current_page_name()
    callsite = _callsite_signature()
    if key:
        return f"{page}::{callsite}::{kind}::{key}"
    cols = "|".join([str(c) for c in df.columns])[:180]
    return f"{page}::{callsite}::{kind}::{abs(hash(cols))}"


def _default_column_setting(col: str) -> Dict[str, Any]:
    return {
        "source": str(col),
        "label": COLUMN_LABELS.get(str(col), f"{col} / {col}"),
        "visible": True,
        "width": "medium",
        "order": 999,
    }


def _get_table_setting(table_id: str, columns: Iterable[str]) -> Dict[str, Any]:
    all_settings = load_settings()
    table_setting = all_settings.get(table_id, {})
    col_settings = table_setting.get("columns", {})
    # 補齊新欄位，不覆蓋既有設定
    for idx, col in enumerate(columns):
        c = str(col)
        if c not in col_settings:
            col_settings[c] = _default_column_setting(c)
            col_settings[c]["order"] = idx
    table_setting["columns"] = col_settings
    all_settings[table_id] = table_setting
    save_settings(all_settings)
    return table_setting


def _save_table_setting(table_id: str, table_setting: Dict[str, Any]) -> None:
    all_settings = load_settings()
    all_settings[table_id] = table_setting
    save_settings(all_settings)


def _build_column_config(df: pd.DataFrame, table_setting: Dict[str, Any]) -> Dict[str, Any]:
    config = {}
    col_settings = table_setting.get("columns", {})
    for col in df.columns:
        key = str(col)
        meta = col_settings.get(key, _default_column_setting(key))
        label = meta.get("label") or COLUMN_LABELS.get(key, f"{key} / {key}")
        width = meta.get("width") or "medium"
        try:
            config[col] = st.column_config.Column(label=label, width=width)
        except Exception:
            # 舊版 Streamlit 相容
            config[col] = label
    return config


def _visible_order(df: pd.DataFrame, table_setting: Dict[str, Any], editable: bool) -> List[str]:
    col_settings = table_setting.get("columns", {})
    rows = []
    for idx, col in enumerate(df.columns):
        key = str(col)
        meta = col_settings.get(key, _default_column_setting(key))
        visible = bool(meta.get("visible", True))
        # 刪除欄與 ID 欄預設保護：可隱藏，但 data_editor 回傳會合併回原欄位
        rows.append((int(meta.get("order", idx)), key, visible))
    rows.sort(key=lambda x: (x[0], x[1]))
    visible_cols = [key for _, key, visible in rows if visible and key in [str(c) for c in df.columns]]
    # 全部被隱藏時，避免表格空白
    if not visible_cols:
        visible_cols = [str(c) for c in df.columns]
    # 用原欄位物件回傳，避免欄位型別不同
    lookup = {str(c): c for c in df.columns}
    return [lookup[c] for c in visible_cols if c in lookup]


def _settings_editor(table_id: str, df: pd.DataFrame, editable: bool) -> Tuple[Dict[str, Any], bool]:
    table_setting = _get_table_setting(table_id, [str(c) for c in df.columns])
    col_settings = table_setting.get("columns", {})

    with st.expander("欄位設定 / Column Settings（永久保存）", expanded=False):
        st.caption("可設定每個表格欄位的顯示、順序、欄寬與標題。按『套用欄位設定』後會永久保存到 data/persistent_state/spt_table_column_settings.json。")
        rows = []
        for idx, col in enumerate(df.columns):
            key = str(col)
            meta = col_settings.get(key, _default_column_setting(key))
            rows.append({
                "顯示 / Visible": bool(meta.get("visible", True)),
                "欄位 / Column": key,
                "標題 / Header": meta.get("label") or COLUMN_LABELS.get(key, f"{key} / {key}"),
                "順序 / Order": int(meta.get("order", idx)),
                "欄寬 / Width": meta.get("width", "medium"),
            })
        cfg_df = pd.DataFrame(rows)
        _editor_func = _ORIGINAL_DATA_EDITOR or st.data_editor
        edited_cfg = _editor_func(
            cfg_df,
            key=f"column_setting_editor::{_safe_widget_suffix(table_id)}",
            use_container_width=True,
            hide_index=True,
            height=360,
            num_rows="fixed",
            column_config={
                "顯示 / Visible": st.column_config.CheckboxColumn("顯示 / Visible"),
                "欄位 / Column": st.column_config.TextColumn("欄位 / Column", disabled=True),
                "標題 / Header": st.column_config.TextColumn("標題 / Header"),
                "順序 / Order": st.column_config.NumberColumn("順序 / Order", min_value=0, step=1),
                "欄寬 / Width": st.column_config.SelectboxColumn("欄寬 / Width", options=list(WIDTH_OPTIONS.values())),
            },
        )
        st.markdown("#### 欄位順序快速設定 / Column Order")
        current_order = sorted(
            [str(c) for c in df.columns],
            key=lambda x: int(col_settings.get(x, _default_column_setting(x)).get("order", 999)),
        )
        order_text = st.text_area(
            "欄位順序 / Column order（每行一個欄位；可剪下貼上調整順序，按套用後永久保存）",
            value="\n".join(current_order),
            key=f"column_order_text::{_safe_widget_suffix(table_id)}",
            height=420,
            help="每行一個欄位名稱。可直接在這個大型文字框內剪下/貼上調整欄位順序，按套用後會永久保存。Streamlit 原生表格目前無法穩定讀取滑鼠拖拉後的欄位順序。",
        )
        c1, c2, c3 = st.columns([1, 1, 2])
        applied = False
        with c1:
            if st.button("💾 套用欄位設定 / Apply", key=f"apply_cols::{_safe_widget_suffix(table_id)}", use_container_width=True):
                new_cols = {}
                for _, row in edited_cfg.iterrows():
                    key = str(row.get("欄位 / Column", "")).strip()
                    if not key:
                        continue
                    new_cols[key] = {
                        "source": key,
                        "label": str(row.get("標題 / Header") or key),
                        "visible": bool(row.get("顯示 / Visible", True)),
                        "width": str(row.get("欄寬 / Width") or "medium"),
                        "order": int(row.get("順序 / Order", 999)),
                    }
                try:
                    text_order = [x.strip() for x in str(order_text).splitlines() if x.strip()]
                    used = set()
                    order_no = 0
                    for key in text_order:
                        if key in new_cols and key not in used:
                            new_cols[key]["order"] = order_no
                            used.add(key)
                            order_no += 1
                    for key in new_cols:
                        if key not in used:
                            new_cols[key]["order"] = order_no
                            order_no += 1
                except Exception:
                    pass
                table_setting["columns"] = new_cols
                _save_table_setting(table_id, table_setting)
                st.success("欄位設定已永久保存。")
                applied = True
        with c2:
            if st.button("↩️ 恢復預設 / Reset", key=f"reset_cols::{_safe_widget_suffix(table_id)}", use_container_width=True):
                table_setting["columns"] = {str(c): {**_default_column_setting(str(c)), "order": i} for i, c in enumerate(df.columns)}
                _save_table_setting(table_id, table_setting)
                st.warning("已恢復此表格欄位預設設定。")
                applied = True
        with c3:
            st.caption(f"表格ID：{table_id}")
    if applied:
        table_setting = _get_table_setting(table_id, [str(c) for c in df.columns])
    return table_setting, applied


def _merge_hidden_back(original: pd.DataFrame, edited: Any) -> Any:
    """data_editor 隱藏欄位時，避免返回資料遺失隱藏欄位。"""
    if not isinstance(edited, pd.DataFrame):
        try:
            edited_df = pd.DataFrame(edited)
        except Exception:
            return edited
    else:
        edited_df = edited.copy()
    try:
        for col in original.columns:
            if col not in edited_df.columns:
                if len(edited_df) <= len(original):
                    edited_df[col] = list(original[col].iloc[:len(edited_df)])
                else:
                    # 新增列補空值
                    edited_df[col] = None
                    edited_df.loc[:len(original)-1, col] = list(original[col])
        # 保留原順序，新增欄位放後面
        ordered = [c for c in original.columns if c in edited_df.columns] + [c for c in edited_df.columns if c not in original.columns]
        return edited_df[ordered]
    except Exception:
        return edited



def _cell_to_text(v: Any) -> str:
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v)


def _source_signature(df: pd.DataFrame) -> str:
    """Lightweight signature for deciding whether an editor source is the same table.

    We intentionally do NOT hash every cell, because that would reset the unsaved draft
    whenever the page rebuilds the source dataframe from DB during a rerun.  The goal is
    to keep the user's in-progress edits until they explicitly save/reload.
    """
    try:
        cols = [str(c) for c in df.columns]
        row_count = len(df)
        id_hint = ""
        for key_col in ("id", "ID / ID", "帳號 / Username", "username", "employee_id", "work_order", "record_key"):
            if key_col in df.columns:
                vals = [_cell_to_text(x) for x in df[key_col].head(80).tolist()]
                id_hint = "|".join(vals)
                break
        return f"rows={row_count};cols={'|'.join(cols)};ids={id_hint}"
    except Exception:
        return f"rows={len(df)};cols={'|'.join(map(str, df.columns))}"


def _align_draft_to_source(draft: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    """Keep unsaved draft edits while accepting new rows/columns from source."""
    try:
        out = draft.copy()
        # Add new columns from source.
        for col in source.columns:
            if col not in out.columns:
                out[col] = None
                if len(source) >= len(out):
                    out.loc[: len(out) - 1, col] = list(source[col].iloc[: len(out)])
        # If the page added rows to the source, append them to the draft.
        if len(source) > len(out):
            extra = source.iloc[len(out):].copy()
            for col in out.columns:
                if col not in extra.columns:
                    extra[col] = None
            out = pd.concat([out, extra[out.columns]], ignore_index=True)
        # Preserve column order based on source, but keep extra columns at the end.
        ordered = [c for c in source.columns if c in out.columns] + [c for c in out.columns if c not in source.columns]
        return out[ordered].reset_index(drop=True)
    except Exception:
        return draft


def _get_editor_draft(table_id: str, source_df: pd.DataFrame) -> pd.DataFrame:
    """Return a persistent in-session draft for st.data_editor.

    This prevents the common Streamlit rerun problem where a user edits a cell, then a
    selectbox/expander/button reruns the page and the table is rebuilt from the database,
    making the just-entered value appear to disappear before pressing Save.
    """
    draft_key = f"_spt_editor_draft::{table_id}"
    sig_key = f"_spt_editor_source_sig::{table_id}"
    current_sig = _source_signature(source_df)
    existing = st.session_state.get(draft_key)
    existing_sig = st.session_state.get(sig_key)
    if isinstance(existing, pd.DataFrame):
        # Same table shape/keyset: keep user's unsaved edits.
        if existing_sig == current_sig:
            return _align_draft_to_source(existing, source_df)
        # If only row count/columns changed, still try to preserve edits and append source rows.
        try:
            old_cols = set(map(str, existing.columns))
            new_cols = set(map(str, source_df.columns))
            if old_cols == new_cols and len(source_df) >= len(existing):
                merged = _align_draft_to_source(existing, source_df)
                st.session_state[draft_key] = merged
                st.session_state[sig_key] = current_sig
                return merged
        except Exception:
            pass
    draft = source_df.copy()
    st.session_state[draft_key] = draft
    st.session_state[sig_key] = current_sig
    return draft


def _set_editor_draft(table_id: str, edited: Any) -> None:
    try:
        if isinstance(edited, pd.DataFrame):
            st.session_state[f"_spt_editor_draft::{table_id}"] = edited.copy()
        else:
            st.session_state[f"_spt_editor_draft::{table_id}"] = pd.DataFrame(edited)
    except Exception:
        pass


def clear_editor_draft(table_key_contains: str | None = None) -> int:
    """Clear saved editor drafts.  Useful after a real Save/Reload action.

    This function is safe to import from pages; it does nothing if no drafts exist.
    """
    keys = list(st.session_state.keys())
    removed = 0
    for k in keys:
        if k.startswith("_spt_editor_draft::") or k.startswith("_spt_editor_source_sig::"):
            if table_key_contains is None or table_key_contains in k:
                st.session_state.pop(k, None)
                removed += 1
    return removed



# ===== V1.72 全表格啟動/停止編輯保護 =====
def _edit_mode_state_key(table_id: str) -> str:
    return f"_spt_table_edit_enabled::{_safe_widget_suffix(table_id)}"


def _render_editor_lock_controls(table_id: str) -> bool:
    """Render a consistent edit lock bar for every st.data_editor table.

    Default is locked/read-only.  The user must click Enable Edit before editing.
    This prevents Streamlit reruns from repeatedly rebuilding an editable table
    while the user is still entering data.
    """
    state_key = _edit_mode_state_key(table_id)
    if state_key not in st.session_state:
        st.session_state[state_key] = False

    c1, c2, c3 = st.columns([1, 1, 2.7])
    with c1:
        if st.button("🔓 啟動編輯 / Enable Edit", key=f"enable_edit::{_safe_widget_suffix(table_id)}", use_container_width=True):
            st.session_state[state_key] = True
    with c2:
        if st.button("🔒 停止編輯 / Lock Edit", key=f"lock_edit::{_safe_widget_suffix(table_id)}", use_container_width=True):
            st.session_state[state_key] = False
            # Stop editing means cancel current unsaved draft for this table only.
            clear_editor_draft(table_id)
    with c3:
        if bool(st.session_state.get(state_key)):
            st.success("目前狀態：已啟動編輯。修改完成後請按本頁的儲存 / 套用按鈕，資料才會正式寫入。")
        else:
            st.info("目前狀態：唯讀保護。請先按『啟動編輯』再修改表格資料。")
    return bool(st.session_state.get(state_key))

def install_column_settings_patch() -> None:
    """全域安裝表格欄位設定包裝，不需要逐頁改程式。"""
    if getattr(st, "_spt_column_settings_installed", False):
        return

    global _ORIGINAL_DATAFRAME, _ORIGINAL_DATA_EDITOR
    original_dataframe = st.dataframe
    original_data_editor = st.data_editor
    _ORIGINAL_DATAFRAME = original_dataframe
    _ORIGINAL_DATA_EDITOR = original_data_editor

    def dataframe_wrapper(data=None, *args, **kwargs):
        df = _normalize_df(data)
        if df is not None and len(df.columns) > 0:
            key = kwargs.get("key")
            table_id = _stable_table_id(df, key=key, kind="dataframe")
            table_setting, _ = _settings_editor(table_id, df, editable=False)
            kwargs.setdefault("use_container_width", True)
            kwargs["column_config"] = {**_build_column_config(df, table_setting), **kwargs.get("column_config", {})}
            kwargs["column_order"] = kwargs.get("column_order") or _visible_order(df, table_setting, editable=False)
        return original_dataframe(data, *args, **kwargs)

    def data_editor_wrapper(data=None, *args, **kwargs):
        df = _normalize_df(data)
        if df is not None and len(df.columns) > 0:
            key = kwargs.get("key")
            table_id = _stable_table_id(df, key=key, kind="data_editor")
            table_setting, _ = _settings_editor(table_id, df, editable=True)
            edit_enabled = _render_editor_lock_controls(table_id)
            kwargs.setdefault("use_container_width", True)
            kwargs.setdefault("key", f"spt_data_editor::{_safe_widget_suffix(table_id)}")
            kwargs["column_config"] = {**_build_column_config(df, table_setting), **kwargs.get("column_config", {})}
            kwargs["column_order"] = kwargs.get("column_order") or _visible_order(df, table_setting, editable=True)
            if not edit_enabled:
                kwargs["disabled"] = True
            draft_df = _get_editor_draft(table_id, df)
            edited = original_data_editor(draft_df, *args, **kwargs)
            merged = _merge_hidden_back(draft_df, edited)
            if edit_enabled:
                _set_editor_draft(table_id, merged)
            return merged
        edited = original_data_editor(data, *args, **kwargs)
        return edited

    st.dataframe = dataframe_wrapper
    st.data_editor = data_editor_wrapper
    st._spt_column_settings_installed = True


# 手動測試用
if __name__ == "__main__":
    print(f"Column settings path: {SETTINGS_PATH}")
