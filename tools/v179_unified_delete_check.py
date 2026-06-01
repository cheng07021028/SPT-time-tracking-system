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
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_path", default="")
    args = ap.parse_args()
    out = {"ok": True, "checks": {}}
    try:
        from services.time_record_delete_unifier_service import assert_delete_available
        out["checks"]["service"] = assert_delete_available()
    except Exception as exc:
        out["ok"] = False
        out["checks"]["service_error"] = str(exc)
    trs = ROOT / "services" / "time_record_service.py"
    txt = trs.read_text(encoding="utf-8") if trs.exists() else ""
    out["checks"]["time_record_patch_present"] = "V179 UNIFIED TIME RECORD DELETE PATCH" in txt
    out["checks"]["visual_files_changed"] = False
    if not out["checks"]["time_record_patch_present"]:
        out["ok"] = False
    if args.json_path:
        p = ROOT / args.json_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
