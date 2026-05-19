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
    _ensure_process_category_options_table()
    category = _norm_category_name(category_name)

    def _names_for(where_sql: str, params: tuple[Any, ...]) -> list[str]:
        try:
            df = query_df(
                f"SELECT process_name FROM process_category_options WHERE COALESCE(is_active,1)=1 AND {where_sql} ORDER BY sort_order, id",
                params,
            )
            return [str(x).strip() for x in df.get("process_name", []).dropna().tolist() if str(x).strip()] if df is not None and not df.empty else []
        except Exception:
            return []

    common_names = _names_for("(category_name=? OR COALESCE(category_name,'')='')", (PROCESS_CATEGORY_ALL,)) if include_common else []
    category_names = [] if category == PROCESS_CATEGORY_ALL else _names_for("category_name=?", (category,))
    names = common_names + [n for n in category_names if n not in common_names]
    if names:
        return names

    default_category = get_default_process_category()
    if default_category and default_category not in {PROCESS_CATEGORY_ALL, category}:
        default_names = _names_for("category_name=?", (default_category,))
        names = common_names + [n for n in default_names if n not in common_names]
        if names:
            return names

    try:
        df = query_df("SELECT process_name FROM process_category_options WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, id")
        names = []
        for x in df.get("process_name", []).dropna().tolist() if df is not None and not df.empty else []:
            s = str(x).strip()
            if s and s not in names:
                names.append(s)
        if names:
            return names
    except Exception:
        pass
    return DEFAULT_PROCESS_OPTIONS.copy()


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

# ===== V3.46 final system settings persistence hardening =====
# 目的：13｜系統設定的「類別與工段名稱設定」在 Reboot App 後不再被預設資料遮蔽。
# 不新增畫面功能；只修正既有永久檔 export/restore 與 schema 初始化順序。

def _v346_ensure_category_tables_basic() -> None:
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


def _v346_tables_empty_or_default(table_name: str) -> bool:
    try:
        c = _table_count(table_name)
    except Exception:
        c = 0
    if c == 0:
        return True
    if table_name == "process_categories":
        try:
            row = query_one("SELECT COUNT(*) AS c FROM process_categories WHERE category_name<>?", (PROCESS_CATEGORY_ALL,)) or {"c": 0}
            return int(row.get("c") or 0) == 0
        except Exception:
            return False
    return False


def _v346_insert_category_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    now = _now()
    for idx, r in enumerate(rows or [], start=1):
        if not isinstance(r, dict):
            continue
        name = _norm_category_name(r.get("category_name") or r.get("類別") or r.get("category"))
        if not name:
            continue
        active_raw = str(r.get("is_active", 1)).strip().lower()
        active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(r.get("sort_order") or idx))
        except Exception:
            sort_order = idx
        execute(
            """
            INSERT INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(category_name) DO UPDATE SET
                is_active=excluded.is_active,
                sort_order=excluded.sort_order,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (name, active, sort_order, str(r.get("note") or ""), str(r.get("created_at") or now), str(r.get("updated_at") or now)),
        )
        count += 1
    return count


def _v346_insert_category_process_rows(rows: list[dict[str, Any]]) -> int:
    count = 0
    now = _now()
    for idx, r in enumerate(rows or [], start=1):
        if not isinstance(r, dict):
            continue
        proc_name = str(r.get("process_name") or r.get("工段名稱") or r.get("工段名稱 / Process") or "").strip()
        if not proc_name:
            continue
        category = _norm_category_name(r.get("category_name") or r.get("type_name") or r.get("類別") or PROCESS_CATEGORY_ALL)
        active_raw = str(r.get("is_active", 1)).strip().lower()
        active = 0 if active_raw in {"0", "false", "no", "n", "off", "停用", "否"} else 1
        try:
            sort_order = int(float(r.get("sort_order") or idx))
        except Exception:
            sort_order = idx
        execute(
            """
            INSERT INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(category_name, process_name) DO UPDATE SET
                is_active=excluded.is_active,
                sort_order=excluded.sort_order,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (category, proc_name, active, sort_order, str(r.get("note") or ""), str(r.get("created_at") or now), str(r.get("updated_at") or now)),
        )
        count += 1
    return count


def restore_system_settings_from_permanent(force: bool = False) -> dict[str, Any]:  # type: ignore[override]
    _basic_create_tables()
    _v346_ensure_category_tables_basic()
    payload = _load_latest_persistent_payload()
    if not payload:
        return {"ok": False, "restored": {}, "message": "找不到 13 系統設定永久檔"}
    tables = payload.get("tables", {}) if isinstance(payload.get("tables"), dict) else {}
    restored: dict[str, int] = {}

    cat_rows = tables.get("process_categories", []) if isinstance(tables.get("process_categories"), list) else []
    cat_proc_rows = tables.get("process_category_options", []) if isinstance(tables.get("process_category_options"), list) else []
    if not cat_proc_rows and isinstance(tables.get("process_options"), list):
        cat_proc_rows = tables.get("process_options", []) or []
    rest_rows = tables.get("rest_periods", []) if isinstance(tables.get("rest_periods"), list) else []
    app_rows = tables.get("app_settings", []) if isinstance(tables.get("app_settings"), list) else []

    if force or (_v346_tables_empty_or_default("process_categories") and cat_rows):
        if force:
            try: execute("DELETE FROM process_categories")
            except Exception: pass
        restored["process_categories"] = _v346_insert_category_rows(cat_rows)
    if force or (_table_count("process_category_options") == 0 and cat_proc_rows):
        if force:
            try: execute("DELETE FROM process_category_options")
            except Exception: pass
        restored["process_category_options"] = _v346_insert_category_process_rows(cat_proc_rows)
    if force or (_table_count("rest_periods") == 0 and rest_rows):
        if force:
            try: execute("DELETE FROM rest_periods")
            except Exception: pass
        restored["rest_periods"] = _insert_rest_rows(rest_rows)
    if force or (not _has_live_page_reset_setting() and app_rows):
        if force:
            try: execute("DELETE FROM app_settings WHERE setting_key IN ('live_page_reset_time', 'default_process_category')")
            except Exception: pass
        restored["app_settings"] = _insert_app_settings_rows(app_rows)
    if restored:
        _clear_settings_cache()
    return {"ok": bool(restored), "restored": restored, "source": payload.get("_source", "system_settings_json"), "score": payload.get("_score")}


def export_system_settings_permanent(reason: str = "system_settings_changed", write_history: bool = True) -> dict[str, Any]:  # type: ignore[override]
    _basic_create_tables()
    _v346_ensure_category_tables_basic()
    _ensure_permanent_dirs()
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
        "version": "V3.46",
        "exported_at": _now(),
        "reason": reason,
        "description": "13｜系統設定永久紀錄：類別、類別對應工段、休息時間、01 工時紀錄每日重新整理時間。",
        "tables": {
            "process_categories": _df_records(cats),
            "process_category_options": _df_records(proc),
            # Compatibility: older restore code reads process_options.
            "process_options": _df_records(proc),
            "rest_periods": _df_records(rest),
            "app_settings": _df_records(app),
        },
        "table_counts": {
            "process_categories": 0 if cats is None else len(cats),
            "process_category_options": 0 if proc is None else len(proc),
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
    return {"ok": True, "files": [str(p) for p in SYSTEM_SETTINGS_FILES], "table_counts": payload["table_counts"], "payload_version": "V3.46"}


def ensure_system_settings_schema() -> None:  # type: ignore[override]
    global _SYSTEM_SETTINGS_SCHEMA_READY, _RESTORE_FROM_FILE_DONE
    if _SYSTEM_SETTINGS_SCHEMA_READY:
        return
    _basic_create_tables()
    _v346_ensure_category_tables_basic()
    if not _RESTORE_FROM_FILE_DONE:
        try:
            restore_system_settings_from_permanent(force=False)
        except Exception:
            pass
        _RESTORE_FROM_FILE_DONE = True
    now = _now()
    try:
        if _table_count("process_categories") == 0:
            execute(
                """
                INSERT OR IGNORE INTO process_categories(category_name,is_active,sort_order,note,created_at,updated_at)
                VALUES (?,1,0,'所有類別共用工段',?,?)
                """,
                (PROCESS_CATEGORY_ALL, now, now),
            )
    except Exception:
        pass
    try:
        if _table_count("process_category_options") == 0:
            for idx, name in enumerate(DEFAULT_PROCESS_OPTIONS, start=1):
                execute(
                    """
                    INSERT OR IGNORE INTO process_category_options(category_name,process_name,is_active,sort_order,note,created_at,updated_at)
                    VALUES (?,?,1,?,'系統預設工段，可於 13 系統設定修改',?,?)
                    """,
                    (PROCESS_CATEGORY_ALL, name, idx, now, now),
                )
    except Exception:
        pass
    try:
        if _table_count("rest_periods") == 0:
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
