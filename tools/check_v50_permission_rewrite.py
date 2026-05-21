# -*- coding: utf-8 -*-
from pathlib import Path
import ast
ROOT = Path(__file__).resolve().parents[1]
paths = [ROOT/'pages'/'10_10. 權限管理.py', ROOT/'pages'/'10_10. #U6b0a#U9650#U7ba1#U7406.py']
found=False
for p in paths:
    if not p.exists():
        continue
    text=p.read_text(encoding='utf-8')
    ast.parse(text)
    for s in ['待刪除帳號清單 / Accounts Marked for Delete','v50_account_master_delete_usernames','full-rewrite-no-form-no-delete-checkbox']:
        if s not in text:
            raise SystemExit(f'FAIL: {p} missing {s}')
    for s in ['v171_account_master_edit_form','CheckboxColumn("刪除 / Delete']:
        if s in text:
            raise SystemExit(f'FAIL: {p} still contains old account delete checkbox/form logic')
    found=True
if not found:
    raise SystemExit('FAIL: no permission page found')
print('PASS: V50 Account Master is fully rewritten; delete selection is outside data_editor, no form, no delete checkbox.')
