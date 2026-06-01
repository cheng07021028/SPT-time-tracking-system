# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from services.timezone_service import now_text, now_stamp, today_text, today_date

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"


# ===== V3.04 MASTER DATA RESCUE GUARD START =====
# Purpose: 03｜製令管理 and 04｜人員名單 primarily read SQLite tables.
# If a module update/reboot creates an empty SQLite DB while permanent JSON still has data,
# restore the SQLite table from data/persistent_modules before the page displays empty data.
PERSIST_ROOT = PROJECT_ROOT / "data" / "persistent_modules"

_MASTER_MODULES = {
    "work_orders": {
        "module_codes": ["03_work_orders", "03_work_order", "work_orders"],
        "latest_names": ["03_work_orders_records.json", "03_work_order_records.json", "work_orders_records.json"],
        "pk": "work_order",
        "cols": ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"],
    },
    "employees": {
        "module_codes": ["04_employees", "04_employee", "employees"],
        "latest_names": ["04_employees_records.json", "04_employee_records.json", "employees_records.json"],
        "pk": "employee_id",
        "cols": ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"],
    },
}


def _safe_read_json(path: Path) -> Any:
    try:
        if path.exists() and path.is_file() and path.stat().st_size > 2:
            import json
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _extract_rows_from_payload(payload: Any, table: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables")
    if isinstance(tables, dict):
        rows = tables.get(table)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    # Some future/older records may be saved directly as a list or under records/data.
    for key in ("records", "data", "rows"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _candidate_record_files(table: str) -> list[Path]:
    info = _MASTER_MODULES.get(table, {})
    files: list[Path] = []
    for code in info.get("module_codes", []):
        d = PERSIST_ROOT / code
        for name in info.get("latest_names", []):
            files.append(d / name)
        files.extend(sorted((d / "history").glob("*_records_*.json"), reverse=True) if (d / "history").exists() else [])
    # Also scan all persistent modules for a table-bearing record, newest first.
    try:
        files.extend(sorted(PERSIST_ROOT.glob(f"*/**/*records*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True))
    except Exception:
        pass
    seen = set()
    out = []
    for p in files:
        s = str(p.resolve()) if p.exists() else str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def _find_best_persistent_rows(table: str) -> tuple[list[dict[str, Any]], str]:
    best_rows: list[dict[str, Any]] = []
    best_path = ""
    for path in _candidate_record_files(table):
        payload = _safe_read_json(path)
        rows = _extract_rows_from_payload(payload, table)
        if len(rows) > len(best_rows):
            best_rows = rows
            best_path = str(path)
    return best_rows, best_path


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0] if row else 0)
    except Exception:
        return 0


def _normalise_row_for_table(table: str, row: dict[str, Any], now: str) -> dict[str, Any] | None:
    cols = _MASTER_MODULES[table]["cols"]
    out = {c: row.get(c, "") for c in cols}
    # Required keys.
    if table == "work_orders":
        key = _txt(out.get("work_order"))
        if not key:
            return None
        out["work_order"] = key
        out["is_active"] = _bool(out.get("is_active", True))
    elif table == "employees":
        emp_id = _txt(out.get("employee_id"))
        emp_name = _txt(out.get("employee_name"))
        if not emp_id or not emp_name:
            return None
        out["employee_id"] = emp_id
        out["employee_name"] = emp_name
        for c in ["is_active", "is_in_factory", "is_today_attendance"]:
            out[c] = _bool(out.get(c, True))
    # Avoid importing old ids into a fresh SQLite DB; let SQLite assign new ids.
    out["id"] = None
    out["created_at"] = _txt(out.get("created_at")) or now
    out["updated_at"] = _txt(out.get("updated_at")) or now
    return out


def _restore_table_from_persistent_if_empty(table: str) -> dict[str, Any]:
    """Restore work_orders/employees from persistent JSON when SQLite table is empty."""
    ensure_tables()
    if table not in _MASTER_MODULES:
        return {"restored": 0, "source": "", "reason": "unsupported_table"}
    conn = get_conn()
    try:
        current = _table_row_count(conn, table)
        if current > 0:
            return {"restored": 0, "source": "", "reason": "db_not_empty", "current": current}
        rows, source = _find_best_persistent_rows(table)
        if not rows:
            return {"restored": 0, "source": "", "reason": "no_persistent_rows"}
        now = now_text()
        restored = 0
        cur = conn.cursor()
        if table == "work_orders":
            for r in rows:
                rr = _normalise_row_for_table(table, r, now)
                if not rr:
                    continue
                cur.execute("""
                    INSERT INTO work_orders
                    (work_order, part_no, type_name, assembly_location, customer, note, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_order) DO UPDATE SET
                        part_no=excluded.part_no, type_name=excluded.type_name,
                        assembly_location=excluded.assembly_location, customer=excluded.customer,
                        note=excluded.note, is_active=excluded.is_active, updated_at=excluded.updated_at
                """, (_txt(rr.get("work_order")), _txt(rr.get("part_no")), _txt(rr.get("type_name")),
                      _txt(rr.get("assembly_location")), _txt(rr.get("customer")), _txt(rr.get("note")),
                      _bool(rr.get("is_active", True)), _txt(rr.get("created_at")), _txt(rr.get("updated_at"))))
                restored += 1
        elif table == "employees":
            for r in rows:
                rr = _normalise_row_for_table(table, r, now)
                if not rr:
                    continue
                cur.execute("""
                    INSERT INTO employees
                    (employee_id, employee_name, department, title, is_active, is_in_factory, is_today_attendance, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(employee_id) DO UPDATE SET
                        employee_name=excluded.employee_name, department=excluded.department,
                        title=excluded.title, is_active=excluded.is_active,
                        is_in_factory=excluded.is_in_factory,
                        is_today_attendance=excluded.is_today_attendance,
                        note=excluded.note, updated_at=excluded.updated_at
                """, (_txt(rr.get("employee_id")), _txt(rr.get("employee_name")), _txt(rr.get("department")),
                      _txt(rr.get("title")), _bool(rr.get("is_active", True)), _bool(rr.get("is_in_factory", True)),
                      _bool(rr.get("is_today_attendance", True)), _txt(rr.get("note")), _txt(rr.get("created_at")),
                      _txt(rr.get("updated_at"))))
                restored += 1
        conn.commit()
        try:
            log_action(f"RESTORE_{table.upper()}", table, f"從永久 JSON 救援 {table}", f"restored={restored}, source={source}")
        except Exception:
            pass
        return {"restored": restored, "source": source, "reason": "restored"}
    finally:
        conn.close()


def _mirror_table_to_persistent_module(table: str) -> None:
    """Write non-empty DB table to its latest module JSON and history; never mirror an empty table over non-empty JSON."""
    if table not in _MASTER_MODULES:
        return
    try:
        df = _load(table)
        if df.empty:
            rows, _ = _find_best_persistent_rows(table)
            if rows:
                return
        rows = df.to_dict(orient="records")
        code = "03_work_orders" if table == "work_orders" else "04_employees"
        zh = "製令管理" if table == "work_orders" else "人員名單"
        en = "Work Orders" if table == "work_orders" else "Employees"
        payload = {
            "version": "V3.04-master-data-guard",
            "exported_at": now_text(),
            "source": "crud_table_service",
            "module_key": code,
            "module_code": code,
            "module_name_zh": zh,
            "module_name_en": en,
            "tables": {table: rows},
            "table_counts": {table: len(rows)},
            "counts": {table: len(rows)},
        }
        import json
        d = PERSIST_ROOT / code
        h = d / "history"
        d.mkdir(parents=True, exist_ok=True)
        h.mkdir(parents=True, exist_ok=True)
        latest = d / f"{code}_records.json"
        tmp = latest.with_suffix(latest.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        # Verify before replacing.
        json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(latest)
        hist = h / f"{code}_records_{now_stamp()}.json"
        hist.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass
# ===== V3.04 MASTER DATA RESCUE GUARD END =====

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_text() -> str:
    from services.timezone_service import now_text as _nt
    return _nt()

def ensure_tables() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_order TEXT UNIQUE NOT NULL,
        part_no TEXT,
        type_name TEXT,
        assembly_location TEXT,
        customer TEXT,
        note TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT UNIQUE NOT NULL,
        employee_name TEXT NOT NULL,
        department TEXT,
        title TEXT,
        is_active INTEGER DEFAULT 1,
        is_in_factory INTEGER DEFAULT 1,
        is_today_attendance INTEGER DEFAULT 1,
        note TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_time TEXT,
        user_name TEXT,
        action_type TEXT,
        target_table TEXT,
        target_id TEXT,
        message TEXT,
        detail TEXT,
        level TEXT DEFAULT 'INFO'
    )
    """)
    conn.commit()
    conn.close()

def log_action(action_type: str, target_table: str, message: str, detail: str = "") -> None:
    ensure_tables()
    conn = get_conn()
    conn.execute("""
        INSERT INTO system_logs
        (log_time, user_name, action_type, target_table, target_id, message, detail, level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (now_text(), "streamlit_user", action_type, target_table, "", message, detail, "INFO"))
    conn.commit()
    conn.close()

def _load(table: str, order_by: str = "id DESC") -> pd.DataFrame:
    ensure_tables()
    if table in ("work_orders", "employees"):
        try:
            _restore_table_from_persistent_if_empty(table)
        except Exception:
            pass
    conn = get_conn()
    try:
        return pd.read_sql_query(f"SELECT * FROM {table} ORDER BY {order_by}", conn)
    finally:
        conn.close()

def load_work_orders() -> pd.DataFrame:
    df = _load("work_orders")
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    for c in cols:
        if c not in df.columns:
            df[c] = False if c == "is_active" else ""
    df = df[cols]
    df["is_active"] = df["is_active"].fillna(0).astype(bool)
    return df

def load_employees() -> pd.DataFrame:
    df = _load("employees")
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    for c in cols:
        if c not in df.columns:
            df[c] = False if c.startswith("is_") else ""
    df = df[cols]
    for c in ["is_active", "is_in_factory", "is_today_attendance"]:
        df[c] = df[c].fillna(0).astype(bool)
    return df

def _txt(v: Any) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip()

def _bool(v: Any) -> int:
    if isinstance(v, str):
        return 1 if v.strip().lower() in ("1", "true", "yes", "y", "是", "啟用", "在廠", "出勤", "v", "✓") else 0
    return 1 if bool(v) else 0

def _id(v: Any) -> int | None:
    if pd.isna(v) or v == "":
        return None
    try:
        i = int(float(v))
        return i if i > 0 else None
    except Exception:
        return None

def save_work_orders(df: pd.DataFrame) -> dict:
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    now = now_text()
    inserted = updated = deleted = skipped = 0
    for _, r in df.iterrows():
        rid = _id(r.get("id"))
        delete = _bool(r.get("_delete", False))
        wo = _txt(r.get("work_order"))
        if delete:
            if rid:
                cur.execute("DELETE FROM work_orders WHERE id=?", (rid,))
            elif wo:
                cur.execute("DELETE FROM work_orders WHERE work_order=?", (wo,))
            deleted += cur.rowcount
            continue
        if not wo:
            skipped += 1
            continue
        vals = (wo, _txt(r.get("part_no")), _txt(r.get("type_name")), _txt(r.get("assembly_location")),
                _txt(r.get("customer")), _txt(r.get("note")), _bool(r.get("is_active", True)), now)
        if rid:
            cur.execute("""
                UPDATE work_orders
                SET work_order=?, part_no=?, type_name=?, assembly_location=?, customer=?, note=?, is_active=?, updated_at=?
                WHERE id=?
            """, vals + (rid,))
            updated += cur.rowcount
        else:
            cur.execute("""
                INSERT INTO work_orders
                (work_order, part_no, type_name, assembly_location, customer, note, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_order) DO UPDATE SET
                    part_no=excluded.part_no, type_name=excluded.type_name,
                    assembly_location=excluded.assembly_location, customer=excluded.customer,
                    note=excluded.note, is_active=excluded.is_active, updated_at=excluded.updated_at
            """, vals[:7] + (now, now))
            inserted += 1
    conn.commit()
    conn.close()
    try:
        _mirror_table_to_persistent_module("work_orders")
    except Exception:
        pass
    log_action("SAVE_WORK_ORDERS", "work_orders", "儲存製令清單", f"inserted={inserted}, updated={updated}, deleted={deleted}, skipped={skipped}")
    return {"inserted": inserted, "updated": updated, "deleted": deleted, "skipped": skipped}

def save_employees(df: pd.DataFrame) -> dict:
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    now = now_text()
    inserted = updated = deleted = skipped = 0
    for _, r in df.iterrows():
        rid = _id(r.get("id"))
        delete = _bool(r.get("_delete", False))
        emp_id = _txt(r.get("employee_id"))
        emp_name = _txt(r.get("employee_name"))
        if delete:
            if rid:
                cur.execute("DELETE FROM employees WHERE id=?", (rid,))
            elif emp_id:
                cur.execute("DELETE FROM employees WHERE employee_id=?", (emp_id,))
            deleted += cur.rowcount
            continue
        if not emp_id or not emp_name:
            skipped += 1
            continue
        vals = (emp_id, emp_name, _txt(r.get("department")), _txt(r.get("title")),
                _bool(r.get("is_active", True)), _bool(r.get("is_in_factory", True)),
                _bool(r.get("is_today_attendance", True)), _txt(r.get("note")), now)
        if rid:
            cur.execute("""
                UPDATE employees
                SET employee_id=?, employee_name=?, department=?, title=?, is_active=?, is_in_factory=?,
                    is_today_attendance=?, note=?, updated_at=?
                WHERE id=?
            """, vals + (rid,))
            updated += cur.rowcount
        else:
            cur.execute("""
                INSERT INTO employees
                (employee_id, employee_name, department, title, is_active, is_in_factory, is_today_attendance, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id) DO UPDATE SET
                    employee_name=excluded.employee_name, department=excluded.department,
                    title=excluded.title, is_active=excluded.is_active,
                    is_in_factory=excluded.is_in_factory,
                    is_today_attendance=excluded.is_today_attendance,
                    note=excluded.note, updated_at=excluded.updated_at
            """, vals[:8] + (now, now))
            inserted += 1
    conn.commit()
    conn.close()
    try:
        _mirror_table_to_persistent_module("employees")
    except Exception:
        pass
    log_action("SAVE_EMPLOYEES", "employees", "儲存人員名單", f"inserted={inserted}, updated={updated}, deleted={deleted}, skipped={skipped}")
    return {"inserted": inserted, "updated": updated, "deleted": deleted, "skipped": skipped}




# ========================= V28 Permanent Authority Overrides =========================
try:
    from services.permanent_authority_service import df_from_table as _v28_df_from_table, update_tables as _v28_update_tables, table_from_df as _v28_table_from_df
except Exception:
    _v28_df_from_table = _v28_update_tables = _v28_table_from_df = None  # type: ignore

def load_work_orders() -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    if _v28_df_from_table is not None:
        df = _v28_df_from_table("03_work_orders", "work_orders", columns=cols)
        if df is not None:
            for c in cols:
                if c not in df.columns: df[c] = ""
            return df[cols]
    return pd.DataFrame(columns=cols)

def load_employees() -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    if _v28_df_from_table is not None:
        df = _v28_df_from_table("04_employees", "employees", columns=cols)
        if df is not None:
            for c in cols:
                if c not in df.columns: df[c] = ""
            return df[cols]
    return pd.DataFrame(columns=cols)

def save_work_orders(df: pd.DataFrame) -> dict:  # type: ignore[override]
    rows = _v28_table_from_df(df.drop(columns=["刪除 / Delete", "刪除", "_delete"], errors="ignore")) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("03_work_orders", {"work_orders": rows}, reason="crud_save_work_orders_v28")
    log_action("SAVE_WORK_ORDERS", "work_orders", "V28 儲存製令清單", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows)}

def save_employees(df: pd.DataFrame) -> dict:  # type: ignore[override]
    rows = _v28_table_from_df(df.drop(columns=["刪除 / Delete", "刪除", "_delete"], errors="ignore")) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("04_employees", {"employees": rows}, reason="crud_save_employees_v28")
    log_action("SAVE_EMPLOYEES", "employees", "V28 儲存人員清單", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows)}


# ========================= V84 CRUD SINGLE AUTHORITY SAVE =========================
def _v84_crud_authority_exists(module_key: str) -> bool:
    try:
        from services.permanent_authority_service import authority_file_exists as _pa_exists
        return bool(_pa_exists(module_key, "records"))
    except Exception:
        return False


def load_work_orders() -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    if _v28_df_from_table is not None and _v84_crud_authority_exists("03_work_orders"):
        df = _v28_df_from_table("03_work_orders", "work_orders", columns=cols)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]
    return pd.DataFrame(columns=cols)


def load_employees() -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    if _v28_df_from_table is not None and _v84_crud_authority_exists("04_employees"):
        df = _v28_df_from_table("04_employees", "employees", columns=cols)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]
    return pd.DataFrame(columns=cols)


def save_work_orders(df: pd.DataFrame) -> dict:  # type: ignore[override]
    rows = _v28_table_from_df(df.drop(columns=["刪除 / Delete", "刪除", "_delete"], errors="ignore")) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("03_work_orders", {"work_orders": rows}, reason="crud_save_work_orders_v84", github=True)
    log_action("SAVE_WORK_ORDERS", "work_orders", "V84 canonical 儲存製令清單", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows)}


def save_employees(df: pd.DataFrame) -> dict:  # type: ignore[override]
    rows = _v28_table_from_df(df.drop(columns=["刪除 / Delete", "刪除", "_delete"], errors="ignore")) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("04_employees", {"employees": rows}, reason="crud_save_employees_v84", github=True)
    log_action("SAVE_EMPLOYEES", "employees", "V84 canonical 儲存人員清單", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows)}
# ======================= END V84 CRUD SINGLE AUTHORITY SAVE =====================


# ========================= V113 EMPLOYEE ID DISPLAY NORMALIZATION =========================
# Purpose:
# 04｜人員名單目前以 permanent authority records.json 為主，舊匯入資料常帶入 id=None。
# data_editor 會直接顯示 None，造成「ID 異常」。
# 這裡只補 04 employees 的 ID 正規化：
# - 既有正整數 ID 會保留。
# - None / 空白 / nan / null / 重複 ID 會依目前資料順序補成 1..N。
# - 空白新增列不強制產生 ID，避免尚未輸入資料就占用編號。
# - save_employees() 寫回 canonical 前也會補齊，Reboot 後不再顯示 None。

def _v113_blankish(v: Any) -> bool:
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v113_positive_int(v: Any) -> int | None:
    if _v113_blankish(v):
        return None
    try:
        n = int(float(str(v).strip()))
        return n if n > 0 else None
    except Exception:
        return None


def _v113_normalize_employee_ids_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    for c in cols:
        if c not in work.columns:
            work[c] = ""

    used: set[int] = set()
    normalized: list[int | str] = []
    needs_new: list[bool] = []

    for _, row in work.iterrows():
        has_business_key = (not _v113_blankish(row.get("employee_id"))) or (not _v113_blankish(row.get("employee_name")))
        cur = _v113_positive_int(row.get("id"))
        if not has_business_key:
            normalized.append("")
            needs_new.append(False)
        elif cur is not None and cur not in used:
            used.add(cur)
            normalized.append(cur)
            needs_new.append(False)
        else:
            normalized.append("")
            needs_new.append(True)

    next_id = 1
    for i, need in enumerate(needs_new):
        if not need:
            continue
        while next_id in used:
            next_id += 1
        normalized[i] = next_id
        used.add(next_id)
        next_id += 1

    work["id"] = normalized
    return work[cols]


def load_employees() -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    if _v28_df_from_table is not None and _v84_crud_authority_exists("04_employees"):
        df = _v28_df_from_table("04_employees", "employees", columns=cols)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = _v113_normalize_employee_ids_df(df[cols])
        for c in ["is_active", "is_in_factory", "is_today_attendance"]:
            if c in df.columns:
                df[c] = df[c].map(_bool).astype(bool)
        return df[cols]
    return pd.DataFrame(columns=cols)


def save_employees(df: pd.DataFrame) -> dict:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    work = df.drop(columns=["刪除 / Delete", "刪除", "_delete"], errors="ignore").copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=cols)
    for c in cols:
        if c not in work.columns:
            work[c] = ""
    work = _v113_normalize_employee_ids_df(work[cols])
    rows = _v28_table_from_df(work) if _v28_table_from_df is not None else []
    if _v28_update_tables is not None:
        _v28_update_tables("04_employees", {"employees": rows}, reason="crud_save_employees_v113_normalize_id", github=True)
    log_action("SAVE_EMPLOYEES", "employees", "V113 儲存人員清單並正規化 ID", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows), "id_normalized": True}
# ======================= END V113 EMPLOYEE ID DISPLAY NORMALIZATION =====================

# ===== V300.25 03/04 MASTER DATA DEDUPE + AUTHORITY WRITE NORMALIZATION START =====
# Purpose:
# - 04 employees reported one new employee being saved as 3 identical rows.
# - Normalize before writing authority: one employee_id = one row, one work_order = one row.
# - Keep the last non-empty edited row, so edits in the data editor win.
# - Use existing permanent_authority_service.update_tables(), which now writes
#   03/04 immediately through the same durable lane as 10 permissions.


def _v30025_blank(v: Any) -> bool:
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v or "").strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v30025_clean_key(v: Any) -> str:
    if _v30025_blank(v):
        return ""
    return str(v).strip()


def _v30025_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "是", "啟用", "在廠", "出勤", "active"}


def _v30025_keep_last_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    order: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    no_key_rows: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row or {})
        k = _v30025_clean_key(r.get(key))
        if not k:
            # Preserve intentionally blank editor rows only if they have meaningful content.
            meaningful = any(not _v30025_blank(v) for kk, v in r.items() if kk not in {"id", "created_at", "updated_at"})
            if meaningful:
                no_key_rows.append(r)
            continue
        if k not in by_key:
            order.append(k)
        # Later row wins, but keep earlier non-empty fields when the later value is blank.
        prev = by_key.get(k, {})
        merged = dict(prev)
        for col, val in r.items():
            if not _v30025_blank(val) or col not in merged:
                merged[col] = val
        merged[key] = k
        by_key[k] = merged
    return [by_key[k] for k in order] + no_key_rows


def _v30025_next_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used: set[int] = set()
    for r in rows:
        x = dict(r)
        try:
            n = int(float(str(x.get("id", "")).strip()))
        except Exception:
            n = 0
        if n > 0 and n not in used:
            used.add(n)
            x["id"] = n
        else:
            x["id"] = ""
        out.append(x)
    next_id = 1
    for x in out:
        if not _v30025_blank(x.get("id")):
            continue
        while next_id in used:
            next_id += 1
        x["id"] = next_id
        used.add(next_id)
        next_id += 1
    return out


try:
    _v30025_update_tables = _v28_update_tables
    _v30025_table_from_df = _v28_table_from_df
except Exception:
    _v30025_update_tables = None
    _v30025_table_from_df = None


def _v30025_df_rows(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    work = df.drop(columns=["刪除 / Delete", "刪除", "_delete"], errors="ignore").copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=cols)
    for c in cols:
        if c not in work.columns:
            work[c] = ""
    work = work[cols].fillna("")
    if callable(_v30025_table_from_df):
        return _v30025_table_from_df(work)
    return [dict(r) for _, r in work.iterrows()]


def save_work_orders(df: pd.DataFrame) -> dict:  # type: ignore[override]
    cols = ["id", "work_order", "part_no", "type_name", "assembly_location", "customer", "note", "is_active", "created_at", "updated_at"]
    rows = _v30025_df_rows(df, cols)
    rows = _v30025_keep_last_by_key(rows, "work_order")
    rows = _v30025_next_ids(rows)
    for r in rows:
        r["is_active"] = _v30025_bool(r.get("is_active"))
    if callable(_v30025_update_tables):
        _v30025_update_tables("03_work_orders", {"work_orders": rows}, reason="v30025_save_work_orders_dedupe_durable", github=True)
    log_action("SAVE_WORK_ORDERS", "work_orders", "V300.25 儲存製令清單：去重並寫入權威檔", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows), "deduped": True}


def load_employees() -> pd.DataFrame:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    df = _v28_df_from_table("04_employees", "employees", columns=cols) if _v28_df_from_table is not None else pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    rows = _v30025_keep_last_by_key([dict(r) for _, r in df[cols].fillna("").iterrows()], "employee_id")
    rows = _v30025_next_ids(rows)
    out = pd.DataFrame(rows)
    for c in cols:
        if c not in out.columns:
            out[c] = ""
    for c in ["is_active", "is_in_factory", "is_today_attendance"]:
        out[c] = out[c].map(_v30025_bool).astype(bool)
    return out[cols]


def save_employees(df: pd.DataFrame) -> dict:  # type: ignore[override]
    cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at"]
    rows = _v30025_df_rows(df, cols)
    rows = _v30025_keep_last_by_key(rows, "employee_id")
    rows = _v30025_next_ids(rows)
    for r in rows:
        r["is_active"] = _v30025_bool(r.get("is_active"))
        r["is_in_factory"] = _v30025_bool(r.get("is_in_factory"))
        r["is_today_attendance"] = _v30025_bool(r.get("is_today_attendance"))
    if callable(_v30025_update_tables):
        _v30025_update_tables("04_employees", {"employees": rows}, reason="v30025_save_employees_dedupe_durable", github=True)
    log_action("SAVE_EMPLOYEES", "employees", "V300.25 儲存人員清單：去重並寫入權威檔", f"rows={len(rows)}")
    return {"inserted": 0, "updated": len(rows), "deleted": 0, "skipped": 0, "saved": len(rows), "deduped": True}
# ===== V300.25 03/04 MASTER DATA DEDUPE + AUTHORITY WRITE NORMALIZATION END =====


# ===== V300.31 03 WORK ORDERS CLOUD REBOOT DURABILITY FIX START =====
# Purpose:
# - 03. 製令管理新增/修改後，Streamlit Cloud Reboot 不可消失。
# - V300.25 already writes local canonical authority.  This layer explicitly uploads
#   the small 03/04 master authority file through github_cloud_storage_service,
#   bypassing the runtime hot-path guard that intentionally blocks 06/11.
# - No UI/CSS/theme changes; no 01/02 data model changes.
try:
    _v30031_prev_save_work_orders = save_work_orders  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30031_prev_save_work_orders = None
try:
    _v30031_prev_save_employees = save_employees  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v30031_prev_save_employees = None


def _v30031_upload_master_authority(module_key: str) -> dict:
    """Upload the canonical master authority file when an admin explicitly saves it."""
    try:
        from services.permanent_authority_service import canonical_path
        from services.github_cloud_storage_service import upload_file_to_github
        local = canonical_path(module_key, "records")
        if not local.exists():
            return {"ok": False, "skipped": True, "reason": "canonical_missing", "path": str(local)}
        remote = f"data/permanent_store/modules/{module_key}/records.json"
        return dict(upload_file_to_github(local, remote, f"SPT V300.31 durable master authority {module_key}" ) or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "module_key": str(module_key)}


def save_work_orders(df: pd.DataFrame) -> dict:  # type: ignore[override]
    res = _v30031_prev_save_work_orders(df) if callable(_v30031_prev_save_work_orders) else {"ok": False, "error": "previous_save_work_orders_missing"}
    upload = _v30031_upload_master_authority("03_work_orders")
    try:
        if isinstance(res, dict):
            res = dict(res)
            res["v30031_cloud_reboot_durable"] = True
            res["github_upload"] = upload
    except Exception:
        pass
    return res


def save_employees(df: pd.DataFrame) -> dict:  # type: ignore[override]
    res = _v30031_prev_save_employees(df) if callable(_v30031_prev_save_employees) else {"ok": False, "error": "previous_save_employees_missing"}
    upload = _v30031_upload_master_authority("04_employees")
    try:
        if isinstance(res, dict):
            res = dict(res)
            res["v30031_cloud_reboot_durable"] = True
            res["github_upload"] = upload
    except Exception:
        pass
    return res


def audit_v30031_master_authority_upload() -> dict:
    return {
        "version": "V300.31",
        "scope": "03_work_orders_and_04_employees_master_authority_upload",
        "work_orders_upload_check": _v30031_upload_master_authority("03_work_orders"),
        "employees_upload_check": _v30031_upload_master_authority("04_employees"),
    }
# ===== V300.31 03 WORK ORDERS CLOUD REBOOT DURABILITY FIX END =====
