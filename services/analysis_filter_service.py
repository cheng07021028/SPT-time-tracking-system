# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from services.timezone_service import today_date, now_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "data" / "permanent_store" / "config" / "analysis_filter_settings.json"
STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_analysis_filter_settings.json"
MODULE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "05_analysis" / "analysis_filter_settings.json"

# V300.71: 05 Professional BI Filters must use Neon/PostgreSQL as the authority.
# Local JSON files remain only as fallback/mirrors for local test and temporary DB outages.
SYSTEM_SETTING_KEY = "05_work_order_analysis_filters_v30071"
SYSTEM_SETTING_NOTE = "05 製令工時分析｜專業 BI 篩選永久設定 JSON"
LEGACY_MODULE_KEY = "05_analysis"
LEGACY_PAYLOAD_KEY = "analysis_filter_settings"
_DB_SCHEMA_READY = False

MULTI_KEYS = [
    "work_orders", "part_nos", "type_names", "customers", "assembly_locations",
    "process_names", "employee_ids", "employee_names", "departments", "titles",
]


def _default_filters() -> dict[str, Any]:
    import datetime
    today = today_date()
    return {
        "version": "V300.71",
        "updated_at": now_text(),
        "date_preset": "近30天",
        "start_date": str(today - datetime.timedelta(days=30)),
        "end_date": str(today),
        "work_orders": [], "part_nos": [], "type_names": [], "customers": [], "assembly_locations": [],
        "process_names": [], "employee_ids": [], "employee_names": [], "departments": [], "titles": [],
        "status_filter": "全部", "anomaly_filter": "全部", "top_n": "Top 20", "sort_by": "累積工時由大到小", "detail_limit": 1000,
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def _normalize(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _default_filters()
    payload.update(filters or {})
    for key in MULTI_KEYS:
        val = payload.get(key, [])
        if isinstance(val, str):
            payload[key] = [val] if val.strip() else []
        elif isinstance(val, (list, tuple, set)):
            payload[key] = [str(x).strip() for x in val if str(x).strip()]
        else:
            payload[key] = []
    try:
        payload["detail_limit"] = int(payload.get("detail_limit") or 1000)
    except Exception:
        payload["detail_limit"] = 1000
    for key in ["status_filter", "anomaly_filter", "top_n", "sort_by", "date_preset"]:
        payload[key] = str(payload.get(key) or _default_filters().get(key) or "").strip()
    return payload


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
            execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_v30071_system_settings_key ON system_settings(setting_key)", ())
        except Exception:
            pass
        _DB_SCHEMA_READY = True
        return True
    except Exception:
        return False


def _load_from_db() -> dict[str, Any] | None:
    if not _ensure_db_schema():
        return None
    _ensure_database, query_one, _execute = _db_services()
    if not callable(query_one):
        return None
    try:
        row = query_one(
            "SELECT setting_value FROM system_settings WHERE setting_key=? ORDER BY updated_at DESC LIMIT 1",
            (SYSTEM_SETTING_KEY,),
        ) or {}
        raw = row.get("setting_value") if isinstance(row, dict) else None
        if not raw:
            return None
        parsed = json.loads(str(raw))
        return _normalize(parsed) if isinstance(parsed, dict) else None
    except Exception:
        return None


def _save_to_db(payload: dict[str, Any]) -> bool:
    if not _ensure_db_schema():
        return False
    _ensure_database, query_one, execute = _db_services()
    if not callable(query_one) or not callable(execute):
        return False
    text = json.dumps(payload, ensure_ascii=False, default=str)
    now = now_text()
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


def _load_legacy_neon_payload() -> dict[str, Any] | None:
    try:
        from services.neon_authority_service import is_neon_enabled, load_payload
        if not bool(is_neon_enabled()):
            return None
        data = load_payload(LEGACY_MODULE_KEY, LEGACY_PAYLOAD_KEY, None)
        return _normalize(data) if isinstance(data, dict) else None
    except Exception:
        return None


def _save_legacy_neon_payload(payload: dict[str, Any]) -> None:
    try:
        from services.neon_authority_service import is_neon_enabled, save_payload
        if bool(is_neon_enabled()):
            save_payload(LEGACY_MODULE_KEY, LEGACY_PAYLOAD_KEY, payload, user="SYSTEM")
    except Exception:
        pass


def _write_local_filter_cache(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except Exception:
            pass


def load_analysis_filters() -> dict[str, Any]:
    # 1) system_settings is the formal authority after V300.71.
    db_payload = _load_from_db()
    if db_payload:
        return db_payload

    # 2) Promote old Neon module payload once if it exists.
    legacy_payload = _load_legacy_neon_payload()
    if legacy_payload:
        _save_to_db(legacy_payload)
        _write_local_filter_cache(legacy_payload)
        return legacy_payload

    # 3) Local JSON is fallback/migration source only.
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _load_json(path)
        if data:
            payload = _normalize(data)
            _save_to_db(payload)
            return payload
    return _default_filters()


def save_analysis_filters(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize(filters or {})
    payload["version"] = "V300.71"
    payload["updated_at"] = now_text()
    _save_to_db(payload)
    _save_legacy_neon_payload(payload)
    _write_local_filter_cache(payload)
    return payload
