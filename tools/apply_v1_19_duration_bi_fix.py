# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = {
    ROOT / "services" / "duration_service.py": ["hours_to_hms", "hms_to_hours"],
    ROOT / "services" / "table_ui_service.py": ["工時小計 / Work Time", "同時作業 / Parallel Work", "排序設定 / Sort Settings"],
    ROOT / "services" / "time_record_service.py": ["hms_to_hours"],
    ROOT / "pages" / "02_02. 歷史紀錄.py": ["hours_to_hms", "Total Time"],
    ROOT / "pages" / "03_03. 製令管理.py": ["sort_editor_state"],
    ROOT / "pages" / "04_04. 人員名單.py": ["sort_editor_state"],
    ROOT / "pages" / "05_05. 製令工時分析.py": ["plotly_dark", "累積工時 / Total Time"],
    ROOT / "pages" / "08_08. 人員每日工時.py": ["BI 工時分布", "hours_to_hms"],
}

ok = True
for path, needles in checks.items():
    if not path.exists():
        print(f"ERROR: missing {path.relative_to(ROOT)}")
        ok = False
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [n for n in needles if n not in text]
    if missing:
        print(f"ERROR: {path.relative_to(ROOT)} missing markers: {missing}")
        ok = False
    else:
        print(f"OK: {path.relative_to(ROOT)} updated for V1.19")

if ok:
    print("SPT Time Tracking V1.19 duration / sorting / BI patch check completed.")
else:
    raise SystemExit(1)
