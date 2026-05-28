# -*- coding: utf-8 -*-
"""V155 backup queue status service.

Read-only by default.  It summarizes the local authority upload queue, LOG batch
sync state, and V152 time-record event journal outbox so administrators can see
whether shop-floor data has already been backed up to GitHub.

Manual flush only uploads existing local authority/event files.  It does not
modify time-record business rows, does not recalculate, does not delete, and does
not rewrite 01/02 history data from a partial table.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERM_ROOT = PROJECT_ROOT / "data" / "permanent_store"
AUTH_QUEUE_PATH = PERM_ROOT / "authority_upload_queue.json"
EVENT_OUTBOX_PATH = PERM_ROOT / "system" / "time_record_event_upload_outbox.json"
EVENT_STATUS_PATH = PERM_ROOT / "system" / "time_record_event_journal_status.json"


def _now_text() -> str:
    try:
        from services.timezone_service import now_text
        return now_text()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _file_info(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {"path": str(path.relative_to(PROJECT_ROOT)), "exists": False, "size": 0, "modified_at": ""}
        stat = path.stat()
        return {
            "path": str(path.relative_to(PROJECT_ROOT)),
            "exists": True,
            "size": int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        return {"path": str(path), "exists": False, "size": 0, "modified_at": "", "error": str(exc)[:300]}


def _authority_queue_status() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False, "pending": 0, "running": False, "last_error": "", "entries": []}
    try:
        from services.permanent_authority_service import get_authority_upload_queue_status
        raw = get_authority_upload_queue_status()
        if isinstance(raw, dict):
            out.update(raw)
            out["available"] = True
    except Exception as exc:
        out["last_error"] = str(exc)[:500]

    data = _read_json(AUTH_QUEUE_PATH)
    entries = data.get("entries", {}) if isinstance(data.get("entries"), dict) else {}
    rows: list[dict[str, Any]] = []
    for rel, item in entries.items():
        if isinstance(item, dict):
            row = dict(item)
            row.setdefault("remote_path", rel)
            rows.append(row)
        else:
            rows.append({"remote_path": rel, "raw": str(item)[:200]})
    if rows:
        out["entries"] = rows
        out["pending"] = len(rows)
    out["queue_file"] = _file_info(AUTH_QUEUE_PATH)
    return out


def _log_batch_status() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False, "running": False, "pending": False, "last_error": "", "write_count_since_sync": 0}
    for fn_name in ("get_log_batch_status", "get_system_log_authority_status"):
        try:
            import services.log_service as log_service
            fn = getattr(log_service, fn_name, None)
            if callable(fn):
                raw = fn()
                if isinstance(raw, dict):
                    out.update(raw)
                    out["available"] = True
                    break
        except Exception as exc:
            out["last_error"] = str(exc)[:500]
    return out


def _event_journal_status() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False, "pending_event_uploads": 0, "event_files": 0, "sqlite_events": 0, "last_error": ""}
    try:
        from services.time_record_event_journal_service import audit_time_record_event_journal
        raw = audit_time_record_event_journal()
        if isinstance(raw, dict):
            out.update(raw)
            out["available"] = True
    except Exception as exc:
        out["last_error"] = str(exc)[:500]

    data = _read_json(EVENT_OUTBOX_PATH)
    pending_paths = data.get("pending_paths", []) if isinstance(data.get("pending_paths"), list) else []
    if pending_paths:
        out["pending_event_uploads"] = max(int(out.get("pending_event_uploads") or 0), len(pending_paths))
        out["pending_paths_sample"] = pending_paths[:20]
    out["outbox_file"] = _file_info(EVENT_OUTBOX_PATH)
    out["status_file"] = _file_info(EVENT_STATUS_PATH)
    return out


def _authority_files_status() -> list[dict[str, Any]]:
    targets = [
        "modules/01_time_records/records.json",
        "modules/02_history/records.json",
        "modules/03_work_orders/records.json",
        "modules/04_employees/records.json",
        "modules/06_logs/records.json",
        "modules/10_permissions/records.json",
        "modules/10_permissions/settings.json",
        "modules/11_login_logs/records.json",
        "modules/13_system_settings/records.json",
        "modules/13_system_settings/settings.json",
        "modules/14_data_health/records.json",
        "modules/14_data_health/settings.json",
    ]
    rows = []
    for rel in targets:
        info = _file_info(PERM_ROOT / rel)
        info["name"] = rel
        rows.append(info)
    return rows


def collect_backup_queue_status() -> dict[str, Any]:
    authority = _authority_queue_status()
    logs = _log_batch_status()
    events = _event_journal_status()
    files = _authority_files_status()

    authority_pending = int(authority.get("pending") or 0)
    log_pending = bool(logs.get("pending")) or int(logs.get("write_count_since_sync") or 0) > 0
    event_pending = int(events.get("pending_event_uploads") or 0)
    errors = []
    for label, block in [("authority", authority), ("logs", logs), ("events", events)]:
        err = str(block.get("last_error") or "").strip()
        if err:
            errors.append({"source": label, "error": err})
    missing_key_files = [f for f in files if f.get("name") in {"modules/01_time_records/records.json", "modules/02_history/records.json", "modules/10_permissions/records.json"} and not f.get("exists")]

    if errors:
        level = "ERROR"
    elif missing_key_files or authority_pending or log_pending or event_pending:
        level = "WARN"
    else:
        level = "OK"

    return {
        "checked_at": _now_text(),
        "level": level,
        "summary": {
            "authority_pending": authority_pending,
            "log_pending": bool(log_pending),
            "log_write_count_since_sync": int(logs.get("write_count_since_sync") or 0),
            "event_pending": event_pending,
            "missing_key_files": len(missing_key_files),
            "error_count": len(errors),
        },
        "authority_queue": authority,
        "log_batch": logs,
        "event_journal": events,
        "authority_files": files,
        "errors": errors,
        "missing_key_files": missing_key_files,
    }


def flush_backup_queues_now(reason: str = "manual_v155_backup_flush", max_seconds: float = 12.0) -> dict[str, Any]:
    """Best-effort manual upload of pending backup queues.

    This function does not create, edit, delete, or recalculate business records.
    It only uploads local authority/event/log files that already exist.
    """
    result: dict[str, Any] = {"ok": True, "started_at": _now_text(), "actions": []}

    try:
        from services.permanent_authority_service import flush_authority_upload_queue_now
        res = flush_authority_upload_queue_now(reason=reason, max_seconds=float(max_seconds))
        result["actions"].append({"target": "authority_upload_queue", "result": res})
    except Exception as exc:
        result["ok"] = False
        result["actions"].append({"target": "authority_upload_queue", "error": str(exc)[:500]})

    try:
        from services.log_service import flush_log_authority_batch_now
        res = flush_log_authority_batch_now(reason=reason)
        result["actions"].append({"target": "system_log_batch", "result": res})
    except Exception as exc:
        # Older builds may not have V147 log batching; record as unavailable, not fatal.
        result["actions"].append({"target": "system_log_batch", "unavailable": True, "message": str(exc)[:300]})

    try:
        from services.time_record_event_journal_service import flush_time_record_event_journal_now
        res = flush_time_record_event_journal_now(reason=reason, limit=300)
        result["actions"].append({"target": "time_record_event_journal", "result": res})
    except Exception as exc:
        result["actions"].append({"target": "time_record_event_journal", "unavailable": True, "message": str(exc)[:300]})

    result["finished_at"] = _now_text()
    result["after"] = collect_backup_queue_status()
    # If any available action explicitly failed, mark not ok.
    for action in result.get("actions", []):
        if isinstance(action, dict) and action.get("result") and isinstance(action.get("result"), dict):
            if action["result"].get("ok") is False:
                result["ok"] = False
        if isinstance(action, dict) and action.get("error"):
            result["ok"] = False
    return result


def status_rows_for_table(status: dict[str, Any]) -> list[dict[str, Any]]:
    summary = status.get("summary", {}) if isinstance(status.get("summary"), dict) else {}
    rows = [
        {"項目": "GitHub 權威檔待上傳", "數值": summary.get("authority_pending", 0), "說明": "authority_upload_queue.json pending entries"},
        {"項目": "LOG 批次待同步", "數值": "是" if summary.get("log_pending") else "否", "說明": "06 LOG 背景批次狀態"},
        {"項目": "LOG 未同步寫入數", "數值": summary.get("log_write_count_since_sync", 0), "說明": "上次批次同步後新增 LOG 數"},
        {"項目": "工時事件待上傳", "數值": summary.get("event_pending", 0), "說明": "V152 event journal pending uploads"},
        {"項目": "關鍵權威檔缺失", "數值": summary.get("missing_key_files", 0), "說明": "01/02/10 等關鍵 records/settings 檔案"},
        {"項目": "錯誤數", "數值": summary.get("error_count", 0), "說明": "背景上傳或狀態讀取錯誤"},
    ]
    return rows
