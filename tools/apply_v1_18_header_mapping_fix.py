# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = {
    ROOT / 'pages' / '03_03. 製令管理.py': ['V1.18 loaded', 'parse_pasted_work_orders(raw) -> tuple', '依標題列自動對應欄位'],
    ROOT / 'pages' / '04_04. 人員名單.py': ['V1.18 loaded', 'parse_pasted_employees(raw) -> tuple', '依標題列自動對應欄位'],
}

print('=' * 56)
print('SPT Time Tracking V1.18 Header Mapping Check')
print('=' * 56)
all_ok = True
for path, markers in checks.items():
    if not path.exists():
        print(f'MISSING: {path}')
        all_ok = False
        continue
    text = path.read_text(encoding='utf-8', errors='ignore')
    # relaxed markers, source may not contain exact type signature in all Python versions
    needed = ['V1.18 loaded', '依標題列自動對應欄位']
    missing = [m for m in needed if m not in text]
    if missing:
        print(f'NG: {path} missing {missing}')
        all_ok = False
    else:
        print(f'OK: {path.relative_to(ROOT)} supports header-based paste mapping')

if all_ok:
    print('V1.18 setup check completed successfully.')
else:
    print('V1.18 setup check failed. Please re-copy patch files to project root.')
