# -*- coding: utf-8 -*-
"""Run V300.15 authority-chain diagnostics.

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

from services.authority_trace_service import render_markdown_report, save_snapshot


def main() -> int:
    snapshot = save_snapshot(ROOT)
    report = render_markdown_report(snapshot)
    out_dir = ROOT / "data" / "permanent_store" / "authority_trace"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "V300_15_AUTHORITY_TRACE_REPORT.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"V300.15 authority trace snapshot saved: {out_dir / 'v30015_latest_snapshot.json'}")
    print(f"V300.15 authority trace report saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
