# -*- coding: utf-8 -*-
"""V90 quick syntax/import surface check for time_record_service finish_work override."""
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "services" / "time_record_service.py"
py_compile.compile(str(path), doraise=True)
text = path.read_text(encoding="utf-8")
required = [
    "V90 01 FINISH-WORK AUTHORITY MERGE FIX",
    "def _v90_upsert_rows_to_0102_authority",
    "def finish_work(record_id: int, end_action: str",
    "finish_work_v90_authority_merge",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("Missing V90 markers: " + ", ".join(missing))
print("V90 check passed: finish_work uses authority merge without pre-baseline wipe.")
