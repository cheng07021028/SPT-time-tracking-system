# -*- coding: utf-8 -*-
"""
SPT Time Tracking System - Persistence / GitHub Backup Service
V1.10

目的：
1. 將 SQLite 內所有表單與紀錄匯出成可長期保存的備份檔。
2. 備份檔放在 data/persistent_backups/，可被 GitHub 版本控管。
3. 可由 Streamlit 頁面或 tools/backup_to_github.py 執行備份與 git push。

注意：
- SQLite 主資料庫仍維持在 data/database/spt_time_tracking.db。
- data/database/*.db 建議不要直接上傳 GitHub，避免多人覆蓋衝突。
- GitHub 備份以上傳 json / xlsx / csv 摘要為主。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "persistent_backups"
LATEST_MANIFEST = BACKUP_DIR / "latest_backup_manifest.json"


@dataclass
class BackupResult:
    ok: bool
    message: str
    backup_dir: str
    files: list[str]
    git_output: str = ""


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dirs() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    keep = BACKUP_DIR / ".gitkeep"
    if not keep.exists():
        keep.write_text("keep this folder for persistent GitHub backups\n", encoding="utf-8")


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"找不到資料庫：{DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_database_tables() -> list[str]:
    """列出目前 SQLite 內所有使用者資料表。"""
    if not DB_PATH.exists():
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    return [r["name"] for r in rows]


def read_table(table_name: str) -> pd.DataFrame:
    """讀取單一資料表。table_name 只允許來自 sqlite_master，避免 SQL injection。"""
    tables = set(list_database_tables())
    if table_name not in tables:
        raise ValueError(f"資料表不存在或不允許讀取：{table_name}")
    with _connect() as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)


def _safe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """將 DataFrame 轉成 JSON 安全格式。"""
    if df.empty:
        return []
    clean = df.copy()
    clean = clean.where(pd.notnull(clean), None)
    return clean.to_dict(orient="records")


def create_persistent_backup(include_excel: bool = True, include_csv: bool = True) -> BackupResult:
    """
    建立永久備份：
    - JSON：完整備份，最適合 GitHub diff 與長期保存
    - XLSX：主管查閱方便
    - CSV：逐表備份，方便後續程式還原或稽核
    """
    _ensure_dirs()

    if not DB_PATH.exists():
        return BackupResult(
            ok=False,
            message=f"找不到資料庫：{DB_PATH}",
            backup_dir=str(BACKUP_DIR),
            files=[],
        )

    tag = _now_tag()
    batch_dir = BACKUP_DIR / f"backup_{tag}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    tables = list_database_tables()
    payload: dict[str, Any] = {
        "backup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database_path": str(DB_PATH),
        "tables": {},
    }

    created_files: list[str] = []

    # JSON + CSV
    for table in tables:
        df = read_table(table)
        payload["tables"][table] = {
            "row_count": int(len(df)),
            "columns": list(df.columns),
            "records": _safe_records(df),
        }

        if include_csv:
            csv_path = batch_dir / f"{table}.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            created_files.append(str(csv_path.relative_to(PROJECT_ROOT)))

    json_path = batch_dir / "full_backup.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    created_files.append(str(json_path.relative_to(PROJECT_ROOT)))

    # Excel
    if include_excel:
        xlsx_path = batch_dir / "full_backup.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
            summary = pd.DataFrame(
                [
                    {
                        "資料表 / Table": table,
                        "筆數 / Records": payload["tables"][table]["row_count"],
                    }
                    for table in tables
                ]
            )
            summary.to_excel(writer, sheet_name="備份摘要", index=False)

            for table in tables:
                df = read_table(table)
                sheet_name = table[:31] if table else "table"
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        created_files.append(str(xlsx_path.relative_to(PROJECT_ROOT)))

    manifest = {
        "backup_time": payload["backup_time"],
        "backup_folder": str(batch_dir.relative_to(PROJECT_ROOT)),
        "database_path": str(DB_PATH.relative_to(PROJECT_ROOT)),
        "table_count": len(tables),
        "tables": {
            table: {
                "row_count": payload["tables"][table]["row_count"],
                "columns": payload["tables"][table]["columns"],
            }
            for table in tables
        },
        "files": created_files,
    }

    manifest_path = batch_dir / "backup_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    created_files.append(str(manifest_path.relative_to(PROJECT_ROOT)))

    LATEST_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    created_files.append(str(LATEST_MANIFEST.relative_to(PROJECT_ROOT)))

    return BackupResult(
        ok=True,
        message=f"永久備份完成，共 {len(tables)} 個資料表。",
        backup_dir=str(batch_dir),
        files=created_files,
    )


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        shell=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(out.strip() or f"git {' '.join(args)} failed")
    return out.strip()


def git_backup_push(commit_message: str | None = None) -> BackupResult:
    """
    將 data/persistent_backups/ 備份檔 commit + push 到 GitHub。
    需先完成：
    - git remote origin 已設定
    - 本機 GitHub 已登入 / token 已授權
    """
    _ensure_dirs()

    if commit_message is None:
        commit_message = f"Backup SPT time tracking data {_now_tag()}"

    outputs: list[str] = []
    try:
        outputs.append(_run_git(["status", "--short"]))
        outputs.append(_run_git(["add", "data/persistent_backups", ".gitignore"]))

        status_after_add = _run_git(["status", "--short"])
        outputs.append(status_after_add)

        if not status_after_add.strip():
            return BackupResult(
                ok=True,
                message="沒有新的備份異動需要上傳。",
                backup_dir=str(BACKUP_DIR),
                files=[],
                git_output="\n".join(x for x in outputs if x),
            )

        outputs.append(_run_git(["commit", "-m", commit_message]))
        outputs.append(_run_git(["push"]))
        return BackupResult(
            ok=True,
            message="備份已 commit 並 push 到 GitHub。",
            backup_dir=str(BACKUP_DIR),
            files=[],
            git_output="\n".join(x for x in outputs if x),
        )
    except Exception as exc:
        return BackupResult(
            ok=False,
            message=f"GitHub 備份上傳失敗：{exc}",
            backup_dir=str(BACKUP_DIR),
            files=[],
            git_output="\n".join(x for x in outputs if x),
        )


def create_backup_and_push_to_github(include_excel: bool = True, include_csv: bool = True) -> BackupResult:
    backup = create_persistent_backup(include_excel=include_excel, include_csv=include_csv)
    if not backup.ok:
        return backup

    git_result = git_backup_push()
    return BackupResult(
        ok=backup.ok and git_result.ok,
        message=f"{backup.message} / {git_result.message}",
        backup_dir=backup.backup_dir,
        files=backup.files,
        git_output=git_result.git_output,
    )


def load_latest_manifest() -> dict[str, Any] | None:
    if not LATEST_MANIFEST.exists():
        return None
    try:
        return json.loads(LATEST_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return None
