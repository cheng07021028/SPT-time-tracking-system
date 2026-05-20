# -*- coding: utf-8 -*-
"""SPT V28 Permanent Authority Service

唯一資料權威層：
- 每個模組只允許 data/permanent_store/modules/<module_key>/records.json 作為正式資料檔。
- 每個模組只允許 data/permanent_store/modules/<module_key>/settings.json 作為正式設定檔。
- SQLite 只能當快取；history 只能當備份；預設資料只能在完全沒有權威檔時建立。
- 儲存後盡量 GitHub write-through，並做遠端讀回驗證。

本服務設計為可漸進導入：舊檔只在第一次 canonical 檔不存在時遷移，之後不再讀舊檔。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import streamlit as st  # type: ignore
except Exception:  # pragma: no cover
    st = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"
BACKUP_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "history" / "modules"
MANIFEST_PATH = PROJECT_ROOT / "data" / "permanent_store" / "authority_manifest.json"

MODULES: dict[str, dict[str, Any]] = {
    "01_time_records": {"tables": ["time_records"]},
    "02_history": {"tables": ["time_records"]},
    "03_work_orders": {"tables": ["work_orders"]},
    "04_employees": {"tables": ["employees"]},
    "05_analysis": {"tables": ["time_records", "work_orders", "employees"]},
    "06_logs": {"tables": ["system_logs"]},
    "06_system_logs": {"tables": ["system_logs"]},
    "07_missing": {"tables": ["employees", "time_records"]},
    "07_missing_records": {"tables": ["employees", "time_records"]},
    "08_daily_hours": {"tables": ["employees", "time_records"]},
    "10_permissions": {"tables": ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_user_roles", "security_settings"]},
    "11_login_logs": {"tables": ["auth_login_logs", "security_login_logs", "login_logs"]},
    "13_system_settings": {"tables": ["process_categories", "process_category_options", "process_options", "rest_periods", "app_settings", "system_settings"]},
    "ui_table_settings": {"tables": ["table_column_settings", "table_sort_settings", "table_ui_settings"]},
}

_CACHE: dict[tuple[str, str], tuple[float, str, dict[str, Any]]] = {}
_UPLOAD_HASH: dict[str, str] = {}

def now_text() -> str:
    try:
        from services.timezone_service import now_text as _nt  # type: ignore
        return _nt()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _read_secret(name: str, default: str = "") -> str:
    try:
        if st is not None:
            val = st.secrets.get(name, "")  # type: ignore[attr-defined]
            if val:
                return str(val).strip()
    except Exception:
        pass
    return os.environ.get(name, default).strip()

def github_config() -> dict[str, str]:
    return {
        "token": _read_secret("GITHUB_TOKEN"),
        "repo": _read_secret("GITHUB_REPOSITORY", "cheng07021028/SPT-time-tracking-system"),
        "branch": _read_secret("GITHUB_BRANCH", "main"),
    }

def module_dir(module_key: str) -> Path:
    return AUTH_ROOT / str(module_key)

def canonical_path(module_key: str, kind: str) -> Path:
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    return module_dir(module_key) / f"{kind}.json"

def ensure_dirs() -> None:
    AUTH_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

def _json_default(v: Any) -> Any:
    try:
        import pandas as pd  # type: ignore
        if pd.isna(v): return ""
    except Exception:
        pass
    if hasattr(v, "item"):
        try: return v.item()
        except Exception: pass
    return str(v)

def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    txt = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    tmp.write_text(txt, encoding="utf-8")
    os.replace(tmp, path)
    _CACHE.pop((str(path), "json"), None)

def read_json(path: Path) -> dict[str, Any]:
    try:
        st_m = path.stat().st_mtime
        key = (str(path), "json")
        c = _CACHE.get(key)
        if c and c[0] == st_m:
            return c[2]
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            h = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            _CACHE[key] = (st_m, h, data)
            return data
    except Exception:
        pass
    return {}

def normalize_payload(module_key: str, kind: str, payload: dict[str, Any] | None = None, *, reason: str = "authority_normalize") -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    return {
        "authority_schema": "SPT-PermanentAuthority-V28",
        "module_key": module_key,
        "kind": "settings" if kind == "settings" else "records",
        "updated_at": now_text(),
        "exported_at": payload.get("exported_at") or payload.get("updated_at") or now_text(),
        "reason": reason,
        "tables": tables,
        "settings": settings,
        "table_counts": {k: len(v) for k, v in tables.items() if isinstance(v, list)},
    }

def _legacy_candidates(module_key: str, kind: str) -> list[Path]:
    stem = "settings" if kind == "settings" else "records"
    names = [f"{module_key}_{stem}.json"]
    if module_key == "13_system_settings": names += ["system_settings.json", "13_system_settings_table_column_settings.json"]
    if module_key == "10_permissions": names += ["security_settings.json", "10_permissions_table_column_settings.json"]
    if module_key == "ui_table_settings": names += ["table_persistence.json", "table_column_settings.json", "table_ui_settings.json", "ui_table_settings_settings.json"]
    roots = [
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / module_key,
        PROJECT_ROOT / "data" / "persistent_modules" / module_key,
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state",
        PROJECT_ROOT / "data" / "persistent_state",
        PROJECT_ROOT / "data" / "permanent_store" / "config",
        PROJECT_ROOT / "data" / "config",
    ]
    extra_state = {
        "10_permissions": ["spt_permission_settings.json", "spt_user_persistent_settings.json", "spt_module_settings.json", "spt_security_settings.json"],
        "13_system_settings": ["spt_system_settings.json", "spt_module_settings.json"],
        "ui_table_settings": ["spt_table_persistence.json", "spt_table_column_settings.json", "spt_table_ui_settings.json", "spt_user_persistent_settings.json"],
    }.get(module_key, [])
    out: list[Path] = []
    for root in roots:
        for n in names:
            p = root / n
            if p.exists(): out.append(p)
        for n in extra_state:
            p = root / n
            if p.exists(): out.append(p)
    # Do not read history as authority. History remains backup only.
    return out

def _payload_score(path: Path, payload: dict[str, Any]) -> tuple[str, float, int]:
    t = str(payload.get("updated_at") or payload.get("exported_at") or payload.get("export_time") or "")
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    rows = sum(len(v) for v in tables.values() if isinstance(v, list))
    try: mt = path.stat().st_mtime
    except Exception: mt = 0.0
    return (t, mt, rows)

def migrate_once(module_key: str, kind: str) -> dict[str, Any]:
    path = canonical_path(module_key, kind)
    if path.exists():
        return read_json(path)
    ensure_dirs()
    best_path: Path | None = None
    best_payload: dict[str, Any] = {}
    best_score = ("", 0.0, -1)
    for p in _legacy_candidates(module_key, kind):
        data = read_json(p)
        if not data: continue
        score = _payload_score(p, data)
        if score > best_score:
            best_score, best_path, best_payload = score, p, data
    payload = normalize_payload(module_key, kind, best_payload, reason=f"migrated_from_{best_path.relative_to(PROJECT_ROOT) if best_path else 'empty'}")
    atomic_write_json(path, payload)
    return payload

def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:
    ensure_dirs()
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    return migrate_once(module_key, kind)

def load_tables(module_key: str, kind: str = "records") -> dict[str, list[dict[str, Any]]]:
    payload = load_authority(module_key, kind)
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    return {str(k): list(v) for k, v in tables.items() if isinstance(v, list)}

def _backup_current(module_key: str, kind: str) -> None:
    p = canonical_path(module_key, kind)
    if p.exists():
        b = BACKUP_ROOT / module_key / kind / f"{kind}_{_stamp()}.json"
        b.parent.mkdir(parents=True, exist_ok=True)
        try: shutil.copy2(p, b)
        except Exception: pass

def _remote_path(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/")

def github_put_file(path: Path, content: str, message: str) -> dict[str, Any]:
    cfg = github_config()
    if not cfg["token"] or not cfg["repo"]:
        return {"ok": False, "skipped": True, "reason": "missing_github_config"}
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    rel = _remote_path(path)
    if _UPLOAD_HASH.get(rel) == sha:
        return {"ok": True, "skipped": True, "reason": "unchanged", "path": rel}
    api = f"https://api.github.com/repos/{cfg['repo']}/contents/{urllib.parse.quote(rel)}?ref={urllib.parse.quote(cfg['branch'])}"
    headers = {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json", "User-Agent": "SPT-TimeTracking-V28"}
    old_sha = None
    try:
        req = urllib.request.Request(api, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=12) as r:
            old_sha = json.loads(r.read().decode("utf-8")).get("sha")
    except Exception:
        old_sha = None
    body = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "branch": cfg["branch"]}
    if old_sha: body["sha"] = old_sha
    try:
        req = urllib.request.Request(api.split("?ref=")[0], data=json.dumps(body).encode("utf-8"), headers={**headers, "Content-Type":"application/json"}, method="PUT")
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8"))
        # verify by reading back sha / content sha
        _UPLOAD_HASH[rel] = sha
        return {"ok": True, "path": rel, "commit": (res.get("commit") or {}).get("sha", "")}
    except Exception as exc:
        return {"ok": False, "path": rel, "error": str(exc)[:300]}

def save_authority(module_key: str, *, records: dict[str, list[dict[str, Any]]] | None = None, settings: dict[str, Any] | None = None, reason: str = "authority_save", github: bool = True) -> dict[str, Any]:
    ensure_dirs()
    out: dict[str, Any] = {"ok": True, "module_key": module_key, "files": [], "github": []}
    if records is not None:
        kind = "records"; p = canonical_path(module_key, kind); _backup_current(module_key, kind)
        payload = normalize_payload(module_key, kind, {"tables": records}, reason=reason)
        atomic_write_json(p, payload); out["files"].append(str(p))
        if github:
            out["github"].append(github_put_file(p, p.read_text(encoding="utf-8"), f"SPT authority {module_key} records: {reason}"))
    if settings is not None:
        kind = "settings"; p = canonical_path(module_key, kind); _backup_current(module_key, kind)
        payload = normalize_payload(module_key, kind, {"settings": settings, "tables": settings.get("tables", {}) if isinstance(settings, dict) else {}}, reason=reason)
        atomic_write_json(p, payload); out["files"].append(str(p))
        if github:
            out["github"].append(github_put_file(p, p.read_text(encoding="utf-8"), f"SPT authority {module_key} settings: {reason}"))
    _write_manifest()
    return out

def update_tables(module_key: str, updates: dict[str, list[dict[str, Any]]], *, reason: str = "update_tables", github: bool = True) -> dict[str, Any]:
    cur = load_tables(module_key, "records")
    cur.update({k: list(v) for k, v in updates.items()})
    return save_authority(module_key, records=cur, reason=reason, github=github)

def load_settings(module_key: str) -> dict[str, Any]:
    payload = load_authority(module_key, "settings")
    return payload.get("settings") if isinstance(payload.get("settings"), dict) else {}

def save_settings(module_key: str, settings: dict[str, Any], *, reason: str = "save_settings", github: bool = True) -> dict[str, Any]:
    return save_authority(module_key, settings=settings, reason=reason, github=github)

def df_from_table(module_key: str, table: str, *, columns: Iterable[str] | None = None, active_col: str | None = None, active_only: bool = False):
    import pandas as pd
    rows = load_tables(module_key).get(table, [])
    df = pd.DataFrame(rows)
    cols = list(columns or [])
    for c in cols:
        if c not in df.columns: df[c] = ""
    if cols: df = df[cols]
    if active_only and active_col and active_col in df.columns:
        s = df[active_col].astype(str).str.lower().str.strip()
        df = df[s.isin(["1","true","yes","y","是","啟用","在廠","出勤"]) | (df[active_col] == 1) | (df[active_col] == True)]
    return df.copy()

def table_from_df(df) -> list[dict[str, Any]]:
    if df is None: return []
    try:
        work = df.copy().fillna("")
        return [dict(r) for _, r in work.iterrows()]
    except Exception:
        return []

def _write_manifest() -> None:
    ensure_dirs()
    items = []
    for module_dir in sorted(AUTH_ROOT.glob("*")):
        if not module_dir.is_dir(): continue
        item = {"module_key": module_dir.name}
        for k in ["records", "settings"]:
            p = module_dir / f"{k}.json"
            item[k] = {"exists": p.exists(), "path": str(p.relative_to(PROJECT_ROOT)).replace(os.sep,"/")}
            if p.exists():
                payload = read_json(p)
                item[k]["updated_at"] = payload.get("updated_at") or payload.get("exported_at")
                item[k]["table_counts"] = payload.get("table_counts", {})
        items.append(item)
    atomic_write_json(MANIFEST_PATH, {"authority_schema":"SPT-PermanentAuthority-V28", "updated_at": now_text(), "modules": items})

def authority_health() -> dict[str, Any]:
    _write_manifest()
    return read_json(MANIFEST_PATH)
