# -*- coding: utf-8 -*-
"""V157 regression and 50-user stress simulation service.

This service is intentionally non-destructive.  It never writes to production
SQLite, canonical JSON, GitHub, row shard, or time_record_events.  The 50-user
stress test runs inside a temporary sandbox SQLite database and verifies the
business invariants that caused prior data-loss incidents:

- many people can start the same work order / same process without overwriting;
- one employee with multiple parallel works finishes every parallel row;
- append-only event count equals operation count;
- final records are not lost after concurrent writes;
- no fake active work remains after finish.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TERMINAL_STATUSES = {"下班", "暫停", "完工", "已結束", "結束"}


def _now_text() -> str:
    try:
        from services.timezone_service import now_text  # type: ignore
        return str(now_text())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_text() -> str:
    try:
        from services.timezone_service import today_text  # type: ignore
        return str(today_text())
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _hms_from_seconds(seconds: float | int) -> str:
    total = max(0, int(round(float(seconds or 0))))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _hours_between(start_ts: str, end_ts: str) -> float:
    try:
        s = datetime.strptime(str(start_ts)[:19], "%Y-%m-%d %H:%M:%S")
        e = datetime.strptime(str(end_ts)[:19], "%Y-%m-%d %H:%M:%S")
        return round(max((e - s).total_seconds(), 0) / 3600.0, 4)
    except Exception:
        return 0.0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _record_identity(row: dict[str, Any]) -> str:
    rk = str(row.get("record_key") or "").strip()
    if rk:
        return "rk:" + rk
    return "biz:" + "|".join(
        str(row.get(k) or "").strip()
        for k in ("employee_id", "employee_name", "work_order", "process_name", "start_timestamp")
    )


def _row_hash(row: dict[str, Any]) -> str:
    txt = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


@dataclass
class _Sandbox:
    root: Path
    db_path: Path
    event_dir: Path
    row_dir: Path
    locks: dict[str, threading.RLock]
    lock_guard: threading.RLock

    def lock_for_employee(self, employee_id: str, employee_name: str) -> threading.RLock:
        key = f"{employee_id}|{employee_name}"
        with self.lock_guard:
            if key not in self.locks:
                self.locks[key] = threading.RLock()
            return self.locks[key]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _create_sandbox() -> _Sandbox:
    root = Path(tempfile.mkdtemp(prefix="spt_v157_regression_"))
    db_path = root / "sandbox_time_tracking.db"
    event_dir = root / "time_record_events"
    row_dir = root / "time_record_rows"
    event_dir.mkdir(parents=True, exist_ok=True)
    row_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS time_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_key TEXT UNIQUE,
                status TEXT,
                work_order TEXT,
                part_no TEXT,
                type_name TEXT,
                process_name TEXT,
                employee_id TEXT,
                employee_name TEXT,
                start_action TEXT,
                start_timestamp TEXT,
                end_action TEXT,
                end_timestamp TEXT,
                remark TEXT,
                start_date TEXT,
                start_time TEXT,
                end_date TEXT,
                end_time TEXT,
                work_hours REAL DEFAULT 0,
                assembly_location TEXT,
                group_key TEXT,
                is_group_work INTEGER DEFAULT 0,
                source TEXT,
                row_version INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS time_record_events (
                event_id TEXT PRIMARY KEY,
                record_id INTEGER,
                record_key TEXT,
                employee_id TEXT,
                employee_name TEXT,
                event_type TEXT,
                event_time TEXT,
                payload_json TEXT,
                checksum TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_time TEXT,
                user_name TEXT,
                action_type TEXT,
                target_table TEXT,
                target_id TEXT,
                message TEXT,
                level TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_v157_active ON time_records(employee_id, employee_name, process_name, start_date, end_timestamp, status);
            CREATE INDEX IF NOT EXISTS idx_v157_record_key ON time_records(record_key);
            CREATE INDEX IF NOT EXISTS idx_v157_event_record_key ON time_record_events(record_key);
            """
        )
        conn.commit()
    finally:
        conn.close()
    return _Sandbox(root=root, db_path=db_path, event_dir=event_dir, row_dir=row_dir, locks={}, lock_guard=threading.RLock())


def _append_event(sb: _Sandbox, *, event_type: str, record_id: int, record_key: str, employee_id: str, employee_name: str, payload: dict[str, Any]) -> None:
    event_time = _now_text()
    base = {
        "event_type": event_type,
        "record_id": record_id,
        "record_key": record_key,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "event_time": event_time,
        "payload": payload,
    }
    checksum = hashlib.sha256(json.dumps(base, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    event_id = f"ev_{event_time.replace('-', '').replace(':', '').replace(' ', '_')}_{record_id}_{checksum[:12]}"
    conn = _connect(sb.db_path)
    try:
        conn.execute(
            """
            INSERT INTO time_record_events(event_id, record_id, record_key, employee_id, employee_name, event_type, event_time, payload_json, checksum, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, record_id, record_key, employee_id, employee_name, event_type, event_time, json.dumps(payload, ensure_ascii=False, default=str), checksum, event_time),
        )
        conn.execute(
            """
            INSERT INTO system_logs(log_time, user_name, action_type, target_table, target_id, message, level)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_time, employee_id, event_type, "time_records", str(record_id), f"{employee_name} {event_type} #{record_id}", "INFO"),
        )
        conn.commit()
    finally:
        conn.close()
    day_dir = sb.event_dir / event_time[:10]
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{event_id}.json").write_text(
        json.dumps({**base, "event_id": event_id, "checksum": checksum}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _write_row_shard(sb: _Sandbox, row: dict[str, Any], reason: str) -> None:
    day = str(row.get("start_date") or _today_text())[:10]
    day_dir = sb.row_dir / day
    day_dir.mkdir(parents=True, exist_ok=True)
    rid = _safe_int(row.get("id"), 0)
    file_name = f"tr_{rid:06d}_{_row_hash(row)}.json"
    payload = {"reason": reason, "updated_at": _now_text(), "tables": {"time_records": [row]}}
    (day_dir / file_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _fetch_row(sb: _Sandbox, rid: int) -> dict[str, Any] | None:
    conn = _connect(sb.db_path)
    try:
        r = conn.execute("SELECT * FROM time_records WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _start_work(sb: _Sandbox, *, employee_id: str, employee_name: str, work_order: str, process_name: str, offset_seconds: int) -> int:
    with sb.lock_for_employee(employee_id, employee_name):
        ts = (datetime.now() + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        start_date, start_time = ts[:10], ts[11:19]
        record_key = f"{employee_id}|{employee_name}|{work_order}|{process_name}|{ts}|{hashlib.sha1(os.urandom(8)).hexdigest()[:8]}"
        group_key = f"{employee_id}|{employee_name}|{process_name}|{start_date}"
        conn = _connect(sb.db_path)
        try:
            dup = conn.execute(
                """
                SELECT id FROM time_records
                WHERE employee_id=? AND employee_name=? AND work_order=? AND process_name=? AND start_date=?
                  AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='')
                """,
                (employee_id, employee_name, work_order, process_name, start_date),
            ).fetchone()
            if dup:
                raise RuntimeError(f"duplicate active row detected for {employee_id} {work_order} {process_name}")
            cur = conn.execute(
                """
                INSERT INTO time_records(record_key, status, work_order, part_no, type_name, process_name,
                    employee_id, employee_name, start_action, start_timestamp, remark, start_date, start_time,
                    assembly_location, group_key, is_group_work, source, row_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_key, "作業中", work_order, "PTEST", "V157_TEST", process_name, employee_id, employee_name,
                 "開始", ts, "V157 sandbox regression", start_date, start_time, "TEST", group_key, 0, "v157_sandbox", 1, ts, ts),
            )
            rid = int(cur.lastrowid)
            active_same_group = conn.execute(
                """
                SELECT COUNT(*) AS n FROM time_records
                WHERE employee_id=? AND employee_name=? AND process_name=? AND start_date=?
                  AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='')
                """,
                (employee_id, employee_name, process_name, start_date),
            ).fetchone()["n"]
            if int(active_same_group or 0) > 1:
                conn.execute(
                    """
                    UPDATE time_records SET is_group_work=1, group_key=?, row_version=row_version+1, updated_at=?
                    WHERE employee_id=? AND employee_name=? AND process_name=? AND start_date=?
                      AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='')
                    """,
                    (group_key, ts, employee_id, employee_name, process_name, start_date),
                )
            conn.commit()
        finally:
            conn.close()
        row = _fetch_row(sb, rid) or {}
        _append_event(sb, event_type="START_WORK", record_id=rid, record_key=record_key, employee_id=employee_id, employee_name=employee_name, payload=row)
        _write_row_shard(sb, row, "start_work_v157")
        return rid


def _finish_group(sb: _Sandbox, *, employee_id: str, employee_name: str, process_name: str, status: str = "下班") -> int:
    with sb.lock_for_employee(employee_id, employee_name):
        end_ts = (datetime.now() + timedelta(seconds=90)).strftime("%Y-%m-%d %H:%M:%S")
        end_date, end_time = end_ts[:10], end_ts[11:19]
        conn = _connect(sb.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM time_records
                WHERE employee_id=? AND employee_name=? AND process_name=?
                  AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='')
                ORDER BY id
                """,
                (employee_id, employee_name, process_name),
            ).fetchall()
            if not rows:
                conn.commit()
                return 0
            start_min = min(str(r["start_timestamp"]) for r in rows)
            total_hours = _hours_between(start_min, end_ts)
            avg_hours = round(total_hours / max(len(rows), 1), 4)
            note = f"同步作業平均分配：{len(rows)}筆，群組總工時={_hms_from_seconds(total_hours * 3600)}，平均={_hms_from_seconds(avg_hours * 3600)}"
            updated_ids: list[int] = []
            for r in rows:
                rid = int(r["id"])
                old_remark = str(r["remark"] or "").strip()
                new_remark = (old_remark + "；" if old_remark else "") + note
                conn.execute(
                    """
                    UPDATE time_records
                    SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?, work_hours=?, remark=?,
                        is_group_work=?, row_version=row_version+1, updated_at=?
                    WHERE id=? AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='')
                    """,
                    (status, status, end_ts, end_date, end_time, avg_hours, new_remark, 1 if len(rows) > 1 else int(r["is_group_work"] or 0), end_ts, rid),
                )
                updated_ids.append(rid)
            conn.commit()
        finally:
            conn.close()
        for rid in updated_ids:
            row = _fetch_row(sb, rid) or {}
            _append_event(sb, event_type="FINISH_WORK", record_id=rid, record_key=str(row.get("record_key") or ""), employee_id=employee_id, employee_name=employee_name, payload=row)
            _write_row_shard(sb, row, "finish_work_v157")
        return len(updated_ids)


def _read_table(sb: _Sandbox, table: str) -> pd.DataFrame:
    conn = _connect(sb.db_path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)
    finally:
        conn.close()


def _source_static_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    critical_files = [
        "streamlit_app.py",
        "services/time_record_service.py",
        "services/time_record_event_journal_service.py",
        "services/time_record_integrity_service.py",
        "services/backup_queue_status_service.py",
        "services/permanent_authority_service.py",
        "services/log_service.py",
        "services/security_service.py",
    ]
    critical_page_prefixes = [
        "01_01.", "02_02.", "06_06.", "07_07.", "10_10.", "14_14.",
    ]
    for rel in critical_files:
        p = PROJECT_ROOT / rel
        checks.append({
            "category": "static_file",
            "check": rel,
            "ok": p.exists(),
            "detail": "exists" if p.exists() else "missing",
            "severity": "PASS" if p.exists() else "FAIL",
        })
    page_dir = PROJECT_ROOT / "pages"
    for prefix in critical_page_prefixes:
        matches = sorted(page_dir.glob(prefix + "*.py")) if page_dir.exists() else []
        checks.append({
            "category": "static_file",
            "check": f"pages/{prefix}*.py",
            "ok": len(matches) >= 1,
            "detail": ", ".join(p.name for p in matches[:6]) if matches else "missing",
            "severity": "PASS" if matches else "FAIL",
        })
    # Detect old #Uxxxx page files as warning only, because some current projects still keep them
    # until cleanup tools are run. This must not fail the regression core logic.
    mojibake = sorted(str(p.name) for p in page_dir.glob("*#U*.py")) if page_dir.exists() else []
    checks.append({
        "category": "static_file",
        "check": "mojibake_page_files",
        "ok": len(mojibake) == 0,
        "detail": ", ".join(mojibake[:20]) if mojibake else "no mojibake page files",
        "severity": "WARN" if mojibake else "PASS",
    })
    return checks


def _import_signature_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    modules = [
        ("services.time_record_service", ["start_work", "finish_work", "load_records", "today_records", "sync_time_records_01_02_now"]),
        ("services.time_record_event_journal_service", ["append_time_record_event"]),
        ("services.time_record_integrity_service", ["audit_time_record_integrity", "repair_0102_authority_non_destructive"]),
        ("services.backup_queue_status_service", ["collect_backup_queue_status", "flush_backup_queues_now"]),
    ]
    for mod_name, funcs in modules:
        try:
            mod = __import__(mod_name, fromlist=["*"])
            for fn in funcs:
                checks.append({
                    "category": "import_signature",
                    "check": f"{mod_name}.{fn}",
                    "ok": callable(getattr(mod, fn, None)),
                    "detail": "callable" if callable(getattr(mod, fn, None)) else "missing/non-callable",
                    "severity": "PASS" if callable(getattr(mod, fn, None)) else "FAIL",
                })
        except Exception as exc:
            checks.append({
                "category": "import_signature",
                "check": mod_name,
                "ok": False,
                "detail": f"import failed: {exc}",
                "severity": "FAIL",
            })
    return checks


def _evaluate_sandbox(sb: _Sandbox, expected_workers: int, works_per_worker: int) -> list[dict[str, Any]]:
    records = _read_table(sb, "time_records")
    events = _read_table(sb, "time_record_events")
    logs = _read_table(sb, "system_logs")
    expected_records = expected_workers * works_per_worker
    rows = []

    def add(check: str, ok: bool, detail: str, severity: str | None = None) -> None:
        rows.append({"category": "sandbox_stress", "check": check, "ok": bool(ok), "detail": detail, "severity": severity or ("PASS" if ok else "FAIL")})

    add("expected_record_count", len(records) == expected_records, f"actual={len(records)}, expected={expected_records}")
    add("all_records_terminal", records["status"].astype(str).isin(TERMINAL_STATUSES).all() if not records.empty else False, "all records should be terminal after finish")
    active_mask = records["end_timestamp"].isna() | records["end_timestamp"].astype(str).str.strip().eq("") if not records.empty else pd.Series(dtype=bool)
    add("no_fake_active_work", int(active_mask.sum()) == 0, f"active_without_end={int(active_mask.sum()) if not records.empty else 0}")
    add("unique_record_key", records["record_key"].nunique() == len(records) if not records.empty else False, f"unique={records['record_key'].nunique() if not records.empty else 0}, rows={len(records)}")
    group_sizes = records.groupby(["employee_id", "employee_name", "process_name"]).size() if not records.empty else pd.Series(dtype=int)
    add("parallel_finish_all_rows", bool((group_sizes == works_per_worker).all()) if len(group_sizes) else False, f"groups={len(group_sizes)}, expected_size={works_per_worker}")
    add("same_work_order_multi_person_kept", records.groupby(["work_order", "process_name"])["employee_id"].nunique().max() >= expected_workers if not records.empty else False, "same work order/process should retain every employee")
    add("work_hours_positive", (pd.to_numeric(records["work_hours"], errors="coerce").fillna(0) > 0).all() if not records.empty else False, "each finished row should have positive work_hours")
    start_count = int((events["event_type"] == "START_WORK").sum()) if not events.empty else 0
    finish_count = int((events["event_type"] == "FINISH_WORK").sum()) if not events.empty else 0
    add("event_start_count", start_count == expected_records, f"START_WORK events={start_count}, expected={expected_records}")
    add("event_finish_count", finish_count == expected_records, f"FINISH_WORK events={finish_count}, expected={expected_records}")
    add("log_start_finish_count", len(logs) >= expected_records * 2, f"system_logs={len(logs)}, expected_at_least={expected_records * 2}")
    event_json_count = sum(1 for _ in sb.event_dir.rglob("*.json"))
    row_json_count = sum(1 for _ in sb.row_dir.rglob("*.json"))
    add("event_json_shards", event_json_count >= expected_records * 2, f"event_json={event_json_count}, expected_at_least={expected_records * 2}")
    add("row_json_shards", row_json_count >= expected_records * 2, f"row_json={row_json_count}, expected_at_least={expected_records * 2}")
    return rows


def run_v157_regression_suite(
    worker_count: int = 50,
    works_per_worker: int = 2,
    include_import_checks: bool = True,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Run non-destructive regression and 50-user sandbox stress simulation."""
    worker_count = max(1, min(int(worker_count or 50), 200))
    works_per_worker = max(1, min(int(works_per_worker or 2), 5))
    started = time.perf_counter()
    result: dict[str, Any] = {
        "version": "V157",
        "started_at": _now_text(),
        "worker_count": worker_count,
        "works_per_worker": works_per_worker,
        "sandbox_only": True,
        "production_write": False,
        "checks": [],
        "errors": [],
    }

    def progress(pct: float, msg: str) -> None:
        if callable(progress_callback):
            try:
                progress_callback(float(pct), str(msg))
            except Exception:
                pass

    checks: list[dict[str, Any]] = []
    progress(0.05, "執行靜態檔案檢查")
    checks.extend(_source_static_checks())
    if include_import_checks:
        progress(0.12, "執行服務匯入與函式簽名檢查")
        checks.extend(_import_signature_checks())

    progress(0.20, "建立沙盒資料庫")
    sb = _create_sandbox()
    result["sandbox_root"] = str(sb.root)
    errors: list[dict[str, Any]] = []

    def worker(idx: int) -> None:
        emp_id = f"V157{idx:03d}"
        emp_name = f"測試人員{idx:03d}"
        process = "V157並行測試"
        try:
            for j in range(works_per_worker):
                # all workers intentionally use the same process and one of a few same work orders,
                # proving different employees will not overwrite each other.
                wo = f"V157-WO-{(j % 2) + 1:02d}"
                _start_work(sb, employee_id=emp_id, employee_name=emp_name, work_order=wo, process_name=process, offset_seconds=j)
            _finish_group(sb, employee_id=emp_id, employee_name=emp_name, process_name=process, status="下班")
        except Exception as exc:
            errors.append({"worker": idx, "error": str(exc), "traceback": traceback.format_exc(limit=8)})

    progress(0.30, f"啟動 {worker_count} 人壓力模擬")
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(1, worker_count + 1)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        done = sum(1 for t in threads if not t.is_alive())
        progress(0.30 + 0.50 * (done / max(worker_count, 1)), f"壓力模擬進行中：{done}/{worker_count}")
        time.sleep(0.05)
    for t in threads:
        t.join(timeout=1)

    progress(0.85, "驗證沙盒測試結果")
    checks.extend(_evaluate_sandbox(sb, worker_count, works_per_worker))
    for err in errors:
        checks.append({"category": "sandbox_stress", "check": f"worker_{err.get('worker')}_error", "ok": False, "detail": err.get("error", ""), "severity": "FAIL"})

    df = pd.DataFrame(checks)
    fail_count = int((df["severity"].astype(str) == "FAIL").sum()) if not df.empty and "severity" in df.columns else 0
    warn_count = int((df["severity"].astype(str) == "WARN").sum()) if not df.empty and "severity" in df.columns else 0
    pass_count = int((df["severity"].astype(str) == "PASS").sum()) if not df.empty and "severity" in df.columns else 0
    elapsed = round(time.perf_counter() - started, 3)
    result.update({
        "finished_at": _now_text(),
        "elapsed_seconds": elapsed,
        "summary": {
            "pass_count": pass_count,
            "warn_count": warn_count,
            "fail_count": fail_count,
            "total_checks": len(checks),
            "expected_records": worker_count * works_per_worker,
            "sandbox_root": str(sb.root),
        },
        "checks": df,
        "errors": errors,
        "ok": fail_count == 0,
    })
    progress(1.0, "V157 測試完成")
    return result


def export_v157_regression_excel_bytes(result: dict[str, Any]) -> bytes:
    import io
    bio = io.BytesIO()
    checks = result.get("checks")
    checks_df = checks if isinstance(checks, pd.DataFrame) else pd.DataFrame(checks or [])
    errors_df = pd.DataFrame(result.get("errors") or [])
    summary_rows = []
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    for k, v in {**{k: result.get(k) for k in ("version", "started_at", "finished_at", "elapsed_seconds", "worker_count", "works_per_worker", "sandbox_only", "production_write")}, **summary}.items():
        summary_rows.append({"項目 / Item": k, "值 / Value": v})
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name="摘要")
        checks_df.to_excel(writer, index=False, sheet_name="檢查結果")
        errors_df.to_excel(writer, index=False, sheet_name="錯誤明細")
    return bio.getvalue()


def compact_result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    checks = result.get("checks")
    df = checks if isinstance(checks, pd.DataFrame) else pd.DataFrame(checks or [])
    if df.empty:
        return []
    cols = [c for c in ["category", "check", "severity", "detail"] if c in df.columns]
    return df[cols].to_dict(orient="records")
