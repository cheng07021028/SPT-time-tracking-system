# -*- coding: utf-8 -*-
"""SPT Time Tracking - Settings Durability Service V3.29.

Purpose
-------
Keep user-maintained settings out of Python source code and make them durable:
1. Write settings to data/permanent_store/config, data/permanent_store/persistent_state, and data/permanent_store/persistent_modules.
2. Optionally upload/download those files through the existing GitHub Contents API.
3. Never fail the UI if GitHub token is missing; return a clear skipped status.

This service intentionally does NOT touch theme_service.py and does not change UI style.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Central list of settings files that must survive Reboot App / redeploy.
# Remote path is intentionally the same as the project-relative local path.
CRITICAL_SETTING_FILES: list[dict[str, str]] = [
    {"label": "13 system settings primary", "path": "data/permanent_store/config/system_settings.json"},
    {"label": "13 system settings state", "path": "data/permanent_store/persistent_state/spt_system_settings.json"},
    {"label": "13 system settings module", "path": "data/permanent_store/persistent_modules/13_system_settings/system_settings.json"},
    {"label": "daily backup schedule", "path": "data/permanent_store/config/auto_external_backup_schedule.json"},
    {"label": "daily backup state", "path": "data/permanent_store/persistent_state/auto_external_backup_state.json"},
    {"label": "security settings primary", "path": "data/permanent_store/config/security_settings.json"},
    {"label": "security settings state", "path": "data/permanent_store/persistent_state/spt_security_settings.json"},
    {"label": "permission security settings", "path": "data/permanent_store/persistent_modules/10_permissions/security_settings.json"},
    {"label": "permission module settings", "path": "data/permanent_store/persistent_modules/10_permissions/10_permissions_settings.json"},
    {"label": "module persistence settings", "path": "data/permanent_store/persistent_modules/12_module_persistence/12_module_persistence_settings.json"},
    {"label": "table UI widths/order state", "path": "data/permanent_store/persistent_state/spt_table_ui_settings.json"},
    {"label": "table UI widths/order module", "path": "data/permanent_store/persistent_modules/ui_table_settings/table_ui_settings.json"},
    {"label": "table column settings", "path": "data/permanent_store/persistent_state/spt_table_column_settings.json"},
    {"label": "history filter settings", "path": "data/permanent_store/persistent_state/spt_history_filter_settings.json"},
    {"label": "analysis filter settings", "path": "data/permanent_store/persistent_state/spt_analysis_filter_settings.json"},
    {"label": "global UI settings", "path": "data/permanent_store/persistent_state/spt_global_ui_settings.json"},
    {"label": "home UI settings compatibility", "path": "data/permanent_store/persistent_state/spt_home_ui_settings.json"},
    {"label": "idle timeout state", "path": "data/permanent_store/persistent_state/spt_idle_timeout_settings.json"},
    {"label": "idle timeout config", "path": "data/permanent_store/config/idle_timeout_settings.json"},
    {"label": "auto backup schedule config", "path": "data/permanent_store/config/auto_external_backup_schedule.json"},
    {"label": "auto backup schedule state", "path": "data/permanent_store/persistent_state/auto_external_backup_state.json"},
    {"label": "github cleanup settings", "path": "data/permanent_store/config/github_cleanup_settings.json"},
]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _local_path(rel_path: str) -> Path:
    return PROJECT_ROOT / rel_path


def _read_json(path: Path) -> tuple[bool, str, Any | None]:
    if not path.exists():
        return False, "file not found", None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return True, "json readable", payload
    except Exception as exc:
        return False, f"json read failed: {exc}", None


def get_critical_settings_health() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in CRITICAL_SETTING_FILES:
        rel = item["path"]
        path = _local_path(rel)
        exists = path.exists()
        readable, detail, payload = _read_json(path)
        try:
            size = path.stat().st_size if exists else 0
            modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if exists else ""
        except Exception:
            size = 0
            modified = ""
        rows.append({
            "label": item["label"],
            "path": rel,
            "exists": exists,
            "json_readable": readable,
            "size": size,
            "modified": modified,
            "detail": detail,
            "top_keys": ", ".join(list(payload.keys())[:8]) if isinstance(payload, dict) else "",
        })
    return rows


def upload_critical_settings_to_github(*, archive: bool = False, source: str = "manual") -> dict[str, Any]:
    """Upload critical setting files to GitHub using existing service.

    Missing local files are skipped; this function never creates default settings.
    """
    try:
        from services.github_cloud_storage_service import github_config, upload_file_to_github
    except Exception as exc:
        return {"ok": False, "skipped": True, "message": f"GitHub service unavailable: {exc}", "uploads": []}

    cfg = github_config()
    if not cfg.get("token"):
        return {"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured; local settings are still saved.", "uploads": []}

    stamp = _stamp()
    uploads: list[dict[str, Any]] = []
    for item in CRITICAL_SETTING_FILES:
        rel = item["path"]
        local = _local_path(rel)
        if not local.exists() or local.stat().st_size <= 0:
            uploads.append({"ok": True, "skipped": True, "path": rel, "message": "local file missing; skipped"})
            continue
        res = upload_file_to_github(local, rel, f"SPT settings sync {source} {stamp}: {rel}")
        uploads.append(res)
        if archive:
            # Archive under same folder/history without changing latest canonical file.
            archive_path = str(Path(rel).parent / "history" / f"{Path(rel).stem}_{stamp}{Path(rel).suffix}").replace("\\", "/")
            uploads.append(upload_file_to_github(local, archive_path, f"SPT settings archive {source} {stamp}: {rel}"))

    failures = [u for u in uploads if not u.get("ok") and not u.get("skipped")]
    return {
        "ok": len(failures) == 0,
        "source": source,
        "archive": archive,
        "upload_count": len([u for u in uploads if u.get("ok") and not u.get("skipped")]),
        "skipped_count": len([u for u in uploads if u.get("skipped")]),
        "failures": failures[:10],
        "uploads": uploads,
        "updated_at": _now_text(),
    }


def download_critical_settings_from_github(*, only_missing: bool = True, source: str = "manual") -> dict[str, Any]:
    """Download critical setting files from GitHub to local data/ paths.

    only_missing=True is safest for app boot: existing local settings are not overwritten.
    """
    try:
        from services.github_cloud_storage_service import github_config, download_text_from_github
    except Exception as exc:
        return {"ok": False, "skipped": True, "message": f"GitHub service unavailable: {exc}", "downloads": []}

    cfg = github_config()
    if not cfg.get("token"):
        return {"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured", "downloads": []}

    downloads: list[dict[str, Any]] = []
    for item in CRITICAL_SETTING_FILES:
        rel = item["path"]
        local = _local_path(rel)
        if only_missing and local.exists() and local.stat().st_size > 0:
            downloads.append({"ok": True, "skipped": True, "path": rel, "message": "local file already exists"})
            continue
        res = download_text_from_github(rel)
        if not res.get("ok"):
            downloads.append({"ok": False, "path": rel, "message": res.get("message", "download failed")})
            continue
        try:
            text = str(res.get("text") or "")
            json.loads(text)  # validate; settings files must be JSON.
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp = local.with_suffix(local.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(local)
            downloads.append({"ok": True, "path": rel, "message": "downloaded"})
        except Exception as exc:
            downloads.append({"ok": False, "path": rel, "message": f"write/validate failed: {exc}"})
    failures = [d for d in downloads if not d.get("ok") and not d.get("skipped")]
    return {"ok": len(failures) == 0, "source": source, "downloads": downloads, "failures": failures[:10], "updated_at": _now_text()}
