from __future__ import annotations
import compileall
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

checks = []
checks.append(("compileall", compileall.compile_dir(str(ROOT), quiet=1)))
for rel in [
    "services/db_service.py",
    "services/log_service.py",
    "services/neon_authority_service.py",
    "services/neon_performance_audit_service.py",
    "pages/07_07. 今日未紀錄名單.py",
    "pages/99_99. 效能診斷.py",
]:
    p = ROOT / rel
    checks.append((f"exists:{rel}", p.exists()))

bad_names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if "#U" in p.name]
checks.append(("no_mojibake_names", not bad_names))

for name, ok in checks:
    print(f"{name}: {'OK' if ok else 'FAIL'}")
if bad_names:
    print("bad_names=", bad_names)
if not all(ok for _, ok in checks):
    sys.exit(1)
