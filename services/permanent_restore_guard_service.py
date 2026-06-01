# -*- coding: utf-8 -*-
"""
SPT Time Tracking - Permanent Restore Guard V3.41

集中處理 10/12/13 模組在 Streamlit Cloud Reboot 後的永久檔救援。
設計原則：
- 不在登入頁 import 階段執行 GitHub 網路同步。
- 不用預設資料覆蓋使用者已建立的永久檔。
- 只做本機 data/ 內永久 JSON 檢查與輕量救援。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _safe_json(path: Path) -> Any | None:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _file_info(path: Path) -> dict[str, Any]:
    payload = _safe_json(path)
    return {
        "path": str(path.relative_to(PROJECT_ROOT) if path.exists() else path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
        "json_ok": isinstance(payload, (dict, list)),
        "mtime": path.stat().st_mtime if path.exists() else 0,
    }


def audit_core_permanent_files() -> list[dict[str, Any]]:
    """Return a lightweight status list for 10/12/13 critical persistent files."""
    paths = [
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_records.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "10_permissions_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "10_permissions" / "security_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "config" / "security_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_security_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "12_module_persistence" / "12_module_persistence_records.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "12_module_persistence" / "12_module_persistence_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "config" / "system_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_system_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "13_system_settings" / "system_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_table_ui_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / "ui_table_settings" / "table_ui_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_table_column_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_history_filter_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_analysis_filter_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_global_ui_settings.json",
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_idle_timeout_settings.json",
    ]
    return [_file_info(p) for p in paths]


def restore_core_modules_from_local_permanent() -> dict[str, Any]:
    """Run local-only restore guards for 10/12/13.

    Safe to call from management pages. It intentionally does not call GitHub.
    """
    result: dict[str, Any] = {"ok": True, "modules": {}}
    try:
        from services.permission_service import restore_permission_settings_from_permanent_files
        result["modules"]["10_permissions"] = restore_permission_settings_from_permanent_files(force=False)
    except Exception as exc:
        result["ok"] = False
        result["modules"]["10_permissions"] = {"ok": False, "error": str(exc)}
    try:
        from services.system_settings_service import restore_system_settings_from_permanent, ensure_system_settings_schema
        ensure_system_settings_schema()
        result["modules"]["13_system_settings"] = restore_system_settings_from_permanent(force=False)
    except Exception as exc:
        result["ok"] = False
        result["modules"]["13_system_settings"] = {"ok": False, "error": str(exc)}
    try:
        from services.table_ui_service import restore_table_ui_settings_from_permanent
        result["modules"]["ui_table_settings"] = restore_table_ui_settings_from_permanent(force=False)
    except Exception as exc:
        result["ok"] = False
        result["modules"]["ui_table_settings"] = {"ok": False, "error": str(exc)}
    try:
        from services.module_persistence_service import ensure_dirs, rebuild_global_index, protect_gitignore_rules
        ensure_dirs(); protect_gitignore_rules()
        result["modules"]["12_module_persistence"] = rebuild_global_index()
    except Exception as exc:
        result["ok"] = False
        result["modules"]["12_module_persistence"] = {"ok": False, "error": str(exc)}
    return result

# ===== V3.60 local persistence bootstrap extension =====
_prev_restore_core_modules_from_local_permanent_v360 = restore_core_modules_from_local_permanent

def restore_core_modules_from_local_permanent() -> dict[str, Any]:  # type: ignore[override]
    result = _prev_restore_core_modules_from_local_permanent_v360()
    try:
        from services.persistence_core_service import bootstrap_persistent_state_once
        result.setdefault("modules", {})["v360_persistence_core"] = bootstrap_persistent_state_once()
    except Exception as exc:
        result["ok"] = False
        result.setdefault("modules", {})["v360_persistence_core"] = {"ok": False, "error": str(exc)}
    return result
