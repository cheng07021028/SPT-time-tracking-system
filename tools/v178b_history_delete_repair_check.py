# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    out = {"version": "V178B", "ok": True, "checks": {}}
    svc = ROOT / "services" / "history_delete_repair_service.py"
    tr = ROOT / "services" / "time_record_service.py"
    out["checks"]["service_exists"] = svc.exists()
    out["checks"]["time_record_patch_marker"] = tr.exists() and "V178B HISTORY DELETE STRICT REPAIR" in tr.read_text(encoding="utf-8", errors="ignore")
    try:
        import py_compile
        py_compile.compile(str(svc), doraise=True)
        py_compile.compile(str(ROOT / "tools" / "apply_v178b_history_delete_repair_patch.py"), doraise=True)
        out["checks"]["compile"] = True
    except Exception as exc:
        out["ok"] = False
        out["checks"]["compile"] = False
        out["compile_error"] = str(exc)
    page_hits = []
    for p in (ROOT / "pages").glob("02_02*.py") if (ROOT / "pages").exists() else []:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        page_hits.append({"file": str(p.relative_to(ROOT)), "strict_call": "delete_time_records_v178b_strict" in txt, "robust_checked_ids": "checked_ids_from_editor" in txt})
    out["checks"]["history_pages"] = page_hits
    out["ok"] = bool(out["checks"].get("service_exists")) and bool(out["checks"].get("time_record_patch_marker")) and bool(out["checks"].get("compile"))
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
