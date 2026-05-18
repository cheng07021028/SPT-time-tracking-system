# -*- coding: utf-8 -*-
from pathlib import Path
import sys, json
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from services.persistence_guard_service import check_persistent_health

if __name__ == "__main__":
    result = check_persistent_health(write_manifest=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("errors"):
        raise SystemExit(1)
    raise SystemExit(0)
