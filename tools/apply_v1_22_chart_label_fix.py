# -*- coding: utf-8 -*-
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = {
    ROOT / "pages" / "05_05. 製令工時分析.py": ["製令分析", "累積時數 / Total Hours", "每日趨勢 / Daily Trend"],
    ROOT / "pages" / "08_08. 人員每日工時.py": ["工時分布 / Time Distribution", "累積時數", "人員每日累積工時"],
}
print("=" * 52)
print("SPT Time Tracking V1.22 chart label fix check")
print("=" * 52)
ok = True
for path, needles in checks.items():
    if not path.exists():
        print(f"MISSING: {path}")
        ok = False
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [s for s in needles if s not in text]
    if missing:
        print(f"FAIL: {path.name} missing {missing}")
        ok = False
    else:
        print(f"OK: {path.name} updated")
if ok:
    print("V1.22 files are installed correctly.")
else:
    print("Please unzip the patch into the project root and rerun this check.")
print("=" * 52)
