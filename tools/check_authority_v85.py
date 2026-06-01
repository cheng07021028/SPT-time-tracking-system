# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json, sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AUTH = ROOT / "data" / "permanent_store" / "modules" / "13_system_settings" / "records.json"


def main() -> int:
    print("SPT V85 - 13 系統設定權威檔檢查")
    print("authority:", AUTH.relative_to(ROOT))
    if not AUTH.exists():
        print("MISSING: 權威檔尚未建立。請先進入 13. 系統設定按一次套用存檔。")
        return 1
    try:
        data = json.loads(AUTH.read_text(encoding="utf-8"))
    except Exception as exc:
        print("ERROR: JSON 讀取失敗:", exc)
        return 2
    tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
    for t in ["process_categories", "process_category_options", "process_options", "rest_periods", "app_settings"]:
        rows = tables.get(t, []) if isinstance(tables.get(t), list) else []
        print(f"{t}: {len(rows)}")
    print("schema:", data.get("authority_schema"))
    print("module_key:", data.get("module_key"))
    print("updated_at:", data.get("updated_at"))
    print("reason:", data.get("reason"))
    print("OK: 13. 系統設定目前使用單一 records 權威檔。")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
