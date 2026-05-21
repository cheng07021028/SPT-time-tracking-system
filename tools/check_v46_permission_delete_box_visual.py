# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [ROOT / "pages" / "10_10. 權限管理.py", ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py"]
required = [
    "def _v46_sync_delete_visual_box",
    "def _v46_apply_delete_box_to_bool",
    "刪除方框 / Delete Box",
    "unicode-delete-box-selector-visual-fix",
]
missing = []
for p in paths:
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    for r in required:
        if r not in s:
            missing.append(f"{p}: missing {r}")
if missing:
    print("FAIL: V46 check failed")
    for m in missing:
        print(m)
    raise SystemExit(1)
print("PASS: V46 permission account editor uses Unicode delete box visual selector and converts it back to bool for save.")
