# -*- coding: utf-8 -*-
"""V152 append-only time-record event journal.

This module is intentionally independent from page code.  It adds a transaction
journal beside the existing time_records table so every shop-floor action has a
separate append-only proof record.  JSON/authority snapshots remain useful for
backup and display, but the event journal provides a durable reconstruction path
when a snapshot is overwritten by concurrent users.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

try:
    from services.db_service import DB_PATH, query_df, query_one, clear_query_cache
except Exception:  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = PROJECT_ROOT / "data" / "permanent_store" / "database" / "spt_time_tracking.db"
    query_df = query_one = clear_query_cache = None  # type: ignore

try:
    from services.timezone_service import now_text, today_text
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def today_text() -> str:
        return datetime.now().strftime("%Y-%m-%d")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENT_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "02_history" / "time_record_events"
EVENT_OUTBOX_PATH = PROJECT_ROOT / "data" / "permanent_store" / "system" / "time_record_event_upload_outbox.json"
EVENT_STATUS_PATH = PROJECT_ROOT / "data" / "permanent_store" / "system" / "time_record_event_journal_status.json"

_LOCK = threading.RLock()
_UPLOAD_STATE: dict[str, Any] = {
    "running": False,
    "pending": False,
    "last_error": "",
    "last_upload_at": "",
    "last_event_id": "",
}


def _json_default(value: Any) -> Any:
    try:
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value.strftime("%Y-%m-%d")
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    return str(value)


def _clean_text(value: Any) -> str:
    try:
        if pd is not None and pd.isna(value):
            return ""
    except Exception:
        pass
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return {str(k): _json_default(v) for k, v in row.items()}
    try:
        if hasattr(row, "to_dict"):
            return {str(k): _json_default(v) for k, v in row.to_dict().items()}
    except Exception:
        pass
    return {}


def _records_from_any(rows: Any) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if isinstance(rows, dict):
        return [_row_to_dict(rows)]
    if pd is not None and isinstance(rows, pd.DataFrame):
        try:
            clean = rows.copy().where(pd.notna(rows), "")
            return [_row_to_dict(r) for _, r in clean.iterrows()]
        except Exception:
            return []
    if isinstance(rows, (list, tuple)):
        out: list[dict[str, Any]] = []
        for r in rows:
            d = _row_to_dict(r)
            if d:
                out.append(d)
        return out
    return []


def _record_id(row: dict[str, Any]) -> str:
    for k in ("id", "ID", "ID / ID", "record_id"):
        v = _clean_text(row.get(k))
        if v:
            try:
                return str(int(float(v)))
            except Exception:
                return v
    return ""


def _record_key(row: dict[str, Any]) -> str:
    for k in ("record_key", "紀錄鍵 / Record Key"):
        v = _clean_text(row.get(k))
        if v:
            return v
    emp = _clean_text(row.get("employee_id") or row.get("工號 / Employee ID") or row.get("工號"))
    name = _clean_text(row.get("employee_name") or row.get("姓名 / Name") or row.get("姓名"))
    wo = _clean_text(row.get("work_order") or row.get("製令 / Work Order") or row.get("製令"))
    proc = _clean_text(row.get("process_name") or row.get("工段 / Process") or row.get("工段"))
    start = _clean_text(row.get("start_timestamp") or row.get("開始時間戳 / Start Timestamp") or row.get("開始時間"))
    if emp or wo or proc or start:
        return "biz|" + "|".join([emp, name, wo, proc, start])
    return ""


def _employee_id(row: dict[str, Any]) -> str:
    return _clean_text(row.get("employee_id") or row.get("工號 / Employee ID") or row.get("工號"))


def _employee_name(row: dict[str, Any]) -> str:
    return _clean_text(row.get("employee_name") or row.get("姓名 / Name") or row.get("姓名"))


def _work_order(row: dict[str, Any]) -> str:
    return _clean_text(row.get("work_order") or row.get("製令 / Work Order") or row.get("製令"))


def _process_name(row: dict[str, Any]) -> str:
    return _clean_text(row.get("process_name") or row.get("工段 / Process") or row.get("工段"))


def _start_timestamp(row: dict[str, Any]) -> str:
    return _clean_text(row.get("start_timestamp") or row.get("開始時間戳 / Start Timestamp") or row.get("開始時間"))


def _event_day(event_time: str) -> str:
    text = _clean_text(event_time)
    if len(text) >= 10:
        return text[:10]
    return today_text()


def _safe_event_filename(event_id: str, event_time: str) -> str:
    stamp = _clean_text(event_time).replace("-", "").replace(":", "").replace(" ", "_")[:15]
    return f"ev_{stamp}_{event_id}.json"


def _event_path(event_id: str, event_time: str) -> Path:
    day = _event_day(event_time)
    return EVENT_ROOT / day / _safe_event_filename(event_id, event_time)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    # verify before replace
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def _open_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def ensure_time_record_event_schema() -> None:
    with _open_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS time_record_events (
                event_id TEXT PRIMARY KEY,
                record_key TEXT,
                record_id TEXT,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL,
                employee_id TEXT,
                employee_name TEXT,
                work_order TEXT,
                process_name TEXT,
                start_timestamp TEXT,
                operator_account TEXT,
                payload_json TEXT,
                checksum TEXT,
                previous_checksum TEXT,
                source TEXT DEFAULT 'streamlit',
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS time_record_outbox (
                task_id TEXT PRIMARY KEY,
                task_type TEXT,
                local_path TEXT,
                status TEXT DEFAULT 'pending',
                try_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_events_record_key ON time_record_events(record_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_events_record_id ON time_record_events(record_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_events_type_time ON time_record_events(event_type, event_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_events_employee_time ON time_record_events(employee_id, event_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_outbox_status ON time_record_outbox(status, created_at)")
        conn.commit()


def _last_checksum(conn: sqlite3.Connection | None = None) -> str:
    try:
        if conn is not None:
            row = conn.execute("SELECT checksum FROM time_record_events ORDER BY event_time DESC, created_at DESC LIMIT 1").fetchone()
            return str(row[0] or "") if row else ""
        with _open_conn() as c:
            row = c.execute("SELECT checksum FROM time_record_events ORDER BY event_time DESC, created_at DESC LIMIT 1").fetchone()
            return str(row[0] or "") if row else ""
    except Exception:
        return ""


def _checksum(payload: dict[str, Any], previous_checksum: str) -> str:
    body = json.dumps({"payload": payload, "previous_checksum": previous_checksum}, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _current_user_name() -> str:
    try:
        import streamlit as st  # type: ignore
        user = st.session_state.get("user") or st.session_state.get("current_user") or {}
        if isinstance(user, dict):
            return _clean_text(user.get("username") or user.get("account") or user.get("user_name") or user.get("employee_id")) or "system"
    except Exception:
        pass
    return "system"


def _read_outbox_file() -> dict[str, Any]:
    try:
        if EVENT_OUTBOX_PATH.exists():
            data = json.loads(EVENT_OUTBOX_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {"version": "V152_TIME_RECORD_EVENT_OUTBOX", "pending_paths": [], "updated_at": now_text()}


def _write_outbox_file(data: dict[str, Any]) -> None:
    data = dict(data or {})
    data["updated_at"] = now_text()
    _atomic_write_json(EVENT_OUTBOX_PATH, data)


def _queue_upload(path: Path) -> None:
    try:
        ensure_time_record_event_schema()
        task_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24]
        with _open_conn() as conn:
            conn.execute(
                """
                INSERT INTO time_record_outbox(task_id, task_type, local_path, status, try_count, created_at, updated_at)
                VALUES (?, 'github_upload_event', ?, 'pending', 0, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET status='pending', updated_at=excluded.updated_at
                """,
                (task_id, str(path), now_text(), now_text()),
            )
            conn.commit()
    except Exception:
        pass
    try:
        data = _read_outbox_file()
        pending = list(data.get("pending_paths", [])) if isinstance(data.get("pending_paths"), list) else []
        sp = str(path)
        if sp not in pending:
            pending.append(sp)
        data["pending_paths"] = pending[-1000:]
        _write_outbox_file(data)
    except Exception:
        pass


def _log_warn(action: str, message: str, target_id: str = "") -> None:
    try:
        from services.log_service import write_log
        write_log(action, message, "time_record_events", target_id, level="WARN")
    except Exception:
        pass


def append_time_record_event(
    event_type: str,
    rows: Any = None,
    *,
    record_id: str | int | None = None,
    record_key: str | None = None,
    operator_account: str | None = None,
    reason: str = "",
    payload_extra: dict[str, Any] | None = None,
    schedule_upload: bool = True,
) -> list[str]:
    """Append one immutable event per row.

    This function never deletes or overwrites previous events.  It writes to both
    SQLite and a row-level JSON shard.  GitHub upload is queued asynchronously so
    operator actions do not wait for network round trips.
    """
    event_type = _clean_text(event_type).upper() or "TIME_RECORD_EVENT"
    records = _records_from_any(rows)
    if not records:
        records = [{}]
    written: list[str] = []
    with _LOCK:
        ensure_time_record_event_schema()
        with _open_conn() as conn:
            prev = _last_checksum(conn)
            for row in records:
                row = dict(row or {})
                rid = _clean_text(record_id) or _record_id(row)
                rkey = _clean_text(record_key) or _record_key(row)
                event_id = uuid.uuid4().hex
                event_time = now_text()
                payload = {
                    "schema": "SPT-TimeRecordEvent-V152",
                    "event_id": event_id,
                    "event_type": event_type,
                    "event_time": event_time,
                    "record_id": rid,
                    "record_key": rkey,
                    "operator_account": _clean_text(operator_account) or _current_user_name(),
                    "reason": reason,
                    "row": row,
                    "extra": payload_extra or {},
                }
                checksum = _checksum(payload, prev)
                payload["previous_checksum"] = prev
                payload["checksum"] = checksum
                path = _event_path(event_id, event_time)
                try:
                    _atomic_write_json(path, payload)
                except Exception as exc:
                    _log_warn("V152_EVENT_FILE_WRITE_ERROR", f"事件 JSON 寫入失敗：{exc}", rid)
                    # still try SQLite; do not stop shop-floor operation
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO time_record_events(
                            event_id, record_key, record_id, event_type, event_time,
                            employee_id, employee_name, work_order, process_name, start_timestamp,
                            operator_account, payload_json, checksum, previous_checksum, source, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'streamlit', ?)
                        """,
                        (
                            event_id, rkey, rid, event_type, event_time,
                            _employee_id(row), _employee_name(row), _work_order(row), _process_name(row), _start_timestamp(row),
                            payload["operator_account"], json.dumps(payload, ensure_ascii=False, default=_json_default), checksum, prev, event_time,
                        ),
                    )
                    written.append(event_id)
                    prev = checksum
                except Exception as exc:
                    _log_warn("V152_EVENT_SQLITE_WRITE_ERROR", f"事件 SQLite 寫入失敗：{exc}", rid)
                if schedule_upload:
                    _queue_upload(path)
            conn.commit()
    if schedule_upload:
        schedule_time_record_event_upload("v152_append_event")
    try:
        if callable(clear_query_cache):
            clear_query_cache()
    except Exception:
        pass
    return written


def _pending_paths_from_sqlite(limit: int = 100) -> list[str]:
    try:
        ensure_time_record_event_schema()
        with _open_conn() as conn:
            rows = conn.execute(
                "SELECT local_path FROM time_record_outbox WHERE status='pending' ORDER BY created_at LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [str(r[0]) for r in rows if r and r[0]]
    except Exception:
        return []


def _mark_uploaded(path: str, ok: bool, error: str = "") -> None:
    try:
        task_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24]
        with _open_conn() as conn:
            if ok:
                conn.execute(
                    "UPDATE time_record_outbox SET status='done', last_error='', updated_at=? WHERE task_id=?",
                    (now_text(), task_id),
                )
            else:
                conn.execute(
                    "UPDATE time_record_outbox SET try_count=COALESCE(try_count,0)+1, last_error=?, updated_at=? WHERE task_id=?",
                    (error[:500], now_text(), task_id),
                )
            conn.commit()
    except Exception:
        pass


def _github_upload_path(path: Path, reason: str) -> dict[str, Any]:
    try:
        from services.permanent_authority_service import github_put_file
        if not path.exists():
            return {"ok": False, "error": "file_missing", "path": str(path)}
        return github_put_file(path, path.read_text(encoding="utf-8"), f"SPT time event journal: {reason}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "path": str(path)}


def flush_time_record_event_journal_now(reason: str = "manual_v152_event_flush", limit: int = 200) -> dict[str, Any]:
    """Synchronously upload pending event files.  Safe for logout/manual backup."""
    uploaded = 0
    failed = 0
    paths: list[str] = []
    try:
        paths.extend(_pending_paths_from_sqlite(limit=limit))
    except Exception:
        pass
    try:
        data = _read_outbox_file()
        for p in data.get("pending_paths", []) if isinstance(data.get("pending_paths", []), list) else []:
            if p not in paths:
                paths.append(p)
    except Exception:
        pass
    remaining: list[str] = []
    for p in paths[: int(limit or 200)]:
        path = Path(p)
        res = _github_upload_path(path, reason)
        if res.get("ok"):
            uploaded += 1
            _mark_uploaded(str(path), True)
        else:
            failed += 1
            remaining.append(str(path))
            _mark_uploaded(str(path), False, str(res.get("error") or res)[:500])
    try:
        data = _read_outbox_file()
        # Keep untried paths too.
        all_pending = list(data.get("pending_paths", [])) if isinstance(data.get("pending_paths", []), list) else []
        kept = []
        done = set(paths[: int(limit or 200)]) - set(remaining)
        for p in all_pending:
            if p not in done and p not in kept:
                kept.append(p)
        data["pending_paths"] = kept[-1000:]
        _write_outbox_file(data)
    except Exception:
        pass
    status = {"ok": failed == 0, "uploaded": uploaded, "failed": failed, "pending_remaining": len(remaining)}
    try:
        _atomic_write_json(EVENT_STATUS_PATH, {"schema": "V152_TIME_RECORD_EVENT_STATUS", "updated_at": now_text(), **status, "state": dict(_UPLOAD_STATE)})
    except Exception:
        pass
    return status


def schedule_time_record_event_upload(reason: str = "v152_async_event_upload") -> None:
    try:
        delay = float(os.environ.get("SPT_EVENT_UPLOAD_DELAY_SEC", "0.8") or 0.8)
    except Exception:
        delay = 0.8

    def _worker() -> None:
        try:
            time.sleep(max(delay, 0.0))
            while True:
                _UPLOAD_STATE["pending"] = False
                res = flush_time_record_event_journal_now(reason, limit=80)
                _UPLOAD_STATE["last_upload_at"] = now_text()
                _UPLOAD_STATE["last_error"] = "" if res.get("ok") else json.dumps(res, ensure_ascii=False)[:500]
                if not _UPLOAD_STATE.get("pending"):
                    _UPLOAD_STATE["running"] = False
                    return
                time.sleep(0.3)
        except Exception as exc:
            _UPLOAD_STATE["last_error"] = str(exc)[:500]
            _UPLOAD_STATE["running"] = False

    try:
        _UPLOAD_STATE["pending"] = True
        if _UPLOAD_STATE.get("running"):
            return
        _UPLOAD_STATE["running"] = True
        threading.Thread(target=_worker, name="SPT-V152-TimeRecordEventUpload", daemon=True).start()
    except Exception as exc:
        _UPLOAD_STATE["running"] = False
        _UPLOAD_STATE["last_error"] = str(exc)[:500]


def event_rows_from_sqlite(limit: int | None = None) -> list[dict[str, Any]]:
    try:
        ensure_time_record_event_schema()
        sql = "SELECT * FROM time_record_events ORDER BY event_time, created_at"
        params: tuple[Any, ...] = ()
        if limit:
            sql += " LIMIT ?"
            params = (int(limit),)
        with _open_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def event_rows_from_files() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if not EVENT_ROOT.exists():
            return rows
        for p in sorted(EVENT_ROOT.glob("*/*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("event_id"):
                    rows.append(data)
            except Exception:
                continue
    except Exception:
        pass
    return rows


def rebuild_latest_rows_from_events() -> list[dict[str, Any]]:
    """Rebuild latest rows from append-only events without writing anything."""
    events = []
    for e in event_rows_from_files():
        events.append(e)
    seen_event_ids = {str(e.get("event_id")) for e in events}
    for r in event_rows_from_sqlite():
        eid = str(r.get("event_id") or "")
        if eid in seen_event_ids:
            continue
        try:
            payload = json.loads(r.get("payload_json") or "{}")
        except Exception:
            payload = dict(r)
        if isinstance(payload, dict):
            events.append(payload)
    try:
        events.sort(key=lambda e: (_clean_text(e.get("event_time")), _clean_text(e.get("event_id"))))
    except Exception:
        pass
    by_key: dict[str, dict[str, Any]] = {}
    for e in events:
        row = _row_to_dict(e.get("row") or {})
        if not row:
            continue
        key = _record_key(row) or _clean_text(e.get("record_key")) or ("id:" + _clean_text(e.get("record_id")))
        if not key:
            continue
        event_type = _clean_text(e.get("event_type")).upper()
        if event_type in {"DELETE_MARK", "DELETE_TIME_RECORD", "SOFT_DELETE"}:
            # soft-delete marker: keep row but mark it deleted so UI/tombstone can filter.
            row["is_deleted"] = True
            row["deleted_at"] = _clean_text(e.get("event_time"))
        by_key[key] = row
    return list(by_key.values())


def audit_time_record_event_journal() -> dict[str, Any]:
    file_events = event_rows_from_files()
    sqlite_events = event_rows_from_sqlite()
    rebuilt = rebuild_latest_rows_from_events()
    pending = _pending_paths_from_sqlite(limit=10000)
    return {
        "event_files": len(file_events),
        "sqlite_events": len(sqlite_events),
        "rebuilt_rows": len(rebuilt),
        "pending_event_uploads": len(pending),
        "upload_state": dict(_UPLOAD_STATE),
        "status_path": str(EVENT_STATUS_PATH),
    }
