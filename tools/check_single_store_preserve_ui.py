# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "permanent_store"
required = [
    STORE / "persistent_modules",
    STORE / "persistent_state",
    STORE / "database",
    STORE / "config",
]
missing=[str(p.relative_to(ROOT)) for p in required if not p.exists()]
old=[p for p in [ROOT/"data"/"persistent_modules", ROOT/"data"/"persistent_state", ROOT/"data"/"database", ROOT/"data"/"config"] if p.exists()]
if missing:
    print("Missing permanent store folders:", missing)
    sys.exit(1)
if old:
    print("Legacy official folders still exist:", [str(p.relative_to(ROOT)) for p in old])
    sys.exit(2)
print("OK: original UI/project retained; official data root is data/permanent_store/.")
