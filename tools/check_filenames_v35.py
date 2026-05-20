# -*- coding: utf-8 -*-
"""V35 checker: verify no #Uxxxx page files and 01 master-data wrappers exist."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = PROJECT_ROOT / "pages"
SERVICE = PROJECT_ROOT / "services" / "master_data_service.py"

REQUIRED_PAGES = [
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


def main() -> int:
    errors = []
    if not PAGES_DIR.exists():
        errors.append("pages folder missing")
    else:
        bad = [p.name for p in PAGES_DIR.glob("*.py") if "#U" in p.name]
        bad += [p.name for p in PAGES_DIR.glob("*.py") if any(ch in p.name for ch in "ΦΣτ╜╖╣╚Θσµ")]
        if bad:
            errors.append("mojibake page files remain: " + ", ".join(sorted(set(bad))))
        for name in REQUIRED_PAGES:
            if not (PAGES_DIR / name).exists():
                errors.append(f"missing normal page: pages/{name}")

    service_text = SERVICE.read_text(encoding="utf-8") if SERVICE.exists() else ""
    for fn in [
        "load_employees_for_time_record_fast",
        "load_work_orders_for_time_record_fast",
        "has_master_data_for_time_record_fast",
    ]:
        if not re.search(rf"def\s+{fn}\s*\(", service_text):
            errors.append(f"missing services.master_data_service.{fn}")

    if errors:
        print("FAIL:")
        for e in errors:
            print("  - " + e)
        return 1
    print("PASS: normal Chinese page filenames are present, mojibake page files are removed, and 01 master-data wrappers exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
