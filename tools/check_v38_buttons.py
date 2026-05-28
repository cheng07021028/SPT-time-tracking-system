# -*- coding: utf-8 -*-
from pathlib import Path
import ast, re, py_compile, sys
pages=Path('pages')
required=['02_02. 歷史紀錄.py','03_03. 製令管理.py','04_04. 人員名單.py','07_07. 今日未紀錄名單.py','10_10. 權限管理.py']
errors=[]
def all_func_names(tree):
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in required:
    p=pages/name
    if not p.exists(): errors.append(f'MISSING PAGE: {name}'); continue
    try: py_compile.compile(str(p), doraise=True)
    except Exception as e: errors.append(f'COMPILE ERROR {name}: {e}')
    text=p.read_text(encoding='utf-8')
    tree=ast.parse(text)
    callbacks=re.findall(r'on_click\s*=\s*([A-Za-z_][A-Za-z0-9_]*)', text)
    funcs=all_func_names(tree)
    for cb in callbacks:
        if cb not in funcs:
            errors.append(f'MISSING CALLBACK {name}: {cb}')
for p in pages.glob('*.py'):
    if '#U' in p.name:
        errors.append(f'MOJIBAKE PAGE STILL EXISTS: {p.name}')
if errors:
    print('\n'.join(errors)); sys.exit(1)
print('PASS: V38 pages compile, callbacks exist, and no #U page files remain.')
