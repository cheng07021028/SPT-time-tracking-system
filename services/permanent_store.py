# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORE_ROOT = PROJECT_ROOT / "data" / "permanent_store"
MODULE_ROOT = STORE_ROOT / "modules"
SYSTEM_ROOT = STORE_ROOT / "system"
BACKUP_ROOT = STORE_ROOT / "_backups"
SCHEMA_VERSION = "clean-v1.0"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_store() -> None:
    for p in [STORE_ROOT, MODULE_ROOT, SYSTEM_ROOT, BACKUP_ROOT]:
        p.mkdir(parents=True, exist_ok=True)
    manifest = STORE_ROOT / "manifest.json"
    if not manifest.exists():
        atomic_write_json(manifest, {
            "schema_version": SCHEMA_VERSION,
            "created_at": now_str(),
            "official_root": "data/permanent_store",
            "rule": "Only this root is the official read/write source. Defaults are created only when a file is missing.",
        }, backup=False)


def _json_default(obj: Any) -> Any:
    try:
        import pandas as pd
        if pd.isna(obj):
            return None
    except Exception:
        pass
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def read_json(path: Path, default: Any = None) -> Any:
    ensure_store()
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        corrupt = path.with_suffix(path.suffix + f".corrupt_{stamp()}")
        try:
            shutil.copy2(path, corrupt)
        except Exception:
            pass
        return default


def atomic_write_json(path: Path, data: Any, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        rel = path.relative_to(STORE_ROOT) if STORE_ROOT in path.parents else path.name
        bdir = BACKUP_ROOT / str(rel).replace(os.sep, "__")
        bdir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, bdir / f"{path.stem}_{stamp()}{path.suffix}")
        except Exception:
            pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    ensure_store()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            val = json.loads(line)
            if isinstance(val, dict):
                rows.append(val)
        except Exception:
            continue
    return rows


def module_dir(module_key: str) -> Path:
    ensure_store()
    p = MODULE_ROOT / module_key
    p.mkdir(parents=True, exist_ok=True)
    (p / "backups").mkdir(exist_ok=True)
    return p


def module_records_path(module_key: str) -> Path:
    return module_dir(module_key) / "records.json"


def module_settings_path(module_key: str) -> Path:
    return module_dir(module_key) / "settings.json"


def load_records(module_key: str, default_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    path = module_records_path(module_key)
    if not path.exists():
        rows = list(default_rows or [])
        atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "created_at": now_str(), "updated_at": now_str(), "rows": rows}, backup=False)
        return rows
    data = read_json(path, {})
    if isinstance(data, dict):
        rows = data.get("rows", [])
        return rows if isinstance(rows, list) else []
    if isinstance(data, list):
        return data
    return []


def save_records(module_key: str, rows: list[dict[str, Any]], user: str = "SYSTEM", action: str = "save_records") -> None:
    path = module_records_path(module_key)
    old = read_json(path, {}) if path.exists() else {}
    created_at = old.get("created_at") if isinstance(old, dict) else now_str()
    atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "created_at": created_at or now_str(), "updated_at": now_str(), "updated_by": user, "rows": rows})
    log_event(module_key, action, user, "OK", f"saved {len(rows)} rows")


def load_settings(module_key: str, default_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    path = module_settings_path(module_key)
    if not path.exists():
        settings = dict(default_settings or {})
        atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "created_at": now_str(), "updated_at": now_str(), "settings": settings}, backup=False)
        return settings
    data = read_json(path, {})
    if isinstance(data, dict) and isinstance(data.get("settings"), dict):
        return data["settings"]
    if isinstance(data, dict):
        return data
    return dict(default_settings or {})


def save_settings(module_key: str, settings: dict[str, Any], user: str = "SYSTEM", action: str = "save_settings") -> None:
    path = module_settings_path(module_key)
    old = read_json(path, {}) if path.exists() else {}
    created_at = old.get("created_at") if isinstance(old, dict) else now_str()
    atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "created_at": created_at or now_str(), "updated_at": now_str(), "updated_by": user, "settings": settings})
    log_event(module_key, action, user, "OK", "settings saved")


def system_path(name: str) -> Path:
    ensure_store()
    return SYSTEM_ROOT / name


def load_system(name: str, default: Any = None) -> Any:
    path = system_path(name)
    if not path.exists():
        atomic_write_json(path, default, backup=False)
        return default
    return read_json(path, default)


def save_system(name: str, data: Any) -> None:
    atomic_write_json(system_path(name), data)


def log_event(module_key: str, action: str, user: str, result: str = "OK", message: str = "") -> None:
    row = {"時間": now_str(), "模組": module_key, "動作": action, "使用者": user, "結果": result, "訊息": message}
    append_jsonl(system_path("audit_logs.jsonl"), row)
    append_jsonl(module_dir(module_key) / "audit.jsonl", row)


def store_health() -> dict[str, Any]:
    ensure_store()
    modules = []
    for p in sorted(MODULE_ROOT.iterdir()):
        if not p.is_dir():
            continue
        rec = p / "records.json"
        sett = p / "settings.json"
        modules.append({
            "模組": p.name,
            "records存在": rec.exists(),
            "records大小KB": round(rec.stat().st_size / 1024, 2) if rec.exists() else 0,
            "settings存在": sett.exists(),
            "settings大小KB": round(sett.stat().st_size / 1024, 2) if sett.exists() else 0,
            "最後更新": datetime.fromtimestamp(max([x.stat().st_mtime for x in [rec, sett] if x.exists()] or [p.stat().st_mtime])).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return {"root": str(STORE_ROOT.relative_to(PROJECT_ROOT)), "modules": modules}

ensure_store()
