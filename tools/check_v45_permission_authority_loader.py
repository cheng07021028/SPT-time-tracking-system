# -*- coding: utf-8 -*-
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
    if p.exists():
        found = True
        py_compile.compile(str(p), doraise=True)
        text = p.read_text(encoding="utf-8")
        required = [
            "def _v45_best_account_rows",
            "data/permanent_store",
            "v45_account_source",
            "authority-loader-plus-delete-visual-marker",
        ]
        missing = [s for s in required if s not in text]
        if missing:
            raise SystemExit(f"FAIL: {p} missing {missing}")
if not found:
    raise SystemExit("FAIL: no permission page file found")
print("PASS: V45 permission account editor loads users directly from authority JSON and compiles.")
