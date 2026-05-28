# -*- coding: utf-8 -*-
"""V161 smoke test for global large-table lazy display patch.

This test does not import Streamlit pages or modify project data.  It verifies
that services/table_ui_service.py contains the V161 override and compiles.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "services" / "table_ui_service.py"


def main() -> int:
    if not TARGET.exists():
        print(f"FAIL: missing {TARGET}")
        return 1
    text = TARGET.read_text(encoding="utf-8")
    required = [
        "V161 GLOBAL LARGE TABLE LAZY DISPLAY",
        "def _v161_slice_large_table_for_display",
        "def render_table(",
        "show_width_settings",
    ]
    missing = [x for x in required if x not in text]
    if missing:
        print("FAIL: missing markers:", ", ".join(missing))
        return 2
    py_compile.compile(str(TARGET), doraise=True)
    print("PASS: V161 table lazy display patch is present and table_ui_service.py compiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
