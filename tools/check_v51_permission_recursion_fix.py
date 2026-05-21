# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "pages" / "10_10. 權限管理.py",
    ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]

found = False
for path in CANDIDATES:
    if not path.exists():
        continue
    found = True
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    if "def _v37_touch_account_editor" not in text:
        raise SystemExit(f"FAIL: missing _v37_touch_account_editor in {path}")
    if 'def _v37_touch_account_editor() -> None:\n    _v37_clear_widget_state("v171_account_password_editor_")\n    _v37_touch_account_editor()' in text:
        raise SystemExit(f"FAIL: recursive _v37_touch_account_editor remains in {path}")
    lines = text.splitlines()
    in_func = False
    body = []
    for line in lines:
        if line.startswith("def _v37_touch_account_editor"):
            in_func = True
            body = [line]
            continue
        if in_func and line.startswith("def "):
            break
        if in_func:
            body.append(line)
    joined = "\n".join(body[1:])
    if "_v37_touch_account_editor()" in joined:
        raise SystemExit(f"FAIL: _v37_touch_account_editor calls itself in {path}")

if not found:
    raise SystemExit("FAIL: no 10_10 permission page found")
print("PASS: V51 fixed recursive _v37_touch_account_editor in permission page.")
