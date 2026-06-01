# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / 'pages' / '10_10. 權限管理.py',
    ROOT / 'pages' / '10_10. #U6b0a#U9650#U7ba1#U7406.py',
]
existing = [p for p in paths if p.exists()]
if not existing:
    raise SystemExit('FAIL: 10 permission page not found')
for p in existing:
    text = p.read_text(encoding='utf-8')
    ast.parse(text)
    must = [
        'V41：帳號總表不再放入 st.form',
        'v41_apply_save_account_master',
        'bulk_render_protected',
    ]
    missing = [m for m in must if m not in text]
    if missing:
        raise SystemExit(f'FAIL: {p} missing {missing}')
    if 'with st.form("v171_account_master_edit_form"' in text:
        raise SystemExit(f'FAIL: {p} still uses account master st.form')
print('PASS: V41 permission account editor uses no-form data_editor and bulk state protection.')
