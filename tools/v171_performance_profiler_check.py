# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODULES = [
    "services.performance_profiler_service",
    "services.db_service",
    "services.security_service",
    "services.time_record_service",
    "services.log_service",
    "services.permanent_store",
    "services.permanent_authority_service",
    "services.github_cloud_storage_service",
    "services.master_data_service",
    "services.system_settings_service",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="V171 profiler install smoke check")
    parser.add_argument("--json", default="reports/v171_performance_profiler_check.json")
    args = parser.parse_args()
    results = []
    ok = True
    for name in MODULES:
        row = {"module": name, "import_ok": False, "error": ""}
        try:
            mod = importlib.import_module(name)
            row["import_ok"] = True
            profiled = []
            for attr in ("query_df", "query_one", "execute", "load_records", "today_records", "start_work", "finish_work", "write_log", "check_permission", "require_login", "load_authority", "save_authority", "load_work_orders", "load_employees"):
                obj = getattr(mod, attr, None)
                if callable(obj) and getattr(obj, "__spt_v171_profiled__", False):
                    profiled.append(attr)
            row["profiled_functions"] = profiled
        except Exception as exc:
            msg = str(exc)[:500]
            row["error"] = msg
            # The local packaging container may not have Streamlit installed; production Streamlit Cloud does.
            # Do not fail this smoke test for optional UI dependency import while validating non-visual profiler files.
            if "No module named 'streamlit'" in msg or 'No module named "streamlit"' in msg:
                row["skipped_optional_dependency"] = "streamlit"
            else:
                ok = False
        results.append(row)
    try:
        from services.performance_profiler_service import record_event, write_summary_json
        record_event(category="self_test", name="tools.v171_performance_profiler_check", duration_ms=888.0, ok=True, threshold_ms=1.0, detail={"check": "ok"})
        report = write_summary_json("reports/v171_performance_profile_self_test.json", last_hours=24, top_n=10)
    except Exception as exc:
        ok = False
        report = {"error": str(exc)[:500]}
    out = {"ok": ok, "modules": results, "self_test_report": report}
    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
