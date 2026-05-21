# -*- coding: utf-8 -*-
"""
V1.72 Column Settings Service
全系統表格欄位設定：顯示/隱藏、順序、欄寬、中文/英文標題，永久保存到 JSON。

設計原則：
- 不修改各頁邏輯，透過 monkey patch 包裝 st.dataframe / st.data_editor。
- 不刪除原始欄位；data_editor 隱藏欄位會在返回值時自動合併回來，避免資料遺失。
- 設定檔保存於 data/permanent_store/persistent_state/spt_table_column_settings.json，可納入 GitHub 永久保存。
"""
from __future__ import annotations

import inspect
import json
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state"
SETTINGS_PATH = STATE_DIR / "spt_table_column_settings.json"

# V3.51：只做輕量永久鏡像，不掃 history、不登入時 GitHub 上傳，避免 V3.50 造成無限運行。
COLUMN_SETTINGS_MIRROR_PATHS = [
    SETTINGS_PATH,
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_column_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_table_column_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_column_settings.json",
]

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


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _normalize_widget_key_for_table_id(key: Any) -> str:
    text = str(key or "").strip()
    if not text:
        return ""
    # 10 權限管理曾使用 revision key，例如 v171_account_password_editor_0。
    text = re.sub(r"_(rev|revision)?\d+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^0-9A-Za-z_\-\.\u4e00-\u9fff]+", "_", text).strip("_")
    return text or "table"


def _canonical_table_id(table_id: str) -> str:
    raw = str(table_id or "")
    parts = raw.split("::")
    if len(parts) >= 4 and parts[-2] in {"dataframe", "data_editor"}:
        key = _normalize_widget_key_for_table_id(parts[-1])
        if key:
            return f"global::{parts[-2]}::{key}"
    raw = re.sub(r"v171_account_password_editor_\d+", "v171_account_password_editor", raw)
    return raw


def _normalize_loaded_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("table_column_settings_v2"), dict):
        base = dict(data.get("table_column_settings_v2") or {})
    elif isinstance(data.get("settings"), dict) and isinstance(data["settings"].get("table_column_settings_v2"), dict):
        base = dict(data["settings"].get("table_column_settings_v2") or {})
    else:
        base = {k: v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("columns"), dict)}
    # 加入 canonical alias，不刪舊 key；讓 V350 前後的 key 都讀得到。
    for k, v in list(base.items()):
        ck = _canonical_table_id(k)
        if ck and ck not in base and isinstance(v, dict):
            base[ck] = v
    return base


def load_settings() -> Dict[str, Any]:
    """Load column settings from lightweight permanent files only.

    V3.51 修正 V3.50 無限運行：
    - 不掃 history 資料夾。
    - 不在 load 時回寫檔案。
    - 不觸發 GitHub 上傳或 mark_data_changed。
    """
    _ensure_state_dir()
    merged: Dict[str, Any] = {}
    # 後面的檔案只補缺口；主要檔案仍優先。
    for path in COLUMN_SETTINGS_MIRROR_PATHS:
        data = _normalize_loaded_settings(_read_json_file(path))
        for k, v in data.items():
            merged.setdefault(k, v)
    return merged


def save_settings(settings: Dict[str, Any]) -> None:
    _ensure_state_dir()
    normalized = dict(settings or {})
    for k, v in list(normalized.items()):
        ck = _canonical_table_id(k)
        if ck and ck not in normalized and isinstance(v, dict):
            normalized[ck] = v
    # 主檔維持舊格式：{table_id:{columns:{...}}}
    try:
        from services.persistence_guard_service import atomic_save_json
        atomic_save_json(SETTINGS_PATH, normalized, backup_existing=True)
    except Exception:
        tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(SETTINGS_PATH)
    # 輕量鏡像，僅供 Reboot 後救援；不寫 history、不上傳 GitHub。
    payload = {
        "version": "V3.51",
        "description": "全系統表格欄位設定永久鏡像；V3.51 起避免登入/載入時重流程造成無限運行。",
        "table_column_settings_v2": normalized,
        "table_count": len(normalized),
    }
    for path in COLUMN_SETTINGS_MIRROR_PATHS:
        if path == SETTINGS_PATH:
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            json.loads(tmp.read_text(encoding="utf-8"))
            tmp.replace(path)
        except Exception:
            pass


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
            # V361: use the nearest real page call-site, not the outer module call.
            # candidates[-1] can be the page-level render function call, causing
            # multiple st.dataframe/st.data_editor calls inside the same helper to
            # share one widget key and raise StreamlitDuplicateElementKey.
            return candidates[0]
    except Exception:
        pass
    return "unknown_callsite"


def _safe_widget_suffix(value: str) -> str:
    return hashlib.md5(str(value).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _stable_table_id(df: pd.DataFrame, key: Any = None, kind: str = "table") -> str:
    # 有明確 key 的表格使用穩定全域 key，避免 Reboot / 程式行號改變後讀不到欄位設定。
    # 沒有 key 的表格仍保留 page + callsite，避免同頁多表格撞 key。
    if key:
        stable_key = _normalize_widget_key_for_table_id(key)
        return f"global::{kind}::{stable_key}"
    page = _current_page_name()
    callsite = _callsite_signature()
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
    table_setting = all_settings.get(table_id) or all_settings.get(_canonical_table_id(table_id)) or {}
    if not isinstance(table_setting, dict):
        table_setting = {}
    col_settings = table_setting.get("columns", {}) if isinstance(table_setting.get("columns", {}), dict) else {}
    changed = table_id not in all_settings
    # 補齊新欄位，不覆蓋既有設定；沒變更就不寫檔，避免每次進頁都觸發重跑。
    for idx, col in enumerate(columns):
        c = str(col)
        if c not in col_settings:
            col_settings[c] = _default_column_setting(c)
            col_settings[c]["order"] = idx
            changed = True
    if table_setting.get("columns") != col_settings:
        table_setting["columns"] = col_settings
        changed = True
    if changed:
        all_settings[table_id] = table_setting
        ck = _canonical_table_id(table_id)
        if ck and ck != table_id:
            all_settings[ck] = table_setting
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
    """Render column setting UI without normal st.button controls.

    V1.73 修正：
    - 前版在全域 data_editor wrapper 內加入「啟動/停止編輯」按鈕，遇到頁面本身已經有
      啟動/停止編輯時會重複顯示。
    - 若頁面把 data_editor 放在 st.form 內，欄位設定區的 st.button 會觸發
      StreamlitAPIException: st.button() can't be used in an st.form。

    因此本函式改成「自動保存欄位設定」：欄位設定表與欄位順序文字框修改後，會在該次 rerun
    或表單提交後自動寫入設定檔，不再在這個共用 wrapper 內產生 st.button。
    """
    table_setting = _get_table_setting(table_id, [str(c) for c in df.columns])
    col_settings = table_setting.get("columns", {})

    with st.expander("欄位設定 / Column Settings（永久保存）", expanded=False):
        st.caption(
            "可設定每個表格欄位的顯示、順序、欄寬與標題。修改後會自動保存到 "
            "data/permanent_store/persistent_state/spt_table_column_settings.json。"
        )
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
            "欄位順序 / Column order（每行一個欄位；可剪下貼上調整順序，會自動永久保存）",
            value="\n".join(current_order),
            key=f"column_order_text::{_safe_widget_suffix(table_id)}",
            height=420,
            help="每行一個欄位名稱。可直接剪下/貼上調整欄位順序。Streamlit 原生表格目前無法穩定讀取滑鼠拖拉後的欄位順序。",
        )
        st.caption(f"表格ID：{table_id}")

    # Auto-save settings without using st.button, so this wrapper is safe inside st.form.
    new_cols = {}
    try:
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
        new_cols = dict(col_settings)

    applied = False
    if new_cols and new_cols != table_setting.get("columns", {}):
        table_setting["columns"] = new_cols
        _save_table_setting(table_id, table_setting)
        applied = True
        # 不使用 success toast，避免每次 rerun 過度干擾畫面。

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



# ===== V1.72 全表格啟動/停止編輯保護（V1.73 已停用自動顯示，保留函式供相容） =====
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



def _safe_streamlit_column_order(df: pd.DataFrame, order: Any) -> list[str] | None:
    """Return a Streamlit-safe column_order list.

    Streamlit may raise TypeError when a persisted column order contains
    non-string values, missing columns, pandas Index objects, or values from
    another table.  This sanitizer keeps only existing columns and converts
    everything to plain strings.
    """
    if df is None or order is None:
        return None
    try:
        existing = [str(c) for c in list(df.columns)]
    except Exception:
        return None
    if not existing:
        return None
    if isinstance(order, str):
        raw = [order]
    else:
        try:
            raw = list(order)
        except Exception:
            return None
    clean: list[str] = []
    seen: set[str] = set()
    existing_set = set(existing)
    for item in raw:
        if item is None:
            continue
        col = str(item)
        if col in existing_set and col not in seen:
            clean.append(col)
            seen.add(col)
    return clean or None


def _inject_native_header_sort_style() -> None:
    """Style-only helper for native Streamlit table header sorting.

    It does not add sort buttons or a sort panel.  It only makes the existing
    table header row visibly clickable across all modules, including direct
    st.dataframe / st.data_editor calls that bypass table_ui_service.render_table.
    """
    try:
        st.markdown(
            """
            <style>
            /* V2.91｜全域表格標題列左鍵排序提示：維持原標題列，不新增任何位置 */
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
    except Exception:
        pass




def _apply_settings_to_df(df: pd.DataFrame, table_setting: Dict[str, Any], editable: bool) -> pd.DataFrame:
    """V2.93 compatibility helper.

    Older patch code may call this helper. Keep it intentionally conservative:
    return the original dataframe and let Streamlit column_order/column_config
    handle visual order/hidden columns so no data is lost.
    """
    try:
        return df.copy()
    except Exception:
        return df

# ===== V2.92 NATIVE HEADER SORT FOR LOCKED EDITORS START =====
def _v292_is_fully_locked_editor(kwargs: dict) -> bool:
    """Return True when a data_editor is being used only as read-only display.

    Streamlit's editable grid can make header sort unreliable when it is rendered
    disabled inside a form.  For locked/read-only mode, render the same data via
    st.dataframe so the original header row keeps native left-click sorting.
    """
    try:
        disabled = kwargs.get("disabled", False)
        if disabled is True:
            return True
        if isinstance(disabled, (list, tuple, set)) and disabled:
            # Only treat it as fully locked if every visible column is disabled; normal partial-disabled
            # data_editor should stay editable.
            return False
    except Exception:
        pass
    return False


def _v292_locked_editor_as_sortable_dataframe(original_dataframe, df: pd.DataFrame, *args, **kwargs):
    """Render locked st.data_editor as st.dataframe and return df unchanged."""
    frame_kwargs = dict(kwargs)
    # data_editor-only arguments that st.dataframe does not accept.
    for k in [
        "num_rows", "disabled", "on_change", "args", "kwargs",
        "row_height", "column_order", "hide_index", "use_container_width",
        "height", "width", "key", "column_config",
    ]:
        pass
    dataframe_kwargs = {
        "use_container_width": frame_kwargs.get("use_container_width", True),
        "hide_index": frame_kwargs.get("hide_index", True),
    }
    if frame_kwargs.get("height") is not None:
        dataframe_kwargs["height"] = frame_kwargs.get("height")
    if frame_kwargs.get("width") is not None:
        dataframe_kwargs["width"] = frame_kwargs.get("width")
    if frame_kwargs.get("key") is not None:
        dataframe_kwargs["key"] = f"readonly_sort::{_safe_widget_suffix(str(frame_kwargs.get('key')))}"
    if frame_kwargs.get("column_config") is not None:
        dataframe_kwargs["column_config"] = frame_kwargs.get("column_config")
    if frame_kwargs.get("column_order") is not None:
        safe_order = _safe_streamlit_column_order(df, frame_kwargs.get("column_order"))
        if safe_order:
            dataframe_kwargs["column_order"] = safe_order
    try:
        original_dataframe(df, **dataframe_kwargs)
    except TypeError:
        dataframe_kwargs.pop("column_order", None)
        original_dataframe(df, **dataframe_kwargs)
    return df.copy()
# ===== V2.92 NATIVE HEADER SORT FOR LOCKED EDITORS END =====

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
        _inject_native_header_sort_style()
        df = _normalize_df(data)
        if df is not None and len(df.columns) > 0:
            key = kwargs.get("key")
            table_id = _stable_table_id(df, key=key, kind="dataframe")
            table_setting, _ = _settings_editor(table_id, df, editable=False)
            kwargs.setdefault("use_container_width", True)
            kwargs["column_config"] = {**_build_column_config(df, table_setting), **kwargs.get("column_config", {})}
            raw_order = kwargs.get("column_order") or _visible_order(df, table_setting, editable=False)
            safe_order = _safe_streamlit_column_order(df, raw_order)
            if safe_order:
                kwargs["column_order"] = safe_order
            else:
                kwargs.pop("column_order", None)
        try:
            return original_dataframe(data, *args, **kwargs)
        except TypeError:
            # Fallback for old/corrupt persisted column order settings.
            kwargs.pop("column_order", None)
            return original_dataframe(data, *args, **kwargs)

    def data_editor_wrapper(data=None, *args, **kwargs):
        _inject_native_header_sort_style()
        df = _normalize_df(data)
        if df is not None and len(df.columns) > 0:
            key = kwargs.get("key")
            table_id = _stable_table_id(df, key=key, kind="data_editor")
            # V2.92：如果 data_editor 只是鎖定檢視，改用 st.dataframe 顯示，保留原標題列左鍵排序。
            if _v292_is_fully_locked_editor(kwargs):
                table_setting, _ = _settings_editor(table_id, df, editable=False)
                # V2.93：V2.92 這裡誤呼叫不存在的 _apply_settings_to_df，
                # 造成 03/04 等頁面在 st.form 內直接中斷，進而觸發 Missing Submit Button。
                # 不改資料本體，排序/顯示順序交給 dataframe 的 column_order 與 column_config 處理。
                readonly_df = df.copy()
                cfg = {**_build_column_config(df, table_setting), **kwargs.get("column_config", {})}
                local_kwargs = dict(kwargs)
                local_kwargs["column_config"] = cfg
                if "column_order" not in local_kwargs:
                    order = _visible_order(df, table_setting, editable=False)
                    if order:
                        local_kwargs["column_order"] = order
                return _v292_locked_editor_as_sortable_dataframe(original_dataframe, readonly_df, *args, **local_kwargs)
            table_setting, _ = _settings_editor(table_id, df, editable=True)
            # V1.73：不在全域 wrapper 內再產生「啟動/停止編輯」按鈕。
            # 各頁若已有自己的編輯保護按鈕，保留各頁原本的一組；避免重複顯示與 st.form 內 st.button 錯誤。
            kwargs.setdefault("use_container_width", True)
            kwargs.setdefault("key", f"spt_data_editor::{_safe_widget_suffix(table_id)}")
            kwargs["column_config"] = {**_build_column_config(df, table_setting), **kwargs.get("column_config", {})}
            raw_order = kwargs.get("column_order") or _visible_order(df, table_setting, editable=True)
            safe_order = _safe_streamlit_column_order(df, raw_order)
            if safe_order:
                kwargs["column_order"] = safe_order
            else:
                kwargs.pop("column_order", None)
            draft_df = _get_editor_draft(table_id, df)
            # V68: synchronize Streamlit's widget delta before rendering without callbacks.  This keeps
            # checkbox/text edits from disappearing when another widget triggers a
            # rerun before the page has copied the returned dataframe into its own
            # session_state draft.
            widget_key = kwargs.get("key")
            try:
                from services.data_editor_state_service import apply_data_editor_widget_state
                if widget_key:
                    draft_df = apply_data_editor_widget_state(draft_df, st.session_state.get(widget_key))
                    _set_editor_draft(table_id, draft_df)
            except Exception:
                pass
            # V69: Never pass a data_editor callback through the global wrapper.
            # Reason: many legacy pages render st.data_editor inside st.form.
            # Streamlit allows callbacks only on st.form_submit_button within a form;
            # passing any on_change to data_editor raises StreamlitInvalidFormCallbackError.
            # The table-draft synchronization is handled by reading widget delta
            # before and after rendering, so removing the callback does not affect
            # cell/checkbox state preservation.
            kwargs.pop("on_change", None)
            try:
                edited = original_data_editor(draft_df, *args, **kwargs)
            except TypeError:
                kwargs.pop("column_order", None)
                edited = original_data_editor(draft_df, *args, **kwargs)
            merged = _merge_hidden_back(draft_df, edited)
            try:
                from services.data_editor_state_service import apply_data_editor_widget_state
                if widget_key:
                    merged = apply_data_editor_widget_state(merged, st.session_state.get(widget_key))
            except Exception:
                pass
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

# ===== V3.52 deep persistence repair for column settings =====
# Root fixes:
# 1) Do not render the global Column Settings panel for tables already rendered by
#    services.table_ui_service.render_table().  Those tables have their own
#    Column Width / Order tool, and showing two tools split the saved settings.
# 2) Column settings are now mirrored into system_settings + spt_module_settings
#    and small GitHub files only when the user actually changes settings.  Loading
#    settings does not write files and does not upload, preventing infinite reruns.

_COLUMN_SETTINGS_SYSTEM_KEY_V352 = "spt_table_column_settings_v2"
_COLUMN_SETTINGS_UPLOAD_TS_V352 = 0.0
_COLUMN_SETTINGS_UPLOAD_INTERVAL_SEC_V352 = 6.0

# More permanent mirrors. Keep old paths for backward compatibility.
COLUMN_SETTINGS_MIRROR_PATHS = list(dict.fromkeys([
    SETTINGS_PATH,
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_column_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_table_column_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_column_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_table_column_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_settings.json",
    PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
]))


def _v352_direct_db_path() -> Path:
    return PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"


def _v352_settings_from_system_settings_rows(rows: Any) -> Dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("setting_key") or "") != _COLUMN_SETTINGS_SYSTEM_KEY_V352:
            continue
        raw = row.get("setting_value")
        try:
            parsed = json.loads(str(raw or "{}"))
            return _normalize_loaded_settings(parsed)
        except Exception:
            return {}
    return {}


def _normalize_loaded_settings(data: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
    """V3.52: read all supported JSON shapes, including system_settings mirrors."""
    if not isinstance(data, dict):
        return {}
    candidates: list[Dict[str, Any]] = []
    if isinstance(data.get("table_column_settings_v2"), dict):
        candidates.append(dict(data.get("table_column_settings_v2") or {}))
    if isinstance(data.get("settings"), dict) and isinstance(data["settings"].get("table_column_settings_v2"), dict):
        candidates.append(dict(data["settings"].get("table_column_settings_v2") or {}))
    tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
    if isinstance(tables, dict):
        if isinstance(tables.get("table_column_settings_v2"), dict):
            candidates.append(dict(tables.get("table_column_settings_v2") or {}))
        sys_rows = tables.get("system_settings")
        sys_settings = _v352_settings_from_system_settings_rows(sys_rows)
        if sys_settings:
            candidates.append(sys_settings)
    # direct legacy format: {table_id:{columns:{...}}}
    legacy = {k: v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("columns"), dict)}
    if legacy:
        candidates.append(legacy)

    base: Dict[str, Any] = {}
    for cand in candidates:
        for k, v in cand.items():
            if isinstance(v, dict) and isinstance(v.get("columns"), dict):
                base.setdefault(str(k), v)
    for k, v in list(base.items()):
        ck = _canonical_table_id(k)
        if ck and ck not in base and isinstance(v, dict):
            base[ck] = v
    return base


def _v352_load_db_system_settings() -> Dict[str, Any]:
    """Read column settings mirrored in SQLite system_settings without triggering guards."""
    db_path = _v352_direct_db_path()
    if not db_path.exists():
        return {}
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT setting_value FROM system_settings WHERE setting_key=?",
                (_COLUMN_SETTINGS_SYSTEM_KEY_V352,),
            ).fetchone()
            if not row:
                return {}
            parsed = json.loads(str(row[0] or "{}"))
            return _normalize_loaded_settings(parsed)
        finally:
            conn.close()
    except Exception:
        return {}


def load_settings() -> Dict[str, Any]:  # type: ignore[override]
    """V3.52: load from local JSON + restored module settings + SQLite mirror.

    Load is read-only. It never writes JSON and never uploads to GitHub.
    """
    _ensure_state_dir()
    merged: Dict[str, Any] = {}
    # DB mirror is usually restored from spt_module_settings after Reboot App.
    for k, v in _v352_load_db_system_settings().items():
        merged.setdefault(k, v)
    for path in COLUMN_SETTINGS_MIRROR_PATHS:
        data = _normalize_loaded_settings(_read_json_file(path))
        for k, v in data.items():
            merged.setdefault(k, v)
    return merged


def _v352_write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v352_write_system_settings_json(settings: Dict[str, Any]) -> None:
    """Mirror full column settings into system_settings and table_column_settings.

    Direct sqlite writes avoid db_service._after_write loops; we call GitHub upload below
    only once, and only after a real user setting change.
    """
    db_path = _v352_direct_db_path()
    try:
        import sqlite3
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS system_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT, note TEXT, updated_at TEXT)"
            )
            conn.execute(
                """
                INSERT INTO system_settings(setting_key, setting_value, note, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (
                    _COLUMN_SETTINGS_SYSTEM_KEY_V352,
                    json.dumps({"table_column_settings_v2": settings}, ensure_ascii=False, default=str),
                    "全系統表格欄位設定 JSON mirror；供 Reboot App 後還原。",
                    now,
                ),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS table_column_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_key TEXT,
                    table_key TEXT,
                    column_key TEXT,
                    column_width INTEGER,
                    sort_order INTEGER,
                    updated_at TEXT,
                    UNIQUE(page_key, table_key, column_key)
                )
                """
            )
            width_map = {"small": 90, "medium": 150, "large": 230}
            for table_id, table_setting in settings.items():
                if not isinstance(table_setting, dict):
                    continue
                cols = table_setting.get("columns") if isinstance(table_setting.get("columns"), dict) else {}
                for col_key, meta in cols.items():
                    if not isinstance(meta, dict):
                        continue
                    try:
                        sort_order = int(meta.get("order", 999))
                    except Exception:
                        sort_order = 999
                    width_val = width_map.get(str(meta.get("width") or "medium"), 150)
                    conn.execute(
                        """
                        INSERT INTO table_column_settings(page_key, table_key, column_key, column_width, sort_order, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(page_key, table_key, column_key) DO UPDATE SET
                            column_width=excluded.column_width,
                            sort_order=excluded.sort_order,
                            updated_at=excluded.updated_at
                        """,
                        ("column_settings_v2", str(table_id), str(col_key), int(width_val), int(sort_order), now),
                    )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _v352_write_module_settings_mirrors(settings: Dict[str, Any]) -> None:
    payload = {
        "version": "V3.52",
        "description": "全系統表格欄位設定永久鏡像；10/13/01 Reboot App 後還原用。",
        "table_column_settings_v2": settings,
        "table_count": len(settings),
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    for path in COLUMN_SETTINGS_MIRROR_PATHS:
        try:
            if path.name == "spt_module_settings.json" or path.name.endswith("_settings.json"):
                existing = _read_json_file(path)
                if not isinstance(existing, dict):
                    existing = {}
                existing.setdefault("version", "V3.52")
                existing["exported_at"] = payload["exported_at"]
                existing["table_column_settings_v2"] = settings
                tables = existing.get("tables") if isinstance(existing.get("tables"), dict) else {}
                tables["table_column_settings_v2"] = settings
                sys_rows = [r for r in (tables.get("system_settings") if isinstance(tables.get("system_settings"), list) else []) if isinstance(r, dict) and str(r.get("setting_key") or "") != _COLUMN_SETTINGS_SYSTEM_KEY_V352]
                sys_rows.append({
                    "setting_key": _COLUMN_SETTINGS_SYSTEM_KEY_V352,
                    "setting_value": json.dumps({"table_column_settings_v2": settings}, ensure_ascii=False, default=str),
                    "note": "全系統表格欄位設定 JSON mirror；供 Reboot App 後還原。",
                    "updated_at": payload["exported_at"],
                })
                tables["system_settings"] = sys_rows
                existing["tables"] = tables
                counts = existing.get("table_counts") if isinstance(existing.get("table_counts"), dict) else {}
                counts["system_settings"] = len(sys_rows)
                counts["table_column_settings_v2"] = len(settings)
                existing["table_counts"] = counts
                _v352_write_json_atomic(path, existing)
            else:
                _v352_write_json_atomic(path, payload)
        except Exception:
            pass


def _v352_upload_column_settings_files() -> None:
    """Upload only small settings files; never called from load/restore."""
    global _COLUMN_SETTINGS_UPLOAD_TS_V352
    try:
        now_ts = time.time()
        if now_ts - float(_COLUMN_SETTINGS_UPLOAD_TS_V352 or 0) < _COLUMN_SETTINGS_UPLOAD_INTERVAL_SEC_V352:
            return
        from services.github_cloud_storage_service import github_config, upload_file_to_github
        if not github_config().get("token"):
            return
        files = [
            (SETTINGS_PATH, "data/permanent_store/persistent_state/spt_table_column_settings.json"),
            (PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json", "data/permanent_store/persistent_state/spt_module_settings.json"),
            (PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_column_settings.json", "data/permanent_store/persistent_modules/ui_table_settings/table_column_settings.json"),
            (PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_table_column_settings.json", "data/permanent_store/persistent_modules/01_time_records/01_time_records_table_column_settings.json"),
            (PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_table_column_settings.json", "data/permanent_store/persistent_modules/10_permissions/10_permissions_table_column_settings.json"),
            (PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_column_settings.json", "data/permanent_store/persistent_modules/13_system_settings/13_system_settings_table_column_settings.json"),
        ]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for local, remote in files:
            if local.exists():
                upload_file_to_github(local, remote, f"SPT column settings V352 {stamp}")
        _COLUMN_SETTINGS_UPLOAD_TS_V352 = now_ts
    except Exception:
        pass


def save_settings(settings: Dict[str, Any], *, upload: bool = True) -> None:  # type: ignore[override]
    _ensure_state_dir()
    normalized = dict(settings or {})
    for k, v in list(normalized.items()):
        ck = _canonical_table_id(k)
        if ck and ck not in normalized and isinstance(v, dict):
            normalized[ck] = v
    # No-op if content is unchanged; avoids rerun loops.
    try:
        current = load_settings()
        if current == normalized:
            return
    except Exception:
        pass
    _v352_write_json_atomic(SETTINGS_PATH, normalized)
    _v352_write_module_settings_mirrors(normalized)
    _v352_write_system_settings_json(normalized)
    if upload:
        _v352_upload_column_settings_files()


def _get_table_setting(table_id: str, columns: Iterable[str]) -> Dict[str, Any]:  # type: ignore[override]
    """V3.52: do not persist default settings just by opening a page."""
    all_settings = load_settings()
    table_setting = all_settings.get(table_id) or all_settings.get(_canonical_table_id(table_id)) or {}
    if not isinstance(table_setting, dict):
        table_setting = {}
    col_settings = dict(table_setting.get("columns", {}) if isinstance(table_setting.get("columns", {}), dict) else {})
    for idx, col in enumerate(columns):
        c = str(col)
        if c not in col_settings:
            meta = _default_column_setting(c)
            meta["order"] = idx
            col_settings[c] = meta
    out = dict(table_setting)
    out["columns"] = col_settings
    return out


def _save_table_setting(table_id: str, table_setting: Dict[str, Any]) -> None:  # type: ignore[override]
    all_settings = load_settings()
    all_settings[table_id] = table_setting
    ck = _canonical_table_id(table_id)
    if ck and ck != table_id:
        all_settings[ck] = table_setting
    save_settings(all_settings, upload=True)


def _v352_called_from_table_ui_service() -> bool:
    try:
        for frame in inspect.stack():
            filename = str(frame.filename).replace("\\", "/")
            if filename.endswith("/services/table_ui_service.py") or filename.endswith("services/table_ui_service.py"):
                return True
    except Exception:
        pass
    return False


def _settings_editor(table_id: str, df: pd.DataFrame, editable: bool) -> Tuple[Dict[str, Any], bool]:  # type: ignore[override]
    """V3.52: skip duplicate global settings for render_table() tables.

    The render_table path already shows Column Width / Column Order via
    table_ui_service.  Rendering this global panel too creates two independent
    settings stores for the same visual table.  Direct st.data_editor tables such
    as 10｜權限管理 remain covered by this global editor.
    """
    table_setting = _get_table_setting(table_id, [str(c) for c in df.columns])
    if _v352_called_from_table_ui_service():
        return table_setting, False

    col_settings = table_setting.get("columns", {})
    with st.expander("欄位設定 / Column Settings（永久保存）", expanded=False):
        st.caption(
            "可設定每個表格欄位的顯示、順序、欄寬與標題。修改後會自動保存到永久設定；"
            "若已設定 GitHub Token，會同步保存到 GitHub，避免 Reboot App 後恢復預設。"
        )
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
            "欄位順序 / Column order（每行一個欄位；可剪下貼上調整順序，會自動永久保存）",
            value="\n".join(current_order),
            key=f"column_order_text::{_safe_widget_suffix(table_id)}",
            height=420,
            help="每行一個欄位名稱。",
        )
        st.caption(f"表格ID：{table_id}")

    new_cols = {}
    try:
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
        new_cols = dict(col_settings)

    applied = False
    if new_cols and new_cols != table_setting.get("columns", {}):
        table_setting["columns"] = new_cols
        _save_table_setting(table_id, table_setting)
        applied = True
    if applied:
        table_setting = _get_table_setting(table_id, [str(c) for c in df.columns])
    return table_setting, applied

# ===== V3.60 unified column settings persistence core =====
# 01 使用 table_ui_service，不再重複套用全域欄位設定；10/13 直接 st.data_editor/st.dataframe 仍由本服務處理。
# 所有設定統一保存到 V360 master JSON，並同步舊格式鏡像；載入不寫檔、不掃 history、不自動上傳 GitHub。

def _canonical_table_id(table_id: str) -> str:  # type: ignore[override]
    try:
        from services.table_persistence_service import canonical_table_key
        return canonical_table_key(table_id)
    except Exception:
        raw = str(table_id or "")
        raw = re.sub(r"v171_account_password_editor_\d+", "v171_account_password_editor", raw)
        raw = re.sub(r"v189_permission_editor_\d+", "v189_permission_editor", raw)
        return raw


def _stable_table_id(df: pd.DataFrame, key: Any = None, kind: str = "table") -> str:  # type: ignore[override]
    try:
        from services.table_persistence_service import canonical_table_key
        if key:
            return canonical_table_key(str(key), kind=kind)
        page = _current_page_name()
        callsite = _callsite_signature()
        cols = "|".join([str(c) for c in df.columns])[:180]
        return canonical_table_key(f"{page}::{callsite}::{kind}::{abs(hash(cols))}", kind=kind)
    except Exception:
        if key:
            return str(key)
        return f"{_current_page_name()}::{kind}"


def load_settings() -> Dict[str, Any]:  # type: ignore[override]
    try:
        from services.table_persistence_service import load_column_settings, migrate_legacy_table_settings_to_master
        migrate_legacy_table_settings_to_master(write=True)
        data = load_column_settings()
        return dict(data or {})
    except Exception:
        return {}


def save_settings(settings: Dict[str, Any], *, upload: bool = False) -> None:  # type: ignore[override]
    try:
        from services.table_persistence_service import save_column_settings
        normalized: Dict[str, Any] = {}
        for k, v in dict(settings or {}).items():
            ck = _canonical_table_id(str(k))
            if isinstance(v, dict):
                normalized[ck] = v
        current = load_settings()
        if current == normalized:
            return
        save_column_settings(normalized, reason="v360_column_settings_saved")
    except Exception:
        # Last-resort local write, no GitHub/no history.
        try:
            _ensure_state_dir()
            normalized = {(_canonical_table_id(k)): v for k, v in dict(settings or {}).items() if isinstance(v, dict)}
            tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
            tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            json.loads(tmp.read_text(encoding="utf-8"))
            tmp.replace(SETTINGS_PATH)
        except Exception:
            pass


def _get_table_setting(table_id: str, columns: Iterable[str]) -> Dict[str, Any]:  # type: ignore[override]
    stable_id = _canonical_table_id(table_id)
    all_settings = load_settings()
    table_setting = all_settings.get(stable_id) or all_settings.get(table_id) or {}
    if not isinstance(table_setting, dict):
        table_setting = {}
    col_settings = dict(table_setting.get("columns", {}) if isinstance(table_setting.get("columns", {}), dict) else {})
    for idx, col in enumerate(columns):
        c = str(col)
        if c not in col_settings:
            meta = _default_column_setting(c)
            meta["order"] = idx
            col_settings[c] = meta
    # 10 帳號清單：刪除欄位必須永遠可見且排第一，避免再次消失。
    if stable_id == "10.permissions.account_master":
        for delete_col in ["刪除 / Delete", "delete", "刪除"]:
            if delete_col in col_settings:
                col_settings[delete_col]["visible"] = True
                col_settings[delete_col]["order"] = -999
    out = dict(table_setting)
    out["columns"] = col_settings
    return out


def _save_table_setting(table_id: str, table_setting: Dict[str, Any]) -> None:  # type: ignore[override]
    stable_id = _canonical_table_id(table_id)
    all_settings = load_settings()
    all_settings[stable_id] = table_setting
    save_settings(all_settings, upload=False)


def _visible_order(df: pd.DataFrame, table_setting: Dict[str, Any], editable: bool) -> List[str]:  # type: ignore[override]
    col_settings = table_setting.get("columns", {}) if isinstance(table_setting.get("columns"), dict) else {}
    rows = []
    source_cols = [str(c) for c in df.columns]
    for idx, col in enumerate(df.columns):
        key = str(col)
        meta = col_settings.get(key, _default_column_setting(key))
        visible = bool(meta.get("visible", True))
        # 任何刪除欄位都強制保留，避免帳號刪除方框消失。
        if key in {"刪除 / Delete", "刪除", "delete"}:
            visible = True
            order = -999
        else:
            try:
                order = int(meta.get("order", idx))
            except Exception:
                order = idx
        rows.append((order, key, visible))
    rows.sort(key=lambda x: (x[0], x[1]))
    visible_cols = [key for _, key, visible in rows if visible and key in source_cols]
    if not visible_cols:
        visible_cols = source_cols
    lookup = {str(c): c for c in df.columns}
    return [lookup[c] for c in visible_cols if c in lookup]


def _settings_editor(table_id: str, df: pd.DataFrame, editable: bool) -> Tuple[Dict[str, Any], bool]:  # type: ignore[override]
    """V360: stable-key settings editor; skip duplicate UI for table_ui_service.render_table()."""
    stable_id = _canonical_table_id(table_id)
    table_setting = _get_table_setting(stable_id, [str(c) for c in df.columns])
    if _v352_called_from_table_ui_service():
        return table_setting, False

    col_settings = table_setting.get("columns", {})
    with st.expander("欄位設定 / Column Settings（永久保存）", expanded=False):
        st.caption("V360：欄位顯示、順序、欄寬與標題統一保存到唯一永久設定主檔；Reboot App 後會先讀永久設定，不再讀回預設。")
        rows = []
        for idx, col in enumerate(df.columns):
            key = str(col)
            meta = col_settings.get(key, _default_column_setting(key))
            rows.append({
                "顯示 / Visible": True if key in {"刪除 / Delete", "刪除", "delete"} else bool(meta.get("visible", True)),
                "欄位 / Column": key,
                "標題 / Header": meta.get("label") or COLUMN_LABELS.get(key, f"{key} / {key}"),
                "順序 / Order": -999 if key in {"刪除 / Delete", "刪除", "delete"} else int(meta.get("order", idx)),
                "欄寬 / Width": meta.get("width", "medium"),
            })
        cfg_df = pd.DataFrame(rows)
        _editor_func = _ORIGINAL_DATA_EDITOR or st.data_editor
        edited_cfg = _editor_func(
            cfg_df,
            key=f"column_setting_editor::{_safe_widget_suffix(stable_id)}",
            use_container_width=True,
            hide_index=True,
            height=360,
            num_rows="fixed",
            column_config={
                "顯示 / Visible": st.column_config.CheckboxColumn("顯示 / Visible"),
                "欄位 / Column": st.column_config.TextColumn("欄位 / Column", disabled=True),
                "標題 / Header": st.column_config.TextColumn("標題 / Header"),
                "順序 / Order": st.column_config.NumberColumn("順序 / Order", min_value=-999, step=1),
                "欄寬 / Width": st.column_config.SelectboxColumn("欄寬 / Width", options=list(WIDTH_OPTIONS.values())),
            },
        )
        st.markdown("#### 欄位順序快速設定 / Column Order")
        current_order = sorted(
            [str(c) for c in df.columns],
            key=lambda x: int(col_settings.get(x, _default_column_setting(x)).get("order", 999)),
        )
        # 刪除欄永遠放第一。
        delete_first = [x for x in current_order if x in {"刪除 / Delete", "刪除", "delete"}]
        rest = [x for x in current_order if x not in set(delete_first)]
        current_order = delete_first + rest
        order_text = st.text_area(
            "欄位順序 / Column order（每行一個欄位；可剪下貼上調整順序，會自動永久保存）",
            value="\n".join(current_order),
            key=f"column_order_text::{_safe_widget_suffix(stable_id)}",
            height=420,
            help="每行一個欄位名稱。",
        )
        st.caption(f"表格ID：{stable_id}")

    new_cols = {}
    try:
        for _, row in edited_cfg.iterrows():
            key = str(row.get("欄位 / Column", "")).strip()
            if not key:
                continue
            visible = bool(row.get("顯示 / Visible", True))
            order_val = int(row.get("順序 / Order", 999))
            if key in {"刪除 / Delete", "刪除", "delete"}:
                visible = True
                order_val = -999
            new_cols[key] = {
                "source": key,
                "label": str(row.get("標題 / Header") or key),
                "visible": visible,
                "width": str(row.get("欄寬 / Width") or "medium"),
                "order": order_val,
            }
        text_order = [x.strip() for x in str(order_text).splitlines() if x.strip()]
        used = set()
        order_no = 0
        for key in text_order:
            if key in new_cols and key not in used:
                if key in {"刪除 / Delete", "刪除", "delete"}:
                    new_cols[key]["order"] = -999
                    new_cols[key]["visible"] = True
                else:
                    new_cols[key]["order"] = order_no
                    order_no += 1
                used.add(key)
        for key in new_cols:
            if key not in used:
                if key in {"刪除 / Delete", "刪除", "delete"}:
                    new_cols[key]["order"] = -999
                    new_cols[key]["visible"] = True
                else:
                    new_cols[key]["order"] = order_no
                    order_no += 1
    except Exception:
        new_cols = dict(col_settings)

    applied = False
    if new_cols and new_cols != table_setting.get("columns", {}):
        table_setting["columns"] = new_cols
        _save_table_setting(stable_id, table_setting)
        applied = True
    if applied:
        table_setting = _get_table_setting(stable_id, [str(c) for c in df.columns])
    return table_setting, applied


# ===== V3.67 performance safe mode =====
# 全域表格 wrapper 每個模組都會經過；這裡嚴禁 history 掃描、migrate(write=True)、GitHub、mark_data_changed。
_V367_COLUMN_SETTINGS_CACHE = {"sig": None, "data": None}

def _v367_column_file_sig() -> tuple:
    paths = [SETTINGS_PATH, *COLUMN_SETTINGS_MIRROR_PATHS]
    out = []
    for path in paths:
        try:
            if path.exists():
                st = path.stat()
                out.append((str(path), int(st.st_mtime_ns), int(st.st_size)))
            else:
                out.append((str(path), 0, 0))
        except Exception:
            out.append((str(path), -1, -1))
    return tuple(out)

def _callsite_signature() -> str:  # type: ignore[override]
    # V367: inspect.stack() 很重；改用 sys._getframe 輕量回溯。
    try:
        import sys
        frame = sys._getframe(1)
        depth = 0
        while frame is not None and depth < 18:
            filename = str(frame.f_code.co_filename).replace("\\", "/")
            if "/site-packages/" not in filename and not filename.endswith("column_settings_service.py") and not filename.endswith("table_ui_service.py"):
                if "/pages/" in filename or filename.endswith("streamlit_app.py"):
                    return f"{Path(filename).stem}:{frame.f_lineno}"
            frame = frame.f_back
            depth += 1
    except Exception:
        pass
    return "unknown_callsite"

def load_settings() -> Dict[str, Any]:  # type: ignore[override]
    _ensure_state_dir()
    sig = _v367_column_file_sig()
    try:
        if _V367_COLUMN_SETTINGS_CACHE.get("sig") == sig and isinstance(_V367_COLUMN_SETTINGS_CACHE.get("data"), dict):
            return dict(_V367_COLUMN_SETTINGS_CACHE["data"])
    except Exception:
        pass
    merged: Dict[str, Any] = {}
    # 直接讀固定檔，不 migrate、不掃 history。
    for path in COLUMN_SETTINGS_MIRROR_PATHS:
        data = _normalize_loaded_settings(_read_json_file(path))
        for k, v in data.items():
            merged.setdefault(_canonical_table_id(k), v)
    try:
        from services.table_persistence_service import load_column_settings
        direct = load_column_settings()
        for k, v in dict(direct or {}).items():
            if isinstance(v, dict):
                merged[_canonical_table_id(k)] = v
    except Exception:
        pass
    try:
        _V367_COLUMN_SETTINGS_CACHE["sig"] = sig
        _V367_COLUMN_SETTINGS_CACHE["data"] = dict(merged)
    except Exception:
        pass
    return merged

def save_settings(settings: Dict[str, Any], *, upload: bool = False) -> None:  # type: ignore[override]
    try:
        normalized: Dict[str, Any] = {}
        for k, v in dict(settings or {}).items():
            ck = _canonical_table_id(str(k))
            if isinstance(v, dict):
                normalized[ck] = v
        current = load_settings()
        # 只比對本次涉及的設定，避免其他 mirror 裡的設定造成每次都重寫。
        same = True
        for k, v in normalized.items():
            if current.get(k) != v:
                same = False
                break
        if same and len(normalized) == len(current):
            return
        from services.table_persistence_service import save_column_settings
        save_column_settings(normalized, reason="v367_column_settings_saved")
        # 輕量主檔也保存一份，保持舊相容。
        _ensure_state_dir()
        tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(SETTINGS_PATH)
        _V367_COLUMN_SETTINGS_CACHE["sig"] = _v367_column_file_sig()
        _V367_COLUMN_SETTINGS_CACHE["data"] = dict(normalized)
    except Exception:
        try:
            _ensure_state_dir()
            normalized = {(_canonical_table_id(k)): v for k, v in dict(settings or {}).items() if isinstance(v, dict)}
            tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
            tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            json.loads(tmp.read_text(encoding="utf-8"))
            tmp.replace(SETTINGS_PATH)
        except Exception:
            pass
