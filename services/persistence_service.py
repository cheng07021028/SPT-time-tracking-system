# -*- coding: utf-8 -*-
"""
SPT Time Tracking V1.30 - Persistent Data Guard Service

目的：
1. 將所有資料表與模組設定永久保存到 JSON，避免更新 patch 後資料消失。
2. DB 空白時可從 GitHub latest JSON 或本機永久檔還原。
3. 嚴格防止空 DB 覆蓋有資料的永久檔。
4. 相容舊版 09 備份頁函式。
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

from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"

BACKUP_DIR = PROJECT_ROOT / "data" / "persistent_backups"
LATEST_MANIFEST = BACKUP_DIR / "latest_backup_manifest.json"

STATE_DIR = PROJECT_ROOT / "data" / "permanent_store" / "persistent_state"
ARCHIVE_DIR = STATE_DIR / "archive"
HISTORY_DIR = STATE_DIR / "history"
STATE_JSON = STATE_DIR / "spt_permanent_state.json"
SETTINGS_JSON = STATE_DIR / "spt_module_settings.json"
AUDIT_JSON = STATE_DIR / "spt_audit_log_state.json"
AUDIT_HISTORY_DIR = STATE_DIR / "audit_history"
DB_COPY_DIR = STATE_DIR / "db_copy"
LOCK_FILE = STATE_DIR / ".restore_lock"

BUSINESS_TABLES = ["work_orders", "employees", "time_records"]
SETTING_TABLE_CANDIDATES = [
    "module_settings",
    "table_column_settings",
    "column_width_settings",
    "table_sort_settings",
    "user_table_settings",
    "page_settings",
    "ui_settings",
    "system_settings",
    "rest_periods",
    "process_options",
    "app_settings",
    "auth_users",
    "auth_account_permissions",
    "auth_security_settings",
]


@dataclass
class BackupResult:
    ok: bool
    message: str
    backup_dir: str
    files: list[str]
    git_output: str = ""


def _now() -> str:
    return now_text()


def _stamp() -> str:
    return now_stamp()


def _ensure_dirs() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    DB_COPY_DIR.mkdir(parents=True, exist_ok=True)
    (BACKUP_DIR / ".gitkeep").write_text("keep this folder for persistent GitHub backups\n", encoding="utf-8")
    (STATE_DIR / ".gitkeep").write_text("", encoding="utf-8")
    (HISTORY_DIR / ".gitkeep").write_text("", encoding="utf-8")
    (AUDIT_HISTORY_DIR / ".gitkeep").write_text("", encoding="utf-8")


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return row is not None


def get_existing_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r["name"] for r in rows if not str(r["name"]).startswith("sqlite_")]


def _count_table(conn: sqlite3.Connection, table_name: str) -> int:
    if not table_exists(conn, table_name):
        return 0
    try:
        return int(conn.execute(f'SELECT COUNT(*) AS c FROM "{table_name}"').fetchone()["c"])
    except Exception:
        return 0


def database_business_row_count(conn: sqlite3.Connection | None = None) -> int:
    close = False
    if conn is None:
        if not DB_PATH.exists():
            return 0
        conn = connect_db()
        close = True
    try:
        return sum(_count_table(conn, t) for t in BUSINESS_TABLES)
    finally:
        if close:
            conn.close()


def _state_business_row_count(state: dict[str, Any]) -> int:
    tables = state.get("tables", {})
    if not isinstance(tables, dict):
        return 0
    total = 0
    for table in BUSINESS_TABLES:
        rows = tables.get(table, [])
        if isinstance(rows, list):
            total += len(rows)
        elif isinstance(rows, dict) and isinstance(rows.get("records"), list):
            total += len(rows["records"])
    return total


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalise_backup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """支援 latest state 格式，也支援 full_backup.json 格式。"""
    if "tables" not in payload or not isinstance(payload["tables"], dict):
        return {"tables": {}}
    tables: dict[str, list[dict[str, Any]]] = {}
    for table, value in payload["tables"].items():
        if isinstance(value, list):
            tables[table] = value
        elif isinstance(value, dict) and isinstance(value.get("records"), list):
            tables[table] = value["records"]
    return {"tables": tables}


def _latest_backup_json_candidates() -> list[Path]:
    candidates: list[Path] = []
    if STATE_JSON.exists():
        candidates.append(STATE_JSON)
    if LATEST_MANIFEST.exists():
        manifest = _load_json(LATEST_MANIFEST) or {}
        folder = manifest.get("backup_folder")
        if folder:
            p = PROJECT_ROOT / folder / "full_backup.json"
            if p.exists():
                candidates.append(p)
    for folder in [HISTORY_DIR, ARCHIVE_DIR]:
        if folder.exists():
            for p in sorted(folder.glob("spt_permanent_state_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                if p not in candidates:
                    candidates.append(p)
    if BACKUP_DIR.exists():
        for p in sorted(BACKUP_DIR.glob("backup_*/full_backup.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            if p not in candidates:
                candidates.append(p)
    return candidates


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def export_table(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table_name):
        return []
    rows = conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
    return rows_to_dicts(rows)


def export_permanent_state(include_logs: bool = True, force: bool = False) -> dict[str, Any]:
    """匯出所有資料表與設定。

    安全規則：
    - force=False 時，若目前 DB 主資料為 0，不會覆蓋既有永久檔。
    - 若本機無永久檔且 DB 主資料為 0，也不建立空 latest，避免上傳空檔覆蓋 GitHub。
    """
    _ensure_dirs()
    old_state = _load_json(STATE_JSON) or {}
    old_count = _state_business_row_count(_normalise_backup_payload(old_state))

    if not DB_PATH.exists():
        return {
            "version": "V1.30",
            "exported_at": _now(),
            "skipped": True,
            "reason": "DB not found; export skipped to protect cloud data",
            "previous_business_row_count": old_count,
        }

    conn = connect_db()
    try:
        current_count = database_business_row_count(conn)
        if current_count == 0 and not force:
            return {
                "version": "V1.30",
                "exported_at": _now(),
                "skipped": True,
                "reason": "Current DB has zero business rows; export skipped to protect permanent state",
                "previous_business_row_count": old_count,
                "business_row_count": current_count,
            }

        existing = get_existing_tables(conn)
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in existing:
            if not include_logs and table in {"system_logs", "auth_login_logs"}:
                continue
            tables[table] = export_table(conn, table)

        # V3.02: if time_records is empty but a non-empty time-record backup exists,
        # do not publish a new permanent state that would make 01/02 look empty.
        try:
            from services.time_records_guard_service import should_block_empty_time_record_export
            if len(tables.get("time_records", [])) == 0 and should_block_empty_time_record_export("01_time_records") and not force:
                return {
                    "version": "V3.02",
                    "exported_at": _now(),
                    "skipped": True,
                    "reason": "Blocked permanent export: time_records is empty but non-empty backups exist.",
                    "previous_business_row_count": old_count,
                    "business_row_count": current_count,
                }
        except Exception:
            pass

        state = {
            "version": "V1.30",
            "exported_at": _now(),
            "db_path": str(DB_PATH),
            "db_exists": True,
            "business_row_count": current_count,
            "table_counts": {t: len(rows) for t, rows in tables.items()},
            "tables": tables,
        }

        if STATE_JSON.exists() and old_state:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            archive_name = f"spt_permanent_state_{_stamp()}.json"
            shutil.copy2(STATE_JSON, ARCHIVE_DIR / archive_name)
            shutil.copy2(STATE_JSON, HISTORY_DIR / archive_name)
        STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        settings_tables: dict[str, list[dict[str, Any]]] = {}
        for table in SETTING_TABLE_CANDIDATES:
            if table_exists(conn, table):
                settings_tables[table] = export_table(conn, table)
        settings_state = {
            "version": "V1.30",
            "exported_at": _now(),
            "tables": settings_tables,
            "table_counts": {t: len(rows) for t, rows in settings_tables.items()},
        }
        SETTINGS_JSON.write_text(json.dumps(settings_state, ensure_ascii=False, indent=2), encoding="utf-8")

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
        conn.execute(f'INSERT OR REPLACE INTO "{table_name}" ({col_sql}) VALUES ({placeholders})', [row[k] for k in keys])
        count += 1
    return count


def restore_permanent_state(json_path: str | Path | None = None, mode: str = "replace") -> dict[str, Any]:
    _ensure_dirs()
    target = Path(json_path) if json_path else STATE_JSON
    if not target.exists():
        return {"ok": False, "message": f"找不到永久保存檔：{target}"}
    payload = _normalise_backup_payload(_load_json(target) or {})
    tables = payload.get("tables", {})
    if not isinstance(tables, dict) or not tables:
        return {"ok": False, "message": f"永久保存檔無資料：{target}"}

    # 確保 schema 先存在。
    try:
        from services.db_service import ensure_database
        ensure_database()
    except Exception:
        pass

    conn = connect_db()
    restored: dict[str, int] = {}
    try:
        # 先還原主資料，再還原設定/權限/LOG，避免 FK 或關聯順序問題。
        ordered = [*BUSINESS_TABLES]
        ordered += [t for t in tables.keys() if t not in ordered]
        for table_name in ordered:
            rows = tables.get(table_name, [])
            if isinstance(rows, list) and table_exists(conn, table_name):
                restored[table_name] = _insert_rows(conn, table_name, rows, mode=mode)
        conn.commit()
        return {"ok": True, "restored": restored, "source": str(target), "business_row_count": sum(restored.get(t, 0) for t in BUSINESS_TABLES)}
    finally:
        conn.close()


def restore_latest_available_state(mode: str = "replace") -> dict[str, Any]:
    candidates = _latest_backup_json_candidates()
    if not candidates:
        return {"ok": False, "message": "找不到任何永久保存檔或備份檔。"}
    last_error = ""
    for p in candidates:
        payload = _normalise_backup_payload(_load_json(p) or {})
        if _state_business_row_count(payload) <= 0:
            continue
        result = restore_permanent_state(p, mode=mode)
        if result.get("ok"):
            return result
        last_error = str(result)
    return {"ok": False, "message": f"找到備份檔，但沒有可還原主資料。{last_error}"}


def auto_restore_if_database_empty(force: bool = False) -> dict[str, Any]:
    """資料表存在但主資料為 0 時，自動從 JSON 備份還原。"""
    _ensure_dirs()
    if LOCK_FILE.exists() and not force:
        return {"ok": False, "skipped": True, "message": "restore lock exists"}
    try:
        LOCK_FILE.write_text(_now(), encoding="utf-8")
        if not DB_PATH.exists():
            return restore_latest_available_state(mode="replace")
        with connect_db() as conn:
            current_count = database_business_row_count(conn)
        if current_count > 0 and not force:
            return {"ok": True, "skipped": True, "message": f"資料庫已有主資料：{current_count} 筆，不需還原。"}
        return restore_latest_available_state(mode="replace")
    finally:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def safe_export_after_write() -> dict[str, Any]:
    """寫入 DB 後自動刷新永久 JSON；若 DB 是空的則不覆蓋舊 JSON。"""
    try:
        return export_permanent_state(include_logs=True, force=False)
    except Exception as exc:
        return {"ok": False, "message": str(exc)}



# -----------------------------------------------------------------------------
# V1.37 audit/login-log permanent state
# -----------------------------------------------------------------------------
AUDIT_TABLES = ["auth_login_logs", "system_logs"]


def export_audit_state(force: bool = True) -> dict[str, Any]:
    """Export login/security logs to a dedicated permanent JSON.

    This file is independent from business data. It prevents login logs from
    disappearing after Streamlit Cloud redeploys, while avoiding full GitHub
    backup on every login.
    """
    _ensure_dirs()
    state: dict[str, Any] = {
        "version": "V1.37",
        "exported_at": _now(),
        "description": "SPT login/system audit logs permanent state",
        "tables": {},
        "table_counts": {},
    }
    if not DB_PATH.exists():
        state["warning"] = f"SQLite database not found: {DB_PATH}"
        AUDIT_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state
    conn = connect_db()
    try:
        for table in AUDIT_TABLES:
            if table_exists(conn, table):
                rows = export_table(conn, table)
                state["tables"][table] = rows
                state["table_counts"][table] = len(rows)
        AUDIT_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        hist = AUDIT_HISTORY_DIR / f"spt_audit_log_state_{_stamp()}.json"
        hist.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        state["latest_audit"] = str(AUDIT_JSON)
        state["history_audit"] = str(hist)
        return state
    finally:
        conn.close()


def restore_audit_state(json_path: str | Path | None = None, mode: str = "append") -> dict[str, Any]:
    """Restore login/security logs from dedicated audit JSON.

    Default mode is append to avoid deleting current session logs. Duplicate IDs
    are ignored/replaced by SQLite if the primary key exists.
    """
    _ensure_dirs()
    target = Path(json_path) if json_path else AUDIT_JSON
    if not target.exists():
        return {"ok": False, "message": f"找不到登入紀錄永久檔：{target}"}
    payload = _load_json(target) or {}
    tables = payload.get("tables", {})
    if not isinstance(tables, dict):
        return {"ok": False, "message": "登入紀錄永久檔格式不正確。"}
    try:
        from services.permission_service import init_permission_tables
        init_permission_tables()
    except Exception:
        pass
    conn = connect_db()
    restored: dict[str, int] = {}
    try:
        for table_name in AUDIT_TABLES:
            rows = tables.get(table_name, [])
            if isinstance(rows, list) and table_exists(conn, table_name):
                restored[table_name] = _insert_rows(conn, table_name, rows, mode="replace" if mode == "replace" else "append")
        conn.commit()
        return {"ok": True, "restored": restored, "source": str(target)}
    finally:
        conn.close()


def safe_export_audit_after_write() -> dict[str, Any]:
    try:
        return export_audit_state(force=True)
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def audit_state_status() -> dict[str, Any]:
    payload = _load_json(AUDIT_JSON) or {}
    return {
        "exists": AUDIT_JSON.exists(),
        "path": str(AUDIT_JSON),
        "table_counts": payload.get("table_counts", {}),
        "exported_at": payload.get("exported_at", ""),
    }

# -----------------------------------------------------------------------------
# V1.10 compatibility functions for 09 backup page
# -----------------------------------------------------------------------------
def list_database_tables() -> list[str]:
    if not DB_PATH.exists():
        return []
    with connect_db() as conn:
        return get_existing_tables(conn)


def read_table(table_name: str) -> pd.DataFrame:
    tables = set(list_database_tables())
    if table_name not in tables:
        raise ValueError(f"資料表不存在或不允許讀取：{table_name}")
    with connect_db() as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)


def _safe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    clean = df.copy().where(pd.notnull(df), None)
    return clean.to_dict(orient="records")


def create_persistent_backup(include_excel: bool = True, include_csv: bool = True) -> BackupResult:
    _ensure_dirs()
    if not DB_PATH.exists():
        return BackupResult(False, f"找不到資料庫：{DB_PATH}", str(BACKUP_DIR), [])

    tag = _stamp()
    batch_dir = BACKUP_DIR / f"backup_{tag}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    tables = list_database_tables()
    payload: dict[str, Any] = {"backup_time": _now(), "database_path": str(DB_PATH), "tables": {}}
    created_files: list[str] = []

    for table in tables:
        df = read_table(table)
        payload["tables"][table] = {"row_count": int(len(df)), "columns": list(df.columns), "records": _safe_records(df)}
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
                pd.DataFrame([{"資料表 / Table": t, "筆數 / Records": payload["tables"][t]["row_count"]} for t in tables]).to_excel(writer, sheet_name="備份摘要", index=False)
                for table in tables:
                    read_table(table).to_excel(writer, sheet_name=(table[:31] or "table"), index=False)
            created_files.append(str(xlsx_path.relative_to(PROJECT_ROOT)))
        except Exception:
            pass

    manifest = {
        "backup_time": payload["backup_time"],
        "backup_folder": str(batch_dir.relative_to(PROJECT_ROOT)),
        "database_path": str(DB_PATH.relative_to(PROJECT_ROOT)),
        "table_count": len(tables),
        "tables": {t: {"row_count": payload["tables"][t]["row_count"], "columns": payload["tables"][t]["columns"]} for t in tables},
        "files": created_files,
    }
    manifest_path = batch_dir / "backup_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    created_files.append(str(manifest_path.relative_to(PROJECT_ROOT)))
    LATEST_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    created_files.append(str(LATEST_MANIFEST.relative_to(PROJECT_ROOT)))
    export_permanent_state(include_logs=True, force=False)
    export_audit_state(force=True)
    return BackupResult(True, f"永久備份完成，共 {len(tables)} 個資料表。", str(batch_dir), created_files)


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=str(PROJECT_ROOT), text=True, capture_output=True, shell=False)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(out.strip() or f"git {' '.join(args)} failed")
    return out.strip()


def git_backup_push(commit_message: str | None = None) -> BackupResult:
    _ensure_dirs()
    if commit_message is None:
        commit_message = f"Backup SPT time tracking data {_stamp()}"
    outputs: list[str] = []
    try:
        outputs.append(_run_git(["config", "user.name", "SPT Time Tracking Bot"]))
        outputs.append(_run_git(["config", "user.email", "spt-time-tracking-bot@users.noreply.github.com"]))
        outputs.append(_run_git(["add", "data/persistent_backups", "data/permanent_store/persistent_state", ".gitignore"]))
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
    return BackupResult(backup.ok and git_result.ok, f"{backup.message} / {git_result.message}", backup.backup_dir, backup.files, git_result.git_output)


def load_latest_manifest() -> dict[str, Any] | None:
    return _load_json(LATEST_MANIFEST)


def write_gitkeep() -> None:
    _ensure_dirs()


if __name__ == "__main__":
    print(export_permanent_state(include_logs=True))
