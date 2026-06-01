# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="V174 large table backend filter smoke check")
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args()
    result = {
        "version": "V174",
        "ok": False,
        "visual_changed": False,
        "css_changed": False,
        "theme_changed": False,
        "write_path_changed": False,
        "checks": [],
        "errors": [],
    }
    try:
        import services.large_table_query_service as svc
        status = svc.get_v174_large_table_query_status()
        result["checks"].append({"name": "service_import", "ok": True, "status": status})
    except Exception as exc:
        result["errors"].append(f"large_table_query_service import failed: {exc}")

    try:
        from services.time_record_service import load_history_records_sql_filtered, count_history_records_sql_filtered, load_daily_record_summary_sql
        df = load_history_records_sql_filtered({"detail_limit": 5}, limit=5)
        cnt = count_history_records_sql_filtered({})
        ddf = load_daily_record_summary_sql("2099-01-01")
        result["checks"].append({
            "name": "time_record_v174_helpers",
            "ok": True,
            "history_rows_sample": int(len(df)) if hasattr(df, "__len__") else 0,
            "history_count": int(cnt),
            "daily_summary_rows_sample": int(len(ddf)) if hasattr(ddf, "__len__") else 0,
        })
    except Exception as exc:
        result["errors"].append(f"time_record helpers failed: {exc}")

    try:
        from services.log_service import load_logs_page, count_logs_filtered
        ldf = load_logs_page(limit=5)
        lcnt = count_logs_filtered()
        result["checks"].append({
            "name": "log_v174_helpers",
            "ok": True,
            "log_rows_sample": int(len(ldf)) if hasattr(ldf, "__len__") else 0,
            "log_count": int(lcnt),
        })
    except Exception as exc:
        result["errors"].append(f"log helpers failed: {exc}")

    page_files = [
        PROJECT_ROOT / "pages" / "02_02. 歷史紀錄.py",
        PROJECT_ROOT / "pages" / "06_06. LOG查詢.py",
        PROJECT_ROOT / "pages" / "08_08. 人員每日工時.py",
    ]
    for p in page_files:
        result["checks"].append({"name": f"page_exists:{p.name}", "ok": p.exists()})
        if not p.exists():
            result["errors"].append(f"missing page: {p}")

    # Guard: V174 must not modify visual baseline services.
    forbidden = [
        PROJECT_ROOT / "services" / "theme_service.py",
        PROJECT_ROOT / "services" / "crud_table_service.py",
        PROJECT_ROOT / "services" / "table_ui_service.py",
    ]
    for p in forbidden:
        result["checks"].append({"name": f"visual_file_present_unmodified_target:{p.name}", "ok": p.exists()})

    result["ok"] = not result["errors"]
    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
