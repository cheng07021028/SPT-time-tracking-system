# -*- coding: utf-8 -*-
"""
SPT Time Tracking - V2.94 Persistence Guard Service

目的：
- 防止更新模組、Reboot App、SQLite 重建或 JSON 讀取失敗時，資料/設定靜默回到預設值。
- 提供安全備份、健康檢查、最近備份還原、atomic JSON save、manifest/checksum。

設計原則：
- 不改業務邏輯。
- 不覆蓋 data 內既有資料。
- App 啟動時只做輕量檢查，避免拖慢 Reboot。
- 備份/還原可由 13｜系統設定或 tools/*.py 執行；必要時 DB 遺失才自動嘗試還原 DB。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PERSISTENT_MODULES_DIR = DATA_DIR / "permanent_store" / "persistent_modules"
PERSISTENT_STATE_DIR = DATA_DIR / "permanent_store" / "persistent_state"
DATABASE_DIR = DATA_DIR / "permanent_store" / "database"
DB_PATH = DATABASE_DIR / "spt_time_tracking.db"
STREAMLIT_DIR = PROJECT_ROOT / ".streamlit"
SECRETS_PATH = STREAMLIT_DIR / "secrets.toml"
CONFIG_PATH = STREAMLIT_DIR / "config.toml"
PROJECT_CONFIG_MIRROR_DIR = DATA_DIR / "permanent_store" / "config" / "_project_config_mirror"

BACKUP_ROOT = DATA_DIR / "_persistent_backup"
MANIFEST_PATH = PERSISTENT_STATE_DIR / "persistent_guard_manifest.json"
INITIALIZED_MARKER = PERSISTENT_STATE_DIR / ".spt_initialized"
BOOT_GUARD_MARKER = PERSISTENT_STATE_DIR / ".persistence_guard_boot.json"
CORRUPT_DIR = DATA_DIR / "_persistent_corrupt"

PROTECTED_RELATIVE_PATHS = [
    "data/permanent_store/persistent_modules",
    "data/permanent_store/persistent_state",
    "data/permanent_store/database",
    "data/permanent_store/config",
    "data/permanent_store/config/_project_config_mirror/.streamlit/secrets.toml",
    "data/permanent_store/config/_project_config_mirror/.streamlit/config.toml",
]

CORE_TABLES = [
    "work_orders", "employees", "time_records",
    "auth_users", "auth_account_permissions",
    "security_users", "security_user_roles", "security_module_permissions",
    "system_settings", "table_column_settings", "rest_periods", "process_options",
]

BUSINESS_TABLES = ["work_orders", "employees", "time_records"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dump(path: Path, payload: Any) -> None:
    """Atomic JSON dump used by guard metadata.

    Even guard metadata should never be half-written, because corrupted guard
    files can make the app believe no backup exists and then recreate defaults.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # Validate before replace.
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def atomic_save_json(path: Path | str, payload: Any, *, backup_existing: bool = True) -> dict[str, Any]:
    """安全寫入 JSON：先寫 tmp、驗證可讀，再 replace 正式檔。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup_existing and target.exists() and target.stat().st_size > 0:
        hist = target.parent / "history"
        hist.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, hist / f"{target.stem}_{_stamp()}{target.suffix}")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # 驗證 tmp 是合法 JSON；不合法就不碰正式檔。
    _json_load(tmp)
    tmp.replace(target)
    return {"ok": True, "path": _rel(target), "bytes": target.stat().st_size, "sha256": _sha256_file(target)}


def safe_load_json(path: Path | str, default: Any = None, *, allow_default_when_missing: bool = True) -> Any:
    """安全讀 JSON。

    - 檔案不存在：依 allow_default_when_missing 決定回 default 或丟錯。
    - 檔案存在但壞掉：不靜默回 default，先封存壞檔，再嘗試最近備份還原；失敗就丟錯。
    """
    target = Path(path)
    if not target.exists():
        # If the project has already been initialized, a missing protected JSON
        # is not treated as a clean install. Try to restore it from internal or
        # external backups before allowing defaults.
        if is_initialized():
            restored = restore_single_file_from_latest_backup(target)
            if restored.get("ok"):
                return _json_load(target)
        if allow_default_when_missing:
            return default
        raise FileNotFoundError(f"Persistent JSON not found: {_rel(target)}")
    try:
        if target.stat().st_size <= 0:
            raise ValueError("file is empty")
        return _json_load(target)
    except Exception as exc:
        corrupt = quarantine_corrupt_file(target, reason=str(exc))
        restored = restore_single_file_from_latest_backup(target)
        if restored.get("ok"):
            return _json_load(target)
        raise RuntimeError(
            f"Persistent JSON exists but cannot be read; default overwrite blocked: {_rel(target)}; "
            f"corrupt copy={corrupt.get('quarantine_path')}; error={exc}"
        ) from exc


def quarantine_corrupt_file(path: Path, reason: str = "") -> dict[str, Any]:
    CORRUPT_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {"ok": False, "message": "file not found", "path": _rel(path)}
    dest = CORRUPT_DIR / f"{path.name}.{_stamp()}.corrupt"
    try:
        shutil.copy2(path, dest)
        meta = dest.with_suffix(dest.suffix + ".json")
        _json_dump(meta, {"time": _now(), "source": _rel(path), "reason": reason})
        return {"ok": True, "quarantine_path": _rel(dest)}
    except Exception as exc:
        return {"ok": False, "message": str(exc), "path": _rel(path)}


def _copy_path_to_backup(src: Path, backup_dir: Path) -> list[str]:
    created: list[str] = []
    if not src.exists():
        return created
    rel = src.relative_to(PROJECT_ROOT)
    dest = backup_dir / rel
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
        for p in dest.rglob("*"):
            if p.is_file():
                created.append(_rel(p))
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(_rel(dest))
    return created



def sync_project_config_mirror_to_data() -> dict[str, Any]:
    """Mirror non-data project settings into data/permanent_store/config/_project_config_mirror.

    This keeps backup/restore sources centralized under data/, while still
    preserving Streamlit deployment settings when they exist.
    """
    mirrored: list[dict[str, Any]] = []
    errors: list[str] = []
    candidates: list[tuple[Path, Path]] = [
        (CONFIG_PATH, PROJECT_CONFIG_MIRROR_DIR / ".streamlit" / "config.toml"),
        (SECRETS_PATH, PROJECT_CONFIG_MIRROR_DIR / ".streamlit" / "secrets.toml"),
        (PROJECT_ROOT / "requirements.txt", PROJECT_CONFIG_MIRROR_DIR / "project_files" / "requirements.txt"),
        (PROJECT_ROOT / "README.md", PROJECT_CONFIG_MIRROR_DIR / "project_files" / "README.md"),
        (PROJECT_ROOT / ".gitignore", PROJECT_CONFIG_MIRROR_DIR / "project_files" / ".gitignore"),
    ]
    for src, dest in candidates:
        try:
            if not src.exists() or not src.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            mirrored.append({"source": _rel(src), "mirror": _rel(dest), "bytes": dest.stat().st_size})
        except Exception as exc:
            errors.append(f"{_rel(src)} -> {_rel(dest)}: {exc}")
    try:
        _json_dump(PROJECT_CONFIG_MIRROR_DIR / "PROJECT_CONFIG_MIRROR_MANIFEST.json", {
            "schema_version": "2.99",
            "updated_at": _now(),
            "note": "Non-data deployment configs are mirrored here so backups keep protected settings under data/.",
            "mirrored": mirrored,
            "errors": errors,
        })
    except Exception as exc:
        errors.append(f"mirror manifest write failed: {exc}")
    return {"ok": len(errors) == 0, "mirrored": mirrored, "errors": errors, "mirror_dir": _rel(PROJECT_CONFIG_MIRROR_DIR)}


def _copy_data_tree_to_backup(backup_dir: Path, *, include_database: bool = True) -> list[str]:
    """Copy critical data subfolders into backup without recursive backup caches."""
    created: list[str] = []
    sources = [PERSISTENT_MODULES_DIR, PERSISTENT_STATE_DIR, DATA_DIR / "permanent_store" / "config"]
    if include_database:
        sources.append(DATABASE_DIR)
    for src in sources:
        created.extend(_copy_path_to_backup(src, backup_dir))
    return created

def create_persistent_backup(reason: str = "manual", include_database: bool = True) -> dict[str, Any]:
    """備份所有重要資料與設定；不修改正式資料。"""
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    backup_dir = BACKUP_ROOT / f"backup_{_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    mirror_result = sync_project_config_mirror_to_data()

    created: list[str] = _copy_data_tree_to_backup(backup_dir, include_database=include_database)

    health = check_persistent_health(write_manifest=False)
    manifest = {
        "schema_version": "2.94",
        "backup_time": _now(),
        "reason": reason,
        "backup_dir": _rel(backup_dir),
        "protected_paths": PROTECTED_RELATIVE_PATHS,
        "all_protected_sources_under_data": True,
        "project_config_mirror": mirror_result,
        "file_count": len(created),
        "health": health,
    }
    _json_dump(backup_dir / "persistent_backup_manifest.json", manifest)
    _write_latest_backup_pointer(backup_dir)
    ensure_initialized_marker()
    return {"ok": True, "backup_dir": _rel(backup_dir), "file_count": len(created), "health": health}


def _write_latest_backup_pointer(backup_dir: Path) -> None:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    _json_dump(BACKUP_ROOT / "latest_backup.json", {"time": _now(), "backup_dir": _rel(backup_dir)})


def list_persistent_backups() -> list[Path]:
    if not BACKUP_ROOT.exists():
        return []
    items = [p for p in BACKUP_ROOT.glob("backup_*") if p.is_dir()]
    return sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)


def _external_backup_root_candidates() -> list[Path]:
    """Return possible external backup roots configured from 13｜系統設定.

    This intentionally avoids importing Streamlit and never modifies settings.
    """
    roots: list[Path] = []
    for p in [
        DATA_DIR / "permanent_store" / "config" / "auto_external_backup_schedule.json",
        PERSISTENT_STATE_DIR / "auto_external_backup_state.json",
    ]:
        try:
            if not p.exists() or p.stat().st_size <= 0:
                continue
            payload = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            for key in ("target_folder", "backup_root", "root", "folder"):
                value = str(payload.get(key) or "").strip().strip('"')
                if value:
                    roots.append(Path(value).expanduser())
            value = str(payload.get("last_backup_dir") or "").strip().strip('"')
            if value:
                last = Path(value).expanduser()
                roots.append(last.parent if last.name else last)
        except Exception:
            continue
    # Deduplicate preserving order.
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        try:
            key = str(r.resolve())
        except Exception:
            key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def list_external_persistent_backups() -> list[Path]:
    """List external full backups created from 13｜系統設定.

    External backups have the same project-relative layout (data/...,
    .streamlit/...) and contain SPT_BACKUP_MANIFEST.json. These must be included
    in restore/search fallback, otherwise the system may say no backup exists even
    when the user selected an external backup folder.
    """
    items: list[Path] = []
    for root in _external_backup_root_candidates():
        try:
            if not root.exists() or not root.is_dir():
                continue
            for p in root.glob("SPT_time_tracking_backup_*"):
                if p.is_dir() and ((p / "SPT_BACKUP_MANIFEST.json").exists() or (p / "data").exists()):
                    items.append(p)
            # Also allow custom backup name prefixes; manifest is the reliable marker.
            for manifest in root.glob("*/SPT_BACKUP_MANIFEST.json"):
                parent = manifest.parent
                if parent.is_dir() and parent not in items:
                    items.append(parent)
        except Exception:
            continue
    return sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)


def list_all_persistent_backups(include_external: bool = True) -> list[Path]:
    items = list_persistent_backups()
    if include_external:
        items.extend(list_external_persistent_backups())
    seen: set[str] = set()
    out: list[Path] = []
    for p in sorted(items, key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def latest_backup_dir() -> Path | None:
    items = list_all_persistent_backups(include_external=True)
    return items[0] if items else None


def restore_latest_persistent_backup(*, include_secrets: bool = False) -> dict[str, Any]:
    backup = latest_backup_dir()
    if not backup:
        return {"ok": False, "message": "找不到任何 data/_persistent_backup/backup_* 備份。"}
    return restore_persistent_backup(backup, include_secrets=include_secrets)


def restore_persistent_backup(backup_dir: Path | str, *, include_secrets: bool = False) -> dict[str, Any]:
    """還原最近備份。預設不還原 secrets，避免誤覆蓋 token。"""
    bdir = Path(backup_dir)
    if not bdir.exists():
        return {"ok": False, "message": f"備份不存在：{backup_dir}"}
    restored: list[str] = []
    for rel in ["data/permanent_store/persistent_modules", "data/permanent_store/persistent_state", "data/permanent_store/database"]:
        src = bdir / rel
        if src.exists():
            dest = PROJECT_ROOT / rel
            if dest.exists():
                safety = PROJECT_ROOT / "data" / "_persistent_restore_replaced" / f"{dest.name}_{_stamp()}"
                safety.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_dir():
                    shutil.copytree(dest, safety, dirs_exist_ok=True)
                else:
                    shutil.copy2(dest, safety)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            restored.append(rel)
    if include_secrets:
        # V2.99: backups keep these under data/permanent_store/config/_project_config_mirror.
        # Older backups with direct .streamlit paths are still supported.
        for rel, mirror_rel in [
            (".streamlit/secrets.toml", "data/permanent_store/config/_project_config_mirror/.streamlit/secrets.toml"),
            (".streamlit/config.toml", "data/permanent_store/config/_project_config_mirror/.streamlit/config.toml"),
        ]:
            src = bdir / mirror_rel
            if not src.exists():
                src = bdir / rel
            if src.exists():
                dest = PROJECT_ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                restored.append(rel)
    ensure_initialized_marker()
    return {"ok": True, "source": _rel(bdir), "restored": restored}


def restore_single_file_from_latest_backup(target: Path | str) -> dict[str, Any]:
    target = Path(target)
    try:
        rel = target.resolve().relative_to(PROJECT_ROOT.resolve())
    except Exception:
        return {"ok": False, "message": "target outside project root"}
    mirror_rel = None
    if str(rel).replace("\\", "/") == ".streamlit/secrets.toml":
        mirror_rel = Path("data/permanent_store/config/_project_config_mirror/.streamlit/secrets.toml")
    elif str(rel).replace("\\", "/") == ".streamlit/config.toml":
        mirror_rel = Path("data/permanent_store/config/_project_config_mirror/.streamlit/config.toml")
    for backup in list_all_persistent_backups(include_external=True):
        candidates = [backup / rel]
        if mirror_rel is not None:
            candidates.insert(0, backup / mirror_rel)
        for src in candidates:
            if src.exists() and src.is_file() and src.stat().st_size > 0:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                return {"ok": True, "source": _rel(src), "target": _rel(target)}
    return {"ok": False, "message": f"找不到可還原單檔：{_rel(target)}"}


def ensure_initialized_marker() -> None:
    PERSISTENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not INITIALIZED_MARKER.exists():
        INITIALIZED_MARKER.write_text(_now(), encoding="utf-8")


def is_initialized() -> bool:
    return INITIALIZED_MARKER.exists()


def _db_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    if not DB_PATH.exists():
        return counts
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            for t in CORE_TABLES:
                try:
                    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
                    if row:
                        counts[t] = int(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] or 0)
                except Exception:
                    counts[t] = -1
        finally:
            conn.close()
    except Exception:
        return {"__error__": -1}
    return counts


def _json_file_status(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {"path": _rel(path), "exists": path.exists()}
    if not path.exists():
        return item
    item["bytes"] = path.stat().st_size
    item["mtime"] = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    try:
        payload = _json_load(path)
        item["ok"] = True
        item["sha256"] = _sha256_file(path)
        if isinstance(payload, list):
            item["row_count"] = len(payload)
        elif isinstance(payload, dict):
            if isinstance(payload.get("tables"), dict):
                counts: dict[str, int] = {}
                for k, v in payload["tables"].items():
                    if isinstance(v, list):
                        counts[k] = len(v)
                    elif isinstance(v, dict) and isinstance(v.get("records"), list):
                        counts[k] = len(v["records"])
                item["table_counts"] = counts
            for key in ["records", "data"]:
                if isinstance(payload.get(key), list):
                    item["row_count"] = len(payload[key])
    except Exception as exc:
        item["ok"] = False
        item["error"] = str(exc)
    return item


def check_persistent_health(write_manifest: bool = True) -> dict[str, Any]:
    """檢查重要資料健康狀態。"""
    PERSISTENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    json_targets = [
        PERSISTENT_STATE_DIR / "spt_permanent_state.json",
        PERSISTENT_STATE_DIR / "spt_module_settings.json",
        PERSISTENT_STATE_DIR / "spt_audit_log_state.json",
        PERSISTENT_STATE_DIR / "spt_idle_timeout_settings.json",
        PERSISTENT_MODULES_DIR / "01_time_records" / "01_time_records_records.json",
        PERSISTENT_MODULES_DIR / "02_history" / "02_history_records.json",
        PERSISTENT_MODULES_DIR / "03_work_orders" / "03_work_orders_records.json",
        PERSISTENT_MODULES_DIR / "04_employees" / "04_employees_records.json",
        PERSISTENT_MODULES_DIR / "10_permissions" / "10_permissions_records.json",
        PERSISTENT_MODULES_DIR / "10_permissions" / "10_permissions_settings.json",
    ]
    json_status = [_json_file_status(p) for p in json_targets]
    db_counts = _db_counts()
    warnings: list[str] = []
    errors: list[str] = []

    for item in json_status:
        if item.get("exists") and not item.get("ok", True):
            errors.append(f"JSON 讀取失敗：{item.get('path')}｜{item.get('error')}")
    if DB_PATH.exists():
        business_total = sum(max(0, int(db_counts.get(t, 0))) for t in BUSINESS_TABLES)
        if is_initialized() and business_total == 0:
            warnings.append("已初始化專案的 SQLite 主資料筆數為 0，可能是資料庫重建或讀取來源跑掉。")
    elif is_initialized():
        warnings.append("已初始化專案找不到 SQLite DB，可能會觸發預設初始化。")

    manifest = {
        "schema_version": "2.94",
        "checked_at": _now(),
        "initialized": is_initialized(),
        "project_root": str(PROJECT_ROOT),
        "db_path": _rel(DB_PATH),
        "db_exists": DB_PATH.exists(),
        "db_counts": db_counts,
        "json_status": json_status,
        "warnings": warnings,
        "errors": errors,
        "internal_backup_count": len(list_persistent_backups()),
        "external_backup_count": len(list_external_persistent_backups()),
        "latest_backup_dir": str(latest_backup_dir() or ""),
    }
    if write_manifest:
        _json_dump(MANIFEST_PATH, manifest)
    return manifest


def guard_before_database_init() -> dict[str, Any]:
    """DB schema 初始化前的輕量保護。

    專業防護原則：只要專案已有任何持久資料或備份跡象，就不能把 DB
    遺失視為第一次安裝。若 DB 不見，會先從內建或外部備份還原；找不到
    備份才允許 schema 建立，但會在 health manifest 留警告。
    """
    PERSISTENT_STATE_DIR.mkdir(parents=True, exist_ok=True)

    existing_evidence = any([
        INITIALIZED_MARKER.exists(),
        bool(list_all_persistent_backups(include_external=True)),
        any(PERSISTENT_MODULES_DIR.rglob("*.json")) if PERSISTENT_MODULES_DIR.exists() else False,
        any(PERSISTENT_STATE_DIR.glob("*.json")) if PERSISTENT_STATE_DIR.exists() else False,
    ])

    if not DB_PATH.exists() and existing_evidence:
        for backup in list_all_persistent_backups(include_external=True):
            src = backup / "data" / "permanent_store" / "database" / DB_PATH.name
            if src.exists() and src.stat().st_size > 0:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, DB_PATH)
                ensure_initialized_marker()
                return {"ok": True, "restored_db": _rel(src), "source_backup": str(backup)}
        ensure_initialized_marker()
        return {"ok": False, "warning": "DB missing; persistent evidence exists but no backup DB found. Schema creation allowed without overwriting persistent JSON."}

    if not is_initialized():
        ensure_initialized_marker()
        return {"ok": True, "first_init": True, "message": "initialized marker created"}

    return {"ok": True, "skipped": True}


def guard_after_database_init() -> dict[str, Any]:
    """DB 初始化後健康檢查；不做重型備份，避免拖慢。"""
    health = check_persistent_health(write_manifest=True)
    # 每個 process 最多 6 小時做一次輕量備份，避免 Reboot 每次都慢。
    try:
        last = 0.0
        if BOOT_GUARD_MARKER.exists():
            payload = _json_load(BOOT_GUARD_MARKER)
            last = float(payload.get("last_backup_ts", 0) or 0)
        now_ts = time.time()
        has_backup = bool(list_persistent_backups())
        if (not has_backup) or (now_ts - last > 6 * 3600):
            # 僅備份 data 內資料與 DB，不含 secrets，避免過慢與敏感資料擴散。
            create_persistent_backup(reason="auto_boot_guard", include_database=True)
            _json_dump(BOOT_GUARD_MARKER, {"last_backup_ts": now_ts, "last_backup_at": _now()})
    except Exception:
        pass
    return {"ok": True, "health": health}


def print_health_report() -> int:
    health = check_persistent_health(write_manifest=True)
    print(json.dumps(health, ensure_ascii=False, indent=2, default=str))
    return 1 if health.get("errors") else 0
