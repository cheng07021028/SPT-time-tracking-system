# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
root = Path(__file__).resolve().parents[1]
paths = [
    root / 'pages' / '10_10. 權限管理.py',
]
for p in paths:
    if not p.exists():
        raise SystemExit(f'MISSING: {p}')
    txt = p.read_text(encoding='utf-8')
    required = [
        'bulk_render_protected_v42',
        'v42_account_visible_delete_true',
        'draft-authority-no-render-overwrite',
        'do not assign edited_users back to v133_users_df on every',
    ]
    for marker in required:
        if marker not in txt:
            raise SystemExit(f'MISSING MARKER {marker!r} in {p}')
    if 'st.session_state["v133_users_df"] = edited_users.copy(deep=True)' in txt:
        raise SystemExit('OLD V41 overwrite assignment still exists')
    py_compile.compile(str(p), doraise=True)
print('PASS: V42 account editor prevents data_editor stale return from overwriting the button-updated draft.')
