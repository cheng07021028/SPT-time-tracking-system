# -*- coding: utf-8 -*-
"""Remove old mojibake 02 History page after applying V145.

Keep:
    pages/02_02. 歷史紀錄.py
Remove if present:
    pages/02_02. #U6b77#U53f2#U7d00#U9304.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
KEEP = PAGES / "02_02. 歷史紀錄.py"
OLD = PAGES / "02_02. #U6b77#U53f2#U7d00#U9304.py"


def main() -> int:
    if not KEEP.exists():
        print(f"[WARN] 正確檔案不存在：{KEEP}")
        print("請先把 V145 修正包內的 pages/02_02. 歷史紀錄.py 上傳/覆蓋到 GitHub。")
        return 1
    if OLD.exists():
        OLD.unlink()
        print(f"[OK] 已刪除舊亂碼頁面：{OLD}")
    else:
        print("[OK] 未找到舊亂碼 02 頁面，不需刪除。")
    print(f"[KEEP] 保留：{KEEP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
