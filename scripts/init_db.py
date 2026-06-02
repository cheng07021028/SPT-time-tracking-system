from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spt_core.db import current_database_label, init_db

if __name__ == "__main__":
    init_db()
    print(f"Database initialized: {current_database_label()}")
