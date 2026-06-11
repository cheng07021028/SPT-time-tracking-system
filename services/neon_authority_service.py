# -*- coding: utf-8 -*-
"""Neon authority helpers for the original SPT UI.

This is the compatibility layer that lets old pages keep their UI while moving
formal module/settings/audit persistence to PostgreSQL/Neon as the single source
of truth. Local JSON is only used when DATABASE_URL is not configured.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any




# ===== V300.55 Neon authority transient-shutdown guard =====
# Neon Free can scale to zero or restart a compute.  During that short window
# psycopg may raise AdminShutdown / connection-terminated errors.  Authority
# settings such as 05 analysis filters must not crash the whole page, and schema
# DDL must not run on every save.  Keep an in-process schema guard and retry only
# transient PostgreSQL connection failures.
_V30055_SCHEMA_READY = False
_V30055_SCHEMA_LAST_ERROR = ""


def _v30055_is_transient_pg_error(exc: Exception) -> bool:
    text = f"{type(exc).__module__}.{type(exc).__name__}: {exc}".lower()
    markers = (
        "adminshutdown",
        "admin shutdown",
        "terminating connection",
        "server closed the connection",
        "connection is closed",
        "connection already closed",
        "could not receive data from server",
        "could not send data to server",
        "ssl syscall error",
        "connection reset",
        "connection refused",
        "the database system is shutting down",
        "the database system is starting up",
        "operationalerror",
    )
    return any(m in text for m in markers)


def _v30055_reset_pg_connection() -> None:
    try:
        from services import db_service as _db
        close_fn = getattr(_db, "_v29_pg_close_cached_connection", None)
        if callable(close_fn):
            close_fn()
    except Exception:
        pass


def _v30055_retry_pg(fn, *, attempts: int = 3, base_sleep: float = 0.18):
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not _v30055_is_transient_pg_error(exc) or attempt >= max(1, attempts) - 1:
                raise
            _v30055_reset_pg_connection()
            try:
                time.sleep(base_sleep * (attempt + 1))
            except Exception:
                pass
    if last_exc:
        raise last_exc
    return None


def _v30055_safe_local_mirror(module_key: str, kind: str, payload: Any, user: str = "SYSTEM") -> None:
    """Best-effort local fallback/cache only.  Neon remains the authority."""
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        safe_module = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(module_key)) or "module"
        safe_kind = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(kind)) or "payload"
        path = root / "data" / "permanent_store" / "neon_transient_fallback" / safe_module / f"{safe_kind}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dumps({"payload": payload, "updated_at": now_text(), "updated_by": str(user or "SYSTEM"), "note": "temporary local fallback after transient Neon error"}), encoding="utf-8")
    except Exception:
        pass


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_default(value: Any) -> Any:
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def is_neon_enabled() -> bool:
    try:
        from services.db_service import is_postgres_enabled
        return bool(is_postgres_enabled())
    except Exception:
        return False


def ensure_neon_authority_schema() -> None:
    """Create additive generic authority tables in Neon.

    V300.55: run this DDL once per Streamlit worker process and retry transient
    Neon AdminShutdown / connection-closed events.  Do not execute CREATE/ALTER
    on every settings save; that wastes Neon compute and can surface scale-to-zero
    restarts to the user.
    """
    global _V30055_SCHEMA_READY, _V30055_SCHEMA_LAST_ERROR
    if not is_neon_enabled():
        return
    if _V30055_SCHEMA_READY:
        return
    from services import db_service as _db

    def _ensure_once() -> None:
        global _V30055_SCHEMA_READY, _V30055_SCHEMA_LAST_ERROR
        with _db._v25_pg_connect() as conn:  # type: ignore[attr-defined]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS spt_module_authority (
                        module_key TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT,
                        updated_by TEXT,
                        PRIMARY KEY (module_key, kind)
                    )
                    """
                )
                for col, ddl in (
                    ("kind", "TEXT DEFAULT 'records'"),
                    ("payload", "TEXT DEFAULT '{}'"),
                    ("updated_at", "TEXT"),
                    ("updated_by", "TEXT"),
                    ("deleted_at", "TEXT"),
                    ("created_at", "TEXT"),
                    ("record_key", "TEXT"),
                    ("table_name", "TEXT"),
                ):
                    try:
                        cur.execute(f"ALTER TABLE spt_module_authority ADD COLUMN IF NOT EXISTS {col} {ddl}")
                    except Exception:
                        pass
                try:
                    cur.execute("UPDATE spt_module_authority SET kind=COALESCE(NULLIF(kind,''), NULLIF(table_name,''), 'records') WHERE kind IS NULL OR kind=''")
                except Exception:
                    pass
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS spt_module_authority_audit (
                        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                        event_time TEXT,
                        module_key TEXT,
                        action TEXT,
                        username TEXT,
                        result TEXT,
                        message TEXT,
                        detail TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS spt_system_json_store (
                        name TEXT PRIMARY KEY,
                        payload TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT
                    )
                    """
                )
                # Soft-delete / tombstone compatible columns for log-like tables.
                for table in ("system_logs", "auth_login_logs", "security_login_logs", "time_records"):
                    for col, ddl in (
                        ("deleted_at", "TEXT"),
                        ("deleted_by", "TEXT"),
                        ("delete_reason", "TEXT"),
                    ):
                        try:
                            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}")
                        except Exception:
                            pass
                cur.execute("CREATE INDEX IF NOT EXISTS idx_spt_module_authority_kind ON spt_module_authority(kind)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_spt_module_authority_audit_module_time ON spt_module_authority_audit(module_key, event_time)")
            conn.commit()
        _V30055_SCHEMA_READY = True
        _V30055_SCHEMA_LAST_ERROR = ""

    try:
        _v30055_retry_pg(_ensure_once, attempts=3)
    except Exception as exc:
        _V30055_SCHEMA_LAST_ERROR = str(exc)
        raise

def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def _loads(text: Any, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(str(text))
    except Exception:
        return default


def load_payload(module_key: str, kind: str, default: Any = None) -> Any:
    if not is_neon_enabled():
        return default
    try:
        ensure_neon_authority_schema()
        from services.db_service import query_one

        row = query_one(
            "SELECT payload FROM spt_module_authority WHERE module_key=? AND kind=?",
            (str(module_key), str(kind)),
        )
        if not row:
            return default
        return _loads(row.get("payload"), default)
    except Exception as exc:
        if _v30055_is_transient_pg_error(exc):
            return default
        raise


def save_payload(module_key: str, kind: str, payload: Any, user: str = "SYSTEM") -> dict[str, Any]:
    if not is_neon_enabled():
        return {"ok": False, "skipped": True, "reason": "postgres_disabled"}
    try:
        ensure_neon_authority_schema()
        from services.db_service import execute

        # V300.55: one UPSERT instead of UPDATE then INSERT.  This reduces Neon
        # writes and avoids a race if two users save the same settings together.
        execute(
            """
            INSERT INTO spt_module_authority(module_key, kind, payload, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (module_key, kind) DO UPDATE
            SET payload=EXCLUDED.payload,
                updated_at=EXCLUDED.updated_at,
                updated_by=EXCLUDED.updated_by,
                deleted_at=NULL
            """,
            (str(module_key), str(kind), _dumps(payload), now_text(), str(user or "SYSTEM")),
        )
        return {"ok": True, "backend": "neon", "module_key": str(module_key), "kind": str(kind)}
    except Exception as exc:
        if _v30055_is_transient_pg_error(exc):
            _v30055_safe_local_mirror(str(module_key), str(kind), payload, user=user)
            return {"ok": False, "backend": "neon", "transient": True, "reason": type(exc).__name__, "message": str(exc)}
        raise


def load_system_payload(name: str, default: Any = None) -> Any:
    if not is_neon_enabled():
        return default
    try:
        ensure_neon_authority_schema()
        from services.db_service import query_one

        row = query_one("SELECT payload FROM spt_system_json_store WHERE name=?", (str(name),))
        if not row:
            return default
        return _loads(row.get("payload"), default)
    except Exception as exc:
        if _v30055_is_transient_pg_error(exc):
            return default
        raise


def save_system_payload(name: str, payload: Any) -> dict[str, Any]:
    if not is_neon_enabled():
        return {"ok": False, "skipped": True, "reason": "postgres_disabled"}
    try:
        ensure_neon_authority_schema()
        from services.db_service import execute

        execute(
            """
            INSERT INTO spt_system_json_store(name, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at
            """,
            (str(name), _dumps(payload), now_text()),
        )
        return {"ok": True, "backend": "neon", "name": str(name)}
    except Exception as exc:
        if _v30055_is_transient_pg_error(exc):
            return {"ok": False, "backend": "neon", "transient": True, "reason": type(exc).__name__, "message": str(exc)}
        raise


def append_audit(module_key: str, action: str, username: str = "SYSTEM", result: str = "OK", message: str = "", detail: Any = None) -> None:
    if not is_neon_enabled():
        return
    try:
        ensure_neon_authority_schema()
        from services.db_service import execute

        execute(
            """
            INSERT INTO spt_module_authority_audit(event_time, module_key, action, username, result, message, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now_text(), str(module_key), str(action), str(username or "SYSTEM"), str(result), str(message or ""), _dumps(detail or {})),
        )
    except Exception as exc:
        if _v30055_is_transient_pg_error(exc):
            return
        raise


def authority_status() -> dict[str, Any]:
    if not is_neon_enabled():
        return {"backend": "local", "postgres_enabled": False}
    try:
        ensure_neon_authority_schema()
        from services.db_service import query_df

        df = query_df(
            """
            SELECT module_key, kind, updated_at, updated_by, length(payload) AS payload_bytes
            FROM spt_module_authority
            ORDER BY module_key, kind
            """
        )
        rows = df.to_dict("records") if df is not None and not df.empty else []
        return {"backend": "neon", "postgres_enabled": True, "rows": rows, "count": len(rows)}
    except Exception as exc:
        if _v30055_is_transient_pg_error(exc):
            return {"backend": "neon", "postgres_enabled": True, "transient_error": True, "message": str(exc), "rows": [], "count": 0}
        raise


def audit_v30055_neon_authority_admin_shutdown_guard() -> dict[str, Any]:
    return {
        "version": "V300.55_NEON_AUTHORITY_ADMIN_SHUTDOWN_GUARD",
        "schema_process_guard": True,
        "transient_retry": True,
        "save_payload_upsert": True,
        "admin_shutdown_safe": True,
        "schema_ready": bool(_V30055_SCHEMA_READY),
        "last_schema_error": str(_V30055_SCHEMA_LAST_ERROR or ""),
    }
