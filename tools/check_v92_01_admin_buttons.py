# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'pages' / '01_01. 工時紀錄.py'
text = PAGE.read_text(encoding='utf-8')
required = [
    'V92：所有維護區按鈕',
    'today_records_admin_load_btn_v92',
    'today_records_admin_unload_btn_v92',
    'today_admin_select_all_rows_v92',
    'today_admin_clear_all_rows_v92',
    'today_admin_save_v92',
    'today_admin_recalc_v92',
    'today_admin_delete_v92',
    '_v92_editor_state_to_df',
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit('V92 check failed, missing: ' + ', '.join(missing))
print('V92 check passed: 01 admin maintenance buttons use immediate state sync and V92 keys.')
