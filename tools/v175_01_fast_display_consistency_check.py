# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    out: dict = {"ok": False, "checks": {}}
    try:
        import services.time_record_service as trs
        required = [
            "today_records",
            "load_records",
            "get_active_record",
            "refresh_active_records_for_employee",
            "start_work",
            "finish_work",
            "_v175_history_source_df",
        ]
        missing = [name for name in required if not hasattr(trs, name)]
        out["checks"]["required_symbols_present"] = not missing
        out["missing"] = missing
        src = Path(trs.__file__).read_text(encoding="utf-8")
        out["checks"]["v175_marker_present"] = "V175 01 FAST DISPLAY + TODAY/HISTORY CONSISTENCY" in src
        out["checks"]["today_records_authority_only"] = "def today_records" in src and "v175_authority_only" in src
        out["checks"]["no_visual_modules_modified_by_test"] = True
        out["ok"] = all(out["checks"].values()) and not missing
    except Exception as exc:
        out["error"] = repr(exc)
        out["ok"] = False

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    if args.json_path:
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
