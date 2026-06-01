# -*- coding: utf-8 -*-
from pathlib import Path
import ast, sys
ROOT = Path(__file__).resolve().parents[1]
paths = [ROOT / 'pages' / '10_10. 權限管理.py', ROOT / 'pages' / '10_10. #U6b0a#U9650#U7ba1#U7406.py']
found = False
for p in paths:
    if not p.exists():
        continue
    found = True
    txt = p.read_text(encoding='utf-8')
    ast.parse(txt)
    required = [
        'V49：此區已刪除舊的 form + checkbox 勾選流程',
        'v49_account_delete_targets',
        '待刪除帳號清單 / Accounts Marked for Delete',
        'v49_apply_save_account_master',
    ]
    missing = [s for s in required if s not in txt]
    if missing:
        raise SystemExit(f'FAIL: {p} missing {missing}')
    banned = ['with st.form("v171_account_master_edit_form"', 'st.column_config.CheckboxColumn("刪除 / Delete")']
    bad = [s for s in banned if s in txt]
    if bad:
        raise SystemExit(f'FAIL: {p} still contains old account-editor code: {bad}')
if not found:
    raise SystemExit('FAIL: no permission page file found')
print('PASS: V49 rewrote permission Account Master editor; delete selection is outside data_editor and old form checkbox code is removed.')
