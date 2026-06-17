# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from services.timezone_service import today_date, now_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "data" / "permanent_store" / "config" / "history_filter_settings.json"
STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_history_filter_settings.json"
MODULE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "02_history" / "history_filter_settings.json"

# V300.69: 02 Professional Filters must survive Streamlit Cloud Reboot App.
# Local JSON files are kept only as fallback/mirrors.  The authoritative copy is
# stored in Neon/PostgreSQL system_settings under this key.
SYSTEM_SETTING_KEY = "02_history_professional_filters_v30069"
SYSTEM_SETTING_NOTE = "02 歷史紀錄｜專業篩選永久設定 JSON"
_DB_SCHEMA_READY = False

MULTI_KEYS = [
    "work_orders", "part_nos", "type_names", "assembly_locations", "process_names",
    "employee_ids", "employee_names", "departments", "titles", "statuses",
]


def default_history_filters() -> dict[str, Any]:
    today = today_date()
    return {
        "version": "V300.91",
        "updated_at": now_text(),
        "date_preset": "今日",
        "start_date": str(today),
        "end_date": str(today),
        "work_orders": [],
        "part_nos": [],
        "type_names": [],
        "assembly_locations": [],
        "process_names": [],
        "employee_ids": [],
        "employee_names": [],
        "departments": [],
        "titles": [],
        "statuses": [],
        "end_state": "全部",
        "anomaly_filter": "全部",
        "keyword": "",
        "top_n": "全部",
        "sort_by": "ID由新到舊",
        "detail_limit": 1000,
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
    payload = default_history_filters()
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
    payload["keyword"] = str(payload.get("keyword") or "").strip()
    return payload


def _db_services():
    try:
        from services.db_service import ensure_database, query_one, execute
        return ensure_database, query_one, execute
    except Exception:
        return None, None, None


def _ensure_db_schema() -> bool:
    """Create the minimal settings table once per process when DB is available."""
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
            # Some legacy SQLite tables may already have duplicate keys.  The
            # update-then-insert path below still works without this index.
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
            # Final fallback for environments where a unique index exists but
            # update/insert race occurred.
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


def _write_json_mirrors(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except Exception:
            pass


def load_history_filters() -> dict[str, Any]:
    # Neon/PostgreSQL is the authoritative source.  Local JSON is fallback only.
    db_payload = _load_from_db()
    if db_payload:
        return db_payload
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _load_json(path)
        if data:
            payload = _normalize(data)
            # Promote legacy local settings to Neon once, but never block page load.
            _save_to_db(payload)
            return payload
    return default_history_filters()


def save_history_filters(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize(filters)
    payload["version"] = "V300.91"
    payload["updated_at"] = now_text()
    _save_to_db(payload)
    _write_json_mirrors(payload)
    return payload


def reset_history_filters() -> dict[str, Any]:
    payload = default_history_filters()
    return save_history_filters(payload)
