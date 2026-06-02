# -*- coding: utf-8 -*-
"""
SPT Time Tracking - V1.47 Data Guard Service
目的：避免 Streamlit Cloud / 更新模組後 SQLite 空白時，03/04 等核心資料表顯示空白。
策略：
1) 讀 SQLite。若核心表為空，嘗試從獨立永久檔 / latest 永久檔 / history 最新檔還原。
2) 永不以空資料覆蓋既有永久檔。
3) 本服務不連 GitHub API，避免切頁變慢；GitHub 同步仍由 09/12 頁手動處理。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
STATE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state"
MODULE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_modules"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _count_table(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    except Exception:
        return 0


def _read_json(path: Path) -> Any | None:
    try:
        if path.exists() and path.stat().st_size > 0:
            try:
                from services.persistence_guard_service import safe_load_json
                return safe_load_json(path, None, allow_default_when_missing=True)
            except Exception:
                return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _backup_relative_sources(rel_path: str) -> list[Path]:
    out: list[Path] = []
    try:
        from services.persistence_guard_service import list_all_persistent_backups
        for backup in list_all_persistent_backups(include_external=True):
            p = backup / rel_path
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                out.append(p)
    except Exception:
        pass
    return out


def _latest_file(patterns: Iterable[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(PROJECT_ROOT.glob(pattern))
    candidates = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _extract_records(payload: Any, table: str) -> list[dict[str, Any]]:
    """Flexible extraction from different permanent-file formats."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []

    # common formats
    direct_keys = [table, f"{table}_records", "records", "data"]
    for key in direct_keys:
        val = payload.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]

    tables = payload.get("tables") or payload.get("data_tables") or payload.get("sqlite_tables")
    if isinstance(tables, dict):
        val = tables.get(table)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            inner = val.get("records") or val.get("rows") or val.get("data")
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]

    # module permanent format may be {module_code:{records:[...]}}
    for val in payload.values():
        if isinstance(val, dict):
            inner = _extract_records(val, table)
            if inner:
                return inner
    return []


def _employee_sources() -> list[Path]:
    sources = [
        MODULE_DIR / "04_employees" / "04_employees_records.json",
        STATE_DIR / "spt_permanent_state.json",
    ]
    latest = _latest_file([
        "data/permanent_store/persistent_modules/04_employees/history/*employees*records*.json",
        "data/permanent_store/persistent_state/history/spt_permanent_state_*.json",
        "data/permanent_store/persistent_state/archive/spt_permanent_state_*.json",
    ])
    if latest:
        sources.append(latest)
    sources.extend(_backup_relative_sources("data/permanent_store/persistent_modules/04_employees/04_employees_records.json"))
    sources.extend(_backup_relative_sources("data/permanent_store/persistent_state/spt_permanent_state.json"))
    return sources


def _work_order_sources() -> list[Path]:
    sources = [
        MODULE_DIR / "03_work_orders" / "03_work_orders_records.json",
        STATE_DIR / "spt_permanent_state.json",
    ]
    latest = _latest_file([
        "data/permanent_store/persistent_modules/03_work_orders/history/*work_orders*records*.json",
        "data/permanent_store/persistent_state/history/spt_permanent_state_*.json",
        "data/permanent_store/persistent_state/archive/spt_permanent_state_*.json",
    ])
    if latest:
        sources.append(latest)
    sources.extend(_backup_relative_sources("data/permanent_store/persistent_modules/03_work_orders/03_work_orders_records.json"))
    sources.extend(_backup_relative_sources("data/permanent_store/persistent_state/spt_permanent_state.json"))
    return sources


def _ensure_employees_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT UNIQUE NOT NULL,
        employee_name TEXT NOT NULL,
        department TEXT,
        title TEXT,
        is_active INTEGER DEFAULT 1,
        is_in_factory INTEGER DEFAULT 1,
        is_today_attendance INTEGER DEFAULT 1,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)


def _ensure_work_orders_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_order TEXT UNIQUE NOT NULL,
        part_no TEXT,
        type_name TEXT,
        assembly_location TEXT,
        customer TEXT,
        note TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)


def _first(row: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for k in keys:
        if k in row and row.get(k) not in (None, ""):
            return row.get(k)
    return default


def _bool_int(v: Any, default: int = 1) -> int:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return 1 if v else 0
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "是", "啟用", "在職", "active"}:
        return 1
    if s in {"0", "false", "no", "n", "否", "停用", "離職", "inactive"}:
        return 0
    return default


def restore_employees_if_empty(force: bool = False) -> dict[str, Any]:
    conn = _connect()
    _ensure_employees_table(conn)
    before = _count_table(conn, "employees")
    if before > 0 and not force:
        conn.close()
        return {"ok": True, "skipped": True, "table": "employees", "before": before, "restored": 0, "message": "employees already has data"}

    restored = 0
    used = None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for src in _employee_sources():
        payload = _read_json(src)
        records = _extract_records(payload, "employees")
        if not records:
            continue
        for r in records:
            emp_id = str(_first(r, ["employee_id", "工號", "Employee ID", "username"], "")).strip()
            name = str(_first(r, ["employee_name", "姓名", "Name", "display_name"], "")).strip()
            if not emp_id or not name:
                continue
            conn.execute("""
            INSERT INTO employees
            (employee_id, employee_name, department, title, is_active, is_in_factory, is_today_attendance, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id) DO UPDATE SET
                employee_name=excluded.employee_name,
                department=excluded.department,
                title=excluded.title,
                is_active=excluded.is_active,
                is_in_factory=excluded.is_in_factory,
                is_today_attendance=excluded.is_today_attendance,
                note=excluded.note,
                updated_at=excluded.updated_at
            """, (
                emp_id,
                name,
                _first(r, ["department", "單位", "Department"], ""),
                _first(r, ["title", "職稱", "Title"], ""),
                _bool_int(_first(r, ["is_active", "啟用", "Active"], 1), 1),
                _bool_int(_first(r, ["is_in_factory", "在廠", "In Factory"], 1), 1),
                _bool_int(_first(r, ["is_today_attendance", "今日出勤", "Today Attendance"], 1), 1),
                _first(r, ["note", "備註", "Note"], ""),
                _first(r, ["created_at", "建立時間", "Created At"], now),
                now,
            ))
            restored += 1
        if restored:
            used = str(src.relative_to(PROJECT_ROOT))
            break
    conn.commit()
    after = _count_table(conn, "employees")
    conn.close()
    return {"ok": restored > 0, "table": "employees", "before": before, "after": after, "restored": restored, "source": used}


def restore_work_orders_if_empty(force: bool = False) -> dict[str, Any]:
    conn = _connect()
    _ensure_work_orders_table(conn)
    before = _count_table(conn, "work_orders")
    if before > 0 and not force:
        conn.close()
        return {"ok": True, "skipped": True, "table": "work_orders", "before": before, "restored": 0, "message": "work_orders already has data"}

    restored = 0
    used = None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for src in _work_order_sources():
        payload = _read_json(src)
        records = _extract_records(payload, "work_orders")
        if not records:
            continue
        for r in records:
            wo = str(_first(r, ["work_order", "製令", "Work Order", "WO", "MO"], "")).strip()
            if not wo:
                continue
            conn.execute("""
            INSERT INTO work_orders
            (work_order, part_no, type_name, assembly_location, customer, note, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_order) DO UPDATE SET
                part_no=excluded.part_no,
                type_name=excluded.type_name,
                assembly_location=excluded.assembly_location,
                customer=excluded.customer,
                note=excluded.note,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
            """, (
                wo,
                _first(r, ["part_no", "P/N", "Part No", "料號"], ""),
                _first(r, ["type_name", "Type", "機型"], ""),
                _first(r, ["assembly_location", "組立地點", "Assembly Location"], ""),
                _first(r, ["customer", "客戶", "Customer"], ""),
                _first(r, ["note", "備註", "Note"], ""),
                _bool_int(_first(r, ["is_active", "啟用", "Active"], 1), 1),
                _first(r, ["created_at", "建立時間", "Created At"], now),
                now,
            ))
            restored += 1
        if restored:
            used = str(src.relative_to(PROJECT_ROOT))
            break
    conn.commit()
    after = _count_table(conn, "work_orders")
    conn.close()
    return {"ok": restored > 0, "table": "work_orders", "before": before, "after": after, "restored": restored, "source": used}


def ensure_core_data(tables: Iterable[str] | None = None) -> dict[str, Any]:
    tables = list(tables or ["employees", "work_orders"])
    result: dict[str, Any] = {}
    if "employees" in tables:
        result["employees"] = restore_employees_if_empty(force=False)
    if "work_orders" in tables:
        result["work_orders"] = restore_work_orders_if_empty(force=False)
    return result


if __name__ == "__main__":
    print(json.dumps(ensure_core_data(), ensure_ascii=False, indent=2))
