# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "time_record_service.py"
PAGE_CANDIDATES = [
    ROOT / "pages" / "01_01. 工時紀錄.py",
    ROOT / "pages" / "01_01. #U5de5#U6642#U7d00#U9304.py",
]


def main() -> int:
    text = SERVICE.read_text(encoding="utf-8") if SERVICE.exists() else ""
    page_text = "\n".join(p.read_text(encoding="utf-8") for p in PAGE_CANDIDATES if p.exists())
    checks = {
        "service_exists": SERVICE.exists(),
        "v177_marker": "V177 01 TODAY/HISTORY DELETE SYNC AUTHORITY FIX" in text,
        "today_records_overridden": "def today_records(include_finished: bool = True, unfinished_only: bool = False)" in text and "01 Today Records mirrors 02 Editable History" in text,
        "delete_override": "def delete_time_records(record_ids" in text and "delete_time_records_v177_01_02_consistent" in text,
        "editor_delete_fallback": "def delete_time_records_from_editor_df" in text,
        "page_import_fallback": "delete_time_records_from_editor_df" in page_text,
        "page_delete_fallback_call": "delete_time_records_from_editor_df(edited_admin" in page_text,
        "no_visual_files_required": True,
    }
    ok = all(bool(v) for v in checks.values())
    out = {"ok": ok, "checks": checks}
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_path", default="")
    args = ap.parse_args()
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
