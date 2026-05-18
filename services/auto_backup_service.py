# -*- coding: utf-8 -*-
"""
SPT Time Tracking - V2.96 Scheduled External Backup Service

用途：
- 由 13｜系統設定 設定每日固定時間，自動備份專案所有資料與設定到指定資料夾。
- 不依賴 .bat，不需要 Windows Task Scheduler。
- App 執行期間由背景守護執行；若 App 在排程時間未啟動，下一次啟動或頁面互動會補跑一次。

設計重點：
- 不備份到專案內部，避免遞迴/誤上傳 GitHub。
- 備份整個 data 的正式資料，但排除 data/_persistent_backup、_persistent_corrupt、_persistent_restore_replaced 等備份/暫存區。
- 備份 .streamlit/secrets.toml 與 config.toml。
- 產生 manifest，記錄檔案數、大小、checksum、時間與排程狀態。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PERSISTENT_STATE_DIR = DATA_DIR / "persistent_state"
CONFIG_DIR = DATA_DIR / "config"
SCHEDULE_CONFIG_PATH = CONFIG_DIR / "auto_external_backup_schedule.json"
STATE_PATH = PERSISTENT_STATE_DIR / "auto_external_backup_state.json"

EXCLUDE_DIR_NAMES = {
    "_persistent_backup",
    "_persistent_corrupt",
    "_persistent_restore_replaced",
    "__pycache__",
    ".pytest_cache",
}

DEFAULT_SCHEDULE = {
    "enabled": False,
    "daily_time": "17:30",
    "target_folder": "",
    "keep_days": 30,
    "copy_mode": "folder",
    "include_project_configs": True,
    "include_streamlit_config": True,
    "backup_name_prefix": "SPT_time_tracking_backup",
    "last_updated_at": "",
}

_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()
_BACKUP_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now()


def _now_text() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return _now().strftime("%Y%m%d_%H%M%S")


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception as exc:
        # Do not silently reset backup schedule/state to defaults when JSON is
        # corrupted. Quarantine and try internal backup restore first.
        try:
            from services.persistence_guard_service import quarantine_corrupt_file
            quarantine_corrupt_file(path, reason=str(exc))
        except Exception:
            pass
        try:
            rel = path.resolve().relative_to(PROJECT_ROOT.resolve())
            for backup_root in sorted((DATA_DIR / "_persistent_backup").glob("backup_*"), key=lambda p: p.stat().st_mtime, reverse=True):
                src = backup_root / rel
                if src.exists() and src.stat().st_size > 0:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, path)
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data if isinstance(data, dict) else default
        except Exception:
            pass
        return default


def load_backup_schedule() -> dict[str, Any]:
    cfg = dict(DEFAULT_SCHEDULE)
    data = _json_load(SCHEDULE_CONFIG_PATH, {})
    if isinstance(data, dict):
        cfg.update(data)
    return cfg


def save_backup_schedule(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_SCHEDULE)
    out.update(cfg or {})
    out["enabled"] = bool(out.get("enabled"))
    out["daily_time"] = _normalize_time(out.get("daily_time") or "17:30")
    out["target_folder"] = str(out.get("target_folder") or "").strip()
    try:
        out["keep_days"] = max(1, int(out.get("keep_days") or 30))
    except Exception:
        out["keep_days"] = 30
    out["last_updated_at"] = _now_text()
    _json_dump(SCHEDULE_CONFIG_PATH, out)
    return out


def load_backup_state() -> dict[str, Any]:
    return _json_load(STATE_PATH, {})


def save_backup_state(state: dict[str, Any]) -> None:
    _json_dump(STATE_PATH, state or {})


def _normalize_time(value: str) -> str:
    raw = str(value or "").strip().replace("：", ":")
    try:
        parts = raw.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return f"{h:02d}:{m:02d}"
    except Exception:
        return "17:30"


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def validate_target_folder(path_text: str, *, create: bool = False) -> dict[str, Any]:
    path_text = str(path_text or "").strip().strip('"')
    if not path_text:
        return {"ok": False, "message": "尚未設定備份目標資料夾。"}
    target = Path(path_text).expanduser()
    if not target.is_absolute():
        return {"ok": False, "message": "請輸入完整絕對路徑，例如 D:\\SPT_Backup 或 E:\\Backup\\TimeTracking。", "path": str(target)}
    if _is_relative_to(target, PROJECT_ROOT):
        return {"ok": False, "message": "備份目標不可放在目前專案資料夾內，避免備份遞迴與上傳 GitHub 時變巨大。", "path": str(target)}
    try:
        if create:
            target.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            return {"ok": False, "message": "目標資料夾不存在。可按建立/測試備份，或先手動建立資料夾。", "path": str(target)}
        if not target.is_dir():
            return {"ok": False, "message": "目標路徑不是資料夾。", "path": str(target)}
        test = target / f".spt_write_test_{os.getpid()}.tmp"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return {"ok": True, "path": str(target.resolve())}
    except Exception as exc:
        return {"ok": False, "message": f"目標資料夾無法寫入：{exc}", "path": str(target)}


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    return any(name in parts for name in EXCLUDE_DIR_NAMES)


def _copy_file(src: Path, dest: Path) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    size = dest.stat().st_size
    return {"source": _rel(src), "dest": _rel_external(dest), "bytes": size, "sha256": _sha256_file(dest)}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _rel_external(path: Path) -> str:
    return str(path).replace("\\", "/")


def _iter_backup_sources() -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    # 整個 data 內含表格紀錄、權限、歷史、工時、設定，但排除備份/壞檔/還原暫存。
    if DATA_DIR.exists():
        sources.append((DATA_DIR, "data"))
    streamlit_dir = PROJECT_ROOT / ".streamlit"
    if streamlit_dir.exists():
        sources.append((streamlit_dir, ".streamlit"))
    # 專案層級設定檔；不是主要程式碼，但有助於還原部署設定。
    for filename in ["requirements.txt", "README.md", ".gitignore"]:
        p = PROJECT_ROOT / filename
        if p.exists():
            sources.append((p, filename))
    return sources


def create_external_full_backup(target_folder: str, *, reason: str = "manual", create_target: bool = True) -> dict[str, Any]:
    """Create a full external backup folder under target_folder.

    備份內容：
    - data/ 內所有正式資料與設定，排除內建備份/壞檔/還原暫存。
    - .streamlit/ 設定檔。
    - requirements / README 類部署設定。
    """
    validation = validate_target_folder(target_folder, create=create_target)
    if not validation.get("ok"):
        return {"ok": False, **validation}

    with _BACKUP_LOCK:
        target = Path(validation["path"])
        backup_name = f"{load_backup_schedule().get('backup_name_prefix', 'SPT_time_tracking_backup')}_{_stamp()}"
        backup_dir_final = target / backup_name
        backup_dir = target / f".{backup_name}.partial"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=False)

        copied: list[dict[str, Any]] = []
        total_bytes = 0
        errors: list[str] = []

        for src, dest_rel in _iter_backup_sources():
            try:
                if src.is_dir():
                    for p in src.rglob("*"):
                        if not p.is_file():
                            continue
                        if _should_exclude(p):
                            continue
                        rel = p.relative_to(src)
                        info = _copy_file(p, backup_dir / dest_rel / rel)
                        copied.append(info)
                        total_bytes += int(info.get("bytes") or 0)
                elif src.is_file():
                    if _should_exclude(src):
                        continue
                    info = _copy_file(src, backup_dir / dest_rel)
                    copied.append(info)
                    total_bytes += int(info.get("bytes") or 0)
            except Exception as exc:
                errors.append(f"{_rel(src)}: {exc}")

        manifest = {
            "schema_version": "2.96",
            "backup_time": _now_text(),
            "reason": reason,
            "project_root": str(PROJECT_ROOT),
            "backup_dir": str(backup_dir_final),
            "file_count": len(copied),
            "total_bytes": total_bytes,
            "errors": errors,
            "included": ["data/* except _persistent_backup/_persistent_corrupt/_persistent_restore_replaced", ".streamlit/*", "requirements.txt/README.md/.gitignore when present"],
            "files": copied,
        }
        _json_dump(backup_dir / "SPT_BACKUP_MANIFEST.json", manifest)
        # Atomic folder publish: only complete backups appear without .partial.
        if backup_dir_final.exists():
            backup_dir_final = target / f"{backup_name}_{os.getpid()}"
        backup_dir.rename(backup_dir_final)
        manifest["backup_dir"] = str(backup_dir_final)
        _json_dump(backup_dir_final / "SPT_BACKUP_MANIFEST.json", manifest)

        state = load_backup_state()
        state.update({
            "last_result_ok": len(errors) == 0,
            "last_backup_at": _now_text(),
            "last_backup_dir": str(backup_dir_final),
            "last_file_count": len(copied),
            "last_total_bytes": total_bytes,
            "last_errors": errors,
            "last_reason": reason,
        })
        save_backup_state(state)
        cleanup_old_external_backups(target_folder)

        return {
            "ok": len(errors) == 0,
            "backup_dir": str(backup_dir_final),
            "file_count": len(copied),
            "total_bytes": total_bytes,
            "errors": errors,
        }


def cleanup_old_external_backups(target_folder: str) -> dict[str, Any]:
    cfg = load_backup_schedule()
    try:
        keep_days = max(1, int(cfg.get("keep_days") or 30))
    except Exception:
        keep_days = 30
    validation = validate_target_folder(target_folder, create=False)
    if not validation.get("ok"):
        return {"ok": False, "message": validation.get("message")}
    target = Path(validation["path"])
    cutoff = time.time() - keep_days * 86400
    deleted: list[str] = []
    prefix = str(cfg.get("backup_name_prefix") or "SPT_time_tracking_backup")
    for p in target.glob(f"{prefix}_*"):
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p)
                deleted.append(str(p))
        except Exception:
            pass
    return {"ok": True, "deleted": deleted, "keep_days": keep_days}


def _scheduled_datetime_for_today(daily_time: str) -> datetime:
    daily_time = _normalize_time(daily_time)
    h, m = [int(x) for x in daily_time.split(":", 1)]
    n = _now()
    return n.replace(hour=h, minute=m, second=0, microsecond=0)


def _should_run_schedule(cfg: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str]:
    if not cfg.get("enabled"):
        return False, "schedule disabled"
    target_ok = validate_target_folder(str(cfg.get("target_folder") or ""), create=False)
    if not target_ok.get("ok"):
        return False, target_ok.get("message") or "invalid target"
    scheduled = _scheduled_datetime_for_today(str(cfg.get("daily_time") or "17:30"))
    now = _now()
    if now < scheduled:
        return False, f"not due until {scheduled.strftime('%H:%M')}"
    today = now.strftime("%Y-%m-%d")
    if str(state.get("last_scheduled_run_date") or "") == today and state.get("last_scheduled_ok"):
        return False, "already ran today"
    return True, "due"


def run_due_backup_if_needed(*, force: bool = False) -> dict[str, Any]:
    cfg = load_backup_schedule()
    state = load_backup_state()
    if not force:
        should, reason = _should_run_schedule(cfg, state)
        if not should:
            return {"ok": True, "skipped": True, "reason": reason}
    result = create_external_full_backup(str(cfg.get("target_folder") or ""), reason="scheduled_daily_external_backup" if not force else "forced_scheduled_backup", create_target=True)
    today = _now().strftime("%Y-%m-%d")
    state = load_backup_state()
    state.update({
        "last_checked_at": _now_text(),
        "last_scheduled_run_date": today,
        "last_scheduled_ok": bool(result.get("ok")),
        "last_scheduled_message": "完成" if result.get("ok") else str(result.get("errors") or result.get("message") or result),
    })
    save_backup_state(state)
    return result


def start_auto_backup_scheduler_once() -> dict[str, Any]:
    """Start a daemon thread once per Python process.

    備註：Streamlit / Windows / Cloud 只要 Python process 存活就會執行。
    如果 process 在排程時間休眠或未啟動，下一次啟動時 run_due_backup_if_needed 會補跑。
    """
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return {"ok": True, "started": False, "message": "scheduler already started"}
        _SCHEDULER_STARTED = True

        def _loop():
            while True:
                try:
                    run_due_backup_if_needed(force=False)
                except Exception as exc:
                    state = load_backup_state()
                    state.update({"last_checked_at": _now_text(), "last_scheduler_error": str(exc)})
                    try:
                        save_backup_state(state)
                    except Exception:
                        pass
                time.sleep(60)

        t = threading.Thread(target=_loop, name="SPTExternalAutoBackupScheduler", daemon=True)
        t.start()
        return {"ok": True, "started": True, "message": "scheduler started"}


def get_schedule_status() -> dict[str, Any]:
    cfg = load_backup_schedule()
    state = load_backup_state()
    target = validate_target_folder(str(cfg.get("target_folder") or ""), create=False)
    scheduled = _scheduled_datetime_for_today(str(cfg.get("daily_time") or "17:30"))
    now = _now()
    next_run = scheduled
    if now >= scheduled and str(state.get("last_scheduled_run_date") or "") == now.strftime("%Y-%m-%d") and state.get("last_scheduled_ok"):
        next_run = scheduled + timedelta(days=1)
    elif now >= scheduled and not state.get("last_scheduled_ok"):
        next_run = now
    return {
        "config": cfg,
        "state": state,
        "target_ok": target.get("ok"),
        "target_message": target.get("message", "OK" if target.get("ok") else ""),
        "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S"),
        "scheduler_started": _SCHEDULER_STARTED,
    }
