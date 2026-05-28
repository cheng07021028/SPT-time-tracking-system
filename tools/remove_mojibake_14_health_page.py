# -*- coding: utf-8 -*-
"""Remove mojibake duplicate page files for 14. 資料健康檢查中心.

Run from project root:
    python tools/remove_mojibake_14_health_page.py
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = PROJECT_ROOT / "pages"
KEEP_NAME = "14_14. 資料健康檢查中心.py"

BAD_PATTERNS = [
    "#U8cc7#U6599#U5065#U5eb7#U6aa2#U67e5#U4e2d#U5fc3",
    "資料健康檢查中心".encode("utf-8").decode("cp437", errors="ignore"),
    "Φ│çµûÖσüÑσ║╖µ¬óµƒÑΣ╕¡σ┐â",
]


def main() -> int:
    if not PAGES_DIR.exists():
        print(f"pages folder not found: {PAGES_DIR}")
        return 1
    removed = 0
    keep = PAGES_DIR / KEEP_NAME
    for path in PAGES_DIR.glob("14_14*.py"):
        if path.name == KEEP_NAME:
            continue
        name = path.name
        if any(p and p in name for p in BAD_PATTERNS) or "#U" in name:
            try:
                path.unlink()
                print(f"removed: {path}")
                removed += 1
            except Exception as exc:
                print(f"failed to remove {path}: {exc}")
    print(f"done. removed={removed}; keep={keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
