# -*- coding: utf-8 -*-
"""SPT permanent-store GitHub write-through helper - V7 speed optimized.

保留原功能與路徑：使用者按儲存後，仍會把必要永久 JSON 寫回 GitHub，
確保 Streamlit Cloud Reboot 後不回復舊設定。

V7 加速重點：
- 只上傳呼叫端指定的檔案。
- 以 SHA256 比對內容，未變更的檔案不重複上傳。
- 失敗只回傳狀態，不讓頁面卡死或崩潰。
"""
from __future__ import annotations

import hashlib
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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _remote_path(local_path: Path) -> str:
    p = Path(local_path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except Exception:
        return ""


def _allowed_remote(remote: str) -> bool:
    # V7: 保留 V5 安全限制，同時相容目前專案仍在使用的 latest JSON 路徑。
    return remote.startswith("data/permanent_store/")


def github_write_through_files(paths: Iterable[Path | str], *, source: str = "settings_save", force: bool = False) -> dict[str, Any]:
    """Upload selected JSON files to GitHub if token is configured.

    V7 會略過內容沒有變更的檔案，避免每次儲存都把所有 mirror 檔重傳。
    """
    raw_paths = list(paths or [])
    unique: list[Path] = []
    seen: set[str] = set()
    for raw in raw_paths:
        path = Path(raw)
        try:
            path = path.resolve()
        except Exception:
            path = Path(raw)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                unique.append(path)
        except Exception:
            pass

    status = _read_json(STATUS_PATH)
    known_hashes = status.get("file_hashes") if isinstance(status.get("file_hashes"), dict) else {}
    result: dict[str, Any] = {
        "ok": True,
        "source": source,
        "uploaded_at": _now_text(),
        "requested_count": len(raw_paths),
        "file_count": len(unique),
        "uploaded_count": 0,
        "skipped_unchanged_count": 0,
        "uploads": [],
        "mode": "v11_skip_unchanged_targeted_upload_force_supported",
        "force": bool(force),
    }
    if not unique:
        result.update({"ok": False, "message": "no existing files to upload"})
        _write_json(STATUS_PATH, {**status, **result})
        return result

    try:
        from services.github_cloud_storage_service import github_config, upload_text_to_github
        cfg = github_config()
        if not cfg.get("token"):
            result.update({"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured"})
            _write_json(STATUS_PATH, {**status, **result})
            return result
        uploads = []
        new_hashes = dict(known_hashes or {})
        for path in unique:
            remote = _remote_path(path)
            if not remote or not _allowed_remote(remote):
                uploads.append({"ok": False, "path": str(path), "message": "refuse to upload unknown data path"})
                continue
            try:
                text = path.read_text(encoding="utf-8")
                json.loads(text)  # validate JSON before upload
                digest = _sha256_text(text)
                if (not force) and str(known_hashes.get(remote) or "") == digest:
                    uploads.append({"ok": True, "path": remote, "skipped": True, "message": "unchanged"})
                    result["skipped_unchanged_count"] += 1
                    continue
                up = upload_text_to_github(remote, text, f"SPT V7 write-through {source}: {remote}")
                uploads.append(up)
                if up.get("ok"):
                    new_hashes[remote] = digest
                    result["uploaded_count"] += 1
            except Exception as exc:
                uploads.append({"ok": False, "path": remote, "message": str(exc)})
        result["uploads"] = uploads
        result["ok"] = bool(uploads) and all(bool(u.get("ok")) for u in uploads)
        status["file_hashes"] = new_hashes
    except Exception as exc:
        result.update({"ok": False, "message": f"GitHub write-through unavailable: {exc}"})

    try:
        status.update(result)
        _write_json(STATUS_PATH, status)
    except Exception:
        pass
    return result

# ===== V20.0 compatibility alias for time-record/system write-through =====
def write_through_paths(paths, reason: str = "write_through_paths", force: bool = False):
    """Backward-compatible wrapper used by older V18/V19 patches."""
    return github_write_through_files(paths, source=reason, force=force)
# ===== V20.0 compatibility alias END =====
