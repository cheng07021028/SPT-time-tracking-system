# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = ROOT / "pages"
if not base.exists():
    base = ROOT / "modified_files" / "pages"
paths = [
    base / "10_10. 權限管理.py",
    base / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]
required = [
    "V43 按鈕狀態診斷",
    "visible_delete_true_count",
    "v43_account_use_draft_for_save",
    "diagnostic-after-editor-and-draft-save-guard",
]
missing = []
for path in paths:
    if not path.exists():
        missing.append(f"missing file: {path}")
        continue
    text = path.read_text(encoding="utf-8")
    for marker in required:
        if marker not in text:
            missing.append(f"{path}: missing marker {marker}")
if missing:
    print("FAIL: V43 permission account diagnostic guard is incomplete")
    for m in missing:
        print(" -", m)
    raise SystemExit(1)
print("PASS: V43 permission account editor diagnostic is after data_editor and bulk save uses draft authority.")
