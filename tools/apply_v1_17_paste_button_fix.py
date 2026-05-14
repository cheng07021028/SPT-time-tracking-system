# -*- coding: utf-8 -*-
"""V1.17 paste-button fix verifier.
Run from project root after extracting the patch.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
TARGETS = [
    PAGES / "03_03. 製令管理.py",
    PAGES / "04_04. 人員名單.py",
]
OLD_CANDIDATES = [
    PAGES / "03. 製令管理.py",
    PAGES / "04. 人員名單.py",
    PAGES / "3_製令管理.py",
    PAGES / "4_人員名單.py",
    PAGES / "03_製令管理.py",
    PAGES / "04_人員名單.py",
]

print("=" * 56)
print("SPT Time Tracking V1.17 Paste Button Fix Check")
print("=" * 56)

for old in OLD_CANDIDATES:
    if old.exists():
        old.unlink()
        print(f"Removed old page: {old.relative_to(ROOT)}")

ok = True
for target in TARGETS:
    if not target.exists():
        print(f"MISSING: {target.relative_to(ROOT)}")
        ok = False
        continue
    text = target.read_text(encoding="utf-8", errors="ignore")
    required = ["V1.17 loaded", "加入清單編輯", "直接儲存貼上資料"]
    missing = [r for r in required if r not in text]
    if missing:
        print(f"CHECK FAILED: {target.relative_to(ROOT)} missing {missing}")
        ok = False
    else:
        print(f"OK: {target.relative_to(ROOT)} contains V1.17 paste buttons")

print("=" * 56)
if ok:
    print("V1.17 check completed. Restart Streamlit or Reboot app.")
else:
    print("V1.17 check failed. Extract the patch to the PROJECT ROOT and overwrite files.")
print("=" * 56)
