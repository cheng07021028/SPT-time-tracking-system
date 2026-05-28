# -*- coding: utf-8 -*-
"""Install/init Persistence Guard marker and first backup."""
from pathlib import Path
import sys, json
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from services.persistence_guard_service import ensure_initialized_marker, create_persistent_backup, check_persistent_health

if __name__ == "__main__":
    ensure_initialized_marker()
    backup = create_persistent_backup(reason="install_persistence_guard", include_database=True)
    health = check_persistent_health(write_manifest=True)
    print(json.dumps({"backup": backup, "health": health}, ensure_ascii=False, indent=2, default=str))
