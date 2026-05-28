# -*- coding: utf-8 -*-
"""V196 reboot-proof hard delete guard for SPT time records.

Purpose:
- Deleting rows from 01/02 must survive Streamlit reboot.
- Deleted rows must not be resurrected from SQLite, event journal, row shard, or LOG recovery.
- Store durable tombstones in canonical authority files, then filter all display/query paths.

This service is intentionally UI-neutral: it does not change CSS/theme/pages.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from services.timezone_service import now_text
except Exception:  # pragma: no cover
    from datetime import datetime
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_GUARD_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "time_record_delete_guard" / "records.json"
SETTINGS_MODULES = ("02_history", "01_time_records")
TABLE_NAME = "deleted_time_records"
SETTINGS_KEY = "v196_hard_deleted_time_records"
_BOOTSTRAPPED_FROM_LOGS = False
_CACHE: dict[str, Any] = {"entries": None, "identity_set": None}


def _txt(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat", "null"):
        return ""
    return s


def _to_int(v: Any) -> int | None:
    s = _txt(v)
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None

def _id_col(df: pd.DataFrame | None) -> str:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return ""
    for c in ("id", "ID", "ID / ID", "ID / ID / ID", "紀錄編號", "record_id"):
        if c in df.columns:
            return c
    return ""


def _norm_ts(v: Any) -> str:
    s = _txt(v)
    if not s:
        return ""
    s = s.replace("/", "-")
    # keep seconds when available
    m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})(?:\s+|T)?(\d{1,2}:\d{2}(?::\d{2})?)?", s)
    if not m:
        return s
    d = m.group(1)
    t = m.group(2) or ""
    try:
        parts = d.split("-")
        d = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    except Exception:
        pass
    if t:
        tp = t.split(":")
        if len(tp) == 2:
            t = f"{int(tp[0]):02d}:{int(tp[1]):02d}:00"
        elif len(tp) >= 3:
            t = f"{int(tp[0]):02d}:{int(tp[1]):02d}:{int(float(tp[2])):02d}"
        return f"{d} {t}"
    return d


def business_key(row: dict[str, Any]) -> str:
    start = (
        _txt(row.get("start_timestamp"))
        or _txt(row.get("開始時間戳 / Start Timestamp"))
        or _txt(row.get("開始時間 / Start Timestamp"))
        or _txt(row.get("開始時間戳"))
        or _txt(row.get("開始時間"))
    )
    if not start:
        sd = _txt(row.get("start_date")) or _txt(row.get("開始日期 / Start Date")) or _txt(row.get("開始日期"))
        st = _txt(row.get("start_time")) or _txt(row.get("開始時刻 / Start Time")) or _txt(row.get("開始時刻"))
        start = (sd + " " + st).strip() if (sd or st) else ""
    return "|".join([
        _txt(row.get("employee_id") or row.get("工號") or row.get("工號 / Employee ID") or row.get("Employee ID")),
        _txt(row.get("employee_name") or row.get("姓名") or row.get("姓名 / Name") or row.get("Name")),
        _txt(row.get("work_order") or row.get("製令") or row.get("製令 / Work Order") or row.get("Work Order")),
        _txt(row.get("process_name") or row.get("工段名稱") or row.get("工段名稱 / Process") or row.get("工段 / Process") or row.get("Process") or row.get("process")),
        _norm_ts(start),
    ])


def identities_for_row(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    rid = _to_int(row.get("id") or row.get("ID") or row.get("ID / ID"))
    if rid is not None:
        ids.add(f"id:{rid}")
    rk = _txt(row.get("record_key") or row.get("紀錄鍵 / Record Key") or row.get("Record Key") or row.get("record key"))
    if rk:
        ids.add(f"record_key:{rk}")
    bk = business_key(row)
    if bk.strip("|"):
        ids.add(f"biz:{bk}")
    return ids


def _clean_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    out.setdefault("deleted_at", now_text())
    out.setdefault("source", "V196")
    identities = set()
    for x in out.get("identities", []) if isinstance(out.get("identities", []), list) else []:
        s = _txt(x)
        if s:
            identities.add(s)
    row = out.get("row") if isinstance(out.get("row"), dict) else {}
    identities.update(identities_for_row(row))
    rid = _to_int(out.get("id"))
    if rid is not None:
        identities.add(f"id:{rid}")
        out["id"] = rid
    rk = _txt(out.get("record_key"))
    if rk:
        identities.add(f"record_key:{rk}")
    bk = _txt(out.get("business_key"))
    if bk:
        identities.add(f"biz:{bk}")
    out["identities"] = sorted(identities)
    return out


def _read_local_entries() -> list[dict[str, Any]]:
    try:
        if LOCAL_GUARD_PATH.exists():
            payload = json.loads(LOCAL_GUARD_PATH.read_text(encoding="utf-8"))
            tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
            rows = tables.get(TABLE_NAME, []) if isinstance(tables, dict) else []
            if isinstance(rows, list):
                return [_clean_entry(x) for x in rows if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _write_local_entries(entries: list[dict[str, Any]]) -> None:
    try:
        LOCAL_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "V196",
            "updated_at": now_text(),
            "reason": "reboot_proof_time_record_delete_guard",
            "tables": {TABLE_NAME: entries},
        }
        tmp = LOCAL_GUARD_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(LOCAL_GUARD_PATH)
    except Exception:
        pass


def _load_settings_entries() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from services.permanent_authority_service import load_settings
        for module in SETTINGS_MODULES:
            stg = load_settings(module)
            rows = stg.get(SETTINGS_KEY, []) if isinstance(stg, dict) else []
            if isinstance(rows, list):
                out.extend([_clean_entry(x) for x in rows if isinstance(x, dict)])
    except Exception:
        pass
    return out


def _save_settings_entries(entries: list[dict[str, Any]], *, github: bool = True) -> None:
    try:
        from services.permanent_authority_service import load_settings, save_settings
        for module in SETTINGS_MODULES:
            stg = load_settings(module)
            if not isinstance(stg, dict):
                stg = {}
            stg[SETTINGS_KEY] = entries
            stg["v196_hard_delete_updated_at"] = now_text()
            save_settings(module, stg, reason="V196 hard delete guard", github=github)
    except Exception:
        pass


def _save_guard_records(entries: list[dict[str, Any]], *, github: bool = True) -> None:
    try:
        from services.permanent_authority_service import update_tables
        update_tables("time_record_delete_guard", {TABLE_NAME: entries}, reason="V196 hard delete guard", github=github)
    except Exception:
        pass


def _dedupe_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        e = _clean_entry(raw)
        identities = e.get("identities", [])
        if identities:
            key = sorted(identities)[0]
        else:
            key = json.dumps(e, ensure_ascii=False, sort_keys=True)
        if key not in by_key:
            by_key[key] = e
        else:
            merged = by_key[key]
            old_ids = set(merged.get("identities", []))
            old_ids.update(e.get("identities", []))
            merged["identities"] = sorted(x for x in old_ids if _txt(x))
            if not merged.get("row") and e.get("row"):
                merged["row"] = e.get("row")
    # bounded to avoid huge settings file
    rows = list(by_key.values())
    rows.sort(key=lambda x: _txt(x.get("deleted_at")), reverse=True)
    return rows[:50000]


def _parse_deleted_ids_from_logs() -> list[dict[str, Any]]:
    """Best-effort: convert existing DELETE_TIME_RECORDS logs with explicit target_id into tombstones."""
    global _BOOTSTRAPPED_FROM_LOGS
    if _BOOTSTRAPPED_FROM_LOGS:
        return []
    _BOOTSTRAPPED_FROM_LOGS = True
    rows: list[dict[str, Any]] = []
    try:
        from services.db_service import query_df
        log_df = query_df(
            """
            SELECT id, log_time, action_type, target_table, target_id, message, detail
            FROM system_logs
            WHERE (action_type LIKE '%DELETE%' OR message LIKE '%刪除%')
              AND (target_table LIKE '%time%' OR target_table LIKE '%工時%' OR message LIKE '%工時%')
            ORDER BY id DESC
            LIMIT 500
            """
        )
        if log_df is None or log_df.empty:
            return []
        for _, rr in log_df.iterrows():
            target = _txt(rr.get("target_id"))
            if not target:
                continue
            ids = []
            for token in re.split(r"[,;，、\s]+", target):
                rid = _to_int(token)
                if rid is not None and rid > 0:
                    ids.append(rid)
            for rid in sorted(set(ids)):
                rows.append({
                    "id": rid,
                    "identities": [f"id:{rid}"],
                    "deleted_at": _txt(rr.get("log_time")) or now_text(),
                    "source": "V196_BOOTSTRAP_FROM_DELETE_LOG",
                    "reason": _txt(rr.get("message"))[:300],
                    "log_id": _to_int(rr.get("id")),
                })
    except Exception:
        return []
    return rows


def load_deleted_entries(*, include_log_bootstrap: bool = True) -> list[dict[str, Any]]:
    if _CACHE.get("entries") is not None:
        return list(_CACHE["entries"])
    entries = []
    entries.extend(_read_local_entries())
    entries.extend(_load_settings_entries())
    if include_log_bootstrap:
        entries.extend(_parse_deleted_ids_from_logs())
    merged = _dedupe_entries(entries)
    _CACHE["entries"] = merged
    return list(merged)


def identity_set() -> set[str]:
    if _CACHE.get("identity_set") is not None:
        return set(_CACHE["identity_set"])
    ids: set[str] = set()
    for e in load_deleted_entries():
        for x in e.get("identities", []) if isinstance(e.get("identities", []), list) else []:
            s = _txt(x)
            if s:
                ids.add(s)
    _CACHE["identity_set"] = set(ids)
    return ids


def clear_cache() -> None:
    _CACHE["entries"] = None
    _CACHE["identity_set"] = None


def row_is_deleted(row: dict[str, Any], deleted_ids: set[str] | None = None) -> bool:
    ids = deleted_ids if deleted_ids is not None else identity_set()
    if not ids:
        return False
    return bool(identities_for_row(row) & ids)


def filter_deleted_rows(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    ids = identity_set()
    if not ids:
        return df.copy().reset_index(drop=True)
    mask = []
    for _, rr in df.iterrows():
        try:
            mask.append(not row_is_deleted(dict(rr.to_dict()), ids))
        except Exception:
            mask.append(True)
    return df.loc[mask].copy().reset_index(drop=True)


def add_deleted_rows(rows: pd.DataFrame | list[dict[str, Any]] | None = None, record_ids: Iterable[Any] | None = None, *, reason: str = "V196 hard delete", github: bool = True) -> list[dict[str, Any]]:
    current = load_deleted_entries(include_log_bootstrap=True)
    new_entries: list[dict[str, Any]] = []
    if isinstance(rows, pd.DataFrame) and not rows.empty:
        for _, rr in rows.iterrows():
            row = dict(rr.to_dict())
            new_entries.append(_clean_entry({
                "row": row,
                "id": _to_int(row.get("id") or row.get("ID") or row.get("ID / ID")),
                "record_key": _txt(row.get("record_key")),
                "business_key": business_key(row),
                "deleted_at": now_text(),
                "source": "V196",
                "reason": reason,
            }))
    elif isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                new_entries.append(_clean_entry({
                    "row": row,
                    "id": _to_int(row.get("id") or row.get("ID") or row.get("ID / ID")),
                    "record_key": _txt(row.get("record_key")),
                    "business_key": business_key(row),
                    "deleted_at": now_text(),
                    "source": "V196",
                    "reason": reason,
                }))
    for x in record_ids or []:
        rid = _to_int(x)
        if rid is not None and rid > 0:
            new_entries.append(_clean_entry({
                "id": rid,
                "identities": [f"id:{rid}"],
                "deleted_at": now_text(),
                "source": "V196",
                "reason": reason,
            }))
    merged = _dedupe_entries(current + new_entries)
    _write_local_entries(merged)
    _save_settings_entries(merged, github=github)
    _save_guard_records(merged, github=github)
    clear_cache()
    return merged


def _delete_from_sqlite(record_ids: list[int]) -> int:
    if not record_ids:
        return 0
    try:
        from services.db_service import DB_PATH, clear_query_cache
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        ph = ",".join(["?"] * len(record_ids))
        with sqlite3.connect(DB_PATH, timeout=8) as conn:
            cur = conn.execute(f"DELETE FROM time_records WHERE id IN ({ph})", tuple(record_ids))
            conn.commit()
            deleted = int(cur.rowcount or 0)
        try:
            clear_query_cache()
        except Exception:
            pass
        return deleted
    except Exception:
        return 0


def force_delete_time_records(record_ids: Iterable[Any], *, reason: str = "V196 hard delete", source_df: pd.DataFrame | None = None, github: bool = True) -> dict[str, Any]:
    ids = sorted({int(x) for x in (_to_int(v) for v in (record_ids or [])) if x is not None and x > 0})
    if not ids:
        return {"ok": False, "deleted_count": 0, "reason": "no_ids"}
    src = source_df.copy() if isinstance(source_df, pd.DataFrame) else pd.DataFrame()
    id_col = _id_col(src)
    if src is not None and not src.empty and id_col:
        deleted_rows = src.loc[src[id_col].map(_to_int).isin(set(ids))].copy()
    else:
        deleted_rows = pd.DataFrame()
    add_deleted_rows(deleted_rows, ids, reason=reason, github=github)
    sqlite_deleted = _delete_from_sqlite(ids)
    # Rewrite 01/02 authority without hard-deleted rows.
    written = 0
    try:
        from services.permanent_authority_service import df_from_table, table_from_df, update_tables
        frames = []
        for module in ("02_history", "01_time_records"):
            try:
                frames.append(df_from_table(module, "time_records"))
            except Exception:
                pass
        if isinstance(src, pd.DataFrame) and not src.empty:
            frames.append(src)
        merged = pd.concat([f for f in frames if isinstance(f, pd.DataFrame) and not f.empty], ignore_index=True) if frames else pd.DataFrame()
        remaining = filter_deleted_rows(merged)
        # De-duplicate by identities, preferring last occurrence.
        if not remaining.empty:
            by_key: dict[str, dict[str, Any]] = {}
            for _, rr in remaining.iterrows():
                row = dict(rr.to_dict())
                ids2 = sorted(identities_for_row(row))
                key = ids2[0] if ids2 else json.dumps(row, ensure_ascii=False, sort_keys=True)
                by_key[key] = row
            remaining = pd.DataFrame(list(by_key.values()))
        rows = table_from_df(remaining)
        for module in ("01_time_records", "02_history"):
            update_tables(module, {"time_records": rows}, reason="V196 hard delete rewrite 01/02", github=github)
        written = len(rows)
    except Exception:
        pass
    try:
        from services.log_service import write_log
        write_log(
            "DELETE_TIME_RECORDS_V196",
            f"{reason}：V196 reboot-proof hard delete；ids={ids}；sqlite_deleted={sqlite_deleted}；remaining={written}",
            "time_records",
            target_id=",".join(map(str, ids)),
            level="WARN",
        )
    except Exception:
        pass
    clear_cache()
    return {"ok": True, "deleted_count": len(ids), "sqlite_deleted": sqlite_deleted, "remaining": written, "ids": ids}


# V198 hard delete guard compatibility marker: supports 02 editor strict delete with bilingual columns.


# =================== V199 02-HISTORY DELETE SAME-LANE GUARD ===================
# Purpose:
# - 01 deletion already survives Reboot because it calls the latest delete_time_records lane.
# - 02 page still could call older delete_time_records_v178b_strict in some deployments.
# - This function is the single authority rewrite/delete guard for both 01 and 02.

def _v199_strip_ui_columns(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    drop_cols = [
        "刪除 / Delete", "重算 / Recalc", "刪除", "重算",
        "Delete", "Recalc", "_selected", "_delete", "_recalc",
    ]
    return df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore").copy()


def _v199_dedupe_df(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    by_key: dict[str, dict[str, Any]] = {}
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        ids = sorted(identities_for_row(row))
        key = ids[0] if ids else json.dumps(row, ensure_ascii=False, sort_keys=True)
        by_key[key] = row
    return pd.DataFrame(list(by_key.values())) if by_key else pd.DataFrame()


def _v199_authority_frames() -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    try:
        from services.permanent_authority_service import df_from_table
        for module in ("02_history", "01_time_records"):
            try:
                f = df_from_table(module, "time_records")
                if isinstance(f, pd.DataFrame) and not f.empty:
                    frames.append(_v199_strip_ui_columns(f))
            except Exception:
                pass
    except Exception:
        pass
    return frames


def force_delete_time_records_v199(record_ids: Iterable[Any], *, reason: str = "V199 hard delete", source_df: pd.DataFrame | None = None, github: bool = True) -> dict[str, Any]:
    """Hard delete one or more time records and make the delete survive Reboot App.

    Difference from older V178/V178B lanes:
    - Always writes durable hard-delete guard entries.
    - Rewrites 01_time_records and 02_history from authority frames only.
    - Uses source_df only as deletion evidence, never as the replacement authority table.
    - Strips editor-only checkbox columns before writing authority files.
    """
    ids = sorted({int(x) for x in (_to_int(v) for v in (record_ids or [])) if x is not None and x > 0})
    src = source_df.copy() if isinstance(source_df, pd.DataFrame) else pd.DataFrame()
    selected_rows = pd.DataFrame()
    if not src.empty:
        id_col = _id_col(src)
        if id_col and ids:
            selected_rows = src.loc[src[id_col].map(_to_int).isin(set(ids))].copy()
        elif id_col and not ids:
            # Allow callers that pass only selected rows as source_df.
            selected_rows = src.copy()
            ids = sorted({int(x) for x in (selected_rows[id_col].map(_to_int).tolist()) if x is not None and x > 0})
    if not ids and (selected_rows is None or selected_rows.empty):
        return {"ok": False, "deleted_count": 0, "reason": "no_ids_or_rows", "ids": []}

    add_deleted_rows(_v199_strip_ui_columns(selected_rows), ids, reason=reason, github=github)
    sqlite_deleted = _delete_from_sqlite(ids)

    written = 0
    before = 0
    try:
        from services.permanent_authority_service import table_from_df, update_tables
        frames = _v199_authority_frames()
        merged = pd.concat([f for f in frames if isinstance(f, pd.DataFrame) and not f.empty], ignore_index=True) if frames else pd.DataFrame()
        before = int(len(merged)) if isinstance(merged, pd.DataFrame) else 0
        remaining = filter_deleted_rows(_v199_strip_ui_columns(merged))
        remaining = _v199_dedupe_df(remaining)
        rows = table_from_df(remaining)
        for module in ("01_time_records", "02_history"):
            update_tables(module, {"time_records": rows}, reason="V199 hard delete rewrite 01/02", github=github)
        written = int(len(rows))
    except Exception:
        pass

    try:
        from services.log_service import write_log
        write_log(
            "DELETE_TIME_RECORDS_V199",
            f"{reason}：V199 01/02 same-lane reboot-proof hard delete；ids={ids}；sqlite_deleted={sqlite_deleted}；authority_before={before}；remaining={written}",
            "time_records",
            target_id=",".join(map(str, ids)),
            level="WARN",
        )
    except Exception:
        pass
    clear_cache()
    return {"ok": True, "deleted_count": int(len(ids)), "ids": ids, "sqlite_deleted": sqlite_deleted, "authority_before": before, "authority_remaining": written}

# =================== END V199 02-HISTORY DELETE SAME-LANE GUARD ===================
