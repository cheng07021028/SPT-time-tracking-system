# -*- coding: utf-8 -*-
"""V164 repository layer smoke test.

Usage:
    python tools/v164_repository_smoke_test.py
    python tools/v164_repository_smoke_test.py --json reports/v164_repository_health.json

This test is read-only.  It does not create, update, delete, recalculate, import
or upload production data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        import pandas as pd  # type: ignore

        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def run_smoke_test() -> dict[str, Any]:
    from services.repositories import (
        get_log_repository,
        get_permission_repository,
        get_settings_repository,
        get_time_record_repository,
        repository_health_report,
    )

    report = repository_health_report()
    preview: dict[str, Any] = {}

    checks = {
        "time_records_preview_rows": lambda: len(get_time_record_repository().load_records().head(5)),
        "logs_preview_rows": lambda: len(get_log_repository().list_logs(limit=5)),
        "permission_users_preview_rows": lambda: len(get_permission_repository().list_users(limit=5)),
        "settings_process_preview_rows": lambda: len(get_settings_repository().list_process_options(limit=5)),
    }

    for key, fn in checks.items():
        try:
            preview[key] = {"ok": True, "rows": int(fn())}
        except Exception as exc:
            preview[key] = {"ok": False, "error": repr(exc)}

    report["preview_checks"] = preview
    report["smoke_ok"] = bool(report.get("overall_ok")) and all(v.get("ok") for v in preview.values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="SPT V164 repository layer smoke test")
    parser.add_argument("--json", dest="json_path", default="", help="Optional JSON report path")
    args = parser.parse_args()

    report = run_smoke_test()
    text = json.dumps(report, ensure_ascii=False, indent=2, default=_json_default)

    if args.json_path:
        out = Path(args.json_path)
        if not out.is_absolute():
            out = PROJECT_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"V164 repository smoke report written: {out}")
    else:
        print(text)

    if not report.get("smoke_ok"):
        print("V164 repository smoke test found warnings/errors.", file=sys.stderr)
        return 1
    print("V164 repository smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
