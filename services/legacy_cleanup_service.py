# -*- coding: utf-8 -*-
"""Legacy path cleanup utilities for SPT Time Tracking.

Purpose
-------
The current architecture treats ``data/permanent_store/`` as the only official
runtime/persistence source.  Older builds used several root-level folders such
as ``data/persistent_modules`` and ``data/persistent_state``.  If those folders
remain in a GitHub repository or a Streamlit container, an old helper function or
manual restore flow may accidentally read stale data.

This service provides a guarded cleanup operation for 13｜系統設定:
- delete local legacy folders/files only;
- optionally delete matching legacy paths from GitHub through Contents API;
- never touch ``data/permanent_store``.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERMANENT_ROOT = (PROJECT_ROOT / "data" / "permanent_store").resolve()

# Local paths that are explicitly considered obsolete after the single-store migration.
# Keep this list narrow.  Do not include data/logo, import, export, tools, pages, services.
LEGACY_LOCAL_PATHS: List[Path] = [
    PROJECT_ROOT / "data" / "persistent_modules",
    PROJECT_ROOT / "data" / "persistent_state",
    PROJECT_ROOT / "data" / "database",
    PROJECT_ROOT / "data" / "config",
    PROJECT_ROOT / "date" / "persistent_state",      # old typo path used in early cloud persistence
    PROJECT_ROOT / "data" / "persisten_state",       # old typo path used in early cloud persistence
]

# Remote repo paths that must not exist after the migration.  These are GitHub
# repository paths, not local OS paths.
LEGACY_REMOTE_PATHS: List[str] = [
    "data/persistent_modules",
    "data/persistent_state",
    "data/database",
    "data/config",
    "date/persistent_state",
    "data/persisten_state",
]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def _is_safe_legacy_path(path: Path) -> bool:
    """Return True only for explicit legacy paths under PROJECT_ROOT and outside permanent_store."""
    try:
        resolved = path.resolve()
        resolved.relative_to(PROJECT_ROOT.resolve())
    except Exception:
        return False
    try:
        resolved.relative_to(PERMANENT_ROOT)
        return False
    except Exception:
        pass
    allowed = {p.resolve() for p in LEGACY_LOCAL_PATHS}
    return resolved in allowed


def get_legacy_local_status() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in LEGACY_LOCAL_PATHS:
        exists = path.exists()
        count = 0
        size = 0
        if exists:
            if path.is_file():
                count = 1
                try:
                    size = path.stat().st_size
                except Exception:
                    size = 0
            else:
                for item in path.rglob("*"):
                    if item.is_file():
                        count += 1
                        try:
                            size += item.stat().st_size
                        except Exception:
                            pass
        rows.append({
            "路徑 / Path": _safe_relative(path),
            "存在 / Exists": exists,
            "檔案數 / Files": count,
            "大小 / Size": size,
            "安全判定 / Guard": "可清除" if _is_safe_legacy_path(path) else "保護中，不清除",
        })
    return rows


def cleanup_legacy_local_paths(dry_run: bool = False) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    deleted = 0
    skipped = 0
    errors: List[str] = []
    for path in LEGACY_LOCAL_PATHS:
        exists = path.exists()
        safe = _is_safe_legacy_path(path)
        item: Dict[str, Any] = {
            "path": _safe_relative(path),
            "exists": exists,
            "safe": safe,
            "action": "none",
            "ok": True,
        }
        if not exists:
            item["action"] = "not_found"
            skipped += 1
        elif not safe:
            item["action"] = "blocked_by_guard"
            item["ok"] = False
            skipped += 1
        elif dry_run:
            item["action"] = "dry_run_delete"
        else:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                item["action"] = "deleted"
                deleted += 1
            except Exception as exc:
                item["action"] = "error"
                item["ok"] = False
                item["error"] = str(exc)
                errors.append(f"{_safe_relative(path)}: {exc}")
        rows.append(item)
    return {
        "ok": len(errors) == 0,
        "deleted_count": deleted,
        "skipped_count": skipped,
        "dry_run": dry_run,
        "rows": rows,
        "errors": errors,
        "message": "舊本機路徑清理完成" if not errors else "舊本機路徑清理有錯誤",
        "cleaned_at": _now_text(),
    }


def _read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st  # type: ignore
        val = st.secrets.get(name, "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, default).strip()


def _github_cfg() -> Dict[str, str]:
    return {
        "token": _read_secret("GITHUB_TOKEN"),
        "repo": _read_secret("GITHUB_REPOSITORY", "cheng07021028/SPT-time-tracking-system"),
        "branch": _read_secret("GITHUB_BRANCH", "main"),
    }


def _github_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import json
    import urllib.error
    import urllib.request

    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SPT-Time-Tracking-Legacy-Cleanup",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": parsed}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"message": body}
        return {"ok": False, "status": exc.code, "body": parsed}
    except Exception as exc:
        return {"ok": False, "status": 0, "body": {"message": str(exc)}}


def _contents_url(repo: str, path: str, branch: str) -> str:
    import urllib.parse
    encoded = urllib.parse.quote(path.strip("/"), safe="/")
    return f"https://api.github.com/repos/{repo}/contents/{encoded}?ref={urllib.parse.quote(branch)}"


def _delete_url(repo: str, path: str) -> str:
    import urllib.parse
    encoded = urllib.parse.quote(path.strip("/"), safe="/")
    return f"https://api.github.com/repos/{repo}/contents/{encoded}"


def _list_remote_files(repo: str, branch: str, token: str, path: str) -> List[Dict[str, str]]:
    """Recursively list files under a GitHub contents path. Missing path returns []."""
    res = _github_request("GET", _contents_url(repo, path, branch), token)
    if res.get("status") == 404:
        return []
    if not res.get("ok"):
        return [{"path": path, "type": "error", "message": str(res.get("body", {}).get("message", res.get("body")))}]
    body = res.get("body")
    files: List[Dict[str, str]] = []
    if isinstance(body, dict):
        if body.get("type") == "file":
            files.append({"path": str(body.get("path", path)), "sha": str(body.get("sha", "")), "type": "file"})
        return files
    if isinstance(body, list):
        for entry in body:
            if not isinstance(entry, dict):
                continue
            etype = str(entry.get("type", ""))
            epath = str(entry.get("path", ""))
            if etype == "file":
                files.append({"path": epath, "sha": str(entry.get("sha", "")), "type": "file"})
            elif etype == "dir":
                files.extend(_list_remote_files(repo, branch, token, epath))
    return files


def get_legacy_remote_status() -> Dict[str, Any]:
    cfg = _github_cfg()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "skipped": True, "message": "未設定 GITHUB_TOKEN，無法檢查 GitHub 舊路徑。", "rows": []}
    rows: List[Dict[str, Any]] = []
    for remote in LEGACY_REMOTE_PATHS:
        files = _list_remote_files(repo, branch, token, remote)
        error_items = [x for x in files if x.get("type") == "error"]
        rows.append({
            "GitHub 路徑 / Remote Path": remote,
            "存在檔案數 / Files": len([x for x in files if x.get("type") == "file"]),
            "狀態 / Status": "錯誤" if error_items else ("有舊檔" if files else "不存在"),
            "說明 / Detail": error_items[0].get("message", "") if error_items else "",
        })
    return {"ok": True, "repo": repo, "branch": branch, "rows": rows}


def cleanup_legacy_remote_paths(dry_run: bool = False) -> Dict[str, Any]:
    cfg = _github_cfg()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "skipped": True, "message": "未設定 GITHUB_TOKEN，無法清除 GitHub 舊路徑。", "rows": []}
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    deleted = 0
    checked = 0
    for remote_root in LEGACY_REMOTE_PATHS:
        files = _list_remote_files(repo, branch, token, remote_root)
        for file_item in files:
            if file_item.get("type") == "error":
                rows.append({"path": remote_root, "action": "list_error", "ok": False, "error": file_item.get("message", "")})
                errors.append(f"{remote_root}: {file_item.get('message', '')}")
                continue
            path = str(file_item.get("path", ""))
            sha = str(file_item.get("sha", ""))
            checked += 1
            if not path or not sha:
                continue
            if "data/permanent_store" in path.replace("\\", "/"):
                rows.append({"path": path, "action": "blocked_permanent_store", "ok": False})
                continue
            if dry_run:
                rows.append({"path": path, "action": "dry_run_delete", "ok": True})
                continue
            payload = {
                "message": f"Remove legacy SPT persistence file {path}",
                "sha": sha,
                "branch": branch,
            }
            res = _github_request("DELETE", _delete_url(repo, path), token, payload)
            ok = bool(res.get("ok"))
            rows.append({"path": path, "action": "deleted" if ok else "delete_error", "ok": ok, "status": res.get("status"), "detail": res.get("body")})
            if ok:
                deleted += 1
            else:
                errors.append(f"{path}: {res.get('body')}")
    return {
        "ok": len(errors) == 0,
        "repo": repo,
        "branch": branch,
        "checked_file_count": checked,
        "deleted_file_count": deleted,
        "dry_run": dry_run,
        "rows": rows,
        "errors": errors,
        "message": "GitHub 舊路徑清理完成" if not errors else "GitHub 舊路徑清理有錯誤",
        "cleaned_at": _now_text(),
    }


def cleanup_legacy_paths(include_github: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    local = cleanup_legacy_local_paths(dry_run=dry_run)
    remote: Dict[str, Any] = {"skipped": True, "message": "未勾選 GitHub 舊路徑清理。", "rows": []}
    if include_github:
        remote = cleanup_legacy_remote_paths(dry_run=dry_run)
    return {
        "ok": bool(local.get("ok")) and bool(remote.get("ok", True) or remote.get("skipped")),
        "local": local,
        "remote": remote,
        "include_github": include_github,
        "dry_run": dry_run,
    }
