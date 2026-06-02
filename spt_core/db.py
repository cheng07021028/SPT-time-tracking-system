from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .utils import ensure_parent


_PARAM_RE = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
_POOL = None
_SCHEMA_READY = False


def load_env_file() -> None:
    """Small .env loader so local usage does not require python-dotenv at import time."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def database_url() -> str:
    load_env_file()
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    return "sqlite:///data/spt_local_demo.db"


def backend() -> str:
    url = database_url()
    if url.startswith(("postgresql://", "postgres://")):
        return "postgres"
    if url.startswith("sqlite://"):
        return "sqlite"
    raise RuntimeError("DATABASE_URL must start with postgresql://, postgres://, or sqlite://")


def current_database_label() -> str:
    if backend() == "postgres":
        parsed = urlparse(database_url())
        return f"PostgreSQL / Neon：{parsed.hostname or 'configured'}"
    return "SQLite Demo（非正式多人權威資料庫）"


def _sqlite_path(url: str) -> str:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError("Invalid sqlite DATABASE_URL")
    path = url[len(prefix):]
    if path == ":memory:":
        return path
    ensure_parent(path)
    return path


def _sqlite_connect():
    conn = sqlite3.connect(_sqlite_path(database_url()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _postgres_pool():
    global _POOL
    if _POOL is None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except Exception as exc:
            raise RuntimeError(
                "PostgreSQL mode requires psycopg[binary,pool]. Run: pip install -r requirements.txt"
            ) from exc
        _POOL = ConnectionPool(conninfo=database_url(), min_size=1, max_size=int(os.getenv("SPT_DB_POOL_SIZE", "5")), kwargs={"row_factory": dict_row})
    return _POOL


@contextmanager
def get_connection():
    if backend() == "postgres":
        with _postgres_pool().connection() as conn:
            yield conn
    else:
        conn = _sqlite_connect()
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def transaction():
    with get_connection() as conn:
        try:
            if backend() == "sqlite":
                conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def translate_sql(sql: str) -> str:
    if backend() == "postgres":
        return _PARAM_RE.sub(lambda m: f"%({m.group(1)})s", sql)
    return sql


def execute(conn, sql: str, params: dict[str, Any] | None = None):
    return conn.execute(translate_sql(sql), params or {})


def executemany(conn, sql: str, rows: Iterable[dict[str, Any]]):
    if backend() == "postgres":
        with conn.cursor() as cur:
            cur.executemany(translate_sql(sql), list(rows))
            return cur
    return conn.executemany(translate_sql(sql), list(rows))


def row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def fetch_one(conn, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cur = execute(conn, sql, params)
    return row_to_dict(cur.fetchone())


def fetch_all(conn, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cur = execute(conn, sql, params)
    return [row_to_dict(row) for row in cur.fetchall()]


def scalar(conn, sql: str, params: dict[str, Any] | None = None) -> Any:
    row = fetch_one(conn, sql, params)
    if not row:
        return None
    return next(iter(row.values()))


def init_db() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    from .schema import create_schema
    from .seed import seed_minimum_data

    with transaction() as conn:
        create_schema(conn)
        seed_minimum_data(conn)
    _SCHEMA_READY = True


def reset_for_tests() -> None:
    global _POOL, _SCHEMA_READY
    _SCHEMA_READY = False
    if _POOL is not None:
        try:
            _POOL.close()
        except Exception:
            pass
    _POOL = None
