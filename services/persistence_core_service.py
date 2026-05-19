# -*- coding: utf-8 -*-
"""
SPT Time Tracking - V360 Unified Persistence Core

架構級修正：建立唯一設定主來源，避免 SQLite / JSON / session_state / 預設值互相覆蓋。
本服務只處理本機 JSON 與輕量鏡像，不在載入時掃 history、不自動上傳 GitHub，避免登入或頁面無限運轉。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
MODULE_DIR = PROJECT_ROOT / "data" / "persistent_modules"
MASTER_SETTINGS_PATH = STATE_DIR / "spt_user_persistent_settings.json"

MASTER_MIRROR_PATHS = [
    MASTER_SETTINGS_PATH,
    STATE_DIR / "spt_module_settings.json",
    MODULE_DIR / "ui_table_settings" / "v360_user_persistent_settings.json",
    MODULE_DIR / "01_time_records" / "v360_user_persistent_settings.json",
    MODULE_DIR / "10_permissions" / "v360_user_persistent_settings.json",
    MODULE_DIR / "13_system_settings" / "v360_user_persistent_settings.json",
]


def now_text() -> str:
    try:
        from services.timezone_service import now_text as _now_text
        return _now_text()
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for path in MASTER_MIRROR_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # verify before replace
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _blank_master() -> dict[str, Any]:
    return {
        "version": "V360",
        "updated_at": now_text(),
        "description": "超慧科技製造部工時紀錄系統唯一設定主來源；SQLite 僅作運行快取。",
        "table_settings": {},
        "column_settings": {},
        "system_settings": {},
        "permission_settings": {},
        "source": "v360_unified_persistence_core",
    }


def _score_master(data: dict[str, Any]) -> tuple[int, int, int, int, float]:
    if not isinstance(data, dict):
        return (-1, -1, -1, -1, 0.0)
    table_count = len(data.get("table_settings") or {}) if isinstance(data.get("table_settings"), dict) else 0
    column_count = len(data.get("column_settings") or {}) if isinstance(data.get("column_settings"), dict) else 0
    system_count = len(data.get("system_settings") or {}) if isinstance(data.get("system_settings"), dict) else 0
    permission_count = len(data.get("permission_settings") or {}) if isinstance(data.get("permission_settings"), dict) else 0
    try:
        updated = float(data.get("_mtime") or 0.0)
    except Exception:
        updated = 0.0
    return (table_count, column_count, system_count, permission_count, updated)


def load_master_settings() -> dict[str, Any]:
    """Load the best available master settings without writing anything."""
    ensure_dirs()
    best: dict[str, Any] | None = None
    best_score = (-1, -1, -1, -1, -1.0)
    for path in MASTER_MIRROR_PATHS:
        payload = read_json(path)
        if not payload:
            continue
        # spt_module_settings may embed our master section under v360_user_persistent_settings.
        if isinstance(payload.get("v360_user_persistent_settings"), dict):
            payload = payload.get("v360_user_persistent_settings") or {}
        if not isinstance(payload, dict):
            continue
        try:
            payload = dict(payload)
            payload["_mtime"] = path.stat().st_mtime if path.exists() else 0.0
        except Exception:
            pass
        score = _score_master(payload)
        if score > best_score:
            best = payload
            best_score = score
    if not best:
        return _blank_master()
    base = _blank_master()
    # Merge sections explicitly to avoid malformed files dropping required keys.
    for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
        if isinstance(best.get(section), dict):
            base[section] = dict(best.get(section) or {})
    base["updated_at"] = str(best.get("updated_at") or now_text())
    return base


def save_master_settings(master: dict[str, Any], *, reason: str = "v360_save") -> dict[str, Any]:
    ensure_dirs()
    payload = _blank_master()
    for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
        if isinstance(master.get(section), dict):
            payload[section] = dict(master.get(section) or {})
    payload["updated_at"] = now_text()
    payload["reason"] = reason
    for path in MASTER_MIRROR_PATHS:
        if path.name == "spt_module_settings.json":
            existing = read_json(path)
            if not isinstance(existing, dict):
                existing = {}
            existing["v360_user_persistent_settings"] = payload
            existing["updated_at"] = payload["updated_at"]
            existing["version"] = str(existing.get("version") or "V360")
            atomic_write_json(path, existing)
        else:
            atomic_write_json(path, payload)
    return {"ok": True, "files": [str(p) for p in MASTER_MIRROR_PATHS], "reason": reason}


def get_section(section: str) -> dict[str, Any]:
    master = load_master_settings()
    data = master.get(section)
    return dict(data or {}) if isinstance(data, dict) else {}


def update_section(section: str, data: dict[str, Any], *, reason: str = "v360_update_section") -> dict[str, Any]:
    master = load_master_settings()
    master[section] = dict(data or {})
    return save_master_settings(master, reason=reason)


def merge_section(section: str, data: dict[str, Any], *, reason: str = "v360_merge_section") -> dict[str, Any]:
    master = load_master_settings()
    cur = master.get(section) if isinstance(master.get(section), dict) else {}
    merged = dict(cur or {})
    merged.update(dict(data or {}))
    master[section] = merged
    return save_master_settings(master, reason=reason)


def bootstrap_persistent_state_once() -> dict[str, Any]:
    """Lightweight local bootstrap: create master file and let table persistence migrate old settings.

    This intentionally avoids GitHub, history scans, full exports and page reruns.
    """
    ensure_dirs()
    result: dict[str, Any] = {"ok": True, "steps": []}
    try:
        master = load_master_settings()
        save_master_settings(master, reason="v360_bootstrap_touch")
        result["steps"].append({"step": "master_settings", "ok": True})
    except Exception as exc:
        result["ok"] = False
        result["steps"].append({"step": "master_settings", "ok": False, "error": str(exc)})
    try:
        from services.table_persistence_service import migrate_legacy_table_settings_to_master
        r = migrate_legacy_table_settings_to_master(write=True)
        result["steps"].append({"step": "table_persistence_migration", **(r if isinstance(r, dict) else {"result": str(r)})})
    except Exception as exc:
        result["ok"] = False
        result["steps"].append({"step": "table_persistence_migration", "ok": False, "error": str(exc)})
    return result


# ===== V3.63 definitive persistence source + GitHub write-through =====
# 真正原則：永久主檔是唯一主來源；本機 JSON 寫完後，如果有 GITHUB_TOKEN，立即把小型設定檔寫回 GitHub。
# 這樣 Streamlit Cloud Reboot 後才會從 GitHub 重新載入最新設定，而不是回到 repo 內舊預設。
REMOTE_MASTER_SETTINGS_PATH = "data/persistent_state/spt_user_persistent_settings.json"


def _v363_remote_download_if_missing() -> None:
    """Download the canonical master only when local canonical file is missing.

    No history scan, no DB restore, no rerun.  This avoids login spinning but fixes
    the Streamlit Cloud case where local ephemeral settings vanished after reboot.
    """
    try:
        if MASTER_SETTINGS_PATH.exists() and MASTER_SETTINGS_PATH.stat().st_size > 0:
            return
        from services.github_cloud_storage_service import github_config, download_text_from_github
        if not github_config().get("token"):
            return
        res = download_text_from_github(REMOTE_MASTER_SETTINGS_PATH)
        if not res.get("ok"):
            return
        text = str(res.get("text") or "")
        data = json.loads(text)
        if not isinstance(data, dict):
            return
        ensure_dirs()
        atomic_write_json(MASTER_SETTINGS_PATH, data)
    except Exception:
        pass


def _v363_normalize_master_payload(payload: dict[str, Any]) -> dict[str, Any]:
    base = _blank_master()
    if not isinstance(payload, dict):
        return base
    if isinstance(payload.get("v360_user_persistent_settings"), dict):
        payload = payload.get("v360_user_persistent_settings") or {}
    for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
        if isinstance(payload.get(section), dict):
            base[section] = dict(payload.get(section) or {})
    base["updated_at"] = str(payload.get("updated_at") or now_text())
    base["version"] = str(payload.get("version") or "V363")
    return base


def load_master_settings() -> dict[str, Any]:  # type: ignore[override]
    """V363: deterministic load.

    Old logic picked the 'richest' mirror by counts; that is unsafe after user
    deletes rows or intentionally leaves a table empty.  Now we merge mirrors in
    a fixed order and let the canonical master file win.
    """
    ensure_dirs()
    _v363_remote_download_if_missing()
    merged = _blank_master()
    # Lowest priority first, canonical master last.
    ordered_paths = [p for p in MASTER_MIRROR_PATHS if p != MASTER_SETTINGS_PATH] + [MASTER_SETTINGS_PATH]
    found = False
    for path in ordered_paths:
        payload = read_json(path)
        if not payload:
            continue
        found = True
        norm = _v363_normalize_master_payload(payload)
        for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
            cur = merged.get(section) if isinstance(merged.get(section), dict) else {}
            incoming = norm.get(section) if isinstance(norm.get(section), dict) else {}
            # File-level deterministic merge.  Empty dict is valid but should not erase
            # other sections from another mirror unless it is the canonical full file.
            if path == MASTER_SETTINGS_PATH:
                # canonical section is authoritative when present in raw payload
                raw = payload.get("v360_user_persistent_settings") if isinstance(payload.get("v360_user_persistent_settings"), dict) else payload
                if isinstance(raw.get(section), dict):
                    cur = dict(incoming)
                else:
                    cur = dict(cur or {})
            else:
                tmp = dict(cur or {})
                tmp.update(dict(incoming or {}))
                cur = tmp
            merged[section] = cur
        if norm.get("updated_at"):
            merged["updated_at"] = norm.get("updated_at")
    return merged if found else _blank_master()


def _v363_upload_master_files_to_github(reason: str) -> dict[str, Any]:
    try:
        from services.github_cloud_storage_service import github_config, upload_file_to_github
        if not github_config().get("token"):
            return {"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured"}
        uploads = []
        # Upload only small canonical / compatibility files.  No history, no DB dump.
        for local, remote in [
            (MASTER_SETTINGS_PATH, REMOTE_MASTER_SETTINGS_PATH),
            (STATE_DIR / "spt_module_settings.json", "data/persistent_state/spt_module_settings.json"),
            (STATE_DIR / "spt_table_ui_settings.json", "data/persistent_state/spt_table_ui_settings.json"),
            (STATE_DIR / "spt_table_column_settings.json", "data/persistent_state/spt_table_column_settings.json"),
        ]:
            try:
                if local.exists() and local.stat().st_size > 0:
                    uploads.append(upload_file_to_github(local, remote, f"SPT V363 settings save {reason} {now_text()}"))
            except Exception as exc:
                uploads.append({"ok": False, "path": remote, "message": str(exc)})
        return {"ok": all(bool(x.get("ok")) for x in uploads) if uploads else False, "uploads": uploads}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def save_master_settings(master: dict[str, Any], *, reason: str = "v363_save") -> dict[str, Any]:  # type: ignore[override]
    ensure_dirs()
    payload = _blank_master()
    for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
        if isinstance(master.get(section), dict):
            payload[section] = dict(master.get(section) or {})
    payload["updated_at"] = now_text()
    payload["version"] = "V363"
    payload["reason"] = reason
    written = []
    for path in MASTER_MIRROR_PATHS:
        if path.name == "spt_module_settings.json":
            existing = read_json(path)
            if not isinstance(existing, dict):
                existing = {}
            existing["v360_user_persistent_settings"] = payload
            existing["updated_at"] = payload["updated_at"]
            existing["version"] = str(existing.get("version") or "V363")
            atomic_write_json(path, existing)
        else:
            atomic_write_json(path, payload)
        written.append(str(path))
    upload = _v363_upload_master_files_to_github(reason)
    return {"ok": True, "files": written, "reason": reason, "github_upload": upload}


def bootstrap_persistent_state_once() -> dict[str, Any]:  # type: ignore[override]
    ensure_dirs()
    result: dict[str, Any] = {"ok": True, "steps": []}
    try:
        _v363_remote_download_if_missing()
        master = load_master_settings()
        # Write local mirrors only.  No GitHub upload during boot.
        payload = _blank_master()
        for section in ["table_settings", "column_settings", "system_settings", "permission_settings"]:
            if isinstance(master.get(section), dict):
                payload[section] = dict(master.get(section) or {})
        payload["updated_at"] = str(master.get("updated_at") or now_text())
        payload["version"] = "V363"
        payload["reason"] = "v363_bootstrap_local_only"
        for path in MASTER_MIRROR_PATHS:
            if path.name == "spt_module_settings.json":
                existing = read_json(path)
                if not isinstance(existing, dict):
                    existing = {}
                existing["v360_user_persistent_settings"] = payload
                existing["updated_at"] = payload["updated_at"]
                atomic_write_json(path, existing)
            else:
                atomic_write_json(path, payload)
        result["steps"].append({"step": "master_settings", "ok": True, "mode": "v363_local_bootstrap"})
    except Exception as exc:
        result["ok"] = False
        result["steps"].append({"step": "master_settings", "ok": False, "error": str(exc)})
    try:
        from services.table_persistence_service import migrate_legacy_table_settings_to_master
        r = migrate_legacy_table_settings_to_master(write=True)
        result["steps"].append({"step": "table_persistence_migration", **(r if isinstance(r, dict) else {"result": str(r)})})
    except Exception as exc:
        result["ok"] = False
        result["steps"].append({"step": "table_persistence_migration", "ok": False, "error": str(exc)})
    return result
