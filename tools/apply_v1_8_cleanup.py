# -*- coding: utf-8 -*-
"""SPT Time Tracking V1.8 cleanup.
Deletes old/duplicate page files so Streamlit sidebar only shows 01~08 once.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
DELETE_NAMES = [
    "1_工時紀錄.py", "2_歷史紀錄.py", "3_製令管理.py", "4_人員名單.py",
    "5_製令工時分析.py", "6_LOG查詢.py", "7_今日未紀錄名單.py", "8_人員每日工時.py",
    "01. 工時紀錄.py", "02. 歷史紀錄.py", "03. 製令管理.py", "04. 人員名單.py",
    "05. 製令工時分析.py", "06. LOG查詢.py", "07. 今日未紀錄名單.py", "08. 人員每日工時.py",
]
KEEP_PREFIXES = ["01_01", "02_02", "03_03", "04_04", "05_05", "06_06", "07_07", "08_08"]

def main() -> None:
    print("============================================")
    print("SPT Time Tracking V1.8 cleanup")
    print("============================================")
    if not PAGES.exists():
        print(f"Pages folder not found: {PAGES}")
        return
    removed = 0
    for name in DELETE_NAMES:
        p = PAGES / name
        if p.exists():
            p.unlink()
            removed += 1
            print(f"Deleted old page: {name}")
    print("\nCurrent page files:")
    for p in sorted(PAGES.glob("*.py")):
        print(" -", p.name)
    missing = []
    for prefix in KEEP_PREFIXES:
        if not any(p.name.startswith(prefix) for p in PAGES.glob("*.py")):
            missing.append(prefix)
    if missing:
        print("\nWARNING: Missing new page prefixes:", ", ".join(missing))
        print("Please confirm the V1.8 patch was extracted to the project root.")
    else:
        print("\nCleanup completed. Sidebar should show 01. ~ 08. only once.")

if __name__ == "__main__":
    main()
