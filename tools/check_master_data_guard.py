# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import json
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
PERSIST = ROOT / "data" / "permanent_store" / "persistent_modules"

TARGETS = {
    "work_orders": PERSIST / "03_work_orders" / "03_work_orders_records.json",
    "employees": PERSIST / "04_employees" / "04_employees_records.json",
}


def db_count(table: str) -> int:
    if not DB.exists():
        return -1
    try:
        with sqlite3.connect(DB) as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(row[0] if row else 0)
    except Exception:
        return -1


def json_count(table: str, path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("tables", {}).get(table, [])
        return len(rows) if isinstance(rows, list) else 0
    except Exception:
        return -1


def main() -> int:
    print("SPT Master Data Guard Check")
    print(f"Project: {ROOT}")
    print(f"DB: {DB} exists={DB.exists()}")
    for table, path in TARGETS.items():
        print(f"{table}: db_count={db_count(table)}, json_count={json_count(table, path)}, json={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
