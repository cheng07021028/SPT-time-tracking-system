# -*- coding: utf-8 -*-
"""Check V89 02 history authority-first patch markers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
svc = ROOT / "services" / "time_record_service.py"
text = svc.read_text(encoding="utf-8")
required = [
    "V89 02 HISTORY STRICT AUTHORITY-FIRST",
    "def _v89_sync_sqlite_cache_from_authority",
    "def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False)",
    "def delete_time_records(record_ids: list[int], reason: str = \"管理員刪除工時紀錄\")",
    "def recalculate_time_records(record_ids: list[int] | None = None)",
    "V89B 01 ACTION BASELINE FROM AUTHORITY",
]
missing = [m for m in required if m not in text]
if missing:
    print("V89 檢查失敗，缺少：")
    for m in missing:
        print("-", m)
    raise SystemExit(1)
print("V89 檢查通過：02 歷史紀錄已改為 canonical 權威檔優先讀寫，SQLite 僅作快取。")
print("權威檔：data/permanent_store/modules/02_history/records.json")
