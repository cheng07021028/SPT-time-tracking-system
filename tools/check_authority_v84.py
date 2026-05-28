# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json, sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.permanent_authority_service import load_authority, canonical_path

MODS = [
    "01_time_records", "02_history", "03_work_orders", "04_employees", "05_analysis",
    "06_logs", "06_system_logs", "07_missing", "07_missing_records", "08_daily_hours",
    "10_permissions", "11_login_logs", "13_system_settings", "ui_table_settings",
]

def main() -> int:
    ok = True
    for m in MODS:
        for k in ["records", "settings"]:
            p = canonical_path(m, k)
            try:
                payload = load_authority(m, k)
                exists = p.exists()
                print(f"{m}/{k}: {'OK' if exists else 'CREATED'} {p.relative_to(ROOT)} counts={payload.get('table_counts', {})} updated_at={payload.get('updated_at')}")
                if not exists:
                    ok = False
            except Exception as exc:
                print(f"{m}/{k}: ERROR {exc}")
                ok = False
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
