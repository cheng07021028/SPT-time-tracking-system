# -*- coding: utf-8 -*-
"""V182-V188 consolidated data consistency and operations audit service.

Purpose:
- Read-only diagnostics first. No production writes in this service.
- Compare 01_time_records / 02_history / SQLite / tombstone / LOGRECOVERY.
- Classify duplicate time records and error logs.
- Provide Excel export for managers before destructive cleanup.

This module intentionally avoids CSS/UI/theme changes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

SERVICE_VERSION = "V182_CONSOLIDATED_AUDIT_DIRECT_OVERWRITE"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "permanent_store"
DB_PATH = DATA_ROOT / "database" / "spt_time_tracking.db"

AUTH_01 = DATA_ROOT / "modules" / "01_time_records" / "records.json"
AUTH_02 = DATA_ROOT / "modules" / "02_history" / "records.json"
AUTH_06 = DATA_ROOT / "modules" / "06_logs" / "records.json"
PERSIST_01 = DATA_ROOT / "persistent_modules" / "01_time_records" / "01_time_records_records.json"
PERSIST_02 = DATA_ROOT / "persistent_modules" / "02_history" / "02_history_records.json"
PERSIST_06 = DATA_ROOT / "persistent_modules" / "06_logs" / "06_logs_records.json"

SETTINGS_01_CANDIDATES = [
    DATA_ROOT / "modules" / "01_time_records" / "settings.json",
    DATA_ROOT / "persistent_modules" / "01_time_records" / "01_time_records_settings.json",
]
SETTINGS_02_CANDIDATES = [
    DATA_ROOT / "modules" / "02_history" / "settings.json",
    DATA_ROOT / "persistent_modules" / "02_history" / "02_history_settings.json",
]

RECORD_KEY_COLS = ["record_key", "Record Key", "主鍵", "紀錄主鍵", "key"]
ID_COLS = ["id", "ID", "Id", "record_id", "target_id", "Target ID"]
EMP_ID_COLS = ["employee_id", "工號", "工號 / Employee ID", "Employee ID"]
EMP_NAME_COLS = ["employee_name", "姓名", "姓名 / Name", "Name"]
WO_COLS = ["work_order", "製令", "製令 / Work Order", "Work Order"]
PROC_COLS = ["process_name", "process", "工段", "製程", "工段 / Process", "Process"]
START_COLS = ["start_timestamp", "開始時間", "開始時間 / Start Time", "start_time", "Start Time"]
END_COLS = ["end_timestamp", "結束時間", "結束時間 / End Time", "end_time", "End Time"]
STATUS_COLS = ["status", "狀態", "狀態 / Status", "Status"]
SOURCE_COLS = ["source", "來源", "Source"]
ACTION_COLS = ["action", "動作", "Action", "operation", "event_type"]
LEVEL_COLS = ["level", "層級", "Level", "severity"]
DETAIL_COLS = ["detail", "內容", "Detail", "message", "SQL", "sql"]
LOG_TIME_COLS = ["log_time", "timestamp", "時間", "created_at", "updated_at"]

TERMINAL_STATUS_HINTS = ["下班", "暫停", "完工", "已結束", "補登結束", "closed", "finish", "end"]
ACTIVE_STATUS_HINTS = ["作業中", "開始", "running", "active", "start"]
RECOVERY_HINTS = ["LOGRECOVERY", "V164B_LOG_ONLY_RECOVERY", "LOG_ONLY_RECOVERY"]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    return str(v).strip()


def _safe_int(v: Any) -> Optional[int]:
    try:
        s = _to_str(v)
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


def _first_value(row: Dict[str, Any], names: Sequence[str]) -> str:
    for name in names:
        if name in row and _to_str(row.get(name)):
            return _to_str(row.get(name))
    lowered = {str(k).strip().lower(): k for k in row.keys()}
    for name in names:
        k = lowered.get(name.lower())
        if k is not None and _to_str(row.get(k)):
            return _to_str(row.get(k))
    return ""


def _record_id(row: Dict[str, Any]) -> Optional[int]:
    for col in ID_COLS:
        if col in row:
            x = _safe_int(row.get(col))
            if x is not None:
                return x
    return None


def _record_key(row: Dict[str, Any]) -> str:
    return _first_value(row, RECORD_KEY_COLS)


def _business_key(row: Dict[str, Any]) -> str:
    parts = [
        _first_value(row, EMP_ID_COLS),
        _first_value(row, EMP_NAME_COLS),
        _first_value(row, WO_COLS),
        _first_value(row, PROC_COLS),
        _first_value(row, START_COLS),
    ]
    return "|".join([p.strip() for p in parts])


def _compact_row(row: Dict[str, Any], source: str = "") -> Dict[str, Any]:
    return {
        "source": source or _first_value(row, SOURCE_COLS),
        "id": _record_id(row),
        "record_key": _record_key(row),
        "business_key": _business_key(row),
        "employee_id": _first_value(row, EMP_ID_COLS),
        "employee_name": _first_value(row, EMP_NAME_COLS),
        "work_order": _first_value(row, WO_COLS),
        "process_name": _first_value(row, PROC_COLS),
        "start_timestamp": _first_value(row, START_COLS),
        "end_timestamp": _first_value(row, END_COLS),
        "status": _first_value(row, STATUS_COLS),
        "source_field": _first_value(row, SOURCE_COLS),
    }


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _extract_records(obj: Any) -> List[Dict[str, Any]]:
    if obj is None:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for key in ["records", "data", "rows", "items", "time_records", "history_records", "logs"]:
            value = obj.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        # Some authority files are a dict keyed by record id.
        values = list(obj.values())
        if values and all(isinstance(x, dict) for x in values):
            return [x for x in values if isinstance(x, dict)]
    return []


def _load_records_from_paths(paths: Sequence[Path], source_name: str) -> List[Dict[str, Any]]:
    for path in paths:
        rows = _extract_records(_load_json(path))
        if rows:
            for r in rows:
                r.setdefault("_audit_source_file", str(path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path))
                r.setdefault("_audit_source_name", source_name)
            return rows
    return []


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return cur.fetchone() is not None
    except Exception:
        return False


def _sqlite_rows(table: str, limit: int = 50000) -> List[Dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            if not _sqlite_table_exists(conn, table):
                return []
            cur = conn.execute(f"SELECT * FROM {table} LIMIT ?", (int(limit),))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


def _load_tombstones() -> Dict[str, Any]:
    ids, keys, bkeys = set(), set(), set()
    files = []
    for path in SETTINGS_01_CANDIDATES + SETTINGS_02_CANDIDATES:
        obj = _load_json(path)
        if isinstance(obj, dict):
            files.append(str(path.relative_to(PROJECT_ROOT) if path.exists() and path.is_relative_to(PROJECT_ROOT) else path))
            for x in obj.get("deleted_record_ids", []) if isinstance(obj.get("deleted_record_ids", []), list) else []:
                y = _safe_int(x)
                if y is not None:
                    ids.add(y)
            for x in obj.get("deleted_record_keys", []) if isinstance(obj.get("deleted_record_keys", []), list) else []:
                s = _to_str(x)
                if s:
                    keys.add(s)
            for x in obj.get("deleted_record_business_keys", []) if isinstance(obj.get("deleted_record_business_keys", []), list) else []:
                s = _to_str(x)
                if s:
                    bkeys.add(s)
    return {
        "ids": ids,
        "record_keys": keys,
        "business_keys": bkeys,
        "source_files": files,
    }


def _index(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    by_id, by_key, by_bkey = {}, {}, {}
    for r in rows:
        rid = _record_id(r)
        if rid is not None:
            by_id[str(rid)] = r
        rk = _record_key(r)
        if rk:
            by_key[rk] = r
        bk = _business_key(r)
        if bk and bk != "||||":
            by_bkey[bk] = r
    return {"id": by_id, "record_key": by_key, "business_key": by_bkey}


def _has_match(row: Dict[str, Any], idx: Dict[str, Dict[str, Dict[str, Any]]]) -> bool:
    rid = _record_id(row)
    if rid is not None and str(rid) in idx["id"]:
        return True
    rk = _record_key(row)
    if rk and rk in idx["record_key"]:
        return True
    bk = _business_key(row)
    if bk and bk != "||||" and bk in idx["business_key"]:
        return True
    return False


def _is_deleted_by_tombstone(row: Dict[str, Any], tomb: Dict[str, Any]) -> bool:
    rid = _record_id(row)
    if rid is not None and rid in tomb["ids"]:
        return True
    rk = _record_key(row)
    if rk and rk in tomb["record_keys"]:
        return True
    bk = _business_key(row)
    if bk and bk != "||||" and bk in tomb["business_keys"]:
        return True
    return False


def _is_recovery(row: Dict[str, Any]) -> bool:
    joined = "|".join([_record_key(row), _first_value(row, SOURCE_COLS), _to_str(row.get("source")), _to_str(row.get("record_key"))]).upper()
    return any(h.upper() in joined for h in RECOVERY_HINTS)


def _is_terminal(row: Dict[str, Any]) -> bool:
    status = _first_value(row, STATUS_COLS).lower()
    end_ts = _first_value(row, END_COLS)
    return bool(end_ts) or any(h.lower() in status for h in TERMINAL_STATUS_HINTS)


def _is_active(row: Dict[str, Any]) -> bool:
    status = _first_value(row, STATUS_COLS).lower()
    return (not _is_terminal(row)) and (any(h.lower() in status for h in ACTIVE_STATUS_HINTS) or bool(_first_value(row, START_COLS)))


def _duplicate_groups(rows: Sequence[Dict[str, Any]], source_name: str, limit: int = 200) -> List[Dict[str, Any]]:
    groups = defaultdict(list)
    for r in rows:
        rk = _record_key(r)
        bk = _business_key(r)
        key = f"record_key::{rk}" if rk else f"business_key::{bk}"
        if key.endswith("||||") or key.endswith("::"):
            continue
        groups[key].append(r)
    out = []
    for key, items in groups.items():
        if len(items) <= 1:
            continue
        sample = _compact_row(items[0], source_name)
        sample.update({"issue": "duplicate_records", "duplicate_key": key, "duplicate_count": len(items), "action_hint": "先人工確認；建議只保留資料最完整的一筆。"})
        out.append(sample)
    out.sort(key=lambda x: x.get("duplicate_count", 0), reverse=True)
    return out[:limit]


def _classify_log_error(row: Dict[str, Any]) -> str:
    text = " ".join([_first_value(row, ACTION_COLS), _first_value(row, LEVEL_COLS), _first_value(row, DETAIL_COLS), _to_str(row.get("error")), _to_str(row.get("exception"))]).lower()
    if any(k in text for k in ["database is locked", "sqlite", "db", "database"]):
        return "DB/SQLite"
    if any(k in text for k in ["github", "api", "push", "sync"]):
        return "GitHub/Sync"
    if any(k in text for k in ["permission", "權限", "denied", "access"]):
        return "Permission"
    if any(k in text for k in ["timeout", "timed out", "逾時"]):
        return "Timeout"
    if any(k in text for k in ["importerror", "modulenotfound", "module"]):
        return "Import/Dependency"
    if any(k in text for k in ["typeerror", "valueerror", "keyerror", "attributeerror"]):
        return "Python Error"
    if any(k in text for k in ["error", "exception", "traceback", "失敗", "錯誤"]):
        return "General Error"
    return "Other"


def _analyze_logs(logs: Sequence[Dict[str, Any]], limit: int = 200) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    error_rows = []
    for r in logs:
        level = _first_value(r, LEVEL_COLS).upper()
        text = " ".join([level, _first_value(r, ACTION_COLS), _first_value(r, DETAIL_COLS)]).lower()
        if "error" in text or "錯誤" in text or "exception" in text or level in {"ERROR", "CRITICAL"}:
            c = _classify_log_error(r)
            row = {
                "category": c,
                "log_time": _first_value(r, LOG_TIME_COLS),
                "action": _first_value(r, ACTION_COLS),
                "level": _first_value(r, LEVEL_COLS),
                "target_id": _first_value(r, ["target_id", "Target ID", "id", "ID"]),
                "detail": _first_value(r, DETAIL_COLS)[:500],
            }
            error_rows.append(row)
    summary = []
    cnt = Counter(x["category"] for x in error_rows)
    for k, v in cnt.most_common():
        summary.append({"category": k, "count": v, "action_hint": "依分類優先處理最高筆數錯誤。"})
    return summary, error_rows[:limit]


def collect_v182_consolidated_audit(limit_rows: int = 500) -> Dict[str, Any]:
    """Return read-only consolidated audit report."""
    started = datetime.now()
    errors: List[str] = []
    try:
        rows01 = _load_records_from_paths([AUTH_01, PERSIST_01], "01_authority")
        rows02 = _load_records_from_paths([AUTH_02, PERSIST_02], "02_history")
        logs = _load_records_from_paths([AUTH_06, PERSIST_06], "06_logs")
        sql_time = _sqlite_rows("time_records")
        sql_logs = _sqlite_rows("logs", limit=50000)
        if sql_logs and not logs:
            logs = sql_logs
        tomb = _load_tombstones()

        idx01 = _index(rows01)
        idx02 = _index(rows02)
        idxsql = _index(sql_time)

        issue_rows: List[Dict[str, Any]] = []
        def add_issue(issue: str, row: Dict[str, Any], source: str, severity: str, hint: str):
            cr = _compact_row(row, source)
            cr.update({"issue": issue, "severity": severity, "action_hint": hint})
            issue_rows.append(cr)

        for r in rows01:
            if not _has_match(r, idx02):
                add_issue("01_has_02_missing", r, "01_authority", "HIGH", "01 有但 02 沒有；需確認是否應補入 02 或從 01 清除。")
        for r in rows02:
            if not _has_match(r, idx01):
                add_issue("02_has_01_missing", r, "02_history", "MEDIUM", "02 有但 01 沒有；若為已結束歷史通常可接受，但 Today 顯示應以 02 為準。")
        for r in sql_time:
            if not _has_match(r, idx01) and not _has_match(r, idx02):
                add_issue("sqlite_orphan", r, "sqlite_time_records", "HIGH", "SQLite 有但 01/02 權威檔沒有；若已刪除需被 tombstone 擋住，不能復活。")

        for source, rows in [("01_authority", rows01), ("02_history", rows02), ("sqlite_time_records", sql_time)]:
            for r in rows:
                if _is_deleted_by_tombstone(r, tomb):
                    add_issue("tombstone_but_visible_source", r, source, "CRITICAL", "已在刪除 tombstone 內但仍存在來源資料；畫面必須過濾，必要時清理來源殘留。")

        for source, rows in [("01_authority", rows01), ("02_history", rows02), ("sqlite_time_records", sql_time)]:
            for r in rows:
                if _is_recovery(r) and _is_active(r):
                    add_issue("log_recovery_active", r, source, "HIGH", "LOGRECOVERY 不應進入一般 Active Work；請走 V166B 待補人工結算。")

        duplicate_rows = []
        duplicate_rows.extend(_duplicate_groups(rows01, "01_authority", limit_rows))
        duplicate_rows.extend(_duplicate_groups(rows02, "02_history", limit_rows))
        duplicate_rows.extend(_duplicate_groups(sql_time, "sqlite_time_records", limit_rows))

        log_summary, log_errors = _analyze_logs(logs, limit_rows)

        source_counts = [
            {"source": "01_authority", "count": len(rows01), "path": str(AUTH_01.relative_to(PROJECT_ROOT))},
            {"source": "02_history", "count": len(rows02), "path": str(AUTH_02.relative_to(PROJECT_ROOT))},
            {"source": "sqlite_time_records", "count": len(sql_time), "path": str(DB_PATH.relative_to(PROJECT_ROOT)) if DB_PATH.exists() else "missing"},
            {"source": "06_logs", "count": len(logs), "path": str(AUTH_06.relative_to(PROJECT_ROOT))},
            {"source": "tombstone_ids", "count": len(tomb["ids"]), "path": ", ".join(tomb.get("source_files", []))},
            {"source": "tombstone_record_keys", "count": len(tomb["record_keys"]), "path": ", ".join(tomb.get("source_files", []))},
            {"source": "tombstone_business_keys", "count": len(tomb["business_keys"]), "path": ", ".join(tomb.get("source_files", []))},
        ]

        severity_counts = Counter(x.get("severity", "") for x in issue_rows)
        issue_counts = Counter(x.get("issue", "") for x in issue_rows)
        issue_summary = [{"issue": k, "count": v} for k, v in issue_counts.most_common()]
        severity_summary = [{"severity": k, "count": v} for k, v in severity_counts.most_common()]

        version_rows = collect_v182_version_health_rows()
        backup_rows = collect_v182_backup_queue_hint_rows()

        recommended = []
        if issue_counts.get("tombstone_but_visible_source", 0):
            recommended.append("先處理 tombstone 仍可見資料，這是刪除後復活的主因。")
        if issue_counts.get("log_recovery_active", 0):
            recommended.append("將 LOGRECOVERY 作業中資料轉入 V166B 待補人工結算，不要進 Active Work。")
        if duplicate_rows:
            recommended.append("先產生重複資料清單，人工確認後再清理，不要直接刪除。")
        if log_summary:
            recommended.append("依 06 LOG 錯誤分類先修最高筆數錯誤。")
        if not recommended:
            recommended.append("目前未偵測到高風險不一致；建議定期匯出報告留存。")

        elapsed = (datetime.now() - started).total_seconds()
        ok = not severity_counts.get("CRITICAL", 0)
        return {
            "ok": ok,
            "version": SERVICE_VERSION,
            "generated_at": _now_str(),
            "elapsed_seconds": round(elapsed, 3),
            "production_write_path_changed": False,
            "read_only": True,
            "source_counts": source_counts,
            "severity_summary": severity_summary,
            "issue_summary": issue_summary,
            "issue_rows": issue_rows[:limit_rows],
            "duplicate_rows": duplicate_rows[:limit_rows],
            "log_error_summary": log_summary,
            "log_error_rows": log_errors,
            "version_rows": version_rows,
            "backup_rows": backup_rows,
            "recommendations": recommended,
            "errors": errors,
        }
    except Exception as exc:
        errors.append(str(exc))
        return {
            "ok": False,
            "version": SERVICE_VERSION,
            "generated_at": _now_str(),
            "production_write_path_changed": False,
            "read_only": True,
            "source_counts": [],
            "severity_summary": [{"severity": "EXCEPTION", "count": 1}],
            "issue_summary": [],
            "issue_rows": [],
            "duplicate_rows": [],
            "log_error_summary": [],
            "log_error_rows": [],
            "version_rows": [],
            "backup_rows": [],
            "recommendations": ["V182 檢查服務發生例外，請先查看 errors 欄位。"],
            "errors": errors + [traceback.format_exc()],
        }


def collect_v182_version_health_rows() -> List[Dict[str, Any]]:
    required = [
        "services/time_record_service.py",
        "services/log_service.py",
        "services/time_record_transaction_guard_service.py",
        "services/history_delete_repair_service.py",
        "services/time_record_delete_unifier_service.py",
        "services/time_record_delete_queue_service.py",
        "services/data_consistency_audit_service.py",
        "pages/01_01. 工時紀錄.py",
        "pages/02_02. 歷史紀錄.py",
        "pages/14_14. 資料健康檢查中心.py",
    ]
    rows = []
    for rel in required:
        p = PROJECT_ROOT / rel
        rows.append({
            "file": rel,
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else 0,
            "modified_time": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if p.exists() else "",
        })
    return rows


def collect_v182_backup_queue_hint_rows() -> List[Dict[str, Any]]:
    rows = []
    candidates = [
        DATA_ROOT / "persistent_state" / "auto_external_backup_state.json",
        DATA_ROOT / "persistent_state" / "spt_audit_log_state.json",
        DATA_ROOT / "manifest.json",
    ]
    for p in candidates:
        obj = _load_json(p)
        rows.append({
            "file": str(p.relative_to(PROJECT_ROOT)) if p.exists() else str(p),
            "exists": p.exists(),
            "json_ok": isinstance(obj, (dict, list)),
            "size_bytes": p.stat().st_size if p.exists() else 0,
            "hint": "備份/狀態檔只作狀態提示；現場交易不可等待 GitHub。",
        })
    return rows


def export_v182_audit_excel_bytes(report: Optional[Dict[str, Any]] = None) -> bytes:
    report = report or collect_v182_consolidated_audit(limit_rows=5000)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(report.get("source_counts", [])).to_excel(writer, index=False, sheet_name="source_counts")
        pd.DataFrame(report.get("severity_summary", [])).to_excel(writer, index=False, sheet_name="severity_summary")
        pd.DataFrame(report.get("issue_summary", [])).to_excel(writer, index=False, sheet_name="issue_summary")
        pd.DataFrame(report.get("issue_rows", [])).to_excel(writer, index=False, sheet_name="issues")
        pd.DataFrame(report.get("duplicate_rows", [])).to_excel(writer, index=False, sheet_name="duplicates")
        pd.DataFrame(report.get("log_error_summary", [])).to_excel(writer, index=False, sheet_name="log_error_summary")
        pd.DataFrame(report.get("log_error_rows", [])).to_excel(writer, index=False, sheet_name="log_errors")
        pd.DataFrame(report.get("version_rows", [])).to_excel(writer, index=False, sheet_name="version_health")
        pd.DataFrame(report.get("backup_rows", [])).to_excel(writer, index=False, sheet_name="backup_hints")
        pd.DataFrame([{"recommendation": x} for x in report.get("recommendations", [])]).to_excel(writer, index=False, sheet_name="recommendations")
    bio.seek(0)
    return bio.getvalue()


# Backward-friendly aliases for page/tool callers.
collect_consolidated_audit = collect_v182_consolidated_audit
export_consolidated_audit_excel_bytes = export_v182_audit_excel_bytes
