# -*- coding: utf-8 -*-
"""V180B check: verify 02 history page no longer uses unsafe work_hours sum."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGE = PROJECT_ROOT / "pages" / "02_02. 歷史紀錄.py"


def main() -> int:
    result = {
        "page_exists": PAGE.exists(),
        "helper_present": False,
        "unsafe_work_hours_sum_present": False,
        "ok": False,
    }
    if PAGE.exists():
        text = PAGE.read_text(encoding="utf-8", errors="ignore")
        result["helper_present"] = "_v180b_safe_work_hours_total_hms" in text or "_safe_work_hours_total_hms" in text
        result["unsafe_work_hours_sum_present"] = bool(
            re.search(r"hours_to_hms\(\s*df\s*\[\s*['\"]work_hours['\"]\s*\]\s*\.sum\(\s*\)\s*\)", text)
        )
        result["ok"] = result["helper_present"] and not result["unsafe_work_hours_sum_present"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
