# -*- coding: utf-8 -*-
"""Static checks for V95 permission authority/speed patch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
perm = ROOT / "services" / "permission_service.py"
page10 = ROOT / "pages" / "10_10. 權限管理.py"
page01 = ROOT / "pages" / "01_01. 工時紀錄.py"

checks = []
pt = perm.read_text(encoding="utf-8")
checks.append(("permission V95 marker", "V95 PERMISSION SINGLE-AUTHORITY SPEED" in pt))
checks.append(("single authority path", "data/permanent_store/modules/10_permissions/records.json" in pt))
checks.append(("auth_account_permissions persisted", '"auth_account_permissions"' in pt))
checks.append(("cached restore", "authority_already_restored" in pt and "_V95_LAST_RESTORE_SIG" in pt))
checks.append(("default restore disabled", "v95_disabled_default_restore" in pt))
checks.append(("delete tombstone", "deleted_usernames" in pt and "save_account_master" in pt))

t10 = page10.read_text(encoding="utf-8")
checks.append(("10 raw editor helper", "def _v95_raw_data_editor" in t10))
checks.append(("10 account raw editor", "edited_users = _v95_raw_data_editor" in t10))
checks.append(("10 permission raw editor", "edited_perm = _v95_raw_data_editor" in t10))
checks.append(("10 lazy excel", "v95_build_permission_management_excel" in t10 and "_build_permission_excel_export_v93()" in t10))

t01 = page01.read_text(encoding="utf-8")
checks.append(("01 raw editor helper", "def _v95_raw_data_editor" in t01))
checks.append(("01 admin raw editor", "edited_admin_return = _v95_raw_data_editor" in t01))

failed = [name for name, ok in checks if not ok]
if failed:
    print("FAILED:")
    for f in failed:
        print(" -", f)
    raise SystemExit(1)
print("V95 checks passed")
