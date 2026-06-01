# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]


def main() -> int:
    removed = []
    for p in TARGETS:
        if p.exists():
            p.unlink()
            removed.append(str(p.relative_to(ROOT)))
    normal = ROOT / "pages" / "10_10. 權限管理.py"
    if not normal.exists():
        print("ERROR: pages/10_10. 權限管理.py 不存在，請先覆蓋 V55 修改檔。")
        return 1
    if removed:
        print("已刪除舊亂碼頁面：")
        for x in removed:
            print(" -", x)
    else:
        print("未發現需刪除的 10_10 #U 亂碼頁面。")
    print("OK: 保留正常中文頁面 pages/10_10. 權限管理.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
