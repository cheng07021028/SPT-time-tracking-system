# -*- coding: utf-8 -*-
"""Remove old mojibake page name for 01. 工時紀錄.

Use after uploading pages/01_01. 工時紀錄.py to GitHub, so Streamlit does not show
or execute both the old #Uxxxx page and the corrected Unicode filename page.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
KEEP = PAGES / "01_01. 工時紀錄.py"
OLD_NAMES = [
    "01_01. #U5de5#U6642#U7d00#U9304.py",
]


def main() -> int:
    if not KEEP.exists():
        print(f"找不到正確檔名：{KEEP}")
        return 1
    removed = 0
    for name in OLD_NAMES:
        p = PAGES / name
        if p.exists():
            p.unlink()
            print(f"已刪除舊亂碼頁面：{p}")
            removed += 1
    if removed == 0:
        print("沒有找到需要刪除的 01 亂碼頁面。")
    print("完成。請 commit/push 後 Reboot Streamlit App。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
