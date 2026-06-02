# -*- coding: utf-8 -*-
"""V300.15.1 all-module authority read/write trace utilities.

Diagnostic only. This module inspects expected authority folders/files and
legacy candidates for 15 modules. It does not modify module records, settings,
tombstones, 01/02 business logic, UI theme, permissions, or system settings.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MODULES_TO_TRACE: Dict[str, Dict[str, Any]] = {
    "01_time_records": {
        "module_no": "01",
        "title": "工時紀錄",
        "authority_dir": "data/permanent_store/modules/01_time_records",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": [
            "data/persistent_modules/01_time_records",
            "data/persistent_state/01_time_records",
            "data/permanent_store/persistent_modules/01_time_records",
            "data/permanent_store/persistent_state/01_time_records",
            "data/database",
        ],
        "expected_mode": "records.json + tombstones.json; do not overwrite from legacy/cache after reboot",
    },
    "02_history": {
        "module_no": "02",
        "title": "歷史紀錄",
        "authority_dir": "data/permanent_store/modules/02_history",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": [
            "data/persistent_modules/02_history",
            "data/persistent_state/02_history",
            "data/permanent_store/persistent_modules/02_history",
            "data/permanent_store/persistent_state/02_history",
            "data/database",
        ],
        "expected_mode": "records.json + tombstones.json; synchronized view of 01 records",
    },
    "03_work_orders": {
        "module_no": "03",
        "title": "製令管理",
        "authority_dir": "data/permanent_store/modules/03_work_orders",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/03_work_orders", "data/persistent_state/03_work_orders", "data/config", "data/database"],
        "expected_mode": "work-order master records and settings",
    },
    "04_employees": {
        "module_no": "04",
        "title": "人員名單",
        "authority_dir": "data/permanent_store/modules/04_employees",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/04_employees", "data/persistent_state/04_employees", "data/config", "data/database"],
        "expected_mode": "employee master records and activation state",
    },
    "05_work_order_time_analysis": {
        "module_no": "05",
        "title": "製令工時分析",
        "authority_dir": "data/permanent_store/modules/05_work_order_time_analysis",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/05_work_order_time_analysis", "data/persistent_state/05_work_order_time_analysis", "data/database"],
        "expected_mode": "analysis snapshots/settings; should not overwrite 01/02 raw authority",
    },
    "06_log_query": {
        "module_no": "06",
        "title": "LOG查詢",
        "authority_dir": "data/permanent_store/modules/06_log_query",
        "preferred_records": ["records.jsonl", "records.json", "settings.json", "authority_manifest.json"],
        "legacy_candidates": ["data/logs", "data/persistent_modules/06_log_query", "data/persistent_state/06_log_query", "data/permanent_store/persistent_modules/06_log_query", "data/performance"],
        "expected_mode": "append-only records.jsonl preferred for log/event data",
    },
    "07_missing_today": {
        "module_no": "07",
        "title": "今日未紀錄名單",
        "authority_dir": "data/permanent_store/modules/07_missing_today",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/07_missing_today", "data/persistent_state/07_missing_today", "data/database"],
        "expected_mode": "today missing-record snapshots and confirmation records",
    },
    "08_employee_daily_hours": {
        "module_no": "08",
        "title": "人員每日工時",
        "authority_dir": "data/permanent_store/modules/08_employee_daily_hours",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/08_employee_daily_hours", "data/persistent_state/08_employee_daily_hours", "data/database"],
        "expected_mode": "daily employee hours snapshots/corrections",
    },
    "09_backup_restore": {
        "module_no": "09",
        "title": "資料永久保存與備份",
        "authority_dir": "data/permanent_store/modules/09_backup_restore",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/09_backup_restore", "data/persistent_state/09_backup_restore", "data/permanent_store/_backups", "data/permanent_store/config"],
        "expected_mode": "backup/restore policy and backup execution state",
    },
    "10_permissions": {
        "module_no": "10",
        "title": "權限管理",
        "authority_dir": "data/permanent_store/modules/10_permissions",
        "preferred_records": ["records.json", "security_runtime_settings.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/10_permissions", "data/persistent_state/10_permissions", "data/permanent_store/persistent_modules", "data/permanent_store/persistent_state", "data/security"],
        "expected_mode": "records.json for accounts/permissions + independent security_runtime_settings.json",
    },
    "11_login_records": {
        "module_no": "11",
        "title": "登入紀錄",
        "authority_dir": "data/permanent_store/modules/11_login_records",
        "preferred_records": ["records.jsonl", "records.json", "settings.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/11_login_records", "data/persistent_state/11_login_records", "data/login_logs", "data/security"],
        "expected_mode": "append-only records.jsonl preferred for login events",
    },
    "12_module_persistence_center": {
        "module_no": "12",
        "title": "模組永久紀錄中心",
        "authority_dir": "data/permanent_store/modules/12_module_persistence_center",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules", "data/persistent_state", "data/permanent_store/manifest.json", "data/permanent_store/modules/00_MODULE_AUTHORITY_REGISTRY.json"],
        "expected_mode": "authority inventory, repair logs and module persistence audit state",
    },
    "13_system_settings": {
        "module_no": "13",
        "title": "系統設定",
        "authority_dir": "data/permanent_store/modules/13_system_settings",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/13_system_settings", "data/persistent_state/13_system_settings", "data/config", "data/system_settings", "data/permanent_store/config"],
        "expected_mode": "settings authority; do not silently alter 01/02 runtime links",
    },
    "14_data_health": {
        "module_no": "14",
        "title": "資料健康檢查中心",
        "authority_dir": "data/permanent_store/modules/14_data_health",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/persistent_modules/14_data_health", "data/persistent_state/14_data_health", "data/permanent_store/authority_trace", "data/performance"],
        "expected_mode": "health-check reports and repair recommendations",
    },
    "99_speed_diagnostic": {
        "module_no": "99",
        "title": "效能診斷",
        "authority_dir": "data/permanent_store/modules/99_speed_diagnostic",
        "preferred_records": ["records.json", "settings.json", "tombstones.json", "authority_manifest.json"],
        "legacy_candidates": ["data/performance", "data/persistent_modules/99_speed_diagnostic", "data/persistent_state/99_speed_diagnostic"],
        "expected_mode": "diagnostic settings only; large performance events may remain in data/performance",
    },
}

TRACE_DIR = Path("data/permanent_store/authority_trace")
TRACE_FILE = TRACE_DIR / "v30015_authority_trace.jsonl"
SNAPSHOT_FILE = TRACE_DIR / "v30015_latest_snapshot.json"
REPORT_FILE = TRACE_DIR / "V300_15_AUTHORITY_TRACE_REPORT.md"


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
            rows: List[Any] = []
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
            info["top_keys"] = list(data.keys())[:50]
            for key in (
                "users", "accounts", "permissions", "account_permissions", "module_permissions",
                "auth_security_settings", "security_settings", "settings", "records", "tombstones",
                "deleted_usernames", "deleted_keys",
            ):
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
    if module_key:
        selected = {module_key: MODULES_TO_TRACE[module_key]}
    else:
        selected = MODULES_TO_TRACE
    result: Dict[str, Any] = {
        "generated_at": _now(),
        "project_root": str(root).replace("\\", "/"),
        "module_count": len(selected),
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
            module_info["authority_files"][filename] = _summarize_file(authority_dir / filename)
        for rel in cfg["legacy_candidates"]:
            module_info["legacy_candidates"][rel] = _summarize_file(root / rel)

        has_authority = any(v.get("exists") for v in module_info["authority_files"].values())
        has_records_like = any(
            v.get("exists") for name, v in module_info["authority_files"].items()
            if name in {"records.json", "records.jsonl"}
        )
        has_legacy = any(v.get("exists") for v in module_info["legacy_candidates"].values())
        if not has_authority:
            module_info["warnings"].append("Missing expected authority folder/files.")
        if not has_records_like:
            module_info["warnings"].append("Missing records authority file (records.json or records.jsonl).")
        if has_legacy:
            module_info["warnings"].append("Legacy source exists; verify it does not overwrite authority after reboot.")
        if key in {"06_log_query", "11_login_records"} and not (authority_dir / "records.jsonl").exists():
            module_info["warnings"].append("Append-only module should prefer records.jsonl for event logs.")
        result["modules"][key] = module_info
    return result


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


def save_snapshot(project_root: str | os.PathLike[str] = ".") -> Dict[str, Any]:
    root = Path(project_root).resolve()
    snapshot = inspect_module_authority(root)
    trace_dir = root / TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    (root / SNAPSHOT_FILE).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / REPORT_FILE).write_text(render_markdown_report(snapshot), encoding="utf-8")
    return snapshot


def render_markdown_report(snapshot: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# V300.15.1 全模組權威檔盤點報告")
    lines.append("")
    lines.append(f"Generated at: `{snapshot.get('generated_at')}`")
    lines.append(f"Project root: `{snapshot.get('project_root')}`")
    lines.append(f"Module count: `{snapshot.get('module_count')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| 模組 | 權威檔存在數 | 舊來源存在數 | 警告數 |")
    lines.append("|---|---:|---:|---:|")
    for key, info in snapshot.get("modules", {}).items():
        auth_count = sum(1 for v in (info.get("authority_files") or {}).values() if v.get("exists"))
        legacy_count = sum(1 for v in (info.get("legacy_candidates") or {}).values() if v.get("exists"))
        warn_count = len(info.get("warnings") or [])
        lines.append(f"| {info.get('module_no')}. {info.get('title')} (`{key}`) | {auth_count} | {legacy_count} | {warn_count} |")
    lines.append("")
    lines.append("## Details")
    lines.append("")
    for key, info in snapshot.get("modules", {}).items():
        lines.append(f"### {info.get('module_no')}. {info.get('title')} (`{key}`)")
        lines.append("")
        lines.append(f"Expected mode: {info.get('expected_mode')}")
        ad = info.get("authority_dir", {})
        lines.append(f"Authority dir: `{ad.get('path')}` exists={ad.get('exists')}")
        lines.append("")
        lines.append("Authority files:")
        for name, finfo in (info.get("authority_files") or {}).items():
            parts = [f"- `{name}` exists={finfo.get('exists')}"]
            if finfo.get("size_bytes") is not None:
                parts.append(f"size={finfo.get('size_bytes')}")
            if finfo.get("row_count") is not None:
                parts.append(f"rows={finfo.get('row_count')}")
            for count_key in sorted([k for k in finfo.keys() if k.endswith("_count") or k.endswith("_keys_count")]):
                parts.append(f"{count_key}={finfo[count_key]}")
            lines.append(" ".join(parts))
        lines.append("")
        lines.append("Legacy candidates:")
        for rel, finfo in (info.get("legacy_candidates") or {}).items():
            lines.append(f"- `{rel}` exists={finfo.get('exists')} type={'dir' if finfo.get('is_dir') else 'file' if finfo.get('is_file') else '-'}")
        warnings = info.get("warnings") or []
        if warnings:
            lines.append("")
            lines.append("Warnings:")
            for warning in warnings:
                lines.append(f"- {warning}")
        lines.append("")
    return "\n".join(lines)
