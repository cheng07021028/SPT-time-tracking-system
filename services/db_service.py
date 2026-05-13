# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable, Any
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "data" / "database"
DB_PATH = DB_DIR / "spt_time_tracking.db"


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with get_connection() as conn:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.lastrowid


def executemany(sql: str, rows: list[Iterable[Any]]) -> None:
    with get_connection() as conn:
        conn.executemany(sql, rows)
        conn.commit()


def query_df(sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=tuple(params))


def query_one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None
