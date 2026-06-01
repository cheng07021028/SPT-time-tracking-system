# -*- coding: utf-8 -*-
"""V39: Remove old #Uxxxx / mojibake Streamlit page files after normal Chinese pages exist.

Run from project root. Safe behavior:
- Only deletes known old page filenames when corresponding normal filename exists.
- Does not delete data, services, or permanent_store.
"""
from pathlib import Path

PAGE_MAP = {
    '01_01. #U5de5#U6642#U7d00#U9304.py': '01_01. 工時紀錄.py',
    '02_02. #U6b77#U53f2#U7d00#U9304.py': '02_02. 歷史紀錄.py',
    '03_03. #U88fd#U4ee4#U7ba1#U7406.py': '03_03. 製令管理.py',
    '04_04. #U4eba#U54e1#U540d#U55ae.py': '04_04. 人員名單.py',
    '05_05. #U88fd#U4ee4#U5de5#U6642#U5206#U6790.py': '05_05. 製令工時分析.py',
    '06_06. LOG#U67e5#U8a62.py': '06_06. LOG查詢.py',
    '07_07. #U4eca#U65e5#U672a#U7d00#U9304#U540d#U55ae.py': '07_07. 今日未紀錄名單.py',
    '08_08. #U4eba#U54e1#U6bcf#U65e5#U5de5#U6642.py': '08_08. 人員每日工時.py',
    '09_09. #U8cc7#U6599#U6c38#U4e45#U4fdd#U5b58#U8207#U5099#U4efd.py': '09_09. 資料永久保存與備份.py',
    '10_10. #U6b0a#U9650#U7ba1#U7406.py': '10_10. 權限管理.py',
    '11_11. #U767b#U5165#U7d00#U9304.py': '11_11. 登入紀錄.py',
    '12_12. #U6a21#U7d44#U6c38#U4e45#U7d00#U9304#U4e2d#U5fc3.py': '12_12. 模組永久紀錄中心.py',
    '13_13. #U7cfb#U7d71#U8a2d#U5b9a.py': '13_13. 系統設定.py',
}

# Other common mojibake variants observed on Windows unzip / upload. Kept conservative.
PREFIXES = [f"{i:02d}_{i:02d}." for i in range(1, 14)]


def is_mojibake_page(path: Path) -> bool:
    name = path.name
    if '#U' in name:
        return True
    # Avoid deleting normal Chinese or expected English files. Only delete known page-prefix files
    # with mojibake symptoms.
    suspicious = any(token in name for token in ['Φ', '╜', 'τ', 'Σ', 'Ñ', 'Â', 'Ã', '�'])
    return suspicious and any(name.startswith(prefix) for prefix in PREFIXES)


def main() -> int:
    pages = Path('pages')
    if not pages.exists():
        print('ERROR: pages folder not found. Run from project root.')
        return 2

    removed = []
    skipped_missing_normal = []

    for old, new in PAGE_MAP.items():
        old_path = pages / old
        new_path = pages / new
        if old_path.exists():
            if new_path.exists():
                old_path.unlink()
                removed.append(old)
            else:
                skipped_missing_normal.append((old, new))

    # Remove additional mojibake page files only when another normal file with same numeric prefix exists.
    normal_by_prefix = {p.name.split('.')[0].strip(): p for p in pages.glob('*.py') if '#U' not in p.name and not is_mojibake_page(p)}
    for p in list(pages.glob('*.py')):
        if not is_mojibake_page(p):
            continue
        prefix = p.name.split('.')[0].strip()
        if prefix in normal_by_prefix and p.exists():
            p.unlink()
            removed.append(p.name)

    pycache = pages / '__pycache__'
    if pycache.exists():
        for p in pycache.glob('*'):
            try:
                p.unlink()
            except Exception:
                pass

    if skipped_missing_normal:
        print('WARNING: some old page files were kept because normal replacements are missing:')
        for old, new in skipped_missing_normal:
            print(f' - {old} -> missing {new}')

    print(f'Removed old/mojibake page files: {len(removed)}')
    for x in removed:
        print(' -', x)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
