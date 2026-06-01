# -*- coding: utf-8 -*-
"""V180 Emergency fast delete service for SPT time records.

Purpose:
- Delete 01/02 time records without waiting for Streamlit rendering, GitHub, full rebuild,
  event-journal replay, or row-shard recovery.
- Create tombstones so deleted rows do not reappear from SQLite / LOGRECOVERY / event journal / row shard.
- Keep this service local-first and deterministic.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"
SYSTEM_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "system"
BACKUP_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "_backups" / "v180_delete"
DB_CANDIDATES = [
    PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db",
    PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db",
]

ID_FIELDS = ["id", "ID", "ID / ID", "ID / ID / ID"]
KEY_FIELDS = ["record_key", "紀錄鍵 / Record Key", "record_key / Record Key"]
EMP_FIELDS = ["employee_id", "工號", "工號 / Employee ID", "employee_id / Employee ID"]
NAME_FIELDS = ["employee_name", "姓名", "姓名 / Name", "employee_name / Name"]
WO_FIELDS = ["work_order", "製令", "製令 / Work Order", "work_order / Work Order"]
PROC_FIELDS = ["process_name", "工段", "工段 / Process", "process_name / Process"]
START_FIELDS = ["start_timestamp", "開始時間", "開始時間 / Start Timestamp", "start_timestamp / Start Timestamp"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _json_default(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _write_json_atomic(path: Path, data: Any, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        try:
            bdir = BACKUP_ROOT / str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "__")
            bdir.mkdir(parents=True, exist_ok=True)
            bpath = bdir / f"{path.stem}_{_stamp()}{path.suffix}"
            bpath.write_bytes(path.read_bytes())
        except Exception:
            pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


def _canonical_path(module_key: str) -> Path:
    return AUTH_ROOT / module_key / "records.json"


def _settings_path(module_key: str) -> Path:
    return AUTH_ROOT / module_key / "settings.json"


def _get(row: dict[str, Any], fields: Iterable[str]) -> Any:
    for f in fields:
        if f in row and row.get(f) not in (None, "", "nan", "NaN"):
            return row.get(f)
    return ""


def _safe_int(v: Any) -> int | None:
    try:
        if v is None or str(v).strip() == "":
            return None
        return int(float(str(v).strip()))
    except Exception:
        return None


def _business_key(row: dict[str, Any]) -> str:
    parts = [
        str(_get(row, EMP_FIELDS)).strip(),
        str(_get(row, NAME_FIELDS)).strip(),
        str(_get(row, WO_FIELDS)).strip(),
        str(_get(row, PROC_FIELDS)).strip(),
        str(_get(row, START_FIELDS)).strip(),
    ]
    return "|".join(parts)


def _load_rows(module_key: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _canonical_path(module_key)
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    tables = data.setdefault("tables", {})
    rows = tables.get("time_records", [])
    if not isinstance(rows, list):
        rows = []
    rows = [dict(r) for r in rows if isinstance(r, dict)]
    return data, rows


def _save_rows(module_key: str, data: dict[str, Any], rows: list[dict[str, Any]], reason: str) -> None:
    data = dict(data or {})
    data.setdefault("authority_schema", "SPT-PermanentAuthority-V29")
    data["module_key"] = module_key
    data["kind"] = "records"
    data["updated_at"] = _now()
    data["exported_at"] = _now()
    data["reason"] = reason
    data["empty_authoritative"] = False
    data.setdefault("tables", {})
    data["tables"]["time_records"] = rows
    data.setdefault("settings", {})
    data["table_counts"] = {"time_records": len(rows)}
    _write_json_atomic(_canonical_path(module_key), data, backup=True)


def _load_settings(module_key: str) -> dict[str, Any]:
    path = _settings_path(module_key)
    data = _read_json(path, {})
    if isinstance(data, dict) and isinstance(data.get("settings"), dict):
        return dict(data["settings"])
    if isinstance(data, dict):
        return dict(data)
    return {}


def _save_settings(module_key: str, settings: dict[str, Any]) -> None:
    path = _settings_path(module_key)
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or "settings" not in payload:
        payload = {"schema_version": "V180", "created_at": _now(), "settings": {}}
    payload["updated_at"] = _now()
    payload["settings"] = settings
    _write_json_atomic(path, payload, backup=True)


def _add_tombstones(rows: list[dict[str, Any]], ids: set[int], record_keys: set[str], business_keys: set[str]) -> None:
    for r in rows:
        rid = _safe_int(_get(r, ID_FIELDS))
        if rid is not None:
            ids.add(rid)
        rk = str(_get(r, KEY_FIELDS)).strip()
        if rk:
            record_keys.add(rk)
        bk = _business_key(r).strip("|")
        if bk and bk.count("|") >= 4:
            business_keys.add(bk)
    for module in ("01_time_records", "02_history"):
        stg = _load_settings(module)
        cur_ids = set(_safe_int(x) for x in stg.get("deleted_record_ids", []) if _safe_int(x) is not None)
        cur_keys = set(str(x).strip() for x in stg.get("deleted_record_keys", []) if str(x).strip())
        cur_biz = set(str(x).strip() for x in stg.get("deleted_record_business_keys", []) if str(x).strip())
        stg["deleted_record_ids"] = sorted(cur_ids | ids)
        stg["deleted_record_keys"] = sorted(cur_keys | record_keys)
        stg["deleted_record_business_keys"] = sorted(cur_biz | business_keys)
        stg["delete_tombstone_updated_at"] = _now()
        stg["delete_tombstone_version"] = "V180"
        _save_settings(module, stg)


def _row_matches(row: dict[str, Any], ids: set[int], record_keys: set[str], business_keys: set[str]) -> bool:
    rid = _safe_int(_get(row, ID_FIELDS))
    if rid is not None and rid in ids:
        return True
    rk = str(_get(row, KEY_FIELDS)).strip()
    if rk and rk in record_keys:
        return True
    bk = _business_key(row)
    if bk and bk in business_keys:
        return True
    return False


def _delete_from_authority(module_key: str, ids: set[int], record_keys: set[str], business_keys: set[str]) -> tuple[int, list[dict[str, Any]]]:
    data, rows = _load_rows(module_key)
    deleted_rows: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for r in rows:
        if _row_matches(r, ids, record_keys, business_keys):
            deleted_rows.append(r)
        else:
            kept.append(r)
    if deleted_rows:
        _save_rows(module_key, data, kept, reason="V180_EMERGENCY_LOCAL_DELETE")
    return len(deleted_rows), deleted_rows


def _delete_from_sqlite(ids: set[int], record_keys: set[str], business_keys: set[str]) -> int:
    deleted = 0
    for db in DB_CANDIDATES:
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(str(db), timeout=2)
            con.execute("PRAGMA busy_timeout=2000")
            cur = con.cursor()
            clauses: list[str] = []
            params: list[Any] = []
            if ids:
                ph = ",".join(["?"] * len(ids))
                clauses.append(f"id IN ({ph})")
                params.extend(sorted(ids))
            if record_keys:
                ph = ",".join(["?"] * len(record_keys))
                clauses.append(f"record_key IN ({ph})")
                params.extend(sorted(record_keys))
            # Business keys are slower but only used for selected rows / recovery rows.
            for bk in sorted(business_keys):
                parts = bk.split("|")
                if len(parts) >= 5:
                    clauses.append("(COALESCE(employee_id,'')=? AND COALESCE(employee_name,'')=? AND COALESCE(work_order,'')=? AND COALESCE(process_name,'')=? AND COALESCE(start_timestamp,'')=?)")
                    params.extend(parts[:5])
            if clauses:
                cur.execute("DELETE FROM time_records WHERE " + " OR ".join(clauses), params)
                deleted += max(int(cur.rowcount or 0), 0)
            con.commit()
            con.close()
        except Exception:
            try:
                con.close()  # type: ignore[name-defined]
            except Exception:
                pass
    return deleted


def _append_delete_audit(result: dict[str, Any]) -> None:
    try:
        SYSTEM_ROOT.mkdir(parents=True, exist_ok=True)
        path = SYSTEM_ROOT / "v180_delete_audit.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, default=_json_default) + "\n")
    except Exception:
        pass


def force_delete_time_records(
    record_ids: Iterable[Any] | None = None,
    record_keys: Iterable[Any] | None = None,
    business_keys: Iterable[Any] | None = None,
    reason: str = "V180 emergency force delete",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete time records from 01/02 authority + SQLite with tombstone.

    This function is intentionally local-first: no GitHub upload, no full replay,
    no UI rendering dependency. It is suitable when Streamlit delete spins forever.
    """
    t0 = time.perf_counter()
    ids = set(_safe_int(x) for x in (record_ids or []) if _safe_int(x) is not None)
    keys = set(str(x).strip() for x in (record_keys or []) if str(x).strip())
    biz = set(str(x).strip() for x in (business_keys or []) if str(x).strip())
    if not ids and not keys and not biz:
        return {"ok": False, "message": "No delete keys provided", "deleted": 0, "elapsed_ms": 0}

    # Expand ids/keys/business keys from current authority rows before delete.
    matched_rows: list[dict[str, Any]] = []
    for module in ("02_history", "01_time_records"):
        _, rows = _load_rows(module)
        matched_rows.extend([r for r in rows if _row_matches(r, ids, keys, biz)])
    _add_tombstones(matched_rows, ids, keys, biz)

    if dry_run:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return {"ok": True, "dry_run": True, "matched_rows": len(matched_rows), "deleted": 0, "elapsed_ms": elapsed}

    d02, rows02 = _delete_from_authority("02_history", ids, keys, biz)
    d01, rows01 = _delete_from_authority("01_time_records", ids, keys, biz)
    dsql = _delete_from_sqlite(ids, keys, biz)
    # Re-add tombstones after actual deletion using deleted rows too.
    _add_tombstones(rows02 + rows01 + matched_rows, ids, keys, biz)

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    result = {
        "ok": True,
        "dry_run": False,
        "reason": reason,
        "input_ids": sorted(ids),
        "input_record_keys": sorted(keys),
        "input_business_keys": sorted(biz),
        "deleted_02_history": d02,
        "deleted_01_time_records": d01,
        "deleted_sqlite": dsql,
        "matched_rows": len(matched_rows),
        "deleted": max(d01, d02, dsql, len(matched_rows)),
        "elapsed_ms": elapsed,
        "timestamp": _now(),
    }
    _append_delete_audit(result)
    return result


def delete_time_records_fast_local(record_ids: Iterable[Any], reason: str = "V180 fast local delete") -> int:
    result = force_delete_time_records(record_ids=record_ids, reason=reason, dry_run=False)
    return int(result.get("deleted") or 0)
