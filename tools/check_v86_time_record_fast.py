# -*- coding: utf-8 -*-
"""V86 quick validation for 01 time record fast-load patch."""
from __future__ import annotations
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
CHECK_FILES = [
    ROOT / "pages" / "01_01. 工時紀錄.py",
    ROOT / "services" / "time_record_service.py",
    ROOT / "services" / "security_service.py",
    ROOT / "services" / "master_data_service.py",
    ROOT / "services" / "system_settings_service.py",
    ROOT / "services" / "permanent_authority_service.py",
]


def main() -> int:
    missing = [str(p) for p in CHECK_FILES if not p.exists()]
    if missing:
        print("Missing files:")
        for p in missing:
            print(" -", p)
        return 1
    for p in CHECK_FILES:
        py_compile.compile(str(p), doraise=True)
        print("OK", p.relative_to(ROOT))
    print("V86 check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
