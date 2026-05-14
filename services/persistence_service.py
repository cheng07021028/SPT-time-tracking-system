# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.20 - Persistent Data Service
用途：
1. 將 SQLite 重要資料表永久匯出成 JSON。
2. 將模組設定、欄寬、排序、UI 狀態匯出成 JSON。
3. 更新程式後可從 JSON 還原，不會每次改版都重新輸入。

注意：
- data/database/*.db 仍建議不要上 GitHub，避免二進位資料庫衝突。
- data/persistent_state/*.json 可上 GitHub，作為永久保存與跨版本還原來源。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
ARCHIVE_DIR = STATE_DIR / "archive"
STATE_JSON = STATE_DIR / "spt_permanent_state.json"
SETTINGS_JSON = STATE_DIR / "spt_module_settings.json"
DB_COPY_DIR = STATE_DIR / "db_copy"

DEFAULT_TABLES = [
    "work_orders",
    "employees",
    "time_records",
    "system_logs",
    "rest_periods",
    "system_settings",
]

SETTING_TABLE_CANDIDATES = [
    "module_settings",
    "table_column_settings",
    "column_width_settings",
    "table_sort_settings",
    "user_table_settings",
    "page_settings",
    "ui_settings",
    "system_settings",
]


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    DB_COPY_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_existing_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r["name"] for r in rows if not str(r["name"]).startswith("sqlite_")]


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def export_table(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table_name):
        return []
    rows = conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
    return rows_to_dicts(rows)


def export_permanent_state(include_logs: bool = True) -> dict[str, Any]:
    """匯出所有主資料與設定到 JSON。"""
    _ensure_dirs()
    if not DB_PATH.exists():
        state = {"version": "V1.20", "exported_at": _now(), "db_exists": False, "tables": {}}
        STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state

    conn = connect_db()
    try:
        existing = get_existing_tables(conn)
        tables = {}
        for table in existing:
            if not include_logs and table == "system_logs":
                continue
            tables[table] = export_table(conn, table)

        state = {
            "version": "V1.20",
            "exported_at": _now(),
            "db_path": str(DB_PATH),
            "db_exists": True,
            "tables": tables,
        }
        if STATE_JSON.exists():
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(STATE_JSON, ARCHIVE_DIR / f"spt_permanent_state_{_stamp()}.json")
        STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        # 另外匯出模組設定候選表，方便快速比對。
        settings_tables = {}
        for table in SETTING_TABLE_CANDIDATES:
            if table_exists(conn, table):
                settings_tables[table] = export_table(conn, table)
        SETTINGS_JSON.write_text(
            json.dumps({"version": "V1.20", "exported_at": _now(), "tables": settings_tables}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 同步保留一份 DB copy，不建議上傳 GitHub，但本機可救援。
        if DB_PATH.exists():
            shutil.copy2(DB_PATH, DB_COPY_DIR / "spt_time_tracking_latest.db")
            shutil.copy2(DB_PATH, DB_COPY_DIR / f"spt_time_tracking_{_stamp()}.db")
        return state
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [r["name"] for r in rows]


def _insert_rows(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, Any]], mode: str = "replace") -> int:
    if not rows or not table_exists(conn, table_name):
        return 0
    columns = _table_columns(conn, table_name)
    valid_rows = []
    for row in rows:
        filtered = {k: v for k, v in row.items() if k in columns}
        if filtered:
            valid_rows.append(filtered)
    if not valid_rows:
        return 0

    if mode == "replace":
        conn.execute(f'DELETE FROM "{table_name}"')

    count = 0
    for row in valid_rows:
        keys = list(row.keys())
        placeholders = ",".join(["?"] * len(keys))
        col_sql = ",".join([f'"{k}"' for k in keys])
        sql = f'INSERT OR REPLACE INTO "{table_name}" ({col_sql}) VALUES ({placeholders})'
        conn.execute(sql, [row[k] for k in keys])
        count += 1
    return count


def restore_permanent_state(json_path: str | Path | None = None, mode: str = "replace") -> dict[str, Any]:
    """從 JSON 還原資料。mode='replace' 會先清空表再匯入。"""
    _ensure_dirs()
    target = Path(json_path) if json_path else STATE_JSON
    if not target.exists():
        return {"ok": False, "message": f"找不到永久保存檔：{target}"}

    state = json.loads(target.read_text(encoding="utf-8"))
    tables = state.get("tables", {})
    if not isinstance(tables, dict):
        return {"ok": False, "message": "永久保存檔格式錯誤：tables 不存在"}

    conn = connect_db()
    restored = {}
    try:
        for table_name, rows in tables.items():
            if isinstance(rows, list) and table_exists(conn, table_name):
                restored[table_name] = _insert_rows(conn, table_name, rows, mode=mode)
        conn.commit()
        return {"ok": True, "restored": restored, "source": str(target)}
    finally:
        conn.close()


def write_gitkeep() -> None:
    _ensure_dirs()
    (STATE_DIR / ".gitkeep").write_text("", encoding="utf-8")


if __name__ == "__main__":
    result = export_permanent_state(include_logs=True)
    print("Permanent state exported:", STATE_JSON)
    print("Tables:", ", ".join(result.get("tables", {}).keys()))
