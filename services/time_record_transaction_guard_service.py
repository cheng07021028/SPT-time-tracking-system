# -*- coding: utf-8 -*-
"""V178 time-record transaction guard and display consistency helpers.

This module is intentionally backend-only.  It does not import Streamlit and it
never changes CSS/theme/page rendering.  It provides:
- duplicate transaction guard for START/FINISH reruns;
- durable tombstones for deleted time records;
- filtered/deduplicated display frames so 01 Today Records and 02 History stay consistent.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from services.db_service import DB_PATH, query_df, query_one, clear_query_cache  # type: ignore
except Exception:  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"
    query_df = None  # type: ignore
    query_one = None  # type: ignore
    def clear_query_cache() -> None:  # type: ignore
        return None

try:
    from services.timezone_service import now_text, today_text, taiwan_now  # type: ignore
except Exception:  # pragma: no cover
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def today_text() -> str:
        return datetime.now().strftime("%Y-%m-%d")
    def taiwan_now():
        return datetime.now()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOMBSTONE_PATH = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "time_record_delete_tombstones" / "records.json"

TERMINAL_STATUSES = {"暫停", "下班", "完工", "已結束", "補登結束", "待人工確認"}
RECOVERY_SOURCES = {"V164B_LOG_ONLY_RECOVERY", "LOG_ONLY_RECOVERY", "LOGRECOVERY"}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def business_key(row: Any) -> str:
    r = dict(row) if isinstance(row, dict) else {}
    parts = [
        _clean(r.get("employee_id") or r.get("工號 / Employee ID") or r.get("工號")),
        _clean(r.get("employee_name") or r.get("姓名 / Name") or r.get("姓名")),
        _clean(r.get("work_order") or r.get("製令 / Work Order") or r.get("製令")),
        _clean(r.get("process_name") or r.get("工段 / Process") or r.get("工段")),
        _clean(r.get("start_timestamp") or r.get("開始時間 / Start Timestamp") or r.get("開始時間")),
    ]
    return "|".join(parts)


def row_identity(row: Any) -> dict[str, Any]:
    r = dict(row) if isinstance(row, dict) else {}
    return {
        "id": _safe_int(r.get("id")),
        "record_key": _clean(r.get("record_key")),
        "business_key": business_key(r),
    }


def _connect(timeout: int = 12) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def ensure_v178_schema() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS time_record_transaction_guard (
                op_key TEXT PRIMARY KEY,
                op_type TEXT,
                first_at TEXT,
                last_at TEXT,
                ttl_seconds INTEGER DEFAULT 10,
                status TEXT DEFAULT 'CLAIMED',
                result_id INTEGER,
                result_count INTEGER DEFAULT 0,
                hit_count INTEGER DEFAULT 0,
                payload TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trx_guard_type_time ON time_record_transaction_guard(op_type, last_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS time_record_delete_tombstones (
                tombstone_key TEXT PRIMARY KEY,
                record_id INTEGER,
                record_key TEXT,
                business_key TEXT,
                deleted_at TEXT,
                reason TEXT,
                source TEXT DEFAULT 'V178'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_tombstone_record_id ON time_record_delete_tombstones(record_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_tombstone_record_key ON time_record_delete_tombstones(record_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tr_tombstone_business_key ON time_record_delete_tombstones(business_key)")
        conn.commit()
    finally:
        conn.close()


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def start_op_key(employee: dict, work_order: dict, process_name: str, bucket_seconds: int = 8) -> str:
    now_bucket = int(time.time() // max(1, int(bucket_seconds)))
    parts = [
        "START_WORK",
        _clean((employee or {}).get("employee_id")),
        _clean((employee or {}).get("employee_name")),
        _clean((work_order or {}).get("work_order")),
        _clean(process_name),
        today_text(),
        str(now_bucket),
    ]
    return _hash_text("|".join(parts))


def finish_op_key(record_id: Any, end_action: str, bucket_seconds: int = 8) -> str:
    now_bucket = int(time.time() // max(1, int(bucket_seconds)))
    return _hash_text("|".join(["FINISH_WORK", _clean(record_id), _clean(end_action), str(now_bucket)]))


def claim_operation(op_type: str, op_key: str, ttl_seconds: int = 10, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {'claimed': True} if caller should execute; otherwise duplicate result."""
    ensure_v178_schema()
    now = now_text()
    payload_text = json.dumps(payload or {}, ensure_ascii=False, default=str)[:4000]
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM time_record_transaction_guard WHERE op_key=?", (op_key,)).fetchone()
        if row:
            r = dict(row)
            try:
                elapsed = (datetime.fromisoformat(now.replace("/", "-")) - datetime.fromisoformat(str(r.get("first_at") or now).replace("/", "-"))).total_seconds()
            except Exception:
                elapsed = 0
            if elapsed <= int(r.get("ttl_seconds") or ttl_seconds):
                conn.execute(
                    "UPDATE time_record_transaction_guard SET last_at=?, hit_count=COALESCE(hit_count,0)+1 WHERE op_key=?",
                    (now, op_key),
                )
                conn.commit()
                return {
                    "claimed": False,
                    "duplicate": True,
                    "status": r.get("status") or "CLAIMED",
                    "result_id": _safe_int(r.get("result_id")),
                    "result_count": _safe_int(r.get("result_count")),
                }
        conn.execute(
            """
            INSERT OR REPLACE INTO time_record_transaction_guard
            (op_key, op_type, first_at, last_at, ttl_seconds, status, result_id, result_count, hit_count, payload)
            VALUES (?, ?, ?, ?, ?, 'CLAIMED', NULL, 0, 0, ?)
            """,
            (op_key, op_type, now, now, int(ttl_seconds), payload_text),
        )
        conn.commit()
        return {"claimed": True, "duplicate": False, "status": "CLAIMED", "result_id": 0, "result_count": 0}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # Fail open: never block production work because the guard table is unavailable.
        return {"claimed": True, "duplicate": False, "status": "CLAIM_FAILED_OPEN", "result_id": 0, "result_count": 0}
    finally:
        conn.close()


def complete_operation(op_key: str, result_id: int = 0, result_count: int = 0, status: str = "DONE") -> None:
    try:
        ensure_v178_schema()
        conn = _connect()
        try:
            conn.execute(
                "UPDATE time_record_transaction_guard SET last_at=?, result_id=?, result_count=?, status=? WHERE op_key=?",
                (now_text(), int(result_id or 0), int(result_count or 0), status, op_key),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _read_tombstone_json() -> list[dict[str, Any]]:
    try:
        if TOMBSTONE_PATH.exists() and TOMBSTONE_PATH.stat().st_size > 0:
            data = json.loads(TOMBSTONE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows = data.get("tombstones") or data.get("records") or []
                return [dict(x) for x in rows if isinstance(x, dict)]
            if isinstance(data, list):
                return [dict(x) for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _write_tombstone_json(rows: list[dict[str, Any]]) -> None:
    try:
        TOMBSTONE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": "V178", "updated_at": now_text(), "tombstones": rows}
        tmp = TOMBSTONE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, TOMBSTONE_PATH)
    except Exception:
        pass


def load_tombstones() -> dict[str, set[str]]:
    ensure_v178_schema()
    by_id: set[str] = set()
    by_record_key: set[str] = set()
    by_business_key: set[str] = set()
    try:
        conn = _connect()
        try:
            for row in conn.execute("SELECT record_id, record_key, business_key FROM time_record_delete_tombstones"):
                rid = _clean(row[0])
                rk = _clean(row[1])
                bk = _clean(row[2])
                if rid and rid != "0":
                    by_id.add(rid)
                if rk:
                    by_record_key.add(rk)
                if bk and bk != "||||":
                    by_business_key.add(bk)
        finally:
            conn.close()
    except Exception:
        pass
    for r in _read_tombstone_json():
        rid = _clean(r.get("record_id"))
        rk = _clean(r.get("record_key"))
        bk = _clean(r.get("business_key"))
        if rid and rid != "0":
            by_id.add(rid)
        if rk:
            by_record_key.add(rk)
        if bk and bk != "||||":
            by_business_key.add(bk)
    return {"ids": by_id, "record_keys": by_record_key, "business_keys": by_business_key}


def is_tombstoned(row: Any, tombstones: dict[str, set[str]] | None = None) -> bool:
    ts = tombstones or load_tombstones()
    ident = row_identity(row)
    rid = _clean(ident.get("id"))
    rk = _clean(ident.get("record_key"))
    bk = _clean(ident.get("business_key"))
    if rid and rid != "0" and rid in ts.get("ids", set()):
        return True
    if rk and rk in ts.get("record_keys", set()):
        return True
    if bk and bk != "||||" and bk in ts.get("business_keys", set()):
        return True
    return False


def add_tombstones(rows: Iterable[Any], reason: str = "管理員刪除工時紀錄") -> int:
    ensure_v178_schema()
    clean_rows = []
    now = now_text()
    for row in rows or []:
        r = dict(row) if isinstance(row, dict) else {}
        ident = row_identity(r)
        if not (ident.get("id") or ident.get("record_key") or ident.get("business_key")):
            continue
        key = _hash_text("|".join([_clean(ident.get("id")), _clean(ident.get("record_key")), _clean(ident.get("business_key"))]))
        clean_rows.append({
            "tombstone_key": key,
            "record_id": int(ident.get("id") or 0),
            "record_key": ident.get("record_key") or "",
            "business_key": ident.get("business_key") or "",
            "deleted_at": now,
            "reason": reason,
            "source": "V178",
        })
    if not clean_rows:
        return 0
    conn = _connect()
    written = 0
    try:
        conn.execute("BEGIN")
        for r in clean_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO time_record_delete_tombstones
                (tombstone_key, record_id, record_key, business_key, deleted_at, reason, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (r["tombstone_key"], r["record_id"], r["record_key"], r["business_key"], r["deleted_at"], r["reason"], r["source"]),
            )
            written += 1
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
    # Mirror to JSON for authority-layer durability.
    old = _read_tombstone_json()
    merged: dict[str, dict[str, Any]] = {}
    for r in old + clean_rows:
        key = _clean(r.get("tombstone_key")) or _hash_text("|".join([_clean(r.get("record_id")), _clean(r.get("record_key")), _clean(r.get("business_key"))]))
        merged[key] = dict(r, tombstone_key=key)
    _write_tombstone_json(list(merged.values()))
    try:
        clear_query_cache()
    except Exception:
        pass
    return written


def rows_by_ids(record_ids: Iterable[Any]) -> list[dict[str, Any]]:
    ids: list[int] = []
    for x in record_ids or []:
        i = _safe_int(x)
        if i > 0 and i not in ids:
            ids.append(i)
    if not ids:
        return []
    rows: list[dict[str, Any]] = []
    placeholders = ",".join(["?"] * len(ids))
    try:
        if query_df is not None:
            df = query_df(f"SELECT * FROM time_records WHERE id IN ({placeholders})", ids)
            if isinstance(df, pd.DataFrame) and not df.empty:
                rows.extend(df.to_dict("records"))
    except Exception:
        pass
    try:
        from services.permanent_authority_service import df_from_table  # type: ignore
        for module in ("02_history", "01_time_records"):
            df2 = df_from_table(module, "time_records")
            if isinstance(df2, pd.DataFrame) and not df2.empty and "id" in df2.columns:
                id_series = pd.to_numeric(df2["id"], errors="coerce").fillna(-1).astype(int)
                sub = df2.loc[id_series.isin(ids)]
                if not sub.empty:
                    rows.extend(sub.to_dict("records"))
    except Exception:
        pass
    # Deduplicate evidence rows.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        ident = row_identity(r)
        key = "|".join([_clean(ident.get("id")), _clean(ident.get("record_key")), _clean(ident.get("business_key"))])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def purge_tombstoned_from_sqlite() -> int:
    ts = load_tombstones()
    clauses: list[str] = []
    params: list[Any] = []
    ids = [int(x) for x in ts.get("ids", set()) if str(x).isdigit()]
    if ids:
        clauses.append("id IN (" + ",".join(["?"] * len(ids)) + ")")
        params.extend(ids)
    rks = [x for x in ts.get("record_keys", set()) if x]
    if rks:
        clauses.append("record_key IN (" + ",".join(["?"] * len(rks)) + ")")
        params.extend(rks)
    bks = [x for x in ts.get("business_keys", set()) if x and x != "||||"]
    # Avoid huge SQL for very large tombstone files.
    bks = bks[-1000:]
    deleted = 0
    conn = _connect()
    try:
        if clauses:
            cur = conn.execute("DELETE FROM time_records WHERE " + " OR ".join(clauses), tuple(params))
            deleted += int(cur.rowcount or 0)
        # Business key purge is slower; keep bounded but effective.
        for bk in bks:
            parts = bk.split("|", 4)
            if len(parts) != 5:
                continue
            cur = conn.execute(
                """
                DELETE FROM time_records
                WHERE COALESCE(employee_id,'')=? AND COALESCE(employee_name,'')=?
                  AND COALESCE(work_order,'')=? AND COALESCE(process_name,'')=?
                  AND COALESCE(start_timestamp,'')=?
                """,
                tuple(parts),
            )
            deleted += int(cur.rowcount or 0)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
    try:
        clear_query_cache()
    except Exception:
        pass
    return deleted


def filter_tombstoned_df(df: Any) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    ts = load_tombstones()
    try:
        mask = df.apply(lambda r: not is_tombstoned(dict(r), ts), axis=1)
        return df.loc[mask].copy().reset_index(drop=True)
    except Exception:
        return df


def _terminal_score(row: dict[str, Any]) -> int:
    status = _clean(row.get("status"))
    end_ts = _clean(row.get("end_timestamp"))
    wh = _clean(row.get("work_hours"))
    score = 0
    if status in TERMINAL_STATUSES:
        score += 5
    if end_ts:
        score += 4
    if wh and wh not in {"0", "0.0", "00:00:00"}:
        score += 2
    src = _clean(row.get("source"))
    if src in RECOVERY_SOURCES or src.startswith("LOGRECOVERY"):
        score -= 5
    return score


def dedupe_display_df(df: Any) -> pd.DataFrame:
    """Display-level dedupe only.  Does not delete records."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    x = df.copy()
    try:
        if "__v178_bkey" not in x.columns:
            x["__v178_bkey"] = x.apply(lambda r: business_key(dict(r)), axis=1)
        x["__v178_score"] = x.apply(lambda r: _terminal_score(dict(r)), axis=1)
        if "id" in x.columns:
            x["__v178_id_num"] = pd.to_numeric(x["id"], errors="coerce").fillna(0)
        else:
            x["__v178_id_num"] = 0
        # First collapse duplicate record_key; then collapse exact business duplicate.
        if "record_key" in x.columns:
            x["__v178_rk"] = x["record_key"].map(_clean)
            has_rk = x["__v178_rk"] != ""
            rk_part = x.loc[has_rk].sort_values(["__v178_rk", "__v178_score", "__v178_id_num"], ascending=[True, False, False]).drop_duplicates("__v178_rk", keep="first")
            no_rk = x.loc[~has_rk]
            x = pd.concat([rk_part, no_rk], ignore_index=True)
        x = x.sort_values(["__v178_bkey", "__v178_score", "__v178_id_num"], ascending=[True, False, False])
        # Only collapse non-empty full business keys. Empty keys are left untouched.
        non_empty = x["__v178_bkey"].astype(str) != "||||"
        b_part = x.loc[non_empty].drop_duplicates("__v178_bkey", keep="first")
        empty_part = x.loc[~non_empty]
        out = pd.concat([b_part, empty_part], ignore_index=True)
        sort_col = "id" if "id" in out.columns else "__v178_id_num"
        try:
            out["__v178_sort"] = pd.to_numeric(out[sort_col], errors="coerce").fillna(0)
            out = out.sort_values("__v178_sort", ascending=False)
        except Exception:
            pass
        drop_cols = [c for c in out.columns if str(c).startswith("__v178_")]
        return out.drop(columns=drop_cols, errors="ignore").reset_index(drop=True)
    except Exception:
        return df


def filter_and_dedupe_df(df: Any) -> pd.DataFrame:
    return dedupe_display_df(filter_tombstoned_df(df))


def active_row_is_safe(row: Any) -> bool:
    r = dict(row) if isinstance(row, dict) else {}
    source = _clean(r.get("source"))
    record_key = _clean(r.get("record_key"))
    status = _clean(r.get("status"))
    end_ts = _clean(r.get("end_timestamp"))
    if is_tombstoned(r):
        return False
    if source in RECOVERY_SOURCES or record_key.startswith("LOGRECOVERY|"):
        # LOG-only recovery is not a normal active work row until V166B manual close confirms it.
        return False
    if status and status != "作業中":
        return False
    if end_ts:
        return False
    return True


def filter_active_df(df: Any) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    try:
        mask = df.apply(lambda r: active_row_is_safe(dict(r)), axis=1)
        return filter_and_dedupe_df(df.loc[mask].copy())
    except Exception:
        return filter_and_dedupe_df(df)


def audit_v178_state() -> dict[str, Any]:
    ensure_v178_schema()
    out: dict[str, Any] = {"ok": True, "version": "V178"}
    try:
        conn = _connect()
        try:
            out["transaction_guard_rows"] = int(conn.execute("SELECT COUNT(*) FROM time_record_transaction_guard").fetchone()[0])
            out["tombstone_rows_sqlite"] = int(conn.execute("SELECT COUNT(*) FROM time_record_delete_tombstones").fetchone()[0])
            try:
                out["time_records_rows_sqlite"] = int(conn.execute("SELECT COUNT(*) FROM time_records").fetchone()[0])
            except Exception as exc:
                # Some smoke-test environments have not initialized the app database yet.
                out["time_records_rows_sqlite"] = None
                out["time_records_note"] = str(exc)[:200]
        finally:
            conn.close()
    except Exception as exc:
        out["ok"] = False
        out["sqlite_error"] = str(exc)[:300]
    out["tombstone_rows_json"] = len(_read_tombstone_json())
    return out


def lookup_operation(op_key: str) -> dict[str, Any]:
    try:
        ensure_v178_schema()
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM time_record_transaction_guard WHERE op_key=?", (op_key,)).fetchone()
            if not row:
                return {}
            r = dict(row)
            return {
                "status": r.get("status") or "",
                "result_id": _safe_int(r.get("result_id")),
                "result_count": _safe_int(r.get("result_count")),
                "hit_count": _safe_int(r.get("hit_count")),
                "first_at": r.get("first_at") or "",
                "last_at": r.get("last_at") or "",
            }
        finally:
            conn.close()
    except Exception:
        return {}
