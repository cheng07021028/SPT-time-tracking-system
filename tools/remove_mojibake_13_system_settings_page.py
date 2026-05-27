# -*- coding: utf-8 -*-
"""Remove legacy mojibake Streamlit page for 13 系統設定.

Run from project root after uploading pages/13_13. 系統設定.py:
    python tools/remove_mojibake_13_system_settings_page.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
LEGACY_NAMES = [
    "13_13. #U7cfb#U7d71#U8a2d#U5b9a.py",
]
KEEP = PAGES / "13_13. 系統設定.py"


def main() -> int:
    if not KEEP.exists():
        print(f"未找到正確檔案，先確認已上傳：{KEEP}")
        return 1
    removed = 0
    for name in LEGACY_NAMES:
        path = PAGES / name
        if path.exists():
            path.unlink()
            print(f"已刪除舊亂碼頁面：{path}")
            removed += 1
    if removed == 0:
        print("沒有找到需要刪除的 13 系統設定亂碼頁面。")
    else:
        print(f"完成，已刪除 {removed} 個舊亂碼頁面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
