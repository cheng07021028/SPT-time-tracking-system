# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.legacy_neon_migration_service import migrate_legacy_source_to_neon


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/migrate_legacy_to_neon.py <legacy_project.zip or folder>")
    result = migrate_legacy_source_to_neon(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
