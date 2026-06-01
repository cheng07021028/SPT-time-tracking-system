# -*- coding: utf-8 -*-
from pathlib import Path
import sys, json
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from services.persistence_guard_service import create_persistent_backup

if __name__ == "__main__":
    result = create_persistent_backup(reason="manual_before_update", include_database=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)
