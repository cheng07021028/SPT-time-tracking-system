# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import shutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = PROJECT_ROOT / "services" / "time_record_service.py"
PATCH = PROJECT_ROOT / "services" / "time_record_service_v163_daily_close_guard_patch.py"
MARKER = "V163 DAILY CLOSE LOCK GUARD"


def main() -> int:
    if not TARGET.exists():
        print(f"ERROR: target not found: {TARGET}")
        return 2
    if not PATCH.exists():
        print(f"ERROR: patch not found: {PATCH}")
        return 2
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("V163 daily close guard already applied. No change.")
        return 0
    bak = TARGET.with_suffix(TARGET.suffix + ".bak_v162_before_v163_daily_close")
    if not bak.exists():
        shutil.copy2(TARGET, bak)
        print(f"Backup created: {bak}")
    patch_text = PATCH.read_text(encoding="utf-8")
    TARGET.write_text(text.rstrip() + "\n\n" + patch_text.strip() + "\n", encoding="utf-8", newline="\n")
    print("V163 daily close guard appended to services/time_record_service.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
