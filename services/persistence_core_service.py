# -*- coding: utf-8 -*-
"""
SPT Time Tracking - V360 Unified Persistence Core

架構級修正：建立唯一設定主來源，避免 SQLite / JSON / session_state / 預設值互相覆蓋。
本服務只處理本機 JSON 與輕量鏡像，不在載入時掃 history、不自動上傳 GitHub，避免登入或頁面無限運轉。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
MODULE_DIR = PROJECT_ROOT / "data" / "persistent_modules"
MASTER_SETTINGS_PATH = STATE_DIR / "spt_user_persistent_settings.json"

MASTER_MIRROR_PATHS = [
    MASTER_SETTINGS_PATH,
    STATE_DIR / "spt_module_settings.json",
    MODULE_DIR / "ui_table_settings" / "v360_user_persistent_settings.json",
    MODULE_DIR / "01_time_records" / "v360_user_persistent_settings.json",
    MODULE_DIR / "10_permissions" / "v360_user_persistent_settings.json",
    MODULE_DIR / "13_system_settings" / "v360_user_persistent_settings.json",
]


def now_text() -> str:
    try:
        from services.timezone_service import now_text as _now_text
        return _now_text()
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for path in MASTER_MIRROR_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # verify before replace
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _blank_master() -> dict[str, Any]:
    return {
        "version": "V360",
        "updated_at": now_text(),
        "description": "超慧科技製造部工時紀錄系統唯一設定主來源；SQLite 僅作運行快取。",
        "table_settings": {},
        "column_settings": {},
        "system_settings": {},
        "permission_settings": {},
        "source": "v360_unified_persistence_core",
    }


def _score_master(data: dict[str, Any]) -> tuple[int, int, int, int, float]:
    if not isinstance(data, dict):
        return (-1, -1, -1, -1, 0.0)
    table_count = len(data.get("table_settings") or {}) if isinstance(data.get("table_settings"), dict) else 0
    column_count = len(data.get("column_settings") or {}) if isinstance(data.get("column_settings"), dict) else 0
    system_count = len(data.get("system_settings") or {}) if isinstance(data.get("system_settings"), dict) else 0
    permission_count = len(data.get("permission_settings") or {}) if isinstance(data.get("permission_settings"), dict) else 0
    try:
        updated = float(data.get("_mtime") or 0.0)
    except Exception:
        updated = 0.0
    return (table_count, column_count, system_count, permission_count, updated)


def load_master_settings() -> dict[str, Any]:
    """Load the best available master settings without writing anything."""
    ensure_dirs()
    best: dict[str, Any] | None = None
    best_score = (-1, -1, -1, -1, -1.0)
    for path in MASTER_MIRROR_PATHS:
        payload = read_json(path)
        if not payload:
            continue
        # spt_module_settings may embed our master section under v360_user_persistent_settings.
        if isinstance(payload.get("v360_user_persistent_settings"), dict):
            payload = payload.get("v360_user_persistent_settings") or {}
        if not isinstance(payload, dict):
            continue
        try:
            payload = dict(payload)
            payload["_mtime"] = path.stat().st_mtime if path.exists() else 0.0
        except Exception:
            pass
        score = _score_master(payload)
        if score > best_score:
            best = payload
            best_score = score
    if not best:
        return _blank_master()
    base = _blank_master()
    # Merge sections explicitly to avoid malformed files dropping required keys.
    for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
        if isinstance(best.get(section), dict):
            base[section] = dict(best.get(section) or {})
    base["updated_at"] = str(best.get("updated_at") or now_text())
    return base


def save_master_settings(master: dict[str, Any], *, reason: str = "v360_save") -> dict[str, Any]:
    ensure_dirs()
    payload = _blank_master()
    for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
        if isinstance(master.get(section), dict):
            payload[section] = dict(master.get(section) or {})
    payload["updated_at"] = now_text()
    payload["reason"] = reason
    for path in MASTER_MIRROR_PATHS:
        if path.name == "spt_module_settings.json":
            existing = read_json(path)
            if not isinstance(existing, dict):
                existing = {}
            existing["v360_user_persistent_settings"] = payload
            existing["updated_at"] = payload["updated_at"]
            existing["version"] = str(existing.get("version") or "V360")
            atomic_write_json(path, existing)
        else:
            atomic_write_json(path, payload)
    return {"ok": True, "files": [str(p) for p in MASTER_MIRROR_PATHS], "reason": reason}


def get_section(section: str) -> dict[str, Any]:
    master = load_master_settings()
    data = master.get(section)
    return dict(data or {}) if isinstance(data, dict) else {}


def update_section(section: str, data: dict[str, Any], *, reason: str = "v360_update_section") -> dict[str, Any]:
    master = load_master_settings()
    master[section] = dict(data or {})
    return save_master_settings(master, reason=reason)


def merge_section(section: str, data: dict[str, Any], *, reason: str = "v360_merge_section") -> dict[str, Any]:
    master = load_master_settings()
    cur = master.get(section) if isinstance(master.get(section), dict) else {}
    merged = dict(cur or {})
    merged.update(dict(data or {}))
    master[section] = merged
    return save_master_settings(master, reason=reason)


def bootstrap_persistent_state_once() -> dict[str, Any]:
    """Lightweight local bootstrap: create master file and let table persistence migrate old settings.

    This intentionally avoids GitHub, history scans, full exports and page reruns.
    """
    ensure_dirs()
    result: dict[str, Any] = {"ok": True, "steps": []}
    try:
        master = load_master_settings()
        save_master_settings(master, reason="v360_bootstrap_touch")
        result["steps"].append({"step": "master_settings", "ok": True})
    except Exception as exc:
        result["ok"] = False
        result["steps"].append({"step": "master_settings", "ok": False, "error": str(exc)})
    try:
        from services.table_persistence_service import migrate_legacy_table_settings_to_master
        r = migrate_legacy_table_settings_to_master(write=True)
        result["steps"].append({"step": "table_persistence_migration", **(r if isinstance(r, dict) else {"result": str(r)})})
    except Exception as exc:
        result["ok"] = False
        result["steps"].append({"step": "table_persistence_migration", "ok": False, "error": str(exc)})
    return result
