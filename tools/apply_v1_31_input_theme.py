# -*- coding: utf-8 -*-
"""SPT Time Tracking V1.31 setup check."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "services" / "theme_service.py"
MARKERS = [
    "V1.31 全系統輸入區淺色科技風",
    "Global Light Input Fields",
    "data-baseweb=\"input\"",
]

def main() -> int:
    if not THEME.exists():
        print(f"ERROR: not found: {THEME}")
        return 1
    text = THEME.read_text(encoding="utf-8", errors="ignore")
    missing = [m for m in MARKERS if m not in text]
    if missing:
        print("ERROR: V1.31 input theme markers missing:")
        for m in missing:
            print(" -", m)
        return 2
    print("OK: V1.31 input theme installed.")
    print(f"Checked: {THEME}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
