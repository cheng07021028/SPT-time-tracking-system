# -*- coding: utf-8 -*-
"""
SPT Time Tracking System
V1.43 Module-level Permanent Records Service

Purpose
- Keep an independent permanent file and settings file for every module.
- Files are stored under data/permanent_store/persistent_modules/<module_code>/ and are not overwritten by patch updates.
- Each export also writes a timestamp history snapshot.
- Designed as an additive service: it does not remove or replace existing page features.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
PERSIST_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules"
GLOBAL_STATE = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_independent_state.json"
GLOBAL_SETTINGS = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_independent_settings.json"

MODULE_TABLE_MAP: Dict[str, Dict[str, Any]] = {
    "01_time_record": {
        "name_zh": "工時紀錄",
        "name_en": "Time Records",
        "tables": ["time_records"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    "02_history": {
        "name_zh": "歷史紀錄",
        "name_en": "History",
        "tables": ["time_records"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    "03_work_orders": {
        "name_zh": "製令管理",
        "name_en": "Work Orders",
        "tables": ["work_orders"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    "04_employees": {
        "name_zh": "人員名單",
        "name_en": "Employees",
        "tables": ["employees"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    "05_analysis": {
        "name_zh": "製令工時分析",
        "name_en": "Work Order Analysis",
        "tables": ["time_records", "work_orders", "employees"],
        "settings_keys": ["table_columns", "sort", "filters", "chart", "ui"],
    },
    "06_logs": {
        "name_zh": "LOG查詢",
        "name_en": "System Logs",
        "tables": ["system_logs"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    "07_missing_today": {
        "name_zh": "今日未紀錄名單",
        "name_en": "Missing Today",
        "tables": ["employees", "time_records"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    # 舊版相容代碼：部分權限或永久檔仍可能使用 07_missing。
    "07_missing": {
        "name_zh": "今日未紀錄名單",
        "name_en": "Missing Today Legacy",
        "tables": ["employees", "time_records"],
        "settings_keys": ["table_columns", "sort", "filters", "ui"],
    },
    "08_daily_hours": {
        "name_zh": "人員每日工時",
        "name_en": "Daily Hours",
        "tables": ["employees", "time_records"],
        "settings_keys": ["table_columns", "sort", "filters", "chart", "ui"],
    },
    "09_persistence": {
        "name_zh": "資料永久保存與備份",
        "name_en": "Persistence & Backup",
        "tables": ["system_settings"],
        "settings_keys": ["github", "backup", "ui"],
    },
    "10_permissions": {
        "name_zh": "權限管理",
        "name_en": "Permissions",
        "tables": ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_module_permissions", "security_settings"],
        "settings_keys": ["table_columns", "sort", "filters", "security", "ui"],
    },
    "11_login_logs": {
        "name_zh": "登入紀錄",
        "name_en": "Login Logs",
        "tables": ["auth_login_logs", "security_login_logs"],
        "settings_keys": ["table_columns", "sort", "filters", "retention", "ui"],
    },
    "12_module_persistence": {
        "name_zh": "模組永久紀錄中心",
        "name_en": "Module Permanent Records",
        "tables": ["system_settings"],
        "settings_keys": ["module_persistence", "records", "settings", "audit", "history", "ui"],
    },
    "13_system_settings": {
        "name_zh": "系統設定",
        "name_en": "System Settings",
        "tables": ["process_options", "rest_periods", "system_settings"],
        "settings_keys": ["process", "rest_periods", "ui"],
    },
}

def _now() -> str:
    return now_text()


def _stamp() -> str:
    return now_stamp()


def normalize_module_code(module_code: str) -> str:
    """Normalize legacy module codes to the canonical persistent folder names."""
    code = str(module_code or "").strip()
    if code == "01_time_record":
        return "01_time_records"
    return code


def _json_default(obj: Any) -> str:
    return str(obj)


DERIVED_RECORD_MODULES = {"07_missing_today", "07_missing", "08_daily_hours"}


def _path_exists(*parts: str) -> bool:
    try:
        return (PROJECT_ROOT.joinpath(*parts)).exists()
    except Exception:
        return False


def _module_sources_exist(*module_codes: str) -> bool:
    for code in module_codes:
        ncode = normalize_module_code(code)
        if not latest_records_path(ncode).exists():
            return False
    return True


def _health_records_exists(module_code: str) -> tuple[bool, str, str]:
    """Return (exists, path, note) for module records health.

    Some modules are derived or settings-only. They should not be flagged as broken
    just because <module>_records.json is not the true source of truth.
    """
    code = normalize_module_code(module_code)
    if code in DERIVED_RECORD_MODULES:
        ok = _module_sources_exist("04_employees", "01_time_records") or _module_sources_exist("04_employees", "02_history")
        return ok, "derived: 04_employees + 01_time_records/02_history", "衍生查詢模組，允許沒有獨立 records；檢查來源模組資料。"
    if code == "13_system_settings":
        candidates = [
            PROJECT_ROOT / "data" / "permanent_store" / "config" / "system_settings.json",
            PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_system_settings.json",
            PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "system_settings.json",
        ]
        ok = any(p.exists() and p.stat().st_size > 0 for p in candidates)
        path = "; ".join(str(p.relative_to(PROJECT_ROOT)) for p in candidates)
        return ok, path, "設定型模組，records 來源為 system_settings 永久設定檔。"
    rec = latest_records_path(code)
    return rec.exists(), str(rec.relative_to(PROJECT_ROOT)), ""


def _health_settings_exists(module_code: str) -> tuple[bool, str, str]:
    code = normalize_module_code(module_code)
    if code in DERIVED_RECORD_MODULES:
        settings = latest_settings_path(code)
        ok = settings.exists() or (_module_sources_exist("04_employees", "01_time_records") or _module_sources_exist("04_employees", "02_history"))
        return ok, str(settings.relative_to(PROJECT_ROOT)), "衍生查詢模組設定檔可選；若未建立，使用來源模組與預設篩選設定。"
    if code == "13_system_settings":
        candidates = [
            PROJECT_ROOT / "data" / "permanent_store" / "config" / "system_settings.json",
            PROJECT_ROOT / "data" / "permanent_store" / "config" / "auto_backup_settings.json",
            PROJECT_ROOT / "data" / "permanent_store" / "config" / "auto_external_backup_schedule.json",
            PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_system_settings.json",
            PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_auto_backup_settings.json",
            PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "system_settings.json",
        ]
        ok = any(p.exists() and p.stat().st_size > 0 for p in candidates)
        path = "; ".join(str(p.relative_to(PROJECT_ROOT)) for p in candidates)
        return ok, path, "檢查系統設定、自動備份與 13 模組永久設定檔。"
    settings = latest_settings_path(code)
    return settings.exists(), str(settings.relative_to(PROJECT_ROOT)), ""


def ensure_dirs() -> None:
    PERSIST_ROOT.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "permanent_store" / "persistent_state").mkdir(parents=True, exist_ok=True)
    for code in MODULE_TABLE_MAP:
        module_dir(code).mkdir(parents=True, exist_ok=True)
        (module_dir(code) / "history").mkdir(parents=True, exist_ok=True)
        (module_dir(code) / ".gitkeep").touch(exist_ok=True)


def module_dir(module_code: str) -> Path:
    return PERSIST_ROOT / normalize_module_code(module_code)


def latest_records_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / f"{code}_records.json"


def latest_settings_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / f"{code}_settings.json"


def latest_audit_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / f"{code}_audit.jsonl"


def history_records_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / "history" / f"{code}_records_{_stamp()}.json"


def history_settings_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / "history" / f"{code}_settings_{_stamp()}.json"


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def read_table(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
    return [dict(r) for r in rows]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()["c"])


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def append_audit(module_code: str, action: str, username: str = "SYSTEM", detail: Optional[Dict[str, Any]] = None) -> None:
    ensure_dirs()
    payload = {
        "time": _now(),
        "module_code": module_code,
        "module_name": MODULE_TABLE_MAP.get(module_code, {}).get("name_zh", module_code),
        "username": username,
        "action": action,
        "detail": detail or {},
    }
    path = latest_audit_path(module_code)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")


def export_module_records(module_code: str, username: str = "SYSTEM", write_history: bool = True) -> Dict[str, Any]:
    ensure_dirs()
    info = MODULE_TABLE_MAP.get(module_code)
    if not info:
        raise ValueError(f"Unknown module_code: {module_code}")

    payload = {
        "schema_version": "1.43",
        "exported_at": _now(),
        "module_code": module_code,
        "module_name_zh": info["name_zh"],
        "module_name_en": info["name_en"],
        "tables": {},
        "counts": {},
    }
    if DB_PATH.exists():
        with connect_db() as conn:
            for table in info.get("tables", []):
                data = read_table(conn, table)
                payload["tables"][table] = data
                payload["counts"][table] = len(data)
    else:
        payload["warning"] = "SQLite DB not found; exported empty module state."

    latest = latest_records_path(module_code)
    save_json(latest, payload)
    if write_history:
        save_json(history_records_path(module_code), payload)
    append_audit(module_code, "EXPORT_RECORDS", username, {"counts": payload["counts"]})
    rebuild_global_index()
    return payload


def export_all_modules(username: str = "SYSTEM") -> Dict[str, Any]:
    ensure_dirs()
    result = {}
    for code in MODULE_TABLE_MAP:
        result[code] = export_module_records(code, username=username, write_history=True)
    return result


def get_module_status() -> List[Dict[str, Any]]:
    ensure_dirs()
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw_code, info in MODULE_TABLE_MAP.items():
        code = normalize_module_code(raw_code)
        if code in seen:
            continue
        seen.add(code)
        rec = load_json(latest_records_path(code), {}) or {}
        settings = load_json(latest_settings_path(code), {}) or {}
        counts = rec.get("counts", {})
        rec_ok, rec_path, rec_note = _health_records_exists(code)
        set_ok, set_path, set_note = _health_settings_exists(code)
        rows.append({
            "模組代碼 / Module Code": code,
            "模組 / Module": f'{info["name_zh"]} / {info["name_en"]}',
            "紀錄檔 / Records Exists": bool(rec_ok),
            "設定檔 / Settings Exists": bool(set_ok),
            "紀錄時間 / Exported At": rec.get("exported_at", ""),
            "設定時間 / Settings At": settings.get("saved_at", ""),
            "資料筆數 / Counts": json.dumps(counts, ensure_ascii=False),
            "路徑 / Path": rec_path if rec_note else str(module_dir(code).relative_to(PROJECT_ROOT)),
            "檢查說明 / Health Note": rec_note or set_note,
            "設定路徑 / Settings Path": set_path,
        })
    return rows


def save_module_settings(module_code: str, settings: Dict[str, Any], username: str = "SYSTEM", write_history: bool = True) -> Dict[str, Any]:
    ensure_dirs()
    info = MODULE_TABLE_MAP.get(module_code, {"name_zh": module_code, "name_en": module_code})
    payload = {
        "schema_version": "1.43",
        "saved_at": _now(),
        "module_code": module_code,
        "module_name_zh": info.get("name_zh", module_code),
        "module_name_en": info.get("name_en", module_code),
        "settings": settings,
    }
    save_json(latest_settings_path(module_code), payload)
    if write_history:
        save_json(history_settings_path(module_code), payload)
    append_audit(module_code, "SAVE_SETTINGS", username, {"keys": list(settings.keys())})
    rebuild_global_index()
    return payload


def load_module_settings(module_code: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = load_json(latest_settings_path(module_code), {}) or {}
    if payload.get("settings") is not None:
        return payload.get("settings", {})
    return default or {}


def rebuild_global_index() -> Dict[str, Any]:
    ensure_dirs()
    index = {
        "schema_version": "1.43",
        "updated_at": _now(),
        "root": str(PERSIST_ROOT.relative_to(PROJECT_ROOT)),
        "modules": {},
    }
    for code, info in MODULE_TABLE_MAP.items():
        index["modules"][code] = {
            "name_zh": info["name_zh"],
            "name_en": info["name_en"],
            "records_path": str(latest_records_path(code).relative_to(PROJECT_ROOT)),
            "settings_path": str(latest_settings_path(code).relative_to(PROJECT_ROOT)),
            "audit_path": str(latest_audit_path(code).relative_to(PROJECT_ROOT)),
            "records_exists": latest_records_path(code).exists(),
            "settings_exists": latest_settings_path(code).exists(),
            "audit_exists": latest_audit_path(code).exists(),
        }
    save_json(GLOBAL_STATE, index)
    settings_index = {
        "schema_version": "1.43",
        "updated_at": _now(),
        "note": "Independent module settings are saved under data/permanent_store/persistent_modules/<module_code>/.",
        "modules": {code: str(latest_settings_path(code).relative_to(PROJECT_ROOT)) for code in MODULE_TABLE_MAP},
    }
    save_json(GLOBAL_SETTINGS, settings_index)
    return index


def bootstrap_module_persistence(username: str = "SYSTEM") -> Dict[str, Any]:
    ensure_dirs()
    index = rebuild_global_index()
    # Create placeholder settings for modules that do not yet have settings files.
    for code, info in MODULE_TABLE_MAP.items():
        if not latest_settings_path(code).exists():
            save_module_settings(code, {"created_by": "V1.43 bootstrap", "table_columns": {}, "sort": {}, "filters": {}, "ui": {}}, username=username, write_history=False)
    append_audit("09_persistence", "BOOTSTRAP_MODULE_PERSISTENCE", username, {"modules": len(MODULE_TABLE_MAP)})
    return index


def protect_gitignore_rules() -> None:
    """Ensure permanent module JSON files are NOT ignored by .gitignore."""
    gitignore = PROJECT_ROOT / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = text.splitlines()
    add_lines = [
        "",
        "# V1.43 independent permanent module records - keep these tracked",
        "!data/permanent_store/persistent_modules/",
        "!data/permanent_store/persistent_modules/**",
        "!data/permanent_store/persistent_state/spt_module_independent_state.json",
        "!data/permanent_store/persistent_state/spt_module_independent_settings.json",
        "!data/permanent_store/persistent_state/spt_audit_log_state.json",
    ]
    if "!data/permanent_store/persistent_modules/**" not in text:
        lines.extend(add_lines)
        gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    protect_gitignore_rules()
    bootstrap_module_persistence()
    export_all_modules()
    print("V1.43 module persistence bootstrap completed.")
    print(f"Root: {PERSIST_ROOT}")
