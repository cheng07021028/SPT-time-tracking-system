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


def _default_filters() -> dict[str, Any]:
    today = today_date()
    start = today.replace(day=1)
    return {
        "version": "V2.13",
        "updated_at": now_text(),
        "date_preset": "近30天",
        "start_date": str(today - __import__('datetime').timedelta(days=30)),
        "end_date": str(today),
        "work_orders": [],
        "part_nos": [],
        "type_names": [],
        "customers": [],
        "assembly_locations": [],
        "process_names": [],
        "employee_ids": [],
        "employee_names": [],
        "departments": [],
        "titles": [],
        "status_filter": "全部",
        "anomaly_filter": "全部",
        "top_n": "Top 20",
        "sort_by": "累積工時由大到小",
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


def load_analysis_filters() -> dict[str, Any]:
    filters = _default_filters()
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _load_json(path)
        if data:
            filters.update(data)
            break
    # normalize list fields
    for key in [
        "work_orders", "part_nos", "type_names", "customers", "assembly_locations",
        "process_names", "employee_ids", "employee_names", "departments", "titles",
    ]:
        val = filters.get(key, [])
        if isinstance(val, str):
            filters[key] = [val] if val else []
        elif not isinstance(val, list):
            filters[key] = []
        else:
            filters[key] = [str(x) for x in val if str(x).strip()]
    return filters


def save_analysis_filters(filters: dict[str, Any]) -> None:
    payload = _default_filters()
    payload.update(filters or {})
    payload["version"] = "V2.13"
    payload["updated_at"] = now_text()
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
