# -*- coding: utf-8 -*-
"""
V171 Performance Profiler Service

目的：只量測真正慢點，不改 UI、不改 CSS、不改資料流程。
- 預設只記錄超過門檻的慢函式，避免大量寫檔。
- JSONL 事件寫入 data/performance/performance_events.jsonl。
- 可由 tools/v171_performance_profiler_report.py 產生彙總報告。

環境變數：
- SPT_PERF_PROFILER=1/0           是否啟用，預設 1
- SPT_PERF_THRESHOLD_MS=300       預設慢事件門檻
- SPT_PERF_SAMPLE_ALL=0/1         是否記錄所有事件，預設 0
- SPT_PERF_MAX_BYTES=5242880      單一 JSONL 檔最大大小，預設 5MB
"""
from __future__ import annotations

import functools
import json
import os
import re
import threading
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERF_DIR = PROJECT_ROOT / "data" / "performance"
EVENT_PATH = PERF_DIR / "performance_events.jsonl"
_LOCK = threading.RLock()
_INSTALLED: set[str] = set()

_DEFAULT_THRESHOLD_MS = float(os.environ.get("SPT_PERF_THRESHOLD_MS", "300") or 300)
_MAX_BYTES = int(float(os.environ.get("SPT_PERF_MAX_BYTES", str(5 * 1024 * 1024)) or (5 * 1024 * 1024)))

_PASSWORD_KEYS = {"password", "new_password", "old_password", "pwd", "token", "secret", "github_token"}


def is_enabled() -> bool:
    val = str(os.environ.get("SPT_PERF_PROFILER", "1") or "1").strip().lower()
    return val not in {"0", "false", "no", "off", "disabled"}


def sample_all() -> bool:
    val = str(os.environ.get("SPT_PERF_SAMPLE_ALL", "0") or "0").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _now_text() -> str:
    # 不依賴 timezone_service，避免 profiler 造成循環 import。
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_text(value: Any, limit: int = 220) -> str:
    try:
        text = str(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _sanitize_dict(data: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (data or {}).items():
        key = str(k)
        if any(secret in key.lower() for secret in _PASSWORD_KEYS):
            out[key] = "***"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = _safe_text(v, 500) if isinstance(v, str) else v
        else:
            out[key] = _safe_text(v, 220)
    return out


def sql_summary(sql: Any) -> dict[str, Any]:
    text = _safe_text(sql, 800)
    low = " " + " ".join(text.lower().split()) + " "
    action = "SQL"
    for k in ("select", "insert", "update", "delete", "create", "alter", "pragma", "with"):
        if low.strip().startswith(k):
            action = k.upper()
            break
    table = ""
    patterns = [r"\bfrom\s+([\w_]+)", r"\binto\s+([\w_]+)", r"\bupdate\s+([\w_]+)", r"\btable\s+([\w_]+)"]
    for pat in patterns:
        m = re.search(pat, low)
        if m:
            table = m.group(1)
            break
    return {"sql_action": action, "sql_table": table, "sql_preview": text[:500]}


def _context() -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    # Streamlit 不一定存在；失敗就略過。
    try:
        import streamlit as st  # type: ignore
        ss = getattr(st, "session_state", {})
        user = ss.get("auth_username") or ss.get("username") or ss.get("current_user") or ss.get("user")
        if user:
            ctx["username"] = _safe_text(user, 120)
        page = ss.get("_spt_current_page") or ss.get("current_page")
        if page:
            ctx["page"] = _safe_text(page, 160)
    except Exception:
        pass
    try:
        ctx["pid"] = os.getpid()
        ctx["thread"] = threading.current_thread().name
    except Exception:
        pass
    return ctx


def _rotate_if_needed() -> None:
    try:
        if EVENT_PATH.exists() and EVENT_PATH.stat().st_size > _MAX_BYTES:
            backup = EVENT_PATH.with_suffix(".jsonl.1")
            try:
                if backup.exists():
                    backup.unlink()
            except Exception:
                pass
            EVENT_PATH.replace(backup)
    except Exception:
        pass


def record_event(
    *,
    category: str,
    name: str,
    duration_ms: float,
    ok: bool = True,
    threshold_ms: float | None = None,
    detail: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if not is_enabled():
        return
    threshold = float(threshold_ms if threshold_ms is not None else _DEFAULT_THRESHOLD_MS)
    if ok and not sample_all() and duration_ms < threshold:
        return
    event = {
        "ts": _now_text(),
        "epoch": time.time(),
        "category": str(category or "general"),
        "name": str(name or "unknown"),
        "duration_ms": round(float(duration_ms), 3),
        "threshold_ms": round(threshold, 3),
        "ok": bool(ok),
        "slow": bool(duration_ms >= threshold),
        "detail": _sanitize_dict(detail or {}),
        "error": _safe_text(error, 500) if error else "",
    }
    event.update(_context())
    try:
        PERF_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            _rotate_if_needed()
            with EVENT_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # profiler 永遠不能讓主系統掛掉
        pass


class profile:
    def __init__(self, category: str, name: str, threshold_ms: float | None = None, detail: dict[str, Any] | None = None):
        self.category = category
        self.name = name
        self.threshold_ms = threshold_ms
        self.detail = detail or {}
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        duration_ms = (time.perf_counter() - self.start) * 1000.0
        record_event(
            category=self.category,
            name=self.name,
            duration_ms=duration_ms,
            ok=exc is None,
            threshold_ms=self.threshold_ms,
            detail=self.detail,
            error="" if exc is None else _safe_text(exc, 500),
        )
        return False


def wrap_function(
    func: Callable[..., Any],
    *,
    category: str,
    name: str | None = None,
    threshold_ms: float | None = None,
    detail_factory: Callable[[tuple[Any, ...], dict[str, Any]], dict[str, Any]] | None = None,
) -> Callable[..., Any]:
    if not callable(func):
        return func
    if getattr(func, "__spt_v171_profiled__", False):
        return func
    func_name = name or getattr(func, "__name__", "unknown")
    threshold = float(threshold_ms if threshold_ms is not None else _DEFAULT_THRESHOLD_MS)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not is_enabled():
            return func(*args, **kwargs)
        detail: dict[str, Any] = {}
        if callable(detail_factory):
            try:
                detail = detail_factory(args, kwargs) or {}
            except Exception as exc:
                detail = {"detail_factory_error": _safe_text(exc, 200)}
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000.0
            record_event(category=category, name=func_name, duration_ms=duration_ms, ok=True, threshold_ms=threshold, detail=detail)
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            detail2 = dict(detail)
            try:
                detail2["traceback"] = "".join(traceback.format_exception_only(type(exc), exc))[:500]
            except Exception:
                pass
            record_event(category=category, name=func_name, duration_ms=duration_ms, ok=False, threshold_ms=threshold, detail=detail2, error=_safe_text(exc, 500))
            raise

    try:
        setattr(wrapper, "__spt_v171_profiled__", True)
        setattr(wrapper, "__spt_v171_profile_name__", func_name)
    except Exception:
        pass
    return wrapper


def mark_installed(key: str) -> bool:
    """Return True if this key was newly installed."""
    with _LOCK:
        if key in _INSTALLED:
            return False
        _INSTALLED.add(key)
        return True


def read_events(limit: int = 1000, last_hours: float | None = None) -> list[dict[str, Any]]:
    files = []
    if EVENT_PATH.with_suffix(".jsonl.1").exists():
        files.append(EVENT_PATH.with_suffix(".jsonl.1"))
    if EVENT_PATH.exists():
        files.append(EVENT_PATH)
    events: list[dict[str, Any]] = []
    cutoff = None
    if last_hours is not None:
        cutoff = time.time() - float(last_hours) * 3600.0
    try:
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for line in lines[-max(limit * 2, 2000):]:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if cutoff is not None and float(ev.get("epoch") or 0) < cutoff:
                    continue
                events.append(ev)
        events.sort(key=lambda x: float(x.get("epoch") or 0), reverse=True)
        return events[:limit]
    except Exception:
        return events[-limit:]


def summarize_events(events: Iterable[dict[str, Any]], top_n: int = 20) -> dict[str, Any]:
    evs = list(events)
    by_name: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "slow_count": 0, "error_count": 0})
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "slow_count": 0, "error_count": 0})
    tables = Counter()
    for ev in evs:
        dur = float(ev.get("duration_ms") or 0.0)
        name = str(ev.get("name") or "unknown")
        cat = str(ev.get("category") or "general")
        for bucket, key in ((by_name, name), (by_category, cat)):
            row = bucket[key]
            row["count"] += 1
            row["total_ms"] += dur
            row["max_ms"] = max(float(row["max_ms"]), dur)
            row["slow_count"] += 1 if ev.get("slow") else 0
            row["error_count"] += 1 if not ev.get("ok", True) else 0
        detail = ev.get("detail") or {}
        tbl = detail.get("sql_table") or detail.get("module_key") or detail.get("table")
        if tbl:
            tables[str(tbl)] += 1
    def finalize(bucket: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for key, row in bucket.items():
            count = int(row["count"] or 0)
            total = float(row["total_ms"] or 0)
            rows.append({
                "name": key,
                "count": count,
                "slow_count": int(row["slow_count"] or 0),
                "error_count": int(row["error_count"] or 0),
                "total_ms": round(total, 3),
                "avg_ms": round(total / count, 3) if count else 0,
                "max_ms": round(float(row["max_ms"] or 0), 3),
            })
        rows.sort(key=lambda r: (r["total_ms"], r["max_ms"], r["count"]), reverse=True)
        return rows[:top_n]
    top_events = sorted(evs, key=lambda x: float(x.get("duration_ms") or 0), reverse=True)[:top_n]
    return {
        "event_file": str(EVENT_PATH),
        "event_count": len(evs),
        "slow_count": sum(1 for e in evs if e.get("slow")),
        "error_count": sum(1 for e in evs if not e.get("ok", True)),
        "by_name": finalize(by_name),
        "by_category": finalize(by_category),
        "hot_tables_or_modules": [{"name": k, "count": v} for k, v in tables.most_common(top_n)],
        "top_events": top_events,
    }


def write_summary_json(path: str | Path, *, limit: int = 2000, last_hours: float | None = 24, top_n: int = 30) -> dict[str, Any]:
    events = read_events(limit=limit, last_hours=last_hours)
    summary = summarize_events(events, top_n=top_n)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
