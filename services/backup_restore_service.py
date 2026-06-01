# -*- coding: utf-8 -*-
"""V158 Backup / Restore Center service.

安全原則：
- 建立備份只讀取檔案，不修改正式資料。
- 還原只做「非破壞式缺漏補回」：只新增目前 01/02 缺少的 time_records，不刪除、不覆蓋現有列、不重新編號。
- 還原會尊重 02_history 的 deleted_record_ids / deleted_record_keys tombstone，避免已刪資料復活。
- GitHub 上傳交由 existing permanent_authority_service / backup queue 處理；本服務不在高頻作業路徑執行。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
PERMANENT_ROOT = DATA_ROOT / "permanent_store"
BACKUP_DIR = PERMANENT_ROOT / "_backups" / "v158"
MANIFEST_NAME = "V158_BACKUP_MANIFEST.json"


def _now_text() -> str:
    try:
        from services.timezone_service import now_text  # type: ignore
        return str(now_text())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _safe_json_default(value: Any) -> Any:
    try:
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (datetime,)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _load_json_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        return _load_json_text(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _table_rows_from_payload(payload: dict[str, Any], table: str = "time_records") -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables")
    if isinstance(tables, dict) and isinstance(tables.get(table), list):
        return [dict(r) for r in tables.get(table, []) if isinstance(r, dict)]
    records = payload.get("records")
    if isinstance(records, dict) and isinstance(records.get(table), list):
        return [dict(r) for r in records.get(table, []) if isinstance(r, dict)]
    if isinstance(records, list):
        return [dict(r) for r in records if isinstance(r, dict)]
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [dict(r) for r in rows if isinstance(r, dict)]
    return []


def _clean_str(value: Any) -> str:
    try:
        if value is None:
            return ""
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _to_int(value: Any) -> int | None:
    s = _clean_str(value)
    if not s:
        return None
    try:
        n = int(float(s))
        return n if n > 0 else None
    except Exception:
        return None


def _row_record_key(row: dict[str, Any]) -> str:
    for c in ("record_key", "紀錄鍵 / Record Key"):
        v = _clean_str(row.get(c))
        if v:
            return v
    return ""


def _row_business_key(row: dict[str, Any]) -> str:
    emp = _clean_str(row.get("employee_id") or row.get("工號 / Employee ID") or row.get("工號") or row.get("Employee ID"))
    name = _clean_str(row.get("employee_name") or row.get("姓名 / Name") or row.get("姓名") or row.get("Name"))
    wo = _clean_str(row.get("work_order") or row.get("製令 / Work Order") or row.get("製令") or row.get("Work Order"))
    proc = _clean_str(row.get("process_name") or row.get("工段 / Process") or row.get("製程") or row.get("Process"))
    start = _clean_str(row.get("start_timestamp") or row.get("開始時間戳 / Start Timestamp") or row.get("開始時間") or row.get("Start Timestamp"))
    if emp and wo and proc and start:
        return f"biz:{emp}|{name}|{wo}|{proc}|{start}"
    return ""


def _row_identity_key(row: dict[str, Any]) -> str:
    rk = _row_record_key(row)
    if rk:
        return f"rk:{rk}"
    bk = _row_business_key(row)
    if bk:
        return bk
    rid = _to_int(row.get("id") or row.get("ID") or row.get("ID / ID"))
    if rid is not None:
        return f"id:{rid}"
    # Last fallback is intentionally row hash, so ambiguous rows do not overwrite each other.
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=_safe_json_default)
    return "hash:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _settings_deleted_sets() -> tuple[set[int], set[str]]:
    settings_path = PERMANENT_ROOT / "modules" / "02_history" / "settings.json"
    payload = _read_json_file(settings_path)
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
    ids: set[int] = set()
    keys: set[str] = set()
    for x in settings.get("deleted_record_ids", []) if isinstance(settings, dict) else []:
        n = _to_int(x)
        if n is not None:
            ids.add(n)
    for x in settings.get("deleted_record_keys", []) if isinstance(settings, dict) else []:
        s = _clean_str(x)
        if s:
            keys.add(s)
    return ids, keys


def _is_tombstoned(row: dict[str, Any], deleted_ids: set[int], deleted_keys: set[str]) -> bool:
    rk = _row_record_key(row)
    if rk and rk in deleted_keys:
        return True
    # ID tombstone only applies to rows without record_key to avoid SQLite id reuse killing new rows.
    if not rk:
        rid = _to_int(row.get("id") or row.get("ID") or row.get("ID / ID"))
        return bool(rid is not None and rid in deleted_ids)
    return False


def _zip_add_file(zf: zipfile.ZipFile, path: Path, arcname: str, files_meta: list[dict[str, Any]]) -> None:
    try:
        data = path.read_bytes()
    except Exception:
        return
    zf.writestr(arcname, data)
    files_meta.append({
        "path": arcname,
        "size": len(data),
        "sha256": _sha256_bytes(data),
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    })


def _iter_backup_source_files() -> list[Path]:
    roots = [
        PERMANENT_ROOT / "modules",
        PERMANENT_ROOT / "system",
        PERMANENT_ROOT / "config",
        PERMANENT_ROOT / "persistent_state",
        PERMANENT_ROOT / "persistent_modules",
        PERMANENT_ROOT / "database",
        DATA_ROOT / "database",
    ]
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            out.append(root)
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            # Avoid recursive backup ZIPs and temporary files.
            parts = {x.lower() for x in p.parts}
            if "_backups" in parts or p.name.endswith(".tmp") or p.name.startswith("~$"):
                continue
            out.append(p)
    return sorted(set(out))


def create_full_backup_snapshot(reason: str = "manual_v158_backup", *, save_to_disk: bool = True) -> dict[str, Any]:
    """Create a complete backup ZIP of permanent data and database snapshots."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files_meta: list[dict[str, Any]] = []
    zip_buffer = io.BytesIO()
    created_at = _now_text()
    file_name = f"SPT_V158_full_backup_{_stamp()}.zip"

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in _iter_backup_source_files():
            try:
                arc = path.relative_to(PROJECT_ROOT).as_posix()
            except Exception:
                arc = path.name
            _zip_add_file(zf, path, arc, files_meta)
        manifest = {
            "schema": "SPT-V158-FullBackup",
            "created_at": created_at,
            "reason": reason,
            "project_root_name": PROJECT_ROOT.name,
            "file_count": len(files_meta),
            "files": files_meta,
            "notes": "Full backup for SPT time tracking permanent data. Restore uses non-destructive merge by default.",
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, default=_safe_json_default).encode("utf-8"))

    data = zip_buffer.getvalue()
    sha = _sha256_bytes(data)
    saved_path = None
    if save_to_disk:
        saved_path = BACKUP_DIR / file_name
        saved_path.write_bytes(data)
        # Sidecar manifest helps list backups without opening every ZIP.
        sidecar = saved_path.with_suffix(".json")
        sidecar.write_text(json.dumps({
            "schema": "SPT-V158-BackupSidecar",
            "created_at": created_at,
            "reason": reason,
            "file_name": file_name,
            "size": len(data),
            "sha256": sha,
            "file_count": len(files_meta),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "file_name": file_name,
        "created_at": created_at,
        "reason": reason,
        "size": len(data),
        "sha256": sha,
        "file_count": len(files_meta),
        "zip_bytes": data,
        "saved_path": str(saved_path) if saved_path else "",
    }


def list_backup_snapshots(limit: int = 20) -> list[dict[str, Any]]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for p in sorted(BACKUP_DIR.glob("SPT_V158_full_backup_*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        info = {
            "file_name": p.name,
            "path": str(p),
            "size": p.stat().st_size,
            "modified_at": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "sha256": "",
            "file_count": "",
        }
        sidecar = p.with_suffix(".json")
        if sidecar.exists():
            s = _read_json_file(sidecar)
            info.update({k: s.get(k, info.get(k, "")) for k in ("created_at", "reason", "sha256", "file_count")})
        rows.append(info)
        if len(rows) >= int(limit or 20):
            break
    return rows


def inspect_backup_zip_bytes(data: bytes) -> dict[str, Any]:
    if not data:
        return {"ok": False, "reason": "empty_file"}
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            names = zf.namelist()
            manifest = {}
            if MANIFEST_NAME in names:
                manifest = _load_json_text(zf.read(MANIFEST_NAME).decode("utf-8", errors="replace"))
            module_records = [n for n in names if n.startswith("data/permanent_store/modules/") and n.endswith("records.json")]
            db_files = [n for n in names if n.endswith(".db") or n.endswith(".sqlite")]
            event_files = [n for n in names if "/time_record_events/" in n and n.endswith(".json")]
            row_shards = [n for n in names if "/time_record_rows/" in n and n.endswith(".json")]
            return {
                "ok": True,
                "schema": manifest.get("schema", "unknown"),
                "created_at": manifest.get("created_at", ""),
                "reason": manifest.get("reason", ""),
                "file_count": len(names),
                "zip_size": len(data),
                "sha256": _sha256_bytes(data),
                "module_records_count": len(module_records),
                "database_files_count": len(db_files),
                "time_record_event_files_count": len(event_files),
                "time_record_row_shards_count": len(row_shards),
                "has_01_time_records": "data/permanent_store/modules/01_time_records/records.json" in names,
                "has_02_history": "data/permanent_store/modules/02_history/records.json" in names,
                "has_06_logs": "data/permanent_store/modules/06_logs/records.json" in names,
                "has_10_permissions": "data/permanent_store/modules/10_permissions/records.json" in names,
            }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _extract_time_rows_from_backup_zip(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not data:
        return rows
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                use = False
                if name in (
                    "data/permanent_store/modules/01_time_records/records.json",
                    "data/permanent_store/modules/02_history/records.json",
                ):
                    use = True
                elif "/time_record_rows/" in name:
                    use = True
                elif "/time_record_events/" in name:
                    # event journal is audit evidence; rows are only used if they have an embedded time_record row.
                    use = True
                if not use:
                    continue
                payload = _load_json_text(zf.read(name).decode("utf-8", errors="replace"))
                if not payload:
                    continue
                if "/time_record_events/" in name:
                    event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
                    for key in ("time_record", "record", "row", "after", "data"):
                        if isinstance(event_payload.get(key), dict):
                            rows.append(dict(event_payload[key]))
                            break
                    continue
                # Normal authority payload or shard row.
                extracted = _table_rows_from_payload(payload, "time_records")
                if extracted:
                    rows.extend(extracted)
                elif any(k in payload for k in ("record_key", "employee_id", "work_order", "process_name", "start_timestamp")):
                    rows.append(dict(payload))
    except Exception:
        pass
    # Deduplicate backup rows by robust identity.
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict) or not r:
            continue
        k = _row_identity_key(r)
        old = out.get(k)
        if old is None:
            out[k] = dict(r)
        else:
            # Prefer rows with terminal status/end time if duplicate exists.
            score_old = 1 if _clean_str(old.get("end_timestamp")) or _clean_str(old.get("end_action")) else 0
            score_new = 1 if _clean_str(r.get("end_timestamp")) or _clean_str(r.get("end_action")) else 0
            if score_new >= score_old:
                out[k] = dict(r)
    return list(out.values())


def _current_time_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Prefer the current authoritative files.
    for module_key in ("02_history", "01_time_records"):
        p = PERMANENT_ROOT / "modules" / module_key / "records.json"
        rows.extend(_table_rows_from_payload(_read_json_file(p), "time_records"))
    # Include SQLite runtime cache as another current source.
    try:
        db_candidates = [DATA_ROOT / "database" / "spt_time_tracking.db", PERMANENT_ROOT / "database" / "spt_time_tracking.db"]
        db_path = next((x for x in db_candidates if x.exists()), None)
        if db_path:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                for r in conn.execute("SELECT * FROM time_records").fetchall():
                    rows.append(dict(r))
            finally:
                conn.close()
    except Exception:
        pass
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if isinstance(r, dict) and r:
            out[_row_identity_key(r)] = r
    return list(out.values())


def _save_time_rows_to_authority(rows: list[dict[str, Any]], reason: str, github: bool) -> int:
    try:
        from services.permanent_authority_service import save_authority, table_from_df  # type: ignore
        if pd is not None:
            safe_rows = table_from_df(pd.DataFrame(rows))
        else:
            safe_rows = rows
        save_authority("01_time_records", records={"time_records": safe_rows}, reason=f"{reason}_01", github=bool(github))
        save_authority("02_history", records={"time_records": safe_rows}, reason=f"{reason}_02", github=bool(github))
        return len(safe_rows)
    except Exception:
        # Last resort direct write; still non-destructive from already merged rows.
        payload = {
            "authority_schema": "SPT-PermanentAuthority-V158-RestoreFallback",
            "module_key": "02_history",
            "kind": "records",
            "updated_at": _now_text(),
            "reason": reason,
            "tables": {"time_records": rows},
            "table_counts": {"time_records": len(rows)},
        }
        for module_key in ("01_time_records", "02_history"):
            p = PERMANENT_ROOT / "modules" / module_key / "records.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            x = dict(payload)
            x["module_key"] = module_key
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(x, ensure_ascii=False, indent=2, default=_safe_json_default), encoding="utf-8")
            os.replace(tmp, p)
        return len(rows)


def _insert_missing_rows_to_sqlite_cache(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    try:
        from services.db_service import DB_PATH as runtime_db_path, ensure_database  # type: ignore
        ensure_database()
        db_path = Path(runtime_db_path)
    except Exception:
        db_path = DATA_ROOT / "database" / "spt_time_tracking.db"
    if not db_path.exists():
        return 0
    inserted = 0
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            cols_info = conn.execute("PRAGMA table_info(time_records)").fetchall()
            cols = [str(r[1]) for r in cols_info]
            if not cols:
                return 0
            for row in rows:
                rk = _row_record_key(row)
                rid = _to_int(row.get("id"))
                exists = None
                if rk:
                    exists = conn.execute("SELECT id FROM time_records WHERE record_key=? LIMIT 1", (rk,)).fetchone()
                if exists is None and rid is not None:
                    exists = conn.execute("SELECT id FROM time_records WHERE id=? LIMIT 1", (rid,)).fetchone()
                if exists:
                    continue
                insert_cols = [c for c in cols if c in row]
                if not insert_cols:
                    continue
                ph = ",".join(["?"] * len(insert_cols))
                qcols = ",".join([f'"{c}"' for c in insert_cols])
                vals = [row.get(c) for c in insert_cols]
                conn.execute(f"INSERT OR IGNORE INTO time_records ({qcols}) VALUES ({ph})", vals)
                inserted += 1
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return inserted
    return inserted


def restore_missing_time_records_from_backup(data: bytes, *, dry_run: bool = True, github: bool = True, reason: str = "v158_restore_missing") -> dict[str, Any]:
    """Non-destructively restore missing time_records from a V158 backup ZIP.

    Existing rows are not overwritten. Tombstoned/deleted rows are not restored.
    """
    inspect = inspect_backup_zip_bytes(data)
    if not inspect.get("ok"):
        return {"ok": False, "reason": inspect.get("reason", "invalid_backup"), "inspect": inspect}

    backup_rows = _extract_time_rows_from_backup_zip(data)
    current_rows = _current_time_rows()
    deleted_ids, deleted_keys = _settings_deleted_sets()

    current_by_key = {_row_identity_key(r): r for r in current_rows if isinstance(r, dict)}
    missing: list[dict[str, Any]] = []
    skipped_deleted = 0
    skipped_existing = 0
    for row in backup_rows:
        if _is_tombstoned(row, deleted_ids, deleted_keys):
            skipped_deleted += 1
            continue
        k = _row_identity_key(row)
        if k in current_by_key:
            skipped_existing += 1
            continue
        missing.append(row)

    merged = list(current_by_key.values()) + missing
    # Sort by start timestamp/id for stable output.
    def _sort_key(r: dict[str, Any]) -> tuple[str, int]:
        return (_clean_str(r.get("start_timestamp") or r.get("created_at")), _to_int(r.get("id")) or 0)
    merged = sorted(merged, key=_sort_key)

    result = {
        "ok": True,
        "dry_run": bool(dry_run),
        "backup_total_rows": len(backup_rows),
        "current_total_rows": len(current_rows),
        "missing_rows": len(missing),
        "skipped_existing": skipped_existing,
        "skipped_deleted_tombstone": skipped_deleted,
        "merged_total_rows": len(merged),
        "sqlite_inserted": 0,
        "saved_authority_rows": 0,
        "sample_missing": missing[:20],
        "inspect": inspect,
    }
    if dry_run or not missing:
        return result

    saved = _save_time_rows_to_authority(merged, reason=reason, github=bool(github))
    sqlite_inserted = _insert_missing_rows_to_sqlite_cache(missing)
    result["saved_authority_rows"] = saved
    result["sqlite_inserted"] = sqlite_inserted
    return result


def backup_manifest_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(summary, dict):
        return []
    keys = [
        "ok", "schema", "created_at", "reason", "file_count", "zip_size", "sha256",
        "module_records_count", "database_files_count", "time_record_event_files_count",
        "time_record_row_shards_count", "has_01_time_records", "has_02_history", "has_06_logs", "has_10_permissions",
    ]
    return [{"項目 / Item": k, "值 / Value": summary.get(k, "")} for k in keys]


if __name__ == "__main__":
    snap = create_full_backup_snapshot(reason="cli_v158_backup", save_to_disk=True)
    print(json.dumps({k: v for k, v in snap.items() if k != "zip_bytes"}, ensure_ascii=False, indent=2))
