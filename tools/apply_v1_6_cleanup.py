# -*- coding: utf-8 -*-
"""Cleanup/rename Streamlit pages for V1.6.
- Keeps one canonical file per page.
- Renames files so the sidebar shows 01. / 02. labels.
- Deletes duplicate old page names.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"

PAGE_KEYWORDS = [
    ("工時紀錄", "01_01. 工時紀錄.py"),
    ("歷史紀錄", "02_02. 歷史紀錄.py"),
    ("製令管理", "03_03. 製令管理.py"),
    ("人員名單", "04_04. 人員名單.py"),
    ("製令工時分析", "05_05. 製令工時分析.py"),
    ("LOG查詢", "06_06. LOG查詢.py"),
    ("今日未紀錄名單", "07_07. 今日未紀錄名單.py"),
    ("人員每日工時", "08_08. 人員每日工時.py"),
]


def score_candidate(path: Path, keyword: str) -> int:
    name = path.name
    score = 0
    if keyword in name:
        score += 10
    if name[:2].isdigit():
        score += 3
    if name.startswith("01_") or name.startswith("02_") or name.startswith("03_") or name.startswith("04_") or name.startswith("05_") or name.startswith("06_") or name.startswith("07_") or name.startswith("08_"):
        score += 2
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "render_header" in text or "render_page_header" in text:
            score += 2
        if "import apply_theme" in text or "apply_theme" in text:
            score += 1
    except Exception:
        pass
    return score


def main() -> None:
    print("============================================")
    print("SPT Time Tracking V1.6 cleanup start")
    print("Project:", ROOT)
    print("Pages:", PAGES)
    if not PAGES.exists():
        print("pages folder not found.")
        return

    all_pages = [p for p in PAGES.glob("*.py") if p.is_file() and p.name != "__init__.py"]
    touched: set[Path] = set()

    for keyword, canonical_name in PAGE_KEYWORDS:
        canonical = PAGES / canonical_name
        candidates = [p for p in all_pages if keyword in p.name]
        if not candidates:
            print(f"MISS: {keyword}")
            continue
        candidates.sort(key=lambda p: (score_candidate(p, keyword), p.stat().st_mtime), reverse=True)
        keeper = candidates[0]
        if keeper.resolve() != canonical.resolve():
            if canonical.exists():
                backup = PAGES / (canonical.stem + ".bak_v16.py")
                shutil.move(str(canonical), str(backup))
                print("backup existing canonical:", backup.name)
            shutil.move(str(keeper), str(canonical))
            print(f"RENAMED: {keeper.name} -> {canonical.name}")
        else:
            print(f"KEEP: {canonical.name}")
        touched.add(canonical.resolve())

        # delete duplicates for same keyword
        for p in list(PAGES.glob("*.py")):
            if p.name == "__init__.py":
                continue
            if keyword in p.name and p.resolve() != canonical.resolve():
                try:
                    p.unlink()
                    print("DELETE duplicate:", p.name)
                except Exception as exc:
                    print("WARN cannot delete", p.name, exc)

    print("============================================")
    print("Final pages:")
    for p in sorted(PAGES.glob("*.py")):
        print(" -", p.name)
    print("SPT Time Tracking V1.6 cleanup completed.")
    print("============================================")


if __name__ == "__main__":
    main()
