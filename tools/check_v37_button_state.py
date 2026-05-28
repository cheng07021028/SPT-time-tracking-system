# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import ast, re, sys
ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
NEEDED = [
    "02_02. 歷史紀錄.py", "03_03. 製令管理.py", "04_04. 人員名單.py",
    "07_07. 今日未紀錄名單.py", "10_10. 權限管理.py",
]
missing=[]
for name in NEEDED:
    p=PAGES/name
    if not p.exists(): missing.append(str(p))
    else: ast.parse(p.read_text(encoding="utf-8"))
if missing:
    print("MISSING files:")
    print("\n".join(missing))
    sys.exit(1)
# Check no #U pages remain.
moji=[p.name for p in PAGES.glob("*.py") if "#U" in p.name or "Φ" in p.name]
if moji:
    print("WARNING: mojibake page files still exist; remove them to avoid Streamlit running old pages:")
    print("\n".join(moji))
else:
    print("PASS: no mojibake page files detected.")
print("PASS: V37 button-state protection files compile.")
