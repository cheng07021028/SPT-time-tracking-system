# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / "pages" / "10_10. 權限管理.py",
    ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]
required = [
    "v53-normal-checkbox-direct-draft",
    "☑ 刪除全選 / Select Delete",
    "☐ 刪除取消 / Clear Delete",
    "☑ 啟用全選 / Active All",
    "☐ 啟用取消 / Inactive All",
    "st.data_editor(",
    "key=account_editor_key",
]
for p in paths:
    if not p.exists():
        raise SystemExit(f"MISSING: {p}")
    text = p.read_text(encoding="utf-8")
    missing = [s for s in required if s not in text]
    if missing:
        raise SystemExit(f"FAIL: {p} missing {missing}")
    bad = ["with st.form(\"v171_account_master_edit_form", "_selected_delete_usernames(df, account_editor_key)"]
    bad_found = [s for s in bad if s in text]
    if bad_found:
        raise SystemExit(f"FAIL: old account editor form/delete fallback still exists in {p}: {bad_found}")
print("PASS: V53 Account Master uses normal checkbox buttons for delete/active all, without old form overwrite logic.")
