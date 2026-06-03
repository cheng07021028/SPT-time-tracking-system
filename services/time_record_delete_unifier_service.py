# -*- coding: utf-8 -*-
"""V63 delete unifier: Neon/runtime authority only.

The old version wrote tombstones into local authority JSON and SQLite cache.  In
this runtime-consolidated build, deletion is a DB soft delete through
services.time_record_service.delete_time_records. UI imports remain unchanged.
"""
from __future__ import annotations

from typing import Any
import pandas as pd

ID_COLS = ["id", "ID", "ID / ID", "ID / ID / ID", "紀錄編號", "record_id"]
DELETE_COLS = ["刪除 / Delete", "Delete", "刪除", "_delete"]


def _text(v: Any) -> str:
    try:
        if v is None or pd.isna(v):
            return ""
    except Exception:
        if v is None:
            return ""
    return str(v).strip()


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return _text(v).lower() in {"1", "true", "yes", "y", "on", "checked", "selected", "是", "勾選", "刪除"}


def _to_int(v: Any) -> int | None:
    try:
        s = _text(v)
        if not s:
            return None
        i = int(float(s))
        return i if i > 0 else None
    except Exception:
        return None


def selected_rows_from_editor(frame: pd.DataFrame, delete_col: str | None = None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    col = delete_col or next((c for c in DELETE_COLS if c in frame.columns), "")
    if not col or col not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame[col].map(_to_bool)].copy().reset_index(drop=True)


def selected_ids_from_editor(frame: pd.DataFrame, delete_col: str | None = None) -> list[int]:
    selected = selected_rows_from_editor(frame, delete_col)
    if selected.empty:
        return []
    id_col = next((c for c in ID_COLS if c in selected.columns), "")
    if not id_col:
        return []
    ids: list[int] = []
    for x in selected[id_col].tolist():
        rid = _to_int(x)
        if rid is not None and rid not in ids:
            ids.append(rid)
    return ids


def force_delete_time_records(record_ids, selected_rows: pd.DataFrame | None = None, reason: str = "V63 editor selected delete", github: bool = False) -> int:
    from services.time_record_service import delete_time_records
    ids: list[int] = []
    for x in record_ids or []:
        rid = _to_int(x)
        if rid is not None and rid not in ids:
            ids.append(rid)
    if not ids and isinstance(selected_rows, pd.DataFrame):
        ids = selected_ids_from_editor(selected_rows)
    return int(delete_time_records(ids, reason=reason) or 0)


def delete_selected_time_records_from_editor(frame: pd.DataFrame, delete_col: str | None = None, *, reason: str = "V63 editor selected delete", github: bool = False) -> int:
    return force_delete_time_records(selected_ids_from_editor(frame, delete_col), selected_rows=frame, reason=reason, github=github)


def assert_delete_available() -> dict[str, Any]:
    return {"ok": True, "service": "time_record_delete_unifier_service", "version": "V63_NEON_RUNTIME", "supports": ["id", "soft_delete", "neon_runtime_authority"]}
