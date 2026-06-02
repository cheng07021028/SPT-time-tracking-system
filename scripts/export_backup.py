from __future__ import annotations

from pathlib import Path
import csv
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spt_core.db import fetch_all, transaction, init_db
from spt_core.utils import now_dt

TABLES = ["employees", "work_orders", "processes", "system_settings", "time_records", "operation_logs", "login_events", "delete_events", "users"]


def export_table(conn, table: str, out_dir: Path) -> None:
    rows = fetch_all(conn, f"SELECT * FROM {table}")
    path = out_dir / f"{table}.csv"
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    init_db()
    out_dir = ROOT / "exports" / now_dt().strftime("backup_%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    with transaction() as conn:
        for table in TABLES:
            export_table(conn, table, out_dir)
    print(f"Exported backup to {out_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
