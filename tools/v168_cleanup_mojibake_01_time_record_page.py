# -*- coding: utf-8 -*-
"""Remove old #Uxxxx 01 time-record page after the normal Chinese filename is present.

This is optional but recommended for repositories that still contain:
    pages/01_01. #U5de5#U6642#U7d00#U9304.py
It never deletes the normal page.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
NORMAL = PAGES / "01_01. 工時紀錄.py"


def main() -> int:
    if not NORMAL.exists():
        print("正常中文頁面不存在，為安全起見不刪除任何檔案：", NORMAL)
        return 1
    removed = []
    for p in PAGES.glob("01_01.*.py"):
        if p == NORMAL:
            continue
        if "#U" in p.name:
            p.unlink()
            removed.append(str(p.relative_to(ROOT)))
    if removed:
        print("已移除舊亂碼 01 頁面：")
        for x in removed:
            print("-", x)
    else:
        print("沒有找到需要移除的舊亂碼 01 頁面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
