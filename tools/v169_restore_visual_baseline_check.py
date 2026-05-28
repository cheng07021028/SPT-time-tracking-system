# -*- coding: utf-8 -*-
"""V169 restore visual baseline smoke check.
Read-only check for restored visual-critical files without importing Streamlit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = {
    "services/theme_service.py": ["def apply_theme", "def render_header"],
    "services/security_service.py": ["def require_login", "def require_module_access", "def check_permission"],
    "services/db_service.py": ["def execute", "def query_df"],
    "services/crud_table_service.py": [],
    "services/master_data_service.py": [],
    "services/time_record_service.py": [],
    "pages/01_01. 工時紀錄.py": [],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    result = {"ok": True, "checked_files": [], "missing": [], "notes": []}
    for rel, needles in REQUIRED_FILES.items():
        p = PROJECT_ROOT / rel
        if not p.exists():
            result["ok"] = False
            result["missing"].append(rel)
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        result["checked_files"].append(rel)
        for needle in needles:
            if needle not in text:
                result["ok"] = False
                result["missing"].append(f"{rel}: {needle}")
    result["notes"].append("Read-only visual baseline rollback check. No business data is written.")
    if args.json_path:
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
