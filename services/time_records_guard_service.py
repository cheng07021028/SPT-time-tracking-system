# -*- coding: utf-8 -*-
"""SPT Time Tracking V3.02 - 01/02 time records persistence guard.

Purpose
-------
Protect the shared ``time_records`` source used by:
- 01｜工時紀錄
- 02｜歷史紀錄

This service is intentionally conservative:
- It never deletes user data.
- It restores only when the SQLite ``time_records`` table is empty or missing.
- It searches canonical, legacy, local backup, and external backup locations.
- It blocks empty exports from overwriting non-empty time-record backups.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "database" / "spt_time_tracking.db"
PERSIST_ROOT = DATA_DIR / "persistent_modules"
STATE_DIR = DATA_DIR / "persistent_state"
CORRUPT_DIR = DATA_DIR / "_persistent_corrupt"
RESTORE_LOG = STATE_DIR / "time_records_guard_log.jsonl"
CANONICAL_01 = "01_time_records"
LEGACY_01 = "01_time_record"
HISTORY_02 = "02_history"
TIME_RECORD_MODULE_CODES = (CANONICAL_01, LEGACY_01, HISTORY_02)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_time_module_code(module_code: str | None) -> str:
    code = str(module_code or "").strip()
    if code == LEGACY_01:
        return CANONICAL_01
    return code


def _log(action: str, detail: dict[str, Any] | None = None) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"time": now_text(), "action": action, "detail": detail or {}}
        with RESTORE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _safe_load_json(path: Path) -> Any | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        try:
            CORRUPT_DIR.mkdir(parents=True, exist_ok=True)
            target = CORRUPT_DIR / f"{path.name}.{now_stamp()}.corrupt"
            shutil.copy2(path, target)
            _log("CORRUPT_JSON_ARCHIVED", {"path": str(path), "archive": str(target), "error": str(exc)})
        except Exception:
            pass
        return None


def _extract_time_records(payload: Any) -> list[dict[str, Any]]:
    """Extract time_records list from supported backup payload formats."""
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables")
    if isinstance(tables, dict):
        val = tables.get("time_records")
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict) and isinstance(val.get("records"), list):
            return [r for r in val.get("records", []) if isinstance(r, dict)]
    # Some tools may save direct records list.
    for key in ("time_records", "records", "data"):
        val = payload.get(key)
        if isinstance(val, list):
            rows = [r for r in val if isinstance(r, dict)]
            # Only accept direct records if they look like time records.
            if rows and any(("work_order" in r or "employee_id" in r or "start_timestamp" in r) for r in rows[:5]):
                return rows
    return []


def _module_records_candidates() -> list[Path]:
    candidates: list[Path] = []
    for code in TIME_RECORD_MODULE_CODES:
        module_dir = PERSIST_ROOT / normalize_time_module_code(code)
        # canonical latest file
        latest = module_dir / f"{normalize_time_module_code(code)}_records.json"
        candidates.append(latest)
        # legacy latest file can exist under legacy folder/name
        legacy_latest = PERSIST_ROOT / code / f"{code}_records.json"
        candidates.append(legacy_latest)
        # all history files
        for base in {module_dir / "history", PERSIST_ROOT / code / "history"}:
            if base.exists():
                candidates.extend(sorted(base.glob("*_records_*.json"), key=lambda p: p.stat().st_mtime, reverse=True))
    return _dedupe_existing(candidates)


def _persistent_state_candidates() -> list[Path]:
    candidates: list[Path] = []
    for p in [
        STATE_DIR / "spt_permanent_state.json",
        DATA_DIR / "persistent_backups" / "latest_backup_manifest.json",
    ]:
        if p.exists():
            candidates.append(p)
    for folder in [STATE_DIR / "history", STATE_DIR / "archive", DATA_DIR / "persistent_backups", DATA_DIR / "_persistent_backup"]:
        if not folder.exists():
            continue
        candidates.extend(sorted(folder.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True))
    return _dedupe_existing(candidates)


def _load_auto_backup_config() -> dict[str, Any]:
    for path in [
        DATA_DIR / "config" / "auto_backup_settings.json",
        DATA_DIR / "config" / "daily_external_backup_settings.json",
        STATE_DIR / "auto_backup_settings.json",
    ]:
        payload = _safe_load_json(path)
        if isinstance(payload, dict):
            return payload
    return {}


def _external_backup_candidates() -> list[Path]:
    candidates: list[Path] = []
    cfg = _load_auto_backup_config()
    raw_paths = []
    for key in ("target_dir", "backup_dir", "backup_root", "external_backup_dir", "target_folder"):
        if cfg.get(key):
            raw_paths.append(str(cfg.get(key)))
    for raw in raw_paths:
        try:
            base = Path(raw).expanduser()
            if not base.exists():
                continue
            candidates.extend(sorted(base.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True))
            # DB copies in external backups are also useful.
            candidates.extend(sorted(base.rglob("spt_time_tracking.db"), key=lambda p: p.stat().st_mtime, reverse=True))
        except Exception:
            continue
    return _dedupe_existing(candidates)


def _dedupe_existing(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        try:
            pp = Path(p)
            if not pp.exists() or not pp.is_file():
                continue
            key = str(pp.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(pp)
        except Exception:
            continue
    return out


@dataclass
class TimeRecordBackupCandidate:
    path: Path
    row_count: int
    source_type: str
    rows: list[dict[str, Any]]


def find_time_record_backup_candidates(include_external: bool = True) -> list[TimeRecordBackupCandidate]:
    candidates: list[TimeRecordBackupCandidate] = []
    paths = _module_records_candidates() + _persistent_state_candidates()
    if include_external:
        paths += _external_backup_candidates()
    for path in _dedupe_existing(paths):
        # SQLite backup DB candidate
        if path.name == "spt_time_tracking.db":
            rows = _read_time_records_from_db(path)
            if rows:
                candidates.append(TimeRecordBackupCandidate(path=path, row_count=len(rows), source_type="sqlite_backup", rows=rows))
            continue
        payload = _safe_load_json(path)
        rows = _extract_time_records(payload)
        if rows:
            source = "module_records" if "persistent_modules" in str(path) else "json_backup"
            candidates.append(TimeRecordBackupCandidate(path=path, row_count=len(rows), source_type=source, rows=rows))
    candidates.sort(key=lambda c: (c.row_count, c.path.stat().st_mtime if c.path.exists() else 0), reverse=True)
    return candidates


def _read_time_records_from_db(db_path: Path) -> list[dict[str, Any]]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='time_records'").fetchone()
            if not exists:
                return []
            return [dict(r) for r in conn.execute('SELECT * FROM time_records').fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def time_records_count(db_path: Path = DB_PATH) -> int:
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            if not _table_exists(conn, "time_records"):
                return 0
            return int(conn.execute("SELECT COUNT(*) FROM time_records").fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return 0


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except Exception:
        return []


def _insert_time_records(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    cols = _table_columns(conn, "time_records")
    if not cols:
        return 0
    # Keep id only when DB is empty; otherwise id conflicts may break restore. This function
    # is only called for empty table, so id is safe if present and valid.
    inserted = 0
    for row in rows:
        clean = {c: row.get(c) for c in cols if c in row}
        if not clean:
            continue
        columns = list(clean.keys())
        placeholders = ",".join(["?"] * len(columns))
        quoted = ",".join([f'"{c}"' for c in columns])
        values = [clean[c] for c in columns]
        try:
            conn.execute(f'INSERT OR IGNORE INTO time_records ({quoted}) VALUES ({placeholders})', values)
            inserted += 1
        except Exception:
            # Retry without id when a saved id conflicts or type is invalid.
            if "id" in clean:
                clean.pop("id", None)
                columns = list(clean.keys())
                if columns:
                    quoted = ",".join([f'"{c}"' for c in columns])
                    placeholders = ",".join(["?"] * len(columns))
                    values = [clean[c] for c in columns]
                    try:
                        conn.execute(f'INSERT OR IGNORE INTO time_records ({quoted}) VALUES ({placeholders})', values)
                        inserted += 1
                    except Exception:
                        pass
    return inserted


def rescue_time_records_if_empty(trigger: str = "manual", include_external: bool = True) -> dict[str, Any]:
    """Restore shared 01/02 time_records from backups only when DB table is empty."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if time_records_count(DB_PATH) > 0:
        return {"ok": True, "skipped": True, "reason": "time_records already has data", "count": time_records_count(DB_PATH)}

    candidates = find_time_record_backup_candidates(include_external=include_external)
    if not candidates:
        _log("RESCUE_NO_CANDIDATE", {"trigger": trigger})
        return {"ok": False, "skipped": True, "reason": "no non-empty time_records backup found"}

    best = candidates[0]
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            if not _table_exists(conn, "time_records"):
                return {"ok": False, "reason": "time_records table does not exist yet", "candidate": str(best.path)}
            inserted = _insert_time_records(conn, best.rows)
            conn.commit()
        finally:
            conn.close()
        _log("RESCUE_TIME_RECORDS_RESTORED", {"trigger": trigger, "source": str(best.path), "source_type": best.source_type, "rows": best.row_count, "inserted": inserted})
        mirror_time_records_to_module_files(best.rows, reason=f"rescue:{trigger}")
        return {"ok": True, "restored": True, "inserted": inserted, "source": str(best.path), "source_type": best.source_type, "source_rows": best.row_count}
    except Exception as exc:
        _log("RESCUE_FAILED", {"trigger": trigger, "source": str(best.path), "error": str(exc)})
        return {"ok": False, "reason": str(exc), "source": str(best.path)}


def has_nonempty_time_record_backup(include_external: bool = True) -> bool:
    return bool(find_time_record_backup_candidates(include_external=include_external))


def should_block_empty_time_record_export(module_code: str | None = None) -> bool:
    """Return True if DB time_records is empty while non-empty backups exist."""
    code = normalize_time_module_code(module_code)
    if code not in {CANONICAL_01, HISTORY_02, "05_analysis", "07_missing", "07_missing_today", "08_daily_hours", ""}:
        return False
    return time_records_count(DB_PATH) == 0 and has_nonempty_time_record_backup(include_external=True)


def _atomic_save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # Verify tmp before replace.
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def mirror_time_records_to_module_files(rows: list[dict[str, Any]], reason: str = "manual") -> dict[str, Any]:
    """Keep 01 and 02 module JSON files mutually protective."""
    if not rows:
        return {"ok": False, "skipped": True, "reason": "no rows"}
    payload_common = {
        "schema_version": "3.02",
        "exported_at": now_text(),
        "reason": reason,
        "tables": {"time_records": rows},
        "counts": {"time_records": len(rows)},
    }
    saved: list[str] = []
    for code, name_zh, name_en in [
        (CANONICAL_01, "工時紀錄", "Time Records"),
        (HISTORY_02, "歷史紀錄", "History"),
    ]:
        payload = dict(payload_common)
        payload.update({"module_code": code, "module_name_zh": name_zh, "module_name_en": name_en})
        base = PERSIST_ROOT / code
        latest = base / f"{code}_records.json"
        history = base / "history" / f"{code}_records_{now_stamp()}.json"
        _atomic_save_json(latest, payload)
        _atomic_save_json(history, payload)
        saved.append(str(latest))
    # Legacy alias marker: do not duplicate data, but leave a small pointer for old tools.
    legacy_base = PERSIST_ROOT / LEGACY_01
    try:
        _atomic_save_json(legacy_base / f"{LEGACY_01}_records.json", {
            "schema_version": "3.02",
            "alias_of": CANONICAL_01,
            "canonical_path": str((PERSIST_ROOT / CANONICAL_01 / f"{CANONICAL_01}_records.json").relative_to(PROJECT_ROOT)),
            "exported_at": now_text(),
            "counts": {"time_records": len(rows)},
        })
    except Exception:
        pass
    _log("MIRROR_TIME_RECORDS_TO_MODULE_FILES", {"rows": len(rows), "saved": saved, "reason": reason})
    return {"ok": True, "rows": len(rows), "saved": saved}


def health_report() -> dict[str, Any]:
    candidates = find_time_record_backup_candidates(include_external=True)
    return {
        "checked_at": now_text(),
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
        "db_time_records_count": time_records_count(DB_PATH),
        "backup_candidates": [
            {"path": str(c.path), "rows": c.row_count, "source_type": c.source_type}
            for c in candidates[:20]
        ],
        "has_backup": bool(candidates),
        "canonical_module_dir": str((PERSIST_ROOT / CANONICAL_01).relative_to(PROJECT_ROOT)),
        "legacy_module_alias": LEGACY_01,
    }

# ===== V18.0 permanent_store-first guard override =====
# 目的：刪除歷史紀錄後 Reboot 不再從舊 history / 舊 persistent_modules 大檔還原回來。
# 原則：只在 DB 空白時救援；救援來源優先固定 latest，不再用「筆數最多」舊備份當權威。
DATA_DIR = PROJECT_ROOT / "data"
PERMANENT_ROOT = DATA_DIR / "permanent_store"
DB_PATH = PERMANENT_ROOT / "database" / "spt_time_tracking.db"
PERSIST_ROOT = PERMANENT_ROOT / "persistent_modules"
STATE_DIR = PERMANENT_ROOT / "persistent_state"
RESTORE_LOG = STATE_DIR / "time_records_guard_log.jsonl"


def _module_records_candidates() -> list[Path]:  # type: ignore[override]
    candidates: list[Path] = []
    # 固定 latest 檔為權威來源。history 僅保留人工查核，不再自動還原避免刪除資料復活。
    for code in (CANONICAL_01, HISTORY_02, LEGACY_01):
        canonical = normalize_time_module_code(code)
        candidates.append(PERSIST_ROOT / canonical / f"{canonical}_records.json")
        candidates.append(PERSIST_ROOT / code / f"{code}_records.json")
    # 相容：若尚未搬移到 permanent_store，才 read-through 舊 latest，不掃舊 history。
    legacy_root = DATA_DIR / "persistent_modules"
    for code in (CANONICAL_01, HISTORY_02, LEGACY_01):
        canonical = normalize_time_module_code(code)
        candidates.append(legacy_root / canonical / f"{canonical}_records.json")
        candidates.append(legacy_root / code / f"{code}_records.json")
    return _dedupe_existing(candidates)


def find_time_record_backup_candidates(include_external: bool = True) -> list[TimeRecordBackupCandidate]:  # type: ignore[override]
    candidates: list[TimeRecordBackupCandidate] = []
    for path in _module_records_candidates():
        payload = _safe_load_json(path)
        rows = _extract_time_records(payload)
        if rows:
            candidates.append(TimeRecordBackupCandidate(path=path, row_count=len(rows), source_type="module_latest", rows=rows))
    # latest 優先，若都有資料，以檔案更新時間決定，不以筆數最多決定，避免已刪除資料被舊大檔復活。
    candidates.sort(key=lambda c: (c.path.stat().st_mtime if c.path.exists() else 0, c.row_count), reverse=True)
    return candidates
