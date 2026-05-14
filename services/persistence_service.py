# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.21 - Persistence Service Compatibility Fix

整合 V1.10「資料永久保存與備份」頁面需要的舊函式，與 V1.20「更新前/更新後永久狀態」需要的新函式。
修正：09_09. 資料永久保存與備份.py 匯入 services.persistence_service 時發生 ImportError。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"

# V1.10 backup paths - used by 09 backup page
BACKUP_DIR = PROJECT_ROOT / "data" / "persistent_backups"
LATEST_MANIFEST = BACKUP_DIR / "latest_backup_manifest.json"

# V1.20 permanent state paths - used before/after patch update
STATE_DIR = PROJECT_ROOT / "data" / "persistent_state"
ARCHIVE_DIR = STATE_DIR / "archive"
STATE_JSON = STATE_DIR / "spt_permanent_state.json"
SETTINGS_JSON = STATE_DIR / "spt_module_settings.json"
DB_COPY_DIR = STATE_DIR / "db_copy"

SETTING_TABLE_CANDIDATES = [
    "module_settings",
    "table_column_settings",
    "column_width_settings",
    "table_sort_settings",
    "user_table_settings",
    "page_settings",
    "ui_settings",
    "system_settings",
]


@dataclass
class BackupResult:
    ok: bool
    message: str
    backup_dir: str
    files: list[str]
    git_output: str = ""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _stamp() -> str:
    return _now_tag()


def _ensure_dirs() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    DB_COPY_DIR.mkdir(parents=True, exist_ok=True)
    (BACKUP_DIR / ".gitkeep").write_text("keep this folder for persistent GitHub backups\n", encoding="utf-8")
    (STATE_DIR / ".gitkeep").write_text("", encoding="utf-8")


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"找不到資料庫：{DB_PATH}")
    return connect_db()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_existing_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r["name"] for r in rows if not str(r["name"]).startswith("sqlite_")]


# -----------------------------------------------------------------------------
# V1.10 compatibility functions for 09 backup page
# -----------------------------------------------------------------------------
def list_database_tables() -> list[str]:
    """列出目前 SQLite 內所有使用者資料表。"""
    if not DB_PATH.exists():
        return []
    with connect_db() as conn:
        return get_existing_tables(conn)


def read_table(table_name: str) -> pd.DataFrame:
    """讀取單一資料表。table_name 只允許來自 sqlite_master，避免 SQL injection。"""
    tables = set(list_database_tables())
    if table_name not in tables:
        raise ValueError(f"資料表不存在或不允許讀取：{table_name}")
    with connect_db() as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)


def _safe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    clean = df.copy()
    clean = clean.where(pd.notnull(clean), None)
    return clean.to_dict(orient="records")


def create_persistent_backup(include_excel: bool = True, include_csv: bool = True) -> BackupResult:
    """建立 data/persistent_backups/ 下的 JSON / Excel / CSV 永久備份。"""
    _ensure_dirs()
    if not DB_PATH.exists():
        return BackupResult(False, f"找不到資料庫：{DB_PATH}", str(BACKUP_DIR), [])

    tag = _now_tag()
    batch_dir = BACKUP_DIR / f"backup_{tag}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    tables = list_database_tables()
    payload: dict[str, Any] = {
        "backup_time": _now(),
        "database_path": str(DB_PATH),
        "tables": {},
    }
    created_files: list[str] = []

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
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    created_files.append(str(json_path.relative_to(PROJECT_ROOT)))

    if include_excel:
        xlsx_path = batch_dir / "full_backup.xlsx"
        try:
            with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
                summary = pd.DataFrame([
                    {"資料表 / Table": table, "筆數 / Records": payload["tables"][table]["row_count"]}
                    for table in tables
                ])
                summary.to_excel(writer, sheet_name="備份摘要", index=False)
                for table in tables:
                    df = read_table(table)
                    df.to_excel(writer, sheet_name=(table[:31] or "table"), index=False)
            created_files.append(str(xlsx_path.relative_to(PROJECT_ROOT)))
        except Exception:
            # xlsxwriter/openpyxl abnormal should not block JSON backup
            pass

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

    # Also refresh V1.20 JSON state so both backup systems stay aligned.
    try:
        export_permanent_state(include_logs=True)
    except Exception:
        pass

    return BackupResult(True, f"永久備份完成，共 {len(tables)} 個資料表。", str(batch_dir), created_files)


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=str(PROJECT_ROOT), text=True, capture_output=True, shell=False)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(out.strip() or f"git {' '.join(args)} failed")
    return out.strip()


def git_backup_push(commit_message: str | None = None) -> BackupResult:
    """將 persistent_backups 與 persistent_state 備份檔 commit + push 到 GitHub。"""
    _ensure_dirs()
    if commit_message is None:
        commit_message = f"Backup SPT time tracking data {_now_tag()}"
    outputs: list[str] = []
    try:
        outputs.append(_run_git(["add", "data/persistent_backups", "data/persistent_state", ".gitignore"]))
        status_after_add = _run_git(["status", "--short"])
        outputs.append(status_after_add)
        if not status_after_add.strip():
            return BackupResult(True, "沒有新的備份異動需要上傳。", str(BACKUP_DIR), [], "\n".join(x for x in outputs if x))
        outputs.append(_run_git(["commit", "-m", commit_message]))
        outputs.append(_run_git(["push"]))
        return BackupResult(True, "備份已 commit 並 push 到 GitHub。", str(BACKUP_DIR), [], "\n".join(x for x in outputs if x))
    except Exception as exc:
        return BackupResult(False, f"GitHub 備份上傳失敗：{exc}", str(BACKUP_DIR), [], "\n".join(x for x in outputs if x))


def create_backup_and_push_to_github(include_excel: bool = True, include_csv: bool = True) -> BackupResult:
    backup = create_persistent_backup(include_excel=include_excel, include_csv=include_csv)
    if not backup.ok:
        return backup
    git_result = git_backup_push()
    return BackupResult(
        backup.ok and git_result.ok,
        f"{backup.message} / {git_result.message}",
        backup.backup_dir,
        backup.files,
        git_result.git_output,
    )


def load_latest_manifest() -> dict[str, Any] | None:
    if not LATEST_MANIFEST.exists():
        return None
    try:
        return json.loads(LATEST_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return None


# -----------------------------------------------------------------------------
# V1.20 permanent state export / restore functions
# -----------------------------------------------------------------------------
def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def export_table(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table_name):
        return []
    rows = conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
    return rows_to_dicts(rows)


def export_permanent_state(include_logs: bool = True) -> dict[str, Any]:
    """匯出所有資料表與設定到 data/persistent_state/spt_permanent_state.json。"""
    _ensure_dirs()
    if not DB_PATH.exists():
        state = {"version": "V1.21", "exported_at": _now(), "db_exists": False, "tables": {}}
        STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state

    conn = connect_db()
    try:
        existing = get_existing_tables(conn)
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in existing:
            if not include_logs and table == "system_logs":
                continue
            tables[table] = export_table(conn, table)

        state = {
            "version": "V1.21",
            "exported_at": _now(),
            "db_path": str(DB_PATH),
            "db_exists": True,
            "tables": tables,
        }
        if STATE_JSON.exists():
            shutil.copy2(STATE_JSON, ARCHIVE_DIR / f"spt_permanent_state_{_stamp()}.json")
        STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        settings_tables: dict[str, list[dict[str, Any]]] = {}
        for table in SETTING_TABLE_CANDIDATES:
            if table_exists(conn, table):
                settings_tables[table] = export_table(conn, table)
        SETTINGS_JSON.write_text(
            json.dumps({"version": "V1.21", "exported_at": _now(), "tables": settings_tables}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if DB_PATH.exists():
            shutil.copy2(DB_PATH, DB_COPY_DIR / "spt_time_tracking_latest.db")
            shutil.copy2(DB_PATH, DB_COPY_DIR / f"spt_time_tracking_{_stamp()}.db")
        return state
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [r["name"] for r in rows]


def _insert_rows(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, Any]], mode: str = "replace") -> int:
    if not rows or not table_exists(conn, table_name):
        return 0
    columns = _table_columns(conn, table_name)
    valid_rows = []
    for row in rows:
        filtered = {k: v for k, v in row.items() if k in columns}
        if filtered:
            valid_rows.append(filtered)
    if not valid_rows:
        return 0
    if mode == "replace":
        conn.execute(f'DELETE FROM "{table_name}"')
    count = 0
    for row in valid_rows:
        keys = list(row.keys())
        placeholders = ",".join(["?"] * len(keys))
        col_sql = ",".join([f'"{k}"' for k in keys])
        sql = f'INSERT OR REPLACE INTO "{table_name}" ({col_sql}) VALUES ({placeholders})'
        conn.execute(sql, [row[k] for k in keys])
        count += 1
    return count


def restore_permanent_state(json_path: str | Path | None = None, mode: str = "replace") -> dict[str, Any]:
    """從 JSON 還原資料。mode='replace' 會先清空表再匯入。"""
    _ensure_dirs()
    target = Path(json_path) if json_path else STATE_JSON
    if not target.exists():
        return {"ok": False, "message": f"找不到永久保存檔：{target}"}
    state = json.loads(target.read_text(encoding="utf-8"))
    tables = state.get("tables", {})
    if not isinstance(tables, dict):
        return {"ok": False, "message": "永久保存檔格式錯誤：tables 不存在"}
    conn = connect_db()
    restored: dict[str, int] = {}
    try:
        for table_name, rows in tables.items():
            if isinstance(rows, list) and table_exists(conn, table_name):
                restored[table_name] = _insert_rows(conn, table_name, rows, mode=mode)
        conn.commit()
        return {"ok": True, "restored": restored, "source": str(target)}
    finally:
        conn.close()


def write_gitkeep() -> None:
    _ensure_dirs()


if __name__ == "__main__":
    result = export_permanent_state(include_logs=True)
    print("Permanent state exported:", STATE_JSON)
    print("Tables:", ", ".join(result.get("tables", {}).keys()))
