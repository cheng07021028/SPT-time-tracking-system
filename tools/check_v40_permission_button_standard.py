# -*- coding: utf-8 -*-
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "pages" / "10_10. 權限管理.py",
    ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]
path = next((p for p in CANDIDATES if p.exists()), None)
if path is None:
    raise SystemExit("FAIL: 10 permission page not found")
text = path.read_text(encoding="utf-8")
if "_v37_touch_account_editor()\n    _v37_touch_account_editor()" in text:
    raise SystemExit("FAIL: recursive _v37_touch_account_editor still exists")
required = [
    "def _v40_account_delete_true_count",
    "def _v37_touch_account_editor",
    "def _v25_account_set_edit",
    "def _v25_account_add_blank",
    "def _v25_account_delete_flag",
    "def _v25_account_reload",
    "V40 按鈕狀態診斷",
]
missing = [s for s in required if s not in text]
if missing:
    raise SystemExit("FAIL: missing V40 items: " + ", ".join(missing))
ast.parse(text)
print(f"PASS: V40 permission account editor standard is present in {path.name}; recursion removed; diagnostics included.")
