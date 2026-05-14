# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"

for name in ["03. 製令管理.py", "3_製令管理.py", "04. 人員名單.py", "4_人員名單.py"]:
    p = PAGES / name
    if p.exists():
        try:
            p.unlink()
            print(f"Deleted duplicate old page: {name}")
        except Exception as e:
            print(f"Cannot delete {name}: {e}")

print("V1.14 CRUD setup completed. Please restart Streamlit.")
