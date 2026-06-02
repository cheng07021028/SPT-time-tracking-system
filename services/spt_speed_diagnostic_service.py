# -*- coding: utf-8 -*-
"""
V257 SPT Speed Diagnostic Service

Only records timing data. It does not change UI, CSS, database behavior, or business logic.
Events are written to data/performance/performance_events.jsonl and can be reviewed from
99_效能診斷.py.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

try:
    from services.performance_profiler_service import record_event, read_events, summarize_events, write_summary_json
except Exception:  # pragma: no cover
    record_event = None  # type: ignore
    read_events = None  # type: ignore
    summarize_events = None  # type: ignore
    write_summary_json = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "data" / "performance"


def now_perf() -> float:
    return time.perf_counter()


def tick(category: str, name: str, start: float, *, threshold_ms: float = 200.0, detail: dict[str, Any] | None = None) -> float:
    duration_ms = (time.perf_counter() - start) * 1000.0
    if callable(record_event):
        try:
            record_event(category=category, name=name, duration_ms=duration_ms, ok=True, threshold_ms=threshold_ms, detail=detail or {})
        except Exception:
            pass
    return time.perf_counter()


def record(category: str, name: str, duration_ms: float, *, ok: bool = True, threshold_ms: float = 200.0, detail: dict[str, Any] | None = None, error: str = "") -> None:
    if callable(record_event):
        try:
            record_event(category=category, name=name, duration_ms=duration_ms, ok=ok, threshold_ms=threshold_ms, detail=detail or {}, error=error)
        except Exception:
            pass


def _safe_detail(args: tuple[Any, ...], kwargs: dict[str, Any], *, max_args: int = 3) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["args_count"] = len(args)
        out["kwargs"] = ",".join(sorted(str(k) for k in kwargs.keys()))[:200]
        for i, value in enumerate(args[:max_args]):
            text = str(value)
            if len(text) > 180:
                text = text[:180] + "..."
            out[f"arg{i}"] = text
    except Exception:
        pass
    return out


def wrap(func: Callable[..., Any], *, category: str, name: str | None = None, threshold_ms: float = 200.0, detail_factory: Callable[[tuple[Any, ...], dict[str, Any]], dict[str, Any]] | None = None) -> Callable[..., Any]:
    if not callable(func):
        return func
    if getattr(func, "__spt_v257_diag_wrapped__", False):
        return func
    label = name or getattr(func, "__name__", "unknown")

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        detail: dict[str, Any] = {}
        try:
            detail = detail_factory(args, kwargs) if callable(detail_factory) else _safe_detail(args, kwargs)
        except Exception as exc:
            detail = {"detail_error": str(exc)[:200]}
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000.0
            record(category, label, duration_ms, ok=True, threshold_ms=threshold_ms, detail=detail)
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            record(category, label, duration_ms, ok=False, threshold_ms=threshold_ms, detail=detail, error=str(exc)[:500])
            raise

    try:
        _wrapped.__name__ = getattr(func, "__name__", "wrapped")
        _wrapped.__doc__ = getattr(func, "__doc__", None)
        setattr(_wrapped, "__spt_v257_diag_wrapped__", True)
    except Exception:
        pass
    return _wrapped


def sql_detail(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    sql = str(args[0] if args else kwargs.get("sql", ""))
    low = " ".join(sql.lower().split())
    action = low.split(" ", 1)[0].upper() if low else "SQL"
    table = ""
    for marker in (" from ", " into ", " update ", " table "):
        idx = f" {low} ".find(marker)
        if idx >= 0:
            rest = f" {low} "[idx + len(marker):].strip()
            table = rest.split(" ", 1)[0].strip('"`[](),')
            break
    return {
        "sql_action": action,
        "sql_table": table,
        "sql_preview": sql[:500],
        "params_count": len(args[1]) if len(args) > 1 and hasattr(args[1], "__len__") else 0,
    }


def function_detail(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return _safe_detail(args, kwargs)


def build_summary(last_hours: float | None = 24, limit: int = 5000) -> dict[str, Any]:
    if not callable(read_events) or not callable(summarize_events):
        return {"error": "performance_profiler_service unavailable"}
    events = read_events(limit=limit, last_hours=last_hours)  # type: ignore[misc]
    return summarize_events(events, top_n=40)  # type: ignore[misc]


def write_report(last_hours: float | None = 24) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "spt_v257_speed_summary.json"
    if callable(write_summary_json):
        try:
            write_summary_json(path, limit=5000, last_hours=last_hours, top_n=50)  # type: ignore[misc]
            return path
        except Exception:
            pass
    summary = build_summary(last_hours=last_hours)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
