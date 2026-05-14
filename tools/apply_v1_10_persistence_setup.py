# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.10 Persistence Setup

功能：
1. 建立 data/persistent_backups/.gitkeep
2. 安全追加 .gitignore 規則，不覆蓋既有內容
3. 確保 SQLite 主資料庫不直接上傳 GitHub
4. 確保 persistent_backups 可被 GitHub 追蹤
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "data" / "persistent_backups"
GITIGNORE = ROOT / ".gitignore"

BLOCK = """
# ===== SPT Time Tracking V1.10 Persistence Rules =====
# Local SQLite database should not be committed directly.
data/database/*.db
data/database/*.sqlite
data/database/*.sqlite3

# Persistent backup files are allowed to be tracked by GitHub.
!data/
!data/persistent_backups/
!data/persistent_backups/**
# ===== End SPT Persistence Rules =====
""".strip()


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    keep = BACKUP_DIR / ".gitkeep"
    if not keep.exists():
        keep.write_text("keep this folder for persistent GitHub backups\n", encoding="utf-8")

    old = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    if "SPT Time Tracking V1.10 Persistence Rules" not in old:
        if old and not old.endswith("\n"):
            old += "\n"
        GITIGNORE.write_text(old + "\n" + BLOCK + "\n", encoding="utf-8")

    print("=" * 60)
    print("SPT Time Tracking V1.10 Persistence Setup Completed")
    print(f"Backup folder: {BACKUP_DIR}")
    print(f"Gitignore: {GITIGNORE}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
