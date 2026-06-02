# -*- coding: utf-8 -*-
"""Module persistence center backed by Neon/PostgreSQL when configured.

Keeps the original 12｜模組永久紀錄中心 UI contract, but module records and
settings are no longer authoritative JSON files on Streamlit Cloud.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

try:
    from services.timezone_service import now_text, now_stamp
except Exception:
    def now_text() -> str: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def now_stamp() -> str: return datetime.now().strftime("%Y%m%d_%H%M%S")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
PERSIST_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules"
GLOBAL_STATE = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_independent_state.json"
GLOBAL_SETTINGS = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state" / "spt_module_independent_settings.json"

MODULE_TABLE_MAP: Dict[str, Dict[str, Any]] = {
    "01_time_records": {"name_zh": "工時紀錄", "name_en": "Time Records", "tables": ["time_records"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "01_time_record": {"name_zh": "工時紀錄", "name_en": "Time Records", "tables": ["time_records"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "02_history": {"name_zh": "歷史紀錄", "name_en": "History", "tables": ["time_records"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "03_work_orders": {"name_zh": "製令管理", "name_en": "Work Orders", "tables": ["work_orders"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "04_employees": {"name_zh": "人員名單", "name_en": "Employees", "tables": ["employees"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "05_analysis": {"name_zh": "製令工時分析", "name_en": "Work Order Analysis", "tables": ["time_records", "work_orders", "employees"], "settings_keys": ["table_columns", "sort", "filters", "chart", "ui"]},
    "06_logs": {"name_zh": "LOG查詢", "name_en": "System Logs", "tables": ["system_logs"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "07_missing_today": {"name_zh": "今日未紀錄名單", "name_en": "Missing Today", "tables": ["employees", "time_records"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "07_missing": {"name_zh": "今日未紀錄名單", "name_en": "Missing Today Legacy", "tables": ["employees", "time_records"], "settings_keys": ["table_columns", "sort", "filters", "ui"]},
    "08_daily_hours": {"name_zh": "人員每日工時", "name_en": "Daily Hours", "tables": ["employees", "time_records"], "settings_keys": ["table_columns", "sort", "filters", "chart", "ui"]},
    "09_persistence": {"name_zh": "資料永久保存與備份", "name_en": "Persistence & Backup", "tables": ["system_settings"], "settings_keys": ["github", "backup", "ui"]},
    "10_permissions": {"name_zh": "權限管理", "name_en": "Permissions", "tables": ["auth_users", "auth_account_permissions", "auth_security_settings", "security_users", "security_module_permissions", "security_settings"], "settings_keys": ["table_columns", "sort", "filters", "security", "ui"]},
    "11_login_logs": {"name_zh": "登入紀錄", "name_en": "Login Logs", "tables": ["auth_login_logs", "security_login_logs"], "settings_keys": ["table_columns", "sort", "filters", "retention", "ui"]},
    "12_module_persistence": {"name_zh": "模組永久紀錄中心", "name_en": "Module Permanent Records", "tables": ["spt_module_authority"], "settings_keys": ["module_persistence", "records", "settings", "audit", "history", "ui"]},
    "13_system_settings": {"name_zh": "系統設定", "name_en": "System Settings", "tables": ["process_options", "rest_periods", "system_settings", "app_settings"], "settings_keys": ["process", "rest_periods", "ui"]},
    "14_data_health": {"name_zh": "資料健康檢查中心", "name_en": "Data Health", "tables": ["spt_module_authority_audit"], "settings_keys": ["ui"]},
    "98_authority_diagnostic": {"name_zh": "權威檔診斷", "name_en": "Authority Diagnostic", "tables": ["spt_module_authority"], "settings_keys": ["ui"]},
    "99_speed_diagnostic": {"name_zh": "效能診斷", "name_en": "Performance", "tables": ["spt_module_authority_audit"], "settings_keys": ["ui"]},
}


def _now() -> str: return now_text()
def _stamp() -> str: return now_stamp()

def normalize_module_code(module_code: str) -> str:
    code = str(module_code or "").strip()
    if code == "01_time_record":
        return "01_time_records"
    return code


def _is_pg() -> bool:
    try:
        from services.db_service import is_postgres_enabled
        return bool(is_postgres_enabled())
    except Exception:
        return False


def ensure_dirs() -> None:
    PERSIST_ROOT.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "permanent_store" / "persistent_state").mkdir(parents=True, exist_ok=True)
    if _is_pg():
        try:
            from services.neon_authority_service import ensure_neon_authority_schema
            ensure_neon_authority_schema()
        except Exception:
            pass


def module_dir(module_code: str) -> Path:
    return PERSIST_ROOT / normalize_module_code(module_code)

def latest_records_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / f"{code}_records.json"

def latest_settings_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / f"{code}_settings.json"

def latest_audit_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / f"{code}_audit.jsonl"

def history_records_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / "history" / f"{code}_records_{_stamp()}.json"

def history_settings_path(module_code: str) -> Path:
    code = normalize_module_code(module_code)
    return module_dir(code) / "history" / f"{code}_settings_{_stamp()}.json"


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def read_table(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    if not table_exists(conn, table): return []
    rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
    return [dict(r) for r in rows]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table): return 0
    return int(conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()["c"])


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def append_audit(module_code: str, action: str, username: str = "SYSTEM", detail: Optional[Dict[str, Any]] = None) -> None:
    if _is_pg():
        from services.neon_authority_service import append_audit as _append
        _append(normalize_module_code(module_code), action, username, "OK", "", detail or {})
        return
    ensure_dirs()
    payload = {"time": _now(), "module_code": module_code, "username": username, "action": action, "detail": detail or {}}
    path = latest_audit_path(module_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _pg_read_table(table: str) -> list[dict[str, Any]]:
    try:
        from services.db_service import query_df
        df = query_df(f"SELECT * FROM {table}")
        return df.to_dict("records") if df is not None and not df.empty else []
    except Exception:
        return []


def _table_rows(table: str) -> list[dict[str, Any]]:
    if _is_pg(): return _pg_read_table(table)
    if not DB_PATH.exists(): return []
    with connect_db() as conn: return read_table(conn, table)


def export_module_records(module_code: str, username: str = "SYSTEM", write_history: bool = True) -> Dict[str, Any]:
    ensure_dirs()
    code = normalize_module_code(module_code)
    info = MODULE_TABLE_MAP.get(code) or MODULE_TABLE_MAP.get(module_code)
    if not info:
        raise ValueError(f"Unknown module_code: {module_code}")
    payload = {"schema_version": "neon-v31", "exported_at": _now(), "module_code": code, "module_name_zh": info["name_zh"], "module_name_en": info["name_en"], "tables": {}, "counts": {}, "backend": "neon" if _is_pg() else "sqlite"}
    for table in info.get("tables", []):
        data = _table_rows(table)
        payload["tables"][table] = data
        payload["counts"][table] = len(data)
    if _is_pg():
        from services.neon_authority_service import save_payload
        save_payload(code, "records", payload, username)
    else:
        save_json(latest_records_path(code), payload)
        if write_history: save_json(history_records_path(code), payload)
    append_audit(code, "EXPORT_RECORDS", username, {"counts": payload["counts"], "backend": payload["backend"]})
    rebuild_global_index()
    return payload


def export_all_modules(username: str = "SYSTEM") -> Dict[str, Any]:
    ensure_dirs()
    result = {}
    seen = set()
    for raw_code in MODULE_TABLE_MAP:
        code = normalize_module_code(raw_code)
        if code in seen: continue
        seen.add(code)
        try: result[code] = export_module_records(code, username=username, write_history=True)
        except Exception as exc: result[code] = {"ok": False, "message": str(exc)}
    return result


def get_module_status() -> List[Dict[str, Any]]:
    ensure_dirs()
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    authority_rows = []
    if _is_pg():
        try:
            from services.neon_authority_service import authority_status
            authority_rows = authority_status().get("rows", [])
        except Exception:
            authority_rows = []
    auth_map = {(str(r.get("module_key")), str(r.get("kind"))): r for r in authority_rows if isinstance(r, dict)}
    for raw_code, info in MODULE_TABLE_MAP.items():
        code = normalize_module_code(raw_code)
        if code in seen: continue
        seen.add(code)
        counts = {}
        for table in info.get("tables", []):
            try:
                if _is_pg():
                    from services.db_service import query_one
                    q = query_one(f"SELECT COUNT(*) AS c FROM {table}") or {}
                    counts[table] = int(q.get("c") or 0)
                elif DB_PATH.exists():
                    with connect_db() as conn: counts[table] = table_count(conn, table)
                else:
                    counts[table] = 0
            except Exception:
                counts[table] = 0
        rec_meta = auth_map.get((code, "records"), {})
        set_meta = auth_map.get((code, "settings"), {})
        rows.append({
            "模組代碼 / Module Code": code,
            "模組 / Module": f'{info["name_zh"]} / {info["name_en"]}',
            "紀錄檔 / Records Exists": bool(_is_pg() or latest_records_path(code).exists()),
            "設定檔 / Settings Exists": bool(_is_pg() or latest_settings_path(code).exists()),
            "紀錄時間 / Exported At": rec_meta.get("updated_at", "Neon live table" if _is_pg() else ""),
            "設定時間 / Settings At": set_meta.get("updated_at", ""),
            "資料筆數 / Counts": json.dumps(counts, ensure_ascii=False),
            "路徑 / Path": f"neon://{','.join(info.get('tables', []))}" if _is_pg() else str(module_dir(code).relative_to(PROJECT_ROOT)),
            "檢查說明 / Health Note": "Neon/PostgreSQL single source" if _is_pg() else "Local fallback",
            "設定路徑 / Settings Path": f"neon://spt_module_authority/{code}/settings" if _is_pg() else str(latest_settings_path(code).relative_to(PROJECT_ROOT)),
        })
    return rows


def save_module_settings(module_code: str, settings: Dict[str, Any], username: str = "SYSTEM", write_history: bool = True) -> Dict[str, Any]:
    ensure_dirs()
    code = normalize_module_code(module_code)
    info = MODULE_TABLE_MAP.get(code, {"name_zh": code, "name_en": code})
    payload = {"schema_version": "neon-v31", "saved_at": _now(), "module_code": code, "module_name_zh": info.get("name_zh", code), "module_name_en": info.get("name_en", code), "settings": settings, "backend": "neon" if _is_pg() else "local"}
    if _is_pg():
        from services.neon_authority_service import save_payload
        save_payload(code, "settings", payload, username)
    else:
        save_json(latest_settings_path(code), payload)
        if write_history: save_json(history_settings_path(code), payload)
    append_audit(code, "SAVE_SETTINGS", username, {"keys": list(settings.keys())})
    rebuild_global_index()
    return payload


def load_module_settings(module_code: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    code = normalize_module_code(module_code)
    if _is_pg():
        try:
            from services.neon_authority_service import load_payload
            payload = load_payload(code, "settings", {}) or {}
            if isinstance(payload, dict) and payload.get("settings") is not None:
                return payload.get("settings", {})
            return payload if isinstance(payload, dict) else (default or {})
        except Exception:
            return default or {}
    payload = load_json(latest_settings_path(code), {}) or {}
    if payload.get("settings") is not None: return payload.get("settings", {})
    return default or {}


def rebuild_global_index() -> Dict[str, Any]:
    ensure_dirs()
    index = {"schema_version": "neon-v31", "updated_at": _now(), "root": "neon://spt_module_authority" if _is_pg() else str(PERSIST_ROOT.relative_to(PROJECT_ROOT)), "backend": "neon" if _is_pg() else "local", "modules": {}}
    for code, info in MODULE_TABLE_MAP.items():
        ncode = normalize_module_code(code)
        index["modules"][ncode] = {"name_zh": info["name_zh"], "name_en": info["name_en"], "records_path": f"neon://{ncode}/records" if _is_pg() else str(latest_records_path(ncode).relative_to(PROJECT_ROOT)), "settings_path": f"neon://{ncode}/settings" if _is_pg() else str(latest_settings_path(ncode).relative_to(PROJECT_ROOT)), "audit_path": "neon://spt_module_authority_audit" if _is_pg() else str(latest_audit_path(ncode).relative_to(PROJECT_ROOT)), "records_exists": True, "settings_exists": True, "audit_exists": True}
    if _is_pg():
        try:
            from services.neon_authority_service import save_system_payload
            save_system_payload("spt_module_independent_state.json", index)
            save_system_payload("spt_module_independent_settings.json", {"schema_version": "neon-v31", "updated_at": _now(), "modules": {code: f"neon://{normalize_module_code(code)}/settings" for code in MODULE_TABLE_MAP}})
        except Exception:
            pass
    else:
        save_json(GLOBAL_STATE, index)
        save_json(GLOBAL_SETTINGS, {"schema_version": "neon-v31", "updated_at": _now(), "modules": {code: str(latest_settings_path(code).relative_to(PROJECT_ROOT)) for code in MODULE_TABLE_MAP}})
    return index


def bootstrap_module_persistence(username: str = "SYSTEM") -> Dict[str, Any]:
    ensure_dirs()
    index = rebuild_global_index()
    for code in MODULE_TABLE_MAP:
        if not load_module_settings(code, None):
            save_module_settings(code, {"created_by": "neon-v31 bootstrap", "table_columns": {}, "sort": {}, "filters": {}, "ui": {}}, username=username, write_history=False)
    append_audit("09_persistence", "BOOTSTRAP_MODULE_PERSISTENCE", username, {"modules": len(MODULE_TABLE_MAP), "backend": "neon" if _is_pg() else "local"})
    return index


def protect_gitignore_rules() -> None:
    # No-op in Neon mode; kept for old page compatibility.
    return None

if __name__ == "__main__":
    bootstrap_module_persistence()
    print("Module persistence bootstrap completed.")
