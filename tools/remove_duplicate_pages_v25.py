# -*- coding: utf-8 -*-
"""Remove legacy duplicate Streamlit page files.
Run from project root: python tools/remove_duplicate_pages_v25.py
This keeps normal Chinese filenames and removes #Uxxxx/mojibake duplicates only.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
KEEP = {
    "01_01. 工時紀錄.py", "02_02. 歷史紀錄.py", "03_03. 製令管理.py", "04_04. 人員名單.py",
    "05_05. 製令工時分析.py", "06_06. LOG查詢.py", "07_07. 今日未紀錄名單.py", "08_08. 人員每日工時.py",
    "09_09. 資料永久保存與備份.py", "10_10. 權限管理.py", "11_11. 登入紀錄.py", "12_12. 模組永久紀錄中心.py",
    "13_13. 系統設定.py",
}
removed = []
if PAGES.exists():
    for p in PAGES.glob("*.py"):
        name = p.name
        if name in KEEP:
            continue
        # Remove legacy unicode-escape pages and mojibake-looking duplicates with same numeric prefix.
        if "#U" in name or any(ch in name for ch in "σµτΦΣ╖╜ΘÖÉ¼èôí"):
            p.unlink()
            removed.append(name)
print("Removed duplicate pages:")
for name in removed:
    print(" -", name)
if not removed:
    print("(none)")
