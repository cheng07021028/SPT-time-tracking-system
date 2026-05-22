# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
ROOT = Path(__file__).resolve().parents[1]
for rel in [
    "pages/01_01. 工時紀錄.py",
    "pages/10_10. 權限管理.py",
    "services/time_record_service.py",
    "services/permission_service.py",
]:
    py_compile.compile(str(ROOT / rel), doraise=True)
print("V94 check OK")
