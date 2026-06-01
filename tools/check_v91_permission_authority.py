# -*- coding: utf-8 -*-
"""Check V91 permission single authority rules."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "data" / "permanent_store" / "modules" / "10_permissions" / "records.json"
SERVICE = ROOT / "services" / "permission_service.py"

text = SERVICE.read_text(encoding="utf-8")
required = [
    "V91 SINGLE CANONICAL AUTHORITY PATCH",
    "data/permanent_store/modules/10_permissions/records.json",
    "def restore_default_accounts_once_v57()",
    "v91_disabled_default_restore",
]
missing = [s for s in required if s not in text]
if missing:
    raise SystemExit(f"V91 patch missing: {missing}")

if AUTH.exists():
    data = json.loads(AUTH.read_text(encoding="utf-8"))
    tables = data.get("tables", {})
    users = tables.get("auth_users", [])
    print(f"authority file: {AUTH}")
    print(f"auth_users: {len(users)}")
    print("usernames:", ", ".join(str(u.get("username", "")) for u in users if isinstance(u, dict)))
else:
    print(f"authority file not created yet: {AUTH}")
print("V91 permission authority check passed")
