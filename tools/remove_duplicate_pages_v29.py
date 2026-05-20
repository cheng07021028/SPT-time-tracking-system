# -*- coding: utf-8 -*-
"""Remove old duplicated Streamlit page files (#Uxxxx / mojibake) after V29.
Run from project root: python tools/remove_duplicate_pages_v29.py
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
KEEP_KEYWORDS = ["工時紀錄", "歷史紀錄", "製令管理", "人員名單", "製令工時分析", "LOG查詢", "今日未紀錄名單", "人員每日工時", "資料永久保存", "權限管理", "登入紀錄", "模組永久紀錄中心", "系統設定"]

def is_legacy_duplicate(path: Path) -> bool:
    name = path.name
    if not name.endswith(".py"):
        return False
    if "#U" in name:
        return True
    # Common mojibake fragments seen when Chinese filenames were decoded incorrectly.
    bad_fragments = ["Φ", "τ", "Σ", "╜", "╕", "╢", "╡", "Θ", "Γ"]
    if any(x in name for x in bad_fragments):
        return True
    return False

def main() -> int:
    removed = []
    if not PAGES.exists():
        print("pages folder not found")
        return 1
    for p in sorted(PAGES.glob("*.py")):
        if is_legacy_duplicate(p):
            print(f"DELETE legacy duplicate: {p.relative_to(ROOT)}")
            p.unlink()
            removed.append(str(p.relative_to(ROOT)))
    print(f"removed={len(removed)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
