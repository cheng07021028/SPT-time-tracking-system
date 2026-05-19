# -*- coding: utf-8 -*-
"""
SPT Time Tracking - V360 Table Persistence Service

統一 01 / 10 / 13 及所有模組的表格設定主來源。
- table_settings：欄寬、欄位順序、排序狀態。
- column_settings：全域 st.data_editor/st.dataframe 欄位顯示、順序、欄寬、標題。

載入時不寫檔、不上傳、不掃 history；只有使用者真的修改設定時才寫檔。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def canonical_table_key(table_key: Any, *, kind: str = "table") -> str:
    raw = str(table_key or "").strip()
    if not raw:
        return "unknown.table"
    text = raw.replace("\\", "/")
    low = text.lower()

    # Remove Streamlit/editor revision suffixes.
    text = re.sub(r"_(rev|revision)?\d+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"v171_account_password_editor_\d+", "v171_account_password_editor", text)
    text = re.sub(r"v189_permission_editor_\d+", "v189_permission_editor", text)

    # 01｜工時紀錄
    if "today_records_admin_maintenance" in text:
        return "01.time_records.admin_maintenance"
    if "today_records" in text or "frame_active_parallel_group" in text or "active_parallel_group" in text:
        return "01.time_records.main"
    if "start_conflicting_active_records" in text:
        return "01.time_records.conflicts"

    # 10｜權限管理
    if "v171_account_password_editor" in text or "account_password_editor" in text or "account_master" in low:
        return "10.permissions.account_master"
    if "v189_permission_editor" in text or "permission_editor" in text:
        return "10.permissions.permission_matrix"

    # 13｜系統設定
    if "system_process_categories" in text:
        return "13.system_settings.category_master"
    if "system_process_options" in text:
        return "13.system_settings.category_specific_process_options"
    if "system_rest_periods" in text:
        return "13.system_settings.rest_periods"
    if "category_process" in low:
        return "13.system_settings.category_process_options"

    # global::data_editor::xxx / global::dataframe::xxx -> xxx if possible.
    parts = text.split("::")
    if len(parts) >= 3 and parts[0] == "global":
        tail = parts[-1]
        if tail and tail != text:
            return canonical_table_key(tail, kind=parts[-2] or kind)

    safe = re.sub(r"[^0-9A-Za-z_\.\-\u4e00-\u9fff]+", "_", text).strip("_")
    return safe or "unknown.table"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _load_master() -> dict[str, Any]:
    from services.persistence_core_service import load_master_settings
    return load_master_settings()


def _save_master(master: dict[str, Any], reason: str) -> dict[str, Any]:
    from services.persistence_core_service import save_master_settings
    return save_master_settings(master, reason=reason)


def _normalize_widths(widths: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(widths, dict):
        return out
    for k, v in widths.items():
        try:
            iv = int(float(v))
            if iv > 0:
                out[str(k)] = iv
        except Exception:
            pass
    return out


def _normalize_order(order: Any) -> list[str]:
    if isinstance(order, str):
        try:
            parsed = json.loads(order)
            if isinstance(parsed, list):
                order = parsed
            else:
                order = [x.strip() for x in order.splitlines() if x.strip()]
        except Exception:
            order = [x.strip() for x in order.splitlines() if x.strip()]
    try:
        values = list(order or [])
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in values:
        sx = str(x).strip()
        if sx and sx not in seen:
            out.append(sx)
            seen.add(sx)
    return out


def load_table_settings(table_key: Any) -> dict[str, Any]:
    key = canonical_table_key(table_key)
    master = _load_master()
    settings = master.get("table_settings") if isinstance(master.get("table_settings"), dict) else {}
    data = settings.get(key) if isinstance(settings, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "table_key": key,
        "widths": _normalize_widths(data.get("widths", {})),
        "order": _normalize_order(data.get("order", [])),
        "sort": data.get("sort", {}) if isinstance(data.get("sort"), dict) else {},
    }


def save_table_settings(table_key: Any, *, widths: dict[str, int] | None = None, order: Iterable[str] | None = None, sort: dict[str, Any] | None = None, reason: str = "table_settings_saved") -> dict[str, Any]:
    key = canonical_table_key(table_key)
    master = _load_master()
    table_settings = master.get("table_settings") if isinstance(master.get("table_settings"), dict) else {}
    cur = table_settings.get(key) if isinstance(table_settings.get(key), dict) else {}
    if widths is not None:
        cur["widths"] = _normalize_widths(widths)
    if order is not None:
        cur["order"] = _normalize_order(order)
    if sort is not None:
        cur["sort"] = dict(sort or {})
    cur["updated_at"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
    table_settings[key] = cur
    master["table_settings"] = table_settings
    res = _save_master(master, reason=reason)
    mirror_legacy_table_ui_settings(table_settings)
    return res


def load_column_settings() -> dict[str, Any]:
    master = _load_master()
    data = master.get("column_settings") if isinstance(master.get("column_settings"), dict) else {}
    return dict(data or {})


def save_column_settings(settings: dict[str, Any], *, reason: str = "column_settings_saved") -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for k, v in dict(settings or {}).items():
        key = canonical_table_key(k)
        if isinstance(v, dict):
            normalized[key] = v
    master = _load_master()
    master["column_settings"] = normalized
    res = _save_master(master, reason=reason)
    mirror_legacy_column_settings(normalized)
    return res


def _legacy_payload_table_ui(table_settings: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for key, item in dict(table_settings or {}).items():
        if not isinstance(item, dict):
            continue
        rows.append({
            "table_key": str(key),
            "widths_json": json.dumps(_normalize_widths(item.get("widths", {})), ensure_ascii=False),
            "order_json": json.dumps(_normalize_order(item.get("order", [])), ensure_ascii=False),
            "updated_at": str(item.get("updated_at") or ""),
        })
    return {"version": "V360", "tables": {"table_ui_settings": rows}, "table_counts": {"table_ui_settings": len(rows)}}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def mirror_legacy_table_ui_settings(table_settings: dict[str, Any] | None = None) -> None:
    if table_settings is None:
        master = _load_master()
        table_settings = master.get("table_settings") if isinstance(master.get("table_settings"), dict) else {}
    payload = _legacy_payload_table_ui(table_settings or {})
    paths = [
        PROJECT_ROOT / "data" / "persistent_state" / "spt_table_ui_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "ui_table_settings" / "table_ui_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_ui_settings.json",
    ]
    for path in paths:
        try:
            if path.name.endswith("_settings.json") and path.exists():
                existing = _read_json(path)
                if not isinstance(existing, dict):
                    existing = {}
                existing.setdefault("version", "V360")
                tables = existing.get("tables") if isinstance(existing.get("tables"), dict) else {}
                tables["table_ui_settings"] = payload["tables"]["table_ui_settings"]
                existing["tables"] = tables
                counts = existing.get("table_counts") if isinstance(existing.get("table_counts"), dict) else {}
                counts["table_ui_settings"] = len(payload["tables"]["table_ui_settings"])
                existing["table_counts"] = counts
                _atomic_json(path, existing)
            else:
                _atomic_json(path, payload)
        except Exception:
            pass


def mirror_legacy_column_settings(settings: dict[str, Any] | None = None) -> None:
    if settings is None:
        settings = load_column_settings()
    payload = {"version": "V360", "table_column_settings_v2": settings or {}, "table_count": len(settings or {})}
    paths = [
        PROJECT_ROOT / "data" / "persistent_state" / "spt_table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "ui_table_settings" / "table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "01_time_records" / "01_time_records_table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_column_settings.json",
    ]
    for path in paths:
        try:
            _atomic_json(path, payload)
        except Exception:
            pass


def _extract_legacy_table_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    rows = tables.get("table_ui_settings") if isinstance(tables.get("table_ui_settings"), list) else payload.get("table_ui_settings")
    return [r for r in (rows or []) if isinstance(r, dict)] if isinstance(rows, list) else []


def _extract_legacy_column_settings(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("table_column_settings_v2"), dict):
        return dict(payload.get("table_column_settings_v2") or {})
    if isinstance(payload.get("settings"), dict) and isinstance(payload["settings"].get("table_column_settings_v2"), dict):
        return dict(payload["settings"].get("table_column_settings_v2") or {})
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if isinstance(tables.get("table_column_settings_v2"), dict):
        return dict(tables.get("table_column_settings_v2") or {})
    return {k: v for k, v in payload.items() if isinstance(v, dict) and isinstance(v.get("columns"), dict)}


def migrate_legacy_table_settings_to_master(*, write: bool = True) -> dict[str, Any]:
    """One-time lightweight migration from old JSON settings to V360 master."""
    master = _load_master()
    table_settings = master.get("table_settings") if isinstance(master.get("table_settings"), dict) else {}
    column_settings = master.get("column_settings") if isinstance(master.get("column_settings"), dict) else {}
    table_paths = [
        PROJECT_ROOT / "data" / "persistent_state" / "spt_table_ui_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "ui_table_settings" / "table_ui_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "13_system_settings_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_ui_settings.json",
    ]
    column_paths = [
        PROJECT_ROOT / "data" / "persistent_state" / "spt_table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "ui_table_settings" / "table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "01_time_records" / "01_time_records_table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_table_column_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "13_system_settings_table_column_settings.json",
    ]
    migrated_tables = 0
    migrated_columns = 0
    for path in table_paths:
        payload = _read_json(path)
        for row in _extract_legacy_table_rows(payload):
            raw_key = row.get("table_key")
            key = canonical_table_key(raw_key)
            widths = {}
            order = []
            try:
                widths = json.loads(str(row.get("widths_json") or "{}"))
            except Exception:
                widths = {}
            try:
                order = json.loads(str(row.get("order_json") or "[]"))
            except Exception:
                order = []
            if _normalize_widths(widths) or _normalize_order(order):
                cur = table_settings.get(key) if isinstance(table_settings.get(key), dict) else {}
                if _normalize_widths(widths):
                    cur["widths"] = _normalize_widths(widths)
                if _normalize_order(order):
                    cur["order"] = _normalize_order(order)
                cur["updated_at"] = str(row.get("updated_at") or "")
                table_settings[key] = cur
                migrated_tables += 1
    for path in column_paths:
        payload = _read_json(path)
        data = _extract_legacy_column_settings(payload)
        for k, v in data.items():
            key = canonical_table_key(k)
            if isinstance(v, dict) and isinstance(v.get("columns"), dict):
                column_settings[key] = v
                migrated_columns += 1
    master["table_settings"] = table_settings
    master["column_settings"] = column_settings
    if write and (migrated_tables or migrated_columns):
        _save_master(master, reason="v360_migrate_legacy_table_settings")
        mirror_legacy_table_ui_settings(table_settings)
        mirror_legacy_column_settings(column_settings)
    return {"ok": True, "migrated_table_rows": migrated_tables, "migrated_column_settings": migrated_columns, "table_count": len(table_settings), "column_count": len(column_settings)}


# ===== V3.66 direct-module persistence, same pattern as 03/04 master data =====
# 目的：01 / 10 / 13 的表格設定不要再用「最豐富檔案 / history / GitHub / SQLite 預設」判斷。
# 原則：使用者儲存 -> 直接寫入固定模組 JSON；Reboot -> 直接讀固定模組 JSON。
# SQLite 僅作相容快取，不再是判斷主來源。

import time as _v366_time

_V366_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_table_persistence.json"
_V366_MODULE_FILES = {
    "01": PROJECT_ROOT / "data" / "persistent_modules" / "01_time_records" / "table_persistence.json",
    "10": PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "table_persistence.json",
    "13": PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "table_persistence.json",
    "ui": PROJECT_ROOT / "data" / "persistent_modules" / "ui_table_settings" / "table_persistence.json",
}


def _v366_now_text() -> str:
    try:
        from services.timezone_service import now_text as _nt
        return _nt()
    except Exception:
        return _v366_time.strftime("%Y-%m-%d %H:%M:%S")


def _v366_module_code_for_key(key: str) -> str:
    k = canonical_table_key(key)
    if k.startswith("01."):
        return "01"
    if k.startswith("10."):
        return "10"
    if k.startswith("13."):
        return "13"
    return "ui"


def _v366_blank_payload() -> dict[str, Any]:
    return {
        "version": "V3.66-direct-module-persistence",
        "updated_at": _v366_now_text(),
        "description": "表格設定固定檔。模式比照 03/04：儲存直接寫 latest JSON，Reboot 直接讀 latest JSON，不掃 history、不走 GitHub、不用資料筆數猜測。",
        "table_settings": {},
        "column_settings": {},
    }


def _v366_read_payload(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    # support old unified master shape
    if isinstance(data.get("v360_user_persistent_settings"), dict):
        data = data.get("v360_user_persistent_settings") or {}
    return data


def _v366_load_all_direct() -> dict[str, Any]:
    """Read fixed latest files only; later module files override state file for their own keys."""
    out = _v366_blank_payload()
    for path in [_V366_STATE_FILE, *_V366_MODULE_FILES.values()]:
        data = _v366_read_payload(path)
        if not data:
            continue
        ts = str(data.get("updated_at") or out.get("updated_at") or "")
        if ts:
            out["updated_at"] = ts
        if isinstance(data.get("table_settings"), dict):
            for k, v in data["table_settings"].items():
                ck = canonical_table_key(k)
                if isinstance(v, dict):
                    out["table_settings"][ck] = dict(v)
        if isinstance(data.get("column_settings"), dict):
            for k, v in data["column_settings"].items():
                ck = canonical_table_key(k)
                if isinstance(v, dict):
                    out["column_settings"][ck] = dict(v)
    return out


def _v366_write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v366_write_direct(all_payload: dict[str, Any], changed_key: str | None = None) -> None:
    all_payload = dict(all_payload or {})
    all_payload.setdefault("table_settings", {})
    all_payload.setdefault("column_settings", {})
    all_payload["version"] = "V3.66-direct-module-persistence"
    all_payload["updated_at"] = _v366_now_text()
    _v366_write_payload(_V366_STATE_FILE, all_payload)

    # Write complete shards by module, so 09/manual backup can persist the same way as 03/04.
    for module_code, path in _V366_MODULE_FILES.items():
        shard = _v366_blank_payload()
        shard["updated_at"] = all_payload["updated_at"]
        for k, v in dict(all_payload.get("table_settings") or {}).items():
            if _v366_module_code_for_key(k) == module_code:
                shard["table_settings"][canonical_table_key(k)] = v
        for k, v in dict(all_payload.get("column_settings") or {}).items():
            if _v366_module_code_for_key(k) == module_code:
                shard["column_settings"][canonical_table_key(k)] = v
        # keep ui shard as a complete safety mirror too
        if module_code == "ui":
            shard["table_settings"] = dict(all_payload.get("table_settings") or {})
            shard["column_settings"] = dict(all_payload.get("column_settings") or {})
        _v366_write_payload(path, shard)

    # Maintain older files so existing 09/module center sees the same data.
    try:
        mirror_legacy_table_ui_settings(all_payload.get("table_settings") or {})
    except Exception:
        pass
    try:
        mirror_legacy_column_settings(all_payload.get("column_settings") or {})
    except Exception:
        pass


def load_table_settings(table_key: Any) -> dict[str, Any]:  # type: ignore[override]
    key = canonical_table_key(table_key)
    payload = _v366_load_all_direct()
    settings = payload.get("table_settings") if isinstance(payload.get("table_settings"), dict) else {}
    data = settings.get(key) if isinstance(settings, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "table_key": key,
        "widths": _normalize_widths(data.get("widths", {})),
        "order": _normalize_order(data.get("order", [])),
        "sort": data.get("sort", {}) if isinstance(data.get("sort"), dict) else {},
    }


def save_table_settings(table_key: Any, *, widths: dict[str, int] | None = None, order: Iterable[str] | None = None, sort: dict[str, Any] | None = None, reason: str = "table_settings_saved") -> dict[str, Any]:  # type: ignore[override]
    key = canonical_table_key(table_key)
    payload = _v366_load_all_direct()
    table_settings = payload.get("table_settings") if isinstance(payload.get("table_settings"), dict) else {}
    cur = table_settings.get(key) if isinstance(table_settings.get(key), dict) else {}
    if widths is not None:
        cur["widths"] = _normalize_widths(widths)
    if order is not None:
        cur["order"] = _normalize_order(order)
    if sort is not None:
        cur["sort"] = dict(sort or {})
    cur["updated_at"] = _v366_now_text()
    cur["reason"] = reason
    table_settings[key] = cur
    payload["table_settings"] = table_settings
    _v366_write_direct(payload, changed_key=key)
    return {"ok": True, "mode": "v366_direct", "key": key, "reason": reason, "files": [str(_V366_STATE_FILE), str(_V366_MODULE_FILES[_v366_module_code_for_key(key)])]}


def load_column_settings() -> dict[str, Any]:  # type: ignore[override]
    payload = _v366_load_all_direct()
    data = payload.get("column_settings") if isinstance(payload.get("column_settings"), dict) else {}
    return {canonical_table_key(k): v for k, v in dict(data or {}).items() if isinstance(v, dict)}


def save_column_settings(settings: dict[str, Any], *, reason: str = "column_settings_saved") -> dict[str, Any]:  # type: ignore[override]
    payload = _v366_load_all_direct()
    normalized: dict[str, Any] = {}
    for k, v in dict(settings or {}).items():
        if isinstance(v, dict):
            item = dict(v)
            item["updated_at"] = item.get("updated_at") or _v366_now_text()
            item["reason"] = reason
            normalized[canonical_table_key(k)] = item
    payload["column_settings"] = normalized
    _v366_write_direct(payload)
    return {"ok": True, "mode": "v366_direct", "table_count": len(normalized), "reason": reason, "file": str(_V366_STATE_FILE)}


def migrate_legacy_table_settings_to_master(*, write: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """V366: one-time fallback only when the direct file is still empty; no history scanning."""
    direct = _v366_load_all_direct()
    if direct.get("table_settings") or direct.get("column_settings"):
        return {"ok": True, "mode": "v366_direct_already_exists", "table_count": len(direct.get("table_settings") or {}), "column_count": len(direct.get("column_settings") or {})}
    # Import from the old V360 master if present, once.
    try:
        from services.persistence_core_service import load_master_settings
        old = load_master_settings()
    except Exception:
        old = {}
    imported = _v366_blank_payload()
    if isinstance(old.get("table_settings"), dict):
        imported["table_settings"] = {canonical_table_key(k): v for k, v in old["table_settings"].items() if isinstance(v, dict)}
    if isinstance(old.get("column_settings"), dict):
        imported["column_settings"] = {canonical_table_key(k): v for k, v in old["column_settings"].items() if isinstance(v, dict)}
    if write and (imported["table_settings"] or imported["column_settings"]):
        _v366_write_direct(imported)
    return {"ok": True, "mode": "v366_direct_migrated_from_old_master", "table_count": len(imported["table_settings"]), "column_count": len(imported["column_settings"])}


# ===== V3.67 performance safe mode =====
# 直接持久化保留，但讀取加快取；載入不 migrate、不 mirror、不寫檔。
_V367_DIRECT_CACHE = {"sig": None, "payload": None}

def _v367_direct_paths() -> list[Path]:
    return [_V366_STATE_FILE, *_V366_MODULE_FILES.values()]

def _v367_sig(paths: list[Path]) -> tuple:
    out = []
    for path in paths:
        try:
            if path.exists():
                st = path.stat()
                out.append((str(path), int(st.st_mtime_ns), int(st.st_size)))
            else:
                out.append((str(path), 0, 0))
        except Exception:
            out.append((str(path), -1, -1))
    return tuple(out)

def _v366_load_all_direct() -> dict[str, Any]:  # type: ignore[override]
    paths = _v367_direct_paths()
    sig = _v367_sig(paths)
    try:
        if _V367_DIRECT_CACHE.get("sig") == sig and isinstance(_V367_DIRECT_CACHE.get("payload"), dict):
            # Deep enough copy for nested dict settings without expensive copy module.
            return json.loads(json.dumps(_V367_DIRECT_CACHE["payload"], ensure_ascii=False, default=str))
    except Exception:
        pass
    out = _v366_blank_payload()
    for path in paths:
        data = _v366_read_payload(path)
        if not data:
            continue
        ts = str(data.get("updated_at") or out.get("updated_at") or "")
        if ts:
            out["updated_at"] = ts
        if isinstance(data.get("table_settings"), dict):
            for k, v in data["table_settings"].items():
                ck = canonical_table_key(k)
                if isinstance(v, dict):
                    out["table_settings"][ck] = dict(v)
        if isinstance(data.get("column_settings"), dict):
            for k, v in data["column_settings"].items():
                ck = canonical_table_key(k)
                if isinstance(v, dict):
                    out["column_settings"][ck] = dict(v)
    try:
        _V367_DIRECT_CACHE["sig"] = sig
        _V367_DIRECT_CACHE["payload"] = json.loads(json.dumps(out, ensure_ascii=False, default=str))
    except Exception:
        pass
    return out

def _v366_write_direct(all_payload: dict[str, Any], changed_key: str | None = None) -> None:  # type: ignore[override]
    # V367: 寫入固定 latest JSON；舊格式鏡像改為可選停用，避免一次儲存造成大量檔案寫入。
    all_payload = dict(all_payload or {})
    all_payload.setdefault("table_settings", {})
    all_payload.setdefault("column_settings", {})
    all_payload["version"] = "V3.67-direct-module-persistence-fast"
    all_payload["updated_at"] = _v366_now_text()
    _v366_write_payload(_V366_STATE_FILE, all_payload)
    for module_code, path in _V366_MODULE_FILES.items():
        shard = _v366_blank_payload()
        shard["version"] = "V3.67-direct-module-persistence-fast"
        shard["updated_at"] = all_payload["updated_at"]
        for k, v in dict(all_payload.get("table_settings") or {}).items():
            if _v366_module_code_for_key(k) == module_code:
                shard["table_settings"][canonical_table_key(k)] = v
        for k, v in dict(all_payload.get("column_settings") or {}).items():
            if _v366_module_code_for_key(k) == module_code:
                shard["column_settings"][canonical_table_key(k)] = v
        if module_code == "ui":
            shard["table_settings"] = dict(all_payload.get("table_settings") or {})
            shard["column_settings"] = dict(all_payload.get("column_settings") or {})
        _v366_write_payload(path, shard)
    try:
        _V367_DIRECT_CACHE["sig"] = _v367_sig(_v367_direct_paths())
        _V367_DIRECT_CACHE["payload"] = json.loads(json.dumps(all_payload, ensure_ascii=False, default=str))
    except Exception:
        pass
    # 舊格式鏡像只在明確開啟時執行；一般點頁/儲存不再大量寫舊檔。
    try:
        import os
        if os.environ.get("SPT_WRITE_LEGACY_TABLE_MIRRORS", "").strip() == "1":
            mirror_legacy_table_ui_settings(all_payload.get("table_settings") or {})
            mirror_legacy_column_settings(all_payload.get("column_settings") or {})
    except Exception:
        pass

def migrate_legacy_table_settings_to_master(*, write: bool = False) -> dict[str, Any]:  # type: ignore[override]
    # V367: 一般載入完全不 migrate。直接檔存在就回報；不存在也不掃 history。
    direct = _v366_load_all_direct()
    return {"ok": True, "mode": "v367_no_load_migration", "table_count": len(direct.get("table_settings") or {}), "column_count": len(direct.get("column_settings") or {}), "write": False}

# ===== V3.70 direct latest settings file persistence, same as 03/04 modules =====
# 背景：V366/V367 將表格設定寫到 table_persistence.json，但 03/04 成功模式是
# data/persistent_modules/<module>/<module>_settings.json 或 <module>_records.json 這種 latest 固定檔。
# 09｜資料永久保存與備份 / GitHub 同步通常會優先處理 <module>_settings.json。
# 因此 01｜工時紀錄表格設定改為：儲存時同步寫入 01_time_records_settings.json；
# Reboot 時優先從同一固定 latest settings 檔讀回，不再只靠 table_persistence.json。

_V370_MODULE_SETTINGS_FILES = {
    "01": PROJECT_ROOT / "data" / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
    "10": PROJECT_ROOT / "data" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
    "13": PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "13_system_settings_settings.json",
    "ui": PROJECT_ROOT / "data" / "persistent_modules" / "ui_table_settings" / "ui_table_settings_settings.json",
}
_V370_13_SYSTEM_SETTINGS_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "system_settings.json"


def _v370_stamp_to_float(value: Any, fallback: float = 0.0) -> float:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        # YYYY-MM-DD HH:MM:SS / YYYY/MM/DD HH:MM:SS are lexicographically stable after normalization.
        import datetime as _dt
        norm = text.replace("/", "-").replace("T", " ")[:19]
        return _dt.datetime.fromisoformat(norm).timestamp()
    except Exception:
        return fallback


def _v370_extract_table_settings_from_payload(payload: dict[str, Any], *, path_mtime: float = 0.0) -> dict[str, dict[str, Any]]:
    """Extract canonical table_settings from all supported latest-file shapes."""
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("v360_user_persistent_settings"), dict):
        payload = payload.get("v360_user_persistent_settings") or {}
    out: dict[str, dict[str, Any]] = {}

    def put(raw_key: Any, item: Any, updated_hint: Any = None) -> None:
        key = canonical_table_key(raw_key)
        if not key or not isinstance(item, dict):
            return
        widths = _normalize_widths(item.get("widths", {}))
        order = _normalize_order(item.get("order", []))
        sort = item.get("sort", {}) if isinstance(item.get("sort"), dict) else {}
        if not widths and not order and not sort:
            return
        row = {"widths": widths, "order": order, "sort": sort}
        row["updated_at"] = str(item.get("updated_at") or updated_hint or payload.get("updated_at") or "")
        row["reason"] = str(item.get("reason") or payload.get("reason") or "")
        out[key] = row

    if isinstance(payload.get("table_settings"), dict):
        for k, v in (payload.get("table_settings") or {}).items():
            put(k, v)
    ui = payload.get("ui") if isinstance(payload.get("ui"), dict) else {}
    if isinstance(ui.get("table_settings"), dict):
        for k, v in (ui.get("table_settings") or {}).items():
            put(k, v)
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if isinstance(tables.get("table_settings"), dict):
        for k, v in (tables.get("table_settings") or {}).items():
            put(k, v)
    rows = tables.get("table_ui_settings") if isinstance(tables.get("table_ui_settings"), list) else payload.get("table_ui_settings")
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                widths = json.loads(str(r.get("widths_json") or "{}"))
            except Exception:
                widths = {}
            try:
                order = json.loads(str(r.get("order_json") or "[]"))
            except Exception:
                order = []
            put(r.get("table_key"), {"widths": widths, "order": order, "updated_at": r.get("updated_at")}, r.get("updated_at"))
    # Ensure every row has a comparable update stamp.
    for item in out.values():
        item["_updated_num"] = _v370_stamp_to_float(item.get("updated_at"), path_mtime)
    return out


def _v370_extract_column_settings_from_payload(payload: dict[str, Any], *, path_mtime: float = 0.0) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("v360_user_persistent_settings"), dict):
        payload = payload.get("v360_user_persistent_settings") or {}
    candidates: list[dict[str, Any]] = []
    if isinstance(payload.get("column_settings"), dict):
        candidates.append(payload.get("column_settings") or {})
    ui = payload.get("ui") if isinstance(payload.get("ui"), dict) else {}
    if isinstance(ui.get("column_settings"), dict):
        candidates.append(ui.get("column_settings") or {})
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if isinstance(tables.get("column_settings"), dict):
        candidates.append(tables.get("column_settings") or {})
    if isinstance(payload.get("table_column_settings_v2"), dict):
        candidates.append(payload.get("table_column_settings_v2") or {})
    out: dict[str, dict[str, Any]] = {}
    for data in candidates:
        for k, v in dict(data or {}).items():
            if isinstance(v, dict):
                item = dict(v)
                item.setdefault("updated_at", payload.get("updated_at") or "")
                item["_updated_num"] = _v370_stamp_to_float(item.get("updated_at"), path_mtime)
                out[canonical_table_key(k)] = item
    return out


def _v370_direct_paths() -> list[Path]:
    paths = [
        _V366_STATE_FILE,
        *_V366_MODULE_FILES.values(),
        *_V370_MODULE_SETTINGS_FILES.values(),
        _V370_13_SYSTEM_SETTINGS_FILE,
        PROJECT_ROOT / "data" / "persistent_state" / "spt_user_persistent_settings.json",
        PROJECT_ROOT / "data" / "persistent_state" / "spt_module_settings.json",
    ]
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def _v370_load_all_direct_latest() -> dict[str, Any]:
    payload = _v366_blank_payload()
    table_items: dict[str, dict[str, Any]] = {}
    column_items: dict[str, dict[str, Any]] = {}
    newest = 0.0
    for path in _v370_direct_paths():
        data = _v366_read_payload(path)
        if not data:
            continue
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
        except Exception:
            mtime = 0.0
        newest = max(newest, mtime)
        for k, item in _v370_extract_table_settings_from_payload(data, path_mtime=mtime).items():
            if k not in table_items or float(item.get("_updated_num") or 0) >= float(table_items[k].get("_updated_num") or 0):
                table_items[k] = item
        for k, item in _v370_extract_column_settings_from_payload(data, path_mtime=mtime).items():
            if k not in column_items or float(item.get("_updated_num") or 0) >= float(column_items[k].get("_updated_num") or 0):
                column_items[k] = item
    for item in table_items.values():
        item.pop("_updated_num", None)
    for item in column_items.values():
        item.pop("_updated_num", None)
    payload["table_settings"] = table_items
    payload["column_settings"] = column_items
    payload["updated_at"] = _v366_now_text() if newest else str(payload.get("updated_at") or _v366_now_text())
    payload["version"] = "V3.70-direct-latest-settings-file"
    return payload


def _v370_table_rows_from_settings(table_settings: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for k, v in dict(table_settings or {}).items():
        if not isinstance(v, dict):
            continue
        rows.append({
            "table_key": canonical_table_key(k),
            "widths_json": json.dumps(_normalize_widths(v.get("widths", {})), ensure_ascii=False),
            "order_json": json.dumps(_normalize_order(v.get("order", [])), ensure_ascii=False),
            "updated_at": str(v.get("updated_at") or _v366_now_text()),
        })
    return rows


def _v370_write_settings_file(path: Path, module_code: str, shard: dict[str, Any]) -> None:
    existing = _read_json(path)
    if not isinstance(existing, dict):
        existing = {}
    existing["version"] = "V3.70-direct-latest-settings-file"
    existing["updated_at"] = shard.get("updated_at") or _v366_now_text()
    existing["module_key"] = module_code
    existing["description"] = "表格欄寬/欄位順序設定固定 latest 檔；讀寫方式比照 03/04 模組。"
    existing["table_settings"] = dict(shard.get("table_settings") or {})
    existing["column_settings"] = dict(shard.get("column_settings") or {})
    ui = existing.get("ui") if isinstance(existing.get("ui"), dict) else {}
    ui["table_settings"] = dict(shard.get("table_settings") or {})
    ui["column_settings"] = dict(shard.get("column_settings") or {})
    existing["ui"] = ui
    tables = existing.get("tables") if isinstance(existing.get("tables"), dict) else {}
    rows = _v370_table_rows_from_settings(shard.get("table_settings") or {})
    tables["table_ui_settings"] = rows
    existing["tables"] = tables
    counts = existing.get("table_counts") if isinstance(existing.get("table_counts"), dict) else {}
    counts["table_ui_settings"] = len(rows)
    existing["table_counts"] = counts
    _v366_write_payload(path, existing)


def _v370_write_direct(all_payload: dict[str, Any], changed_key: str | None = None) -> None:
    all_payload = dict(all_payload or {})
    all_payload.setdefault("table_settings", {})
    all_payload.setdefault("column_settings", {})
    all_payload["version"] = "V3.70-direct-latest-settings-file"
    all_payload["updated_at"] = _v366_now_text()

    # 1) 全域快速檔，保留 V366/V367 成功模式。
    _v366_write_payload(_V366_STATE_FILE, all_payload)

    # 2) 各模組固定 latest 檔，這才是 03/04 的成功模式：<module>/<module>_settings.json。
    for module_code, path in _V366_MODULE_FILES.items():
        shard = _v366_blank_payload()
        shard["version"] = "V3.70-direct-latest-settings-file"
        shard["updated_at"] = all_payload["updated_at"]
        for k, v in dict(all_payload.get("table_settings") or {}).items():
            if _v366_module_code_for_key(k) == module_code:
                shard["table_settings"][canonical_table_key(k)] = v
        for k, v in dict(all_payload.get("column_settings") or {}).items():
            if _v366_module_code_for_key(k) == module_code:
                shard["column_settings"][canonical_table_key(k)] = v
        if module_code == "ui":
            shard["table_settings"] = dict(all_payload.get("table_settings") or {})
            shard["column_settings"] = dict(all_payload.get("column_settings") or {})
        _v366_write_payload(path, shard)
        if module_code in _V370_MODULE_SETTINGS_FILES:
            _v370_write_settings_file(_V370_MODULE_SETTINGS_FILES[module_code], module_code, shard)
    # 13 額外寫入既有 system_settings.json，但不清除其中原本的系統設定內容。
    try:
        thirteen = _v366_blank_payload()
        thirteen["updated_at"] = all_payload["updated_at"]
        for k, v in dict(all_payload.get("table_settings") or {}).items():
            if _v366_module_code_for_key(k) == "13":
                thirteen["table_settings"][canonical_table_key(k)] = v
        for k, v in dict(all_payload.get("column_settings") or {}).items():
            if _v366_module_code_for_key(k) == "13":
                thirteen["column_settings"][canonical_table_key(k)] = v
        if thirteen["table_settings"] or thirteen["column_settings"]:
            _v370_write_settings_file(_V370_13_SYSTEM_SETTINGS_FILE, "13", thirteen)
    except Exception:
        pass
    try:
        _V367_DIRECT_CACHE["sig"] = _v367_sig(_v370_direct_paths())
        _V367_DIRECT_CACHE["payload"] = json.loads(json.dumps(all_payload, ensure_ascii=False, default=str))
    except Exception:
        pass


def load_table_settings(table_key: Any) -> dict[str, Any]:  # type: ignore[override]
    key = canonical_table_key(table_key)
    payload = _v370_load_all_direct_latest()
    settings = payload.get("table_settings") if isinstance(payload.get("table_settings"), dict) else {}
    data = settings.get(key) if isinstance(settings, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "table_key": key,
        "widths": _normalize_widths(data.get("widths", {})),
        "order": _normalize_order(data.get("order", [])),
        "sort": data.get("sort", {}) if isinstance(data.get("sort"), dict) else {},
    }


def save_table_settings(table_key: Any, *, widths: dict[str, int] | None = None, order: Iterable[str] | None = None, sort: dict[str, Any] | None = None, reason: str = "table_settings_saved") -> dict[str, Any]:  # type: ignore[override]
    key = canonical_table_key(table_key)
    payload = _v370_load_all_direct_latest()
    table_settings = payload.get("table_settings") if isinstance(payload.get("table_settings"), dict) else {}
    cur = table_settings.get(key) if isinstance(table_settings.get(key), dict) else {}
    if widths is not None:
        cur["widths"] = _normalize_widths(widths)
    if order is not None:
        cur["order"] = _normalize_order(order)
    if sort is not None:
        cur["sort"] = dict(sort or {})
    cur["updated_at"] = _v366_now_text()
    cur["reason"] = reason
    table_settings[key] = cur
    payload["table_settings"] = table_settings
    _v370_write_direct(payload, changed_key=key)
    return {
        "ok": True,
        "mode": "v370_direct_latest_settings_file",
        "key": key,
        "reason": reason,
        "files": [
            str(_V366_STATE_FILE),
            str(_V366_MODULE_FILES[_v366_module_code_for_key(key)]),
            str(_V370_MODULE_SETTINGS_FILES.get(_v366_module_code_for_key(key), _V370_MODULE_SETTINGS_FILES["ui"])),
        ],
    }


def load_column_settings() -> dict[str, Any]:  # type: ignore[override]
    payload = _v370_load_all_direct_latest()
    data = payload.get("column_settings") if isinstance(payload.get("column_settings"), dict) else {}
    return {canonical_table_key(k): v for k, v in dict(data or {}).items() if isinstance(v, dict)}


def save_column_settings(settings: dict[str, Any], *, reason: str = "column_settings_saved") -> dict[str, Any]:  # type: ignore[override]
    payload = _v370_load_all_direct_latest()
    normalized: dict[str, Any] = {}
    for k, v in dict(settings or {}).items():
        if isinstance(v, dict):
            item = dict(v)
            item["updated_at"] = item.get("updated_at") or _v366_now_text()
            item["reason"] = reason
            normalized[canonical_table_key(k)] = item
    payload["column_settings"] = normalized
    _v370_write_direct(payload)
    return {"ok": True, "mode": "v370_direct_latest_settings_file", "table_count": len(normalized), "reason": reason, "file": str(_V366_STATE_FILE)}


def migrate_legacy_table_settings_to_master(*, write: bool = False) -> dict[str, Any]:  # type: ignore[override]
    direct = _v370_load_all_direct_latest()
    return {
        "ok": True,
        "mode": "v370_direct_latest_settings_file_no_load_migration",
        "table_count": len(direct.get("table_settings") or {}),
        "column_count": len(direct.get("column_settings") or {}),
        "write": False,
    }
