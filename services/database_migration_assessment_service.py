# -*- coding: utf-8 -*-
"""V190 PostgreSQL / SQL Server migration readiness assessment.

Read-only assessment only.  It does not connect to external databases and does
not alter production write paths.
"""
from __future__ import annotations

import io
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from services.db_service import get_connection, query_df, query_one, DB_PATH
except Exception:  # pragma: no cover
    get_connection = None  # type: ignore
    query_df = None  # type: ignore
    query_one = None  # type: ignore
    DB_PATH = None  # type: ignore

try:
    from services.timezone_service import now_text
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CORE_TABLES = [
    "time_records", "system_logs", "employees", "work_orders", "login_logs",
    "auth_users", "auth_account_permissions", "security_users", "security_module_permissions",
    "system_settings", "process_options", "rest_periods",
]

JSON_AUTHORITY_HINTS = [
    "data/permanent_store",
    "data/persistent_state",
    "data/persistent_modules",
]


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default


def _table_exists(name: str) -> bool:
    if query_one is None:
        return False
    try:
        return bool(query_one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))
    except Exception:
        return False


def _row_count(name: str) -> int:
    if query_one is None or not _table_exists(name):
        return 0
    try:
        row = query_one(f"SELECT COUNT(*) AS n FROM {name}") or {}
        return _safe_int(row.get("n"), 0)
    except Exception:
        return 0


def _schema_rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if get_connection is None:
        return out
    try:
        with get_connection() as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            for t in tables:
                try:
                    table = str(t[0])
                except Exception:
                    table = str(t["name"])
                if table.startswith("sqlite_"):
                    continue
                cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
                idxs = conn.execute(f"PRAGMA index_list({table})").fetchall()
                out.append({
                    "table": table,
                    "row_count": _row_count(table),
                    "column_count": len(cols),
                    "index_count": len(idxs),
                    "core_table": table in CORE_TABLES,
                })
    except Exception as exc:
        out.append({"table": "<schema_error>", "error": str(exc), "row_count": 0, "column_count": 0, "index_count": 0, "core_table": False})
    return out


def _json_authority_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in JSON_AUTHORITY_HINTS:
        root = PROJECT_ROOT / rel
        if not root.exists():
            rows.append({"path": rel, "exists": False, "json_files": 0, "size_bytes": 0})
            continue
        files = list(root.rglob("*.json"))
        rows.append({
            "path": rel,
            "exists": True,
            "json_files": len(files),
            "size_bytes": sum(int(f.stat().st_size) for f in files if f.exists()),
        })
    return rows


def collect_v190_database_migration_assessment() -> dict[str, Any]:
    started = time.perf_counter()
    schema = _schema_rows()
    json_rows = _json_authority_rows()
    critical_tables = ["time_records", "system_logs", "employees", "work_orders"]
    missing = [t for t in critical_tables if not _table_exists(t)]
    total_rows = sum(_safe_int(r.get("row_count"), 0) for r in schema)
    sqlite_db_size = 0
    try:
        if DB_PATH and Path(DB_PATH).exists():
            sqlite_db_size = int(Path(DB_PATH).stat().st_size)
    except Exception:
        sqlite_db_size = 0

    migration_steps = [
        {"step": 1, "phase": "Repository abstraction", "status": "partial", "note": "V164/V165 已建立 repository/readiness 概念，仍需把 01/02/06 寫入全部導向 repository interface。"},
        {"step": 2, "phase": "Schema freeze", "status": "needed", "note": "先凍結 time_records/system_logs/employees/work_orders 欄位，建立 PostgreSQL/SQL Server DDL。"},
        {"step": 3, "phase": "Dual-write shadow mode", "status": "recommended", "note": "先 SQLite 正式寫入，同步影子寫入外部 DB，14 顯示差異，不立即切正式。"},
        {"step": 4, "phase": "Read shadow compare", "status": "recommended", "note": "同一查詢同時比對 SQLite 與外部 DB row count/hash。"},
        {"step": 5, "phase": "Cutover", "status": "future", "note": "連續穩定後才把正式讀寫切到 PostgreSQL/SQL Server；GitHub 保留備份用途。"},
    ]
    backend_recommendations = [
        {"backend": "PostgreSQL", "fit": "recommended", "reason": "適合 Streamlit Cloud / 多人同時寫入 / JSONB 稽核欄位 / 雲端部署。"},
        {"backend": "SQL Server", "fit": "recommended_if_company_it", "reason": "公司內網 Windows/AD/既有 IT 管理若以 Microsoft 為主，SQL Server 更容易納管。"},
        {"backend": "SQLite", "fit": "current_limit", "reason": "適合單機或低併發；50 人同時操作時容易遇到鎖等待與本機檔案生命週期問題。"},
    ]
    risk_rows = []
    if missing:
        risk_rows.append({"severity": "HIGH", "risk": "核心資料表缺失", "detail": ", ".join(missing)})
    if total_rows > 50000:
        risk_rows.append({"severity": "MEDIUM", "risk": "資料量增加", "detail": "建議優先做 SQL 分頁與外部 DB 影子寫入。"})
    if sqlite_db_size > 100 * 1024 * 1024:
        risk_rows.append({"severity": "MEDIUM", "risk": "SQLite DB 檔案偏大", "detail": f"目前約 {sqlite_db_size / 1024 / 1024:.1f} MB。"})
    if not risk_rows:
        risk_rows.append({"severity": "INFO", "risk": "未發現阻斷性風險", "detail": "可先做外部 DB schema 與 shadow mode，不建議直接 cutover。"})

    return {
        "ok": True,
        "version": "V190",
        "generated_at": now_text(),
        "production_write_path_changed": False,
        "external_database_enabled": False,
        "safe_to_switch_live_database_now": False,
        "sqlite_db_path": str(DB_PATH or ""),
        "sqlite_db_size_bytes": sqlite_db_size,
        "schema_rows": schema,
        "json_authority_rows": json_rows,
        "migration_steps": migration_steps,
        "backend_recommendations": backend_recommendations,
        "risk_rows": risk_rows,
        "summary": {
            "sqlite_table_count": len(schema),
            "sqlite_total_rows": total_rows,
            "missing_core_tables": missing,
            "recommended_next_version": "V191 dual-write shadow mode 設計，但先不切正式 DB。",
        },
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }


def export_v190_assessment_excel_bytes(report: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame([report.get("summary", {}) | {
            "version": report.get("version"),
            "generated_at": report.get("generated_at"),
            "production_write_path_changed": report.get("production_write_path_changed"),
            "external_database_enabled": report.get("external_database_enabled"),
            "safe_to_switch_live_database_now": report.get("safe_to_switch_live_database_now"),
            "sqlite_db_size_bytes": report.get("sqlite_db_size_bytes"),
        }]).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(report.get("schema_rows", [])).to_excel(writer, sheet_name="SQLiteSchema", index=False)
        pd.DataFrame(report.get("json_authority_rows", [])).to_excel(writer, sheet_name="JsonAuthority", index=False)
        pd.DataFrame(report.get("migration_steps", [])).to_excel(writer, sheet_name="MigrationSteps", index=False)
        pd.DataFrame(report.get("backend_recommendations", [])).to_excel(writer, sheet_name="BackendOptions", index=False)
        pd.DataFrame(report.get("risk_rows", [])).to_excel(writer, sheet_name="Risks", index=False)
    output.seek(0)
    return output.getvalue()
