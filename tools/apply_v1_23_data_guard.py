# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.db_service import ensure_database
from services.persistence_service import _ensure_dirs, auto_restore_if_database_empty, export_permanent_state, STATE_DIR, BACKUP_DIR

GITIGNORE = ROOT / ".gitignore"
ADD_BLOCK = """
# SPT permanent JSON state - keep in GitHub
!data/persistent_state/
!data/persistent_state/.gitkeep
!data/persistent_state/*.json
!data/persistent_state/archive/
!data/persistent_state/archive/*.json
!data/persistent_backups/
!data/persistent_backups/.gitkeep
!data/persistent_backups/latest_backup_manifest.json
!data/persistent_backups/backup_*/
!data/persistent_backups/backup_*/*.json
!data/persistent_backups/backup_*/*.csv
!data/persistent_backups/backup_*/*.xlsx

# Local SQLite DB rescue copies are not committed
data/persistent_state/db_copy/
"""

if __name__ == "__main__":
    _ensure_dirs()
    ensure_database()
    result = auto_restore_if_database_empty()
    try:
        export_permanent_state(include_logs=True, force=False)
    except Exception:
        pass
    current = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    if "# SPT permanent JSON state - keep in GitHub" not in current:
        GITIGNORE.write_text(current.rstrip() + "\n" + ADD_BLOCK + "\n", encoding="utf-8")
    print("============================================")
    print("SPT V1.23 Data Guard Setup Completed")
    print(f"Persistent state folder: {STATE_DIR}")
    print(f"Persistent backup folder: {BACKUP_DIR}")
    print(f"Auto restore result: {result}")
    print("OK: Future DB writes will refresh permanent JSON state automatically.")
    print("============================================")
