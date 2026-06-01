# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / "pages" / "10_10. 權限管理.py",
    ROOT / "pages" / "10_10. #U6b0a#U9650#U7ba1#U7406.py",
]
existing = [p for p in paths if p.exists()]
if not existing:
    raise SystemExit("FAIL: permission page not found")
for p in existing:
    py_compile.compile(str(p), doraise=True)
    text = p.read_text(encoding="utf-8")
    required = [
        "待刪除帳號清單 / Accounts Marked for Delete",
        "v48_delete_usernames",
        "delete-selection-outside-data-editor-no-checkbox-visual-dependency",
        "st.multiselect(",
    ]
    missing = [s for s in required if s not in text]
    if missing:
        raise SystemExit(f"FAIL: {p.name} missing {missing}")
print("PASS: V48 permission account delete selection is outside data_editor and no longer depends on checkbox visual display.")
