# -*- coding: utf-8 -*-
"""SPT Time Tracking V1.3 cleanup.

Run from project root after extracting the V1.3 patch:
    python tools\apply_v1_3_cleanup.py

It removes old Streamlit page filenames such as pages/1_工時紀錄.py,
so the sidebar will show the new names: 01. 工時紀錄, 02. 歷史紀錄, etc.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
OLD_PAGE_NAMES = [
    "1_工時紀錄.py",
    "2_歷史紀錄.py",
    "3_製令管理.py",
    "4_人員名單.py",
    "5_製令工時分析.py",
    "6_LOG查詢.py",
    "7_今日未紀錄名單.py",
    "8_人員每日工時.py",
]

removed = []
for name in OLD_PAGE_NAMES:
    path = PAGES / name
    if path.exists():
        path.unlink()
        removed.append(str(path.relative_to(ROOT)))

print("SPT Time Tracking V1.3 cleanup completed.")
if removed:
    print("Removed old pages:")
    for item in removed:
        print(" -", item)
else:
    print("No old page files found.")
