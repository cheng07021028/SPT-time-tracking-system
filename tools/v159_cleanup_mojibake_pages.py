# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.page_hygiene_service import collect_page_hygiene_status, cleanup_duplicate_mojibake_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="V159 duplicate #U mojibake Streamlit page cleanup")
    parser.add_argument("--apply", action="store_true", help="Actually delete safe duplicate #U page files. Default is dry-run.")
    parser.add_argument("--json", dest="json_path", default="", help="Optional path to save a JSON report.")
    args = parser.parse_args()

    result = cleanup_duplicate_mojibake_pages(apply=bool(args.apply))
    status = result.get("after") or result.get("before") or collect_page_hygiene_status()
    print("========== V159 Page Hygiene ==========")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Total pages: {status.get('total_py_pages', 0)}")
    print(f"Mojibake pages: {status.get('mojibake_pages', 0)}")
    print(f"Safe duplicate pages: {status.get('safe_to_remove', 0)}")
    print(f"Must keep pages: {status.get('must_keep', 0)}")
    if result.get("planned_or_removed"):
        print("Files:")
        for f in result.get("planned_or_removed", []):
            print(" -", f)
    else:
        print("No safe duplicate #U pages found.")
    if result.get("errors"):
        print("Errors:")
        for e in result.get("errors", []):
            print(" -", e)
    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("Report:", out)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
