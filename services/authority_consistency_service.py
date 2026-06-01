# -*- coding: utf-8 -*-
"""V300.17 authority consistency helpers.

Low-risk helpers for modules that need one reboot-stable authority path.
This module does not import Streamlit at import time and does not touch 01/02.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"

MODULE_ALIASES = {
    "06_logs": "06_log_query",
    "06_system_logs": "06_log_query",
    "06_log_query": "06_log_query",
    "11_login_logs": "11_login_records",
    "11_login_records": "11_login_records",
    "10_permissions": "10_permissions",
    "13_system_settings": "13_system_settings",
}


def now_text() -> str:
    try:
        from services.timezone_service import now_text as _nt  # type: ignore
        return str(_nt())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def module_key(key: str) -> str:
    return MODULE_ALIASES.get(str(key), str(key))


def module_dir(key: str) -> Path:
    return AUTH_ROOT / module_key(key)


def records_jsonl_path(key: str) -> Path:
    return module_dir(key) / "records.jsonl"


def records_json_path(key: str) -> Path:
    return module_dir(key) / "records.json"


def settings_json_path(key: str) -> Path:
    return module_dir(key) / "settings.json"


def manifest_path(key: str) -> Path:
    return module_dir(key) / "authority_manifest.json"


def _json_default(v: Any) -> Any:
    try:
        import pandas as pd  # type: ignore
        if pd.isna(v):
            return ""
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return str(v)


def safe_text(v: Any) -> str:
    if v is None:
        return ""
    try:
        import pandas as pd  # type: ignore
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.lower() in {"none", "nan", "null", "<na>"}:
        return ""
    return s


def stable_id(row: dict[str, Any], fields: Iterable[str] | None = None) -> str:
    if fields:
        text = "|".join(safe_text(row.get(f)) for f in fields)
    else:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 1:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def ensure_module_authority(key: str, *, mode: str = "records") -> dict[str, Any]:
    k = module_key(key)
    d = module_dir(k)
    d.mkdir(parents=True, exist_ok=True)
    if mode == "jsonl":
        p = records_jsonl_path(k)
        if not p.exists():
            p.write_text("", encoding="utf-8")
    else:
        p = records_json_path(k)
        if not p.exists():
            atomic_write_json(p, {
                "authority_schema": "SPT_MODULE_AUTHORITY_V1",
                "module_key": k,
                "kind": "records",
                "updated_at": now_text(),
                "tables": {},
                "settings": {},
                "table_counts": {},
            })
    m = manifest_path(k)
    if not m.exists():
        atomic_write_json(m, {
            "authority_schema": "SPT_MODULE_AUTHORITY_MANIFEST_V1",
            "module_key": k,
            "mode": mode,
            "created_at": now_text(),
            "updated_at": now_text(),
            "rule": "single authority path; legacy sources must not overwrite after reboot",
        })
    return {"ok": True, "module_key": k, "authority_dir": str(d), "mode": mode}


def append_jsonl(key: str, row: dict[str, Any], *, identity_fields: Iterable[str] | None = None, github: bool = False, reason: str = "append_jsonl") -> dict[str, Any]:
    k = module_key(key)
    ensure_module_authority(k, mode="jsonl")
    clean = dict(row or {})
    clean.setdefault("authority_module_key", k)
    clean.setdefault("authority_written_at", now_text())
    clean.setdefault("authority_event_id", stable_id(clean, identity_fields))
    path = records_jsonl_path(k)
    line = json.dumps(clean, ensure_ascii=False, default=_json_default)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    atomic_write_json(manifest_path(k), {
        "authority_schema": "SPT_MODULE_AUTHORITY_MANIFEST_V1",
        "module_key": k,
        "mode": "jsonl",
        "updated_at": now_text(),
        "last_reason": reason,
        "records_file": "records.jsonl",
    })
    upload = None
    if github:
        upload = upload_authority_file(k, "records.jsonl", reason=reason)
    return {"ok": True, "module_key": k, "path": str(path), "event_id": clean.get("authority_event_id"), "github_upload": upload}


def read_jsonl(key: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    k = module_key(key)
    path = records_jsonl_path(k)
    rows: list[dict[str, Any]] = []
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if limit and limit > 0:
            lines = lines[-int(limit):]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        return []
    return rows


def merge_by_event_id(rows: Iterable[dict[str, Any]], *, id_fields: Iterable[str] | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        key = safe_text(r.get("authority_event_id")) or stable_id(r, id_fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(r))
    return out


def upload_authority_file(key: str, filename: str, *, reason: str = "authority_upload") -> dict[str, Any]:
    k = module_key(key)
    local = module_dir(k) / filename
    if not local.exists():
        return {"ok": False, "error": "local_file_missing", "path": str(local)}
    remote = f"data/permanent_store/modules/{k}/{filename}"
    try:
        from services.github_cloud_storage_service import upload_file_to_github
        res = upload_file_to_github(local, remote, f"SPT V300.17 authority {k} {reason} {now_text()}")
        return dict(res or {"ok": True})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "path": str(local), "remote": remote}


def save_settings(key: str, settings: dict[str, Any], *, github: bool = True, reason: str = "save_settings") -> dict[str, Any]:
    k = module_key(key)
    ensure_module_authority(k, mode="records")
    payload = {
        "authority_schema": "SPT_MODULE_SETTINGS_V1",
        "module_key": k,
        "kind": "settings",
        "updated_at": now_text(),
        "reason": reason,
        "settings": dict(settings or {}),
    }
    path = settings_json_path(k)
    atomic_write_json(path, payload)
    upload = upload_authority_file(k, "settings.json", reason=reason) if github else None
    return {"ok": True, "module_key": k, "path": str(path), "github_upload": upload}


def audit_authority_consistency() -> dict[str, Any]:
    modules = ["06_log_query", "10_permissions", "11_login_records", "13_system_settings"]
    out: dict[str, Any] = {"version": "V300.17", "generated_at": now_text(), "modules": {}}
    for k in modules:
        d = module_dir(k)
        out["modules"][k] = {
            "authority_dir_exists": d.exists(),
            "records_json_exists": records_json_path(k).exists(),
            "records_jsonl_exists": records_jsonl_path(k).exists(),
            "settings_json_exists": settings_json_path(k).exists(),
            "manifest_exists": manifest_path(k).exists(),
        }
    return out
