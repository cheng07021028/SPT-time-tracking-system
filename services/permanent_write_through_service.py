# -*- coding: utf-8 -*-
"""SPT permanent-store GitHub write-through helper.

Purpose:
- Keep Streamlit Cloud reboot persistence deterministic.
- When a user presses Save/Apply for settings that live in JSON files, upload
  exactly those JSON files to GitHub immediately.
- This is intentionally targeted; it does not upload the whole project and it
  never deletes data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_write_through_status.json"


def _now_text() -> str:
    try:
        from services.timezone_service import now_text
        return now_text()
    except Exception:
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _remote_path(local_path: Path) -> str:
    p = Path(local_path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except Exception:
        # Safety: only upload files inside this project. Unknown files are rejected.
        return ""


def github_write_through_files(paths: Iterable[Path | str], *, source: str = "settings_save") -> dict[str, Any]:
    """Upload selected permanent JSON files to GitHub if token is configured.

    Returns a structured result. Failure is reported but never raises, so the UI
    can still show a precise warning instead of crashing.
    """
    unique: list[Path] = []
    seen: set[str] = set()
    for raw in paths or []:
        path = Path(raw)
        try:
            path = path.resolve()
        except Exception:
            path = Path(raw)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            unique.append(path)

    result: dict[str, Any] = {
        "ok": True,
        "source": source,
        "uploaded_at": _now_text(),
        "requested_count": len(list(paths or [])) if not isinstance(paths, list) else len(paths),
        "file_count": len(unique),
        "uploads": [],
    }
    if not unique:
        result.update({"ok": False, "message": "no existing files to upload"})
        _write_json(STATUS_PATH, result)
        return result

    try:
        from services.github_cloud_storage_service import github_config, upload_text_to_github
        cfg = github_config()
        if not cfg.get("token"):
            result.update({"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured"})
            _write_json(STATUS_PATH, result)
            return result
        uploads = []
        for path in unique:
            remote = _remote_path(path)
            if not remote or not remote.startswith("data/permanent_store/"):
                uploads.append({"ok": False, "path": str(path), "message": "refuse to upload non permanent_store file"})
                continue
            try:
                text = path.read_text(encoding="utf-8")
                # Validate JSON before upload; most permanent files here are JSON.
                json.loads(text)
                uploads.append(upload_text_to_github(remote, text, f"SPT write-through {source}: {remote}"))
            except Exception as exc:
                uploads.append({"ok": False, "path": remote, "message": str(exc)})
        result["uploads"] = uploads
        result["ok"] = bool(uploads) and all(bool(u.get("ok")) for u in uploads)
    except Exception as exc:
        result.update({"ok": False, "message": f"GitHub write-through unavailable: {exc}"})

    try:
        status = _read_json(STATUS_PATH)
        status.update(result)
        _write_json(STATUS_PATH, status)
    except Exception:
        pass
    return result
