# -*- coding: utf-8 -*-
"""Remove old mojibake 06 LOG page after adding the no-mojibake page name.

Run from project root:
    python tools/remove_mojibake_06_log_page.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "pages" / "06_06. LOG#U67e5#U8a62.py"
NEW = ROOT / "pages" / "06_06. LOG查詢.py"

if NEW.exists() and OLD.exists():
    OLD.unlink()
    print(f"Removed: {OLD}")
elif OLD.exists() and not NEW.exists():
    print(f"Old mojibake page exists, but new page not found. Keep old file: {OLD}")
else:
    print("No mojibake 06 LOG page cleanup needed.")
