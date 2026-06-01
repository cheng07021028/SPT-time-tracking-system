# -*- coding: utf-8 -*-
"""Run V300.15.1 all-module authority diagnostics.

Usage:
    python tools/v30015_authority_trace.py

Outputs:
    data/permanent_store/authority_trace/v30015_latest_snapshot.json
    data/permanent_store/authority_trace/V300_15_AUTHORITY_TRACE_REPORT.md
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.authority_trace_service import REPORT_FILE, SNAPSHOT_FILE, save_snapshot  # noqa: E402


def main() -> int:
    save_snapshot(ROOT)
    print(f"V300.15.1 all-module authority snapshot saved: {ROOT / SNAPSHOT_FILE}")
    print(f"V300.15.1 all-module authority report saved: {ROOT / REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
