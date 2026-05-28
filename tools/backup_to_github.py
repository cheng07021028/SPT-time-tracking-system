# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Backup to GitHub
V1.10

用法：
python tools/backup_to_github.py

功能：
1. 建立 data/persistent_backups/ 備份。
2. git add / commit / push 到 GitHub。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.persistence_service import create_backup_and_push_to_github


def main() -> int:
    result = create_backup_and_push_to_github(include_excel=True, include_csv=True)
    print("=" * 60)
    print("SPT Time Tracking Backup to GitHub")
    print("=" * 60)
    print(result.message)
    print(f"Backup dir: {result.backup_dir}")
    if result.files:
        print("Files:")
        for f in result.files:
            print(f" - {f}")
    if result.git_output:
        print("-" * 60)
        print(result.git_output)
    print("=" * 60)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
