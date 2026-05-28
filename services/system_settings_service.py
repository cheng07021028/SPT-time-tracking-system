# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - System Settings Service V2.09

集中管理：
1. 工段名稱下拉選單（供 01 工時紀錄使用）
2. 休息時間設定（供工時計算扣除休息使用）
3. 01 工時紀錄每日重新整理時間

V2.09 修正重點：
- 13｜系統設定不再只依賴 SQLite。
- 每次套用工段、休息時間、01 顯示重新整理時間時，都會立即寫入獨立永久設定檔。
- Streamlit / GitHub 更新後，如果 SQLite 被重建，會優先從永久設定檔還原，再決定是否建立系統預設值。
- 永久設定檔路徑：
  data/config/system_settings.json
  data/persistent_state/spt_system_settings.json
  data/persistent_modules/13_system_settings/system_settings.json
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    import streamlit as st  # type: ignore
except Exception:  # pragma: no cover - Streamlit may be unavailable during compile/tests
    st = None  # type: ignore

from services.timezone_service import now_text, now_stamp, today_text, today_date

from .db_service import execute, query_df, query_one, mark_data_changed
from .log_service import write_log

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_SETTINGS_FILES = [
    PROJECT_ROOT / "data" / "config" / "system_settings.json",
    PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json",
    PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "system_settings.json",
]
SYSTEM_SETTINGS_HISTORY_DIR = PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "history"

DEFAULT_PROCESS_OPTIONS = [
    "前置鈑金", "LP改造", "骨架組立", "配電", "模組", "水平", "S.T.", "清潔", "收機", "包機",
    "Packing", "異常", "設變", "重工", "教育訓練", "IPQC", "其他",
]

DEFAULT_REST_PERIODS = [
    {"name": "上午休息", "start_time": "10:30", "end_time": "10:45", "is_active": 1, "sort_order": 1},
    {"name": "午休", "start_time": "12:00", "end_time": "13:00", "is_active": 1, "sort_order": 2},
    {"name": "下午休息", "start_time": "15:00", "end_time": "15:15", "is_active": 1, "sort_order": 3},
    {"name": "晚餐休息", "start_time": "18:00", "end_time": "18:30", "is_active": 1, "sort_order": 4},
    {"name": "晚上休息", "start_time": "20:00", "end_time": "20:15", "is_active": 1, "sort_order": 5},
]

DEFAULT_LIVE_PAGE_RESET_TIME = "02:00"
_LIVE_PAGE_RESET_TIME_CACHE: str | None = None

_SYSTEM_SETTINGS_SCHEMA_READY = False
_PROCESS_OPTIONS_CACHE: list[str] | None = None
_RESTORE_FROM_FILE_DONE = False
_REMOTE_SETTINGS_RESTORE_CHECKED = False


def _now() -> str:
    return now_text()


def _valid_hhmm(value: str) -> bool:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return False
    try:
        h = int(parts[0]); m = int(parts[1])
    except Exception:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def _normalize_hhmm(value: str) -> str:
    text = str(value or "").strip()
    h, m = [int(x) for x in text.split(":")[:2]]
    return f"{h:02d}:{m:02d}"


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (datetime, time)):
        return value.isoformat()
    return value


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        records.append({str(k): _json_safe(v) for k, v in row.items()})
    return records


def _row_get(row: Any, *keys: str, default: Any = "") -> Any:
    """Read a value by internal or displayed bilingual column name."""
    try:
        for key in keys:
            if key in row:
                val = row.get(key)
                if val is not None and str(val).lower() != "nan":
                    return val
        normalized = {str(k).strip().lower(): k for k in getattr(row, "keys", lambda: [])()}
        for key in keys:
            real = normalized.get(str(key).strip().lower())
            if real is not None:
                val = row.get(real)
                if val is not None and str(val).lower() != "nan":
                    return val
    except Exception:
        pass
    return default


def _ensure_permanent_dirs() -> None:
    for p in SYSTEM_SETTINGS_FILES:
        p.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_SETTINGS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON safely so 13｜系統設定不會因中斷寫檔變壞檔。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text, encoding="utf-8")
    # Validate before replace.
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _payload_has_useful_settings(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    tables = data.get("tables") if isinstance(data, dict) else None
    if not isinstance(tables, dict):
        return any(k in data for k in ("process_options", "rest_periods", "app_settings"))
    return any(isinstance(tables.get(k), list) and len(tables.get(k, [])) > 0 for k in ("process_options", "rest_periods", "app_settings"))


def _normalize_persistent_payload(data: dict[str, Any]) -> dict[str, Any]:
    tables = data.get("tables")
    if isinstance(tables, dict):
        return data
    return {"tables": {
        "process_options": data.get("process_options", []),
        "rest_periods": data.get("rest_periods", []),
        "app_settings": data.get("app_settings", []),
    }}


def _load_latest_persistent_payload() -> dict[str, Any] | None:
    """Read 13｜系統設定 from canonical permanent files first.

    舊版用 mtime 找最新檔，history 裡若留下預設值，更新模組後可能反而讀到
    較新的預設紀錄，造成畫面回復原始設定。
    新規則：先讀固定永久檔，再把 history 當最後救援來源。
    """
    global _REMOTE_SETTINGS_RESTORE_CHECKED

    # 1) Canonical permanent files are the authoritative records.
    for p in SYSTEM_SETTINGS_FILES:
        data = _load_json_file(p)
        if _payload_has_useful_settings(data):
            return _normalize_persistent_payload(data or {})

    # 1.5) Important: do NOT contact GitHub here.
    # This function can be called while rendering the login page or importing pages.
    # Network I/O during boot/login caused the app to keep running indefinitely.
    # GitHub restore is now manual from 13｜系統設定, or handled by explicit backup actions.

    # 2) History is fallback only, newest first.
    if SYSTEM_SETTINGS_HISTORY_DIR.exists():
        for p in sorted(SYSTEM_SETTINGS_HISTORY_DIR.glob("system_settings_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            data = _load_json_file(p)
            if _payload_has_useful_settings(data):
                return _normalize_persistent_payload(data or {})
    return None

def _clear_settings_cache() -> None:
    global _PROCESS_OPTIONS_CACHE, _LIVE_PAGE_RESET_TIME_CACHE
    _PROCESS_OPTIONS_CACHE = None
    _LIVE_PAGE_RESET_TIME_CACHE = None
    try:
        from .calculation_service import clear_rest_periods_cache
        clear_rest_periods_cache()
    except Exception:
        pass


def _basic_create_tables() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS rest_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            note TEXT,
            updated_at TEXT
        )
        """
    )


def _table_count(table_name: str) -> int:
    try:
        row = query_one(f"SELECT COUNT(*) AS c FROM {table_name}") or {"c": 0}
        return int(row.get("c") or 0)
    except Exception:
        return 0



def _norm_time_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if ":" in text:
            parts = text.split(":")
            h = int(float(parts[0]))
            m = int(float(parts[1]))
            return f"{h:02d}:{m:02d}"
    except Exception:
        pass
    return text


def _dedupe_rest_periods() -> int:
    """Merge duplicate rest-period rows.

    V2.32: 13｜系統設定曾因預設值、永久檔還原、手動套用重複導致
    「二、休息時間設定」出現相同資料兩次。這裡以
    name + start_time + end_time 為唯一邏輯鍵，只保留最早 id，並把啟用與排序資訊合併。
    """
    try:
        df = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        return 0
    if df is None or df.empty or "id" not in df.columns:
        return 0
    keep: dict[tuple[str, str, str], dict[str, Any]] = {}
    remove_ids: list[int] = []
    for _, r in df.iterrows():
        try:
            rid = int(float(r.get("id")))
        except Exception:
            continue
        name = str(r.get("name") or "").strip()
        start = _norm_time_key(r.get("start_time"))
        end = _norm_time_key(r.get("end_time"))
        if not start or not end:
            continue
        key = (name, start, end)
        active = 1 if str(r.get("is_active", 1)).strip().lower() not in {"0", "false", "no", "n", "off", "停用", "否"} else 0
        try:
            sort_order = int(float(r.get("sort_order") or rid))
        except Exception:
            sort_order = rid
        if key not in keep:
            keep[key] = {"id": rid, "is_active": active, "sort_order": sort_order}
        else:
            target = keep[key]
            remove_ids.append(rid)
            target["is_active"] = max(int(target.get("is_active", 0)), active)
            target["sort_order"] = min(int(target.get("sort_order", sort_order)), sort_order)
    for key, info in keep.items():
        try:
            execute(
                "UPDATE rest_periods SET is_active=?, sort_order=? WHERE id=?",
                (int(info["is_active"]), int(info["sort_order"]), int(info["id"])),
            )
        except Exception:
            pass
    deleted = 0
    for rid in remove_ids:
        try:
            execute("DELETE FROM rest_periods WHERE id=?", (rid,))
            deleted += 1
        except Exception:
            pass
    if deleted:
        _clear_settings_cache()
        try:
            write_log("DEDUP_REST_PERIODS", f"自動合併重複休息時間設定 {deleted} 筆", "rest_periods", level="WARN")
        except Exception:
            pass
    return deleted

def _has_live_page_reset_setting() -> bool:
    try:
        row = query_one("SELECT setting_value FROM app_settings WHERE setting_key='live_page_reset_time'")
        return bool(row and str(row.get("setting_value") or "").strip())
    except Exception:
        return False


def _insert_process_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    now = _now()
    for idx, r in enumerate(rows or [], start=1):
        name = str(r.get("process_name") or r.get("name") or "").strip()
        if not name:
            continue
        try:
            is_active = int(float(r.get("is_active", 1) if r.get("is_active", 1) is not None else 1))
        except Exception:
            is_active = 1
        try:
            sort_order = int(float(_row_get(r, "sort_order", "排序 / Sort", "排序", "Sort", default=idx) or idx))
        except Exception:
            sort_order = idx
        note = str(r.get("note") or "")
        created_at = str(r.get("created_at") or now)
        updated_at = str(r.get("updated_at") or now)
        execute(
            """
            INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(process_name) DO UPDATE SET
                is_active=excluded.is_active,
                sort_order=excluded.sort_order,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (name, is_active, sort_order, note, created_at, updated_at),
        )
        count += 1
    return count


def _insert_rest_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    for idx, r in enumerate(rows or [], start=1):
        name = str(r.get("name") or f"休息{idx}").strip()
        start_time = str(r.get("start_time") or "").strip()
        end_time = str(r.get("end_time") or "").strip()
        if not start_time or not end_time:
            continue
        try:
            is_active = int(float(r.get("is_active", 1) if r.get("is_active", 1) is not None else 1))
        except Exception:
            is_active = 1
        try:
            sort_order = int(float(_row_get(r, "sort_order", "排序 / Sort", "排序", "Sort", default=idx) or idx))
        except Exception:
            sort_order = idx
        existing = query_one(
            "SELECT id FROM rest_periods WHERE name=? AND start_time=? AND end_time=? LIMIT 1",
            (name, start_time, end_time),
        )
        if existing and existing.get("id"):
            execute(
                "UPDATE rest_periods SET is_active=?, sort_order=? WHERE id=?",
                (is_active, sort_order, int(existing.get("id"))),
            )
        else:
            execute(
                """
                INSERT INTO rest_periods(name, start_time, end_time, is_active, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, start_time, end_time, is_active, sort_order),
            )
        count += 1
    return count


def _insert_app_settings_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    now = _now()
    for r in rows or []:
        key = str(r.get("setting_key") or "").strip()
        if not key:
            continue
        value = str(r.get("setting_value") or "").strip()
        note = str(r.get("note") or "")
        updated_at = str(r.get("updated_at") or now)
        execute(
            """
            INSERT INTO app_settings(setting_key, setting_value, note, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value=excluded.setting_value,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (key, value, note, updated_at),
        )
        count += 1
    return count


def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:
    """Restore 13｜系統設定 from permanent JSON.

    force=False: only fills missing/empty setting tables. This prevents normal page
    loads from overwriting active SQLite data.
    """
    _basic_create_tables()
    payload = _load_latest_persistent_payload()
    if not payload:
        return {"ok": False, "restored": {}, "message": "找不到 13 系統設定永久檔"}
    tables = payload.get("tables", {}) if isinstance(payload.get("tables"), dict) else {}
    restored: dict[str, int] = {}

    proc_rows = tables.get("process_options", []) if isinstance(tables.get("process_options"), list) else []
    rest_rows = tables.get("rest_periods", []) if isinstance(tables.get("rest_periods"), list) else []
    app_rows = tables.get("app_settings", []) if isinstance(tables.get("app_settings"), list) else []

    if force or (_table_count("process_options") == 0 and proc_rows):
        if force:
            execute("DELETE FROM process_options")
        restored["process_options"] = _insert_process_rows(proc_rows)
    if force or (_table_count("rest_periods") == 0 and rest_rows):
        if force:
            execute("DELETE FROM rest_periods")
        restored["rest_periods"] = _insert_rest_rows(rest_rows)
    if force or (not _has_live_page_reset_setting() and app_rows):
        if force:
            execute("DELETE FROM app_settings WHERE setting_key IN ('live_page_reset_time')")
        restored["app_settings"] = _insert_app_settings_rows(app_rows)

    if restored:
        _clear_settings_cache()
    return {"ok": bool(restored), "restored": restored, "source": "system_settings_json"}


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:
    """Write a dedicated permanent file for 13｜系統設定 immediately."""
    ensure_system_settings_schema()
    _ensure_permanent_dirs()
    try:
        proc = query_df("SELECT id, process_name, is_active, sort_order, note, created_at, updated_at FROM process_options ORDER BY sort_order, id")
    except Exception:
        proc = pd.DataFrame()
    try:
        rest = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        rest = pd.DataFrame()
    try:
        app = query_df("SELECT setting_key, setting_value, note, updated_at FROM app_settings ORDER BY setting_key")
    except Exception:
        app = pd.DataFrame()

    payload: dict[str, Any] = {
        "version": "V2.09",
        "exported_at": _now(),
        "reason": reason,
        "description": "13｜系統設定永久紀錄：工段名稱、休息時間、01 工時紀錄每日重新整理時間。",
        "tables": {
            "process_categories": _df_records(cats),
            "process_options": _df_records(proc),
            "rest_periods": _df_records(rest),
            "app_settings": _df_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
    }
    for p in SYSTEM_SETTINGS_FILES:
        _atomic_write_json(p, payload)
    if write_history:
        hist = SYSTEM_SETTINGS_HISTORY_DIR / f"system_settings_{now_stamp()}.json"
        _atomic_write_json(hist, payload)
    # Do not upload to GitHub automatically from the save path.
    # Auto network sync during normal page loads/saves can freeze login or rerun cycles.
    # Use the explicit buttons in 13｜系統設定 for GitHub upload/download.
    github_sync: dict[str, Any] = {"ok": True, "skipped": True, "message": "GitHub sync skipped on automatic setting export; use 13 manual sync."}

    try:
        mark_data_changed("13｜系統設定已變更，永久設定檔已建立；GitHub 同步請到 13 頁面手動執行。", "system_settings_permanent_json")
    except Exception:
        pass
    return {"ok": True, "files": [str(p) for p in SYSTEM_SETTINGS_FILES], "table_counts": payload["table_counts"], "github_sync": github_sync}


def ensure_system_settings_schema() -> None:
    """Prepare setting tables once without causing repeated backup sync."""
    global _SYSTEM_SETTINGS_SCHEMA_READY, _RESTORE_FROM_FILE_DONE
    if _SYSTEM_SETTINGS_SCHEMA_READY:
        return

    _basic_create_tables()

    # V2.09: Restore user-maintained settings from dedicated JSON before seeding defaults.
    if not _RESTORE_FROM_FILE_DONE:
        try:
            restore_system_settings_from_permanent(force=False)
        except Exception:
            pass
        _RESTORE_FROM_FILE_DONE = True

    now = _now()

    # Seed only when the table is truly empty and no permanent file restored anything.
    try:
        row = query_one("SELECT COUNT(*) AS c FROM process_options") or {"c": 0}
        if int(row.get("c") or 0) == 0:
            for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
                execute(
                    """
                    INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
                    VALUES (?, 1, ?, '系統預設工段，可於 13 系統設定修改', ?, ?)
                    """,
                    (name, idx, now, now),
                )
    except Exception:
        pass

    try:
        row = query_one("SELECT COUNT(*) AS c FROM rest_periods") or {"c": 0}
        if int(row.get("c") or 0) == 0:
            for item in DEFAULT_REST_PERIODS:
                execute(
                    """
                    INSERT INTO rest_periods(name, start_time, end_time, is_active, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item["name"], item["start_time"], item["end_time"], item["is_active"], item["sort_order"]),
                )
    except Exception:
        pass

    try:
        if not _has_live_page_reset_setting():
            execute(
                """
                INSERT INTO app_settings(setting_key, setting_value, note, updated_at)
                VALUES ('live_page_reset_time', ?, '01 工時紀錄每日重新整理時間；只影響 01 顯示，不刪除 02 歷史紀錄', ?)
                ON CONFLICT(setting_key) DO NOTHING
                """,
                (DEFAULT_LIVE_PAGE_RESET_TIME, now),
            )
    except Exception:
        pass

    try:
        _dedupe_rest_periods()
    except Exception:
        pass

    _SYSTEM_SETTINGS_SCHEMA_READY = True


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:
    ensure_system_settings_schema()
    sql = "SELECT id, process_name, is_active, sort_order, note, created_at, updated_at FROM process_options WHERE 1=1"
    params: list = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY sort_order, id"
    return query_df(sql, params)


def get_process_options() -> list[str]:
    global _PROCESS_OPTIONS_CACHE
    if _PROCESS_OPTIONS_CACHE:
        return list(_PROCESS_OPTIONS_CACHE)
    try:
        df = load_process_options_df(active_only=True)
        if df.empty:
            _PROCESS_OPTIONS_CACHE = DEFAULT_PROCESS_OPTIONS.copy()
        else:
            names = [str(x).strip() for x in df["process_name"].dropna().tolist() if str(x).strip()]
            _PROCESS_OPTIONS_CACHE = names or DEFAULT_PROCESS_OPTIONS.copy()
    except Exception:
        _PROCESS_OPTIONS_CACHE = DEFAULT_PROCESS_OPTIONS.copy()
    return list(_PROCESS_OPTIONS_CACHE)


def save_process_options_df(df: pd.DataFrame) -> int:
    ensure_system_settings_schema()
    if df is None:
        return 0
    now = _now()
    count = 0
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(_row_get(r, "process_name", "工段名稱 / Process", "工段名稱", "Process", default="")).strip()
        if not name:
            continue
        active_raw = str(_row_get(r, "is_active", "啟用 / Active", "啟用", "Active", default=True)).strip().lower()
        is_active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(_row_get(r, "sort_order", "排序 / Sort", "排序", "Sort", default=idx) or idx))
        except Exception:
            sort_order = idx
        note = str(_row_get(r, "note", "備註 / Note", "備註", "Note", default="") or "")
        rid = _row_get(r, "id", "ID / ID", "ID", default="")
        if str(rid).strip() and str(rid).strip().lower() not in {"nan", "none"}:
            execute(
                """
                UPDATE process_options
                SET process_name=?, is_active=?, sort_order=?, note=?, updated_at=?
                WHERE id=?
                """,
                (name, is_active, sort_order, note, now, int(float(rid))),
            )
        else:
            execute(
                """
                INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (name, is_active, sort_order, note, now, now),
            )
        count += 1
    _clear_settings_cache()
    export_system_settings_permanent("save_process_options", write_history=True)
    write_log("SAVE_PROCESS_OPTIONS", f"儲存工段名稱設定 {count} 筆，已寫入 13 系統設定永久檔", "process_options")
    return count


def delete_process_options(ids: Iterable[int]) -> int:
    ensure_system_settings_schema()
    count = 0
    for rid in ids or []:
        try:
            i = int(rid)
        except Exception:
            continue
        execute("DELETE FROM process_options WHERE id=?", (i,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_process_options", write_history=True)
        write_log("DELETE_PROCESS_OPTIONS", f"刪除工段名稱設定 {count} 筆，已寫入 13 系統設定永久檔", "process_options", level="WARN")
    return count


def load_rest_periods_df(active_only: bool = False) -> pd.DataFrame:
    ensure_system_settings_schema()
    try:
        _dedupe_rest_periods()
    except Exception:
        pass
    sql = "SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods WHERE 1=1"
    params: list = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY sort_order, id"
    return query_df(sql, params)


def save_rest_periods_df(df: pd.DataFrame) -> int:
    ensure_system_settings_schema()
    if df is None:
        return 0
    count = 0
    seen_keys: set[tuple[str, str, str]] = set()
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(_row_get(r, "name", "名稱 / Name", "休息名稱 / Name", "名稱", "Name", default="")).strip() or f"休息{idx}"
        start_time = _norm_time_key(_row_get(r, "start_time", "開始時間 / Start Time", "開始時間", "Start Time", default=""))
        end_time = _norm_time_key(_row_get(r, "end_time", "結束時間 / End Time", "結束時間", "End Time", default=""))
        if not start_time or not end_time:
            continue
        row_key = (name, start_time, end_time)
        if row_key in seen_keys:
            continue
        seen_keys.add(row_key)
        active_raw = str(_row_get(r, "is_active", "啟用 / Active", "啟用", "Active", default=True)).strip().lower()
        is_active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(_row_get(r, "sort_order", "排序 / Sort", "排序", "Sort", default=idx) or idx))
        except Exception:
            sort_order = idx
        rid = _row_get(r, "id", "ID / ID", "ID", default="")
        if str(rid).strip() and str(rid).strip().lower() not in {"nan", "none"}:
            execute(
                """
                UPDATE rest_periods
                SET name=?, start_time=?, end_time=?, is_active=?, sort_order=?
                WHERE id=?
                """,
                (name, start_time, end_time, is_active, sort_order, int(float(rid))),
            )
        else:
            existing = query_one(
                "SELECT id FROM rest_periods WHERE name=? AND start_time=? AND end_time=? LIMIT 1",
                (name, start_time, end_time),
            )
            if existing and existing.get("id"):
                execute(
                    "UPDATE rest_periods SET is_active=?, sort_order=? WHERE id=?",
                    (is_active, sort_order, int(existing.get("id"))),
                )
            else:
                execute(
                    """
                    INSERT INTO rest_periods(name, start_time, end_time, is_active, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, start_time, end_time, is_active, sort_order),
                )
        count += 1
    try:
        _dedupe_rest_periods()
    except Exception:
        pass
    _clear_settings_cache()
    export_system_settings_permanent("save_rest_periods", write_history=True)
    write_log("SAVE_REST_PERIODS", f"儲存休息時間設定 {count} 筆，已寫入 13 系統設定永久檔", "rest_periods")
    return count


def delete_rest_periods(ids: Iterable[int]) -> int:
    ensure_system_settings_schema()
    count = 0
    for rid in ids or []:
        try:
            i = int(rid)
        except Exception:
            continue
        execute("DELETE FROM rest_periods WHERE id=?", (i,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_rest_periods", write_history=True)
        write_log("DELETE_REST_PERIODS", f"刪除休息時間設定 {count} 筆，已寫入 13 系統設定永久檔", "rest_periods", level="WARN")
    return count


def get_live_page_reset_time() -> str:
    """Return the 01 live work page daily refresh time (HH:MM)."""
    global _LIVE_PAGE_RESET_TIME_CACHE
    if _LIVE_PAGE_RESET_TIME_CACHE:
        return _LIVE_PAGE_RESET_TIME_CACHE
    try:
        ensure_system_settings_schema()
        row = query_one("SELECT setting_value FROM app_settings WHERE setting_key='live_page_reset_time'")
        value = str((row or {}).get("setting_value") or DEFAULT_LIVE_PAGE_RESET_TIME).strip()
        if not _valid_hhmm(value):
            value = DEFAULT_LIVE_PAGE_RESET_TIME
    except Exception:
        value = DEFAULT_LIVE_PAGE_RESET_TIME
    _LIVE_PAGE_RESET_TIME_CACHE = _normalize_hhmm(value)
    return _LIVE_PAGE_RESET_TIME_CACHE


def save_live_page_reset_time(value: str) -> str:
    ensure_system_settings_schema()
    if not _valid_hhmm(value):
        raise ValueError("01 工時紀錄每日清理時間格式錯誤，請使用 HH:MM，例如 02:00。")
    value = _normalize_hhmm(value)
    now = _now()
    execute(
        """
        INSERT INTO app_settings(setting_key, setting_value, note, updated_at)
        VALUES ('live_page_reset_time', ?, '01 工時紀錄每日重新整理時間；只影響 01 顯示，不刪除 02 歷史紀錄', ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (value, now),
    )
    _clear_settings_cache()
    export_system_settings_permanent("save_live_page_reset_time", write_history=True)
    write_log("SAVE_LIVE_PAGE_RESET_TIME", f"儲存 01 工時紀錄每日重新整理時間：{value}，已寫入 13 系統設定永久檔", "app_settings")
    return value


def dedupe_rest_periods() -> int:
    """Public wrapper for 13｜系統設定：合併重複休息時間設定。"""
    ensure_system_settings_schema()
    n = _dedupe_rest_periods()
    if n:
        export_system_settings_permanent("dedupe_rest_periods", write_history=True)
    return n

# =============================================================================
# V3.28 - Model-specific process options
# =============================================================================
PROCESS_MODEL_ALL = "全部 / 通用"
DEFAULT_PROCESS_MODEL_KEY = "default_process_model"


def _ensure_process_model_options_table() -> None:
    """Create model-specific process option table without touching legacy data."""
    ensure_system_settings_schema()
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_model_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT DEFAULT '',
            process_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(type_name, process_name)
        )
        """
    )
    # Migration: seed model-specific table from legacy process_options once.
    try:
        row = query_one("SELECT COUNT(*) AS c FROM process_model_options") or {"c": 0}
        if int(row.get("c") or 0) == 0:
            legacy = query_df("SELECT process_name, is_active, sort_order, note, created_at, updated_at FROM process_options ORDER BY sort_order, id")
            now = _now()
            for _, r in legacy.fillna("").iterrows():
                name = str(r.get("process_name") or "").strip()
                if not name:
                    continue
                execute(
                    """
                    INSERT OR IGNORE INTO process_model_options(type_name, process_name, is_active, sort_order, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        PROCESS_MODEL_ALL,
                        name,
                        int(float(r.get("is_active") or 1)),
                        int(float(r.get("sort_order") or 0)),
                        str(r.get("note") or ""),
                        str(r.get("created_at") or now),
                        str(r.get("updated_at") or now),
                    ),
                )
    except Exception:
        pass


def _norm_model_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "null", "全部", "通用", "all", "common", "*"}:
        return PROCESS_MODEL_ALL
    return text


def load_process_model_choices(include_common: bool = True) -> list[str]:
    """Return model choices from work orders + process mappings."""
    _ensure_process_model_options_table()
    names: set[str] = set()
    if include_common:
        names.add(PROCESS_MODEL_ALL)
    try:
        wo = query_df("SELECT DISTINCT type_name FROM work_orders WHERE COALESCE(type_name,'')<>'' ORDER BY type_name")
        for x in wo.get("type_name", []).dropna().tolist() if not wo.empty else []:
            if str(x).strip():
                names.add(str(x).strip())
    except Exception:
        pass
    try:
        mp = query_df("SELECT DISTINCT type_name FROM process_model_options WHERE COALESCE(type_name,'')<>'' ORDER BY type_name")
        for x in mp.get("type_name", []).dropna().tolist() if not mp.empty else []:
            if str(x).strip():
                names.add(_norm_model_name(x))
    except Exception:
        pass
    default = get_default_process_model()
    if default:
        names.add(default)
    ordered = [PROCESS_MODEL_ALL] if include_common else []
    ordered += sorted([n for n in names if n != PROCESS_MODEL_ALL])
    return ordered


def get_default_process_model() -> str:
    _ensure_process_model_options_table()
    try:
        row = query_one("SELECT setting_value FROM app_settings WHERE setting_key=?", (DEFAULT_PROCESS_MODEL_KEY,)) or {}
        value = str(row.get("setting_value") or "").strip()
        return _norm_model_name(value) if value else PROCESS_MODEL_ALL
    except Exception:
        return PROCESS_MODEL_ALL


def save_default_process_model(type_name: str) -> str:
    _ensure_process_model_options_table()
    model = _norm_model_name(type_name)
    now = _now()
    execute(
        """
        INSERT INTO app_settings(setting_key, setting_value, note, updated_at)
        VALUES (?, ?, '01 工時紀錄：製令機型空白或找不到對應工段時使用的預設機型', ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (DEFAULT_PROCESS_MODEL_KEY, model, now),
    )
    _clear_settings_cache()
    export_system_settings_permanent("save_default_process_model", write_history=True)
    write_log("SAVE_DEFAULT_PROCESS_MODEL", f"儲存預設機型：{model}", "app_settings")
    return model


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    _ensure_process_model_options_table()
    sql = "SELECT id, type_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_model_options WHERE 1=1"
    params: list = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY CASE WHEN type_name=? THEN 0 ELSE 1 END, type_name, sort_order, id"
    params.append(PROCESS_MODEL_ALL)
    df = query_df(sql, params)
    if df.empty:
        # Last-resort legacy fallback.
        legacy = query_df("SELECT id, process_name, is_active, sort_order, note, created_at, updated_at FROM process_options ORDER BY sort_order, id")
        if not legacy.empty:
            legacy.insert(1, "type_name", PROCESS_MODEL_ALL)
        return legacy
    return df


def get_process_options_by_model(type_name: str | None = None, include_common: bool = True) -> list[str]:
    """Return process names for selected model.

    Selection logic:
    1. Exact model rows + common rows.
    2. If no exact model rows, default model rows + common rows.
    3. If still empty, all active rows, then legacy defaults.
    """
    _ensure_process_model_options_table()
    model = _norm_model_name(type_name)
    common_names: list[str] = []
    model_names: list[str] = []

    def _names_for(where_sql: str, params: tuple) -> list[str]:
        try:
            df = query_df(
                f"SELECT process_name FROM process_model_options WHERE COALESCE(is_active,1)=1 AND {where_sql} ORDER BY sort_order, id",
                params,
            )
            return [str(x).strip() for x in df.get("process_name", []).dropna().tolist() if str(x).strip()] if not df.empty else []
        except Exception:
            return []

    if include_common:
        common_names = _names_for("(type_name=? OR COALESCE(type_name,'')='')", (PROCESS_MODEL_ALL,))
    if model and model != PROCESS_MODEL_ALL:
        model_names = _names_for("type_name=?", (model,))

    names = common_names + [n for n in model_names if n not in common_names]
    if names:
        return names

    default_model = get_default_process_model()
    if default_model and default_model not in {PROCESS_MODEL_ALL, model}:
        default_names = _names_for("type_name=?", (default_model,))
        names = common_names + [n for n in default_names if n not in common_names]
        if names:
            return names

    try:
        df = query_df("SELECT process_name FROM process_model_options WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, id")
        names = []
        for x in df.get("process_name", []).dropna().tolist() if not df.empty else []:
            s = str(x).strip()
            if s and s not in names:
                names.append(s)
        if names:
            return names
    except Exception:
        pass
    return DEFAULT_PROCESS_OPTIONS.copy()


def get_process_options() -> list[str]:  # type: ignore[override]
    return get_process_options_by_model(get_default_process_model(), include_common=True)


def save_process_options_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    _ensure_process_model_options_table()
    if df is None:
        return 0
    now = _now()
    count = 0
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(r.get("process_name", r.get("工段名稱", ""))).strip()
        if not name:
            continue
        model = _norm_model_name(r.get("type_name", r.get("機型", PROCESS_MODEL_ALL)))
        active_raw = str(r.get("is_active", r.get("啟用", True))).strip().lower()
        is_active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(r.get("sort_order", r.get("排序", idx)) or idx))
        except Exception:
            sort_order = idx
        note = str(r.get("note", r.get("備註", "")) or "")
        rid = str(r.get("id", "")).strip()
        if rid and rid.lower() not in {"nan", "none"}:
            execute(
                """
                UPDATE process_model_options
                SET type_name=?, process_name=?, is_active=?, sort_order=?, note=?, updated_at=?
                WHERE id=?
                """,
                (model, name, is_active, sort_order, note, now, int(float(rid))),
            )
        else:
            execute(
                """
                INSERT INTO process_model_options(type_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(type_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (model, name, is_active, sort_order, note, now, now),
            )
        count += 1
    _clear_settings_cache()
    export_system_settings_permanent("save_model_process_options", write_history=True)
    write_log("SAVE_PROCESS_OPTIONS", f"儲存機型對應工段設定 {count} 筆，已寫入 13 系統設定永久檔", "process_model_options")
    return count


def delete_process_options(ids: Iterable[int]) -> int:  # type: ignore[override]
    _ensure_process_model_options_table()
    count = 0
    for rid in ids or []:
        try:
            i = int(float(rid))
        except Exception:
            continue
        execute("DELETE FROM process_model_options WHERE id=?", (i,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_model_process_options", write_history=True)
        write_log("DELETE_PROCESS_OPTIONS", f"刪除機型對應工段設定 {count} 筆，已寫入 13 系統設定永久檔", "process_model_options", level="WARN")
    return count


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """Write 13｜系統設定 permanent files, including model-specific process mappings.

    V3.30 merge rule:
    - Keep V3.28 model-specific process options used by 01｜工時紀錄.
    - Keep V3.29 GitHub critical-settings sync and atomic JSON save.
    """
    ensure_system_settings_schema()
    _ensure_process_model_options_table()
    _ensure_permanent_dirs()
    try:
        proc = query_df("SELECT id, type_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_model_options ORDER BY type_name, sort_order, id")
    except Exception:
        proc = pd.DataFrame()
    try:
        rest = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        rest = pd.DataFrame()
    try:
        app = query_df("SELECT setting_key, setting_value, note, updated_at FROM app_settings ORDER BY setting_key")
    except Exception:
        app = pd.DataFrame()
    payload: dict[str, Any] = {
        "version": "V3.30",
        "exported_at": _now(),
        "reason": reason,
        "description": "13｜系統設定永久紀錄：機型對應工段名稱、休息時間、01 工時紀錄每日重新整理時間。",
        "tables": {
            "process_categories": _df_records(cats),
            "process_options": _df_records(proc),
            "rest_periods": _df_records(rest),
            "app_settings": _df_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
    }
    for out_path in SYSTEM_SETTINGS_FILES:
        _atomic_write_json(out_path, payload)
    if write_history:
        hist = SYSTEM_SETTINGS_HISTORY_DIR / f"system_settings_{now_stamp()}.json"
        _atomic_write_json(hist, payload)

    # Do not upload to GitHub automatically from the save path.
    # Auto network sync during normal page loads/saves can freeze login or rerun cycles.
    # Use the explicit buttons in 13｜系統設定 for GitHub upload/download.
    github_sync: dict[str, Any] = {"ok": True, "skipped": True, "message": "GitHub sync skipped on automatic setting export; use 13 manual sync."}

    try:
        mark_data_changed("13｜系統設定已變更，永久設定檔已建立；GitHub 同步請到 13 頁面手動執行。", "system_settings_permanent_json")
    except Exception:
        pass
    return {"ok": True, "files": [str(p) for p in SYSTEM_SETTINGS_FILES], "table_counts": payload["table_counts"], "github_sync": github_sync, "payload_version": "V3.30"}



# =============================================================================
# V3.33 - Category-specific process options (replaces UI use of model-specific process mapping)
# =============================================================================
PROCESS_CATEGORY_ALL = "全部 / 通用"
DEFAULT_PROCESS_CATEGORY_KEY = "default_process_category"


def _norm_category_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "null", "全部", "通用", "all", "common", "*"}:
        return PROCESS_CATEGORY_ALL
    return text


def _ensure_process_category_options_table() -> None:
    """Create category-specific process option table and seed without deleting old data.

    V3.33 requirement:
    - 13｜系統設定使用「類別 / Category」設定工段。
    - 01｜工時紀錄使用「類別 / Category」下拉連動工段。
    - 保留 V3.28 model table for compatibility, but UI and new saves use category table.
    """
    ensure_system_settings_schema()
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_category_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT DEFAULT '',
            process_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(category_name, process_name)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    now = _now()

    # Always keep common category available.
    execute(
        """
        INSERT OR IGNORE INTO process_categories(category_name, is_active, sort_order, note, created_at, updated_at)
        VALUES (?, 1, 0, '所有類別共用工段', ?, ?)
        """,
        (PROCESS_CATEGORY_ALL, now, now),
    )

    try:
        existing = query_df("SELECT DISTINCT category_name FROM process_category_options WHERE COALESCE(category_name,'')<>''")
        for name in existing.get("category_name", []).dropna().tolist() if existing is not None and not existing.empty else []:
            cat = _norm_category_name(name)
            execute(
                """
                INSERT OR IGNORE INTO process_categories(category_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, 1, 999, '', ?, ?)
                """,
                (cat, now, now),
            )
    except Exception:
        pass

    try:
        row = query_one("SELECT COUNT(*) AS c FROM process_category_options") or {"c": 0}
        if int(row.get("c") or 0) != 0:
            return
    except Exception:
        return

    seeded = 0
    # Prefer previous V3.28 model process mapping, reinterpreting type_name as category_name.
    try:
        old = query_df("SELECT type_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_model_options ORDER BY type_name, sort_order, id")
        for _, r in old.fillna("").iterrows() if old is not None and not old.empty else []:
            name = str(r.get("process_name") or "").strip()
            if not name:
                continue
            execute(
                """
                INSERT OR IGNORE INTO process_category_options(category_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _norm_category_name(r.get("type_name")),
                    name,
                    int(float(r.get("is_active") or 1)),
                    int(float(r.get("sort_order") or 0)),
                    str(r.get("note") or ""),
                    str(r.get("created_at") or now),
                    str(r.get("updated_at") or now),
                ),
            )
            seeded += 1
    except Exception:
        pass

    if seeded:
        return

    # Legacy fallback: process_options -> common category.
    try:
        legacy = query_df("SELECT process_name, is_active, sort_order, note, created_at, updated_at FROM process_options ORDER BY sort_order, id")
        for _, r in legacy.fillna("").iterrows() if legacy is not None and not legacy.empty else []:
            name = str(r.get("process_name") or "").strip()
            if not name:
                continue
            execute(
                """
                INSERT OR IGNORE INTO process_category_options(category_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROCESS_CATEGORY_ALL,
                    name,
                    int(float(r.get("is_active") or 1)),
                    int(float(r.get("sort_order") or 0)),
                    str(r.get("note") or ""),
                    str(r.get("created_at") or now),
                    str(r.get("updated_at") or now),
                ),
            )
    except Exception:
        pass


def load_process_category_choices(include_common: bool = True) -> list[str]:
    _ensure_process_category_options_table()
    names: set[str] = set()
    if include_common:
        names.add(PROCESS_CATEGORY_ALL)
    try:
        cat_df = query_df("SELECT category_name FROM process_categories WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, id")
        for x in cat_df.get("category_name", []).dropna().tolist() if cat_df is not None and not cat_df.empty else []:
            names.add(_norm_category_name(x))
    except Exception:
        pass
    try:
        df = query_df("SELECT DISTINCT category_name FROM process_category_options WHERE COALESCE(category_name,'')<>'' ORDER BY category_name")
        for x in df.get("category_name", []).dropna().tolist() if df is not None and not df.empty else []:
            names.add(_norm_category_name(x))
    except Exception:
        pass
    default = get_default_process_category()
    if default:
        names.add(default)
    ordered = [PROCESS_CATEGORY_ALL] if include_common else []
    ordered += sorted([n for n in names if n != PROCESS_CATEGORY_ALL])
    return ordered


def load_process_categories_df(active_only: bool = False) -> pd.DataFrame:
    _ensure_process_category_options_table()
    sql = "SELECT id, category_name, is_active, sort_order, note, created_at, updated_at FROM process_categories WHERE 1=1"
    if active_only:
        sql += " AND COALESCE(is_active,1)=1"
    sql += " ORDER BY CASE WHEN category_name=? THEN 0 ELSE 1 END, sort_order, id"
    df = query_df(sql, (PROCESS_CATEGORY_ALL,))
    if df is None or df.empty:
        return pd.DataFrame(columns=["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    return df


def save_process_categories_df(df: pd.DataFrame) -> int:
    _ensure_process_category_options_table()
    if df is None:
        return 0
    now = _now()
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    count = 0
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = _norm_category_name(_row_get(r, "category_name", "category", "類別", "類別 / Category", default=""))
        if not name:
            continue
        raw_active = str(_row_get(r, "is_active", "啟用", "啟用 / Active", default=True)).strip().lower()
        is_active = 0 if raw_active in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(_row_get(r, "sort_order", "排序", "排序 / Sort", default=idx)))
        except Exception:
            sort_order = idx
        note = str(_row_get(r, "note", "備註", "備註 / Note", default="") or "").strip()
        rid = str(_row_get(r, "id", default="") or "").strip()
        old_name = ""
        if rid:
            try:
                old_row = query_one("SELECT category_name FROM process_categories WHERE id=?", (int(float(rid)),)) or {}
                old_name = _norm_category_name(old_row.get("category_name")) if old_row else ""
            except Exception:
                old_name = ""
        if rid:
            try:
                execute(
                    """
                    UPDATE process_categories
                    SET category_name=?, is_active=?, sort_order=?, note=?, updated_at=?
                    WHERE id=?
                    """,
                    (name, is_active, sort_order, note, now, int(float(rid))),
                )
                if old_name and old_name != name:
                    execute("UPDATE process_category_options SET category_name=?, updated_at=? WHERE category_name=?", (name, now, old_name))
                count += 1
                continue
            except Exception:
                pass
        execute(
            """
            INSERT INTO process_categories(category_name, is_active, sort_order, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(category_name) DO UPDATE SET
                is_active=excluded.is_active,
                sort_order=excluded.sort_order,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (name, is_active, sort_order, note, now, now),
        )
        count += 1
    _clear_settings_cache()
    export_system_settings_permanent("save_process_categories", write_history=True)
    write_log("SAVE_PROCESS_CATEGORIES", f"儲存類別設定 {count} 筆，已寫入 13 系統設定永久檔", "process_categories")
    return count


def delete_process_categories(ids: Iterable[int]) -> int:
    _ensure_process_category_options_table()
    count = 0
    for raw in ids:
        try:
            i = int(raw)
        except Exception:
            continue
        row = query_one("SELECT category_name FROM process_categories WHERE id=?", (i,)) or {}
        category = _norm_category_name(row.get("category_name")) if row else ""
        if not category or category == PROCESS_CATEGORY_ALL:
            continue
        execute("DELETE FROM process_categories WHERE id=?", (i,))
        execute("DELETE FROM process_category_options WHERE category_name=?", (category,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_process_categories", write_history=True)
        write_log("DELETE_PROCESS_CATEGORIES", f"刪除類別設定 {count} 筆，並移除對應工段，已寫入永久檔", "process_categories", level="WARN")
    return count

def get_default_process_category() -> str:
    _ensure_process_category_options_table()
    try:
        row = query_one("SELECT setting_value FROM app_settings WHERE setting_key=?", (DEFAULT_PROCESS_CATEGORY_KEY,)) or {}
        value = str(row.get("setting_value") or "").strip()
        return _norm_category_name(value) if value else PROCESS_CATEGORY_ALL
    except Exception:
        return PROCESS_CATEGORY_ALL


def save_default_process_category(category_name: str) -> str:
    _ensure_process_category_options_table()
    category = _norm_category_name(category_name)
    now = _now()
    execute(
        """
        INSERT INTO app_settings(setting_key, setting_value, note, updated_at)
        VALUES (?, ?, '01 工時紀錄：類別空白或找不到對應工段時使用的預設類別', ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (DEFAULT_PROCESS_CATEGORY_KEY, category, now),
    )
    _clear_settings_cache()
    export_system_settings_permanent("save_default_process_category", write_history=True)
    write_log("SAVE_DEFAULT_PROCESS_CATEGORY", f"儲存預設類別：{category}", "app_settings")
    return category


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    _ensure_process_category_options_table()
    sql = "SELECT id, category_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_category_options WHERE 1=1"
    params: list[Any] = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY CASE WHEN category_name=? THEN 0 ELSE 1 END, category_name, sort_order, id"
    params.append(PROCESS_CATEGORY_ALL)
    df = query_df(sql, params)
    if df is None or df.empty:
        legacy = query_df("SELECT id, process_name, is_active, sort_order, note, created_at, updated_at FROM process_options ORDER BY sort_order, id")
        if legacy is not None and not legacy.empty:
            legacy.insert(1, "category_name", PROCESS_CATEGORY_ALL)
        return legacy
    return df


def get_process_options_by_category(category_name: str | None = None, include_common: bool = True) -> list[str]:
    """Return active process names for the selected category.

    Important rule for 01｜工時紀錄:
    類別｜Category 決定 工段名稱｜Process；選擇哪個類別，只能出現
    13｜系統設定「一、類別與工段名稱設定 / Category & Process Options」
    中該類別對應的工段。

    Therefore this function no longer falls back to the default category, all
    categories, legacy process_options, or DEFAULT_PROCESS_OPTIONS when a
    category has no rows. An empty list is a valid saved setting.
    """
    _ensure_process_category_options_table()
    category = _norm_category_name(category_name)

    def _names_for(where_sql: str, params: tuple[Any, ...]) -> list[str]:
        try:
            df = query_df(
                f"SELECT process_name FROM process_category_options WHERE COALESCE(is_active,1)=1 AND {where_sql} ORDER BY sort_order, id",
                params,
            )
            names: list[str] = []
            for x in df.get("process_name", []).dropna().tolist() if df is not None and not df.empty else []:
                s = str(x).strip()
                if s and s not in names:
                    names.append(s)
            return names
        except Exception:
            return []

    # 「全部 / 通用」也是一個類別；選到它時只顯示通用工段。
    if category == PROCESS_CATEGORY_ALL:
        return _names_for("(category_name=? OR COALESCE(category_name,'')='')", (PROCESS_CATEGORY_ALL,))

    category_names = _names_for("category_name=?", (category,))
    if not include_common:
        return category_names

    common_names = _names_for("(category_name=? OR COALESCE(category_name,'')='')", (PROCESS_CATEGORY_ALL,))
    return common_names + [n for n in category_names if n not in common_names]


def get_process_options_by_category_exact(category_name: str | None = None) -> list[str]:
    """Strict category-to-process mapping for 01｜工時紀錄.

    This helper intentionally returns only the process names under the selected
    category in process_category_options. No default fallback is allowed, because
    an empty mapping must remain empty and prompt the admin to maintain 13｜系統設定.
    """
    return get_process_options_by_category(category_name, include_common=False)


def get_process_options() -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(get_default_process_category(), include_common=True)


def save_process_options_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    _ensure_process_category_options_table()
    if df is None:
        return 0
    now = _now()
    count = 0
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(r.get("process_name", r.get("工段名稱", r.get("工段名稱 / Process", "")))).strip()
        if not name:
            continue
        category = _norm_category_name(
            r.get("category_name", r.get("category", r.get("類別", r.get("類別 / Category", r.get("type_name", r.get("機型", PROCESS_CATEGORY_ALL))))))
        )
        active_raw = str(r.get("is_active", r.get("啟用", r.get("啟用 / Active", True)))).strip().lower()
        is_active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(r.get("sort_order", r.get("排序", r.get("sort_order / sort_order", idx))) or idx))
        except Exception:
            sort_order = idx
        note = str(r.get("note", r.get("備註", r.get("備註 / Note", ""))) or "")
        rid = str(r.get("id", r.get("ID", r.get("ID / ID", "")))).strip()
        if rid and rid.lower() not in {"nan", "none"}:
            execute(
                """
                UPDATE process_category_options
                SET category_name=?, process_name=?, is_active=?, sort_order=?, note=?, updated_at=?
                WHERE id=?
                """,
                (category, name, is_active, sort_order, note, now, int(float(rid))),
            )
        else:
            execute(
                """
                INSERT INTO process_category_options(category_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (category, name, is_active, sort_order, note, now, now),
            )
        count += 1
    _clear_settings_cache()
    export_system_settings_permanent("save_category_process_options", write_history=True)
    write_log("SAVE_PROCESS_OPTIONS", f"儲存類別對應工段設定 {count} 筆，已寫入 13 系統設定永久檔", "process_category_options")
    return count


def delete_process_options(ids: Iterable[int]) -> int:  # type: ignore[override]
    _ensure_process_category_options_table()
    count = 0
    for rid in ids or []:
        try:
            i = int(float(rid))
        except Exception:
            continue
        execute("DELETE FROM process_category_options WHERE id=?", (i,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_category_process_options", write_history=True)
        write_log("DELETE_PROCESS_OPTIONS", f"刪除類別對應工段設定 {count} 筆，已寫入 13 系統設定永久檔", "process_category_options", level="WARN")
    return count


# Backward-compatible aliases. Old V3.28 pages can still import model names,
# but they now use category logic so the app does not break during rolling updates.
def load_process_model_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    return load_process_category_choices(include_common=include_common)


def get_default_process_model() -> str:  # type: ignore[override]
    return get_default_process_category()


def save_default_process_model(type_name: str) -> str:  # type: ignore[override]
    return save_default_process_category(type_name)


def get_process_options_by_model(type_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(type_name, include_common=include_common)


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """Write 13｜系統設定 permanent files, including category-specific process mappings."""
    ensure_system_settings_schema()
    _ensure_process_category_options_table()
    _ensure_permanent_dirs()
    try:
        proc = query_df("SELECT id, category_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_category_options ORDER BY category_name, sort_order, id")
        cats = query_df("SELECT id, category_name, is_active, sort_order, note, created_at, updated_at FROM process_categories ORDER BY sort_order, id")
    except Exception:
        proc = pd.DataFrame()
    try:
        rest = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        rest = pd.DataFrame()
    try:
        app = query_df("SELECT setting_key, setting_value, note, updated_at FROM app_settings ORDER BY setting_key")
    except Exception:
        app = pd.DataFrame()
    payload: dict[str, Any] = {
        "version": "V3.33",
        "exported_at": _now(),
        "reason": reason,
        "description": "13｜系統設定永久紀錄：類別對應工段名稱、休息時間、01 工時紀錄每日重新整理時間。",
        "tables": {
            "process_categories": _df_records(cats),
            "process_options": _df_records(proc),
            "rest_periods": _df_records(rest),
            "app_settings": _df_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
    }
    for out_path in SYSTEM_SETTINGS_FILES:
        _atomic_write_json(out_path, payload)
    if write_history:
        hist = SYSTEM_SETTINGS_HISTORY_DIR / f"system_settings_{now_stamp()}.json"
        _atomic_write_json(hist, payload)
    try:
        mark_data_changed("13｜系統設定已變更，永久設定檔已建立；GitHub 同步請到 13 頁面手動執行。", "system_settings_permanent_json")
    except Exception:
        pass
    return {"ok": True, "files": [str(p) for p in SYSTEM_SETTINGS_FILES], "table_counts": payload["table_counts"], "payload_version": "V3.33"}

# ===== V3.41 13｜系統設定永久檔防回原始設定守門 =====
# 避免 Reboot App 後讀到較新的預設檔而覆蓋使用者設定。

def _v341_system_candidate_paths() -> list[Path]:
    paths = [p for p in SYSTEM_SETTINGS_FILES if p.exists()]
    if SYSTEM_SETTINGS_HISTORY_DIR.exists():
        paths.extend(SYSTEM_SETTINGS_HISTORY_DIR.glob("system_settings_*.json"))
    uniq = {str(p): p for p in paths if p.exists()}
    return sorted(uniq.values(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _v341_tables_from_system_payload(data: dict[str, Any]) -> dict[str, list]:
    if not isinstance(data, dict):
        return {}
    tables = data.get("tables")
    if isinstance(tables, dict):
        return {str(k): (v if isinstance(v, list) else []) for k, v in tables.items()}
    return {
        "process_options": data.get("process_options", []) if isinstance(data.get("process_options"), list) else [],
        "process_categories": data.get("process_categories", []) if isinstance(data.get("process_categories"), list) else [],
        "rest_periods": data.get("rest_periods", []) if isinstance(data.get("rest_periods"), list) else [],
        "app_settings": data.get("app_settings", []) if isinstance(data.get("app_settings"), list) else [],
    }


def _v341_system_score(path: Path, tables: dict[str, list]) -> tuple[int, int, int, int, float]:
    cats = len(tables.get("process_categories", []) or [])
    proc = len(tables.get("process_category_options", []) or []) + len(tables.get("process_options", []) or [])
    rests = len(tables.get("rest_periods", []) or [])
    apps = len(tables.get("app_settings", []) or [])
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    return (cats, proc, rests, apps, mtime)


def _load_latest_persistent_payload() -> dict[str, Any] | None:  # type: ignore[override]
    """V3.41: choose the richest 13 setting payload, not simply the newest file."""
    best_path: Path | None = None
    best_payload: dict[str, Any] | None = None
    best_score = (-1, -1, -1, -1, -1.0)
    for path in _v341_system_candidate_paths():
        data = _load_json_file(path)
        if not data:
            continue
        tables = _v341_tables_from_system_payload(data)
        score = _v341_system_score(path, tables)
        if score > best_score:
            best_score = score
            best_path = path
            best_payload = {"tables": tables, "_source": str(best_path), "_score": score}
    return best_payload


_old_export_system_settings_permanent_v341 = export_system_settings_permanent

def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """V3.41: protect existing non-default settings from being overwritten by empty/default tables."""
    ensure_system_settings_schema()
    payload_before = _load_latest_persistent_payload()
    before_tables = payload_before.get("tables", {}) if isinstance(payload_before, dict) else {}
    before_score = _v341_system_score(Path(str(payload_before.get("_source", SYSTEM_SETTINGS_FILES[0]))) if isinstance(payload_before, dict) else SYSTEM_SETTINGS_FILES[0], before_tables) if before_tables else (-1, -1, -1, -1, -1.0)
    try:
        proc_count = _table_count("process_options")
        rest_count = _table_count("rest_periods")
    except Exception:
        proc_count = rest_count = 0
    # If current DB is empty/default-like but a richer permanent payload exists, restore first and avoid bad export.
    if before_tables and proc_count <= 0 and before_score[1] > 0:
        restore_system_settings_from_permanent(force=True)
    return _old_export_system_settings_permanent_v341(reason=reason, write_history=write_history)


_old_restore_system_settings_from_permanent_v341 = restore_system_settings_from_permanent

def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    """V3.41 wrapper: restore category tables as well, using richest permanent file."""
    _basic_create_tables()
    try:
        _ensure_process_category_options_table()
    except Exception:
        pass
    payload = _load_latest_persistent_payload()
    if not payload:
        return {"ok": False, "restored": {}, "message": "找不到 13 系統設定永久檔"}
    tables = payload.get("tables", {}) if isinstance(payload.get("tables"), dict) else {}
    restored: dict[str, int] = {}
    # Restore legacy/default tables through original implementation first.
    try:
        r0 = _old_restore_system_settings_from_permanent_v341(force=force)
        restored.update(r0.get("restored", {}) if isinstance(r0, dict) else {})
    except Exception:
        pass
    # Restore category master/options if present.
    cat_rows = tables.get("process_categories", []) if isinstance(tables.get("process_categories"), list) else []
    # V3.43: current export stores category/process mapping under tables["process_options"].
    # Older restore code looked only for "process_category_options", so Reboot could
    # recreate the default category-process mapping and hide user-maintained rows.
    cat_proc_rows = tables.get("process_category_options", []) if isinstance(tables.get("process_category_options"), list) else []
    if not cat_proc_rows and isinstance(tables.get("process_options"), list):
        cat_proc_rows = tables.get("process_options", []) or []
    if force or (_table_count("process_categories") == 0 and cat_rows):
        if force:
            try: execute("DELETE FROM process_categories")
            except Exception: pass
        try:
            count = 0
            for idx, r in enumerate(cat_rows or [], start=1):
                name = _norm_category_name(r.get("category_name") or r.get("類別") or r.get("category"))
                if not name:
                    continue
                active_raw = str(r.get("is_active", 1)).strip().lower()
                active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
                try: sort_order = int(float(r.get("sort_order") or idx))
                except Exception: sort_order = idx
                execute("""
                    INSERT INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(category_name) DO UPDATE SET
                        is_active=excluded.is_active, sort_order=excluded.sort_order,
                        note=excluded.note, updated_at=excluded.updated_at
                """, (name, active, sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())))
                count += 1
            restored["process_categories"] = count
        except Exception:
            pass
    if force or (_table_count("process_category_options") == 0 and cat_proc_rows):
        if force:
            try: execute("DELETE FROM process_category_options")
            except Exception: pass
        try:
            count = 0
            for idx, r in enumerate(cat_proc_rows or [], start=1):
                category = _norm_category_name(r.get("category_name") or r.get("type_name") or PROCESS_CATEGORY_ALL)
                proc = str(r.get("process_name") or "").strip()
                if not proc:
                    continue
                active_raw = str(r.get("is_active", 1)).strip().lower()
                active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
                try: sort_order = int(float(r.get("sort_order") or idx))
                except Exception: sort_order = idx
                execute("""
                    INSERT INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(category_name, process_name) DO UPDATE SET
                        is_active=excluded.is_active, sort_order=excluded.sort_order,
                        note=excluded.note, updated_at=excluded.updated_at
                """, (category, proc, active, sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())))
                count += 1
            restored["process_category_options"] = count
        except Exception:
            pass
    if restored:
        _clear_settings_cache()
    return {"ok": bool(restored), "restored": restored, "source": payload.get("_source", "system_settings_json"), "score": payload.get("_score", None)}


# ===== V3.63 definitive 13-system-settings persistence =====
# 原因：舊版用「資料越多越好」挑永久檔，會把使用者清空後的有效設定誤判為不完整，
# Reboot 後又選到含預設資料的舊 history。V363 改為：直接最新永久檔優先，空表也是有效設定。

def _v363_upload_system_settings_files(reason: str) -> dict[str, Any]:
    try:
        from services.github_cloud_storage_service import github_config, upload_file_to_github
        if not github_config().get("token"):
            return {"ok": False, "skipped": True, "message": "GITHUB_TOKEN not configured"}
        uploads = []
        for local, remote in [
            (PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json", "data/persistent_state/spt_system_settings.json"),
            (PROJECT_ROOT / "data" / "config" / "system_settings.json", "data/config/system_settings.json"),
            (PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "system_settings.json", "data/persistent_modules/13_system_settings/system_settings.json"),
        ]:
            if local.exists() and local.stat().st_size > 0:
                uploads.append(upload_file_to_github(local, remote, f"SPT V363 system settings {reason} {now_text()}"))
        return {"ok": all(bool(x.get("ok")) for x in uploads) if uploads else False, "uploads": uploads}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _v363_direct_system_candidate_paths() -> list[Path]:
    # Direct/latest files first by priority.  History is fallback only.
    direct = [
        PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json",
        PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "system_settings.json",
        PROJECT_ROOT / "data" / "config" / "system_settings.json",
    ]
    existing = [p for p in direct if p.exists() and p.stat().st_size > 0]
    if existing:
        return existing
    if SYSTEM_SETTINGS_HISTORY_DIR.exists():
        return sorted(SYSTEM_SETTINGS_HISTORY_DIR.glob("system_settings_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return []


def _load_latest_persistent_payload() -> dict[str, Any] | None:  # type: ignore[override]
    for path in _v363_direct_system_candidate_paths():
        data = _load_json_file(path)
        if not data:
            continue
        tables = _v341_tables_from_system_payload(data)
        # Key point: even empty lists are valid if the table key exists.
        if isinstance(data.get("tables"), dict) or tables:
            return {"tables": tables, "_source": str(path), "_score": ("v363_direct", path.stat().st_mtime if path.exists() else 0)}
    return None


_prev_export_system_settings_permanent_v363 = export_system_settings_permanent

def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    res = _prev_export_system_settings_permanent_v363(reason=reason, write_history=write_history)
    try:
        # Mirror this module into unified master so table/system state lives in the same top-level source.
        from services.persistence_core_service import load_master_settings, save_master_settings
        payload = _load_json_file(PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json") or {}
        master = load_master_settings()
        sys_section = master.get("system_settings") if isinstance(master.get("system_settings"), dict) else {}
        sys_section["13.system_settings"] = payload
        master["system_settings"] = sys_section
        save_master_settings(master, reason=f"v363_system_settings_{reason}")
    except Exception:
        pass
    try:
        res["github_upload"] = _v363_upload_system_settings_files(reason)
    except Exception:
        pass
    return res


_prev_restore_system_settings_from_permanent_v363 = restore_system_settings_from_permanent

def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    _basic_create_tables()
    try:
        _ensure_process_category_options_table()
    except Exception:
        pass
    payload = _load_latest_persistent_payload()
    if not payload:
        return {"ok": False, "restored": {}, "message": "找不到 13 系統設定永久檔"}
    tables = payload.get("tables", {}) if isinstance(payload.get("tables"), dict) else {}
    restored: dict[str, int] = {}
    # First restore rest/app using existing logic, but category tables below are authoritative.
    try:
        r0 = _old_restore_system_settings_from_permanent_v341(force=force)
        restored.update(r0.get("restored", {}) if isinstance(r0, dict) else {})
    except Exception:
        pass
    has_cat_key = "process_categories" in tables
    has_proc_key = "process_options" in tables or "process_category_options" in tables
    cat_rows = tables.get("process_categories", []) if isinstance(tables.get("process_categories"), list) else []
    cat_proc_rows = tables.get("process_category_options", []) if isinstance(tables.get("process_category_options"), list) else []
    if not cat_proc_rows and isinstance(tables.get("process_options"), list):
        cat_proc_rows = tables.get("process_options", []) or []
    # If the latest permanent file explicitly has the table key, it is authoritative,
    # including empty list.  This prevents reboot from refilling defaults.
    try:
        if force or has_cat_key:
            execute("DELETE FROM process_categories")
            count = 0
            for idx, r in enumerate(cat_rows or [], start=1):
                name = _norm_category_name(r.get("category_name") or r.get("類別") or r.get("category"))
                if not name:
                    continue
                active_raw = str(r.get("is_active", 1)).strip().lower()
                active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
                try: sort_order = int(float(r.get("sort_order") or idx))
                except Exception: sort_order = idx
                execute("""
                    INSERT INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(category_name) DO UPDATE SET is_active=excluded.is_active, sort_order=excluded.sort_order, note=excluded.note, updated_at=excluded.updated_at
                """, (name, active, sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())))
                count += 1
            restored["process_categories"] = count
        if force or has_proc_key:
            execute("DELETE FROM process_category_options")
            count = 0
            for idx, r in enumerate(cat_proc_rows or [], start=1):
                category = _norm_category_name(r.get("category_name") or r.get("type_name") or PROCESS_CATEGORY_ALL)
                proc = str(r.get("process_name") or "").strip()
                if not proc:
                    continue
                active_raw = str(r.get("is_active", 1)).strip().lower()
                active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
                try: sort_order = int(float(r.get("sort_order") or idx))
                except Exception: sort_order = idx
                execute("""
                    INSERT INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(category_name, process_name) DO UPDATE SET is_active=excluded.is_active, sort_order=excluded.sort_order, note=excluded.note, updated_at=excluded.updated_at
                """, (category, proc, active, sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())))
                count += 1
            restored["process_category_options"] = count
    except Exception as exc:
        restored["error"] = str(exc)
    if restored:
        _clear_settings_cache()
    return {"ok": bool(restored), "restored": restored, "source": payload.get("_source", "system_settings_json"), "score": payload.get("_score", None)}


# ===== V3.66 system settings persistence: same direct-latest-file pattern as 03/04 =====
# 原則：13｜系統設定儲存後直接寫固定 latest JSON；Reboot 直接讀固定 JSON。
# 不再用「資料越多越好」、不掃 history、不自動 GitHub、不讓空表被預設值覆蓋。

_V366_SYSTEM_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json"
_V366_SYSTEM_MODULE_FILE = PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings" / "system_settings.json"
_V366_SYSTEM_CONFIG_FILE = PROJECT_ROOT / "data" / "config" / "system_settings.json"
_V366_SYSTEM_SCHEMA_READY = False
_V366_SYSTEM_RESTORED_DIRECT = False


def _v366_system_read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v366_system_atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v366_create_category_tables_no_seed() -> None:
    _basic_create_tables()
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_category_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT DEFAULT '',
            process_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(category_name, process_name)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS process_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            note TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )


def _v366_system_direct_payload() -> dict[str, Any]:
    for path in [_V366_SYSTEM_MODULE_FILE, _V366_SYSTEM_STATE_FILE, _V366_SYSTEM_CONFIG_FILE]:
        data = _v366_system_read_json(path)
        tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
        # Empty lists are valid, as long as the latest file explicitly has the keys.
        if isinstance(tables, dict) and any(k in tables for k in ["process_categories", "process_options", "process_category_options", "rest_periods", "app_settings"]):
            return data
    return {}


def _load_latest_persistent_payload() -> dict[str, Any] | None:  # type: ignore[override]
    data = _v366_system_direct_payload()
    if not data:
        return None
    tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
    return {"tables": tables, "_source": "v366_direct_system_settings", "_score": "direct_latest"}


def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    _v366_create_category_tables_no_seed()
    payload = _v366_system_direct_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not tables:
        return {"ok": False, "mode": "v366_direct", "restored": {}, "message": "no direct system settings file"}
    restored: dict[str, int] = {}

    def _active(v: Any, default: int = 1) -> int:
        text = str(v if v is not None else default).strip().lower()
        return 0 if text in {"0", "false", "no", "n", "off", "停用", "否"} else 1

    # The keys themselves are authoritative, even when the list is empty.
    if force or "process_categories" in tables:
        execute("DELETE FROM process_categories")
        count = 0
        for idx, r in enumerate(tables.get("process_categories") or [], start=1):
            if not isinstance(r, dict):
                continue
            name = _norm_category_name(r.get("category_name") or r.get("category") or r.get("類別"))
            if not name:
                continue
            try:
                sort_order = int(float(r.get("sort_order") or idx))
            except Exception:
                sort_order = idx
            execute(
                """
                INSERT INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(category_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (name, _active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            count += 1
        restored["process_categories"] = count

    has_proc_key = "process_options" in tables or "process_category_options" in tables
    if force or has_proc_key:
        execute("DELETE FROM process_category_options")
        execute("DELETE FROM process_options")
        proc_rows = tables.get("process_category_options") if isinstance(tables.get("process_category_options"), list) else tables.get("process_options", [])
        count = 0
        for idx, r in enumerate(proc_rows or [], start=1):
            if not isinstance(r, dict):
                continue
            category = _norm_category_name(r.get("category_name") or r.get("type_name") or PROCESS_CATEGORY_ALL)
            proc = str(r.get("process_name") or "").strip()
            if not proc:
                continue
            try:
                sort_order = int(float(r.get("sort_order") or idx))
            except Exception:
                sort_order = idx
            execute(
                """
                INSERT INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (category, proc, _active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            # Legacy process_options cache for older callers.
            execute(
                """
                INSERT INTO process_options(process_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (proc, _active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            count += 1
        restored["process_category_options"] = count
        restored["process_options"] = count

    if force or "rest_periods" in tables:
        execute("DELETE FROM rest_periods")
        restored["rest_periods"] = _insert_rest_rows(tables.get("rest_periods") or [])

    if force or "app_settings" in tables:
        execute("DELETE FROM app_settings")
        restored["app_settings"] = _insert_app_settings_rows(tables.get("app_settings") or [])

    _clear_settings_cache()
    return {"ok": True, "mode": "v366_direct", "restored": restored, "source": str(_V366_SYSTEM_MODULE_FILE)}


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    _v366_create_category_tables_no_seed()
    try:
        cats = query_df("SELECT id, category_name, is_active, sort_order, note, created_at, updated_at FROM process_categories ORDER BY sort_order, id")
    except Exception:
        cats = pd.DataFrame()
    try:
        proc = query_df("SELECT id, category_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_category_options ORDER BY category_name, sort_order, id")
    except Exception:
        proc = pd.DataFrame()
    try:
        rest = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        rest = pd.DataFrame()
    try:
        app = query_df("SELECT setting_key, setting_value, note, updated_at FROM app_settings ORDER BY setting_key")
    except Exception:
        app = pd.DataFrame()
    payload: dict[str, Any] = {
        "version": "V3.66-direct-system-settings-persistence",
        "exported_at": _now(),
        "reason": reason,
        "module_key": "13_system_settings",
        "module_name_zh": "系統設定",
        "module_name_en": "System Settings",
        "description": "13｜系統設定固定永久檔。模式比照 03/04：儲存直接寫 latest JSON，Reboot 直接讀 latest JSON；空表也是有效設定。",
        "tables": {
            "process_categories": _df_records(cats),
            "process_options": _df_records(proc),
            "rest_periods": _df_records(rest),
            "app_settings": _df_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
    }
    for path in [_V366_SYSTEM_MODULE_FILE, _V366_SYSTEM_STATE_FILE, _V366_SYSTEM_CONFIG_FILE]:
        _v366_system_atomic_write(path, payload)
    # Compatibility with unified master, but do not let it control restore.
    try:
        from services.persistence_core_service import load_master_settings, save_master_settings
        master = load_master_settings()
        sys_section = master.get("system_settings") if isinstance(master.get("system_settings"), dict) else {}
        sys_section["13.system_settings"] = payload
        master["system_settings"] = sys_section
        save_master_settings(master, reason=f"v366_system_settings_{reason}")
    except Exception:
        pass
    try:
        mark_data_changed("13｜系統設定已變更，已寫入固定永久檔；如部署於 Streamlit Cloud，請用 09 備份到 GitHub。", "13_system_settings")
    except Exception:
        pass
    return {"ok": True, "mode": "v366_direct", "files": [str(_V366_SYSTEM_MODULE_FILE), str(_V366_SYSTEM_STATE_FILE), str(_V366_SYSTEM_CONFIG_FILE)], "table_counts": payload["table_counts"]}


def ensure_system_settings_schema() -> None:  # type: ignore[override]
    """Create schema and restore direct latest settings before any default seed."""
    global _V366_SYSTEM_SCHEMA_READY, _SYSTEM_SETTINGS_SCHEMA_READY, _V366_SYSTEM_RESTORED_DIRECT
    if _V366_SYSTEM_SCHEMA_READY:
        return
    _v366_create_category_tables_no_seed()
    direct_payload = _v366_system_direct_payload()
    if direct_payload:
        restore_system_settings_from_permanent(force=True)
        _V366_SYSTEM_RESTORED_DIRECT = True
    now = _now()
    # Seed defaults only when no fixed permanent file exists at all.
    if not direct_payload:
        try:
            if _table_count("process_categories") == 0:
                execute(
                    "INSERT OR IGNORE INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at) VALUES (?,1,1,'系統預設類別',?,?)",
                    (PROCESS_CATEGORY_ALL, now, now),
                )
            if _table_count("process_category_options") == 0:
                for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
                    execute(
                        """
                        INSERT OR IGNORE INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                        VALUES (?, ?, 1, ?, '系統預設工段，可於 13 系統設定修改', ?, ?)
                        """,
                        (PROCESS_CATEGORY_ALL, name, idx, now, now),
                    )
                    execute(
                        """
                        INSERT OR IGNORE INTO process_options(process_name,is_active,sort_order,note,created_at,updated_at)
                        VALUES (?,1,?,'系統預設工段，可於 13 系統設定修改',?,?)
                        """,
                        (name, idx, now, now),
                    )
            if _table_count("rest_periods") == 0:
                _insert_rest_rows(DEFAULT_REST_PERIODS)
            if not _has_live_page_reset_setting():
                execute(
                    "INSERT OR REPLACE INTO app_settings(setting_key,setting_value,note,updated_at) VALUES (?,?,?,?)",
                    ("live_page_reset_time", DEFAULT_LIVE_PAGE_RESET_TIME, "01 工時紀錄每日自動重新整理時間", now),
                )
        except Exception:
            pass
    _clear_settings_cache()
    _SYSTEM_SETTINGS_SCHEMA_READY = True
    _V366_SYSTEM_SCHEMA_READY = True



# ===== V3.72 DIRECT LATEST SYSTEM SETTINGS LIKE 03/04 =====
# 目的：13｜系統設定改成跟 03｜製令管理、04｜人員名單一樣的固定 latest JSON 讀寫。
# - 儲存：直接寫 data/persistent_modules/13_system_settings/13_system_settings_records.json
# - Reboot：直接讀同一個 latest JSON
# - 不掃 history、不比資料筆數、不讓 SQLite 預設值覆蓋使用者設定
# - 空清單也是有效設定
_V372_SYSTEM_MODULE_DIR = PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings"
_V372_SYSTEM_LATEST_FILE = _V372_SYSTEM_MODULE_DIR / "13_system_settings_records.json"
_V372_SYSTEM_COMPAT_FILE = _V372_SYSTEM_MODULE_DIR / "system_settings.json"
_V372_SYSTEM_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json"
_V372_SYSTEM_CONFIG_FILE = PROJECT_ROOT / "data" / "config" / "system_settings.json"
_V372_SYSTEM_RESTORE_FLAG = "_v372_system_latest_restored"
try:
    _v372_prev_ensure_system_settings_schema = ensure_system_settings_schema  # type: ignore[name-defined]
except Exception:
    _v372_prev_ensure_system_settings_schema = None


def _v372_system_read_latest() -> dict[str, Any]:
    for path in [_V372_SYSTEM_LATEST_FILE, _V372_SYSTEM_COMPAT_FILE, _V372_SYSTEM_STATE_FILE, _V372_SYSTEM_CONFIG_FILE]:
        data = _v366_system_read_json(path) if "_v366_system_read_json" in globals() else {}
        if not isinstance(data, dict):
            continue
        tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
        if isinstance(tables, dict) and any(k in tables for k in ["process_categories", "process_category_options", "process_options", "rest_periods", "app_settings"]):
            return data
    return {}


def _v372_df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.where(pd.notna(df), "").to_dict(orient="records")


def _v372_system_payload_from_db(reason: str = "system_settings_saved") -> dict[str, Any]:
    _v366_create_category_tables_no_seed()
    try:
        cats = query_df("SELECT id, category_name, is_active, sort_order, note, created_at, updated_at FROM process_categories ORDER BY sort_order, id")
    except Exception:
        cats = pd.DataFrame(columns=["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    try:
        proc = query_df("SELECT id, category_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_category_options ORDER BY category_name, sort_order, id")
    except Exception:
        proc = pd.DataFrame(columns=["id", "category_name", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    try:
        rest = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        rest = pd.DataFrame(columns=["id", "name", "start_time", "end_time", "is_active", "sort_order"])
    try:
        app = query_df("SELECT setting_key, setting_value, note, updated_at FROM app_settings ORDER BY setting_key")
    except Exception:
        app = pd.DataFrame(columns=["setting_key", "setting_value", "note", "updated_at"])
    proc_rows = _v372_df_to_records(proc)
    payload: dict[str, Any] = {
        "version": "V3.72-direct-latest-like-03-04",
        "exported_at": _now(),
        "reason": reason,
        "module_key": "13_system_settings",
        "module_code": "13_system_settings",
        "module_name_zh": "系統設定",
        "module_name_en": "System Settings",
        "source": "system_settings_service_v372",
        "description": "13｜系統設定固定 latest JSON。模式比照 03/04：儲存寫 latest，Reboot 讀 same latest；空表也是有效設定。",
        "tables": {
            "process_categories": _v372_df_to_records(cats),
            "process_category_options": proc_rows,
            # 相容舊呼叫端。注意：內容與 process_category_options 完全一致。
            "process_options": proc_rows,
            "rest_periods": _v372_df_to_records(rest),
            "app_settings": _v372_df_to_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_category_options": 0 if proc is None else len(proc),
            "process_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
        "counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_category_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
    }
    return payload


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    """V3.72：照 03/04 的成功模式，固定 latest 檔直接覆蓋。"""
    payload = _v372_system_payload_from_db(reason)
    for path in [_V372_SYSTEM_LATEST_FILE, _V372_SYSTEM_COMPAT_FILE, _V372_SYSTEM_STATE_FILE, _V372_SYSTEM_CONFIG_FILE]:
        _v366_system_atomic_write(path, payload)
    _clear_settings_cache()
    return {
        "ok": True,
        "mode": "v372_direct_latest_like_03_04",
        "files": [str(_V372_SYSTEM_LATEST_FILE), str(_V372_SYSTEM_COMPAT_FILE), str(_V372_SYSTEM_STATE_FILE), str(_V372_SYSTEM_CONFIG_FILE)],
        "table_counts": payload.get("table_counts", {}),
    }


def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    """V3.72：Reboot 後只讀固定 latest，不掃 history，不用資料筆數猜測。"""
    _v366_create_category_tables_no_seed()
    payload = _v372_system_read_latest()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or not any(k in tables for k in ["process_categories", "process_category_options", "process_options", "rest_periods", "app_settings"]):
        return {"ok": False, "mode": "v372_direct_latest_like_03_04", "message": "no fixed latest system settings file"}

    restored: dict[str, int] = {}

    def _active(v: Any, default: int = 1) -> int:
        text = str(v if v is not None else default).strip().lower()
        return 0 if text in {"0", "false", "no", "n", "off", "停用", "否"} else 1

    # key 存在即代表有效設定；空清單也要覆蓋成空表。
    if "process_categories" in tables:
        execute("DELETE FROM process_categories")
        count = 0
        for idx, r in enumerate(tables.get("process_categories") or [], start=1):
            if not isinstance(r, dict):
                continue
            name = _norm_category_name(r.get("category_name") or r.get("category") or r.get("類別"))
            if not name:
                continue
            try:
                sort_order = int(float(r.get("sort_order") or idx))
            except Exception:
                sort_order = idx
            execute(
                """
                INSERT INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(category_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (name, _active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            count += 1
        restored["process_categories"] = count

    if "process_category_options" in tables or "process_options" in tables:
        execute("DELETE FROM process_category_options")
        execute("DELETE FROM process_options")
        proc_rows = tables.get("process_category_options") if isinstance(tables.get("process_category_options"), list) else tables.get("process_options", [])
        count = 0
        for idx, r in enumerate(proc_rows or [], start=1):
            if not isinstance(r, dict):
                continue
            category = _norm_category_name(r.get("category_name") or r.get("type_name") or PROCESS_CATEGORY_ALL)
            proc = str(r.get("process_name") or "").strip()
            if not proc:
                continue
            try:
                sort_order = int(float(r.get("sort_order") or idx))
            except Exception:
                sort_order = idx
            execute(
                """
                INSERT INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (category, proc, _active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            execute(
                """
                INSERT INTO process_options(process_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (proc, _active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            count += 1
        restored["process_category_options"] = count
        restored["process_options"] = count

    if "rest_periods" in tables:
        execute("DELETE FROM rest_periods")
        restored["rest_periods"] = _insert_rest_rows(tables.get("rest_periods") or [])

    if "app_settings" in tables:
        execute("DELETE FROM app_settings")
        restored["app_settings"] = _insert_app_settings_rows(tables.get("app_settings") or [])

    _clear_settings_cache()
    return {"ok": True, "mode": "v372_direct_latest_like_03_04", "source": str(_V372_SYSTEM_LATEST_FILE), "restored": restored}


def ensure_system_settings_schema() -> None:  # type: ignore[override]
    """V3.72：先讀固定 latest；只有 latest 不存在才允許初始預設。"""
    global _SYSTEM_SETTINGS_SCHEMA_READY
    _v366_create_category_tables_no_seed()
    payload = _v372_system_read_latest()
    if payload:
        restore_system_settings_from_permanent(force=True)
    else:
        # 固定 latest 不存在，才走舊版預設初始化一次。
        try:
            if _v372_prev_ensure_system_settings_schema is not None:
                _v372_prev_ensure_system_settings_schema()
        except Exception:
            pass
    _clear_settings_cache()
    _SYSTEM_SETTINGS_SCHEMA_READY = True

# ===== V3.73 FINAL DIRECT-LATEST SYSTEM SETTINGS PATCH START =====
# Purpose: make 13｜系統設定 behave like 03｜製令管理 / 04｜人員名單.
# Rule:
#   1. Save/delete writes one fixed latest JSON directly.
#   2. Reboot/page load restores from the fixed latest JSON only when DB is empty.
#   3. No history scan, no "larger file wins", no load-time overwrite loop.
_V373_SYSTEM_MODULE_DIR = PROJECT_ROOT / "data" / "persistent_modules" / "13_system_settings"
_V373_SYSTEM_LATEST_FILE = _V373_SYSTEM_MODULE_DIR / "13_system_settings_records.json"
_V373_SYSTEM_COMPAT_FILE = _V373_SYSTEM_MODULE_DIR / "system_settings.json"
_V373_SYSTEM_STATE_FILE = PROJECT_ROOT / "data" / "persistent_state" / "spt_system_settings.json"
_V373_SYSTEM_CONFIG_FILE = PROJECT_ROOT / "data" / "config" / "system_settings.json"
_V373_SYSTEM_RESTORE_KEY = "_v373_system_latest_restored"


def _v373_s_read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 2:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _v373_s_atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def _v373_s_latest_payload() -> dict[str, Any]:
    # Fixed latest is authoritative. Compat/state/config are only migration fallback when latest is absent.
    for path in [_V373_SYSTEM_LATEST_FILE, _V373_SYSTEM_COMPAT_FILE, _V373_SYSTEM_STATE_FILE, _V373_SYSTEM_CONFIG_FILE]:
        data = _v373_s_read_json(path)
        tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
        if isinstance(tables, dict) and any(k in tables for k in ["process_categories", "process_category_options", "process_options", "rest_periods", "app_settings"]):
            return data
    return {}


def _v373_s_schema_only() -> None:
    try:
        _v366_create_category_tables_no_seed()  # type: ignore[name-defined]
    except Exception:
        try:
            _ensure_process_category_options_table()  # type: ignore[name-defined]
        except Exception:
            pass


def _v373_table_count(table: str) -> int:
    try:
        row = query_one(f'SELECT COUNT(*) AS c FROM "{table}"') or {}
        return int(row.get("c", 0) or 0)
    except Exception:
        return 0


def _v373_s_db_empty() -> bool:
    _v373_s_schema_only()
    # Same spirit as 03/04: only restore when current DB table has no user rows.
    return (_v373_table_count("process_categories") == 0 and _v373_table_count("process_category_options") == 0)


def _v373_active(v: Any, default: int = 1) -> int:
    text = str(v if v is not None else default).strip().lower()
    return 0 if text in {"0", "false", "no", "n", "off", "停用", "否"} else 1


def _v373_df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.where(pd.notna(df), "").to_dict(orient="records")


def _v373_insert_app_settings_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        key = str(r.get("setting_key") or "").strip()
        if not key:
            continue
        execute(
            "INSERT OR REPLACE INTO app_settings(setting_key,setting_value,note,updated_at) VALUES (?,?,?,?)",
            (key, str(r.get("setting_value") or ""), str(r.get("note") or ""), str(r.get("updated_at") or _now())),
        )
        count += 1
    return count


def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    _v373_s_schema_only()
    payload = _v373_s_latest_payload()
    tables = payload.get("tables") if isinstance(payload.get("tables"), dict) else {}
    if not isinstance(tables, dict) or not any(k in tables for k in ["process_categories", "process_category_options", "process_options", "rest_periods", "app_settings"]):
        return {"ok": False, "mode": "v373_direct_latest_like_03_04", "message": "no fixed latest system settings file"}
    if not force and not _v373_s_db_empty():
        return {"ok": True, "mode": "v373_direct_latest_like_03_04", "skipped": True, "reason": "db_not_empty_like_03_04"}
    restored: dict[str, int] = {}
    if "process_categories" in tables:
        execute("DELETE FROM process_categories")
        count = 0
        for idx, r in enumerate(tables.get("process_categories") or [], start=1):
            if not isinstance(r, dict):
                continue
            name = _norm_category_name(r.get("category_name") or r.get("category") or r.get("類別"))
            if not name:
                continue
            try:
                sort_order = int(float(r.get("sort_order") or idx))
            except Exception:
                sort_order = idx
            execute(
                """
                INSERT INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(category_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (name, _v373_active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            count += 1
        restored["process_categories"] = count
    if "process_category_options" in tables or "process_options" in tables:
        execute("DELETE FROM process_category_options")
        execute("DELETE FROM process_options")
        proc_rows = tables.get("process_category_options") if isinstance(tables.get("process_category_options"), list) else tables.get("process_options", [])
        count = 0
        for idx, r in enumerate(proc_rows or [], start=1):
            if not isinstance(r, dict):
                continue
            category = _norm_category_name(r.get("category_name") or r.get("type_name") or PROCESS_CATEGORY_ALL)
            proc = str(r.get("process_name") or "").strip()
            if not proc:
                continue
            try:
                sort_order = int(float(r.get("sort_order") or idx))
            except Exception:
                sort_order = idx
            execute(
                """
                INSERT INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (category, proc, _v373_active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            execute(
                """
                INSERT INTO process_options(process_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active, sort_order=excluded.sort_order,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (proc, _v373_active(r.get("is_active", 1)), sort_order, str(r.get("note") or ""), str(r.get("created_at") or _now()), str(r.get("updated_at") or _now())),
            )
            count += 1
        restored["process_category_options"] = count
        restored["process_options"] = count
    if "rest_periods" in tables:
        execute("DELETE FROM rest_periods")
        restored["rest_periods"] = _insert_rest_rows(tables.get("rest_periods") or [])
    if "app_settings" in tables:
        execute("DELETE FROM app_settings")
        restored["app_settings"] = _v373_insert_app_settings_rows(tables.get("app_settings") or [])
    _clear_settings_cache()
    if st is not None:
        try:
            st.session_state[_V373_SYSTEM_RESTORE_KEY] = True
        except Exception:
            pass
    return {"ok": True, "mode": "v373_direct_latest_like_03_04", "source": str(_V373_SYSTEM_LATEST_FILE), "restored": restored}


def _v373_restore_system_once_if_needed() -> None:
    if st is not None:
        try:
            if st.session_state.get(_V373_SYSTEM_RESTORE_KEY):
                return
        except Exception:
            pass
    restore_system_settings_from_permanent(force=False)
    if st is not None:
        try:
            st.session_state[_V373_SYSTEM_RESTORE_KEY] = True
        except Exception:
            pass


def ensure_system_settings_schema() -> None:  # type: ignore[override]
    global _SYSTEM_SETTINGS_SCHEMA_READY
    _v373_s_schema_only()
    _v373_restore_system_once_if_needed()
    # Seed minimal defaults only when no fixed latest exists and DB is empty.
    if not _v373_s_latest_payload() and _v373_s_db_empty():
        now = _now()
        try:
            execute("INSERT OR IGNORE INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at) VALUES (?,1,1,'系統預設類別',?,?)", (PROCESS_CATEGORY_ALL, now, now))
            for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
                execute("INSERT OR IGNORE INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at) VALUES (?, ?, 1, ?, '系統預設工段，可於 13 系統設定修改', ?, ?)", (PROCESS_CATEGORY_ALL, name, idx, now, now))
        except Exception:
            pass
    _SYSTEM_SETTINGS_SCHEMA_READY = True


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    _v373_s_schema_only()
    try:
        cats = query_df("SELECT id, category_name, is_active, sort_order, note, created_at, updated_at FROM process_categories ORDER BY sort_order, id")
    except Exception:
        cats = pd.DataFrame(columns=["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    try:
        proc = query_df("SELECT id, category_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_category_options ORDER BY category_name, sort_order, id")
    except Exception:
        proc = pd.DataFrame(columns=["id", "category_name", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    try:
        rest = query_df("SELECT id, name, start_time, end_time, is_active, sort_order FROM rest_periods ORDER BY sort_order, id")
    except Exception:
        rest = pd.DataFrame(columns=["id", "name", "start_time", "end_time", "is_active", "sort_order"])
    try:
        app = query_df("SELECT setting_key, setting_value, note, updated_at FROM app_settings ORDER BY setting_key")
    except Exception:
        app = pd.DataFrame(columns=["setting_key", "setting_value", "note", "updated_at"])
    proc_rows = _v373_df_records(proc)
    payload = {
        "version": "V3.73-direct-latest-like-03-04-final",
        "exported_at": _now(),
        "reason": reason,
        "module_key": "13_system_settings",
        "module_code": "13_system_settings",
        "module_name_zh": "系統設定",
        "module_name_en": "System Settings",
        "source": "system_settings_service_v373",
        "description": "13 系統設定：比照 03/04，儲存寫固定 latest JSON；Reboot 僅在 DB 空白時讀同一 latest JSON。空表也是有效設定。",
        "tables": {
            "process_categories": _v373_df_records(cats),
            "process_category_options": proc_rows,
            "process_options": proc_rows,
            "rest_periods": _v373_df_records(rest),
            "app_settings": _v373_df_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_category_options": 0 if proc is None else len(proc),
            "process_options": 0 if proc is None else len(proc),
            "rest_periods": 0 if rest is None else len(rest),
            "app_settings": 0 if app is None else len(app),
        },
    }
    for path in [_V373_SYSTEM_LATEST_FILE, _V373_SYSTEM_COMPAT_FILE, _V373_SYSTEM_STATE_FILE, _V373_SYSTEM_CONFIG_FILE]:
        _v373_s_atomic_write(path, payload)
    _clear_settings_cache()
    return {"ok": True, "mode": "v373_direct_latest_like_03_04_final", "files": [str(_V373_SYSTEM_LATEST_FILE), str(_V373_SYSTEM_COMPAT_FILE), str(_V373_SYSTEM_STATE_FILE), str(_V373_SYSTEM_CONFIG_FILE)], "table_counts": payload["table_counts"]}


def load_process_categories_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    ensure_system_settings_schema()
    sql = "SELECT id, category_name, is_active, sort_order, note, created_at, updated_at FROM process_categories WHERE 1=1"
    if active_only:
        sql += " AND COALESCE(is_active,1)=1"
    sql += " ORDER BY CASE WHEN category_name=? THEN 0 ELSE 1 END, sort_order, id"
    df = query_df(sql, (PROCESS_CATEGORY_ALL,))
    if df is None or df.empty:
        return pd.DataFrame(columns=["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    return df


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    ensure_system_settings_schema()
    sql = "SELECT id, category_name, process_name, is_active, sort_order, note, created_at, updated_at FROM process_category_options WHERE 1=1"
    params: list[Any] = []
    if active_only:
        sql += " AND COALESCE(is_active, 1)=1"
    sql += " ORDER BY CASE WHEN category_name=? THEN 0 ELSE 1 END, category_name, sort_order, id"
    params.append(PROCESS_CATEGORY_ALL)
    df = query_df(sql, params)
    if df is None or df.empty:
        return pd.DataFrame(columns=["id", "category_name", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
    return df


def load_process_category_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    df = load_process_categories_df(active_only=True)
    names = [str(x).strip() for x in df.get("category_name", []).dropna().tolist() if str(x).strip()] if df is not None and not df.empty else []
    if include_common and PROCESS_CATEGORY_ALL not in names:
        names.insert(0, PROCESS_CATEGORY_ALL)
    return names or ([PROCESS_CATEGORY_ALL] if include_common else [])


def get_process_options_by_category(category_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    # Strict link requested by user: selected Category decides Process list.
    ensure_system_settings_schema()
    category = _norm_category_name(category_name)
    try:
        df = query_df(
            "SELECT process_name FROM process_category_options WHERE COALESCE(is_active,1)=1 AND category_name=? ORDER BY sort_order, id",
            (category,),
        )
        names = [str(x).strip() for x in df.get("process_name", []).dropna().tolist() if str(x).strip()] if df is not None and not df.empty else []
        return names
    except Exception:
        return []


def get_process_options() -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(get_default_process_category(), include_common=False)


def save_process_categories_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    _v373_s_schema_only()
    if df is None:
        return 0
    now = _now(); count = 0
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = _norm_category_name(_row_get(r, "category_name", "category", "類別", "類別 / Category", default=""))
        if not name:
            continue
        is_active = _v373_active(_row_get(r, "is_active", "啟用", "啟用 / Active", default=True))
        try:
            sort_order = int(float(_row_get(r, "sort_order", "排序", "排序 / Sort", default=idx) or idx))
        except Exception:
            sort_order = idx
        note = str(_row_get(r, "note", "備註", "備註 / Note", default="") or "").strip()
        rid = str(_row_get(r, "id", default="") or "").strip()
        old_name = ""
        if rid:
            try:
                old_row = query_one("SELECT category_name FROM process_categories WHERE id=?", (int(float(rid)),)) or {}
                old_name = _norm_category_name(old_row.get("category_name")) if old_row else ""
            except Exception:
                old_name = ""
        if rid:
            try:
                execute("UPDATE process_categories SET category_name=?, is_active=?, sort_order=?, note=?, updated_at=? WHERE id=?", (name, is_active, sort_order, note, now, int(float(rid))))
                if old_name and old_name != name:
                    execute("UPDATE process_category_options SET category_name=?, updated_at=? WHERE category_name=?", (name, now, old_name))
                count += 1
                continue
            except Exception:
                pass
        execute(
            """
            INSERT INTO process_categories(category_name, is_active, sort_order, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(category_name) DO UPDATE SET is_active=excluded.is_active, sort_order=excluded.sort_order, note=excluded.note, updated_at=excluded.updated_at
            """,
            (name, is_active, sort_order, note, now, now),
        )
        count += 1
    _clear_settings_cache()
    export_system_settings_permanent("save_process_categories_v373", write_history=False)
    return count


def delete_process_categories(ids: Iterable[int]) -> int:  # type: ignore[override]
    _v373_s_schema_only(); count = 0
    for raw in ids or []:
        try:
            i = int(float(raw))
        except Exception:
            continue
        row = query_one("SELECT category_name FROM process_categories WHERE id=?", (i,)) or {}
        category = _norm_category_name(row.get("category_name")) if row else ""
        if not category or category == PROCESS_CATEGORY_ALL:
            continue
        execute("DELETE FROM process_categories WHERE id=?", (i,))
        execute("DELETE FROM process_category_options WHERE category_name=?", (category,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_process_categories_v373", write_history=False)
    return count


def save_process_options_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    _v373_s_schema_only()
    if df is None:
        return 0
    now = _now(); count = 0
    work = df.copy().drop(columns=["刪除", "delete", "selected"], errors="ignore").fillna("")
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = str(r.get("process_name", r.get("工段名稱", r.get("工段名稱 / Process", "")))).strip()
        if not name:
            continue
        category = _norm_category_name(r.get("category_name", r.get("category", r.get("類別", r.get("類別 / Category", PROCESS_CATEGORY_ALL)))))
        is_active = _v373_active(r.get("is_active", r.get("啟用", r.get("啟用 / Active", True))))
        try:
            sort_order = int(float(r.get("sort_order", r.get("排序", idx)) or idx))
        except Exception:
            sort_order = idx
        note = str(r.get("note", r.get("備註", r.get("備註 / Note", ""))) or "")
        rid = str(r.get("id", r.get("ID", r.get("ID / ID", "")))).strip()
        if rid and rid.lower() not in {"nan", "none"}:
            execute("UPDATE process_category_options SET category_name=?, process_name=?, is_active=?, sort_order=?, note=?, updated_at=? WHERE id=?", (category, name, is_active, sort_order, note, now, int(float(rid))))
        else:
            execute(
                """
                INSERT INTO process_category_options(category_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET is_active=excluded.is_active, sort_order=excluded.sort_order, note=excluded.note, updated_at=excluded.updated_at
                """,
                (category, name, is_active, sort_order, note, now, now),
            )
        count += 1
    _clear_settings_cache()
    export_system_settings_permanent("save_category_process_options_v373", write_history=False)
    return count


def delete_process_options(ids: Iterable[int]) -> int:  # type: ignore[override]
    _v373_s_schema_only(); count = 0
    for rid in ids or []:
        try:
            i = int(float(rid))
        except Exception:
            continue
        execute("DELETE FROM process_category_options WHERE id=?", (i,))
        count += 1
    if count:
        _clear_settings_cache()
        export_system_settings_permanent("delete_category_process_options_v373", write_history=False)
    return count

# Backward-compatible aliases.
def load_process_model_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    return load_process_category_choices(include_common=include_common)

def get_default_process_model() -> str:  # type: ignore[override]
    return get_default_process_category()

def save_default_process_model(type_name: str) -> str:  # type: ignore[override]
    return save_default_process_category(type_name)

def get_process_options_by_model(type_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(type_name, include_common=False)
# ===== V3.73 FINAL DIRECT-LATEST SYSTEM SETTINGS PATCH END =====




# ========================= V28 Permanent Authority Overrides =========================
# 13 系統設定以 canonical records.json 為唯一權威，不再依賴先進 13 頁還原 SQLite。
try:
    from services.permanent_authority_service import load_tables as _v28_load_tables, update_tables as _v28_update_tables, table_from_df as _v28_table_from_df
except Exception:
    _v28_load_tables = _v28_update_tables = _v28_table_from_df = None  # type: ignore

def _v28_sys_tables() -> dict:
    if _v28_load_tables is not None:
        return _v28_load_tables("13_system_settings")
    return {}

def _v28_df(table: str, cols: list[str]) -> pd.DataFrame:
    rows = _v28_sys_tables().get(table, [])
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns: df[c] = ""
    return df[cols]

def load_process_categories_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"]
    df = _v28_df("process_categories", cols)
    if df.empty:
        # If only options exist, derive categories without seeding defaults over user data.
        opt = _v28_df("process_category_options", ["category_name"])
        names = sorted({str(x).strip() for x in opt.get("category_name", []) if str(x).strip()})
        df = pd.DataFrame([{"id": i+1, "category_name": n, "is_active": 1, "sort_order": i+1, "note": "", "created_at": "", "updated_at": ""} for i, n in enumerate(names)])
    if active_only and "is_active" in df.columns:
        m = df["is_active"].astype(str).str.lower().str.strip().isin(["1","true","yes","y","是","啟用"]) | (df["is_active"] == 1) | (df["is_active"] == True)
        df = df[m]
    if not df.empty:
        df = df.sort_values(["sort_order", "id"], kind="stable", na_position="last")
    return df.reset_index(drop=True)

def load_process_options_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "category_name", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"]
    df = _v28_df("process_category_options", cols)
    if df.empty:
        old = _v28_df("process_options", ["id", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"])
        if not old.empty:
            old["category_name"] = PROCESS_CATEGORY_ALL
            df = old[cols]
    if active_only and "is_active" in df.columns:
        m = df["is_active"].astype(str).str.lower().str.strip().isin(["1","true","yes","y","是","啟用"]) | (df["is_active"] == 1) | (df["is_active"] == True)
        df = df[m]
    if not df.empty:
        df = df.sort_values(["category_name", "sort_order", "id"], kind="stable", na_position="last")
    return df.reset_index(drop=True)

def load_process_category_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    df = load_process_categories_df(active_only=True)
    names = [str(x).strip() for x in df.get("category_name", []) if str(x).strip()]
    if include_common and PROCESS_CATEGORY_ALL not in names:
        names.insert(0, PROCESS_CATEGORY_ALL)
    return names

def get_process_options_by_category(category_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    category = _norm_category_name(category_name)
    df = load_process_options_df(active_only=True)
    if "category_name" in df.columns:
        df = df[df["category_name"].astype(str).str.strip() == category]
    return [str(x).strip() for x in df.get("process_name", []) if str(x).strip()]

def get_process_options() -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(get_default_process_category(), include_common=False)

def _v28_save_sys_table(table: str, df: pd.DataFrame, reason: str) -> int:
    tables = _v28_sys_tables()
    rows = _v28_table_from_df(df) if _v28_table_from_df is not None else []
    tables[table] = rows
    # Compatibility: keep process_options mirror for pages/functions that still expect old table name.
    if table == "process_category_options": tables["process_options"] = list(rows)
    if _v28_update_tables is not None:
        _v28_update_tables("13_system_settings", tables, reason=reason)
    return len(rows)

def save_process_categories_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    if df is None: return 0
    work = df.copy().drop(columns=["刪除", "delete", "selected", "刪除 / Delete"], errors="ignore").fillna("")
    return _v28_save_sys_table("process_categories", work, "save_process_categories_v28")

def save_process_options_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    if df is None: return 0
    work = df.copy().drop(columns=["刪除", "delete", "selected", "刪除 / Delete"], errors="ignore").fillna("")
    if "category_name" not in work.columns: work["category_name"] = PROCESS_CATEGORY_ALL
    return _v28_save_sys_table("process_category_options", work, "save_process_options_v28")

def delete_process_categories(ids: Iterable[int]) -> int:  # type: ignore[override]
    tables = _v28_sys_tables(); ids_set = {str(int(float(x))) for x in ids or [] if str(x).strip()}
    before = len(tables.get("process_categories", []))
    cats = [r for r in tables.get("process_categories", []) if str(r.get("id", "")) not in ids_set and str(r.get("category_name", "")) != PROCESS_CATEGORY_ALL]
    removed_names = {str(r.get("category_name", "")) for r in tables.get("process_categories", []) if str(r.get("id", "")) in ids_set}
    opts = [r for r in tables.get("process_category_options", []) if str(r.get("category_name", "")) not in removed_names]
    tables["process_categories"] = cats; tables["process_category_options"] = opts; tables["process_options"] = list(opts)
    if _v28_update_tables is not None: _v28_update_tables("13_system_settings", tables, reason="delete_process_categories_v28")
    return max(0, before - len(cats))

def delete_process_options(ids: Iterable[int]) -> int:  # type: ignore[override]
    tables = _v28_sys_tables(); ids_set = {str(int(float(x))) for x in ids or [] if str(x).strip()}
    before = len(tables.get("process_category_options", []))
    opts = [r for r in tables.get("process_category_options", []) if str(r.get("id", "")) not in ids_set]
    tables["process_category_options"] = opts; tables["process_options"] = list(opts)
    if _v28_update_tables is not None: _v28_update_tables("13_system_settings", tables, reason="delete_process_options_v28")
    return max(0, before - len(opts))

# ========================= V85 SYSTEM SETTINGS SINGLE AUTHORITY FIX =========================
# 目的：13. 系統設定改成與 01 / V28 權威檔相同做法。
# 規則：所有類別、工段、休息時間、app_settings 只以
# data/permanent_store/modules/13_system_settings/records.json 為 records 權威檔。
# SQLite 只做相容快取；讀取與 Reboot 不再以 SQLite / history / 舊 persistent 檔覆蓋權威檔。

try:
    from services.permanent_authority_service import (
        load_tables as _v85_pa_load_tables,
        save_authority as _v85_pa_save_authority,
        canonical_path as _v85_pa_canonical_path,
        authority_file_exists as _v85_pa_authority_file_exists,
    )
except Exception:
    _v85_pa_load_tables = None  # type: ignore
    _v85_pa_save_authority = None  # type: ignore
    _v85_pa_canonical_path = None  # type: ignore
    _v85_pa_authority_file_exists = None  # type: ignore

_V85_MODULE_KEY = "13_system_settings"
_V85_AUTH_READY = False


def _v85_auth_file_exists() -> bool:
    try:
        if _v85_pa_authority_file_exists is not None:
            return bool(_v85_pa_authority_file_exists(_V85_MODULE_KEY, "records"))
    except Exception:
        pass
    try:
        if _v85_pa_canonical_path is not None:
            return bool(_v85_pa_canonical_path(_V85_MODULE_KEY, "records").exists())
    except Exception:
        pass
    return False


def _v85_now() -> str:
    try:
        return _now()
    except Exception:
        try:
            return now_text()
        except Exception:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _v85_blank(v: Any) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v).strip().lower() in {"", "nan", "none", "null", "<na>"}


def _v85_text(v: Any, default: str = "") -> str:
    return default if _v85_blank(v) else str(v).strip()


def _v85_get(row: Any, *names: str, default: Any = "") -> Any:
    try:
        keys = list(row.keys()) if hasattr(row, "keys") else []
        lower = {str(k).strip().lower(): k for k in keys}
        for n in names:
            if n in row and not _v85_blank(row.get(n)):
                return row.get(n)
            real = lower.get(str(n).strip().lower())
            if real is not None and not _v85_blank(row.get(real)):
                return row.get(real)
    except Exception:
        pass
    return default


def _v85_bool(v: Any, default: bool = True) -> int:
    if _v85_blank(v):
        return 1 if default else 0
    if isinstance(v, bool):
        return 1 if v else 0
    text = str(v).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "是", "啟用", "在廠", "出勤"}:
        return 1
    if text in {"0", "false", "no", "n", "off", "否", "停用", "未啟用"}:
        return 0
    return 1 if default else 0


def _v85_int(v: Any, default: int | None = None) -> int | None:
    if _v85_blank(v):
        return default
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _v85_next_id(rows: list[dict[str, Any]]) -> int:
    mx = 0
    for r in rows or []:
        x = _v85_int(r.get("id"), None)
        if x is not None and x > mx:
            mx = x
    return mx + 1


def _v85_records_df(rows: list[dict[str, Any]], cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows or [])
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    if not df.empty:
        return df[cols].copy()
    return pd.DataFrame(columns=cols)


def _v85_raw_tables() -> dict[str, list[dict[str, Any]]]:
    if _v85_pa_load_tables is None:
        return {}
    try:
        tables = _v85_pa_load_tables(_V85_MODULE_KEY, "records") or {}
        return {str(k): [dict(r) for r in (v or []) if isinstance(r, dict)] for k, v in tables.items() if isinstance(v, list)}
    except Exception:
        return {}


def _v85_normalize_tables(tables: dict[str, list[dict[str, Any]]] | None) -> dict[str, list[dict[str, Any]]]:
    out = {str(k): [dict(r) for r in (v or []) if isinstance(r, dict)] for k, v in (tables or {}).items() if isinstance(v, list)}
    out.setdefault("process_categories", [])
    # 權威檔內正式使用 process_category_options；process_options 僅做舊版相容鏡像。
    if not out.get("process_category_options") and out.get("process_options"):
        fixed = []
        for idx, r in enumerate(out.get("process_options") or [], start=1):
            x = dict(r)
            x.setdefault("id", idx)
            x.setdefault("category_name", PROCESS_CATEGORY_ALL)
            fixed.append(x)
        out["process_category_options"] = fixed
    out.setdefault("process_category_options", [])
    out["process_options"] = list(out.get("process_category_options", []))
    out.setdefault("rest_periods", [])
    out.setdefault("app_settings", [])
    return out


def _v85_tables() -> dict[str, list[dict[str, Any]]]:
    return _v85_normalize_tables(_v85_raw_tables())


def _v85_save_tables(tables: dict[str, list[dict[str, Any]]], reason: str) -> dict[str, Any]:
    tables = _v85_normalize_tables(tables)
    if _v85_pa_save_authority is None:
        return {"ok": False, "reason": "permanent_authority_service_not_available"}
    res = _v85_pa_save_authority(_V85_MODULE_KEY, records=tables, reason=reason, github=True)
    _v85_sync_to_sqlite(tables)
    _clear_settings_cache()
    return res


def _v85_seed_tables() -> dict[str, list[dict[str, Any]]]:
    now = _v85_now()
    cats = [{"id": 1, "category_name": PROCESS_CATEGORY_ALL, "is_active": 1, "sort_order": 1, "note": "系統預設類別", "created_at": now, "updated_at": now}]
    opts = []
    for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
        opts.append({"id": idx, "category_name": PROCESS_CATEGORY_ALL, "process_name": name, "is_active": 1, "sort_order": idx, "note": "系統預設工段，可於 13 系統設定修改", "created_at": now, "updated_at": now})
    rests = []
    for idx, r in enumerate(DEFAULT_REST_PERIODS, start=1):
        x = dict(r); x.setdefault("id", idx); rests.append(x)
    apps = [
        {"setting_key": "live_page_reset_time", "setting_value": DEFAULT_LIVE_PAGE_RESET_TIME, "note": "01 工時紀錄每日重新整理時間；只影響 01 顯示，不刪除 02 歷史紀錄", "updated_at": now},
        {"setting_key": DEFAULT_PROCESS_CATEGORY_KEY, "setting_value": PROCESS_CATEGORY_ALL, "note": "01 工時紀錄預設類別", "updated_at": now},
    ]
    return _v85_normalize_tables({"process_categories": cats, "process_category_options": opts, "rest_periods": rests, "app_settings": apps})


def _v85_create_sqlite_schema() -> None:
    try:
        if "_v366_create_category_tables_no_seed" in globals():
            _v366_create_category_tables_no_seed()  # type: ignore[name-defined]
            return
    except Exception:
        pass
    try:
        _basic_create_tables()
        execute("""
            CREATE TABLE IF NOT EXISTS process_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT UNIQUE NOT NULL,
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                note TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        execute("""
            CREATE TABLE IF NOT EXISTS process_category_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT DEFAULT '',
                process_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                note TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(category_name, process_name)
            )
        """)
    except Exception:
        pass


def _v85_sync_to_sqlite(tables: dict[str, list[dict[str, Any]]]) -> None:
    """SQLite 只作相容快取。權威仍是 records.json。"""
    try:
        _v85_create_sqlite_schema()
        execute("DELETE FROM process_categories")
        execute("DELETE FROM process_category_options")
        execute("DELETE FROM process_options")
        execute("DELETE FROM rest_periods")
        execute("DELETE FROM app_settings")
        for idx, r in enumerate(tables.get("process_categories", []) or [], start=1):
            name = _v85_text(r.get("category_name"))
            if not name:
                continue
            execute(
                """
                INSERT INTO process_categories(id, category_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (_v85_int(r.get("id"), idx), name, _v85_bool(r.get("is_active"), True), _v85_int(r.get("sort_order"), idx), _v85_text(r.get("note")), _v85_text(r.get("created_at"), _v85_now()), _v85_text(r.get("updated_at"), _v85_now())),
            )
        for idx, r in enumerate(tables.get("process_category_options", []) or tables.get("process_options", []) or [], start=1):
            proc = _v85_text(r.get("process_name"))
            if not proc:
                continue
            category = _norm_category_name(r.get("category_name") or PROCESS_CATEGORY_ALL)
            rid = _v85_int(r.get("id"), idx)
            active = _v85_bool(r.get("is_active"), True)
            sort_order = _v85_int(r.get("sort_order"), idx)
            note = _v85_text(r.get("note"))
            created = _v85_text(r.get("created_at"), _v85_now())
            updated = _v85_text(r.get("updated_at"), _v85_now())
            execute(
                """
                INSERT INTO process_category_options(id, category_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (rid, category, proc, active, sort_order, note, created, updated),
            )
            execute(
                """
                INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (proc, active, sort_order, note, created, updated),
            )
        for idx, r in enumerate(tables.get("rest_periods", []) or [], start=1):
            name = _v85_text(r.get("name")) or f"休息時間{idx}"
            start = _v85_text(r.get("start_time"))
            end = _v85_text(r.get("end_time"))
            if not start or not end:
                continue
            execute(
                "INSERT INTO rest_periods(id, name, start_time, end_time, is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                (_v85_int(r.get("id"), idx), name, start, end, _v85_bool(r.get("is_active"), True), _v85_int(r.get("sort_order"), idx)),
            )
        for r in tables.get("app_settings", []) or []:
            key = _v85_text(r.get("setting_key"))
            if not key:
                continue
            execute(
                "INSERT OR REPLACE INTO app_settings(setting_key, setting_value, note, updated_at) VALUES (?, ?, ?, ?)",
                (key, _v85_text(r.get("setting_value")), _v85_text(r.get("note")), _v85_text(r.get("updated_at"), _v85_now())),
            )
    except Exception:
        pass


def ensure_system_settings_schema() -> None:  # type: ignore[override]
    global _V85_AUTH_READY, _SYSTEM_SETTINGS_SCHEMA_READY
    _v85_create_sqlite_schema()
    existed = _v85_auth_file_exists()
    tables = _v85_tables()
    # 權威檔不存在且完全沒有資料時，才建立初始預設。權威檔一旦存在，即使空表也視為正式設定。
    has_any = any(len(v) > 0 for k, v in tables.items() if k in {"process_categories", "process_category_options", "rest_periods", "app_settings"})
    if not existed and not has_any:
        tables = _v85_seed_tables()
        _v85_save_tables(tables, "seed_default_13_system_settings_v85")
    else:
        _v85_sync_to_sqlite(tables)
    _V85_AUTH_READY = True
    _SYSTEM_SETTINGS_SCHEMA_READY = True


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    ensure_system_settings_schema()
    tables = _v85_tables()
    res = _v85_save_tables(tables, f"export_{reason}_v85")
    return {"ok": True, "mode": "v85_single_authority", "files": res.get("files", []), "table_counts": {k: len(v) for k, v in tables.items() if isinstance(v, list)}}


def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    ensure_system_settings_schema()
    tables = _v85_tables()
    _v85_sync_to_sqlite(tables)
    return {"ok": True, "mode": "v85_single_authority", "source": "data/permanent_store/modules/13_system_settings/records.json", "restored": {k: len(v) for k, v in tables.items() if isinstance(v, list)}}



# >>> V87_SYSTEM_SETTINGS_DISPLAY_SENTINEL_FIX
# V87：修正 13. 系統設定表格把內部排序 sentinel 999999 顯示到畫面。
# 重點：999999 只能做排序 fallback，不可寫回或顯示在 ID / sort_order 欄位。
_V87_FAKE_NUMERIC_SENTINELS = {999999, -999999, 9999990, 99999999}


def _v87_int_or_none(v: Any) -> int | None:
    try:
        if v is None or pd.isna(v):
            return None
    except Exception:
        pass
    try:
        s = str(v).strip()
        if s == "" or s.lower() in {"none", "nan", "null", "<na>"}:
            return None
        n = int(float(s))
        if n in _V87_FAKE_NUMERIC_SENTINELS or n <= 0:
            return None
        return n
    except Exception:
        return None


def _v87_sort_or_default(v: Any, default: int) -> int:
    n = _v87_int_or_none(v)
    return int(default) if n is None else int(n)


def _v87_display_repair_df(df: pd.DataFrame, id_col: str = "id", sort_col: str = "sort_order", group_col: str | None = None) -> pd.DataFrame:
    """修復 13 表格顯示：ID / 排序若是 None、999999 或重複，改成穩定序號。"""
    if df is None or df.empty:
        return df
    out = df.copy()
    if id_col in out.columns:
        raw_ids = [_v87_int_or_none(v) for v in out[id_col].tolist()]
        used: set[int] = set()
        valid_ids = [n for n in raw_ids if n is not None]
        next_id = max(valid_ids + [0]) + 1
        fixed_ids: list[int] = []
        for n in raw_ids:
            if n is None or n in used:
                while next_id in used:
                    next_id += 1
                n = next_id
                next_id += 1
            used.add(int(n))
            fixed_ids.append(int(n))
        out[id_col] = fixed_ids
    if sort_col in out.columns:
        out[sort_col] = [_v87_sort_or_default(v, i) for i, v in enumerate(out[sort_col].tolist(), start=1)]
    sort_cols = []
    if group_col and group_col in out.columns:
        sort_cols.append(group_col)
    if sort_col in out.columns:
        sort_cols.append(sort_col)
    if id_col in out.columns:
        sort_cols.append(id_col)
    if sort_cols:
        out = out.sort_values(sort_cols, kind="stable", na_position="last")
    return out.reset_index(drop=True)


def _v87_clean_input_id(v: Any) -> int | None:
    return _v87_int_or_none(v)
# <<< V87_SYSTEM_SETTINGS_DISPLAY_SENTINEL_FIX

def load_process_categories_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    ensure_system_settings_schema()
    cols = ["id", "category_name", "is_active", "sort_order", "note", "created_at", "updated_at"]
    df = _v85_records_df(_v85_tables().get("process_categories", []), cols)
    if active_only and not df.empty:
        m = df["is_active"].map(lambda x: _v85_bool(x, True) == 1)
        df = df[m]
    if not df.empty:
        df = _v87_display_repair_df(df, id_col="id", sort_col="sort_order")
    return df.reset_index(drop=True)


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    ensure_system_settings_schema()
    cols = ["id", "category_name", "process_name", "is_active", "sort_order", "note", "created_at", "updated_at"]
    df = _v85_records_df(_v85_tables().get("process_category_options", []), cols)
    if active_only and not df.empty:
        m = df["is_active"].map(lambda x: _v85_bool(x, True) == 1)
        df = df[m]
    if not df.empty:
        df = _v87_display_repair_df(df, id_col="id", sort_col="sort_order", group_col="category_name")
    return df.reset_index(drop=True)


def load_process_category_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    cats = load_process_categories_df(active_only=True)
    names: list[str] = []
    for x in cats.get("category_name", []).tolist() if cats is not None and not cats.empty else []:
        n = _norm_category_name(x)
        if n and n not in names:
            names.append(n)
    # 防止有工段但類別表漏資料時下拉看不到。
    opts = load_process_options_df(active_only=True)
    for x in opts.get("category_name", []).tolist() if opts is not None and not opts.empty else []:
        n = _norm_category_name(x)
        if n and n not in names:
            names.append(n)
    if include_common and PROCESS_CATEGORY_ALL not in names:
        names.insert(0, PROCESS_CATEGORY_ALL)
    return names


def get_default_process_category() -> str:  # type: ignore[override]
    tables = _v85_tables()
    for r in tables.get("app_settings", []) or []:
        if _v85_text(r.get("setting_key")) == DEFAULT_PROCESS_CATEGORY_KEY:
            val = _norm_category_name(r.get("setting_value"))
            return val or PROCESS_CATEGORY_ALL
    return PROCESS_CATEGORY_ALL


def save_default_process_category(category_name: str) -> str:  # type: ignore[override]
    category = _norm_category_name(category_name)
    tables = _v85_tables()
    _v85_upsert_app_setting(tables, DEFAULT_PROCESS_CATEGORY_KEY, category, "01 工時紀錄：類別空白或找不到對應工段時使用的預設類別")
    _v85_save_tables(tables, "save_default_process_category_v85")
    try:
        write_log("SAVE_DEFAULT_PROCESS_CATEGORY", f"儲存預設類別：{category}", "13_system_settings")
    except Exception:
        pass
    return category


def get_process_options_by_category(category_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    category = _norm_category_name(category_name)
    df = load_process_options_df(active_only=True)
    if df.empty or "category_name" not in df.columns:
        return []
    if include_common and category != PROCESS_CATEGORY_ALL:
        mask = df["category_name"].astype(str).str.strip().isin([PROCESS_CATEGORY_ALL, category])
    else:
        mask = df["category_name"].astype(str).str.strip().eq(category)
    out: list[str] = []
    for x in df.loc[mask, "process_name"].tolist():
        s = _v85_text(x)
        if s and s not in out:
            out.append(s)
    return out


def get_process_options() -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(get_default_process_category(), include_common=False)


def _v85_normalize_category_rows(df: pd.DataFrame, existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    id_to_old = {str(_v85_int(r.get("id"), -1)): _v85_text(r.get("category_name")) for r in existing if _v85_int(r.get("id"), None) is not None}
    rename_map: dict[str, str] = {}
    next_id = _v85_next_id(existing)
    seen: set[str] = set()
    now = _v85_now()
    for idx, (_, r) in enumerate((df.copy() if df is not None else pd.DataFrame()).fillna("").iterrows(), start=1):
        name = _norm_category_name(_v85_get(r, "category_name", "category", "類別", "類別 / Category", default=""))
        if not name or name in seen:
            continue
        rid = _v87_clean_input_id(_v85_get(r, "id", "ID", "ID / ID", default=""))
        if rid is None:
            rid = next_id; next_id += 1
        old_name = id_to_old.get(str(rid), "")
        if old_name and old_name != name:
            rename_map[old_name] = name
        rows.append({
            "id": rid,
            "category_name": name,
            "is_active": _v85_bool(_v85_get(r, "is_active", "啟用", "啟用 / Active", default=True), True),
            "sort_order": _v87_sort_or_default(_v85_get(r, "sort_order", "排序", "排序 / Sort", default=idx), idx),
            "note": _v85_text(_v85_get(r, "note", "備註", "備註 / Note", default="")),
            "created_at": _v85_text(_v85_get(r, "created_at", "建立時間", default=""), now),
            "updated_at": now,
        })
        seen.add(name)
    return rows, rename_map


def save_process_categories_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    if df is None:
        return 0
    tables = _v85_tables()
    existing = tables.get("process_categories", [])
    rows, rename_map = _v85_normalize_category_rows(df.drop(columns=["刪除", "delete", "selected", "刪除 / Delete"], errors="ignore"), existing)
    for r in tables.get("process_category_options", []) or []:
        cat = _v85_text(r.get("category_name"))
        if cat in rename_map:
            r["category_name"] = rename_map[cat]
            r["updated_at"] = _v85_now()
    tables["process_categories"] = rows
    _v85_save_tables(tables, "save_process_categories_v85")
    try:
        write_log("SAVE_PROCESS_CATEGORIES", f"儲存類別設定 {len(rows)} 筆，已寫入 13 權威檔", "13_system_settings")
    except Exception:
        pass
    return len(rows)


def delete_process_categories(ids: Iterable[int]) -> int:  # type: ignore[override]
    tables = _v85_tables()
    ids_set = {str(_v85_int(x, -999999)) for x in (ids or [])}
    before = len(tables.get("process_categories", []) or [])
    removed = []
    kept = []
    for r in tables.get("process_categories", []) or []:
        rid = str(_v85_int(r.get("id"), -1))
        cat = _v85_text(r.get("category_name"))
        if rid in ids_set and cat != PROCESS_CATEGORY_ALL:
            removed.append(cat)
        else:
            kept.append(r)
    if removed:
        tables["process_categories"] = kept
        tables["process_category_options"] = [r for r in tables.get("process_category_options", []) or [] if _v85_text(r.get("category_name")) not in set(removed)]
        _v85_save_tables(tables, "delete_process_categories_v85")
    return max(0, before - len(kept))


def _v85_normalize_process_rows(df: pd.DataFrame, existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    raw = df.copy() if df is not None else pd.DataFrame()
    raw = raw.drop(columns=["刪除", "delete", "selected", "刪除 / Delete"], errors="ignore").fillna("")
    existing_by_id = {str(_v85_int(r.get("id"), -1)): dict(r) for r in existing if _v85_int(r.get("id"), None) is not None}
    next_id = _v85_next_id(existing)
    rows: list[dict[str, Any]] = []
    affected_categories: set[str] = set()
    seen_key: set[tuple[str, str]] = set()
    now = _v85_now()
    for idx, (_, r) in enumerate(raw.iterrows(), start=1):
        category = _norm_category_name(_v85_get(r, "category_name", "category", "類別", "類別 / Category", "type_name", default=PROCESS_CATEGORY_ALL))
        if category:
            affected_categories.add(category)
        name = _v85_text(_v85_get(r, "process_name", "工段名稱", "工段名稱 / Process", "process", "工段", default=""))
        if not name:
            continue
        key = (category, name)
        if key in seen_key:
            continue
        seen_key.add(key)
        rid = _v87_clean_input_id(_v85_get(r, "id", "ID", "ID / ID", default=""))
        old = existing_by_id.get(str(rid), {}) if rid is not None else {}
        if rid is None:
            rid = next_id; next_id += 1
        rows.append({
            "id": rid,
            "category_name": category,
            "process_name": name,
            "is_active": _v85_bool(_v85_get(r, "is_active", "啟用", "啟用 / Active", default=True), True),
            "sort_order": _v87_sort_or_default(_v85_get(r, "sort_order", "排序", "排序 / Sort", default=idx), idx),
            "note": _v85_text(_v85_get(r, "note", "備註", "備註 / Note", default="")),
            "created_at": _v85_text(_v85_get(r, "created_at", "建立時間", default=old.get("created_at", "")), now),
            "updated_at": now,
        })
    return rows, affected_categories


def save_process_options_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    if df is None:
        return 0
    tables = _v85_tables()
    existing = tables.get("process_category_options", []) or []
    incoming, affected = _v85_normalize_process_rows(df, existing)
    # 13 頁一次只編輯目前篩選類別；所以只替換受影響類別，其他類別保留。
    if affected:
        kept = [r for r in existing if _v85_text(r.get("category_name")) not in affected]
        tables["process_category_options"] = kept + incoming
    else:
        # 無法判斷類別時，不覆蓋舊資料，避免空白表格誤清空。
        tables["process_category_options"] = existing
    # 若新增工段類別不存在，補到類別主表。
    cat_names = {_v85_text(r.get("category_name")) for r in tables.get("process_categories", []) or []}
    next_cat_id = _v85_next_id(tables.get("process_categories", []) or [])
    for cat in sorted(affected):
        if cat and cat not in cat_names:
            tables.setdefault("process_categories", []).append({"id": next_cat_id, "category_name": cat, "is_active": 1, "sort_order": next_cat_id, "note": "由工段設定自動補入", "created_at": _v85_now(), "updated_at": _v85_now()})
            next_cat_id += 1
            cat_names.add(cat)
    _v85_save_tables(tables, "save_process_options_v85")
    try:
        write_log("SAVE_PROCESS_OPTIONS", f"儲存工段設定 {len(incoming)} 筆，影響類別：{', '.join(sorted(affected))}", "13_system_settings")
    except Exception:
        pass
    return len(incoming)


def delete_process_options(ids: Iterable[int]) -> int:  # type: ignore[override]
    tables = _v85_tables()
    ids_set = {str(_v85_int(x, -999999)) for x in (ids or [])}
    before = len(tables.get("process_category_options", []) or [])
    tables["process_category_options"] = [r for r in tables.get("process_category_options", []) or [] if str(_v85_int(r.get("id"), -1)) not in ids_set]
    if before != len(tables["process_category_options"]):
        _v85_save_tables(tables, "delete_process_options_v85")
    return max(0, before - len(tables["process_category_options"]))


def load_rest_periods_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    ensure_system_settings_schema()
    cols = ["id", "name", "start_time", "end_time", "is_active", "sort_order"]
    df = _v85_records_df(_v85_tables().get("rest_periods", []), cols)
    if active_only and not df.empty:
        df = df[df["is_active"].map(lambda x: _v85_bool(x, True) == 1)]
    if not df.empty:
        df = _v87_display_repair_df(df, id_col="id", sort_col="sort_order")
    return df.reset_index(drop=True)


def _v85_normalize_rest_rows(df: pd.DataFrame, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    work = df.copy().drop(columns=["刪除", "delete", "selected", "刪除 / Delete"], errors="ignore").fillna("") if df is not None else pd.DataFrame()
    next_id = _v85_next_id(existing)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for idx, (_, r) in enumerate(work.iterrows(), start=1):
        name = _v85_text(_v85_get(r, "name", "名稱", "休息名稱", "休息名稱 / Name", default=""))
        start = _v85_text(_v85_get(r, "start_time", "開始時間", "開始時間 / Start", default=""))
        end = _v85_text(_v85_get(r, "end_time", "結束時間", "結束時間 / End", default=""))
        if not start or not end:
            continue
        if not name:
            name = f"休息時間{idx}"
        key = (name, start, end)
        if key in seen:
            continue
        seen.add(key)
        rid = _v87_clean_input_id(_v85_get(r, "id", "ID", "ID / ID", default=""))
        if rid is None:
            rid = next_id; next_id += 1
        out.append({"id": rid, "name": name, "start_time": start, "end_time": end, "is_active": _v85_bool(_v85_get(r, "is_active", "啟用", "啟用 / Active", default=True), True), "sort_order": _v87_sort_or_default(_v85_get(r, "sort_order", "排序", "排序 / Sort", default=idx), idx)})
    return out


def save_rest_periods_df(df: pd.DataFrame) -> int:  # type: ignore[override]
    if df is None:
        return 0
    tables = _v85_tables()
    rows = _v85_normalize_rest_rows(df, tables.get("rest_periods", []) or [])
    tables["rest_periods"] = rows
    _v85_save_tables(tables, "save_rest_periods_v85")
    try:
        write_log("SAVE_REST_PERIODS", f"儲存休息時間設定 {len(rows)} 筆，已寫入 13 權威檔", "13_system_settings")
    except Exception:
        pass
    return len(rows)


def delete_rest_periods(ids: Iterable[int]) -> int:  # type: ignore[override]
    tables = _v85_tables()
    ids_set = {str(_v85_int(x, -999999)) for x in (ids or [])}
    before = len(tables.get("rest_periods", []) or [])
    tables["rest_periods"] = [r for r in tables.get("rest_periods", []) or [] if str(_v85_int(r.get("id"), -1)) not in ids_set]
    if before != len(tables["rest_periods"]):
        _v85_save_tables(tables, "delete_rest_periods_v85")
    return max(0, before - len(tables["rest_periods"]))


def _v85_upsert_app_setting(tables: dict[str, list[dict[str, Any]]], key: str, value: str, note: str = "") -> None:
    rows = tables.setdefault("app_settings", [])
    now = _v85_now()
    for r in rows:
        if _v85_text(r.get("setting_key")) == key:
            r["setting_value"] = value
            r["note"] = note or _v85_text(r.get("note"))
            r["updated_at"] = now
            return
    rows.append({"setting_key": key, "setting_value": value, "note": note, "updated_at": now})


def get_live_page_reset_time() -> str:  # type: ignore[override]
    tables = _v85_tables()
    for r in tables.get("app_settings", []) or []:
        if _v85_text(r.get("setting_key")) == "live_page_reset_time":
            val = _v85_text(r.get("setting_value"), DEFAULT_LIVE_PAGE_RESET_TIME)
            return _normalize_hhmm(val) if _valid_hhmm(val) else DEFAULT_LIVE_PAGE_RESET_TIME
    return DEFAULT_LIVE_PAGE_RESET_TIME


def save_live_page_reset_time(value: str) -> str:  # type: ignore[override]
    if not _valid_hhmm(value):
        raise ValueError("01 工時紀錄每日清理時間格式錯誤，請使用 HH:MM，例如 02:00。")
    value = _normalize_hhmm(value)
    tables = _v85_tables()
    _v85_upsert_app_setting(tables, "live_page_reset_time", value, "01 工時紀錄每日重新整理時間；只影響 01 顯示，不刪除 02 歷史紀錄")
    _v85_save_tables(tables, "save_live_page_reset_time_v85")
    try:
        write_log("SAVE_LIVE_PAGE_RESET_TIME", f"儲存 01 工時紀錄每日重新整理時間：{value}", "13_system_settings")
    except Exception:
        pass
    return value


def dedupe_rest_periods() -> int:  # type: ignore[override]
    df = load_rest_periods_df(active_only=False)
    before = len(df)
    rows = _v85_normalize_rest_rows(df, _v85_tables().get("rest_periods", []) or [])
    tables = _v85_tables(); tables["rest_periods"] = rows
    _v85_save_tables(tables, "dedupe_rest_periods_v85")
    return max(0, before - len(rows))

# Compatibility aliases

def load_process_model_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    return load_process_category_choices(include_common=include_common)


def get_default_process_model() -> str:  # type: ignore[override]
    return get_default_process_category()


def save_default_process_model(type_name: str) -> str:  # type: ignore[override]
    return save_default_process_category(type_name)


def get_process_options_by_model(type_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(type_name, include_common=include_common)

# ======================= END V85 SYSTEM SETTINGS SINGLE AUTHORITY FIX =======================


# ======================= V86 01 SYSTEM SETTINGS FAST CACHE =======================
# 只針對 01 工時紀錄下拉必需設定做短暫快取；13 系統設定儲存後仍會清除原本設定快取。
_V86_SYS_FAST_CACHE: dict[tuple[str, str, bool], tuple[float, object]] = {}
_V86_SYS_CACHE_SECONDS = 15.0

try:
    _v86_prev_load_process_category_choices = load_process_category_choices
except Exception:
    _v86_prev_load_process_category_choices = None
try:
    _v86_prev_get_default_process_category = get_default_process_category
except Exception:
    _v86_prev_get_default_process_category = None
try:
    _v86_prev_get_process_options_by_category_exact = get_process_options_by_category_exact
except Exception:
    _v86_prev_get_process_options_by_category_exact = None
try:
    _v86_prev_get_live_page_reset_time = get_live_page_reset_time
except Exception:
    _v86_prev_get_live_page_reset_time = None


def _v86_sys_now() -> float:
    try:
        import time as _time
        return float(_time.time())
    except Exception:
        return 0.0


def clear_time_record_system_fast_cache() -> None:
    try:
        _V86_SYS_FAST_CACHE.clear()
    except Exception:
        pass


def _v86_sys_cached(key: tuple[str, str, bool], loader, copy_list: bool = True):
    now_s = _v86_sys_now()
    got = _V86_SYS_FAST_CACHE.get(key)
    if got and (now_s - got[0] <= _V86_SYS_CACHE_SECONDS):
        val = got[1]
        return list(val) if copy_list and isinstance(val, list) else val
    val = loader()
    if isinstance(val, list):
        store_val = list(val)
    else:
        store_val = val
    _V86_SYS_FAST_CACHE[key] = (now_s, store_val)
    return list(store_val) if copy_list and isinstance(store_val, list) else store_val


def load_process_category_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    return _v86_sys_cached(
        ("category_choices", "", bool(include_common)),
        lambda: _v86_prev_load_process_category_choices(include_common=include_common) if callable(_v86_prev_load_process_category_choices) else [PROCESS_CATEGORY_ALL],
    )


def get_default_process_category() -> str:  # type: ignore[override]
    return str(_v86_sys_cached(
        ("default_category", "", False),
        lambda: _v86_prev_get_default_process_category() if callable(_v86_prev_get_default_process_category) else PROCESS_CATEGORY_ALL,
        copy_list=False,
    ) or PROCESS_CATEGORY_ALL)


def get_process_options_by_category_exact(category_name: str | None = None) -> list[str]:  # type: ignore[override]
    category = _norm_category_name(category_name)
    return _v86_sys_cached(
        ("process_options_exact", category, False),
        lambda: _v86_prev_get_process_options_by_category_exact(category) if callable(_v86_prev_get_process_options_by_category_exact) else [],
    )


def get_live_page_reset_time() -> str:  # type: ignore[override]
    return str(_v86_sys_cached(
        ("live_page_reset_time", "", False),
        lambda: _v86_prev_get_live_page_reset_time() if callable(_v86_prev_get_live_page_reset_time) else DEFAULT_LIVE_PAGE_RESET_TIME,
        copy_list=False,
    ) or DEFAULT_LIVE_PAGE_RESET_TIME)
# ===================== END V86 01 SYSTEM SETTINGS FAST CACHE =====================

# ======================= V88 13 SYSTEM SETTINGS SPEED + DELETE COMMON CATEGORY FIX =======================
# 目的：
# 1) 13｜系統設定套用/存檔不再因每次 rerun 都把整份設定逐筆寫回 SQLite 而卡很久。
# 2) SQLite 僅為相容快取，改用單一 transaction 且不觸發 after-write/GitHub/export/log storm。
# 3) 類別清單管理允許刪除「全部 / 通用」，刪除後不再由下拉清單函式自動補回。
# 4) 不改 13 權威檔架構：仍只以 data/permanent_store/modules/13_system_settings/records.json 為資料權威。

import hashlib as _v88_hashlib
import json as _v88_json

_V88_SQLITE_SYNC_HASH: str = ""
_V88_CATEGORY_CACHE_HASH: str = ""
_V88_CATEGORY_CACHE: list[str] = []


def _v88_json_fingerprint(obj: Any) -> str:
    try:
        text = _v88_json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:
        text = str(obj)
    return _v88_hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _v88_clear_all_system_caches() -> None:
    global _V88_CATEGORY_CACHE_HASH, _V88_CATEGORY_CACHE
    _V88_CATEGORY_CACHE_HASH = ""
    _V88_CATEGORY_CACHE = []
    try:
        _clear_settings_cache()
    except Exception:
        pass
    try:
        clear_time_record_system_fast_cache()  # V86 cache
    except Exception:
        pass


try:
    _v88_prev_v85_sync_to_sqlite = _v85_sync_to_sqlite
except Exception:  # pragma: no cover
    _v88_prev_v85_sync_to_sqlite = None


def _v85_sync_to_sqlite(tables: dict[str, list[dict[str, Any]]]) -> None:  # type: ignore[override]
    """V88：用 hash + transaction 加速 13 設定相容 SQLite 快取同步。

    舊版每次載入 13 頁、每次 data_editor rerun 都會：
    DELETE 多張表 → 逐筆 execute INSERT → 每筆 execute 觸發 system_logs / after_write 檢查。
    這會讓「編輯、套用、存檔」跑很久。

    新版規則：
    - 權威檔未變，不重寫 SQLite。
    - 權威檔有變，只用一次 execute_transaction 寫入 SQLite 快取。
    - mark_changed=False，因為這只是從權威檔同步到 SQLite 快取，不是新的使用者資料異動。
    """
    global _V88_SQLITE_SYNC_HASH
    try:
        norm = _v85_normalize_tables(tables)
    except Exception:
        norm = tables or {}
    fp = _v88_json_fingerprint(norm)
    if _V88_SQLITE_SYNC_HASH == fp:
        return

    try:
        _v85_create_sqlite_schema()
        from .db_service import execute_transaction
        ops: list[tuple[str, tuple[Any, ...]]] = [
            ("DELETE FROM process_categories", ()),
            ("DELETE FROM process_category_options", ()),
            ("DELETE FROM process_options", ()),
            ("DELETE FROM rest_periods", ()),
            ("DELETE FROM app_settings", ()),
        ]
        now = _v85_now()
        for idx, r in enumerate(norm.get("process_categories", []) or [], start=1):
            name = _v85_text(r.get("category_name"))
            if not name:
                continue
            ops.append((
                """
                INSERT INTO process_categories(id, category_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (
                    _v85_int(r.get("id"), idx),
                    name,
                    _v85_bool(r.get("is_active"), True),
                    _v87_sort_or_default(r.get("sort_order"), idx) if "_v87_sort_or_default" in globals() else (_v85_int(r.get("sort_order"), idx) or idx),
                    _v85_text(r.get("note")),
                    _v85_text(r.get("created_at"), now),
                    _v85_text(r.get("updated_at"), now),
                ),
            ))
        for idx, r in enumerate(norm.get("process_category_options", []) or norm.get("process_options", []) or [], start=1):
            proc = _v85_text(r.get("process_name"))
            if not proc:
                continue
            category = _norm_category_name(r.get("category_name") or PROCESS_CATEGORY_ALL)
            rid = _v85_int(r.get("id"), idx) or idx
            active = _v85_bool(r.get("is_active"), True)
            sort_order = _v87_sort_or_default(r.get("sort_order"), idx) if "_v87_sort_or_default" in globals() else (_v85_int(r.get("sort_order"), idx) or idx)
            note = _v85_text(r.get("note"))
            created = _v85_text(r.get("created_at"), now)
            updated = _v85_text(r.get("updated_at"), now)
            ops.append((
                """
                INSERT INTO process_category_options(id, category_name, process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name, process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (rid, category, proc, active, sort_order, note, created, updated),
            ))
            # 舊相容表 process_options 沒有 category 欄，若不同類別有相同工段，保留最後一次更新即可。
            ops.append((
                """
                INSERT INTO process_options(process_name, is_active, sort_order, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(process_name) DO UPDATE SET
                    is_active=excluded.is_active,
                    sort_order=excluded.sort_order,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (proc, active, sort_order, note, created, updated),
            ))
        for idx, r in enumerate(norm.get("rest_periods", []) or [], start=1):
            name = _v85_text(r.get("name")) or f"休息時間{idx}"
            start = _v85_text(r.get("start_time"))
            end = _v85_text(r.get("end_time"))
            if not start or not end:
                continue
            ops.append((
                "INSERT INTO rest_periods(id, name, start_time, end_time, is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _v85_int(r.get("id"), idx) or idx,
                    name,
                    start,
                    end,
                    _v85_bool(r.get("is_active"), True),
                    _v87_sort_or_default(r.get("sort_order"), idx) if "_v87_sort_or_default" in globals() else (_v85_int(r.get("sort_order"), idx) or idx),
                ),
            ))
        for r in norm.get("app_settings", []) or []:
            key = _v85_text(r.get("setting_key"))
            if not key:
                continue
            ops.append((
                "INSERT OR REPLACE INTO app_settings(setting_key, setting_value, note, updated_at) VALUES (?, ?, ?, ?)",
                (key, _v85_text(r.get("setting_value")), _v85_text(r.get("note")), _v85_text(r.get("updated_at"), now)),
            ))
        execute_transaction(ops, mark_changed=False, reason="13_system_settings_sqlite_cache_sync_v88", source_sql="V88_SYNC_13_SYSTEM_SETTINGS_CACHE")
        _V88_SQLITE_SYNC_HASH = fp
    except Exception:
        # 保底：若 transaction 版本在舊環境失敗，回到上一版同步方式，但仍不要中斷頁面。
        try:
            if callable(_v88_prev_v85_sync_to_sqlite):
                _v88_prev_v85_sync_to_sqlite(norm)
                _V88_SQLITE_SYNC_HASH = fp
        except Exception:
            pass


try:
    _v88_prev_v85_save_tables = _v85_save_tables
except Exception:  # pragma: no cover
    _v88_prev_v85_save_tables = None


def _v85_save_tables(tables: dict[str, list[dict[str, Any]]], reason: str) -> dict[str, Any]:  # type: ignore[override]
    """V88：保留權威檔寫入，但減少重複 cache/sync 負擔。"""
    tables = _v85_normalize_tables(tables)
    if _v85_pa_save_authority is None:
        return {"ok": False, "reason": "permanent_authority_service_not_available"}
    # 保留 GitHub write-through，避免 Reboot App 後資料消失；save_authority 本身已做 hash，沒變更不會上傳。
    res = _v85_pa_save_authority(_V85_MODULE_KEY, records=tables, reason=reason, github=True)
    _v85_sync_to_sqlite(tables)
    _v88_clear_all_system_caches()
    return res


def _v88_category_rows(active_only: bool = True) -> list[dict[str, Any]]:
    rows = [dict(r) for r in (_v85_tables().get("process_categories", []) or []) if isinstance(r, dict)]
    if active_only:
        rows = [r for r in rows if _v85_bool(r.get("is_active"), True) == 1]
    def _key(r: dict[str, Any]) -> tuple[int, int, str]:
        return (
            _v87_sort_or_default(r.get("sort_order"), 999999) if "_v87_sort_or_default" in globals() else (_v85_int(r.get("sort_order"), 999999) or 999999),
            _v85_int(r.get("id"), 999999) or 999999,
            _v85_text(r.get("category_name")),
        )
    return sorted(rows, key=_key)


def _v88_active_category_names() -> list[str]:
    tables = _v85_tables()
    fp = _v88_json_fingerprint(tables.get("process_categories", []))
    global _V88_CATEGORY_CACHE_HASH, _V88_CATEGORY_CACHE
    if _V88_CATEGORY_CACHE_HASH == fp:
        return list(_V88_CATEGORY_CACHE)
    out: list[str] = []
    seen: set[str] = set()
    for r in _v88_category_rows(active_only=True):
        name = _norm_category_name(r.get("category_name"))
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    _V88_CATEGORY_CACHE_HASH = fp
    _V88_CATEGORY_CACHE = list(out)
    return out


def load_process_category_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    """V88：只回傳權威檔內存在的類別，不再自動補回「全部 / 通用」。"""
    return _v88_active_category_names()


def get_default_process_category() -> str:  # type: ignore[override]
    """V88：預設類別若已被刪除，改用第一個現存類別；沒有類別則回傳空字串。"""
    names = _v88_active_category_names()
    tables = _v85_tables()
    val = ""
    for r in tables.get("app_settings", []) or []:
        if _v85_text(r.get("setting_key")) == DEFAULT_PROCESS_CATEGORY_KEY:
            val = _norm_category_name(r.get("setting_value"))
            break
    if val and val in names:
        return val
    return names[0] if names else ""


def save_default_process_category(category_name: str) -> str:  # type: ignore[override]
    category = _norm_category_name(category_name)
    names = _v88_active_category_names()
    if category and category not in names:
        raise ValueError(f"類別不存在或已停用：{category}")
    tables = _v85_tables()
    _v85_upsert_app_setting(tables, DEFAULT_PROCESS_CATEGORY_KEY, category, "01 工時紀錄預設類別")
    _v85_save_tables(tables, "save_default_process_category_v88")
    try:
        write_log("SAVE_DEFAULT_PROCESS_CATEGORY", f"儲存預設類別：{category}", "13_system_settings")
    except Exception:
        pass
    return category


def get_process_options_by_category(category_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    """V88：類別不存在就不回傳工段；只有「全部 / 通用」仍存在時才可作共用補充。"""
    category = _norm_category_name(category_name)
    tables = _v85_tables()
    cat_names = {_norm_category_name(r.get("category_name")) for r in tables.get("process_categories", []) or [] if _v85_bool(r.get("is_active"), True) == 1}
    if not category:
        category = get_default_process_category()
    if category and category not in cat_names:
        return []
    rows = [dict(r) for r in (tables.get("process_category_options", []) or []) if isinstance(r, dict) and _v85_bool(r.get("is_active"), True) == 1]
    def _row_key(r: dict[str, Any]) -> tuple[int, int, str]:
        return (
            _v87_sort_or_default(r.get("sort_order"), 999999) if "_v87_sort_or_default" in globals() else (_v85_int(r.get("sort_order"), 999999) or 999999),
            _v85_int(r.get("id"), 999999) or 999999,
            _v85_text(r.get("process_name")),
        )
    selected: list[str] = []
    seen: set[str] = set()
    allowed_categories: list[str] = []
    if include_common and PROCESS_CATEGORY_ALL in cat_names and category != PROCESS_CATEGORY_ALL:
        allowed_categories.append(PROCESS_CATEGORY_ALL)
    if category:
        allowed_categories.append(category)
    for r in sorted(rows, key=_row_key):
        cat = _norm_category_name(r.get("category_name") or PROCESS_CATEGORY_ALL)
        if cat not in allowed_categories:
            continue
        name = _v85_text(r.get("process_name"))
        if name and name not in seen:
            seen.add(name)
            selected.append(name)
    return selected


def get_process_options_by_category_exact(category_name: str | None = None) -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(category_name, include_common=False)


def get_process_options() -> list[str]:  # type: ignore[override]
    return get_process_options_by_category(get_default_process_category(), include_common=True)


def delete_process_categories(ids: Iterable[int]) -> int:  # type: ignore[override]
    """V88：允許刪除「全部 / 通用」，並同步刪除該類別底下工段。"""
    tables = _v85_tables()
    ids_set: set[str] = set()
    for x in ids or []:
        n = _v87_clean_input_id(x) if "_v87_clean_input_id" in globals() else _v85_int(x, None)
        if n is not None:
            ids_set.add(str(n))
    if not ids_set:
        return 0

    old_cats = [dict(r) for r in tables.get("process_categories", []) or [] if isinstance(r, dict)]
    removed_names: set[str] = set()
    kept_cats: list[dict[str, Any]] = []
    for r in old_cats:
        rid = _v87_clean_input_id(r.get("id")) if "_v87_clean_input_id" in globals() else _v85_int(r.get("id"), None)
        if rid is not None and str(rid) in ids_set:
            name = _norm_category_name(r.get("category_name"))
            if name:
                removed_names.add(name)
        else:
            kept_cats.append(r)
    if not removed_names:
        return 0

    tables["process_categories"] = kept_cats
    tables["process_category_options"] = [
        dict(r) for r in tables.get("process_category_options", []) or []
        if _norm_category_name(r.get("category_name") or PROCESS_CATEGORY_ALL) not in removed_names
    ]
    tables["process_options"] = list(tables.get("process_category_options", []) or [])

    # 若預設類別被刪除，改成第一個剩餘啟用類別；沒有剩餘就存空字串，不再補回「全部 / 通用」。
    active_after: list[str] = []
    for r in sorted(tables.get("process_categories", []) or [], key=lambda x: (_v85_int(x.get("sort_order"), 999999) or 999999, _v85_int(x.get("id"), 999999) or 999999)):
        if _v85_bool(r.get("is_active"), True) == 1:
            name = _norm_category_name(r.get("category_name"))
            if name:
                active_after.append(name)
    current_default = ""
    for r in tables.get("app_settings", []) or []:
        if _v85_text(r.get("setting_key")) == DEFAULT_PROCESS_CATEGORY_KEY:
            current_default = _norm_category_name(r.get("setting_value"))
            break
    if current_default in removed_names or (current_default and current_default not in active_after):
        _v85_upsert_app_setting(tables, DEFAULT_PROCESS_CATEGORY_KEY, active_after[0] if active_after else "", "01 工時紀錄預設類別")

    _v85_save_tables(tables, "delete_process_categories_v88")
    try:
        write_log("DELETE_PROCESS_CATEGORIES", f"刪除類別 {len(removed_names)} 筆：{', '.join(sorted(removed_names))}", "13_system_settings", level="WARN")
    except Exception:
        pass
    return len(removed_names)

# ===================== END V88 13 SYSTEM SETTINGS SPEED + DELETE COMMON CATEGORY FIX =====================

# ===================== V156 SYSTEM SETTINGS READ CACHE =====================
# 目的：01/03/13 等頁面頻繁讀取工段、類別、休息時間設定。這些設定讀多寫少，
# 依 13_system_settings 權威檔 mtime 快取可降低切頁與下拉載入時間。資料寫入後檔案 mtime 變更即自動失效。
try:
    import copy as _v156_sys_copy
except Exception:
    _v156_sys_copy = None

_V156_SYS_CACHE: dict[tuple, tuple[tuple, object]] = {}


def _v156_sys_sig() -> tuple:
    try:
        from services.permanent_authority_service import canonical_path as _pa_path
        paths = [_pa_path('13_system_settings', 'records'), _pa_path('13_system_settings', 'settings')]
        out = []
        for p in paths:
            try:
                stt = p.stat(); out.append((str(p), int(stt.st_mtime_ns), int(stt.st_size)))
            except Exception:
                out.append((str(p), 0, -1))
        return tuple(out)
    except Exception:
        return ('system-settings-no-sig',)


def _v156_sys_copy_value(v):
    try:
        if hasattr(v, 'copy'):
            return v.copy(deep=True) if v.__class__.__name__ == 'DataFrame' else v.copy()
    except Exception:
        pass
    try:
        return _v156_sys_copy.deepcopy(v) if _v156_sys_copy is not None else v
    except Exception:
        return v


def _v156_sys_cached(key: tuple, loader):
    sig = _v156_sys_sig()
    got = _V156_SYS_CACHE.get(key)
    if got and got[0] == sig:
        return _v156_sys_copy_value(got[1])
    val = loader()
    try:
        _V156_SYS_CACHE[key] = (sig, _v156_sys_copy_value(val))
    except Exception:
        pass
    return _v156_sys_copy_value(val)


def clear_system_settings_read_cache() -> None:
    try:
        _V156_SYS_CACHE.clear()
    except Exception:
        pass


_v156_prev_load_process_categories_df = load_process_categories_df
_v156_prev_load_process_options_df = load_process_options_df
_v156_prev_load_rest_periods_df = load_rest_periods_df
_v156_prev_load_process_category_choices = load_process_category_choices
_v156_prev_get_process_options_by_category = get_process_options_by_category
_v156_prev_get_process_options_by_category_exact = get_process_options_by_category_exact
_v156_prev_get_process_options = get_process_options
_v156_prev_get_live_page_reset_time = get_live_page_reset_time
try:
    _v156_prev_load_process_model_choices = load_process_model_choices
except Exception:
    _v156_prev_load_process_model_choices = None
try:
    _v156_prev_get_process_options_by_model = get_process_options_by_model
except Exception:
    _v156_prev_get_process_options_by_model = None


def load_process_categories_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    return _v156_sys_cached(('categories_df', bool(active_only)), lambda: _v156_prev_load_process_categories_df(active_only=active_only))


def load_process_options_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    return _v156_sys_cached(('process_options_df', bool(active_only)), lambda: _v156_prev_load_process_options_df(active_only=active_only))


def load_rest_periods_df(active_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    return _v156_sys_cached(('rest_periods_df', bool(active_only)), lambda: _v156_prev_load_rest_periods_df(active_only=active_only))


def load_process_category_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
    return _v156_sys_cached(('category_choices', bool(include_common)), lambda: _v156_prev_load_process_category_choices(include_common=include_common))


def get_process_options_by_category(category_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
    return _v156_sys_cached(('options_by_category', str(category_name or ''), bool(include_common)), lambda: _v156_prev_get_process_options_by_category(category_name=category_name, include_common=include_common))


def get_process_options_by_category_exact(category_name: str | None = None) -> list[str]:  # type: ignore[override]
    return _v156_sys_cached(('options_by_category_exact', str(category_name or '')), lambda: _v156_prev_get_process_options_by_category_exact(category_name=category_name))


def get_process_options() -> list[str]:  # type: ignore[override]
    return _v156_sys_cached(('process_options',), lambda: _v156_prev_get_process_options())


def get_live_page_reset_time() -> str:  # type: ignore[override]
    return _v156_sys_cached(('live_page_reset_time',), lambda: _v156_prev_get_live_page_reset_time())


if callable(_v156_prev_load_process_model_choices):
    def load_process_model_choices(include_common: bool = True) -> list[str]:  # type: ignore[override]
        return _v156_sys_cached(('model_choices', bool(include_common)), lambda: _v156_prev_load_process_model_choices(include_common=include_common))

if callable(_v156_prev_get_process_options_by_model):
    def get_process_options_by_model(type_name: str | None = None, include_common: bool = True) -> list[str]:  # type: ignore[override]
        return _v156_sys_cached(('options_by_model', str(type_name or ''), bool(include_common)), lambda: _v156_prev_get_process_options_by_model(type_name=type_name, include_common=include_common))
# =================== END V156 SYSTEM SETTINGS READ CACHE ===================
