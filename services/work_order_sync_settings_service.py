# -*- coding: utf-8 -*-
"""Persistent settings for 03 Work Order OneDrive mapped sync.

Stores sheet/header-row/column mapping so admins do not need to remap every time.
This module intentionally does not touch database records or GitHub upload; it only
writes small JSON setting files that can be included in the existing persistence flow.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "config" / "work_order_sync_settings.json"
STATE_PATH = ROOT / "data" / "persistent_state" / "spt_work_order_sync_settings.json"
MODULE_PATH = ROOT / "data" / "persistent_modules" / "03_work_orders" / "work_order_sync_settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "version": "V2.46",
    "last_sheet": "",
    "last_header_row": 1,
    "last_mapping": {},
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
    return merged


def load_work_order_sync_settings() -> Dict[str, Any]:
    """Load persistent settings, preferring config then persistent copies."""
    for p in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _read_json(p)
        if data:
            return _merge_settings(data)
    return dict(DEFAULT_SETTINGS)


def save_work_order_sync_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Write settings to all permanent locations."""
    _ensure_dirs()
    data = _merge_settings(settings or {})
    data["version"] = "V2.46"
    data["updated_at"] = _now()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    for p in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        p.write_text(text, encoding="utf-8")
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
    }


def save_sheet_setting(sheet_name: str, header_row: int, mapping: Dict[str, str], delete_missing: bool = False) -> Dict[str, Any]:
    settings = load_work_order_sync_settings()
    sheet_name = str(sheet_name or "")
    try:
        header_row = max(1, int(header_row or 1))
    except Exception:
        header_row = 1
    clean_mapping = {str(k): str(v or "") for k, v in (mapping or {}).items()}
    settings["last_sheet"] = sheet_name
    settings["last_header_row"] = header_row
    settings["last_mapping"] = clean_mapping
    settings["last_delete_missing"] = bool(delete_missing)
    sheet_settings = settings.get("sheet_settings")
    if not isinstance(sheet_settings, dict):
        sheet_settings = {}
    if sheet_name:
        sheet_settings[sheet_name] = {
            "header_row": header_row,
            "mapping": clean_mapping,
            "delete_missing": bool(delete_missing),
            "updated_at": _now(),
        }
    settings["sheet_settings"] = sheet_settings
    return save_work_order_sync_settings(settings)


def clear_work_order_sync_settings() -> None:
    _ensure_dirs()
    for p in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
