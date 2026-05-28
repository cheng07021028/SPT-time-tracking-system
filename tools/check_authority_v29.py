# -*- coding: utf-8 -*-
"""Check SPT V29 authority files and page callback definitions."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_authority() -> bool:
    from services.permanent_authority_service import MODULES, load_authority, authority_health
    ok = True
    for module_key in MODULES:
        for kind in ("records", "settings"):
            payload = load_authority(module_key, kind)
            path = ROOT / "data" / "permanent_store" / "modules" / module_key / f"{kind}.json"
            exists = path.exists()
            counts = payload.get("table_counts", {}) if isinstance(payload, dict) else {}
            print(f"{module_key}/{kind}: {'OK' if exists else 'MISSING'} {path.relative_to(ROOT) if exists else ''} counts={counts}")
            if not exists:
                ok = False
    health = authority_health()
    print("manifest:", health.get("authority_schema"), health.get("updated_at"))
    return ok


def _callbacks_in_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    # static scan for on_click=name
    return re.findall(r"on_click\s*=\s*([A-Za-z_]\w*)", text)


def _defs_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def check_callbacks() -> bool:
    ok = True
    for path in sorted((ROOT / "pages").glob("*.py")):
        if "__pycache__" in str(path):
            continue
        callbacks = _callbacks_in_file(path)
        if not callbacks:
            continue
        defs = _defs_in_file(path)
        missing = [c for c in callbacks if c not in defs]
        print(f"callbacks {path.name}: {len(callbacks)} callbacks, missing={missing}")
        if missing:
            ok = False
    return ok


def main() -> int:
    ok1 = check_authority()
    ok2 = check_callbacks()
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
