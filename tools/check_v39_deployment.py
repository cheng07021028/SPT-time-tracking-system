# -*- coding: utf-8 -*-
"""V39 deployment check: page filenames, callbacks, imports, and compile validation."""
from __future__ import annotations

import ast
import py_compile
from pathlib import Path

ROOT = Path.cwd()
PAGES = ROOT / 'pages'
SERVICES = ROOT / 'services'
TOOLS = ROOT / 'tools'

NORMAL_PAGES = [
    '01_01. 工時紀錄.py',
    '02_02. 歷史紀錄.py',
    '03_03. 製令管理.py',
    '04_04. 人員名單.py',
    '05_05. 製令工時分析.py',
    '06_06. LOG查詢.py',
    '07_07. 今日未紀錄名單.py',
    '08_08. 人員每日工時.py',
    '09_09. 資料永久保存與備份.py',
    '10_10. 權限管理.py',
    '11_11. 登入紀錄.py',
    '12_12. 模組永久紀錄中心.py',
    '13_13. 系統設定.py',
]

REQUIRED_MASTER_FUNCS = [
    'load_employees_for_time_record_fast',
    'load_work_orders_for_time_record_fast',
    'has_master_data_for_time_record_fast',
]


def is_mojibake(name: str) -> bool:
    return '#U' in name or any(token in name for token in ['Φ', '╜', 'τ', 'Σ', 'Ñ', 'Â', 'Ã', '�'])


def get_defined_functions(tree: ast.AST) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def get_onclick_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == 'on_click' and isinstance(kw.value, ast.Name):
                names.add(kw.value.id)
    return names


def check() -> list[str]:
    problems: list[str] = []
    if not PAGES.exists():
        return ['pages folder not found']
    if not SERVICES.exists():
        return ['services folder not found']

    for name in NORMAL_PAGES:
        if not (PAGES / name).exists():
            problems.append(f'MISSING normal page: pages/{name}')

    bad_pages = [p.name for p in PAGES.glob('*.py') if is_mojibake(p.name)]
    for name in sorted(bad_pages):
        problems.append(f'MOJIBAKE page remains: pages/{name}')

    # duplicate numeric prefixes after cleanup are suspicious.
    by_prefix: dict[str, list[str]] = {}
    for p in PAGES.glob('*.py'):
        prefix = p.name.split('.')[0].strip()
        by_prefix.setdefault(prefix, []).append(p.name)
    for prefix, names in sorted(by_prefix.items()):
        if len(names) > 1:
            problems.append(f'DUPLICATE page prefix {prefix}: {names}')

    # compile modified runtime files.
    for base in [PAGES, SERVICES, TOOLS]:
        if not base.exists():
            continue
        for py in base.rglob('*.py'):
            try:
                py_compile.compile(str(py), doraise=True)
            except Exception as exc:
                problems.append(f'COMPILE FAIL {py}: {exc}')

    # callback definitions must exist in each page before runtime.
    for py in PAGES.glob('*.py'):
        try:
            tree = ast.parse(py.read_text(encoding='utf-8-sig'))
        except Exception as exc:
            problems.append(f'AST FAIL {py}: {exc}')
            continue
        defined = get_defined_functions(tree)
        callbacks = get_onclick_names(tree)
        missing = sorted(cb for cb in callbacks if cb not in defined)
        for cb in missing:
            problems.append(f'MISSING CALLBACK in {py.name}: {cb}')

    master = SERVICES / 'master_data_service.py'
    if master.exists():
        try:
            tree = ast.parse(master.read_text(encoding='utf-8-sig'))
            defined = get_defined_functions(tree)
            for fn in REQUIRED_MASTER_FUNCS:
                if fn not in defined:
                    problems.append(f'MISSING master_data_service.{fn}')
        except Exception as exc:
            problems.append(f'AST FAIL master_data_service.py: {exc}')
    else:
        problems.append('MISSING services/master_data_service.py')

    return problems


def main() -> int:
    problems = check()
    if problems:
        print('FAIL: V39 deployment check found problems:')
        for p in problems:
            print(' -', p)
        return 1
    print('PASS: V39 normal pages are active, no #U/mojibake pages remain, callbacks exist, and imports compile.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
