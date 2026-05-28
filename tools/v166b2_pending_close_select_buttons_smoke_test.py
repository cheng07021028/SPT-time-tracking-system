# -*- coding: utf-8 -*-
"""V166B2 smoke test: LOG-only pending close bulk select buttons.

This test is intentionally static and non-destructive. It does not read or write
production time records, authority files, LOG, event journal, row shards, or GitHub.
"""
from __future__ import annotations

import argparse
import json
import py_compile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "14_14. 資料健康檢查中心.py"

REQUIRED_SNIPPETS = [
    "V166B LOG-only 待補紀錄人工結算 / Pending Recovery Close",
    "☑️ 結算全部勾選",
    "⬜ 結算全部取消勾選",
    "v166b_pending_close_select_default",
    "v166b_pending_close_editor_nonce",
    "v166b_select_all_pending_close",
    "v166b_clear_all_pending_close",
    "key=f\"v166b_pending_close_editor_",
]


def run_check() -> dict:
    result = {
        "ok": True,
        "version": "V166B2",
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "page": str(PAGE.relative_to(ROOT)),
        "checks": [],
        "missing": [],
    }
    if not PAGE.exists():
        result["ok"] = False
        result["missing"].append(str(PAGE.relative_to(ROOT)))
        return result

    try:
        py_compile.compile(str(PAGE), doraise=True)
        result["checks"].append({"name": "py_compile_page", "ok": True})
    except Exception as exc:
        result["ok"] = False
        result["checks"].append({"name": "py_compile_page", "ok": False, "error": str(exc)})

    text = PAGE.read_text(encoding="utf-8")
    for snippet in REQUIRED_SNIPPETS:
        exists = snippet in text
        result["checks"].append({"name": f"snippet:{snippet}", "ok": exists})
        if not exists:
            result["ok"] = False
            result["missing"].append(snippet)

    forbidden_files = [p for p in (ROOT / "pages").glob("*.py") if "#U" in p.name]
    result["mojibake_page_files_found"] = [str(p.relative_to(ROOT)) for p in forbidden_files]
    if forbidden_files:
        # Do not fail this patch if legacy project still contains old pages; the patch ZIP itself is checked separately.
        result["checks"].append({"name": "legacy_mojibake_pages_present_in_project", "ok": False, "warning_only": True})

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()

    result = run_check()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.json_path:
        out = ROOT / args.json_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
