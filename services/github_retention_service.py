# -*- coding: utf-8 -*-
"""GitHub module backup audit and retention cleanup service.

V3.26
- Audit whether every module has local records/settings files and matching GitHub files.
- Upload missing/current module records/settings files to GitHub without touching local data.
- Manual GitHub cleanup by date range using timestamp parsed from file names.
- Scheduled GitHub cleanup by retention days/frequency.

Safety rules:
- Never deletes latest non-history files by default.
- Cleanup defaults to dry_run/preview.
- Only deletes files under allowed data paths.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from services.timezone_service import now_text, now_stamp
from services.github_cloud_storage_service import github_config
from services.module_persistence_service import MODULE_TABLE_MAP, latest_records_path, latest_settings_path, normalize_module_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "data" / "permanent_store" / "config" / "github_cleanup_settings.json"
STATE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_github_cleanup_state.json"
AUDIT_PATH = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_github_module_backup_audit.json"

REMOTE_MODULE_ROOT = "data/permanent_store/persistent_modules"
REMOTE_STATE_ROOT = "data/permanent_store/persistent_state"
REMOTE_ALLOWED_ROOTS = [
    "data/permanent_store/persistent_modules",
    "data/permanent_store/persistent_state/history",
    "data/permanent_store/persistent_state/audit_history",
    "data/_external_backup",
    "data/_persistent_backup",
]
PROTECTED_LATEST_NAMES = {
    "spt_permanent_state.json",
    "spt_module_settings.json",
    "spt_audit_log_state.json",
    "spt_system_settings.json",
    "spt_security_settings.json",
    "spt_auto_backup_settings.json",
}
DEFAULT_CLEANUP_SETTINGS = {
    "enabled": False,
    "frequency": "weekly",
    "keep_days": 90,
    "roots": ["data/permanent_store/persistent_state/history", "data/permanent_store/persistent_state/audit_history", "data/permanent_store/persistent_modules"],
    "delete_undated_files": False,
    "last_run_at": "",
    "last_result": {},
}


def _now() -> str:
    return now_text()


def _stamp() -> str:
    return now_stamp()


def _read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st  # type: ignore
        val = st.secrets.get(name, "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, default).strip()


def _github_api_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> tuple[int, Dict[str, Any]]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SPT-Time-Tracking-Retention",
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


def _repo_cfg() -> Dict[str, str]:
    cfg = github_config()
    return {"token": cfg.get("token", ""), "repo": cfg.get("repo", ""), "branch": cfg.get("branch", "main") or "main"}


def _contents_url(repo: str, path: str, branch: str) -> str:
    encoded_path = urllib.parse.quote(str(path).strip("/"), safe="/")
    return f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={urllib.parse.quote(branch)}"


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def load_cleanup_settings() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                out = {**DEFAULT_CLEANUP_SETTINGS, **payload}
                out["roots"] = [str(x) for x in out.get("roots", []) if str(x).strip()]
                return out
        except Exception:
            pass
    return dict(DEFAULT_CLEANUP_SETTINGS)


def save_cleanup_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    payload = {**DEFAULT_CLEANUP_SETTINGS, **(cfg or {})}
    payload["keep_days"] = int(payload.get("keep_days") or 90)
    payload["roots"] = [str(x).strip().strip("/") for x in payload.get("roots", []) if str(x).strip()]
    _write_json_atomic(CONFIG_PATH, payload)
    state_payload = {"saved_at": _now(), "settings": payload}
    _write_json_atomic(STATE_PATH, state_payload)
    return {"ok": True, "path": str(CONFIG_PATH), "state_path": str(STATE_PATH), "settings": payload}


def _remote_file_status(path: str) -> Dict[str, Any]:
    cfg = _repo_cfg()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "exists": False, "status": 0, "message": "缺少 GITHUB_TOKEN", "path": path}
    if not repo or "/" not in repo:
        return {"ok": False, "exists": False, "status": 0, "message": "GITHUB_REPOSITORY 格式錯誤", "path": path}
    status, body = _github_api_request("GET", _contents_url(repo, path, branch), token)
    if status == 200 and isinstance(body, dict):
        return {"ok": True, "exists": True, "status": status, "path": path, "sha": body.get("sha"), "size": body.get("size", 0), "name": body.get("name", "")}
    return {"ok": False, "exists": False, "status": status, "message": body.get("message", "not found"), "path": path}


def audit_module_github_links(check_remote: bool = True) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for raw_code, meta in MODULE_TABLE_MAP.items():
        code = normalize_module_code(raw_code)
        # avoid duplicate alias rows
        if any(r.get("module_code") == code for r in rows):
            continue
        rec_local = latest_records_path(code)
        set_local = latest_settings_path(code)
        rec_remote = f"{REMOTE_MODULE_ROOT}/{code}/{code}_records.json"
        set_remote = f"{REMOTE_MODULE_ROOT}/{code}/{code}_settings.json"
        rec_status = _remote_file_status(rec_remote) if check_remote else {"exists": "未檢查", "size": ""}
        set_status = _remote_file_status(set_remote) if check_remote else {"exists": "未檢查", "size": ""}
        rows.append({
            "module_code": code,
            "module_name": meta.get("name_zh", code),
            "tables": ", ".join(meta.get("tables", [])),
            "local_records_path": str(rec_local.relative_to(PROJECT_ROOT)) if rec_local.exists() else str(rec_local.relative_to(PROJECT_ROOT)),
            "local_records_exists": rec_local.exists(),
            "local_records_size": rec_local.stat().st_size if rec_local.exists() else 0,
            "github_records_path": rec_remote,
            "github_records_exists": bool(rec_status.get("exists")),
            "github_records_size": rec_status.get("size", 0),
            "local_settings_path": str(set_local.relative_to(PROJECT_ROOT)) if set_local.exists() else str(set_local.relative_to(PROJECT_ROOT)),
            "local_settings_exists": set_local.exists(),
            "local_settings_size": set_local.stat().st_size if set_local.exists() else 0,
            "github_settings_path": set_remote,
            "github_settings_exists": bool(set_status.get("exists")),
            "github_settings_size": set_status.get("size", 0),
        })
    ok_records = sum(1 for r in rows if r["local_records_exists"] and r["github_records_exists"])
    ok_settings = sum(1 for r in rows if r["local_settings_exists"] and r["github_settings_exists"])
    payload = {"ok": True, "checked_at": _now(), "check_remote": check_remote, "rows": rows, "summary": {"modules": len(rows), "records_linked": ok_records, "settings_linked": ok_settings}}
    try:
        _write_json_atomic(AUDIT_PATH, payload)
    except Exception:
        pass
    return payload


def _put_text(path_in_repo: str, text: str, message: str) -> Dict[str, Any]:
    cfg = _repo_cfg()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "path": path_in_repo, "message": "缺少 GITHUB_TOKEN"}
    current = _remote_file_status(path_in_repo)
    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path_in_repo.strip('/'), safe='/')}"
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if current.get("sha"):
        payload["sha"] = current["sha"]
    status, body = _github_api_request("PUT", url, token, payload)
    return {"ok": status in (200, 201), "status": status, "path": path_in_repo, "message": body.get("message", "uploaded"), "detail": body}


def upload_all_module_persistent_files_to_github() -> Dict[str, Any]:
    uploads: List[Dict[str, Any]] = []
    stamp = _stamp()
    seen: set[str] = set()
    for raw_code in MODULE_TABLE_MAP:
        code = normalize_module_code(raw_code)
        if code in seen:
            continue
        seen.add(code)
        for local_path, remote_path in [
            (latest_records_path(code), f"{REMOTE_MODULE_ROOT}/{code}/{code}_records.json"),
            (latest_settings_path(code), f"{REMOTE_MODULE_ROOT}/{code}/{code}_settings.json"),
        ]:
            if not local_path.exists():
                uploads.append({"ok": False, "path": remote_path, "local": str(local_path), "message": "本機檔案不存在，略過"})
                continue
            uploads.append(_put_text(remote_path, local_path.read_text(encoding="utf-8"), f"SPT module persistent sync {code} {stamp}"))
    return {"ok": all(bool(u.get("ok")) for u in uploads if "略過" not in str(u.get("message"))), "uploaded_at": _now(), "uploads": uploads}


def _list_remote_dir(path: str) -> List[Dict[str, Any]]:
    cfg = _repo_cfg()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return []
    status, body = _github_api_request("GET", _contents_url(repo, path, branch), token)
    if status != 200:
        return []
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and body.get("type") == "file":
        return [body]
    return []


def list_remote_files_recursive(roots: Iterable[str], max_files: int = 5000) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    stack = [str(r).strip().strip("/") for r in roots if str(r).strip()]
    while stack and len(files) < max_files:
        current = stack.pop(0)
        if not any(current == root or current.startswith(root + "/") for root in REMOTE_ALLOWED_ROOTS):
            continue
        for item in _list_remote_dir(current):
            item_type = item.get("type")
            path = str(item.get("path", ""))
            if item_type == "dir":
                stack.append(path)
            elif item_type == "file":
                files.append(item)
                if len(files) >= max_files:
                    break
    return files


def parse_date_from_path(path: str) -> Optional[date]:
    text = str(path or "")
    patterns = [
        r"(20\d{2})(\d{2})(\d{2})[_-]?(\d{2})?(\d{2})?(\d{2})?",
        r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d)
        except Exception:
            continue
    return None


def _is_protected_file(path: str, delete_undated_files: bool = False) -> bool:
    name = Path(path).name
    if name in PROTECTED_LATEST_NAMES:
        return True
    if not delete_undated_files and parse_date_from_path(path) is None:
        return True
    return False


def _delete_remote_file(path: str, sha: str, message: str) -> Dict[str, Any]:
    cfg = _repo_cfg()
    token, repo, branch = cfg["token"], cfg["repo"], cfg["branch"]
    if not token:
        return {"ok": False, "path": path, "message": "缺少 GITHUB_TOKEN"}
    url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path.strip('/'), safe='/')}"
    payload = {"message": message, "sha": sha, "branch": branch}
    status, body = _github_api_request("DELETE", url, token, payload)
    return {"ok": status == 200, "status": status, "path": path, "message": body.get("message", "deleted"), "detail": body}


def preview_github_cleanup(start_date: date, end_date: date, roots: Iterable[str], delete_undated_files: bool = False) -> Dict[str, Any]:
    all_files = list_remote_files_recursive(roots)
    candidates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for f in all_files:
        path = str(f.get("path", ""))
        file_date = parse_date_from_path(path)
        protected = _is_protected_file(path, delete_undated_files=delete_undated_files)
        if protected:
            skipped.append({"path": path, "reason": "protected_latest_or_undated", "date": str(file_date or "")})
            continue
        if file_date and start_date <= file_date <= end_date:
            candidates.append({"path": path, "name": f.get("name", ""), "sha": f.get("sha", ""), "size": f.get("size", 0), "date": str(file_date)})
        else:
            skipped.append({"path": path, "reason": "outside_date_range_or_no_date", "date": str(file_date or "")})
    return {"ok": True, "preview_at": _now(), "start_date": str(start_date), "end_date": str(end_date), "candidates": candidates, "skipped_count": len(skipped), "total_files_scanned": len(all_files)}


def cleanup_github_files_by_date(start_date: date, end_date: date, roots: Iterable[str], delete_undated_files: bool = False, dry_run: bool = True) -> Dict[str, Any]:
    preview = preview_github_cleanup(start_date, end_date, roots, delete_undated_files=delete_undated_files)
    if dry_run:
        return {**preview, "dry_run": True, "deleted": []}
    deleted: List[Dict[str, Any]] = []
    for item in preview.get("candidates", []):
        path = item.get("path", "")
        sha = item.get("sha", "")
        if not path or not sha:
            deleted.append({"ok": False, "path": path, "message": "缺少 sha，無法刪除"})
            continue
        deleted.append(_delete_remote_file(path, sha, f"SPT cleanup GitHub backup {path} {_stamp()}"))
    result = {**preview, "dry_run": False, "deleted": deleted, "deleted_count": sum(1 for d in deleted if d.get("ok"))}
    return result


def _next_due(last_run_at: str, frequency: str) -> bool:
    if not last_run_at:
        return True
    try:
        last = datetime.fromisoformat(str(last_run_at).replace("Z", "+00:00").split("+")[0])
    except Exception:
        try:
            last = datetime.strptime(str(last_run_at)[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return True
    delta = datetime.now() - last
    if frequency == "daily":
        return delta >= timedelta(days=1)
    if frequency == "monthly":
        return delta >= timedelta(days=28)
    return delta >= timedelta(days=7)


def run_due_github_cleanup_if_needed() -> Dict[str, Any]:
    cfg = load_cleanup_settings()
    if not cfg.get("enabled"):
        return {"ok": True, "skipped": True, "message": "GitHub 定期清理未啟用。"}
    if not _next_due(str(cfg.get("last_run_at", "")), str(cfg.get("frequency", "weekly"))):
        return {"ok": True, "skipped": True, "message": "尚未到達下一次 GitHub 定期清理時間。"}
    keep_days = int(cfg.get("keep_days") or 90)
    end = date.today() - timedelta(days=keep_days)
    start = date(2000, 1, 1)
    result = cleanup_github_files_by_date(start, end, cfg.get("roots", []), bool(cfg.get("delete_undated_files", False)), dry_run=False)
    cfg["last_run_at"] = _now()
    cfg["last_result"] = {"deleted_count": result.get("deleted_count", 0), "scanned": result.get("total_files_scanned", 0), "run_at": _now()}
    save_cleanup_settings(cfg)
    return result
