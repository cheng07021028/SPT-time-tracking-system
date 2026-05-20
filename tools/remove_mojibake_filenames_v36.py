# -*- coding: utf-8 -*-
"""V36: remove #Uxxxx / mojibake Streamlit page files after normal Chinese files are added.

Run from project root:
    python tools/remove_mojibake_filenames_v36.py

This script only removes duplicated old page filenames and __pycache__ files.
It does not delete data/permanent_store or any business data.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = PROJECT_ROOT / "pages"

OLD_PAGE_NAMES = [
    "01_01. #U5de5#U6642#U7d00#U9304.py",
    "02_02. #U6b77#U53f2#U7d00#U9304.py",
    "03_03. #U88fd#U4ee4#U7ba1#U7406.py",
    "04_04. #U4eba#U54e1#U540d#U55ae.py",
    "05_05. #U88fd#U4ee4#U5de5#U6642#U5206#U6790.py",
    "06_06. LOG#U67e5#U8a62.py",
    "07_07. #U4eca#U65e5#U672a#U7d00#U9304#U540d#U55ae.py",
    "08_08. #U4eba#U54e1#U6bcf#U65e5#U5de5#U6642.py",
    "09_09. #U8cc7#U6599#U6c38#U4e45#U4fdd#U5b58#U8207#U5099#U4efd.py",
    "10_10. #U6b0a#U9650#U7ba1#U7406.py",
    "11_11. #U767b#U5165#U7d00#U9304.py",
    "12_12. #U6a21#U7d44#U6c38#U4e45#U7d00#U9304#U4e2d#U5fc3.py",
    "13_13. #U7cfb#U7d71#U8a2d#U5b9a.py",
]

NORMAL_PAGE_NAMES = [
    "01_01. 工時紀錄.py",
    "02_02. 歷史紀錄.py",
    "03_03. 製令管理.py",
    "04_04. 人員名單.py",
    "05_05. 製令工時分析.py",
    "06_06. LOG查詢.py",
    "07_07. 今日未紀錄名單.py",
    "08_08. 人員每日工時.py",
    "09_09. 資料永久保存與備份.py",
    "10_10. 權限管理.py",
    "11_11. 登入紀錄.py",
    "12_12. 模組永久紀錄中心.py",
    "13_13. 系統設定.py",
]

MOJIBAKE_MARKERS = ("#U", "Φ", "Σ", "τ", "╜", "╖", "╣", "╚", "Θ", "σ", "µ")


def main() -> int:
    if not PAGES_DIR.exists():
        print(f"ERROR: pages folder not found: {PAGES_DIR}")
        return 2

    missing_normal = [name for name in NORMAL_PAGE_NAMES if not (PAGES_DIR / name).exists()]
    if missing_normal:
        print("ERROR: normal Chinese page files are missing. Do not delete old pages yet:")
        for name in missing_normal:
            print(f"  - pages/{name}")
        return 3

    deleted = []
    for name in OLD_PAGE_NAMES:
        p = PAGES_DIR / name
        if p.exists():
            p.unlink()
            deleted.append(f"pages/{name}")

    for p in PAGES_DIR.glob("*.py"):
        if any(marker in p.name for marker in MOJIBAKE_MARKERS):
            p.unlink()
            deleted.append(f"pages/{p.name}")

    pycache = PAGES_DIR / "__pycache__"
    if pycache.exists():
        for p in pycache.rglob("*"):
            if p.is_file():
                p.unlink()
                deleted.append(str(p.relative_to(PROJECT_ROOT)))
        # Remove empty pycache dirs from deepest to root.
        for d in sorted([x for x in pycache.rglob("*") if x.is_dir()], reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            pycache.rmdir()
        except OSError:
            pass

    print("V36 cleanup completed.")
    if deleted:
        print("Deleted:")
        for item in deleted:
            print(f"  - {item}")
    else:
        print("No old mojibake page files found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
