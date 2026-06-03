# -*- coding: utf-8 -*-
"""SPT V162 safe file write service.

Purpose
-------
Provide durable JSON writes for authority files under data/permanent_store.
It prevents partially-written JSON, reduces concurrent-writer corruption risk,
and keeps point-in-time backups for recovery.

This service is intentionally independent and conservative:
- Atomic replace in the same directory.
- Exclusive lock file while writing.
- Validate temp JSON before replace.
- Validate final JSON after replace.
- Create timestamped backup before replace.
- Restore latest valid backup if requested by caller/tool.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERMANENT_ROOT = PROJECT_ROOT / "data" / "permanent_store"
BACKUP_ROOT = PERMANENT_ROOT / "safety_backups" / "json_authority"
DEFAULT_LOCK_TIMEOUT_SEC = float(os.environ.get("SPT_SAFE_WRITE_LOCK_TIMEOUT", "20"))
DEFAULT_STALE_LOCK_SEC = float(os.environ.get("SPT_SAFE_WRITE_STALE_LOCK_SEC", "120"))
DEFAULT_KEEP_BACKUPS = int(os.environ.get("SPT_SAFE_WRITE_KEEP_BACKUPS", "20"))


def now_text() -> str:
    try:
        from services.timezone_service import now_text as _nt  # type: ignore
        return str(_nt())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stamp_text() -> str:
    try:
        from services.timezone_service import now_compact as _nc  # type: ignore
        return str(_nc())
    except Exception:
        return datetime.now().strftime("%Y%m%d_%H%M%S")


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


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _backup_dir_for(path: Path) -> Path:
    rel = _rel(path)
    safe_parts = [p for p in rel.split("/") if p and p not in (".", "..")]
    return BACKUP_ROOT.joinpath(*safe_parts[:-1])


def _backup_path_for(path: Path, *, reason: str = "write") -> Path:
    name = path.name
    safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(reason or "write"))[:50]
    return _backup_dir_for(path) / f"{name}.{stamp_text()}_{os.getpid()}_{safe_reason}.bak"


def _prune_backups(path: Path, keep: int = DEFAULT_KEEP_BACKUPS) -> None:
    if keep <= 0:
        return
    bdir = _backup_dir_for(path)
    if not bdir.exists():
        return
    pattern = f"{path.name}.*.bak"
    backups = sorted(bdir.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    for old in backups[keep:]:
        with contextlib.suppress(Exception):
            old.unlink()


def latest_valid_backup(path: Path) -> Path | None:
    bdir = _backup_dir_for(path)
    if not bdir.exists():
        return None
    backups = sorted(bdir.glob(f"{path.name}.*.bak"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    for bak in backups:
        try:
            json.loads(bak.read_text(encoding="utf-8"))
            return bak
        except Exception:
            continue
    return None


@contextlib.contextmanager
def file_lock(path: Path, *, timeout: float = DEFAULT_LOCK_TIMEOUT_SEC, stale_after: float = DEFAULT_STALE_LOCK_SEC):
    """Simple cross-platform exclusive lock based on atomic lock-file creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    token = f"pid={os.getpid()} uuid={uuid.uuid4().hex} at={now_text()} target={_rel(path)}\n"
    start = time.time()
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, token.encode("utf-8"))
            os.fsync(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_after:
                    lock_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                    continue
            except Exception:
                pass
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout waiting for file lock: {_rel(lock_path)}")
            time.sleep(0.08)
    try:
        yield lock_path
    finally:
        if fd is not None:
            with contextlib.suppress(Exception):
                os.close(fd)
        with contextlib.suppress(Exception):
            lock_path.unlink()


def create_backup(path: Path, *, reason: str = "before_write", keep: int = DEFAULT_KEEP_BACKUPS) -> Path | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    bpath = _backup_path_for(path, reason=reason)
    bpath.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, bpath)
    _prune_backups(path, keep=keep)
    return bpath


def atomic_write_json_safely(
    path: str | Path,
    payload: Any,
    *,
    default: Callable[[Any], Any] | None = None,
    reason: str = "safe_json_write",
    create_bak: bool = True,
    keep_backups: int = DEFAULT_KEEP_BACKUPS,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Write JSON by validate -> backup -> fsync temp -> atomic replace -> validate.

    Returns metadata useful for health panels and tests.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    default_fn = default or _json_default
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=default_fn)
    parsed = json.loads(text)
    tmp = p.with_name(f".{p.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    bak: Path | None = None
    with file_lock(p, timeout=lock_timeout):
        if create_bak:
            bak = create_backup(p, reason=reason, keep=keep_backups)
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # Validate the exact bytes that will be moved into place.
        json.loads(tmp.read_text(encoding="utf-8"))
        os.replace(tmp, p)
        # fsync parent dir when platform allows it.
        with contextlib.suppress(Exception):
            dfd = os.open(str(p.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        final_data = json.loads(p.read_text(encoding="utf-8"))
        if final_data != parsed:
            raise RuntimeError(f"Safe JSON write verification mismatch: {_rel(p)}")
    with contextlib.suppress(Exception):
        if tmp.exists():
            tmp.unlink()
    return {
        "ok": True,
        "path": _rel(p),
        "backup_path": _rel(bak) if bak else "",
        "bytes": len(text.encode("utf-8")),
        "sha256": _sha256_text(text),
        "updated_at": now_text(),
        "reason": reason,
    }


def read_json_safely(path: str | Path, *, restore_if_corrupt: bool = False, default: Any | None = None) -> Any:
    p = Path(path)
    if not p.exists() or p.stat().st_size <= 0:
        return {} if default is None else default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        if restore_if_corrupt:
            bak = latest_valid_backup(p)
            if bak is not None:
                with file_lock(p):
                    shutil.copy2(bak, p)
                return json.loads(p.read_text(encoding="utf-8"))
        return {} if default is None else default


def is_authority_json_file(path: Path) -> bool:
    name = path.name.lower()
    if name not in {"records.json", "settings.json", "delete_state.json", "authority_manifest.json", "latest_backup.json"}:
        return False
    rel = _rel(path)
    return "/data/permanent_store/" in f"/{rel}" or rel.startswith("data/permanent_store/")


def iter_authority_json_files(root: str | Path | None = None) -> Iterable[Path]:
    base = Path(root) if root else PERMANENT_ROOT
    if not base.exists():
        return []
    return [p for p in base.rglob("*.json") if p.is_file() and is_authority_json_file(p)]


def inspect_json_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    info: dict[str, Any] = {
        "path": _rel(p),
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else 0,
        "valid_json": False,
        "error": "",
        "latest_valid_backup": "",
        "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if p.exists() else "",
    }
    try:
        if p.exists() and p.stat().st_size > 0:
            json.loads(p.read_text(encoding="utf-8"))
            info["valid_json"] = True
    except Exception as exc:
        info["error"] = str(exc)
        bak = latest_valid_backup(p)
        if bak:
            info["latest_valid_backup"] = _rel(bak)
    return info


def authority_file_health(root: str | Path | None = None) -> dict[str, Any]:
    files = list(iter_authority_json_files(root))
    rows = [inspect_json_file(p) for p in files]
    invalid = [r for r in rows if r.get("exists") and not r.get("valid_json")]
    return {
        "checked_at": now_text(),
        "root": _rel(Path(root) if root else PERMANENT_ROOT),
        "total_files": len(rows),
        "valid_files": len(rows) - len(invalid),
        "invalid_files": len(invalid),
        "files": rows,
    }


def repair_corrupted_json_files(root: str | Path | None = None, *, dry_run: bool = True) -> dict[str, Any]:
    health = authority_file_health(root)
    repaired: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in health.get("files", []):
        if row.get("valid_json"):
            continue
        p = PROJECT_ROOT / str(row.get("path", ""))
        bak = latest_valid_backup(p)
        if not bak:
            skipped.append({"path": row.get("path"), "reason": "no valid backup"})
            continue
        if not dry_run:
            with file_lock(p):
                if p.exists():
                    create_backup(p, reason="corrupt_before_restore")
                shutil.copy2(bak, p)
        repaired.append({"path": row.get("path"), "restored_from": _rel(bak), "dry_run": dry_run})
    return {
        "checked_at": now_text(),
        "dry_run": dry_run,
        "repaired_count": len(repaired),
        "skipped_count": len(skipped),
        "repaired": repaired,
        "skipped": skipped,
    }
