# -*- coding: utf-8 -*-
"""V167 login/startup performance guard check.

This check is intentionally static + compile based so it can run on Streamlit Cloud
without starting the web server. It verifies that the login fast-path overrides are
present and that the patched files compile.
"""
from __future__ import annotations

import argparse
import compileall
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_MARKERS = {
    "services/security_service.py": "V167 LOGIN PERFORMANCE FINAL OVERRIDE",
    "services/db_service.py": "V167 NO-BLOCKING WRITE SYNC FINAL OVERRIDE",
    "services/theme_service.py": "V167 LOGIN THEME FAST PATH FINAL OVERRIDE",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def run_check() -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": "V167_login_startup_performance",
        "project_root": str(PROJECT_ROOT),
        "markers": {},
        "compileall_ok": False,
        "mojibake_page_files": [],
        "ok": False,
    }
    marker_ok = True
    for rel, marker in REQUIRED_MARKERS.items():
        text = _read(PROJECT_ROOT / rel)
        exists = marker in text
        result["markers"][rel] = exists
        marker_ok = marker_ok and exists
    result["mojibake_page_files"] = [
        str(p.relative_to(PROJECT_ROOT))
        for p in (PROJECT_ROOT / "pages").glob("*.py")
        if "#U" in p.name
    ] if (PROJECT_ROOT / "pages").exists() else []
    result["compileall_ok"] = bool(compileall.compile_dir(str(PROJECT_ROOT / "services"), quiet=1)) and bool(compileall.compile_file(str(PROJECT_ROOT / "streamlit_app.py"), quiet=1))
    result["ok"] = bool(marker_ok and result["compileall_ok"] and not result["mojibake_page_files"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    res = run_check()
    if args.json_path:
        out = Path(args.json_path)
        if not out.is_absolute():
            out = PROJECT_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
