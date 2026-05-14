# -*- coding: utf-8 -*-
"""V1.21 setup/check: verify persistence service compatibility."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED = [
    "BACKUP_DIR",
    "create_persistent_backup",
    "create_backup_and_push_to_github",
    "git_backup_push",
    "list_database_tables",
    "load_latest_manifest",
    "read_table",
    "export_permanent_state",
    "restore_permanent_state",
    "STATE_JSON",
    "SETTINGS_JSON",
]


def main() -> int:
    import services.persistence_service as ps
    missing = [name for name in REQUIRED if not hasattr(ps, name)]
    print("=" * 60)
    print("SPT V1.21 Persistence Import Fix Check")
    print("=" * 60)
    if missing:
        print("ERROR: missing names:", ", ".join(missing))
        return 1
    ps.write_gitkeep()
    print("OK: services.persistence_service supports V1.10 backup page and V1.20 permanent state tools.")
    print(f"Backup folder: {ps.BACKUP_DIR}")
    print(f"Permanent state: {ps.STATE_JSON}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
