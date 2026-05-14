# -*- coding: utf-8 -*-
"""SPT Time Tracking V1.28 setup: cleanup duplicate pages and initialize security tables."""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGES = PROJECT_ROOT / "pages"
KEEP = {
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
}


def cleanup_pages() -> None:
    PAGES.mkdir(exist_ok=True)
    removed = []
    for p in PAGES.glob("*.py"):
        if p.name not in KEEP:
            try:
                p.unlink()
                removed.append(p.name)
            except Exception as e:
                print(f"WARN: unable to remove {p.name}: {e}")
    print("Clean pages completed.")
    if removed:
        print("Removed old/duplicate pages:")
        for name in removed:
            print(" -", name)
    else:
        print("No duplicate page files found.")


def init_security() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from services.security_service import ensure_security_schema
    ensure_security_schema()
    print("Security tables initialized.")
    print("Default admin: admin / Admin@1234")
    print("Please login and change passwords before production use.")


if __name__ == "__main__":
    cleanup_pages()
    init_security()
    print("SPT Time Tracking V1.28 permission setup completed.")
