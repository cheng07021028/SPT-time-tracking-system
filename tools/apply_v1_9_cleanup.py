# -*- coding: utf-8 -*-
"""Cleanup duplicated Streamlit page files for V1.9."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"

# Keep only the V1.8/V1.9 numbered page naming style if present.
KEEP_PREFIXES = tuple(f"{i:02d}_{i:02d}." for i in range(1, 9))
OLD_PATTERNS = [
    "1_工時紀錄.py", "2_歷史紀錄.py", "3_製令管理.py", "4_人員名單.py",
    "5_製令工時分析.py", "6_LOG查詢.py", "7_今日未紀錄名單.py", "8_人員每日工時.py",
    "01. 工時紀錄.py", "02. 歷史紀錄.py", "03. 製令管理.py", "04. 人員名單.py",
    "05. 製令工時分析.py", "06. LOG查詢.py", "07. 今日未紀錄名單.py", "08. 人員每日工時.py",
]

def main() -> None:
    print("============================================")
    print("SPT Time Tracking V1.9 Cleanup")
    print("============================================")
    if not PAGES.exists():
        print(f"pages folder not found: {PAGES}")
        return
    removed = []
    for name in OLD_PATTERNS:
        p = PAGES / name
        if p.exists():
            p.unlink()
            removed.append(name)
    print(f"Removed old duplicate pages: {len(removed)}")
    for name in removed:
        print(" -", name)
    print("\nCurrent pages:")
    for p in sorted(PAGES.glob("*.py")):
        print(" -", p.name)
    print("============================================")
    print("V1.9 cleanup completed.")

if __name__ == "__main__":
    main()
