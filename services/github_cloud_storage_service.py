# -*- coding: utf-8 -*-
"""GitHub cloud persistence service for SPT Time Tracking.

This module stores permanent JSON snapshots in the GitHub repository by using
GitHub Contents API. It does NOT use `git push`, so Streamlit Cloud does not
need SSH keys or local git identity.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
HISTORY_DIR = STATE_DIR / "history"
LATEST_STATE = STATE_DIR / "spt_permanent_state.json"
LATEST_SETTINGS = STATE_DIR / "spt_module_settings.json"

TABLE_EXCLUDE = {"sqlite_sequence"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _read_secret(name: str, default: str = "") -> str:
    # Works both locally and on Streamlit Cloud.
    try:
        import streamlit as st  # type: ignore
        val = st.secrets.get(name, "")
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(name, default)


def github_config() -> Dict[str, str]:
    return {
        "token": _read_secret("GITHUB_TOKEN"),
        "repo": _read_secret("GITHUB_REPOSITORY", "cheng07021028/SPT-time-tracking-system"),
        "branch": _read_secret("GITHUB_BRANCH", "main"),
    }


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_exists() -> bool:
    return DB_PATH.exists()


def list_tables() -> List[str]:
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [str(r[0]) for r in rows if str(r[0]) not in TABLE_EXCLUDE]
    finally:
        conn.close()


def export_database_state() -> Dict[str, Any]:
    """Export every SQLite table to a JSON-serializable dictionary."""
    ensure_dirs()
    state: Dict[str, Any] = {
        "schema_version": "v1.26",
        "export_time": _now(),
        "database_path": str(DB_PATH),
        "tables": {},
        "table_counts": {},
    }

    if not DB_PATH.exists():
        state["warning"] = "SQLite database not found. Only metadata exported."
        return state

    conn = _connect()
    try:
        for table in list_tables():
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                data = [dict(r) for r in rows]
                state["tables"][table] = data
                state["table_counts"][table] = len(data)
            except Exception as exc:
                state["tables"][table] = []
                state["table_counts"][table] = 0
                state.setdefault("errors", {})[table] = str(exc)
    finally:
        conn.close()
    return state


def export_module_settings() -> Dict[str, Any]:
    """Export common UI settings if present."""
    ensure_dirs()
    settings: Dict[str, Any] = {
        "schema_version": "v1.26",
        "export_time": _now(),
        "settings": {},
    }
    if not DB_PATH.exists():
        return settings

    conn = _connect()
    try:
        tables = set(list_tables())
        for table in ["system_settings", "ui_settings", "column_width_settings", "module_settings"]:
            if table in tables:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                settings["settings"][table] = [dict(r) for r in rows]
    finally:
        conn.close()
    return settings


def create_permanent_files() -> Dict[str, Any]:
    """Create latest + timestamp history permanent JSON files locally."""
    ensure_dirs()
    stamp = _stamp()
    state = export_database_state()
    module_settings = export_module_settings()

    state_history = HISTORY_DIR / f"spt_permanent_state_{stamp}.json"
    settings_history = HISTORY_DIR / f"spt_module_settings_{stamp}.json"

    LATEST_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_SETTINGS.write_text(json.dumps(module_settings, ensure_ascii=False, indent=2), encoding="utf-8")
    state_history.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    settings_history.write_text(json.dumps(module_settings, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "message": "永久檔案已建立",
        "latest_state": str(LATEST_STATE),
        "latest_settings": str(LATEST_SETTINGS),
        "history_state": str(state_history),
        "history_settings": str(settings_history),
        "table_counts": state.get("table_counts", {}),
        "warning": state.get("warning", ""),
    }


def _github_api_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SPT-Time-Tracking-Persistence",
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
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"message": body}
        return exc.code, parsed


def _get_remote_sha(repo: str, branch: str, token: str, path: str) -> Optional[str]:
    encoded_path = path.replace(" ", "%20")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={branch}"
    status, body = _github_api_request("GET", url, token)
    if status == 200:
        return body.get("sha")
    return None


def upload_text_to_github(path_in_repo: str, content: str, message: str) -> Dict[str, Any]:
    cfg = github_config()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {
            "ok": False,
            "message": "缺少 GITHUB_TOKEN。請到 Streamlit Cloud → App settings → Secrets 設定。",
        }
    if not repo or "/" not in repo:
        return {"ok": False, "message": "GITHUB_REPOSITORY 格式錯誤，應為 owner/repo。"}

    sha = _get_remote_sha(repo, branch, token, path_in_repo)
    encoded_path = path_in_repo.replace(" ", "%20")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    status, body = _github_api_request("PUT", url, token, payload)
    if status in (200, 201):
        return {"ok": True, "message": f"已上傳：{path_in_repo}", "path": path_in_repo, "status": status}
    return {"ok": False, "message": body.get("message", str(body)), "status": status, "detail": body}


def upload_file_to_github(local_path: Path, path_in_repo: str, message: Optional[str] = None) -> Dict[str, Any]:
    if not local_path.exists():
        return {"ok": False, "message": f"找不到本機檔案：{local_path}"}
    content = local_path.read_text(encoding="utf-8")
    return upload_text_to_github(path_in_repo, content, message or f"Update {path_in_repo}")


def create_and_upload_permanent_files() -> Dict[str, Any]:
    """Create local permanent files and upload latest + timestamped history to GitHub."""
    created = create_permanent_files()
    stamp = _stamp()
    uploads = []
    files = [
        (LATEST_STATE, "data/persistent_state/spt_permanent_state.json"),
        (LATEST_SETTINGS, "data/persistent_state/spt_module_settings.json"),
        (Path(created["history_state"]), f"data/persistent_state/history/spt_permanent_state_{stamp}.json"),
        (Path(created["history_settings"]), f"data/persistent_state/history/spt_module_settings_{stamp}.json"),
    ]
    ok_all = True
    for local, remote in files:
        res = upload_file_to_github(local, remote, f"Backup permanent state {stamp}")
        uploads.append(res)
        ok_all = ok_all and bool(res.get("ok"))
    return {**created, "ok": ok_all, "uploads": uploads}


def upload_existing_permanent_files() -> Dict[str, Any]:
    """Upload existing latest permanent files to GitHub without using git push."""
    ensure_dirs()
    stamp = _stamp()
    uploads = []
    if not LATEST_STATE.exists() and not LATEST_SETTINGS.exists():
        return {"ok": False, "message": "找不到永久保存檔，請先建立永久檔案。"}
    if LATEST_STATE.exists():
        uploads.append(upload_file_to_github(LATEST_STATE, "data/persistent_state/spt_permanent_state.json", f"Upload permanent state {stamp}"))
        uploads.append(upload_file_to_github(LATEST_STATE, f"data/persistent_state/history/spt_permanent_state_{stamp}.json", f"Archive permanent state {stamp}"))
    if LATEST_SETTINGS.exists():
        uploads.append(upload_file_to_github(LATEST_SETTINGS, "data/persistent_state/spt_module_settings.json", f"Upload module settings {stamp}"))
        uploads.append(upload_file_to_github(LATEST_SETTINGS, f"data/persistent_state/history/spt_module_settings_{stamp}.json", f"Archive module settings {stamp}"))
    return {"ok": all(bool(x.get("ok")) for x in uploads), "uploads": uploads}


# Backward-compatible function names used by older page versions.
def backup_all_to_files() -> Dict[str, Any]:
    return create_permanent_files()


def backup_all_and_push_to_github() -> Dict[str, Any]:
    # Critical: this uses GitHub API, not git push.
    return create_and_upload_permanent_files()


def push_existing_backups_to_github() -> Dict[str, Any]:
    # Critical: this uses GitHub API, not git push.
    return upload_existing_permanent_files()
