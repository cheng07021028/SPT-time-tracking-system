# -*- coding: utf-8 -*-
"""Persistent settings for 03 Work Order OneDrive mapped sync.

Stores sheet/header-row/column mapping so admins do not need to remap every time.
V300.69: Neon/PostgreSQL system_settings is the authority. Local JSON copies are
kept only as fallback/mirrors for local testing and backup compatibility.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "permanent_store" / "config" / "work_order_sync_settings.json"
STATE_PATH = ROOT / "data" / "permanent_store" / "persistent_state" / "spt_work_order_sync_settings.json"
MODULE_PATH = ROOT / "data" / "permanent_store" / "persistent_modules" / "03_work_orders" / "work_order_sync_settings.json"

SYSTEM_SETTING_KEY = "03_work_order_onedrive_mapping_v30069"
SYSTEM_SETTING_NOTE = "03 製令管理｜OneDrive 對應更新永久設定 JSON"
_DB_SCHEMA_READY = False

DEFAULT_SETTINGS: Dict[str, Any] = {
    "version": "V300.69",
    "last_sheet": "",
    "last_header_row": 1,
    "last_mapping": {},
    "last_delete_missing": False,
    "last_import_mode": "master",
    "last_row_key_col": "製令&出現次數",
    "sheet_settings": {},
    "updated_at": "",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dirs() -> None:
    for p in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        p.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _merge_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        merged.update(data)
    if not isinstance(merged.get("last_mapping"), dict):
        merged["last_mapping"] = {}
    if not isinstance(merged.get("sheet_settings"), dict):
        merged["sheet_settings"] = {}
    try:
        merged["last_header_row"] = max(1, int(merged.get("last_header_row") or 1))
    except Exception:
        merged["last_header_row"] = 1
    merged["last_delete_missing"] = bool(merged.get("last_delete_missing", False))
    import_mode = str(merged.get("last_import_mode") or "master")
    merged["last_import_mode"] = import_mode if import_mode in ("master", "source_rows") else "master"
    merged["last_row_key_col"] = str(merged.get("last_row_key_col") or "製令&出現次數")
    return merged


def _db_services():
    try:
        from services.db_service import ensure_database, query_one, execute
        return ensure_database, query_one, execute
    except Exception:
        return None, None, None


def _ensure_db_schema() -> bool:
    global _DB_SCHEMA_READY
    if _DB_SCHEMA_READY:
        return True
    ensure_database, _query_one, execute = _db_services()
    if not callable(ensure_database) or not callable(execute):
        return False
    try:
        ensure_database()
        execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT,
                setting_value TEXT,
                note TEXT,
                updated_at TEXT
            )
            """,
            (),
        )
        try:
            execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_v30069_system_settings_key ON system_settings(setting_key)", ())
        except Exception:
            pass
        _DB_SCHEMA_READY = True
        return True
    except Exception:
        return False


def _load_from_db() -> Dict[str, Any]:
    if not _ensure_db_schema():
        return {}
    _ensure_database, query_one, _execute = _db_services()
    if not callable(query_one):
        return {}
    try:
        row = query_one(
            "SELECT setting_value FROM system_settings WHERE setting_key=? ORDER BY updated_at DESC LIMIT 1",
            (SYSTEM_SETTING_KEY,),
        ) or {}
        raw = row.get("setting_value") if isinstance(row, dict) else None
        if not raw:
            return {}
        parsed = json.loads(str(raw))
        return _merge_settings(parsed) if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _save_to_db(settings: Dict[str, Any]) -> bool:
    if not _ensure_db_schema():
        return False
    _ensure_database, query_one, execute = _db_services()
    if not callable(query_one) or not callable(execute):
        return False
    text = json.dumps(settings, ensure_ascii=False, default=str)
    now = _now()
    try:
        existing = query_one("SELECT setting_key FROM system_settings WHERE setting_key=? LIMIT 1", (SYSTEM_SETTING_KEY,))
        if existing:
            execute(
                "UPDATE system_settings SET setting_value=?, note=?, updated_at=? WHERE setting_key=?",
                (text, SYSTEM_SETTING_NOTE, now, SYSTEM_SETTING_KEY),
            )
        else:
            execute(
                "INSERT INTO system_settings(setting_key, setting_value, note, updated_at) VALUES (?, ?, ?, ?)",
                (SYSTEM_SETTING_KEY, text, SYSTEM_SETTING_NOTE, now),
            )
        return True
    except Exception:
        try:
            execute(
                """
                INSERT INTO system_settings(setting_key, setting_value, note, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (SYSTEM_SETTING_KEY, text, SYSTEM_SETTING_NOTE, now),
            )
            return True
        except Exception:
            return False


def _write_json_mirrors(settings: Dict[str, Any]) -> None:
    _ensure_dirs()
    text = json.dumps(settings, ensure_ascii=False, indent=2, default=str)
    for p in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        try:
            p.write_text(text, encoding="utf-8")
        except Exception:
            pass


def load_work_order_sync_settings() -> Dict[str, Any]:
    """Load settings, preferring Neon/PostgreSQL authority then fallback mirrors."""
    db_payload = _load_from_db()
    if db_payload:
        return db_payload
    for p in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _read_json(p)
        if data:
            merged = _merge_settings(data)
            _save_to_db(merged)  # promote legacy local settings once when DB is available
            return merged
    return dict(DEFAULT_SETTINGS)


def save_work_order_sync_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Write settings to Neon/PostgreSQL authority and local fallback mirrors."""
    data = _merge_settings(settings or {})
    data["version"] = "V300.69"
    data["updated_at"] = _now()
    _save_to_db(data)
    _write_json_mirrors(data)
    return data


def get_sheet_setting(sheet_name: str) -> Dict[str, Any]:
    settings = load_work_order_sync_settings()
    sheet_name = str(sheet_name or "")
    sheet_settings = settings.get("sheet_settings", {}) if isinstance(settings.get("sheet_settings"), dict) else {}
    sheet_cfg = sheet_settings.get(sheet_name, {}) if sheet_name else {}
    if not isinstance(sheet_cfg, dict):
        sheet_cfg = {}
    # Fallback to last used mapping for new sheets.
    return {
        "header_row": sheet_cfg.get("header_row", settings.get("last_header_row", 1)),
        "mapping": sheet_cfg.get("mapping", settings.get("last_mapping", {})),
        "delete_missing": sheet_cfg.get("delete_missing", settings.get("last_delete_missing", False)),
        "import_mode": sheet_cfg.get("import_mode", settings.get("last_import_mode", "master")),
        "row_key_col": sheet_cfg.get("row_key_col", settings.get("last_row_key_col", "製令&出現次數")),
    }


def save_sheet_setting(
    sheet_name: str,
    header_row: int,
    mapping: Dict[str, str],
    delete_missing: bool = False,
    import_mode: str = "master",
    row_key_col: str = "製令&出現次數",
) -> Dict[str, Any]:
    settings = load_work_order_sync_settings()
    sheet_name = str(sheet_name or "")
    try:
        header_row = max(1, int(header_row or 1))
    except Exception:
        header_row = 1
    clean_mapping = {str(k): str(v or "") for k, v in (mapping or {}).items()}
    import_mode = str(import_mode or "master")
    if import_mode not in ("master", "source_rows"):
        import_mode = "master"
    row_key_col = str(row_key_col or "製令&出現次數")
    settings["last_sheet"] = sheet_name
    settings["last_header_row"] = header_row
    settings["last_mapping"] = clean_mapping
    settings["last_delete_missing"] = bool(delete_missing)
    settings["last_import_mode"] = import_mode
    settings["last_row_key_col"] = row_key_col
    sheet_settings = settings.get("sheet_settings")
    if not isinstance(sheet_settings, dict):
        sheet_settings = {}
    if sheet_name:
        sheet_settings[sheet_name] = {
            "header_row": header_row,
            "mapping": clean_mapping,
            "delete_missing": bool(delete_missing),
            "import_mode": import_mode,
            "row_key_col": row_key_col,
            "updated_at": _now(),
        }
    settings["sheet_settings"] = sheet_settings
    return save_work_order_sync_settings(settings)


def clear_work_order_sync_settings() -> None:
    # Clear means reset the authoritative value to defaults so Reboot App will not
    # reload old local mirror values.  Local mirrors are also overwritten.
    save_work_order_sync_settings(dict(DEFAULT_SETTINGS))
