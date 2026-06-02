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

MULTI_KEYS = [
    "work_orders", "part_nos", "type_names", "assembly_locations", "process_names",
    "employee_ids", "employee_names", "departments", "titles", "statuses",
]


def default_history_filters() -> dict[str, Any]:
    today = today_date()
    return {
        "version": "V2.24",
        "updated_at": now_text(),
        "date_preset": "近30天",
        "start_date": str(today - timedelta(days=30)),
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


def load_history_filters() -> dict[str, Any]:
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _load_json(path)
        if data:
            return _normalize(data)
    return default_history_filters()


def save_history_filters(filters: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize(filters)
    payload["version"] = "V2.24"
    payload["updated_at"] = now_text()
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def reset_history_filters() -> dict[str, Any]:
    payload = default_history_filters()
    return save_history_filters(payload)
