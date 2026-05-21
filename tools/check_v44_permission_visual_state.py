# -*- coding: utf-8 -*-
"""Check V44 account editor visual-state patch."""
from __future__ import annotations
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / "pages" / "10_10. 權限管理.py",
    ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]
found = False
for p in paths:
    if not p.exists():
        continue
    found = True
    py_compile.compile(str(p), doraise=True)
    text = p.read_text(encoding="utf-8")
    required = [
        "_v44_sync_delete_visual",
        "_v44_strip_visual_columns",
        "刪除狀態 / Delete Mark",
        "delete-visual-marker-and-draft-authority",
        "bulk_render_protected_v44",
    ]
    missing = [x for x in required if x not in text]
    if missing:
        raise SystemExit(f"FAIL: {p.name} missing {missing}")
if not found:
    raise SystemExit("FAIL: no 10 permission page file found")
print("PASS: V44 permission account delete visual marker and draft-authority patch is present.")
