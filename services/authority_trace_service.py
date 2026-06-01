# -*- coding: utf-8 -*-
"""V300.15 authority read/write trace utilities.

This module is intentionally additive and non-invasive:
- It does not change 01/02 business logic.
- It does not write or overwrite module records.json data.
- It only inspects expected authority paths, legacy paths, and writes trace reports.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MODULES_TO_TRACE = {
    "06_log_query": {
        "module_no": "06",
        "title": "LOG查詢",
        "authority_dir": "data/permanent_store/modules/06_log_query",
        "preferred_records": ["records.jsonl", "records.json"],
        "legacy_candidates": [
            "data/logs",
            "data/persistent_modules/06_log_query",
            "data/persistent_state/06_log_query",
            "data/performance",
        ],
        "expected_mode": "append-only for log/event data",
    },
    "10_permissions": {
        "module_no": "10",
        "title": "權限管理",
        "authority_dir": "data/permanent_store/modules/10_permissions",
        "preferred_records": ["records.json", "security_runtime_settings.json", "settings.json"],
        "legacy_candidates": [
            "data/persistent_modules/10_permissions",
            "data/persistent_state/10_permissions",
            "data/persistent_modules/permission_management",
            "data/persistent_state/permission_management",
        ],
        "expected_mode": "records.json + independent runtime security settings",
    },
    "11_login_records": {
        "module_no": "11",
        "title": "登入紀錄",
        "authority_dir": "data/permanent_store/modules/11_login_records",
        "preferred_records": ["records.jsonl", "records.json"],
        "legacy_candidates": [
            "data/persistent_modules/11_login_records",
            "data/persistent_state/11_login_records",
            "data/login_logs",
            "data/security",
        ],
        "expected_mode": "append-only login event data",
    },
    "13_system_settings": {
        "module_no": "13",
        "title": "系統設定",
        "authority_dir": "data/permanent_store/modules/13_system_settings",
        "preferred_records": ["records.json", "settings.json", "tombstones.json"],
        "legacy_candidates": [
            "data/persistent_modules/13_system_settings",
            "data/persistent_state/13_system_settings",
            "data/config",
            "data/system_settings",
        ],
        "expected_mode": "records.json + settings.json; do not alter 01/02 runtime links automatically",
    },
}

TRACE_DIR = Path("data/permanent_store/authority_trace")
TRACE_FILE = TRACE_DIR / "v30015_authority_trace.jsonl"
SNAPSHOT_FILE = TRACE_DIR / "v30015_latest_snapshot.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_json_load(path: Path) -> Any:
    try:
        if not path.exists() or not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        if path.suffix.lower() == ".jsonl":
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    rows.append({"_invalid_jsonl_line": line[:200]})
            return rows
        return json.loads(text)
    except Exception as exc:
        return {"_read_error": str(exc)}


def _summarize_file(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "path": str(path).replace("\\", "/"),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }
    if path.exists():
        try:
            st = path.stat()
            info.update({
                "size_bytes": st.st_size,
                "modified_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        except Exception as exc:
            info["stat_error"] = str(exc)
    if path.exists() and path.is_file() and path.suffix.lower() in {".json", ".jsonl"}:
        data = _safe_json_load(path)
        if isinstance(data, dict):
            info["json_type"] = "object"
            info["top_keys"] = list(data.keys())[:40]
            for key in ("users", "accounts", "permissions", "account_permissions", "auth_security_settings", "settings", "records"):
                val = data.get(key)
                if isinstance(val, list):
                    info[f"{key}_count"] = len(val)
                elif isinstance(val, dict):
                    info[f"{key}_keys_count"] = len(val)
        elif isinstance(data, list):
            info["json_type"] = "array"
            info["row_count"] = len(data)
        elif data is not None:
            info["json_type"] = type(data).__name__
    return info


def inspect_module_authority(project_root: str | os.PathLike[str] = ".", module_key: Optional[str] = None) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    selected = MODULES_TO_TRACE
    if module_key:
        selected = {module_key: MODULES_TO_TRACE[module_key]}
    result: Dict[str, Any] = {
        "generated_at": _now(),
        "project_root": str(root).replace("\\", "/"),
        "modules": {},
    }
    for key, cfg in selected.items():
        authority_dir = root / cfg["authority_dir"]
        module_info: Dict[str, Any] = {
            "module_key": key,
            "module_no": cfg["module_no"],
            "title": cfg["title"],
            "expected_mode": cfg["expected_mode"],
            "authority_dir": _summarize_file(authority_dir),
            "authority_files": {},
            "legacy_candidates": {},
            "warnings": [],
        }
        for filename in cfg["preferred_records"]:
            p = authority_dir / filename
            module_info["authority_files"][filename] = _summarize_file(p)
        for rel in cfg["legacy_candidates"]:
            p = root / rel
            module_info["legacy_candidates"][rel] = _summarize_file(p)
        has_authority = any(v.get("exists") for v in module_info["authority_files"].values())
        has_legacy = any(v.get("exists") for v in module_info["legacy_candidates"].values())
        if not has_authority:
            module_info["warnings"].append("Missing expected authority file(s).")
        if has_legacy:
            module_info["warnings"].append("Legacy source exists; verify it does not overwrite authority after reboot.")
        if key in {"06_log_query", "11_login_records"}:
            if not ((authority_dir / "records.jsonl").exists() or (authority_dir / "records.json").exists()):
                module_info["warnings"].append("Append-only module has no records.jsonl/records.json authority file yet.")
        result["modules"][key] = module_info
    return result


def write_authority_trace_event(
    module_key: str,
    action: str,
    before: Optional[Any] = None,
    after: Optional[Any] = None,
    read_source: Optional[str] = None,
    write_target: Optional[str] = None,
    ok: bool = True,
    note: str = "",
    project_root: str | os.PathLike[str] = ".",
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    trace_dir = root / TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": _now(),
        "module_key": module_key,
        "action": action,
        "read_source": read_source,
        "write_target": write_target,
        "ok": ok,
        "note": note,
        "before_preview": _preview_value(before),
        "after_preview": _preview_value(after),
    }
    with (root / TRACE_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def _preview_value(value: Any, limit: int = 500) -> Any:
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def save_snapshot(project_root: str | os.PathLike[str] = ".") -> Dict[str, Any]:
    root = Path(project_root).resolve()
    snapshot = inspect_module_authority(root)
    trace_dir = root / TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    (root / SNAPSHOT_FILE).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def render_markdown_report(snapshot: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# V300.15 Authority Read/Write Chain Diagnostic Report")
    lines.append("")
    lines.append(f"Generated at: `{snapshot.get('generated_at')}`")
    lines.append(f"Project root: `{snapshot.get('project_root')}`")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("This diagnostic package inspects authority-file readiness for modules 06, 10, 11, and 13 only. It does not modify 01/02 logic or overwrite module data.")
    lines.append("")
    for key, info in snapshot.get("modules", {}).items():
        lines.append(f"## {info.get('module_no')}. {info.get('title')} (`{key}`)")
        lines.append("")
        lines.append(f"Expected mode: {info.get('expected_mode')}")
        ad = info.get("authority_dir", {})
        lines.append(f"Authority dir: `{ad.get('path')}` exists={ad.get('exists')}")
        lines.append("")
        lines.append("### Authority files")
        for name, finfo in info.get("authority_files", {}).items():
            parts = [f"- `{name}` exists={finfo.get('exists')}"]
            if finfo.get("size_bytes") is not None:
                parts.append(f"size={finfo.get('size_bytes')}")
            if finfo.get("row_count") is not None:
                parts.append(f"rows={finfo.get('row_count')}")
            for count_key in [k for k in finfo.keys() if k.endswith("_count") or k.endswith("_keys_count")]:
                parts.append(f"{count_key}={finfo[count_key]}")
            lines.append(" ".join(parts))
        lines.append("")
        legacy_exists = [rel for rel, v in info.get("legacy_candidates", {}).items() if v.get("exists")]
        lines.append("### Legacy candidates")
        if legacy_exists:
            for rel in legacy_exists:
                lines.append(f"- `{rel}` exists; verify it is not used to overwrite authority after reboot.")
        else:
            lines.append("- No configured legacy candidate exists.")
        warnings = info.get("warnings") or []
        if warnings:
            lines.append("")
            lines.append("### Warnings")
            for w in warnings:
                lines.append(f"- {w}")
        lines.append("")
    lines.append("## Next action after this diagnostic")
    lines.append("")
    lines.append("Use `data/permanent_store/authority_trace/v30015_latest_snapshot.json` and this report to identify whether each module reads, writes, and reboots from the same authority path. Only after confirming the mismatched path should V300.16 change production read/write behavior.")
    lines.append("")
    return "\n".join(lines)
