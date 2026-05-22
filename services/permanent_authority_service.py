# -*- coding: utf-8 -*-
"""SPT V29 Permanent Authority Service.

正式資料規則：
- 每個模組只有 data/permanent_store/modules/<module_key>/records.json 是 records 權威檔。
- 每個模組只有 data/permanent_store/modules/<module_key>/settings.json 是 settings 權威檔。
- SQLite 只作快取；history 只作備份；預設資料只能在權威檔不存在時建立。
- 開頁只讀 canonical 權威檔，不掃 history、不做 GitHub 同步，避免載入超時。
- 儲存才寫 canonical，並嘗試 GitHub write-through + 遠端讀回驗證。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import time
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
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"

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
    k = "settings" if str(kind).lower().startswith("set") else "records"
    return module_dir(module_key) / f"{k}.json"


def ensure_dirs() -> None:
    AUTH_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)


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


def _clean_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [dict(r) for r in rows if isinstance(r, dict)]


def _normalize_tables_for_module(module_key: str, tables: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {str(k): _clean_rows(v) for k, v in (tables or {}).items() if isinstance(k, str)}
    if module_key == "13_system_settings":
        # 舊版只有 process_options，但新版 01 需要 category + process 連動。
        if not out.get("process_category_options") and out.get("process_options"):
            rows = []
            for i, r in enumerate(out.get("process_options", []), 1):
                x = dict(r)
                x.setdefault("id", i)
                x.setdefault("category_name", "全部 / 通用")
                rows.append(x)
            out["process_category_options"] = rows
        if not out.get("process_categories"):
            names = []
            for r in out.get("process_category_options", []):
                n = str(r.get("category_name", "") or "").strip() or "全部 / 通用"
                if n not in names:
                    names.append(n)
            out["process_categories"] = [
                {"id": i + 1, "category_name": n, "is_active": 1, "sort_order": i + 1, "note": "", "created_at": "", "updated_at": ""}
                for i, n in enumerate(names or ["全部 / 通用"])
            ]
        # Compatibility mirror.
        if out.get("process_category_options"):
            out["process_options"] = list(out["process_category_options"])
    expected = set(MODULES.get(module_key, {}).get("tables", []) or [])
    if expected:
        out = {k: v for k, v in out.items() if k in expected}
    return out


def _extract_tables(payload: dict[str, Any], module_key: str) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}
    tables = payload.get("tables")
    if isinstance(tables, dict):
        return _normalize_tables_for_module(module_key, tables)
    for key in ("records", "data", "rows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            default_table = (MODULES.get(module_key, {}).get("tables") or ["records"])[0]
            return _normalize_tables_for_module(module_key, {default_table: rows})
    return {}


def _table_counts(tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {k: len(v) for k, v in tables.items() if isinstance(v, list)}


def _total_rows(payload: dict[str, Any]) -> int:
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    return sum(len(v) for v in tables.values() if isinstance(v, list))


def normalize_payload(module_key: str, kind: str, payload: dict[str, Any] | None = None, *, reason: str = "authority_normalize", empty_authoritative: bool = False) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    tables = _extract_tables(payload, module_key)
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    return {
        "authority_schema": "SPT-PermanentAuthority-V29",
        "module_key": module_key,
        "kind": "settings" if str(kind).startswith("set") else "records",
        "updated_at": now_text(),
        "exported_at": payload.get("exported_at") or payload.get("updated_at") or payload.get("saved_at") or now_text(),
        "reason": reason,
        "empty_authoritative": bool(empty_authoritative),
        "tables": tables,
        "settings": settings,
        "table_counts": _table_counts(tables),
    }


def _legacy_candidates(module_key: str, kind: str) -> list[Path]:
    stem = "settings" if kind == "settings" else "records"
    names = [f"{module_key}_{stem}.json"]
    # 重要：舊版常把正式 tables 存在 settings/config/state 檔；records 與 settings 都要納入一次性遷移候選。
    names += [f"{module_key}_records.json", f"{module_key}_settings.json"]
    if module_key == "13_system_settings":
        names += ["spt_system_settings.json", "system_settings.json", "13_system_settings_records.json", "13_system_settings_settings.json"]
    if module_key == "10_permissions":
        names += ["spt_permission_settings.json", "spt_user_persistent_settings.json", "10_permissions_records.json", "10_permissions_settings.json"]
    if module_key == "ui_table_settings":
        names += ["table_persistence.json", "table_column_settings.json", "table_ui_settings.json", "spt_table_persistence.json", "spt_table_column_settings.json"]
    roots = [
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules" / module_key,
        PROJECT_ROOT / "data" / "persistent_modules" / module_key,
        PROJECT_ROOT / "data" / "permanent_store" / "persistent_state",
        PROJECT_ROOT / "data" / "persistent_state",
        PROJECT_ROOT / "data" / "permanent_store" / "config",
        PROJECT_ROOT / "data" / "config",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for n in names:
            p = root / n
            if p.exists() and str(p.resolve()) not in seen:
                seen.add(str(p.resolve()))
                out.append(p)
    return out


def _db_payload(module_key: str) -> dict[str, Any]:
    tables = MODULES.get(module_key, {}).get("tables", [])
    if not DB_PATH.exists() or not tables:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        for t in tables:
            try:
                exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
                if not exists:
                    continue
                out[t] = [dict(r) for r in conn.execute(f'SELECT * FROM "{t}"').fetchall()]
            except Exception:
                continue
        conn.close()
    except Exception:
        try:
            conn.close()  # type: ignore
        except Exception:
            pass
    if not out:
        return {}
    return normalize_payload(module_key, "records", {"tables": out, "exported_at": "0000-DB-CACHE"}, reason="migrated_from_sqlite_cache")


def _payload_score(path_label: str, payload: dict[str, Any]) -> tuple[str, float, int]:
    t = str(payload.get("exported_at") or payload.get("updated_at") or payload.get("saved_at") or "")
    rows = _total_rows(payload)
    mt = 0.0
    try:
        p = Path(path_label)
        if p.exists():
            mt = p.stat().st_mtime
    except Exception:
        pass
    return (t, mt, rows)


def _best_legacy_payload(module_key: str, kind: str) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = ("", 0.0, -1)
    best_source = "empty"
    for p in _legacy_candidates(module_key, kind):
        data = read_json(p)
        if not data:
            continue
        payload = normalize_payload(module_key, kind, data, reason=f"migrated_from_{p.relative_to(PROJECT_ROOT)}")
        score = _payload_score(str(p), payload)
        if score > best_score:
            best = payload; best_score = score; best_source = str(p.relative_to(PROJECT_ROOT))
    if kind == "records":
        dbp = _db_payload(module_key)
        if dbp:
            score = _payload_score("sqlite", dbp)
            # DB is cache, so use it only if no legacy latest has rows, or it has more rows than empty canonical.
            if score[2] > best_score[2] and best_score[2] <= 0:
                best = dbp; best_score = score; best_source = "sqlite_cache"
    if best:
        best["reason"] = f"migrated_from_{best_source}"
    return best


def _needs_repair(payload: dict[str, Any], module_key: str, kind: str) -> bool:
    if not payload:
        return True
    if payload.get("empty_authoritative"):
        return False
    # V28 初版可能已建立空 canonical，造成後續不再遷移舊 latest；V29 允許空 canonical 修復一次。
    if _total_rows(payload) <= 0 and kind == "records":
        # 權限/系統設定/主檔不應在有舊 latest 或 DB 的情況下保持空檔。
        if module_key in {"10_permissions", "13_system_settings", "03_work_orders", "04_employees", "01_time_records", "02_history"}:
            return True
    return False


def migrate_once(module_key: str, kind: str) -> dict[str, Any]:
    ensure_dirs()
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    path = canonical_path(module_key, kind)
    cur = read_json(path) if path.exists() else {}
    if path.exists() and not _needs_repair(cur, module_key, kind):
        return cur
    legacy = _best_legacy_payload(module_key, kind)
    if legacy and (not cur or _total_rows(legacy) > _total_rows(cur) or _total_rows(cur) == 0):
        payload = normalize_payload(module_key, kind, legacy, reason=legacy.get("reason", "migrated_v29"))
    elif cur:
        payload = normalize_payload(module_key, kind, cur, reason=cur.get("reason", "canonical_normalized_v29"))
    else:
        payload = normalize_payload(module_key, kind, {}, reason="empty_canonical_created_v29")
    atomic_write_json(path, payload)
    return payload


def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:
    ensure_dirs()
    return migrate_once(str(module_key), "settings" if str(kind).lower().startswith("set") else "records")


def load_tables(module_key: str, kind: str = "records") -> dict[str, list[dict[str, Any]]]:
    payload = load_authority(module_key, kind)
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    return {str(k): _clean_rows(v) for k, v in tables.items()}


def _backup_current(module_key: str, kind: str) -> None:
    p = canonical_path(module_key, kind)
    if p.exists():
        b = BACKUP_ROOT / module_key / kind / f"{kind}_{_stamp()}.json"
        b.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, b)
        except Exception:
            pass


def _remote_path(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/")


def _github_get_content(rel: str) -> dict[str, Any]:
    cfg = github_config()
    if not cfg["token"] or not cfg["repo"]:
        return {}
    api = f"https://api.github.com/repos/{cfg['repo']}/contents/{urllib.parse.quote(rel)}?ref={urllib.parse.quote(cfg['branch'])}"
    headers = {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json", "User-Agent": "SPT-TimeTracking-V29"}
    try:
        req = urllib.request.Request(api, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def github_put_file(path: Path, content: str, message: str) -> dict[str, Any]:
    cfg = github_config()
    if not cfg["token"] or not cfg["repo"]:
        return {"ok": False, "skipped": True, "reason": "missing_github_config"}
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    rel = _remote_path(path)
    if _UPLOAD_HASH.get(rel) == sha:
        return {"ok": True, "skipped": True, "reason": "unchanged", "path": rel, "verified": True}
    current = _github_get_content(rel)
    old_sha = current.get("sha")
    headers = {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json", "User-Agent": "SPT-TimeTracking-V29", "Content-Type": "application/json"}
    body: dict[str, Any] = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "branch": cfg["branch"]}
    if old_sha:
        body["sha"] = old_sha
    api = f"https://api.github.com/repos/{cfg['repo']}/contents/{urllib.parse.quote(rel)}"
    try:
        req = urllib.request.Request(api, data=json.dumps(body).encode("utf-8"), headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=25) as r:
            res = json.loads(r.read().decode("utf-8"))
        # verify by reading back content SHA from GitHub.
        verified = False
        back = _github_get_content(rel)
        try:
            raw = base64.b64decode(str(back.get("content", "")).encode("ascii")).decode("utf-8")
            verified = hashlib.sha256(raw.encode("utf-8")).hexdigest() == sha
        except Exception:
            verified = bool(back.get("sha"))
        _UPLOAD_HASH[rel] = sha
        return {"ok": True, "path": rel, "commit": (res.get("commit") or {}).get("sha", ""), "verified": verified}
    except Exception as exc:
        return {"ok": False, "path": rel, "error": str(exc)[:300], "verified": False}


def save_authority(module_key: str, *, records: dict[str, list[dict[str, Any]]] | None = None, settings: dict[str, Any] | None = None, reason: str = "authority_save", github: bool = True) -> dict[str, Any]:
    ensure_dirs()
    out: dict[str, Any] = {"ok": True, "module_key": module_key, "files": [], "github": []}
    if records is not None:
        kind = "records"; p = canonical_path(module_key, kind); _backup_current(module_key, kind)
        empty_auth = _table_counts(records) == {} or sum(_table_counts(records).values()) == 0
        payload = normalize_payload(module_key, kind, {"tables": records}, reason=reason, empty_authoritative=empty_auth)
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
    cur.update({k: _clean_rows(v) for k, v in updates.items()})
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
        if c not in df.columns:
            df[c] = ""
    if cols:
        df = df[cols]
    if active_only and active_col and active_col in df.columns:
        s = df[active_col].astype(str).str.lower().str.strip()
        df = df[s.isin(["1", "true", "yes", "y", "是", "啟用", "在廠", "出勤"]) | (df[active_col] == 1) | (df[active_col] == True)]
    return df.copy()


def table_from_df(df) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        work = df.copy().fillna("")
        return [dict(r) for _, r in work.iterrows()]
    except Exception:
        return []


def preload_authority(module_keys: Iterable[str] | None = None) -> dict[str, Any]:
    """Lightweight preload after login/page open: only stat+read canonical files, no GitHub, no history scan."""
    keys = list(module_keys or MODULES.keys())
    result: dict[str, Any] = {"ok": True, "modules": {}}
    for k in keys:
        try:
            rec = load_authority(k, "records")
            sett = load_authority(k, "settings")
            result["modules"][k] = {"records": rec.get("table_counts", {}), "settings": sett.get("table_counts", {})}
        except Exception as exc:
            result["ok"] = False
            result["modules"][k] = {"error": str(exc)[:200]}
    return result


def _write_manifest() -> None:
    ensure_dirs()
    items = []
    for d in sorted(AUTH_ROOT.glob("*")):
        if not d.is_dir():
            continue
        item: dict[str, Any] = {"module_key": d.name}
        for k in ["records", "settings"]:
            p = d / f"{k}.json"
            item[k] = {"exists": p.exists(), "path": str(p.relative_to(PROJECT_ROOT)).replace(os.sep, "/")}
            if p.exists():
                payload = read_json(p)
                item[k]["updated_at"] = payload.get("updated_at") or payload.get("exported_at")
                item[k]["table_counts"] = payload.get("table_counts", {})
                item[k]["empty_authoritative"] = payload.get("empty_authoritative", False)
        items.append(item)
    atomic_write_json(MANIFEST_PATH, {"authority_schema": "SPT-PermanentAuthority-V29", "updated_at": now_text(), "modules": items})


def authority_health() -> dict[str, Any]:
    _write_manifest()
    return read_json(MANIFEST_PATH)


# ========================= V72 Fast Local-First Authority Save =========================
# 目的：所有模組按下「套用 / 確認 / 存檔」時，不再被 GitHub 讀回驗證與重複上傳拖慢。
# 原則：
# 1. 本機 canonical 權威檔仍立即寫入，功能與 Reboot App 本機狀態不受影響。
# 2. GitHub 仍會 write-through，但改為短逾時、SHA 快取、不做第二次讀回驗證。
# 3. 內容未變更時不寫 history、不打 GitHub API。
# 4. 任何 GitHub 失敗不得讓頁面或儲存流程崩潰。

_GITHUB_SHA_CACHE_V72: dict[str, str] = {}


def _v72_sha_text(text: str) -> str:
    try:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    except Exception:
        return ""


def _v72_read_text_safe(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def _v72_payload_text(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    except Exception:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _v72_github_timeout_get() -> float:
    try:
        return float(os.environ.get("SPT_GITHUB_GET_TIMEOUT", "5") or 5)
    except Exception:
        return 5.0


def _v72_github_timeout_put() -> float:
    try:
        return float(os.environ.get("SPT_GITHUB_PUT_TIMEOUT", "8") or 8)
    except Exception:
        return 8.0


def _github_get_content(rel: str) -> dict[str, Any]:  # type: ignore[override]
    """V72: short-timeout GitHub metadata read; used only to get current SHA."""
    cfg = github_config()
    if not cfg.get("token") or not cfg.get("repo"):
        return {}
    api = f"https://api.github.com/repos/{cfg['repo']}/contents/{urllib.parse.quote(rel)}?ref={urllib.parse.quote(cfg['branch'])}"
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "SPT-TimeTracking-V72",
    }
    try:
        req = urllib.request.Request(api, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=_v72_github_timeout_get()) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def github_put_file(path: Path, content: str, message: str) -> dict[str, Any]:  # type: ignore[override]
    """V72: GitHub write-through optimized for Streamlit save buttons.

    GitHub Contents API needs the current file SHA for updates. We cache the SHA after
    a successful PUT, skip uploads when the same content was already uploaded in this
    Python process, and avoid the old second read-back verification that caused long waits.
    """
    cfg = github_config()
    rel = _remote_path(path)
    if not cfg.get("token") or not cfg.get("repo"):
        return {"ok": False, "skipped": True, "reason": "missing_github_config", "path": rel, "verified": False}

    content = content or ""
    content_sha = _v72_sha_text(content)
    if _UPLOAD_HASH.get(rel) == content_sha:
        return {"ok": True, "skipped": True, "reason": "unchanged_in_process", "path": rel, "verified": True, "mode": "v72_fast"}

    old_sha = _GITHUB_SHA_CACHE_V72.get(rel, "")
    if not old_sha:
        current = _github_get_content(rel)
        old_sha = str(current.get("sha") or "")
        if old_sha:
            _GITHUB_SHA_CACHE_V72[rel] = old_sha

    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "SPT-TimeTracking-V72",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if old_sha:
        body["sha"] = old_sha
    api = f"https://api.github.com/repos/{cfg['repo']}/contents/{urllib.parse.quote(rel)}"
    try:
        req = urllib.request.Request(api, data=json.dumps(body).encode("utf-8"), headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=_v72_github_timeout_put()) as r:
            res = json.loads(r.read().decode("utf-8"))
        new_sha = str(((res.get("content") or {}).get("sha")) or ((res.get("commit") or {}).get("sha")) or "")
        if new_sha:
            _GITHUB_SHA_CACHE_V72[rel] = new_sha
        _UPLOAD_HASH[rel] = content_sha
        return {"ok": True, "path": rel, "commit": (res.get("commit") or {}).get("sha", ""), "verified": True, "mode": "v72_fast"}
    except Exception as exc:
        return {"ok": False, "path": rel, "error": str(exc)[:300], "verified": False, "mode": "v72_fast"}


def save_authority(module_key: str, *, records: dict[str, list[dict[str, Any]]] | None = None, settings: dict[str, Any] | None = None, reason: str = "authority_save", github: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """V72: local-first save with unchanged-content skip and fast GitHub write-through."""
    ensure_dirs()
    out: dict[str, Any] = {"ok": True, "module_key": module_key, "files": [], "github": [], "mode": "v72_fast_local_first"}

    if records is not None:
        kind = "records"
        p = canonical_path(module_key, kind)
        empty_auth = _table_counts(records) == {} or sum(_table_counts(records).values()) == 0
        payload = normalize_payload(module_key, kind, {"tables": records}, reason=reason, empty_authoritative=empty_auth)
        new_text = _v72_payload_text(payload)
        old_text = _v72_read_text_safe(p)
        changed = _v72_sha_text(new_text) != _v72_sha_text(old_text)
        if changed:
            _backup_current(module_key, kind)
            atomic_write_json(p, payload)
        out["files"].append(str(p))
        out["changed_records"] = bool(changed)
        if github and changed:
            out["github"].append(github_put_file(p, p.read_text(encoding="utf-8"), f"SPT authority {module_key} records: {reason}"))
        elif github and not changed:
            out["github"].append({"ok": True, "skipped": True, "reason": "unchanged_local", "path": _remote_path(p), "mode": "v72_fast"})

    if settings is not None:
        kind = "settings"
        p = canonical_path(module_key, kind)
        payload = normalize_payload(
            module_key,
            kind,
            {"settings": settings, "tables": settings.get("tables", {}) if isinstance(settings, dict) else {}},
            reason=reason,
        )
        new_text = _v72_payload_text(payload)
        old_text = _v72_read_text_safe(p)
        changed = _v72_sha_text(new_text) != _v72_sha_text(old_text)
        if changed:
            _backup_current(module_key, kind)
            atomic_write_json(p, payload)
        out["files"].append(str(p))
        out["changed_settings"] = bool(changed)
        if github and changed:
            out["github"].append(github_put_file(p, p.read_text(encoding="utf-8"), f"SPT authority {module_key} settings: {reason}"))
        elif github and not changed:
            out["github"].append({"ok": True, "skipped": True, "reason": "unchanged_local", "path": _remote_path(p), "mode": "v72_fast"})

    try:
        _write_manifest()
    except Exception:
        pass
    return out


def update_tables(module_key: str, updates: dict[str, list[dict[str, Any]]], *, reason: str = "update_tables", github: bool = True) -> dict[str, Any]:  # type: ignore[override]
    cur = load_tables(module_key, "records")
    cur.update({k: _clean_rows(v) for k, v in (updates or {}).items()})
    return save_authority(module_key, records=cur, reason=reason, github=github)


def save_settings(module_key: str, settings: dict[str, Any], *, reason: str = "save_settings", github: bool = True) -> dict[str, Any]:  # type: ignore[override]
    return save_authority(module_key, settings=settings or {}, reason=reason, github=github)
# ======================= END V72 Fast Local-First Authority Save =======================


# ========================= V84 SINGLE CANONICAL AUTHORITY MODE =========================
# 依 V28 已驗證方法回復並強化：每個模組只讀/寫 data/permanent_store/modules/<module_key>/<kind>.json。
# - canonical 檔案存在時，絕不再從 SQLite、persistent_modules、persistent_state、history 或預設資料修復覆蓋。
# - canonical 檔案不存在時，才做一次舊資料遷移，建立 canonical。
# - save 只寫 canonical 本檔；不寫 history backup，不寫 manifest，不掃描舊路徑。
# - GitHub write-through 仍只寫同一個 canonical repo path，避免 Reboot App 後恢復舊資料。

def authority_file_exists(module_key: str, kind: str = "records") -> bool:
    try:
        return canonical_path(str(module_key), "settings" if str(kind).lower().startswith("set") else "records").exists()
    except Exception:
        return False


def _v84_empty_payload(module_key: str, kind: str, reason: str = "empty_canonical_created_v84") -> dict[str, Any]:
    return normalize_payload(str(module_key), "settings" if str(kind).lower().startswith("set") else "records", {}, reason=reason, empty_authoritative=True)


def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:  # type: ignore[override]
    """V84: read canonical only once it exists; no repair from old/DB/history."""
    ensure_dirs()
    module_key = str(module_key)
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    p = canonical_path(module_key, kind)
    if p.exists():
        data = read_json(p)
        # Return a normalized in-memory view, but do not rewrite or repair from any other source.
        if data:
            return normalize_payload(module_key, kind, data, reason=data.get("reason") or "canonical_loaded_v84", empty_authoritative=bool(data.get("empty_authoritative", False)))
        return _v84_empty_payload(module_key, kind, reason="empty_or_invalid_canonical_loaded_v84")

    # First-time only: if the canonical file does not exist, migrate one best legacy payload.
    legacy = _best_legacy_payload(module_key, kind)
    if legacy:
        payload = normalize_payload(module_key, kind, legacy, reason=legacy.get("reason", "migrated_once_v84"), empty_authoritative=False)
    else:
        payload = _v84_empty_payload(module_key, kind)
    atomic_write_json(p, payload)
    return payload


def load_tables(module_key: str, kind: str = "records") -> dict[str, list[dict[str, Any]]]:  # type: ignore[override]
    payload = load_authority(module_key, kind)
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    return {str(k): _clean_rows(v) for k, v in tables.items()}


def save_authority(module_key: str, *, records: dict[str, list[dict[str, Any]]] | None = None, settings: dict[str, Any] | None = None, reason: str = "authority_save", github: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """V84: write only the canonical authority file(s). No legacy mirror/history/manifest writes."""
    ensure_dirs()
    module_key = str(module_key)
    out: dict[str, Any] = {"ok": True, "module_key": module_key, "files": [], "github": [], "mode": "v84_single_canonical"}

    if records is not None:
        p = canonical_path(module_key, "records")
        empty_auth = _table_counts(records) == {} or sum(_table_counts(records).values()) == 0
        payload = normalize_payload(module_key, "records", {"tables": records}, reason=reason, empty_authoritative=empty_auth)
        new_text = _v72_payload_text(payload) if "_v72_payload_text" in globals() else json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
        old_text = _v72_read_text_safe(p) if "_v72_read_text_safe" in globals() else (p.read_text(encoding="utf-8") if p.exists() else "")
        changed = (_v72_sha_text(new_text) if "_v72_sha_text" in globals() else hashlib.sha256(new_text.encode("utf-8")).hexdigest()) != (_v72_sha_text(old_text) if "_v72_sha_text" in globals() else hashlib.sha256(old_text.encode("utf-8")).hexdigest())
        if changed:
            atomic_write_json(p, payload)
        out["files"].append(str(p))
        out["changed_records"] = bool(changed)
        if github and changed:
            out["github"].append(github_put_file(p, p.read_text(encoding="utf-8"), f"SPT authority {module_key} records: {reason}"))
        elif github:
            out["github"].append({"ok": True, "skipped": True, "reason": "unchanged_single_canonical", "path": _remote_path(p), "mode": "v84_single_canonical"})

    if settings is not None:
        p = canonical_path(module_key, "settings")
        payload = normalize_payload(module_key, "settings", {"settings": settings or {}, "tables": (settings or {}).get("tables", {}) if isinstance(settings, dict) else {}}, reason=reason)
        new_text = _v72_payload_text(payload) if "_v72_payload_text" in globals() else json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
        old_text = _v72_read_text_safe(p) if "_v72_read_text_safe" in globals() else (p.read_text(encoding="utf-8") if p.exists() else "")
        changed = (_v72_sha_text(new_text) if "_v72_sha_text" in globals() else hashlib.sha256(new_text.encode("utf-8")).hexdigest()) != (_v72_sha_text(old_text) if "_v72_sha_text" in globals() else hashlib.sha256(old_text.encode("utf-8")).hexdigest())
        if changed:
            atomic_write_json(p, payload)
        out["files"].append(str(p))
        out["changed_settings"] = bool(changed)
        if github and changed:
            out["github"].append(github_put_file(p, p.read_text(encoding="utf-8"), f"SPT authority {module_key} settings: {reason}"))
        elif github:
            out["github"].append({"ok": True, "skipped": True, "reason": "unchanged_single_canonical", "path": _remote_path(p), "mode": "v84_single_canonical"})
    return out


def update_tables(module_key: str, updates: dict[str, list[dict[str, Any]]], *, reason: str = "update_tables", github: bool = True) -> dict[str, Any]:  # type: ignore[override]
    cur = load_tables(module_key, "records")
    cur.update({str(k): _clean_rows(v) for k, v in (updates or {}).items()})
    return save_authority(module_key, records=cur, reason=reason, github=github)


def load_settings(module_key: str) -> dict[str, Any]:  # type: ignore[override]
    payload = load_authority(module_key, "settings")
    return payload.get("settings") if isinstance(payload.get("settings"), dict) else {}


def save_settings(module_key: str, settings: dict[str, Any], *, reason: str = "save_settings", github: bool = True) -> dict[str, Any]:  # type: ignore[override]
    return save_authority(module_key, settings=settings or {}, reason=reason, github=github)
# ======================= END V84 SINGLE CANONICAL AUTHORITY MODE =====================


# ========================= V84.1 PROMOTE MISPLACED CANONICAL SETTINGS TABLES =========================
# 有些先前版本誤把 records 內容寫進 settings.json，導致 records.json 是空檔。
# 這裡只在 records.json 已存在但為 0 筆、且同模組 settings.json 內有 tables 時，
# 一次性把 settings.tables 搬回 records.json。搬回後仍只以 records.json 作資料權威。

def _v841_promote_settings_tables_if_records_empty(module_key: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind != "records" or _total_rows(payload) > 0:
            return payload
        sp = canonical_path(module_key, "settings")
        if not sp.exists():
            return payload
        sdata = read_json(sp)
        tables = _extract_tables(sdata, module_key)
        if not tables or sum(len(v) for v in tables.values() if isinstance(v, list)) <= 0:
            return payload
        promoted = normalize_payload(module_key, "records", {"tables": tables}, reason="promoted_from_canonical_settings_tables_v84_1", empty_authoritative=False)
        atomic_write_json(canonical_path(module_key, "records"), promoted)
        return promoted
    except Exception:
        return payload


def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:  # type: ignore[override]
    ensure_dirs()
    module_key = str(module_key)
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    p = canonical_path(module_key, kind)
    if p.exists():
        data = read_json(p)
        if data:
            payload = normalize_payload(module_key, kind, data, reason=data.get("reason") or "canonical_loaded_v84_1", empty_authoritative=bool(data.get("empty_authoritative", False)))
        else:
            payload = _v84_empty_payload(module_key, kind, reason="empty_or_invalid_canonical_loaded_v84_1")
        return _v841_promote_settings_tables_if_records_empty(module_key, kind, payload)

    legacy = _best_legacy_payload(module_key, kind)
    if legacy:
        payload = normalize_payload(module_key, kind, legacy, reason=legacy.get("reason", "migrated_once_v84_1"), empty_authoritative=False)
    else:
        payload = _v84_empty_payload(module_key, kind, reason="empty_canonical_created_v84_1")
    atomic_write_json(p, payload)
    return payload


def load_tables(module_key: str, kind: str = "records") -> dict[str, list[dict[str, Any]]]:  # type: ignore[override]
    payload = load_authority(module_key, kind)
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    return {str(k): _clean_rows(v) for k, v in tables.items()}
# ======================= END V84.1 PROMOTE MISPLACED CANONICAL SETTINGS TABLES =====================


# ========================= V84.2 PRIMARY TABLE EMPTY PROMOTION =========================
_V842_PRIMARY_TABLES = {
    "01_time_records": ["time_records"],
    "02_history": ["time_records"],
    "03_work_orders": ["work_orders"],
    "04_employees": ["employees"],
    "10_permissions": ["auth_users"],
    "11_login_logs": ["auth_login_logs", "login_logs", "security_login_logs"],
    "13_system_settings": ["process_categories", "process_category_options", "rest_periods"],
}


def _v842_primary_empty(module_key: str, payload: dict[str, Any]) -> bool:
    try:
        tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
        primaries = _V842_PRIMARY_TABLES.get(module_key, [])
        if not primaries:
            return _total_rows(payload) <= 0
        # If all expected primary tables are missing/empty, the records authority is functionally empty.
        return all(len(tables.get(t, []) if isinstance(tables.get(t), list) else []) <= 0 for t in primaries)
    except Exception:
        return False


def _v842_promote_settings_tables_if_primary_empty(module_key: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind != "records" or not _v842_primary_empty(module_key, payload):
            return payload
        sp = canonical_path(module_key, "settings")
        if not sp.exists():
            return payload
        sdata = read_json(sp)
        tables = _extract_tables(sdata, module_key)
        if not tables:
            return payload
        # Only promote if the settings file has at least one primary table with data.
        primaries = _V842_PRIMARY_TABLES.get(module_key, [])
        if primaries and all(len(tables.get(t, []) if isinstance(tables.get(t), list) else []) <= 0 for t in primaries):
            return payload
        if not primaries and sum(len(v) for v in tables.values() if isinstance(v, list)) <= 0:
            return payload
        promoted = normalize_payload(module_key, "records", {"tables": tables}, reason="promoted_from_canonical_settings_primary_empty_v84_2", empty_authoritative=False)
        atomic_write_json(canonical_path(module_key, "records"), promoted)
        return promoted
    except Exception:
        return payload


def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:  # type: ignore[override]
    ensure_dirs()
    module_key = str(module_key)
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    p = canonical_path(module_key, kind)
    if p.exists():
        data = read_json(p)
        if data:
            payload = normalize_payload(module_key, kind, data, reason=data.get("reason") or "canonical_loaded_v84_2", empty_authoritative=bool(data.get("empty_authoritative", False)))
        else:
            payload = _v84_empty_payload(module_key, kind, reason="empty_or_invalid_canonical_loaded_v84_2")
        payload = _v841_promote_settings_tables_if_records_empty(module_key, kind, payload)
        payload = _v842_promote_settings_tables_if_primary_empty(module_key, kind, payload)
        return payload
    legacy = _best_legacy_payload(module_key, kind)
    if legacy:
        payload = normalize_payload(module_key, kind, legacy, reason=legacy.get("reason", "migrated_once_v84_2"), empty_authoritative=False)
    else:
        payload = _v84_empty_payload(module_key, kind, reason="empty_canonical_created_v84_2")
    atomic_write_json(p, payload)
    return payload
# ======================= END V84.2 PRIMARY TABLE EMPTY PROMOTION =====================


# ========================= V84.3 DO NOT REVIVE FUTURE EMPTY CANONICAL FILES =========================
# V84 之後若使用者真的把某模組刪成 0 筆，save_authority 會寫入 v84 reason。
# 這種 0 筆是正式結果，不能再從 settings 舊資料復活。

def _v843_allow_promote_from_settings(payload: dict[str, Any]) -> bool:
    reason = str(payload.get("reason") or "").lower()
    if "v84" in reason or "single_canonical" in reason:
        return False
    return True


def _v842_promote_settings_tables_if_primary_empty(module_key: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
    try:
        if kind != "records" or not _v842_primary_empty(module_key, payload):
            return payload
        if not _v843_allow_promote_from_settings(payload):
            return payload
        sp = canonical_path(module_key, "settings")
        if not sp.exists():
            return payload
        sdata = read_json(sp)
        tables = _extract_tables(sdata, module_key)
        if not tables:
            return payload
        primaries = _V842_PRIMARY_TABLES.get(module_key, [])
        if primaries and all(len(tables.get(t, []) if isinstance(tables.get(t), list) else []) <= 0 for t in primaries):
            return payload
        if not primaries and sum(len(v) for v in tables.values() if isinstance(v, list)) <= 0:
            return payload
        promoted = normalize_payload(module_key, "records", {"tables": tables}, reason="promoted_from_canonical_settings_primary_empty_v84_3", empty_authoritative=False)
        atomic_write_json(canonical_path(module_key, "records"), promoted)
        return promoted
    except Exception:
        return payload


def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:  # type: ignore[override]
    ensure_dirs()
    module_key = str(module_key)
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    p = canonical_path(module_key, kind)
    if p.exists():
        data = read_json(p)
        if data:
            payload = normalize_payload(module_key, kind, data, reason=data.get("reason") or "canonical_loaded_v84_3", empty_authoritative=bool(data.get("empty_authoritative", False)))
        else:
            payload = _v84_empty_payload(module_key, kind, reason="empty_or_invalid_canonical_loaded_v84_3")
        if _v843_allow_promote_from_settings(payload):
            payload = _v841_promote_settings_tables_if_records_empty(module_key, kind, payload)
            payload = _v842_promote_settings_tables_if_primary_empty(module_key, kind, payload)
        return payload
    legacy = _best_legacy_payload(module_key, kind)
    if legacy:
        payload = normalize_payload(module_key, kind, legacy, reason=legacy.get("reason", "migrated_once_v84_3"), empty_authoritative=False)
    else:
        payload = _v84_empty_payload(module_key, kind, reason="empty_canonical_created_v84_3")
    atomic_write_json(p, payload)
    return payload
# ======================= END V84.3 DO NOT REVIVE FUTURE EMPTY CANONICAL FILES =====================


# ========================= V84.4 PROMOTE LEGACY ONLY FOR PRE-V84 BROKEN EMPTY PRIMARY =========================
# 如果 records.json 已存在但主表為空，而且 reason 是 V84 之前的舊錯誤，允許最後一次從舊 latest/DB 遷移。
# V84 之後寫出的空 records 會保留為正式空資料，不再復活舊檔。

def _v844_promote_legacy_if_pre_v84_primary_empty(module_key: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind != "records" or not _v842_primary_empty(module_key, payload) or not _v843_allow_promote_from_settings(payload):
            return payload
        legacy = _best_legacy_payload(module_key, kind)
        if not legacy:
            return payload
        promoted = normalize_payload(module_key, kind, legacy, reason="promoted_from_legacy_pre_v84_primary_empty_v84_4", empty_authoritative=False)
        if _v842_primary_empty(module_key, promoted):
            return payload
        atomic_write_json(canonical_path(module_key, kind), promoted)
        return promoted
    except Exception:
        return payload


def load_authority(module_key: str, kind: str = "records") -> dict[str, Any]:  # type: ignore[override]
    ensure_dirs()
    module_key = str(module_key)
    kind = "settings" if str(kind).lower().startswith("set") else "records"
    p = canonical_path(module_key, kind)
    if p.exists():
        data = read_json(p)
        if data:
            payload = normalize_payload(module_key, kind, data, reason=data.get("reason") or "canonical_loaded_v84_4", empty_authoritative=bool(data.get("empty_authoritative", False)))
        else:
            payload = _v84_empty_payload(module_key, kind, reason="empty_or_invalid_canonical_loaded_v84_4")
        if _v843_allow_promote_from_settings(payload):
            payload = _v841_promote_settings_tables_if_records_empty(module_key, kind, payload)
            payload = _v842_promote_settings_tables_if_primary_empty(module_key, kind, payload)
            payload = _v844_promote_legacy_if_pre_v84_primary_empty(module_key, kind, payload)
        return payload
    legacy = _best_legacy_payload(module_key, kind)
    if legacy:
        payload = normalize_payload(module_key, kind, legacy, reason=legacy.get("reason", "migrated_once_v84_4"), empty_authoritative=False)
    else:
        payload = _v84_empty_payload(module_key, kind, reason="empty_canonical_created_v84_4")
    atomic_write_json(p, payload)
    return payload
# ======================= END V84.4 PROMOTE LEGACY ONLY FOR PRE-V84 BROKEN EMPTY PRIMARY =====================
