# -*- coding: utf-8 -*-
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / 'pages'
SERVICES = ROOT / 'services'
TARGETS = [
    '02_02. 歷史紀錄.py',
    '03_03. 製令管理.py',
    '04_04. 人員名單.py',
    '07_07. 今日未紀錄名單.py',
    '10_10. 權限管理.py',
]

def collect_defs(tree):
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def collect_on_click_names(tree):
    names=[]
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg=='on_click':
                    v=kw.value
                    if isinstance(v, ast.Name):
                        names.append((v.id, n.lineno))
    return names

def main():
    errors=[]
    if not (SERVICES/'button_rule_service.py').exists():
        errors.append('MISSING services/button_rule_service.py')
    for old in PAGES.glob('*#U*.py'):
        errors.append(f'MOJIBAKE PAGE STILL EXISTS: {old.name}')
    for fn in TARGETS:
        p=PAGES/fn
        if not p.exists():
            errors.append(f'MISSING PAGE: {fn}')
            continue
        text=p.read_text(encoding='utf-8')
        if 'from services.button_rule_service import render_button' not in text:
            errors.append(f'MISSING render_button import: {fn}')
        if '_last_button_action' not in text:
            errors.append(f'MISSING last button action marker: {fn}')
        tree=ast.parse(text)
        defs=collect_defs(tree)
        for name,lineno in collect_on_click_names(tree):
            if name not in defs and name != 'None':
                errors.append(f'MISSING CALLBACK: {fn}:{lineno} -> {name}')
    if errors:
        print('FAIL')
        for e in errors:
            print(' -', e)
        raise SystemExit(1)
    print('PASS: V36 button integration files compile, no mojibake pages expected, callbacks are defined.')

if __name__=='__main__':
    main()
