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


def _neon_enabled() -> bool:
    try:
        from services.neon_authority_service import is_neon_enabled
        return bool(is_neon_enabled())
    except Exception:
        return False


def _default_filters() -> dict[str, Any]:
    import datetime
    today = today_date()
    return {
        "version": "neon-v31",
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
    for key in ["work_orders", "part_nos", "type_names", "customers", "assembly_locations", "process_names", "employee_ids", "employee_names", "departments", "titles"]:
        val = filters.get(key, [])
        if isinstance(val, str): filters[key] = [val] if val else []
        elif not isinstance(val, list): filters[key] = []
        else: filters[key] = [str(x) for x in val if str(x).strip()]
    return filters


def load_analysis_filters() -> dict[str, Any]:
    filters = _default_filters()
    if _neon_enabled():
        try:
            from services.neon_authority_service import load_payload
            data = load_payload("05_analysis", "analysis_filter_settings", None)
            if isinstance(data, dict): filters.update(data)
            return _normalize(filters)
        except Exception:
            pass
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        data = _load_json(path)
        if data:
            filters.update(data); break
    return _normalize(filters)


def _write_local_filter_cache(payload: dict[str, Any]) -> None:
    for path in (CONFIG_PATH, STATE_PATH, MODULE_PATH):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def save_analysis_filters(filters: dict[str, Any]) -> None:
    payload = _default_filters(); payload.update(filters or {})
    payload["version"] = "neon-v31"; payload["updated_at"] = now_text()
    if _neon_enabled():
        try:
            from services.neon_authority_service import save_payload
            result = save_payload("05_analysis", "analysis_filter_settings", payload, user="SYSTEM")
            # Keep a local cache/fallback as well.  Neon remains the authority,
            # but this prevents a transient AdminShutdown from crashing 05 and
            # preserves the latest filter locally until Neon is available again.
            _write_local_filter_cache(payload)
            return
        except Exception:
            _write_local_filter_cache(payload)
            return
    _write_local_filter_cache(payload)
