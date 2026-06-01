# -*- coding: utf-8 -*-
"""V300.17 authority consistency helpers.

Low-risk helpers for modules that need one reboot-stable authority path.
This module does not import Streamlit at import time and does not touch 01/02.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"

MODULE_ALIASES = {
    "06_logs": "06_log_query",
    "06_system_logs": "06_log_query",
    "06_log_query": "06_log_query",
    "11_login_logs": "11_login_records",
    "11_login_records": "11_login_records",
    "10_permissions": "10_permissions",
    "13_system_settings": "13_system_settings",
}


def now_text() -> str:
    try:
        from services.timezone_service import now_text as _nt  # type: ignore
        return str(_nt())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def module_key(key: str) -> str:
    return MODULE_ALIASES.get(str(key), str(key))


def module_dir(key: str) -> Path:
    return AUTH_ROOT / module_key(key)


def records_jsonl_path(key: str) -> Path:
    return module_dir(key) / "records.jsonl"


def records_json_path(key: str) -> Path:
    return module_dir(key) / "records.json"


def settings_json_path(key: str) -> Path:
    return module_dir(key) / "settings.json"


def manifest_path(key: str) -> Path:
    return module_dir(key) / "authority_manifest.json"


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


def safe_text(v: Any) -> str:
    if v is None:
        return ""
    try:
        import pandas as pd  # type: ignore
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    if s.lower() in {"none", "nan", "null", "<na>"}:
        return ""
    return s


def stable_id(row: dict[str, Any], fields: Iterable[str] | None = None) -> str:
    if fields:
        text = "|".join(safe_text(row.get(f)) for f in fields)
    else:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 1:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def ensure_module_authority(key: str, *, mode: str = "records") -> dict[str, Any]:
    k = module_key(key)
    d = module_dir(k)
    d.mkdir(parents=True, exist_ok=True)
    if mode == "jsonl":
        p = records_jsonl_path(k)
        if not p.exists():
            p.write_text("", encoding="utf-8")
    else:
        p = records_json_path(k)
        if not p.exists():
            atomic_write_json(p, {
                "authority_schema": "SPT_MODULE_AUTHORITY_V1",
                "module_key": k,
                "kind": "records",
                "updated_at": now_text(),
                "tables": {},
                "settings": {},
                "table_counts": {},
            })
    m = manifest_path(k)
    if not m.exists():
        atomic_write_json(m, {
            "authority_schema": "SPT_MODULE_AUTHORITY_MANIFEST_V1",
            "module_key": k,
            "mode": mode,
            "created_at": now_text(),
            "updated_at": now_text(),
            "rule": "single authority path; legacy sources must not overwrite after reboot",
        })
    return {"ok": True, "module_key": k, "authority_dir": str(d), "mode": mode}


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_durable_jsonl_module(key: str) -> bool:
    # V300.23：V300.23.1: 06 LOG 保留即時同步；11 登入紀錄不得在登入熱路徑等待 GitHub：
    # 寫入後要盡量立即同步到 GitHub 上的同一路徑，避免 Streamlit Cloud
    # Reboot 後又讀回 GitHub 舊檔。
    return module_key(key) in {"06_log_query"}


def append_jsonl(key: str, row: dict[str, Any], *, identity_fields: Iterable[str] | None = None, github: bool = False, reason: str = "append_jsonl") -> dict[str, Any]:
    k = module_key(key)
    ensure_module_authority(k, mode="jsonl")
    clean = dict(row or {})
    clean.setdefault("authority_module_key", k)
    clean.setdefault("authority_written_at", now_text())
    clean.setdefault("authority_event_id", stable_id(clean, identity_fields))
    path = records_jsonl_path(k)
    line = json.dumps(clean, ensure_ascii=False, default=_json_default)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    # 06 是 append-only 正式紀錄。11 登入紀錄由背景/手動同步，避免卡住登入。
    # 可用 SPT_DISABLE_0611_IMMEDIATE_GITHUB_SYNC=1 暫時停用。
    durable_write = _is_durable_jsonl_module(k) and not _truthy_env("SPT_DISABLE_0611_IMMEDIATE_GITHUB_SYNC", False)
    should_upload = bool(github or durable_write)

    upload = None
    if should_upload:
        upload = upload_authority_file(k, "records.jsonl", reason=reason)

    atomic_write_json(manifest_path(k), {
        "authority_schema": "SPT_MODULE_AUTHORITY_MANIFEST_V1",
        "module_key": k,
        "mode": "jsonl",
        "updated_at": now_text(),
        "last_reason": reason,
        "records_file": "records.jsonl",
        "github_write_through": bool(should_upload),
        "github_last_ok": bool(upload.get("ok")) if isinstance(upload, dict) else None,
        "github_last_result": upload if isinstance(upload, dict) else None,
        "rule": "06/11 append-only authority writes to this path and syncs to GitHub immediately unless disabled",
    })
    return {"ok": True, "module_key": k, "path": str(path), "event_id": clean.get("authority_event_id"), "github_upload": upload, "github_write_through": should_upload}


def read_jsonl(key: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    k = module_key(key)
    path = records_jsonl_path(k)
    rows: list[dict[str, Any]] = []
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if limit and limit > 0:
            lines = lines[-int(limit):]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        return []
    return rows


def merge_by_event_id(rows: Iterable[dict[str, Any]], *, id_fields: Iterable[str] | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        key = safe_text(r.get("authority_event_id")) or stable_id(r, id_fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(r))
    return out


def upload_authority_file(key: str, filename: str, *, reason: str = "authority_upload") -> dict[str, Any]:
    k = module_key(key)
    local = module_dir(k) / filename
    if not local.exists():
        return {"ok": False, "error": "local_file_missing", "path": str(local)}
    remote = f"data/permanent_store/modules/{k}/{filename}"
    try:
        from services.github_cloud_storage_service import upload_file_to_github
        res = upload_file_to_github(local, remote, f"SPT V300.17 authority {k} {reason} {now_text()}")
        return dict(res or {"ok": True})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "path": str(local), "remote": remote}


def save_settings(key: str, settings: dict[str, Any], *, github: bool = True, reason: str = "save_settings") -> dict[str, Any]:
    k = module_key(key)
    ensure_module_authority(k, mode="records")
    payload = {
        "authority_schema": "SPT_MODULE_SETTINGS_V1",
        "module_key": k,
        "kind": "settings",
        "updated_at": now_text(),
        "reason": reason,
        "settings": dict(settings or {}),
    }
    path = settings_json_path(k)
    atomic_write_json(path, payload)
    upload = upload_authority_file(k, "settings.json", reason=reason) if github else None
    return {"ok": True, "module_key": k, "path": str(path), "github_upload": upload}


def audit_authority_consistency() -> dict[str, Any]:
    modules = ["06_log_query", "10_permissions", "11_login_records", "13_system_settings"]
    out: dict[str, Any] = {"version": "V300.17", "generated_at": now_text(), "modules": {}}
    for k in modules:
        d = module_dir(k)
        out["modules"][k] = {
            "authority_dir_exists": d.exists(),
            "records_json_exists": records_json_path(k).exists(),
            "records_jsonl_exists": records_jsonl_path(k).exists(),
            "settings_json_exists": settings_json_path(k).exists(),
            "manifest_exists": manifest_path(k).exists(),
        }
    return out

# =================== V300.23 DIRECT GITHUB DURABLE JSONL FOR 06/11 ===================
# Purpose:
# - 10. 權限管理已證實必須寫回 GitHub 上的同一份權威檔，Reboot 才不會讀舊資料。
# - 06. LOG查詢 / 11. 登入紀錄也比照此模式：append-only records.jsonl 先合併遠端，再寫本機，再上傳同一路徑。
# - This patch intentionally does not touch 01/02 logic, UI, permissions data, or system settings.
try:
    _v30023_prev_append_jsonl = append_jsonl  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_append_jsonl = None
try:
    _v30023_prev_read_jsonl = read_jsonl  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_read_jsonl = None

_V30023_DIRECT_JSONL_MODULES = {"06_log_query", "11_login_records"}


def _v30023_jsonl_remote_path(k: str) -> str:
    return f"data/permanent_store/modules/{module_key(k)}/records.jsonl"


def _v30023_parse_jsonl_text(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _v30023_rows_to_text(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, default=_json_default) + "\n" for r in rows if isinstance(r, dict))


def _v30023_download_remote_rows(k: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    remote = _v30023_jsonl_remote_path(k)
    try:
        from services.github_cloud_storage_service import download_text_from_github
        res = download_text_from_github(remote)
        if res.get("ok"):
            return _v30023_parse_jsonl_text(str(res.get("text") or "")), dict(res)
        return [], dict(res or {"ok": False, "message": "download_failed", "path": remote})
    except Exception as exc:
        return [], {"ok": False, "message": str(exc)[:300], "path": remote}


def _v30023_merge_rows(rows: Iterable[dict[str, Any]], *, identity_fields: Iterable[str] | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        eid = safe_text(row.get("authority_event_id")) or stable_id(row, identity_fields)
        row.setdefault("authority_event_id", eid)
        if eid in seen:
            continue
        seen.add(eid)
        out.append(row)
    return out


def _v30023_write_jsonl(k: str, rows: list[dict[str, Any]]) -> Path:
    path = records_jsonl_path(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_v30023_rows_to_text(rows), encoding="utf-8")
    # Syntax check: parse back before replace.
    _v30023_parse_jsonl_text(tmp.read_text(encoding="utf-8", errors="ignore"))
    os.replace(tmp, path)
    return path


def read_jsonl(key: str, *, limit: int | None = None) -> list[dict[str, Any]]:  # type: ignore[override]
    """Read module authority JSONL.

    V300.23:
    - For 06/11, if the local file is missing/empty after Streamlit reboot, pull the same GitHub authority path once.
    - This prevents the page from falling back to old/empty runtime files.
    """
    k = module_key(key)
    rows: list[dict[str, Any]] = []
    if callable(_v30023_prev_read_jsonl):
        try:
            rows = list(_v30023_prev_read_jsonl(k, limit=limit) or [])
        except TypeError:
            try:
                rows = list(_v30023_prev_read_jsonl(k) or [])
            except Exception:
                rows = []
        except Exception:
            rows = []
    if k in _V30023_DIRECT_JSONL_MODULES and not rows:
        remote_rows, remote_res = _v30023_download_remote_rows(k)
        if remote_rows:
            merged = _v30023_merge_rows(remote_rows)
            try:
                _v30023_write_jsonl(k, merged)
            except Exception:
                pass
            rows = merged
    if limit and int(limit) > 0:
        rows = rows[-int(limit):]
    return rows


def append_jsonl(key: str, row: dict[str, Any], *, identity_fields: Iterable[str] | None = None, github: bool = False, reason: str = "append_jsonl") -> dict[str, Any]:  # type: ignore[override]
    """Append one row to the module JSONL authority file.

    V300.23 direct mode for 06/11:
    - Merge remote GitHub file + local file + new row.
    - Write back the same local records.jsonl.
    - Upload that same file to GitHub when github=True.

    This avoids the previous failure mode where a reboot starts with an empty local file
    and a GitHub upload overwrites the remote history with only the newest row.
    """
    k = module_key(key)
    clean = dict(row or {})
    clean.setdefault("authority_module_key", k)
    clean.setdefault("authority_written_at", now_text())
    clean.setdefault("authority_event_id", stable_id(clean, identity_fields))

    if k not in _V30023_DIRECT_JSONL_MODULES:
        if callable(_v30023_prev_append_jsonl):
            return _v30023_prev_append_jsonl(k, clean, identity_fields=identity_fields, github=github, reason=reason)  # type: ignore[misc]

    ensure_module_authority(k, mode="jsonl")
    local_rows: list[dict[str, Any]] = []
    try:
        if callable(_v30023_prev_read_jsonl):
            local_rows = list(_v30023_prev_read_jsonl(k, limit=None) or [])  # type: ignore[misc]
        else:
            local_rows = _v30023_parse_jsonl_text(records_jsonl_path(k).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        local_rows = []

    remote_rows: list[dict[str, Any]] = []
    remote_download: dict[str, Any] | None = None
    if github and k in _V30023_DIRECT_JSONL_MODULES:
        remote_rows, remote_download = _v30023_download_remote_rows(k)

    merged = _v30023_merge_rows(remote_rows + local_rows + [clean], identity_fields=identity_fields)
    path = _v30023_write_jsonl(k, merged)

    atomic_write_json(manifest_path(k), {
        "authority_schema": "SPT_MODULE_AUTHORITY_MANIFEST_V1",
        "module_key": k,
        "mode": "jsonl",
        "updated_at": now_text(),
        "last_reason": reason,
        "records_file": "records.jsonl",
        "direct_github_durable_write": bool(github and k in _V30023_DIRECT_JSONL_MODULES),
        "remote_path": _v30023_jsonl_remote_path(k),
        "row_count": len(merged),
    })

    upload = None
    if github:
        upload = upload_authority_file(k, "records.jsonl", reason=reason)
    return {
        "ok": True,
        "module_key": k,
        "path": str(path),
        "event_id": clean.get("authority_event_id"),
        "row_count": len(merged),
        "github_upload": upload,
        "github_download_before_merge": remote_download,
        "direct_github_durable_write": bool(github and k in _V30023_DIRECT_JSONL_MODULES),
        "remote_path": _v30023_jsonl_remote_path(k),
    }


def audit_v30023_jsonl_direct_authority() -> dict[str, Any]:
    out: dict[str, Any] = {"version": "V300.23", "generated_at": now_text(), "modules": {}}
    for k in sorted(_V30023_DIRECT_JSONL_MODULES):
        p = records_jsonl_path(k)
        try:
            rows = read_jsonl(k, limit=None)
        except Exception:
            rows = []
        out["modules"][k] = {
            "records_jsonl": str(p),
            "exists": p.exists(),
            "row_count": len(rows),
            "remote_path": _v30023_jsonl_remote_path(k),
            "manifest_exists": manifest_path(k).exists(),
        }
    return out

# ================= END V300.23 DIRECT GITHUB DURABLE JSONL FOR 06/11 =================

# =================== V300.23 DIRECT GITHUB AUTHORITY WRITE-THROUGH FOR 06/11 ===================
# Scope: only the upload helper used by 06. LOG查詢 and 11. 登入紀錄.
# This uses the same direct GitHub write concept that fixed 10. 權限管理.
import base64 as _v30023_base64
import urllib.request as _v30023_urllib_request
import urllib.error as _v30023_urllib_error

try:
    _v30023_prev_upload_authority_file = upload_authority_file  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30023_prev_upload_authority_file = None


def _v30023_read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st  # type: ignore
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value)
    except Exception:
        pass
    try:
        return str(os.environ.get(name, default) or "")
    except Exception:
        return default


def _v30023_github_config() -> dict[str, str]:
    return {
        "token": _v30023_read_secret("GITHUB_TOKEN"),
        "repo": _v30023_read_secret("GITHUB_REPOSITORY", "cheng07021028/SPT-time-tracking-system"),
        "branch": _v30023_read_secret("GITHUB_BRANCH", "main"),
    }


def _v30023_remote_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except Exception:
        return path.name


def _v30023_github_api_request(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SPT-Time-Tracking-Authority-Writer"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = _v30023_urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with _v30023_urllib_request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8")
            return {"ok": True, "status": int(getattr(resp, "status", 200)), "data": json.loads(body) if body else {}}
    except _v30023_urllib_error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")[:600]
        except Exception:
            err_body = ""
        return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "error": err_body or str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:600]}


def _v30023_direct_github_upload(local: Path, *, reason: str = "authority_upload") -> dict[str, Any]:
    cfg = _v30023_github_config()
    token, repo, branch = cfg.get("token", ""), cfg.get("repo", ""), cfg.get("branch", "main")
    rel = _v30023_remote_path(local)
    if not local.exists():
        return {"ok": False, "error": "local_file_missing", "path": str(local), "remote": rel}
    if not token:
        return {"ok": False, "error": "missing_GITHUB_TOKEN", "path": str(local), "remote": rel}
    if not repo:
        return {"ok": False, "error": "missing_GITHUB_REPOSITORY", "path": str(local), "remote": rel}
    try:
        content = local.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"read_local_failed: {exc}", "path": str(local), "remote": rel}
    encoded = _v30023_base64.b64encode(content.encode("utf-8")).decode("ascii")
    api = f"https://api.github.com/repos/{repo}/contents/{rel}"
    get_res = _v30023_github_api_request(f"{api}?ref={branch}", token=token)
    sha = ""
    if get_res.get("ok") and isinstance(get_res.get("data"), dict):
        sha = str(get_res["data"].get("sha") or "")
    put_payload: dict[str, Any] = {"message": f"SPT 06/11 authority save: {reason}", "content": encoded, "branch": branch}
    if sha:
        put_payload["sha"] = sha
    put_res = _v30023_github_api_request(api, method="PUT", payload=put_payload, token=token)
    put_res["path"] = str(local)
    put_res["remote"] = rel
    put_res["branch"] = branch
    return put_res


def _v30023_write_upload_trace(k: str, filename: str, reason: str, result: dict[str, Any]) -> None:
    try:
        trace_path = module_dir(k) / "authority_github_write_trace.json"
        trace = read_json(trace_path)
        events = trace.get("events") if isinstance(trace, dict) else []
        if not isinstance(events, list):
            events = []
        events.append({"ts": now_text(), "module_key": module_key(k), "filename": filename, "reason": reason, "github": result})
        atomic_write_json(trace_path, {"updated_at": now_text(), "events": events[-100:]})
    except Exception:
        pass


def upload_authority_file(key: str, filename: str, *, reason: str = "authority_upload") -> dict[str, Any]:  # type: ignore[override]
    k = module_key(key)
    local = module_dir(k) / filename
    if k in {"06_log_query", "11_login_records"} and filename == "records.jsonl":
        try:
            ensure_module_authority(k, mode="jsonl")
        except Exception:
            pass
        result = _v30023_direct_github_upload(local, reason=reason)
        _v30023_write_upload_trace(k, filename, reason, result)
        return result
    if callable(_v30023_prev_upload_authority_file):
        try:
            return _v30023_prev_upload_authority_file(k, filename, reason=reason)  # type: ignore[misc]
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300], "path": str(local)}
    result = _v30023_direct_github_upload(local, reason=reason)
    _v30023_write_upload_trace(k, filename, reason, result)
    return result

# ================= END V300.23 DIRECT GITHUB AUTHORITY WRITE-THROUGH FOR 06/11 =================
