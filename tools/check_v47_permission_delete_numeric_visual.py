# -*- coding: utf-8 -*-
"""Check V47 permission account delete visual selector patch."""
from __future__ import annotations
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
page = ROOT / 'pages' / '10_10. 權限管理.py'
alt = ROOT / 'pages' / '10_10. #U6b0a#U9650#U7ba1#U7406.py'
text = page.read_text(encoding='utf-8') if page.exists() else ''
required = [
    '刪除選擇 / Delete Select',
    '刪除顯示 / Delete Display',
    '_v47_sync_delete_numeric_visual',
    '_v47_apply_numeric_visual_to_bool',
    'v47_mode',
    'numeric-delete-select-0-1-visible-selector',
]
missing = [s for s in required if s not in text]
if missing:
    raise SystemExit('FAIL: missing V47 markers: ' + ', '.join(missing))
py_compile.compile(str(page), doraise=True)
if alt.exists():
    py_compile.compile(str(alt), doraise=True)
print('PASS: V47 permission account delete selector uses visible 0/1 numeric column and compiles.')
