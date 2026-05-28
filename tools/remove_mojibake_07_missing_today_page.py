# -*- coding: utf-8 -*-
"""Remove legacy mojibake 07 page after installing the no-mojibake page."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "pages" / "07_07. #U4eca#U65e5#U672a#U7d00#U9304#U540d#U55ae.py"
KEEP = ROOT / "pages" / "07_07. 今日未紀錄名單.py"

if not KEEP.exists():
    raise SystemExit(f"正確檔案不存在，停止刪除：{KEEP}")
if LEGACY.exists():
    LEGACY.unlink()
    print(f"已刪除舊亂碼頁面：{LEGACY}")
else:
    print("沒有找到舊亂碼 07 頁面，不需刪除。")
print(f"正確保留：{KEEP}")
