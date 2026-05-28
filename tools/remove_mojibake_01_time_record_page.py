# -*- coding: utf-8 -*-
"""Remove legacy mojibake duplicate page for 01 工時紀錄.

Run from project root:
    python tools/remove_mojibake_01_time_record_page.py
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
KEEP = "01_01. 工時紀錄.py"
REMOVED = []
for p in PAGES.glob("01_01*.py"):
    if p.name == KEEP:
        continue
    if "#U" in p.name or "工時" not in p.name:
        bak = p.with_suffix(p.suffix + ".bak_removed_v143")
        if bak.exists():
            bak.unlink()
        p.rename(bak)
        REMOVED.append((p.name, bak.name))
print("Keep:", KEEP)
if REMOVED:
    print("Removed legacy duplicates:")
    for a, b in REMOVED:
        print(f"- {a} -> {b}")
else:
    print("No legacy duplicate 01 page found.")
