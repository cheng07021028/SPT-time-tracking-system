# -*- coding: utf-8 -*-
"""V204 frontend operation isolation utilities.

UI-neutral backend helper.  It never changes Streamlit pages, CSS, theme, table
rendering, or button layout.  It only lets transaction paths finish locally first
and move expensive follow-up work to a small background/queue layer.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE_DIR = PROJECT_ROOT / "data" / "runtime_queue"
QUEUE_FILE = QUEUE_DIR / "v204_background_jobs.jsonl"
_STATUS_FILE = QUEUE_DIR / "v204_status.json"
_LOCK = threading.Lock()
_TIMERS: dict[str, threading.Timer] = {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)


def enqueue_job(kind: str, payload: dict[str, Any] | None = None, *, reason: str = "", status: str = "pending") -> str:
    """Append a tiny local job record and return its uid.

    This is intentionally local and fast; it does not call GitHub, does not scan
    large files, and does not block the active Streamlit user session.
    """
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex
    row = {
        "uid": uid,
        "kind": str(kind or "background_job"),
        "reason": str(reason or ""),
        "status": str(status or "pending"),
        "created_at": _now(),
        "pid": os.getpid(),
        "payload": _json_safe(payload or {}),
    }
    with _LOCK:
        with QUEUE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return uid


def _write_status(**updates: Any) -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {}
    try:
        if _STATUS_FILE.exists():
            status = json.loads(_STATUS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        status = {}
    status.update({k: _json_safe(v) for k, v in updates.items()})
    status["updated_at"] = _now()
    tmp = _STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, _STATUS_FILE)


def schedule_background_callback(
    key: str,
    callback: Callable[[], Any],
    *,
    reason: str = "",
    delay_sec: float = 0.8,
) -> str:
    """Schedule a coalesced daemon callback.

    Multiple rapid button clicks with the same key collapse into one background
    callback.  The foreground operation returns immediately after local work.
    """
    uid = enqueue_job("background_callback_scheduled", {"key": key}, reason=reason, status="scheduled")

    def _run() -> None:
        start = time.perf_counter()
        enqueue_job("background_callback_start", {"key": key, "source_uid": uid}, reason=reason, status="running")
        try:
            callback()
            elapsed = round(time.perf_counter() - start, 3)
            enqueue_job("background_callback_done", {"key": key, "source_uid": uid, "elapsed_sec": elapsed}, reason=reason, status="done")
            _write_status(last_done_key=key, last_done_reason=reason, last_done_elapsed_sec=elapsed, last_done_at=_now())
        except Exception as exc:
            elapsed = round(time.perf_counter() - start, 3)
            enqueue_job("background_callback_error", {"key": key, "source_uid": uid, "elapsed_sec": elapsed, "error": str(exc)[:1000]}, reason=reason, status="error")
            _write_status(last_error_key=key, last_error_reason=reason, last_error=str(exc)[:1000], last_error_at=_now())

    with _LOCK:
        old = _TIMERS.get(key)
        if old is not None:
            try:
                old.cancel()
            except Exception:
                pass
        timer = threading.Timer(max(0.05, float(delay_sec or 0.8)), _run)
        timer.daemon = True
        _TIMERS[key] = timer
        timer.start()
    return uid


def get_queue_status(max_lines: int = 500) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    try:
        if QUEUE_FILE.exists():
            lines = QUEUE_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-int(max_lines):]
            for line in lines:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        rows = []
    status: dict[str, Any] = {}
    try:
        if _STATUS_FILE.exists():
            status = json.loads(_STATUS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        status = {}
    return {
        "queue_file": str(QUEUE_FILE),
        "recent_count": len(rows),
        "scheduled_in_memory": len(_TIMERS),
        "status": status,
        "recent_rows": rows[-50:],
    }
