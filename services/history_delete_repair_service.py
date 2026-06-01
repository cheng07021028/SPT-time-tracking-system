# -*- coding: utf-8 -*-
"""V178B strict history delete repair helpers.

Backend-only module.  It does not import Streamlit, does not change CSS/theme,
and does not change table rendering.  It makes 02 History deletion authoritative
across 02_history, 01_time_records, SQLite cache, and V178 tombstones.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TRUTHY = {"true", "1", "yes", "y", "on", "勾選", "是", "checked", "select", "selected", "✓", "☑"}
DELETE_COL_CANDIDATES = ["刪除 / Delete", "刪除", "Delete", "delete", "selected", "勾選刪除", "刪除勾選"]
ID_COL_CANDIDATES = ["id", "ID / ID", "ID", "紀錄ID", "紀錄 ID", "record_id", "Record ID"]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return bool(value)
    text = _clean(value).lower()
    return text in TRUTHY


def normalize_ids(record_ids: Iterable[Any] | None) -> list[int]:
    ids: list[int] = []
    for value in record_ids or []:
        rid = _safe_int(value)
        if rid > 0 and rid not in ids:
            ids.append(rid)
    return ids


def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = [str(c) for c in df.columns]
    for c in candidates:
        if c in df.columns:
            return c
    lowered = {str(c).strip().lower(): c for c in df.columns}
    for c in candidates:
        got = lowered.get(str(c).strip().lower())
        if got is not None:
            return got
    # Soft contains matching for localized labels.
    for col in cols:
        low = col.lower()
        if any(str(c).strip().lower() in low for c in candidates if c):
            return col
    return None


def checked_ids_from_editor(frame: Any, checkbox_col: str | None = None) -> list[int]:
    """Extract checked ids from a Streamlit data_editor return frame.

    Handles both internal names (id) and displayed labels (ID / ID), because some
    table renderers return localized column labels.
    """
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    id_col = _first_existing_col(frame, ID_COL_CANDIDATES)
    if not id_col:
        return []
    candidates = []
    if checkbox_col:
        candidates.append(str(checkbox_col))
    candidates.extend(DELETE_COL_CANDIDATES)
    checkbox = _first_existing_col(frame, candidates)
    if not checkbox:
        return []
    try:
        mask = frame[checkbox].map(_to_bool)
        return normalize_ids(frame.loc[mask, id_col].tolist())
    except Exception:
        return []


def _business_key(row: dict[str, Any]) -> str:
    parts = [
        _clean(row.get("employee_id") or row.get("工號 / Employee ID") or row.get("工號")),
        _clean(row.get("employee_name") or row.get("姓名 / Name") or row.get("姓名")),
        _clean(row.get("work_order") or row.get("製令 / Work Order") or row.get("製令")),
        _clean(row.get("process_name") or row.get("工段 / Process") or row.get("工段")),
        _clean(row.get("start_timestamp") or row.get("開始時間戳 / Start Timestamp") or row.get("開始時間 / Start Timestamp") or row.get("開始時間")),
    ]
    return "|".join(parts)


def _record_key(row: dict[str, Any]) -> str:
    return _clean(row.get("record_key") or row.get("紀錄鍵 / Record Key") or row.get("Record Key"))


def _row_id(row: dict[str, Any]) -> int:
    return _safe_int(row.get("id") or row.get("ID / ID") or row.get("ID") or row.get("record_id"))


def _load_authority(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table  # type: ignore
        df = df_from_table(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _save_authority(module_key: str, df: pd.DataFrame, reason: str, *, github: bool = False) -> bool:
    try:
        from services.permanent_authority_service import table_from_df, update_tables  # type: ignore
        rows = table_from_df(df) if isinstance(df, pd.DataFrame) else []
        try:
            update_tables(module_key, {"time_records": rows}, reason=reason, github=bool(github))
        except TypeError:
            update_tables(module_key, {"time_records": rows}, reason=reason)
        return True
    except Exception:
        return False


def _load_sqlite_rows(ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    try:
        from services.db_service import query_df  # type: ignore
        placeholders = ",".join(["?"] * len(ids))
        df = query_df(f"SELECT * FROM time_records WHERE id IN ({placeholders})", ids)
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _collect_evidence(ids: list[int], editor_df: Any = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for df in [_load_authority("02_history"), _load_authority("01_time_records"), _load_sqlite_rows(ids)]:
        if isinstance(df, pd.DataFrame) and not df.empty:
            id_col = _first_existing_col(df, ID_COL_CANDIDATES)
            if id_col:
                id_series = pd.to_numeric(df[id_col], errors="coerce").fillna(-1).astype(int)
                sub = df.loc[id_series.isin(ids)]
                if not sub.empty:
                    rows.extend(sub.to_dict("records"))
    if isinstance(editor_df, pd.DataFrame) and not editor_df.empty:
        id_col = _first_existing_col(editor_df, ID_COL_CANDIDATES)
        if id_col:
            id_series = pd.to_numeric(editor_df[id_col], errors="coerce").fillna(-1).astype(int)
            sub = editor_df.loc[id_series.isin(ids)]
            if not sub.empty:
                rows.extend(sub.to_dict("records"))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        key = "|".join([str(_row_id(r)), _record_key(r), _business_key(r)])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _add_tombstones(rows: list[dict[str, Any]], ids: list[int], reason: str) -> int:
    written = 0
    try:
        from services import time_record_transaction_guard_service as guard  # type: ignore
        try:
            guard.ensure_v178_schema()
        except Exception:
            pass
        if rows:
            written += int(guard.add_tombstones(rows, reason=reason) or 0)
        # If row evidence is missing, still add id-only tombstones so a stale cache row cannot return.
        missing_ids = [i for i in ids if i not in {_row_id(r) for r in rows}]
        if missing_ids:
            written += int(guard.add_tombstones([{"id": i} for i in missing_ids], reason=reason) or 0)
    except Exception:
        written += _fallback_tombstone_json(rows, ids, reason)
    return int(written)


def _fallback_tombstone_json(rows: list[dict[str, Any]], ids: list[int], reason: str) -> int:
    """Fallback JSON tombstones when V178 guard service is unavailable."""
    try:
        try:
            from services.timezone_service import now_text  # type: ignore
            now = now_text()
        except Exception:
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "time_record_delete_tombstones" / "records.json"
        old: list[dict[str, Any]] = []
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                old = list(data.get("tombstones") or data.get("records") or [])
            elif isinstance(data, list):
                old = list(data)
        additions: list[dict[str, Any]] = []
        for r in rows:
            additions.append({"record_id": _row_id(r), "record_key": _record_key(r), "business_key": _business_key(r), "deleted_at": now, "reason": reason, "source": "V178B_FALLBACK"})
        have_ids = {_row_id(r) for r in rows}
        for i in ids:
            if i not in have_ids:
                additions.append({"record_id": int(i), "record_key": "", "business_key": "", "deleted_at": now, "reason": reason, "source": "V178B_FALLBACK"})
        merged: dict[str, dict[str, Any]] = {}
        for r in old + additions:
            key = "|".join([_clean(r.get("record_id")), _clean(r.get("record_key")), _clean(r.get("business_key"))])
            merged[key] = dict(r)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": "V178B", "updated_at": now, "tombstones": list(merged.values())}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
        return len(additions)
    except Exception:
        return 0


def _remove_from_df(df: pd.DataFrame, ids: list[int], evidence: list[dict[str, Any]]) -> tuple[pd.DataFrame, int]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df, 0
    out = df.copy()
    mask = pd.Series([False] * len(out), index=out.index)
    id_col = _first_existing_col(out, ID_COL_CANDIDATES)
    if id_col and ids:
        id_series = pd.to_numeric(out[id_col], errors="coerce").fillna(-1).astype(int)
        mask = mask | id_series.isin(ids)
    keys = {_record_key(r) for r in evidence if _record_key(r)}
    if keys:
        rk_col = _first_existing_col(out, ["record_key", "紀錄鍵 / Record Key", "Record Key"])
        if rk_col:
            mask = mask | out[rk_col].map(lambda v: _clean(v) in keys)
    bkeys = {_business_key(r) for r in evidence if _business_key(r) and _business_key(r) != "||||"}
    if bkeys:
        row_bkeys = out.apply(lambda r: _business_key(dict(r)), axis=1)
        mask = mask | row_bkeys.isin(bkeys)
    deleted = int(mask.sum())
    return out.loc[~mask].copy().reset_index(drop=True), deleted


def _delete_from_sqlite(ids: list[int], evidence: list[dict[str, Any]]) -> int:
    deleted = 0
    try:
        from services.db_service import DB_PATH  # type: ignore
        db_path = Path(DB_PATH)
    except Exception:
        db_path = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(db_path, timeout=12)
        try:
            conn.execute("PRAGMA busy_timeout=8000")
            conn.execute("BEGIN")
            if ids:
                placeholders = ",".join(["?"] * len(ids))
                cur = conn.execute(f"DELETE FROM time_records WHERE id IN ({placeholders})", tuple(ids))
                deleted += int(cur.rowcount or 0)
            keys = [_record_key(r) for r in evidence if _record_key(r)]
            if keys:
                placeholders = ",".join(["?"] * len(keys))
                cur = conn.execute(f"DELETE FROM time_records WHERE record_key IN ({placeholders})", tuple(keys))
                deleted += int(cur.rowcount or 0)
            for bk in {_business_key(r) for r in evidence if _business_key(r) and _business_key(r) != "||||"}:
                parts = bk.split("|", 4)
                if len(parts) == 5:
                    cur = conn.execute(
                        """
                        DELETE FROM time_records
                        WHERE COALESCE(employee_id,'')=? AND COALESCE(employee_name,'')=?
                          AND COALESCE(work_order,'')=? AND COALESCE(process_name,'')=?
                          AND COALESCE(start_timestamp,'')=?
                        """,
                        tuple(parts),
                    )
                    deleted += int(cur.rowcount or 0)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()
    except Exception:
        return int(deleted)
    try:
        from services.db_service import clear_query_cache  # type: ignore
        clear_query_cache()
    except Exception:
        pass
    return int(deleted)


def _write_log(action: str, message: str, level: str = "WARN") -> None:
    try:
        from services.log_service import write_log  # type: ignore
        write_log(action, message, "time_records", level=level)
    except Exception:
        try:
            from services.time_record_service import write_log as tr_write_log  # type: ignore
            tr_write_log(action, message, "time_records", level=level)
        except Exception:
            pass


def delete_history_records_strict(
    record_ids: Iterable[Any] | None,
    *,
    reason: str = "02 歷史紀錄刪除",
    editor_df: Any = None,
    previous_delete_callable: Any = None,
) -> dict[str, Any]:
    """Strictly delete 02 history rows and keep all display/cache layers aligned."""
    ids = normalize_ids(record_ids)
    if not ids and isinstance(editor_df, pd.DataFrame):
        ids = checked_ids_from_editor(editor_df, "刪除 / Delete")
    if not ids:
        return {"ok": False, "deleted_count": 0, "ids": [], "message": "沒有收到可刪除的 ID"}

    evidence = _collect_evidence(ids, editor_df=editor_df)
    tombstones = _add_tombstones(evidence, ids, reason)

    # Preserve existing event-journal/delete-proof behavior, but do not trust it as the final source.
    prev_count = 0
    if callable(previous_delete_callable):
        try:
            prev_count = int(previous_delete_callable(ids, reason=reason) or 0)
        except Exception as exc:
            _write_log("V178B_PREVIOUS_DELETE_ERROR", f"原刪除流程失敗，V178B 將強制同步權威檔：{exc}", level="ERROR")

    df02 = _load_authority("02_history")
    df01 = _load_authority("01_time_records")
    if (df02 is None or df02.empty) and isinstance(editor_df, pd.DataFrame) and not editor_df.empty:
        # Do not use editor_df as full authority because it may be filtered.  This is only for evidence.
        pass

    remaining02, del02 = _remove_from_df(df02, ids, evidence) if isinstance(df02, pd.DataFrame) else (pd.DataFrame(), 0)
    remaining01, del01 = _remove_from_df(df01, ids, evidence) if isinstance(df01, pd.DataFrame) else (pd.DataFrame(), 0)
    saved02 = _save_authority("02_history", remaining02, "delete_history_records_v178b_02", github=False)
    saved01 = _save_authority("01_time_records", remaining01 if isinstance(df01, pd.DataFrame) and not df01.empty else remaining02, "delete_history_records_v178b_01", github=False)
    sqlite_deleted = _delete_from_sqlite(ids, evidence)

    try:
        from services import time_record_transaction_guard_service as guard  # type: ignore
        guard.purge_tombstoned_from_sqlite()
    except Exception:
        pass
    try:
        from services.db_service import mark_data_changed, clear_query_cache  # type: ignore
        clear_query_cache()
        mark_data_changed(f"V178B 已刪除歷史紀錄 {max(del02, del01, prev_count, len(ids))} 筆", "delete_history_records_v178b")
    except Exception:
        pass

    deleted_count = int(max(del02, del01, prev_count, len(evidence), sqlite_deleted, len(ids)))
    _write_log(
        "DELETE_TIME_RECORDS_V178B",
        f"{reason}：已刪除/封鎖 {deleted_count} 筆；02刪除={del02}，01刪除={del01}，SQLite刪除={sqlite_deleted}，tombstone={tombstones}。",
        level="WARN",
    )
    return {
        "ok": True,
        "deleted_count": deleted_count,
        "ids": ids,
        "evidence_count": len(evidence),
        "deleted_02": del02,
        "deleted_01": del01,
        "deleted_sqlite": sqlite_deleted,
        "tombstones": tombstones,
        "saved_02": saved02,
        "saved_01": saved01,
    }
