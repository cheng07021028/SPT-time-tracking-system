# -*- coding: utf-8 -*-
"""Remove accidental Streamlit page entries named theme_service.

This does NOT remove services/theme_service.py.  It only removes accidental page files
that make a useless "theme service" item appear in the Streamlit sidebar.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "pages" / "theme_service.py",
    ROOT / "pages" / "theme service.py",
    ROOT / "pages" / "Theme Service.py",
]
removed = []
for path in CANDIDATES:
    if path.exists():
        path.unlink()
        removed.append(str(path.relative_to(ROOT)))
# Also remove obvious generated copies, but never touch services/theme_service.py.
for path in (ROOT / "pages").glob("*theme*service*.py"):
    try:
        path.unlink()
        removed.append(str(path.relative_to(ROOT)))
    except Exception:
        pass

if removed:
    print("Removed accidental page files:")
    for item in removed:
        print(" -", item)
else:
    print("No accidental theme_service page file found. services/theme_service.py is preserved.")
