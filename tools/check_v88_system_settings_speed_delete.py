# -*- coding: utf-8 -*-
"""V88 quick static check for 13 system settings speed/delete patch."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "services" / "system_settings_service.py"
text = TARGET.read_text(encoding="utf-8")
required = [
    "V88 13 SYSTEM SETTINGS SPEED + DELETE COMMON CATEGORY FIX",
    "def _v85_sync_to_sqlite",
    "execute_transaction(ops, mark_changed=False",
    "def delete_process_categories",
    "允許刪除「全部 / 通用」",
    "def load_process_category_choices",
    "不再自動補回「全部 / 通用」",
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit("V88 check failed, missing: " + ", ".join(missing))
print("V88 check OK: 13 系統設定加速與 全部/通用 可刪除修正已存在。")
