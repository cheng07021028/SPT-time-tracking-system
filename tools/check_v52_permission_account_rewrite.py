# -*- coding: utf-8 -*-
from pathlib import Path
import ast
root = Path(__file__).resolve().parents[1]
files = [root / "pages" / "10_10. 權限管理.py", root / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py"]
seen = False
for p in files:
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    ast.parse(text)
    required = [
        "V52", "_v52_select_all_delete", "_v52_clear_delete", "_v52_save_account_master",
        "待刪除帳號清單 / Accounts Marked for Delete", "v52_account_editor_", "account-master-rewrite-delete-outside-data-editor"
    ]
    missing = [s for s in required if s not in text]
    forbidden = ["with st.form(\"v171_account_master_edit_form", "CheckboxColumn(\"刪除 / Delete\""]
    bad = [s for s in forbidden if s in text]
    if missing:
        raise SystemExit(f"FAIL {p}: missing {missing}")
    if bad:
        raise SystemExit(f"FAIL {p}: old delete/form code remains {bad}")
    seen = True
if not seen:
    raise SystemExit("FAIL: no permission page found")
print("PASS: V52 Account Master rewrite is active; delete selection is outside data_editor and old delete checkbox/form code is removed.")
