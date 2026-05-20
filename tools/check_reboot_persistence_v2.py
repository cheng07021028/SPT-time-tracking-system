# -*- coding: utf-8 -*-
"""SPT Reboot persistence health check.
Checks whether the project still references old persistence roots and whether
single-store latest files exist under data/permanent_store.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "permanent_store"
OLD_DIRS = [
    ROOT / "data" / "persistent_modules",
    ROOT / "data" / "persistent_state",
    ROOT / "data" / "database",
    ROOT / "data" / "config",
]
TEXT_EXTS = {".py", ".toml", ".md", ".txt", ".json", ".gitignore"}
IGNORE_PARTS = {"__pycache__", ".git", "data/permanent_store"}
OLD_PATTERNS = [
    r'\/data\/persistent_modules',
    r'\/data\/persistent_state',
    r'\/data\/database',
    r'\/data\/config',
    r'"data"\s*/\s*"persistent_modules"',
    r'"data"\s*/\s*"persistent_state"',
    r'"data"\s*/\s*"database"',
    r'"data"\s*/\s*"config"',
    r"'data'\s*/\s*'persistent_modules'",
    r"'data'\s*/\s*'persistent_state'",
    r"'data'\s*/\s*'database'",
    r"'data'\s*/\s*'config'",
]


def _is_ignored(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(part in rel for part in IGNORE_PARTS)


def scan_old_references() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or _is_ignored(p) or p.suffix.lower() not in TEXT_EXTS or p.name.startswith("check_"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if "data/permanent_store" in line:
                continue
            if any(re.search(pattern, line) for pattern in OLD_PATTERNS):
                findings.append({"file": p.relative_to(ROOT).as_posix(), "line": i, "text": line.strip()[:220]})
    return findings


def json_info(path: Path) -> dict[str, object]:
    item: dict[str, object] = {"path": path.relative_to(ROOT).as_posix(), "exists": path.exists()}
    if path.exists():
        item["size"] = path.stat().st_size
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                item["exported_at"] = data.get("exported_at") or data.get("updated_at") or data.get("export_time")
                item["table_counts"] = data.get("table_counts") or data.get("counts")
                item["business_row_count"] = data.get("business_row_count")
        except Exception as exc:
            item["json_error"] = str(exc)
    return item


def main() -> int:
    latest_files = [
        STORE / "persistent_state" / "spt_permanent_state.json",
        STORE / "persistent_state" / "spt_module_settings.json",
        STORE / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
        STORE / "persistent_modules" / "03_work_orders" / "03_work_orders_records.json",
        STORE / "persistent_modules" / "04_employees" / "04_employees_records.json",
        STORE / "config" / "system_settings.json",
    ]
    old_dirs = [d.relative_to(ROOT).as_posix() for d in OLD_DIRS if d.exists()]
    findings = scan_old_references()
    report = {
        "ok": not old_dirs and not findings and STORE.exists(),
        "permanent_store_exists": STORE.exists(),
        "old_dirs_present": old_dirs,
        "old_code_references": findings[:50],
        "old_code_reference_count": len(findings),
        "latest_files": [json_info(p) for p in latest_files],
        "github_token_env_set": bool(os.environ.get("GITHUB_TOKEN")),
        "note": "Streamlit Cloud Reboot keeps only files committed/uploaded to GitHub. Local-only changes disappear after reboot.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
