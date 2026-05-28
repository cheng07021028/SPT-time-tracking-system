# -*- coding: utf-8 -*-
"""GitHub cloud persistence service for SPT Time Tracking V1.30.

重點：
1. 永久檔一律使用 data/permanent_store/persistent_state/，避免誤存到 date/persistent_state/。
2. 使用 GitHub Contents API，不用 git push。
3. 支援 Streamlit Cloud 啟動時自動下載 latest JSON 並還原 SQLite。
4. 防止空資料覆蓋 GitHub 上有資料的 JSON。
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state"
HISTORY_DIR = STATE_DIR / "history"
LATEST_STATE = STATE_DIR / "spt_permanent_state.json"
LATEST_SETTINGS = STATE_DIR / "spt_module_settings.json"
LATEST_AUDIT = STATE_DIR / "spt_audit_log_state.json"

REMOTE_STATE_ROOT = "data/permanent_store/persistent_state"
REMOTE_HISTORY_ROOT = "data/permanent_store/persistent_state/history"
REMOTE_AUDIT_HISTORY_ROOT = "data/permanent_store/persistent_state/audit_history"
LEGACY_REMOTE_ROOTS = ["date/persistent_state", "data/persisten_state"]
TABLE_EXCLUDE = {"sqlite_sequence"}
BUSINESS_TABLES = ["work_orders", "employees", "time_records"]


def _now() -> str:
    return now_text()


def _stamp() -> str:
    return now_stamp()


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / ".gitkeep").touch(exist_ok=True)
    (HISTORY_DIR / ".gitkeep").touch(exist_ok=True)


def _read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st  # type: ignore
        val = st.secrets.get(name, "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, default).strip()


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


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return row is not None


def _count_table(conn: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])
    except Exception:
        return 0


def database_business_row_count() -> int:
    if not DB_PATH.exists():
        return 0
    conn = _connect()
    try:
        return sum(_count_table(conn, t) for t in BUSINESS_TABLES)
    finally:
        conn.close()


def list_tables() -> List[str]:
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [str(r[0]) for r in rows if str(r[0]) not in TABLE_EXCLUDE and not str(r[0]).startswith("sqlite_")]
    finally:
        conn.close()


def export_database_state(force: bool = False) -> Dict[str, Any]:
    ensure_dirs()
    state: Dict[str, Any] = {
        "schema_version": "v1.30",
        "export_time": _now(),
        "database_path": str(DB_PATH),
        "tables": {},
        "table_counts": {},
    }
    if not DB_PATH.exists():
        state["skipped"] = True
        state["warning"] = "SQLite database not found. Export skipped to protect cloud data."
        return state
    conn = _connect()
    try:
        business_count = sum(_count_table(conn, t) for t in BUSINESS_TABLES)
        state["business_row_count"] = business_count
        if business_count == 0 and not force:
            state["skipped"] = True
            state["warning"] = "Current DB has zero business rows. Export skipped to protect cloud data."
            return state
        for table in list_tables():
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            records = [dict(r) for r in rows]
            state["tables"][table] = records
            state["table_counts"][table] = len(records)
        return state
    finally:
        conn.close()


def export_module_settings_state() -> Dict[str, Any]:
    ensure_dirs()
    settings_tables = [
        "system_settings",
        "rest_periods",
        "process_options",
        "table_column_settings",
        "table_sort_settings",
        "auth_users",
        "auth_account_permissions",
        "auth_security_settings",
    ]
    payload: Dict[str, Any] = {"schema_version": "v1.30", "export_time": _now(), "tables": {}, "table_counts": {}}
    if not DB_PATH.exists():
        payload["warning"] = "SQLite database not found."
        return payload
    conn = _connect()
    try:
        for table in settings_tables:
            if _table_exists(conn, table):
                rows = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"').fetchall()]
                payload["tables"][table] = rows
                payload["table_counts"][table] = len(rows)
        return payload
    finally:
        conn.close()


def create_permanent_files(force: bool = False) -> Dict[str, Any]:
    ensure_dirs()
    stamp = _stamp()
    state = export_database_state(force=force)
    if state.get("skipped") and not force:
        return {"ok": False, "message": state.get("warning", "主資料為 0，為避免覆蓋 GitHub 永久檔，已停止建立 latest。"), "state": state}
    module_settings = export_module_settings_state()
    try:
        from services.persistence_service import export_audit_state
        audit_state = export_audit_state(force=True)
    except Exception as exc:
        audit_state = {"warning": str(exc)}
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
        "latest_audit": str(LATEST_AUDIT) if LATEST_AUDIT.exists() else "",
        "audit_table_counts": audit_state.get("table_counts", {}),
        "table_counts": state.get("table_counts", {}),
        "business_row_count": state.get("business_row_count", 0),
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
    except Exception as exc:
        return 0, {"message": str(exc)}


def _contents_url(repo: str, path: str, branch: str) -> str:
    encoded_path = urllib.parse.quote(path.strip("/"), safe="/")
    return f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={urllib.parse.quote(branch)}"


def _get_remote_file(repo: str, branch: str, token: str, path: str) -> Dict[str, Any]:
    status, body = _github_api_request("GET", _contents_url(repo, path, branch), token)
    return {"ok": status == 200 and isinstance(body, dict), "status": status, "path": path, "body": body}


def _get_remote_sha(repo: str, branch: str, token: str, path: str) -> Optional[str]:
    res = _get_remote_file(repo, branch, token, path)
    if res.get("ok"):
        return res.get("body", {}).get("sha")
    return None


def _decode_github_content(body: Dict[str, Any]) -> str:
    content = str(body.get("content", ""))
    if body.get("encoding") == "base64":
        return base64.b64decode(content.encode("ascii")).decode("utf-8")
    download_url = body.get("download_url")
    if download_url:
        with urllib.request.urlopen(download_url, timeout=30) as resp:
            return resp.read().decode("utf-8")
    return content


def _normalise_remote_path(path_in_repo: str) -> str:
    return path_in_repo.replace("date/persistent_state", REMOTE_STATE_ROOT).replace("data/persisten_state", REMOTE_STATE_ROOT)


def upload_text_to_github(path_in_repo: str, content: str, message: str) -> Dict[str, Any]:
    cfg = github_config()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "message": "缺少 GITHUB_TOKEN。請到 Streamlit Cloud → App settings → Secrets 設定。"}
    if not repo or "/" not in repo:
        return {"ok": False, "message": "GITHUB_REPOSITORY 格式錯誤，應為 owner/repo。"}
    path_in_repo = _normalise_remote_path(path_in_repo)
    sha = _get_remote_sha(repo, branch, token, path_in_repo)
    encoded_path = urllib.parse.quote(path_in_repo.strip("/"), safe="/")
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
    return {"ok": False, "message": body.get("message", str(body)), "status": status, "detail": body, "path": path_in_repo}


def upload_file_to_github(local_path: Path, path_in_repo: str, message: Optional[str] = None) -> Dict[str, Any]:
    if not local_path.exists():
        return {"ok": False, "message": f"找不到本機檔案：{local_path}"}
    content = local_path.read_text(encoding="utf-8")
    return upload_text_to_github(path_in_repo, content, message or f"Update {path_in_repo}")


def create_and_upload_permanent_files(force: bool = False) -> Dict[str, Any]:
    created = create_permanent_files(force=force)
    if not created.get("ok"):
        return {**created, "uploads": [], "remote_root": REMOTE_STATE_ROOT}
    stamp = _stamp()
    uploads = []
    files = [
        (LATEST_STATE, f"{REMOTE_STATE_ROOT}/spt_permanent_state.json"),
        (LATEST_SETTINGS, f"{REMOTE_STATE_ROOT}/spt_module_settings.json"),
        (Path(created["history_state"]), f"{REMOTE_HISTORY_ROOT}/spt_permanent_state_{stamp}.json"),
        (Path(created["history_settings"]), f"{REMOTE_HISTORY_ROOT}/spt_module_settings_{stamp}.json"),
    ]
    if LATEST_AUDIT.exists():
        files.append((LATEST_AUDIT, f"{REMOTE_STATE_ROOT}/spt_audit_log_state.json"))
        files.append((LATEST_AUDIT, f"{REMOTE_AUDIT_HISTORY_ROOT}/spt_audit_log_state_{stamp}.json"))
    ok_all = True
    for local, remote in files:
        res = upload_file_to_github(local, remote, f"Backup permanent state {stamp}")
        uploads.append(res)
        ok_all = ok_all and bool(res.get("ok"))
    return {**created, "ok": ok_all, "uploads": uploads, "remote_root": REMOTE_STATE_ROOT}


def upload_existing_permanent_files(archive: bool = True) -> Dict[str, Any]:
    ensure_dirs()
    stamp = _stamp()
    uploads = []
    if not LATEST_STATE.exists() and not LATEST_SETTINGS.exists():
        return {"ok": False, "message": "找不到永久保存檔，請先建立永久檔案。"}
    if LATEST_STATE.exists():
        uploads.append(upload_file_to_github(LATEST_STATE, f"{REMOTE_STATE_ROOT}/spt_permanent_state.json", f"Upload permanent state {stamp}"))
        if archive:
            uploads.append(upload_file_to_github(LATEST_STATE, f"{REMOTE_HISTORY_ROOT}/spt_permanent_state_{stamp}.json", f"Archive permanent state {stamp}"))
    if LATEST_SETTINGS.exists():
        uploads.append(upload_file_to_github(LATEST_SETTINGS, f"{REMOTE_STATE_ROOT}/spt_module_settings.json", f"Upload module settings {stamp}"))
        if archive:
            uploads.append(upload_file_to_github(LATEST_SETTINGS, f"{REMOTE_HISTORY_ROOT}/spt_module_settings_{stamp}.json", f"Archive module settings {stamp}"))
    if LATEST_AUDIT.exists():
        uploads.append(upload_file_to_github(LATEST_AUDIT, f"{REMOTE_STATE_ROOT}/spt_audit_log_state.json", f"Upload audit logs {stamp}"))
        if archive:
            uploads.append(upload_file_to_github(LATEST_AUDIT, f"{REMOTE_AUDIT_HISTORY_ROOT}/spt_audit_log_state_{stamp}.json", f"Archive audit logs {stamp}"))
    return {"ok": all(bool(x.get("ok")) for x in uploads), "uploads": uploads, "remote_root": REMOTE_STATE_ROOT}


def download_text_from_github(path_in_repo: str) -> Dict[str, Any]:
    cfg = github_config()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "message": "缺少 GITHUB_TOKEN", "path": path_in_repo}
    res = _get_remote_file(repo, branch, token, path_in_repo)
    if not res.get("ok"):
        body = res.get("body", {})
        return {"ok": False, "message": body.get("message", "找不到 GitHub 雲端檔案"), "status": res.get("status"), "path": path_in_repo, "detail": body}
    try:
        return {"ok": True, "text": _decode_github_content(res["body"]), "path": path_in_repo, "sha": res["body"].get("sha")}
    except Exception as exc:
        return {"ok": False, "message": str(exc), "path": path_in_repo}


def download_latest_permanent_files_from_github(allow_legacy: bool = True) -> Dict[str, Any]:
    ensure_dirs()
    roots = [REMOTE_STATE_ROOT]
    if allow_legacy:
        roots.extend(LEGACY_REMOTE_ROOTS)
    downloaded: List[Dict[str, Any]] = []
    for root in roots:
        found_any = False
        state_res = download_text_from_github(f"{root}/spt_permanent_state.json")
        settings_res = download_text_from_github(f"{root}/spt_module_settings.json")
        audit_res = download_text_from_github(f"{root}/spt_audit_log_state.json")
        if state_res.get("ok"):
            LATEST_STATE.write_text(str(state_res["text"]), encoding="utf-8")
            downloaded.append({"local": str(LATEST_STATE), "remote": state_res["path"], "ok": True})
            found_any = True
        if settings_res.get("ok"):
            LATEST_SETTINGS.write_text(str(settings_res["text"]), encoding="utf-8")
            downloaded.append({"local": str(LATEST_SETTINGS), "remote": settings_res["path"], "ok": True})
            found_any = True
        if audit_res.get("ok"):
            LATEST_AUDIT.write_text(str(audit_res["text"]), encoding="utf-8")
            downloaded.append({"local": str(LATEST_AUDIT), "remote": audit_res["path"], "ok": True})
            found_any = True
        if found_any:
            return {"ok": True, "message": f"已從 GitHub 雲端下載永久檔：{root}", "source_root": root, "downloaded": downloaded}
    return {"ok": False, "message": "GitHub 雲端找不到 data/permanent_store/persistent_state 或舊路徑 date/persistent_state 的永久檔。", "downloaded": downloaded}


def restore_from_github_if_database_empty(force: bool = False) -> Dict[str, Any]:
    """Cloud startup helper: if DB is empty/missing, pull latest JSON from GitHub and restore."""
    try:
        from services.persistence_service import database_business_row_count, restore_latest_available_state
        if DB_PATH.exists() and not force:
            try:
                conn = sqlite3.connect(DB_PATH)
                current_count = database_business_row_count(conn)  # type: ignore[arg-type]
                conn.close()
                if current_count > 0:
                    return {"ok": True, "skipped": True, "message": f"SQLite 已有主資料 {current_count} 筆，不需 GitHub 還原。"}
            except Exception:
                pass
        dl = download_latest_permanent_files_from_github(allow_legacy=True)
        if not dl.get("ok"):
            return dl
        restored = restore_latest_available_state(mode="replace")
        audit_restored = {}
        try:
            from services.persistence_service import restore_audit_state
            audit_restored = restore_audit_state(mode="append")
        except Exception as exc:
            audit_restored = {"ok": False, "message": str(exc)}
        return {"ok": bool(restored.get("ok") or audit_restored.get("ok")), "download": dl, "restore": restored, "audit_restore": audit_restored, "message": "已嘗試從 GitHub latest JSON 還原 SQLite 與登入紀錄。"}
    except Exception as exc:
        return {"ok": False, "message": f"GitHub 自動還原失敗：{exc}"}


def github_cloud_file_status() -> Dict[str, Any]:
    cfg = github_config()
    rows: List[Dict[str, Any]] = []
    for path in [
        f"{REMOTE_STATE_ROOT}/spt_permanent_state.json",
        f"{REMOTE_STATE_ROOT}/spt_module_settings.json",
        f"{REMOTE_STATE_ROOT}/spt_audit_log_state.json",
        *[f"{root}/spt_permanent_state.json" for root in LEGACY_REMOTE_ROOTS],
        *[f"{root}/spt_module_settings.json" for root in LEGACY_REMOTE_ROOTS],
    ]:
        res = download_text_from_github(path)
        item = {"path": path, "exists": bool(res.get("ok")), "message": res.get("message", "OK" if res.get("ok") else "")}
        if res.get("ok") and "spt_permanent_state" in path:
            try:
                payload = json.loads(str(res.get("text", "{}")))
                item["business_row_count"] = payload.get("business_row_count") or sum(len(payload.get("tables", {}).get(t, [])) for t in BUSINESS_TABLES)
                item["table_counts"] = payload.get("table_counts", {})
            except Exception:
                pass
        rows.append(item)
    return {"repo": cfg.get("repo"), "branch": cfg.get("branch"), "token_set": bool(cfg.get("token")), "files": rows}


def migrate_legacy_date_path_to_data_path() -> Dict[str, Any]:
    stamp = _stamp()
    results: List[Dict[str, Any]] = []
    migrated = False
    for legacy_root in LEGACY_REMOTE_ROOTS:
        for filename in ["spt_permanent_state.json", "spt_module_settings.json"]:
            old_path = f"{legacy_root}/{filename}"
            dl = download_text_from_github(old_path)
            if dl.get("ok"):
                new_path = f"{REMOTE_STATE_ROOT}/{filename}"
                up = upload_text_to_github(new_path, str(dl["text"]), f"Migrate SPT persistent state path {stamp}")
                results.append({"from": old_path, "to": new_path, "upload": up})
                migrated = migrated or bool(up.get("ok"))
            else:
                results.append({"from": old_path, "to": f"{REMOTE_STATE_ROOT}/{filename}", "skipped": True, "reason": dl.get("message")})
    return {"ok": migrated, "message": "已嘗試將舊路徑 date/persistent_state 搬到 data/permanent_store/persistent_state", "results": results}




def upload_audit_logs_to_github(archive: bool = True) -> Dict[str, Any]:
    """Create/upload only login/system audit log permanent JSON."""
    ensure_dirs()
    stamp = _stamp()
    try:
        from services.persistence_service import export_audit_state
        audit = export_audit_state(force=True)
    except Exception as exc:
        return {"ok": False, "message": f"建立登入紀錄永久檔失敗：{exc}"}
    uploads: List[Dict[str, Any]] = []
    if LATEST_AUDIT.exists():
        uploads.append(upload_file_to_github(LATEST_AUDIT, f"{REMOTE_STATE_ROOT}/spt_audit_log_state.json", f"Upload audit logs {stamp}"))
        if archive:
            uploads.append(upload_file_to_github(LATEST_AUDIT, f"{REMOTE_AUDIT_HISTORY_ROOT}/spt_audit_log_state_{stamp}.json", f"Archive audit logs {stamp}"))
    return {"ok": all(bool(x.get("ok")) for x in uploads), "audit": audit, "uploads": uploads, "remote_root": REMOTE_STATE_ROOT}

# Backward-compatible function names used by older page versions.
def backup_all_to_files() -> Dict[str, Any]:
    return create_permanent_files()


def backup_all_and_push_to_github() -> Dict[str, Any]:
    return create_and_upload_permanent_files()


def push_existing_backups_to_github() -> Dict[str, Any]:
    return upload_existing_permanent_files()
