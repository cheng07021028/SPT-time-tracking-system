# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.db_service import ensure_database
from services.persistence_service import restore_latest_available_state, export_permanent_state, database_business_row_count, connect_db

if __name__ == "__main__":
    print("============================================")
    print("SPT V1.23 - Recover Data From Persistent Files")
    print("============================================")
    ensure_database()
    with connect_db() as conn:
        before = database_business_row_count(conn)
    print(f"Before restore business rows: {before}")
    result = restore_latest_available_state(mode="replace")
    print(result)
    with connect_db() as conn:
        after = database_business_row_count(conn)
    print(f"After restore business rows: {after}")
    if after > 0:
        export_permanent_state(include_logs=True, force=True)
        print("Permanent state refreshed.")
    else:
        print("No recoverable rows found. If you did not run pre_update_backup or GitHub backup before updating, the lost data may not be recoverable from this project folder.")
    print("============================================")
