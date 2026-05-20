# -*- coding: utf-8 -*-
"""Remove accidental Streamlit page entries named theme service.

This does NOT remove services/theme_service.py. It only removes mistaken page files
under pages/ that make "theme service" appear in the sidebar.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
TARGETS = []
if PAGES.exists():
    for p in PAGES.glob("*.py"):
        low = p.name.lower().replace(" ", "_")
        if low in {"theme_service.py", "theme service.py"} or "theme_service" in low or "theme_service" in p.stem.lower() or p.stem.lower().strip() == "theme service":
            TARGETS.append(p)

if not TARGETS:
    print("OK: no accidental theme service page found under pages/. services/theme_service.py is untouched.")
else:
    for p in TARGETS:
        print(f"DELETE: {p}")
        p.unlink(missing_ok=True)
    print("Done. Restart Streamlit after deletion.")
