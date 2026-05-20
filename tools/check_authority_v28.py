# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json, sys
ROOT = Path(__file__).resolve().parents[1]
# Ensure project root import path
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from services.permanent_authority_service import load_authority, authority_health
MODS = ["01_time_records","02_history","03_work_orders","04_employees","05_analysis","06_logs","06_system_logs","07_missing","07_missing_records","08_daily_hours","10_permissions","11_login_logs","13_system_settings","ui_table_settings"]

def main():
    ok = True
    for m in MODS:
        for k in ["records", "settings"]:
            try:
                data = load_authority(m, k)  # triggers one-time migration from legacy latest if needed
                p = ROOT / "data" / "permanent_store" / "modules" / m / f"{k}.json"
                exists = p.exists()
                print(f"{m}/{k}: {'OK' if exists else 'MISSING'} {p.relative_to(ROOT)}")
                print('  schema=', data.get('authority_schema'), 'updated_at=', data.get('updated_at'), 'counts=', data.get('table_counts'))
                if not exists: ok = False
            except Exception as e:
                print(f"{m}/{k}: ERROR {e}"); ok = False
    print('\nManifest:')
    print(json.dumps(authority_health(), ensure_ascii=False, indent=2)[:3000])
    return 0 if ok else 1
if __name__ == '__main__': raise SystemExit(main())
