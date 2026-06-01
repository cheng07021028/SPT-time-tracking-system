# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.48 - Auto GitHub Sync Service

目的：
- 每次按下「儲存 / 套用」造成 SQLite 寫入後，自動建立永久檔並上傳 GitHub。
- 每個模組有獨立 records / settings / audit 檔案。
- 永不讓空資料覆蓋 GitHub 上已有資料的永久檔。
- 使用 GitHub Contents API，不用 git push，不需要 SSH key。

設計：
1. local first：先寫本機永久 JSON。
2. cloud second：若 GITHUB_TOKEN 已設定，再上傳 latest + timestamp history。
3. safe guard：核心主資料空白時，不覆蓋 latest business state。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state"
STATE_HISTORY_DIR = STATE_DIR / "history"
MODULE_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules"
SYNC_STATUS_PATH = STATE_DIR / "spt_auto_sync_status.json"

LATEST_STATE = STATE_DIR / "spt_permanent_state.json"
LATEST_SETTINGS = STATE_DIR / "spt_module_settings.json"

BUSINESS_TABLES = ["work_orders", "employees", "time_records"]
LOGIN_LOG_TABLES = ["auth_login_logs", "security_login_logs", "login_logs"]

# 模組代碼、名稱與對應資料表。可容忍資料表不存在。
MODULE_TABLES: Dict[str, Dict[str, Any]] = {
    "01_time_records": {
        "module_code": "01",
        "module_name_zh": "工時紀錄",
        "module_name_en": "Time Records",
        "records": ["time_records"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings", "system_settings"],
    },
    "02_history": {
        "module_code": "02",
        "module_name_zh": "歷史紀錄",
        "module_name_en": "History",
        "records": ["time_records"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "03_work_orders": {
        "module_code": "03",
        "module_name_zh": "製令管理",
        "module_name_en": "Work Orders",
        "records": ["work_orders"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "04_employees": {
        "module_code": "04",
        "module_name_zh": "人員名單",
        "module_name_en": "Employees",
        "records": ["employees"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "05_analysis": {
        "module_code": "05",
        "module_name_zh": "製令工時分析",
        "module_name_en": "Work Order Analysis",
        "records": ["time_records", "work_orders", "employees"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "06_system_logs": {
        "module_code": "06",
        "module_name_zh": "LOG查詢",
        "module_name_en": "System Logs",
        "records": ["system_logs"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "07_missing_records": {
        "module_code": "07",
        "module_name_zh": "今日未紀錄名單",
        "module_name_en": "Missing Records",
        "records": ["employees", "time_records"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "08_daily_hours": {
        "module_code": "08",
        "module_name_zh": "人員每日工時",
        "module_name_en": "Daily Hours",
        "records": ["employees", "time_records"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "09_persistence": {
        "module_code": "09",
        "module_name_zh": "資料永久保存與備份",
        "module_name_en": "Persistence",
        "records": [],
        "settings": ["system_settings"],
    },
    "10_permissions": {
        "module_code": "10",
        "module_name_zh": "權限管理",
        "module_name_en": "Permissions",
        "records": ["auth_users", "auth_account_permissions", "auth_security_settings"],
        "settings": ["auth_users", "auth_account_permissions", "auth_security_settings"],
    },
    "11_login_logs": {
        "module_code": "11",
        "module_name_zh": "登入紀錄",
        "module_name_en": "Login Logs",
        "records": ["auth_login_logs", "security_login_logs", "login_logs"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
    "12_module_persistence": {
        "module_code": "12",
        "module_name_zh": "模組永久紀錄中心",
        "module_name_en": "Module Persistence",
        "records": [],
        "settings": ["system_settings"],
    },
    "ui_table_settings": {
        "module_code": "UI",
        "module_name_zh": "表格欄位與排序設定",
        "module_name_en": "Table UI Settings",
        "records": ["table_column_settings", "table_sort_settings"],
        "settings": ["table_column_settings", "table_sort_settings", "table_ui_settings"],
    },
}

# 避免同一個 Streamlit rerun 內連續大量寫入重複推送。latest 仍會儘量更新。
_LAST_SYNC_TS = 0.0
_MIN_SYNC_INTERVAL_SEC = 2.0


def _now() -> str:
    return now_text()


def _stamp() -> str:
    return now_stamp()


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    MODULE_ROOT.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / ".gitkeep").touch(exist_ok=True)
    (STATE_HISTORY_DIR / ".gitkeep").touch(exist_ok=True)
    (MODULE_ROOT / ".gitkeep").touch(exist_ok=True)
    for module_key in MODULE_TABLES:
        d = MODULE_ROOT / module_key
        (d / "history").mkdir(parents=True, exist_ok=True)
        (d / ".gitkeep").touch(exist_ok=True)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return row is not None
    except Exception:
        return False


def _all_tables(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [str(r[0]) for r in rows if not str(r[0]).startswith("sqlite_") and str(r[0]) != "sqlite_sequence"]
    except Exception:
        return []


def _export_table(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    try:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _count_table(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0)
    except Exception:
        return 0


def _business_count_from_tables(tables: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(tables.get(t, []) or []) for t in BUSINESS_TABLES)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _has_token() -> bool:
    try:
        from services.github_cloud_storage_service import github_config
        return bool(github_config().get("token"))
    except Exception:
        return False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _upload_text(remote_path: str, text: str, message: str) -> dict[str, Any]:
    try:
        from services.github_cloud_storage_service import upload_text_to_github
        return upload_text_to_github(remote_path, text, message)
    except Exception as exc:
        return {"ok": False, "message": f"GitHub upload function unavailable: {exc}", "path": remote_path}


def _upload_file(local_path: Path, remote_path: str, message: str) -> dict[str, Any]:
    try:
        text = local_path.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "message": f"讀取檔案失敗：{exc}", "path": str(local_path)}
    return _upload_text(remote_path, text, message)


def export_all_local_permanent_files(force: bool = False, source: str = "manual") -> dict[str, Any]:
    """Create local latest + module independent JSON files.

    force=False 時，若目前核心主資料為 0，會避免覆蓋 latest business state；
    但仍會保存設定檔，避免權限/欄位設定遺失。
    """
    _ensure_dirs()
    stamp = _stamp()
    if not DB_PATH.exists():
        return {"ok": False, "message": "SQLite DB not found", "db_path": str(DB_PATH)}

    conn = _connect()
    try:
        all_tables = _all_tables(conn)
        tables = {t: _export_table(conn, t) for t in all_tables}
        table_counts = {t: len(rows) for t, rows in tables.items()}
        business_count = _business_count_from_tables(tables)

        old_state = _read_json(LATEST_STATE)
        old_business_count = int(old_state.get("business_row_count") or _business_count_from_tables(old_state.get("tables", {}) if isinstance(old_state.get("tables"), dict) else {}))

        state_payload = {
            "version": "V1.48",
            "exported_at": _now(),
            "source": source,
            "db_path": str(DB_PATH),
            "business_row_count": business_count,
            "table_counts": table_counts,
            "tables": tables,
        }

        # 設定檔獨立保存：即使主資料是 0，權限/欄位/安全設定也要保存。
        setting_tables = [
            "system_settings", "table_column_settings", "table_sort_settings", "table_ui_settings",
            "process_categories", "process_category_options", "process_options", "rest_periods", "app_settings",
            "auth_users", "auth_account_permissions", "auth_security_settings",
            "security_users", "security_roles", "security_user_roles", "security_module_permissions", "security_settings",
        ]
        settings_payload = {
            "version": "V1.48",
            "exported_at": _now(),
            "source": source,
            "tables": {t: tables.get(t, []) for t in setting_tables if t in tables},
            "table_counts": {t: table_counts.get(t, 0) for t in setting_tables if t in tables},
        }

        wrote_latest_state = False
        skipped_latest_state = False
        if business_count > 0 or force or old_business_count == 0:
            _write_json(LATEST_STATE, state_payload)
            _write_json(STATE_HISTORY_DIR / f"spt_permanent_state_{stamp}.json", state_payload)
            wrote_latest_state = True
        else:
            # 避免空主資料覆蓋 GitHub 上曾經有資料的 latest。
            skipped_latest_state = True

        _write_json(LATEST_SETTINGS, settings_payload)
        _write_json(STATE_HISTORY_DIR / f"spt_module_settings_{stamp}.json", settings_payload)

        module_results: list[dict[str, Any]] = []
        for module_key, spec in MODULE_TABLES.items():
            module_dir = MODULE_ROOT / module_key
            history_dir = module_dir / "history"
            module_dir.mkdir(parents=True, exist_ok=True)
            history_dir.mkdir(parents=True, exist_ok=True)

            rec_tables = list(dict.fromkeys(spec.get("records", [])))
            set_tables = list(dict.fromkeys(spec.get("settings", [])))
            rec_payload = {
                "version": "V1.48",
                "exported_at": _now(),
                "source": source,
                "module_key": module_key,
                "module_code": spec.get("module_code", ""),
                "module_name_zh": spec.get("module_name_zh", ""),
                "module_name_en": spec.get("module_name_en", ""),
                "tables": {t: tables.get(t, []) for t in rec_tables if t in tables},
                "table_counts": {t: table_counts.get(t, 0) for t in rec_tables if t in tables},
            }
            set_payload = {
                "version": "V1.48",
                "exported_at": _now(),
                "source": source,
                "module_key": module_key,
                "module_code": spec.get("module_code", ""),
                "module_name_zh": spec.get("module_name_zh", ""),
                "module_name_en": spec.get("module_name_en", ""),
                "tables": {t: tables.get(t, []) for t in set_tables if t in tables},
                "table_counts": {t: table_counts.get(t, 0) for t in set_tables if t in tables},
            }
            rec_path = module_dir / f"{module_key}_records.json"
            set_path = module_dir / f"{module_key}_settings.json"
            _write_json(rec_path, rec_payload)
            _write_json(set_path, set_payload)
            _write_json(history_dir / f"{module_key}_records_{stamp}.json", rec_payload)
            _write_json(history_dir / f"{module_key}_settings_{stamp}.json", set_payload)
            module_results.append({"module": module_key, "records": str(rec_path), "settings": str(set_path), "counts": rec_payload["table_counts"]})

        status = {
            "ok": True,
            "version": "V1.48",
            "updated_at": _now(),
            "source": source,
            "business_row_count": business_count,
            "table_counts": table_counts,
            "wrote_latest_state": wrote_latest_state,
            "skipped_latest_state": skipped_latest_state,
            "latest_state": str(LATEST_STATE),
            "latest_settings": str(LATEST_SETTINGS),
            "module_results": module_results,
        }
        _write_json(SYNC_STATUS_PATH, status)
        return status
    finally:
        conn.close()


def upload_all_permanent_files_to_github(archive: bool = True, source: str = "manual") -> dict[str, Any]:
    """Upload latest permanent files and module independent files to GitHub.

    history 檔案用時間戳命名，不會覆蓋舊資料。
    """
    _ensure_dirs()
    stamp = _stamp()
    if not _has_token():
        return {"ok": False, "message": "GITHUB_TOKEN not configured", "uploads": []}

    uploads: list[dict[str, Any]] = []

    # latest state / settings
    if LATEST_STATE.exists():
        uploads.append(_upload_file(LATEST_STATE, "data/permanent_store/persistent_state/spt_permanent_state.json", f"SPT auto sync latest state {stamp}"))
        if archive:
            uploads.append(_upload_file(LATEST_STATE, f"data/permanent_store/persistent_state/history/spt_permanent_state_{stamp}.json", f"SPT auto sync state history {stamp}"))
    if LATEST_SETTINGS.exists():
        uploads.append(_upload_file(LATEST_SETTINGS, "data/permanent_store/persistent_state/spt_module_settings.json", f"SPT auto sync latest settings {stamp}"))
        if archive:
            uploads.append(_upload_file(LATEST_SETTINGS, f"data/permanent_store/persistent_state/history/spt_module_settings_{stamp}.json", f"SPT auto sync settings history {stamp}"))

    # independent module latest + history
    for module_key in MODULE_TABLES:
        module_dir = MODULE_ROOT / module_key
        rec_path = module_dir / f"{module_key}_records.json"
        set_path = module_dir / f"{module_key}_settings.json"
        if rec_path.exists():
            uploads.append(_upload_file(rec_path, f"data/permanent_store/persistent_modules/{module_key}/{module_key}_records.json", f"SPT auto sync {module_key} records {stamp}"))
            if archive:
                uploads.append(_upload_file(rec_path, f"data/permanent_store/persistent_modules/{module_key}/history/{module_key}_records_{stamp}.json", f"SPT auto sync {module_key} records history {stamp}"))
        if set_path.exists():
            uploads.append(_upload_file(set_path, f"data/permanent_store/persistent_modules/{module_key}/{module_key}_settings.json", f"SPT auto sync {module_key} settings {stamp}"))
            if archive:
                uploads.append(_upload_file(set_path, f"data/permanent_store/persistent_modules/{module_key}/history/{module_key}_settings_{stamp}.json", f"SPT auto sync {module_key} settings history {stamp}"))

    ok = bool(uploads) and all(bool(u.get("ok")) for u in uploads)
    status = _read_json(SYNC_STATUS_PATH)
    status.update({
        "last_github_upload_at": _now(),
        "last_github_upload_source": source,
        "last_github_upload_ok": ok,
        "last_github_upload_count": len(uploads),
        "last_github_upload_errors": [u for u in uploads if not u.get("ok")][:10],
    })
    _write_json(SYNC_STATUS_PATH, status)
    return {"ok": ok, "uploads": uploads, "upload_count": len(uploads), "status_path": str(SYNC_STATUS_PATH)}


def auto_sync_after_write(source: str = "db_write", force: bool = False, archive: bool = True) -> dict[str, Any]:
    """Called from db_service._after_write.

    預設會：
    1. 匯出本機永久檔。
    2. 若 Token 已設定，立即上傳到 GitHub。

    為避免同一秒大量 execute 造成 GitHub API 過載，2 秒內重複呼叫會只做本機永久檔，略過 GitHub。
    """
    global _LAST_SYNC_TS
    local = export_all_local_permanent_files(force=force, source=source)
    if not local.get("ok"):
        return {"ok": False, "local": local, "cloud": {"ok": False, "message": "local export failed"}}

    now_ts = time.time()
    if not force and now_ts - _LAST_SYNC_TS < _MIN_SYNC_INTERVAL_SEC:
        return {"ok": True, "local": local, "cloud": {"ok": True, "skipped": True, "message": "GitHub upload throttled; local permanent files updated."}}

    if not _has_token():
        return {"ok": True, "local": local, "cloud": {"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured; local permanent files updated."}}

    cloud = upload_all_permanent_files_to_github(archive=archive, source=source)
    if cloud.get("ok"):
        _LAST_SYNC_TS = now_ts
    return {"ok": bool(cloud.get("ok")), "local": local, "cloud": cloud}


def sync_status() -> dict[str, Any]:
    status = _read_json(SYNC_STATUS_PATH)
    return {
        "status_path": str(SYNC_STATUS_PATH),
        "latest_state_exists": LATEST_STATE.exists(),
        "latest_settings_exists": LATEST_SETTINGS.exists(),
        "github_token_set": _has_token(),
        **status,
    }
