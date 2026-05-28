# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import re

import json
import time
from pathlib import Path
from typing import Iterable, Any

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
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TABLE_UI_PERSIST_FILES = [
    _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_table_ui_settings.json",
    _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_ui_settings.json",
    _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "12_module_persistence" / "table_ui_settings.json",
]
_TABLE_UI_HISTORY_DIR = _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "history"
_TABLE_UI_RESTORED_ONCE = False


def _now_text() -> str:
    try:
        from services.timezone_service import now_text
        return now_text()
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")


def _stamp_text() -> str:
    try:
        from services.timezone_service import now_stamp
        return now_stamp()
    except Exception:
        return time.strftime("%Y%m%d_%H%M%S")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _table_ui_payload_from_db() -> dict[str, Any]:
    ensure_table_ui_schema()
    try:
        from .db_service import query_df
        df = query_df("SELECT table_key, widths_json, order_json, updated_at FROM table_ui_settings ORDER BY table_key")
        rows = df.fillna("").to_dict(orient="records") if df is not None and not df.empty else []
    except Exception:
        rows = []
    return {
        "version": "V3.43",
        "exported_at": _now_text(),
        "description": "全系統表格欄寬與欄位順序永久設定；避免 Reboot App 後恢復預設寬度/順序。",
        "tables": {"table_ui_settings": rows},
        "table_counts": {"table_ui_settings": len(rows)},
    }


def export_table_ui_settings_permanent(reason: str = "table_ui_settings_changed", write_history: bool = True) -> dict[str, Any]:
    """Persist table_ui_settings outside SQLite so Reboot/App redeploy keeps widths/order."""
    payload = _table_ui_payload_from_db()
    payload["version"] = "V3.49"
    payload["reason"] = reason
    rows = _extract_table_ui_rows_from_payload(payload)
    for path in _TABLE_UI_PERSIST_FILES:
        _atomic_json(path, payload)
    try:
        _write_table_ui_into_module_settings(rows, reason)
    except Exception:
        pass
    if write_history:
        _TABLE_UI_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_json(_TABLE_UI_HISTORY_DIR / f"table_ui_settings_{_stamp_text()}.json", payload)
    try:
        from services.db_service import mark_data_changed
        mark_data_changed("表格欄寬/欄位順序設定已變更，已寫入永久 JSON。", "table_ui_settings")
    except Exception:
        pass
    try:
        _try_upload_table_ui_permanent_files(reason)
    except Exception:
        pass
    return {"ok": True, "files": [str(p) for p in _TABLE_UI_PERSIST_FILES], "count": payload["table_counts"]["table_ui_settings"]}


def _extract_table_ui_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Read table_ui_settings rows from all supported permanent JSON shapes."""
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    rows = tables.get("table_ui_settings") if isinstance(tables, dict) else None
    if rows is None:
        rows = payload.get("table_ui_settings")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and str(r.get("table_key") or "").strip()]


def _table_ui_candidate_paths() -> list[Path]:
    """All places where table UI settings may be preserved.

    V3.49 adds spt_module_settings.json and module-level settings as restore sources.
    This is important on Streamlit Cloud: after Reboot App, direct local JSON files may
    not exist yet, but GitHub restore usually downloads spt_module_settings.json first.
    """
    paths: list[Path] = []
    paths.extend(_TABLE_UI_PERSIST_FILES)
    paths.extend([
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
    ])
    history_roots = [
        _TABLE_UI_HISTORY_DIR,
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "history",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "history",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "history",
    ]
    for root in history_roots:
        if root.exists():
            paths.extend(root.glob("*.json"))
    # de-duplicate while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _best_table_ui_payload() -> dict[str, Any]:
    # Newest among payloads with most *valid* rows wins; prevents empty/default exports
    # from hiding richer settings. Supports both direct table_ui JSON and spt_module_settings.
    best: dict[str, Any] = {}
    best_score = (-1, -1.0)
    for path in _table_ui_candidate_paths():
        if not path.exists():
            continue
        payload = _read_json(path)
        rows = _extract_table_ui_rows_from_payload(payload)
        valid_rows = [r for r in rows if _v349_row_has_real_table_ui(r)] if "_v349_row_has_real_table_ui" in globals() else rows
        if not valid_rows:
            continue
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = 0.0
        score = (len(valid_rows), mtime)
        if score > best_score:
            best = {"tables": {"table_ui_settings": valid_rows}, "source": str(path), "score": score}
            best_score = score
    return best


def _write_table_ui_into_module_settings(rows: list[dict[str, Any]], reason: str) -> None:
    """Mirror table_ui_settings into spt_module_settings.json and module settings.

    This lets the existing GitHub latest-settings restore path bring table settings back
    after Streamlit Reboot App, even when the standalone table UI JSON has not yet been
    downloaded/restored.
    """
    if not rows:
        return
    targets = [
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
    ]
    for path in targets:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("version", "V3.49")
        payload["exported_at"] = _now_text()
        payload["reason"] = reason
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        tables["table_ui_settings"] = rows
        payload["tables"] = tables
        counts = payload.get("table_counts") if isinstance(payload.get("table_counts"), dict) else {}
        counts["table_ui_settings"] = len(rows)
        payload["table_counts"] = counts
        _atomic_json(path, payload)


def _try_upload_table_ui_permanent_files(reason: str) -> None:
    """Best-effort small-file GitHub upload.

    No error is shown to users here; page 09 can still show pending backup. The upload is
    intentionally limited to small settings files to avoid slowing normal page use.
    """
    try:
        from services.github_cloud_storage_service import github_config, upload_file_to_github
        cfg = github_config()
        if not cfg.get("token"):
            return
        stamp = _stamp_text()
        files = [
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_table_ui_settings.json", "data/permanent_store/persistent_state/spt_table_ui_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json", "data/permanent_store/persistent_state/spt_module_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_ui_settings.json", "data/permanent_store/persistent_modules/ui_table_settings/table_ui_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json", "data/permanent_store/persistent_modules/ui_table_settings/ui_table_settings_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json", "data/permanent_store/persistent_modules/01_time_records/01_time_records_settings.json"),
        ]
        for local, remote in files:
            if local.exists():
                upload_file_to_github(local, remote, f"SPT table UI settings {reason} {stamp}")
    except Exception:
        pass


def restore_table_ui_settings_from_permanent(force: bool = False) -> dict[str, Any]:
    """Restore table width/order settings when SQLite was rebuilt by Reboot App."""
    ensure_table_ui_schema()
    payload = _best_table_ui_payload()
    rows = ((payload.get("tables") or {}).get("table_ui_settings") or []) if isinstance(payload, dict) else []
    if not rows:
        return {"ok": False, "restored": 0, "message": "找不到 table_ui_settings 永久檔"}
    try:
        current = query_one("SELECT COUNT(*) AS c FROM table_ui_settings") or {"c": 0}
        current_count = int(current.get("c") or 0)
    except Exception:
        current_count = 0
    if not force and current_count >= len(rows):
        return {"ok": False, "restored": 0, "message": "SQLite 現有欄位設定不比永久檔少，略過還原", "source": payload.get("source")}
    if force:
        try:
            execute("DELETE FROM table_ui_settings")
        except Exception:
            pass
    restored = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        table_key = str(r.get("table_key") or "").strip()
        if not table_key:
            continue
        execute(
            """
            INSERT INTO table_ui_settings(table_key, widths_json, order_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(table_key) DO UPDATE SET
                widths_json=excluded.widths_json,
                order_json=excluded.order_json,
                updated_at=excluded.updated_at
            """,
            (table_key, str(r.get("widths_json") or "{}"), str(r.get("order_json") or "[]"), str(r.get("updated_at") or _now_text())),
        )
        restored += 1
    return {"ok": restored > 0, "restored": restored, "source": payload.get("source"), "score": payload.get("score")}


def label_for(col: str) -> str:
    return COLUMN_LABELS.get(col, f"{col} / {col}")


def ensure_table_ui_schema() -> None:
    global _TABLE_UI_SCHEMA_READY, _TABLE_UI_RESTORED_ONCE
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
    if not _TABLE_UI_RESTORED_ONCE:
        _TABLE_UI_RESTORED_ONCE = True
        try:
            restore_table_ui_settings_from_permanent(force=False)
        except Exception:
            pass


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
    try:
        export_table_ui_settings_permanent("save_widths", write_history=True)
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
    try:
        export_table_ui_settings_permanent("save_column_order", write_history=True)
    except Exception:
        pass


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



def _safe_widget_key_part(value: object) -> str:
    """Return a Streamlit-safe compact key segment."""
    raw = str(value or "")
    raw = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", raw)
    raw = raw.strip("_")
    return raw[:96] or "x"


def _width_settings_instance_key(table_key: str, title: str) -> str:
    """Build a stable unique key for width controls.

    Same table_key can appear more than once on a page.  Streamlit then raises
    DuplicateElementKey if all controls use only table_key.  We include the
    external caller's file and line number, so each table location gets a stable
    unique key without changing saved table settings.
    """
    try:
        stack = inspect.stack()
        # stack: 0 this function, 1 render_width_settings, 2 render_table/direct caller, 3 page caller if render_table.
        frame = stack[3] if len(stack) > 3 else (stack[2] if len(stack) > 2 else None)
        if frame is not None:
            caller = f"{Path(frame.filename).stem}_{frame.lineno}"
        else:
            caller = "unknown"
    except Exception:
        caller = "unknown"
    return _safe_widget_key_part(f"{table_key}_{title}_{caller}")

def render_width_settings(table_key: str, df: pd.DataFrame, title: str = "欄寬設定 / Column Width Settings") -> None:
    """Lazy width editor with collision-free widget keys.

    Width/order settings are still saved by table_key, so existing permanent
    settings are preserved.  Widget keys include a stable instance suffix to avoid
    DuplicateElementKey when the same table_key appears more than once on a page.
    """
    if df is None or df.empty:
        return
    instance_key = _width_settings_instance_key(table_key, title)
    show_key = f"show_widths_{instance_key}"
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
            col_key = _safe_widget_key_part(col)
            default_width = int(widths.get(col, DEFAULT_WIDTHS.get(col, 140)))
            default_order = int(order_index.get(str(col), idx + 1))
            with cols[idx % 4]:
                st.markdown(f"**{label_for(col)}**")
                new_widths[col] = st.number_input(
                    "欄寬",
                    min_value=60,
                    max_value=700,
                    value=default_width,
                    step=10,
                    key=f"width_{instance_key}_{idx}_{col_key}",
                )
                new_orders[col] = st.number_input(
                    "順序",
                    min_value=1,
                    max_value=max(len(df.columns), 1),
                    value=default_order,
                    step=1,
                    key=f"order_{instance_key}_{idx}_{col_key}",
                )
        if st.button("儲存欄位設定 / Save Column Settings", key=f"save_widths_{instance_key}", use_container_width=True):
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


def _apply_quick_header_sort(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """Clickable column-title sort bar.

    Streamlit data_editor does not reliably provide native header sorting in every mode/theme.
    This lightweight bar gives every table the same behavior: click a column title once for ASC,
    click the same title again for DESC.  It is intentionally outside the table so it works for
    both dataframe and editable data_editor without breaking cell editing.
    """
    if df is None or df.empty or len(df.columns) == 0:
        return df
    sort_state_key = f"_spt_quick_sort_{table_key}"
    state = st.session_state.get(sort_state_key, {"column": None, "ascending": True})
    with st.container():
        st.caption("點選欄位標題可快速排序；再次點同一欄會切換升冪/降冪。")
        cols_per_row = 6
        columns = list(df.columns)
        for base in range(0, len(columns), cols_per_row):
            row_cols = st.columns(min(cols_per_row, len(columns) - base))
            for i, col in enumerate(columns[base:base + cols_per_row]):
                active = state.get("column") == col
                arrow = " ▲" if active and state.get("ascending", True) else (" ▼" if active else "")
                label = f"↕ {label_for(col)}{arrow}"
                if row_cols[i].button(label, key=f"quick_sort_{table_key}_{base}_{col}", use_container_width=True):
                    ascending = not bool(state.get("ascending", True)) if active else True
                    st.session_state[sort_state_key] = {"column": col, "ascending": ascending}
                    st.rerun()
    state = st.session_state.get(sort_state_key, {})
    sort_col = state.get("column")
    if sort_col in df.columns:
        try:
            return df.sort_values(sort_col, ascending=bool(state.get("ascending", True)), kind="mergesort", na_position="last").reset_index(drop=True)
        except Exception:
            return df
    return df


def _render_sort_controls(table_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """Add explicit sorting controls because Streamlit table sorting is not always obvious in edit mode."""
    if df is None or df.empty or len(df.columns) == 0:
        return df
    with st.expander("排序設定 / Sort Settings", expanded=False):
        c1, c2, c3 = st.columns([2, 1, 1])
        sort_col = c1.selectbox("排序欄位 / Sort Column", list(df.columns), format_func=label_for, key=f"sort_col_{table_key}")
        ascending = c2.radio("排序方向 / Direction", ["升冪 / ASC", "降冪 / DESC"], horizontal=True, key=f"sort_dir_{table_key}") == "升冪 / ASC"
        apply_sort = c3.checkbox("套用排序 / Apply", value=False, key=f"sort_apply_{table_key}")
        if apply_sort and sort_col in df.columns:
            try:
                return df.sort_values(sort_col, ascending=ascending, kind="mergesort", na_position="last").reset_index(drop=True)
            except Exception:
                st.warning("此欄位暫時無法排序，已維持原順序。")
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
    # V3.47：可編輯表格即使目前沒有資料，也要顯示空白表格讓使用者新增；
    # 唯讀空表才顯示 No data。這會套用到所有既有模組，不新增新畫面功能。
    if df is None:
        st.info("目前沒有資料 / No data")
        return None
    if df.empty and not editable:
        st.info("目前沒有資料 / No data")
        return None
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
    # V3.62：明確把套用後的欄位順序傳給 Streamlit。
    # 只改 dataframe/data_editor 的 column_order 參數，不新增畫面功能。
    # 原因：全域 column_settings_service 會再次包裝 st.dataframe / st.data_editor；
    # 若沒有明確傳入 column_order，外層 wrapper 可能用舊的欄位設定順序蓋掉
    # table_ui_service 已套用的順序，造成「順序設定後標題欄沒變」。
    visual_order = [str(c) for c in display_df.columns]
    if editable:
        return st.data_editor(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config=cfg,
            column_order=visual_order,
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
        column_order=visual_order,
        height=height,
        key=key or f"frame_{table_key}",
    )
    return None

# ===== V3.46 reboot-safe table UI persistence hardening =====
# 目的：所有模組共用的欄寬 / 欄位順序，不再因 Reboot 後 SQLite 已有預設列而略過永久 JSON 還原。
# 不新增畫面功能；只加強既有 table_ui_settings 的保存與還原。

def _v346_row_has_real_table_ui(row: dict[str, Any]) -> bool:
    try:
        w = json.loads(str(row.get("widths_json") or "{}"))
    except Exception:
        w = {}
    try:
        o = json.loads(str(row.get("order_json") or "[]"))
    except Exception:
        o = []
    return bool(isinstance(w, dict) and w) or bool(isinstance(o, list) and o)


def restore_table_ui_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    """V3.46: merge/overwrite useful permanent table UI rows instead of comparing only row count."""
    ensure_table_ui_schema()
    payload = _best_table_ui_payload()
    rows = ((payload.get("tables") or {}).get("table_ui_settings") or []) if isinstance(payload, dict) else []
    rows = [r for r in rows if isinstance(r, dict) and str(r.get("table_key") or "").strip() and _v346_row_has_real_table_ui(r)]
    if not rows:
        return {"ok": False, "restored": 0, "message": "找不到含有效欄寬/欄位順序的 table_ui_settings 永久檔"}
    restored = 0
    skipped = 0
    for r in rows:
        table_key = str(r.get("table_key") or "").strip()
        if not table_key:
            continue
        permanent_widths = str(r.get("widths_json") or "{}")
        permanent_order = str(r.get("order_json") or "[]")
        current = query_one("SELECT widths_json, order_json FROM table_ui_settings WHERE table_key=?", (table_key,)) or {}
        if not force:
            cur_row = {"widths_json": current.get("widths_json") or "{}", "order_json": current.get("order_json") or "[]"}
            if _v346_row_has_real_table_ui(cur_row):
                skipped += 1
                continue
        execute(
            """
            INSERT INTO table_ui_settings(table_key, widths_json, order_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(table_key) DO UPDATE SET
                widths_json=excluded.widths_json,
                order_json=excluded.order_json,
                updated_at=excluded.updated_at
            """,
            (table_key, permanent_widths, permanent_order, str(r.get("updated_at") or _now_text())),
        )
        restored += 1
        try:
            st.session_state.pop(f"_spt_width_cache_{table_key}", None)
        except Exception:
            pass
    return {"ok": restored > 0, "restored": restored, "skipped": skipped, "source": payload.get("source"), "score": payload.get("score")}


_old_render_width_settings_v346 = render_width_settings

def render_width_settings(table_key: str, df: pd.DataFrame, title: str = "欄寬設定 / Column Width Settings") -> None:  # type: ignore[override]
    # 每次進入既有欄位設定工具前，先嘗試從永久 JSON 補回 SQLite。若 SQLite 已有有效設定則不覆蓋。
    try:
        restore_table_ui_settings_from_permanent(force=False)
    except Exception:
        pass
    return _old_render_width_settings_v346(table_key, df, title=title)


_old_apply_column_order_v346 = apply_column_order

def apply_column_order(table_key: str, df: pd.DataFrame) -> pd.DataFrame:  # type: ignore[override]
    try:
        restore_table_ui_settings_from_permanent(force=False)
    except Exception:
        pass
    return _old_apply_column_order_v346(table_key, df)

# ===== V3.46 final no-recursion table UI schema/restore =====
def _v346_ensure_table_ui_schema_basic() -> None:
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


def restore_table_ui_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    _v346_ensure_table_ui_schema_basic()
    payload = _best_table_ui_payload()
    rows = ((payload.get("tables") or {}).get("table_ui_settings") or []) if isinstance(payload, dict) else []
    rows = [r for r in rows if isinstance(r, dict) and str(r.get("table_key") or "").strip() and _v346_row_has_real_table_ui(r)]
    if not rows:
        return {"ok": False, "restored": 0, "message": "找不到含有效欄寬/欄位順序的 table_ui_settings 永久檔"}
    restored = 0
    skipped = 0
    for r in rows:
        table_key = str(r.get("table_key") or "").strip()
        permanent_widths = str(r.get("widths_json") or "{}")
        permanent_order = str(r.get("order_json") or "[]")
        current = query_one("SELECT widths_json, order_json FROM table_ui_settings WHERE table_key=?", (table_key,)) or {}
        cur_row = {"widths_json": current.get("widths_json") or "{}", "order_json": current.get("order_json") or "[]"}
        if not force and _v346_row_has_real_table_ui(cur_row):
            skipped += 1
            continue
        execute(
            """
            INSERT INTO table_ui_settings(table_key, widths_json, order_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(table_key) DO UPDATE SET
                widths_json=excluded.widths_json,
                order_json=excluded.order_json,
                updated_at=excluded.updated_at
            """,
            (table_key, permanent_widths, permanent_order, str(r.get("updated_at") or _now_text())),
        )
        restored += 1
        try:
            st.session_state.pop(f"_spt_width_cache_{table_key}", None)
        except Exception:
            pass
    return {"ok": restored > 0, "restored": restored, "skipped": skipped, "source": payload.get("source"), "score": payload.get("score")}


def ensure_table_ui_schema() -> None:  # type: ignore[override]
    global _TABLE_UI_SCHEMA_READY, _TABLE_UI_RESTORED_ONCE
    if _TABLE_UI_SCHEMA_READY:
        return
    _v346_ensure_table_ui_schema_basic()
    _TABLE_UI_SCHEMA_READY = True
    if not _TABLE_UI_RESTORED_ONCE:
        _TABLE_UI_RESTORED_ONCE = True
        try:
            restore_table_ui_settings_from_permanent(force=False)
        except Exception:
            pass


# ===== V3.49 table UI reboot persistence final guard =====
# 修正 01｜工時紀錄與所有模組：Reboot App 後若 SQLite 已有預設欄位設定，仍必須以永久 JSON 為準還原。
# 不新增畫面功能；只修正保存/還原底層。
def _v349_row_has_real_table_ui(row: dict[str, Any]) -> bool:
    try:
        w = json.loads(str(row.get("widths_json") or "{}"))
    except Exception:
        w = {}
    try:
        o = json.loads(str(row.get("order_json") or "[]"))
    except Exception:
        o = []
    return bool(isinstance(w, dict) and w) or bool(isinstance(o, list) and o)


def restore_table_ui_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    """Always restore useful permanent rows over SQLite defaults.

    Previous logic skipped restore whenever SQLite already had any row. That caused
    Reboot App to keep default/original table settings and ignore the user's saved
    settings. V3.49 makes permanent JSON the source of truth for every saved table_key.
    """
    _v346_ensure_table_ui_schema_basic()
    payload = _best_table_ui_payload()
    rows = ((payload.get("tables") or {}).get("table_ui_settings") or []) if isinstance(payload, dict) else []
    rows = [r for r in rows if isinstance(r, dict) and str(r.get("table_key") or "").strip() and _v349_row_has_real_table_ui(r)]
    if not rows:
        return {"ok": False, "restored": 0, "message": "找不到含有效欄寬/欄位順序的 table_ui_settings 永久檔"}
    restored = 0
    unchanged = 0
    for r in rows:
        table_key = str(r.get("table_key") or "").strip()
        permanent_widths = str(r.get("widths_json") or "{}")
        permanent_order = str(r.get("order_json") or "[]")
        current = query_one("SELECT widths_json, order_json FROM table_ui_settings WHERE table_key=?", (table_key,)) or {}
        cur_widths = str(current.get("widths_json") or "{}")
        cur_order = str(current.get("order_json") or "[]")
        if not force and cur_widths == permanent_widths and cur_order == permanent_order:
            unchanged += 1
            continue
        execute(
            """
            INSERT INTO table_ui_settings(table_key, widths_json, order_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(table_key) DO UPDATE SET
                widths_json=excluded.widths_json,
                order_json=excluded.order_json,
                updated_at=excluded.updated_at
            """,
            (table_key, permanent_widths, permanent_order, str(r.get("updated_at") or _now_text())),
        )
        restored += 1
        try:
            st.session_state.pop(f"_spt_width_cache_{table_key}", None)
        except Exception:
            pass
    return {"ok": restored > 0 or unchanged > 0, "restored": restored, "unchanged": unchanged, "source": payload.get("source"), "score": payload.get("score")}


def ensure_table_ui_schema() -> None:  # type: ignore[override]
    global _TABLE_UI_SCHEMA_READY, _TABLE_UI_RESTORED_ONCE
    if _TABLE_UI_SCHEMA_READY:
        return
    _v346_ensure_table_ui_schema_basic()
    _TABLE_UI_SCHEMA_READY = True
    if not _TABLE_UI_RESTORED_ONCE:
        _TABLE_UI_RESTORED_ONCE = True
        try:
            restore_table_ui_settings_from_permanent(force=False)
        except Exception:
            pass


def load_widths(table_key: str) -> dict[str, int]:  # type: ignore[override]
    ensure_table_ui_schema()
    # V3.49：每次讀 01/所有模組欄寬前都先確保永久設定已蓋回，不被預設 SQLite 擋住。
    try:
        restore_table_ui_settings_from_permanent(force=False)
    except Exception:
        pass
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


def load_column_order(table_key: str) -> list[str]:  # type: ignore[override]
    ensure_table_ui_schema()
    try:
        restore_table_ui_settings_from_permanent(force=False)
    except Exception:
        pass
    row = query_one("SELECT order_json FROM table_ui_settings WHERE table_key=?", (table_key,))
    if not row or not row.get("order_json"):
        return []
    try:
        data = json.loads(row["order_json"])
        return [str(x) for x in data if str(x)] if isinstance(data, list) else []
    except Exception:
        return []

# ===== V3.52 deep persistence repair for table_ui_settings =====
# 10/13/01 all need the same table width/order source after Reboot App.
# Previous mirrors focused on UI + 01, so 13 system-setting tables could be
# missing from module-specific restore paths.  This patch extends mirrors only;
# it does not add any new screen function.


def _table_ui_candidate_paths() -> list[Path]:  # type: ignore[override]
    paths: list[Path] = []
    paths.extend(_TABLE_UI_PERSIST_FILES)
    paths.extend([
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_ui_settings.json",
    ])
    history_roots = [
        _TABLE_UI_HISTORY_DIR,
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "history",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "history",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "history",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "history",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "history",
    ]
    for root in history_roots:
        if root.exists():
            paths.extend(root.glob("*.json"))
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _write_table_ui_into_module_settings(rows: list[dict[str, Any]], reason: str) -> None:  # type: ignore[override]
    if not rows:
        return
    targets = [
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_settings.json",
        _PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_ui_settings.json",
    ]
    for path in targets:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("version", "V3.52")
        payload["exported_at"] = _now_text()
        payload["reason"] = reason
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        tables["table_ui_settings"] = rows
        payload["tables"] = tables
        counts = payload.get("table_counts") if isinstance(payload.get("table_counts"), dict) else {}
        counts["table_ui_settings"] = len(rows)
        payload["table_counts"] = counts
        _atomic_json(path, payload)


def _try_upload_table_ui_permanent_files(reason: str) -> None:  # type: ignore[override]
    try:
        from services.github_cloud_storage_service import github_config, upload_file_to_github
        cfg = github_config()
        if not cfg.get("token"):
            return
        stamp = _stamp_text()
        files = [
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_table_ui_settings.json", "data/permanent_store/persistent_state/spt_table_ui_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_settings.json", "data/permanent_store/persistent_state/spt_module_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_ui_settings.json", "data/permanent_store/persistent_modules/ui_table_settings/table_ui_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json", "data/permanent_store/persistent_modules/ui_table_settings/ui_table_settings_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json", "data/permanent_store/persistent_modules/01_time_records/01_time_records_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json", "data/permanent_store/persistent_modules/10_permissions/10_permissions_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_settings.json", "data/permanent_store/persistent_modules/13_system_settings/13_system_settings_settings.json"),
            (_PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_ui_settings.json", "data/permanent_store/persistent_modules/13_system_settings/13_system_settings_table_ui_settings.json"),
        ]
        for local, remote in files:
            if local.exists():
                upload_file_to_github(local, remote, f"SPT table UI settings V352 {reason} {stamp}")
    except Exception:
        pass

# ===== V3.60 unified table persistence core =====
# 架構級修正：render_table / 欄寬 / 欄位順序統一使用 services.table_persistence_service。
# 載入時只讀本機 JSON，不掃 history、不 GitHub 上傳；使用者修改設定時才寫入唯一主檔與舊格式鏡像。

def _v360_key(table_key: str) -> str:
    try:
        from services.table_persistence_service import canonical_table_key
        return canonical_table_key(table_key)
    except Exception:
        return str(table_key or "")


def restore_table_ui_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    try:
        from services.table_persistence_service import migrate_legacy_table_settings_to_master, load_table_settings
        mig = migrate_legacy_table_settings_to_master(write=True)
        _v346_ensure_table_ui_schema_basic()
        restored = 0
        # 同步 V360 主設定到 SQLite 快取，讓舊查詢/健康檢查仍可看到資料。
        from services.persistence_core_service import load_master_settings
        master = load_master_settings()
        table_settings = master.get("table_settings") if isinstance(master.get("table_settings"), dict) else {}
        if force:
            try:
                execute("DELETE FROM table_ui_settings")
            except Exception:
                pass
        for raw_key in table_settings.keys():
            key = _v360_key(raw_key)
            data = load_table_settings(key)
            widths = data.get("widths", {}) if isinstance(data, dict) else {}
            order = data.get("order", []) if isinstance(data, dict) else []
            if not widths and not order:
                continue
            execute(
                """
                INSERT INTO table_ui_settings(table_key, widths_json, order_json, updated_at)
                VALUES (?, ?, ?, datetime('now','localtime'))
                ON CONFLICT(table_key) DO UPDATE SET
                    widths_json=excluded.widths_json,
                    order_json=excluded.order_json,
                    updated_at=excluded.updated_at
                """,
                (key, json.dumps(widths, ensure_ascii=False), json.dumps(order, ensure_ascii=False)),
            )
            try:
                st.session_state.pop(f"_spt_width_cache_{key}", None)
            except Exception:
                pass
            restored += 1
        return {"ok": True, "mode": "v360_unified", "restored": restored, "migration": mig}
    except Exception as exc:
        return {"ok": False, "mode": "v360_unified", "error": str(exc)}


def ensure_table_ui_schema() -> None:  # type: ignore[override]
    global _TABLE_UI_SCHEMA_READY, _TABLE_UI_RESTORED_ONCE
    if _TABLE_UI_SCHEMA_READY:
        return
    _v346_ensure_table_ui_schema_basic()
    _TABLE_UI_SCHEMA_READY = True
    if not _TABLE_UI_RESTORED_ONCE:
        _TABLE_UI_RESTORED_ONCE = True
        try:
            restore_table_ui_settings_from_permanent(force=False)
        except Exception:
            pass


def load_widths(table_key: str) -> dict[str, int]:  # type: ignore[override]
    ensure_table_ui_schema()
    key = _v360_key(table_key)
    try:
        from services.table_persistence_service import load_table_settings
        return dict(load_table_settings(key).get("widths", {}) or {})
    except Exception:
        row = query_one("SELECT widths_json FROM table_ui_settings WHERE table_key=?", (key,))
        try:
            return json.loads(row.get("widths_json") or "{}") if row else {}
        except Exception:
            return {}


def save_widths(table_key: str, widths: dict[str, int]) -> None:  # type: ignore[override]
    ensure_table_ui_schema()
    key = _v360_key(table_key)
    try:
        from services.table_persistence_service import save_table_settings
        save_table_settings(key, widths=widths, reason="v360_save_widths")
    except Exception:
        pass
    # SQLite 僅作快取/相容。
    try:
        execute(
            """
            INSERT INTO table_ui_settings(table_key, widths_json, updated_at)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(table_key) DO UPDATE SET widths_json=excluded.widths_json, updated_at=excluded.updated_at
            """,
            (key, json.dumps(widths or {}, ensure_ascii=False)),
        )
    except Exception:
        pass


def load_column_order(table_key: str) -> list[str]:  # type: ignore[override]
    ensure_table_ui_schema()
    key = _v360_key(table_key)
    try:
        from services.table_persistence_service import load_table_settings
        data = load_table_settings(key).get("order", [])
        return [str(x) for x in data if str(x)] if isinstance(data, list) else []
    except Exception:
        row = query_one("SELECT order_json FROM table_ui_settings WHERE table_key=?", (key,))
        try:
            data = json.loads(row.get("order_json") or "[]") if row else []
            return [str(x) for x in data if str(x)] if isinstance(data, list) else []
        except Exception:
            return []


def save_column_order(table_key: str, order: Iterable[str]) -> None:  # type: ignore[override]
    ensure_table_ui_schema()
    key = _v360_key(table_key)
    cols = [str(c) for c in order if str(c)]
    try:
        from services.table_persistence_service import save_table_settings
        save_table_settings(key, order=cols, reason="v360_save_column_order")
    except Exception:
        pass
    try:
        execute(
            """
            INSERT INTO table_ui_settings(table_key, order_json, updated_at)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(table_key) DO UPDATE SET order_json=excluded.order_json, updated_at=excluded.updated_at
            """,
            (key, json.dumps(cols, ensure_ascii=False)),
        )
    except Exception:
        pass


def apply_column_order(table_key: str, df: pd.DataFrame) -> pd.DataFrame:  # type: ignore[override]
    if df is None or df.empty:
        return df
    key = _v360_key(table_key)
    order = load_column_order(key)
    if not order:
        return df
    ordered = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in ordered]
    return df[ordered + rest] if ordered else df


def export_table_ui_settings_permanent(reason: str = "table_ui_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    try:
        from services.table_persistence_service import mirror_legacy_table_ui_settings, migrate_legacy_table_settings_to_master
        mig = migrate_legacy_table_settings_to_master(write=True)
        mirror_legacy_table_ui_settings()
        return {"ok": True, "mode": "v360_unified", "reason": reason, "migration": mig}
    except Exception as exc:
        return {"ok": False, "mode": "v360_unified", "error": str(exc), "reason": reason}


# ===== V3.67 performance safe mode =====
# 每頁進入時不做 migration/write；只在使用者按儲存欄位設定時寫入。

def restore_table_ui_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    try:
        _v346_ensure_table_ui_schema_basic()
        return {"ok": True, "mode": "v367_no_auto_restore_write", "restored": 0, "force": force}
    except Exception as exc:
        return {"ok": False, "mode": "v367_no_auto_restore_write", "error": str(exc)}

def ensure_table_ui_schema() -> None:  # type: ignore[override]
    global _TABLE_UI_SCHEMA_READY, _TABLE_UI_RESTORED_ONCE
    if _TABLE_UI_SCHEMA_READY:
        return
    _v346_ensure_table_ui_schema_basic()
    _TABLE_UI_SCHEMA_READY = True
    _TABLE_UI_RESTORED_ONCE = True

def export_table_ui_settings_permanent(reason: str = "table_ui_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    # V367: 此函式可能被頁面當作「確保永久設定」呼叫；避免在進頁時寫多個 mirror。
    return {"ok": True, "mode": "v367_direct_persistence_no_export_needed", "reason": reason}


# ===== V3.69 definitive table width save/apply repair =====
# 修正重點：欄寬設定 / Column Width Settings 按下「儲存欄位設定」後，
# 必須立即套用到目前表格，並永久寫入唯一主設定與 SQLite 相容快取。
# 不新增畫面、不改業務資料，只覆蓋欄寬/欄位順序讀寫核心。

def _v369_key_candidates(table_key: str) -> list[str]:
    raw = str(table_key or "").strip()
    keys: list[str] = []
    try:
        ck = _v360_key(raw)
        if ck:
            keys.append(str(ck))
    except Exception:
        pass
    if raw and raw not in keys:
        keys.append(raw)
    return keys or ["unknown.table"]


def _v369_normalize_widths(widths: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(widths, dict):
        return out
    for k, v in widths.items():
        try:
            iv = int(float(v))
            if iv > 0:
                out[str(k)] = max(60, min(700, iv))
        except Exception:
            pass
    return out


def _v369_normalize_order(order: Any) -> list[str]:
    if isinstance(order, str):
        try:
            parsed = json.loads(order)
            order = parsed if isinstance(parsed, list) else [x.strip() for x in order.splitlines() if x.strip()]
        except Exception:
            order = [x.strip() for x in order.splitlines() if x.strip()]
    try:
        values = list(order or [])
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        s = str(item).strip()
        if s and s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _v369_load_table_settings_direct(key: str) -> dict[str, Any]:
    try:
        from services.table_persistence_service import load_table_settings
        data = load_table_settings(key)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _v369_sqlite_get(table_key: str) -> dict[str, Any]:
    try:
        row = query_one("SELECT widths_json, order_json FROM table_ui_settings WHERE table_key=?", (table_key,)) or {}
        widths = json.loads(row.get("widths_json") or "{}") if row else {}
        order = json.loads(row.get("order_json") or "[]") if row else []
        return {"widths": _v369_normalize_widths(widths), "order": _v369_normalize_order(order)}
    except Exception:
        return {"widths": {}, "order": []}


def _v369_sqlite_put(table_key: str, *, widths: dict[str, int] | None = None, order: list[str] | None = None) -> None:
    try:
        _v346_ensure_table_ui_schema_basic()
        current = _v369_sqlite_get(table_key)
        final_widths = _v369_normalize_widths(widths if widths is not None else current.get("widths", {}))
        final_order = _v369_normalize_order(order if order is not None else current.get("order", []))
        execute(
            """
            INSERT INTO table_ui_settings(table_key, widths_json, order_json, updated_at)
            VALUES (?, ?, ?, datetime('now','localtime'))
            ON CONFLICT(table_key) DO UPDATE SET
                widths_json=excluded.widths_json,
                order_json=excluded.order_json,
                updated_at=excluded.updated_at
            """,
            (str(table_key), json.dumps(final_widths, ensure_ascii=False), json.dumps(final_order, ensure_ascii=False)),
        )
    except Exception:
        pass


def load_widths(table_key: str) -> dict[str, int]:  # type: ignore[override]
    try:
        ensure_table_ui_schema()
    except Exception:
        pass
    for key in _v369_key_candidates(table_key):
        data = _v369_load_table_settings_direct(key)
        widths = _v369_normalize_widths(data.get("widths", {}) if isinstance(data, dict) else {})
        if widths:
            return widths
    for key in _v369_key_candidates(table_key):
        widths = _v369_sqlite_get(key).get("widths", {})
        if widths:
            return _v369_normalize_widths(widths)
    return {}


def save_widths(table_key: str, widths: dict[str, int]) -> None:  # type: ignore[override]
    norm = _v369_normalize_widths(widths)
    keys = _v369_key_candidates(table_key)
    primary = keys[0]
    try:
        from services.table_persistence_service import save_table_settings
        save_table_settings(primary, widths=norm, reason="v369_save_widths")
    except Exception:
        pass
    for key in keys:
        _v369_sqlite_put(key, widths=norm)
        try:
            st.session_state[f"_spt_width_cache_{key}"] = {"ts": time.time(), "data": dict(norm)}
        except Exception:
            pass


def load_column_order(table_key: str) -> list[str]:  # type: ignore[override]
    try:
        ensure_table_ui_schema()
    except Exception:
        pass
    for key in _v369_key_candidates(table_key):
        data = _v369_load_table_settings_direct(key)
        order = _v369_normalize_order(data.get("order", []) if isinstance(data, dict) else [])
        if order:
            return order
    for key in _v369_key_candidates(table_key):
        order = _v369_sqlite_get(key).get("order", [])
        if order:
            return _v369_normalize_order(order)
    return []


def save_column_order(table_key: str, order: Iterable[str]) -> None:  # type: ignore[override]
    cols = _v369_normalize_order(order)
    keys = _v369_key_candidates(table_key)
    primary = keys[0]
    try:
        from services.table_persistence_service import save_table_settings
        save_table_settings(primary, order=cols, reason="v369_save_column_order")
    except Exception:
        pass
    for key in keys:
        _v369_sqlite_put(key, order=cols)


def build_column_config(table_key: str, df: pd.DataFrame) -> dict:  # type: ignore[override]
    widths = load_widths(table_key)
    cfg = {}
    for col in df.columns:
        c = str(col)
        cfg[col] = _column_config(c, widths.get(c), df[col] if col in df.columns else None)
    return cfg


def apply_column_order(table_key: str, df: pd.DataFrame) -> pd.DataFrame:  # type: ignore[override]
    if df is None or df.empty:
        return df
    order = load_column_order(table_key)
    if not order:
        return df
    ordered = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in ordered]
    return df[ordered + rest] if ordered else df


# ===== V3.70 readonly ID display repair =====
# 目的：解決 05/08/13 等唯讀表格中 id 欄位因永久 JSON / GitHub 還原沒有 SQLite 自動流水號，
# 畫面顯示整欄 None 的問題。這只改「顯示用 dataframe」，不寫回資料、不改業務主鍵。

def _v370_is_blank_id_value(value: Any) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    s = str(value).strip()
    return s == "" or s.lower() in {"none", "nan", "nat", "<na>", "null"}


def _v370_fill_readonly_id_for_display(df: pd.DataFrame, editable: bool) -> pd.DataFrame:
    if editable or df is None or df.empty:
        return df
    out = df.copy()
    for col in ("id", "ID / ID"):
        if col not in out.columns:
            continue
        vals = []
        for i, value in enumerate(out[col].tolist(), 1):
            vals.append(i if _v370_is_blank_id_value(value) else value)
        out[col] = vals
    return out


_v370_previous_render_table = render_table

def render_table(
    df: pd.DataFrame,
    table_key: str,
    *,
    editable: bool = False,
    disabled: Iterable[str] | None = None,
    key: str | None = None,
    height: int | None = None,
    num_rows: str = "fixed",
) -> pd.DataFrame | None:  # type: ignore[override]
    # 只在唯讀顯示時補序號，避免資料來源缺少 SQLite id 時畫面出現 None。
    # 可編輯模式仍保留真實 id，讓新增資料由儲存流程產生主鍵，不用假 id 造成覆蓋錯誤。
    display_source = _v370_fill_readonly_id_for_display(df, editable=editable) if isinstance(df, pd.DataFrame) else df
    safe_disabled = list(disabled or [])
    if editable:
        for c in ("id", "ID / ID"):
            if isinstance(df, pd.DataFrame) and c in df.columns and c not in safe_disabled:
                safe_disabled.append(c)
    return _v370_previous_render_table(
        display_source,
        table_key,
        editable=editable,
        disabled=safe_disabled,
        key=key,
        height=height,
        num_rows=num_rows,
    )
# ===== END V3.70 readonly ID display repair =====


# ========================= V72 Table UI Speed and Reboot Persistence Guard =========================
# 不改表格內容邏輯，只減少欄寬設定工具的 inspect.stack 成本，並確保儲存後立即清掉寬度/順序快取。

def _width_settings_instance_key(table_key: str, title: str) -> str:  # type: ignore[override]
    try:
        import sys
        frame = sys._getframe(1)
        depth = 0
        caller = "unknown"
        while frame is not None and depth < 10:
            filename = str(frame.f_code.co_filename).replace("\\", "/")
            if "/site-packages/" not in filename and not filename.endswith("table_ui_service.py"):
                caller = f"{Path(filename).stem}_{frame.f_lineno}"
                break
            frame = frame.f_back
            depth += 1
    except Exception:
        caller = "unknown"
    return _safe_widget_key_part(f"{table_key}_{title}_{caller}")


def _v72_clear_table_ui_cache(table_key: str) -> None:
    try:
        keys = []
        try:
            keys = _v369_key_candidates(table_key)
        except Exception:
            keys = [str(table_key)]
        for k in keys:
            st.session_state.pop(f"_spt_width_cache_{k}", None)
    except Exception:
        pass


_v72_prev_save_widths = save_widths
_v72_prev_save_column_order = save_column_order

def save_widths(table_key: str, widths: dict[str, int]) -> None:  # type: ignore[override]
    _v72_prev_save_widths(table_key, widths)
    _v72_clear_table_ui_cache(table_key)


def save_column_order(table_key: str, order: Iterable[str]) -> None:  # type: ignore[override]
    _v72_prev_save_column_order(table_key, order)
    _v72_clear_table_ui_cache(table_key)
# ======================= END V72 Table UI Speed and Reboot Persistence Guard =======================


# ===================== V145 TABLE WIDTH ORDER SAFE CLAMP + NO DUPLICATE 02 SETTINGS =====================
# 修正目的：
# 1) 02 歷史紀錄欄寬/欄位順序設定曾儲存 31、32... 等舊順序值；
#    目前表格只剩 29 欄時，st.number_input(value=31, max_value=29) 會直接拋出
#    StreamlitValueAboveMaxError，造成整頁崩潰。
# 2) 02 歷史紀錄已在頁面上方有專用「02 歷史明細編輯欄寬設定」，
#    render_table 唯讀表格又自動產生一次「欄寬設定」，所以畫面多一組設定。
# 3) 本段只修表格 UI 設定，不改任何業務資料、不改 01/02 工時同步、不改權威檔內容。


def _v145_to_int(value, default: int) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(str(value).strip()))
    except Exception:
        return int(default)


def _v145_clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        iv = _v145_to_int(value, default)
        return max(int(minimum), min(int(maximum), int(iv)))
    except Exception:
        return int(default)


def _v145_normalized_current_order(table_key: str, df: pd.DataFrame) -> list[str]:
    """Return saved order filtered to current columns and renumbered implicitly.

    The stored order is a list of column names, but its old position can be larger
    than current column count after columns were removed/hidden.  We never pass
    that stale position directly into st.number_input.
    """
    if df is None or df.empty:
        return []
    current = [str(c) for c in df.columns]
    current_set = set(current)
    try:
        saved = load_column_order(table_key)
    except Exception:
        saved = []
    out: list[str] = []
    seen: set[str] = set()
    for c in saved or []:
        s = str(c).strip()
        if s in current_set and s not in seen:
            out.append(s)
            seen.add(s)
    for s in current:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _v145_sanitize_widget_int(key: str, minimum: int, maximum: int, default: int) -> int:
    value = st.session_state.get(key, default)
    safe = _v145_clamp_int(value, minimum, maximum, default)
    if key in st.session_state and st.session_state.get(key) != safe:
        try:
            st.session_state[key] = safe
        except Exception:
            pass
    return safe


def render_width_settings(table_key: str, df: pd.DataFrame, title: str = "欄寬設定 / Column Width Settings") -> None:  # type: ignore[override]
    """V145 safe width/order editor.

    Replaces the old width editor to guarantee default order <= current column count.
    This prevents StreamlitValueAboveMaxError when a persisted order was created
    with more columns than the current table.
    """
    if df is None or df.empty:
        return
    try:
        instance_key = _width_settings_instance_key(table_key, title)
    except Exception:
        instance_key = _safe_widget_key_part(f"{table_key}_{title}")
    show_key = f"show_widths_{instance_key}"
    show = st.toggle(f"⌬️ 顯示{title}", value=False, key=show_key)
    if not show:
        return

    widths = load_widths(table_key)
    current_cols = list(df.columns)
    current_order_keys = _v145_normalized_current_order(table_key, df)
    order_index = {str(c): i + 1 for i, c in enumerate(current_order_keys)}
    max_order = max(len(current_cols), 1)

    with st.expander(title, expanded=True):
        st.caption("欄寬與欄位順序會永久保存。順序數字越小越靠左；若欄位數變少，舊順序會自動壓回有效範圍，避免頁面崩潰。")
        new_widths: dict[str, int] = {}
        new_orders: dict[str, int] = {}
        cols = st.columns(4)
        for idx, col in enumerate(current_cols):
            col_str = str(col)
            col_key = _safe_widget_key_part(col_str)
            width_key = f"width_{instance_key}_{idx}_{col_key}"
            order_key = f"order_{instance_key}_{idx}_{col_key}"
            default_width = _v145_clamp_int(widths.get(col_str, DEFAULT_WIDTHS.get(col_str, 140)), 60, 700, 140)
            default_order = _v145_clamp_int(order_index.get(col_str, idx + 1), 1, max_order, idx + 1)
            with cols[idx % 4]:
                st.markdown(f"**{label_for(col_str)}**")
                safe_width = _v145_sanitize_widget_int(width_key, 60, 700, default_width)
                new_widths[col_str] = st.number_input(
                    "欄寬",
                    min_value=60,
                    max_value=700,
                    value=safe_width,
                    step=10,
                    key=width_key,
                )
                safe_order = _v145_sanitize_widget_int(order_key, 1, max_order, default_order)
                new_orders[col_str] = st.number_input(
                    "順序",
                    min_value=1,
                    max_value=max_order,
                    value=safe_order,
                    step=1,
                    key=order_key,
                )
        if st.button("儲存欄位設定 / Save Column Settings", key=f"save_widths_{instance_key}", use_container_width=True):
            save_widths(table_key, new_widths)
            ordered_cols = [c for c, _ in sorted(new_orders.items(), key=lambda kv: (int(kv[1]), str(kv[0])))]
            save_column_order(table_key, ordered_cols)
            try:
                _v72_clear_table_ui_cache(table_key)
            except Exception:
                pass
            st.success("已永久儲存欄寬與欄位順序設定。")
            st.rerun()


def render_table(
    df: pd.DataFrame,
    table_key: str,
    *,
    editable: bool = False,
    disabled: Iterable[str] | None = None,
    key: str | None = None,
    height: int | None = None,
    num_rows: str = "fixed",
    show_width_settings: bool = True,
) -> pd.DataFrame | None:  # type: ignore[override]
    """V145 final table renderer with optional width settings.

    Existing callers are unchanged.  Pages that already render a custom width
    setting block can pass show_width_settings=False to avoid duplicate controls.
    """
    if df is None:
        st.info("目前沒有資料 / No data")
        return None
    if df.empty and not editable:
        st.info("目前沒有資料 / No data")
        return None

    if not editable and show_width_settings:
        render_width_settings(table_key, df)

    source_df = df.copy() if isinstance(df, pd.DataFrame) else df
    if isinstance(source_df, pd.DataFrame):
        source_df = apply_column_order(table_key, source_df)
        if not editable:
            source_df = _v370_fill_readonly_id_for_display(source_df, editable=False)
        display_df = _format_duration_columns_for_display(source_df)
        display_df = _prepare_display_dataframe(display_df)
    else:
        display_df = source_df

    cfg = build_column_config(table_key, display_df) if isinstance(display_df, pd.DataFrame) else {}
    disabled_cols = list(disabled or [])
    for c in ("work_hours", "total_hours", "avg_hours"):
        if isinstance(display_df, pd.DataFrame) and c in display_df.columns and c not in disabled_cols:
            disabled_cols.append(c)
    if editable:
        for c in ("id", "ID / ID"):
            if isinstance(display_df, pd.DataFrame) and c in display_df.columns and c not in disabled_cols:
                disabled_cols.append(c)
    visual_order = [str(c) for c in display_df.columns] if isinstance(display_df, pd.DataFrame) else None

    if editable:
        return st.data_editor(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config=cfg,
            column_order=visual_order,
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
        column_order=visual_order,
        height=height,
        key=key or f"frame_{table_key}",
    )
    return None

# =================== END V145 TABLE WIDTH ORDER SAFE CLAMP + NO DUPLICATE 02 SETTINGS ===================

# ===================== V156 TABLE UI LIGHTWEIGHT CACHE =====================
# 目的：改善各模組表格顯示速度。欄寬、欄位順序、column_config 是純 UI 設定，
# 可安全短期快取；儲存欄寬/順序時會立即清除，不影響資料內容與權威檔。
try:
    import time as _v156_time
except Exception:  # pragma: no cover
    _v156_time = None

_V156_TABLE_UI_CACHE: dict[tuple, tuple[float, object]] = {}
_V156_TABLE_UI_TTL = 20.0


def _v156_ui_now() -> float:
    try:
        return float(_v156_time.time()) if _v156_time is not None else 0.0
    except Exception:
        return 0.0


def _v156_ui_get(key: tuple):
    now = _v156_ui_now()
    got = _V156_TABLE_UI_CACHE.get(key)
    if got and now and (now - got[0] <= _V156_TABLE_UI_TTL):
        value = got[1]
        try:
            return value.copy()
        except Exception:
            return value
    return None


def _v156_ui_set(key: tuple, value) -> None:
    try:
        _V156_TABLE_UI_CACHE[key] = (_v156_ui_now(), value.copy() if hasattr(value, 'copy') else value)
        if len(_V156_TABLE_UI_CACHE) > 256:
            for k in list(_V156_TABLE_UI_CACHE.keys())[:64]:
                _V156_TABLE_UI_CACHE.pop(k, None)
    except Exception:
        pass


def clear_table_ui_light_cache(table_key: str | None = None) -> None:
    try:
        if not table_key:
            _V156_TABLE_UI_CACHE.clear(); return
        tk = str(table_key)
        for k in list(_V156_TABLE_UI_CACHE.keys()):
            if len(k) > 1 and str(k[1]) == tk:
                _V156_TABLE_UI_CACHE.pop(k, None)
    except Exception:
        pass


_v156_prev_load_widths = load_widths
_v156_prev_load_column_order = load_column_order
_v156_prev_build_column_config = build_column_config
_v156_prev_save_widths = save_widths
_v156_prev_save_column_order = save_column_order


def load_widths(table_key: str) -> dict[str, int]:  # type: ignore[override]
    tk = str(table_key or '')
    cached = _v156_ui_get(('widths', tk))
    if isinstance(cached, dict):
        return cached
    val = _v156_prev_load_widths(tk)
    _v156_ui_set(('widths', tk), val)
    return dict(val or {})


def load_column_order(table_key: str) -> list[str]:  # type: ignore[override]
    tk = str(table_key or '')
    cached = _v156_ui_get(('order', tk))
    if isinstance(cached, list):
        return list(cached)
    val = _v156_prev_load_column_order(tk)
    _v156_ui_set(('order', tk), list(val or []))
    return list(val or [])


def _v156_df_signature(df: pd.DataFrame) -> tuple:
    try:
        return (tuple(str(c) for c in df.columns), tuple(str(t) for t in df.dtypes.astype(str).tolist()))
    except Exception:
        return (tuple(str(c) for c in getattr(df, 'columns', [])),)


def build_column_config(table_key: str, df: pd.DataFrame) -> dict:  # type: ignore[override]
    tk = str(table_key or '')
    sig = _v156_df_signature(df) if isinstance(df, pd.DataFrame) else ()
    widths = load_widths(tk)
    width_sig = tuple(sorted((str(k), int(v)) for k, v in widths.items() if str(k)))
    key = ('column_config', tk, sig, width_sig)
    cached = _v156_ui_get(key)
    if isinstance(cached, dict):
        return cached
    cfg = _v156_prev_build_column_config(tk, df)
    _v156_ui_set(key, cfg)
    return dict(cfg or {})


def save_widths(table_key: str, widths: dict[str, int]) -> None:  # type: ignore[override]
    _v156_prev_save_widths(table_key, widths)
    clear_table_ui_light_cache(table_key)


def save_column_order(table_key: str, order: Iterable[str]) -> None:  # type: ignore[override]
    _v156_prev_save_column_order(table_key, order)
    clear_table_ui_light_cache(table_key)
# =================== END V156 TABLE UI LIGHTWEIGHT CACHE ===================
