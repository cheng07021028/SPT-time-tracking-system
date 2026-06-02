# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    ("01", "工時紀錄", "pages/01_01. 工時紀錄.py"),
    ("02", "歷史紀錄", "pages/02_02. 歷史紀錄.py"),
    ("03", "製令管理", "pages/03_03. 製令管理.py"),
    ("04", "人員名單", "pages/04_04. 人員名單.py"),
    ("05", "製令工時分析", "pages/05_05. 製令工時分析.py"),
    ("06", "LOG查詢", "pages/06_06. LOG查詢.py"),
    ("07", "今日未紀錄名單", "pages/07_07. 今日未紀錄名單.py"),
    ("08", "人員每日工時", "pages/08_08. 人員每日工時.py"),
    ("09", "資料永久保存與備份", "pages/09_09. 資料永久保存與備份.py"),
    ("10", "權限管理", "pages/10_10. 權限管理.py"),
    ("11", "登入紀錄", "pages/11_11. 登入紀錄.py"),
    ("12", "模組永久紀錄中心", "pages/12_12. 模組永久紀錄中心.py"),
    ("13", "系統設定", "pages/13_13. 系統設定.py"),
    ("14", "資料健康檢查中心", "pages/14_14. 資料健康檢查中心.py"),
    ("15", "舊資料匯入到Neon", "pages/15_15. 舊資料匯入到Neon.py"),
    ("98", "權威檔診斷", "pages/98_98. 權威檔診斷.py"),
    ("99", "效能診斷", "pages/99_99. 效能診斷.py"),
]

HIGH_RISK_PATTERNS = [
    ("local_json_write", re.compile(r"json\.dump|write_text\(|\.open\(\s*['\"]a|to_json\(")),
    ("direct_sqlite", re.compile(r"\bsqlite3\b|sqlite_sequence|DB_PATH")),
    ("github_realtime", re.compile(r"GITHUB_TOKEN|upload_.*github|download_.*github|github=True")),
    ("local_authority_path", re.compile(r"data/permanent_store|persistent_state|persistent_modules|modules/")),
]

ALLOWED_SERVICE_FILES = {
    "services/db_service.py",
    "services/neon_authority_service.py",
    "services/permanent_store.py",
    "services/module_persistence_service.py",
    "services/column_settings_service.py",
    "services/analysis_filter_service.py",
    "services/settings_durability_service.py",
    "services/backup_restore_service.py",
    "services/neon_performance_audit_service.py",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _risk_count(rel_path: str) -> dict[str, int]:
    text = _read(PROJECT_ROOT / rel_path)
    out = {}
    for name, pat in HIGH_RISK_PATTERNS:
        out[name] = len(pat.findall(text))
    return out


def module_architecture_audit() -> dict[str, Any]:
    try:
        from services.db_service import get_database_backend, is_postgres_enabled, audit_v32_neon_performance_authority
        backend = get_database_backend()
        pg = bool(is_postgres_enabled())
        db_audit = audit_v32_neon_performance_authority()
    except Exception as exc:
        backend = "unknown"
        pg = False
        db_audit = {"ok": False, "error": str(exc)[:300]}
    rows = []
    for code, name, rel in MODULES:
        risk = _risk_count(rel)
        # Page-level session_state is UI state and allowed. Local file writes in pages are a warning.
        warnings = sum(risk.values())
        status = "OK" if pg else "NO_DATABASE_URL"
        if warnings and code not in {"09", "14", "15", "98", "99"}:
            status = "CHECK_REQUIRED"
        if code == "07" and "neon_07_daily_attendance_v32" in _read(PROJECT_ROOT / rel):
            status = "OK"
        rows.append({
            "模組": code,
            "名稱": name,
            "狀態": status,
            "資料權威": "Neon/PostgreSQL" if pg else "SQLite fallback",
            "local_json_write": risk.get("local_json_write", 0),
            "direct_sqlite": risk.get("direct_sqlite", 0),
            "github_realtime": risk.get("github_realtime", 0),
            "local_authority_path": risk.get("local_authority_path", 0),
            "說明": "頁面仍可能含舊相容字樣；正式讀寫需以 service/db_service/neon_authority_service 為準。",
        })
    return {"backend": backend, "postgres_enabled": pg, "db_audit": db_audit, "modules": rows}


def _time_call(name: str, fn) -> dict[str, Any]:
    start = time.perf_counter()
    ok = True
    error = ""
    try:
        result = fn()
    except Exception as exc:
        ok = False
        error = str(exc)[:300]
        result = None
    elapsed = round(time.perf_counter() - start, 4)
    return {"動作": name, "秒數": elapsed, "狀態": "OK" if ok and elapsed <= 3 else ("SLOW" if ok else "ERROR"), "錯誤": error, "結果摘要": str(result)[:160]}


def performance_probe() -> dict[str, Any]:
    from services.db_service import query_one, query_df, ensure_database, get_database_backend
    ensure_database()
    checks = [
        _time_call("db.ensure_database", lambda: ensure_database() or "schema ok"),
        _time_call("01 今日工時查詢", lambda: query_df("SELECT id, employee_id, employee_name, work_order, process_name, status, start_date, start_time FROM time_records WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 100").shape),
        _time_call("02 歷史工時計數", lambda: query_one("SELECT COUNT(*) AS c FROM time_records WHERE deleted_at IS NULL")),
        _time_call("03 製令清單", lambda: query_df("SELECT id, work_order, work_order_no, part_no, type_name FROM work_orders WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 200").shape),
        _time_call("04 人員清單", lambda: query_df("SELECT id, employee_id, employee_name, department, title FROM employees WHERE deleted_at IS NULL ORDER BY employee_id LIMIT 200").shape),
        _time_call("06 LOG 最近資料", lambda: query_df("SELECT id, log_time, user_name, action_type FROM system_logs WHERE deleted_at IS NULL ORDER BY log_time DESC, id DESC LIMIT 200").shape),
        _time_call("10 權限筆數", lambda: query_one("SELECT COUNT(*) AS c FROM auth_account_permissions")),
        _time_call("11 登入紀錄", lambda: query_df("SELECT id, username, event_time, result FROM auth_login_logs WHERE deleted_at IS NULL ORDER BY event_time DESC, id DESC LIMIT 100").shape),
        _time_call("13 工段設定", lambda: query_df("SELECT id, process_name, is_active, sort_order FROM process_options ORDER BY sort_order, id LIMIT 200").shape),
    ]
    return {"backend": get_database_backend(), "target_seconds": 3, "checks": checks, "ok": all(x["狀態"] == "OK" for x in checks)}


def dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows or [])
