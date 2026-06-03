# -*- coding: utf-8 -*-
"""V300.13 module authority registry and safe bootstrap utilities.

Purpose
-------
Create and audit one independent authority area per functional module under:

    data/permanent_store/modules/<module_key>/

This service is intentionally non-destructive:
- It never overwrites an existing records.json by default.
- It creates only missing directories/files.
- It does not import Streamlit, DB, Neon, GitHub, or UI modules.
- It is safe to run during maintenance or from a manual admin tool.

The design goal is to stop cross-module data recovery from old files, caches,
SQLite, or incomplete JSON from overwriting each module's official authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

SCHEMA_VERSION = "V300.13"
DEFAULT_BASE_DIR = Path("data/permanent_store/modules")


@dataclass(frozen=True)
class ModuleAuthoritySpec:
    module_id: str
    module_key: str
    module_name: str
    record_file: str = "records.json"
    settings_file: str = "settings.json"
    tombstone_file: str = "tombstones.json"
    manifest_file: str = "authority_manifest.json"
    description: str = ""
    owns_runtime_data: bool = True


MODULE_AUTHORITY_SPECS: Tuple[ModuleAuthoritySpec, ...] = (
    ModuleAuthoritySpec("01", "01_time_records", "工時紀錄", description="01 工時紀錄正式資料、刪除 tombstone、同步狀態。"),
    ModuleAuthoritySpec("02", "02_history", "歷史紀錄", description="02 歷史紀錄正式資料與 01 同步結果。"),
    ModuleAuthoritySpec("03", "03_work_orders", "製令管理", description="製令主檔、製令啟用狀態、製令備註。"),
    ModuleAuthoritySpec("04", "04_employees", "人員名單", description="人員名單、工號、部門、在職/啟用狀態。"),
    ModuleAuthoritySpec("05", "05_work_order_time_analysis", "製令工時分析", description="製令工時分析設定、快照與分析結果。"),
    ModuleAuthoritySpec("06", "06_log_query", "LOG查詢", description="LOG 查詢設定與必要保留策略；大量 log 可另存 performance/log 目錄。"),
    ModuleAuthoritySpec("07", "07_missing_today", "今日未紀錄名單", description="今日未紀錄名單快照、排除名單、人工確認紀錄。"),
    ModuleAuthoritySpec("08", "08_employee_daily_hours", "人員每日工時", description="人員每日工時快照、彙總與修正紀錄。"),
    ModuleAuthoritySpec("09", "09_backup_restore", "資料永久保存與備份", description="備份/還原設定、最後備份狀態、保留策略。"),
    ModuleAuthoritySpec("10", "10_permissions", "權限管理", description="帳號、角色、模組權限、安全設定；idle timeout 使用 security_runtime_settings.json。"),
    ModuleAuthoritySpec("11", "11_login_records", "登入紀錄", description="登入紀錄索引、查詢設定與匯出狀態。"),
    ModuleAuthoritySpec("12", "12_module_persistence_center", "模組永久紀錄中心", description="模組權威檔盤點、狀態報告、修復紀錄。"),
    ModuleAuthoritySpec("13", "13_system_settings", "系統設定", description="系統參數、休息時段、全域設定。"),
    ModuleAuthoritySpec("14", "14_data_health", "資料健康檢查中心", description="健康檢查結果、修復建議與稽核紀錄。"),
    ModuleAuthoritySpec("99", "99_speed_diagnostic", "效能診斷", description="效能診斷設定與清除紀錄；performance_events 可存 data/performance。", owns_runtime_data=False),
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_module_specs() -> List[Dict[str, Any]]:
    """Return module authority specs as serializable dictionaries."""
    return [asdict(spec) for spec in MODULE_AUTHORITY_SPECS]


def _safe_read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001 - audit should never crash caller
        return None, f"invalid_json: {exc}"


def _safe_write_json(path: Path, payload: Mapping[str, Any], overwrite: bool = False) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    return True


def _default_records_payload(spec: ModuleAuthoritySpec) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "module_id": spec.module_id,
        "module_key": spec.module_key,
        "module_name": spec.module_name,
        "description": spec.description,
        "records": [],
        "deleted_keys": [],
        "tombstone_refs": [],
        "meta": {
            "created_by": "V300.13 module authority bootstrap",
            "created_at": now_text(),
            "non_destructive": True,
            "note": "This file is created only when missing. Existing authority files are not overwritten.",
        },
    }


def _default_settings_payload(spec: ModuleAuthoritySpec) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "module_id": spec.module_id,
        "module_key": spec.module_key,
        "module_name": spec.module_name,
        "settings": {},
        "meta": {
            "created_by": "V300.13 module authority bootstrap",
            "created_at": now_text(),
            "non_destructive": True,
        },
    }
    if spec.module_key == "10_permissions":
        payload["settings"]["idle_timeout_authority_file"] = "security_runtime_settings.json"
    return payload


def _default_tombstones_payload(spec: ModuleAuthoritySpec) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "module_id": spec.module_id,
        "module_key": spec.module_key,
        "module_name": spec.module_name,
        "tombstones": [],
        "deleted_keys": [],
        "meta": {
            "created_by": "V300.13 module authority bootstrap",
            "created_at": now_text(),
            "non_destructive": True,
        },
    }


def _default_manifest_payload(spec: ModuleAuthoritySpec) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "module_id": spec.module_id,
        "module_key": spec.module_key,
        "module_name": spec.module_name,
        "description": spec.description,
        "authority_files": {
            "records": spec.record_file,
            "settings": spec.settings_file,
            "tombstones": spec.tombstone_file,
            "manifest": spec.manifest_file,
        },
        "rules": {
            "read_priority": [
                f"data/permanent_store/modules/{spec.module_key}/{spec.record_file}",
                "Neon/PostgreSQL cache or indexed view",
                "session cache",
            ],
            "write_priority": [
                f"data/permanent_store/modules/{spec.module_key}/{spec.record_file}",
                "module-specific tombstones/settings",
                "Neon/PostgreSQL cache or indexed view",
                "GitHub backup",
            ],
            "legacy_sources_must_not_overwrite": [
                "data/persistent_modules",
                "data/persistent_state",
                "SQLite fallback",
                "legacy settings.json",
                "session_state cache",
            ],
        },
        "created_at": now_text(),
    }


def ensure_module_authorities(
    base_dir: Path | str = DEFAULT_BASE_DIR,
    *,
    overwrite: bool = False,
    include_settings: bool = True,
    include_tombstones: bool = True,
) -> Dict[str, Any]:
    """Create missing authority directories/files for all 15 modules.

    Existing files are preserved unless overwrite=True is explicitly passed.
    The default is safe for production and will not erase existing 01/02/10 data.
    """
    base = Path(base_dir)
    created: List[str] = []
    preserved: List[str] = []
    errors: List[Dict[str, str]] = []

    registry_path = base / "00_MODULE_AUTHORITY_REGISTRY.json"
    registry_payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_text(),
        "module_count": len(MODULE_AUTHORITY_SPECS),
        "modules": get_module_specs(),
    }
    try:
        if _safe_write_json(registry_path, registry_payload, overwrite=overwrite):
            created.append(str(registry_path))
        else:
            preserved.append(str(registry_path))
    except Exception as exc:  # noqa: BLE001
        errors.append({"path": str(registry_path), "error": str(exc)})

    for spec in MODULE_AUTHORITY_SPECS:
        module_dir = base / spec.module_key
        module_dir.mkdir(parents=True, exist_ok=True)
        files_to_create: List[Tuple[Path, Dict[str, Any]]] = [
            (module_dir / spec.manifest_file, _default_manifest_payload(spec)),
            (module_dir / spec.record_file, _default_records_payload(spec)),
        ]
        if include_settings:
            files_to_create.append((module_dir / spec.settings_file, _default_settings_payload(spec)))
        if include_tombstones:
            files_to_create.append((module_dir / spec.tombstone_file, _default_tombstones_payload(spec)))
        if spec.module_key == "10_permissions":
            files_to_create.append((module_dir / "security_runtime_settings.json", {
                "schema_version": SCHEMA_VERSION,
                "idle_auto_logout_minutes": 15,
                "updated_at": now_text(),
                "updated_by": "V300.13 bootstrap default only when missing",
                "note": "Existing file is preserved. Runtime must prefer this independent authority file.",
            }))
        for path, payload in files_to_create:
            try:
                if _safe_write_json(path, payload, overwrite=overwrite):
                    created.append(str(path))
                else:
                    preserved.append(str(path))
            except Exception as exc:  # noqa: BLE001
                errors.append({"path": str(path), "error": str(exc)})

    return {
        "ok": not errors,
        "schema_version": SCHEMA_VERSION,
        "module_count": len(MODULE_AUTHORITY_SPECS),
        "created_count": len(created),
        "preserved_count": len(preserved),
        "error_count": len(errors),
        "created": created,
        "preserved": preserved,
        "errors": errors,
    }


def _count_records(payload: Any) -> Optional[int]:
    if isinstance(payload, dict):
        for key in ("records", "data", "rows", "items", "users"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        if "accounts" in payload and isinstance(payload.get("accounts"), list):
            return len(payload["accounts"])
    if isinstance(payload, list):
        return len(payload)
    return None


def audit_module_authorities(base_dir: Path | str = DEFAULT_BASE_DIR) -> Dict[str, Any]:
    """Audit all module authority directories without modifying files."""
    base = Path(base_dir)
    modules: List[Dict[str, Any]] = []
    missing_required = 0
    invalid_json = 0

    for spec in MODULE_AUTHORITY_SPECS:
        module_dir = base / spec.module_key
        records_path = module_dir / spec.record_file
        settings_path = module_dir / spec.settings_file
        tombstones_path = module_dir / spec.tombstone_file
        manifest_path = module_dir / spec.manifest_file
        records_payload, records_error = _safe_read_json(records_path)
        settings_payload, settings_error = _safe_read_json(settings_path)
        tombstones_payload, tombstones_error = _safe_read_json(tombstones_path)
        manifest_payload, manifest_error = _safe_read_json(manifest_path)
        status = "OK"
        errors = [err for err in (records_error, settings_error, tombstones_error, manifest_error) if err and err != "missing"]
        missing = [
            name for name, err in (
                (spec.record_file, records_error),
                (spec.settings_file, settings_error),
                (spec.tombstone_file, tombstones_error),
                (spec.manifest_file, manifest_error),
            ) if err == "missing"
        ]
        if missing:
            status = "MISSING_FILES"
            missing_required += len(missing)
        if errors:
            status = "INVALID_JSON"
            invalid_json += len(errors)
        modules.append({
            "module_id": spec.module_id,
            "module_key": spec.module_key,
            "module_name": spec.module_name,
            "status": status,
            "path": str(module_dir),
            "records_exists": records_path.exists(),
            "settings_exists": settings_path.exists(),
            "tombstones_exists": tombstones_path.exists(),
            "manifest_exists": manifest_path.exists(),
            "records_count": _count_records(records_payload),
            "missing_files": missing,
            "json_errors": errors,
            "description": spec.description,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "audited_at": now_text(),
        "base_dir": str(base),
        "module_count": len(MODULE_AUTHORITY_SPECS),
        "missing_required_count": missing_required,
        "invalid_json_count": invalid_json,
        "ok": missing_required == 0 and invalid_json == 0,
        "modules": modules,
    }


def render_authority_inventory_markdown(audit: Optional[Mapping[str, Any]] = None) -> str:
    """Render a V300.13 authority inventory report in Markdown."""
    if audit is None:
        audit = audit_module_authorities()
    lines: List[str] = []
    lines.append("# V300.13 權威檔盤點報告")
    lines.append("")
    lines.append(f"產生時間：{audit.get('audited_at', now_text())}")
    lines.append(f"盤點根目錄：`{audit.get('base_dir', DEFAULT_BASE_DIR)}`")
    lines.append(f"模組數量：{audit.get('module_count', len(MODULE_AUTHORITY_SPECS))}")
    lines.append("")
    lines.append("## 核心原則")
    lines.append("")
    lines.append("- 每個模組各自擁有 `data/permanent_store/modules/<module_key>/records.json` 作為正式權威檔。")
    lines.append("- 既有權威檔不可被空白模板覆蓋；初始化流程只補缺檔，不覆蓋現有資料。")
    lines.append("- Reboot 後應優先讀取各模組權威檔，不可由 `persistent_modules`、SQLite、legacy JSON 或 session cache 反向覆蓋。")
    lines.append("- 刪除必須寫入該模組 tombstone / delete event，避免 01/02 資料復活。")
    lines.append("- 10 權限管理的 `閒置自動登出分鐘數` 使用獨立權威檔 `security_runtime_settings.json`。")
    lines.append("")
    lines.append("## 15 個模組權威檔對照")
    lines.append("")
    lines.append("| 模組 | 權威目錄 | records.json | settings.json | tombstones.json | 狀態 |")
    lines.append("|---|---|---:|---:|---:|---|")
    for item in audit.get("modules", []):
        lines.append(
            f"| {item.get('module_id')} {item.get('module_name')} | "
            f"`{item.get('path')}` | "
            f"{'是' if item.get('records_exists') else '否'} | "
            f"{'是' if item.get('settings_exists') else '否'} | "
            f"{'是' if item.get('tombstones_exists') else '否'} | "
            f"{item.get('status')} |"
        )
    lines.append("")
    lines.append("## 讀寫責任切分")
    lines.append("")
    lines.append("### 讀取順序")
    lines.append("")
    lines.append("1. `data/permanent_store/modules/<module_key>/records.json`")
    lines.append("2. Neon/PostgreSQL 快取或索引 View")
    lines.append("3. session cache")
    lines.append("")
    lines.append("### 寫入順序")
    lines.append("")
    lines.append("1. 使用者操作先寫入該模組權威檔")
    lines.append("2. 同步該模組 tombstone/settings")
    lines.append("3. 再更新 Neon/PostgreSQL 快取或 View")
    lines.append("4. 最後才做 GitHub 備份或背景同步")
    lines.append("")
    lines.append("## 高風險禁止事項")
    lines.append("")
    lines.append("- 不可用空白 `records.json` 覆蓋既有 01/02/10 資料。")
    lines.append("- 不可讓舊 `data/persistent_modules` 或 SQLite 在 Reboot 時覆蓋正式權威檔。")
    lines.append("- 不可為了修復帳號而錯誤套用 `deleted_usernames` 導致啟用帳號坍縮。")
    lines.append("- 不可為了防刪除復活，把 01 今日明細正常資料過濾成 0 筆。")
    lines.append("- 不可在 01/02 熱路徑執行全量 migration、CREATE INDEX 或全表修復。")
    lines.append("")
    lines.append("## 後續建議")
    lines.append("")
    lines.append("1. 先執行 V300.13 安全初始化，只補缺檔。")
    lines.append("2. 再逐一檢查每個模組的讀取/寫入程式是否已改為讀寫自己的權威檔。")
    lines.append("3. 01/02/10 先保持現有邏輯穩定，不再一次性大改。")
    lines.append("4. 之後每次修正包都要附回歸測試結果。")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_BASE_DIR",
    "ModuleAuthoritySpec",
    "MODULE_AUTHORITY_SPECS",
    "get_module_specs",
    "ensure_module_authorities",
    "audit_module_authorities",
    "render_authority_inventory_markdown",
]
