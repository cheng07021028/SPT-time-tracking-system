# -*- coding: utf-8 -*-
"""V153 time-record integrity audit and non-destructive repair service.

This service is intentionally read-heavy and conservative:
- Audit never writes anything.
- Repair only merges missing rows into 01/02 canonical authority files.
- Repair never deletes rows, never renumbers IDs, never uses a partial screen table
  to overwrite full history, and never reconstructs incomplete rows from LOG alone.

Designed for SPT time tracking where 50 operators may record work concurrently.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_ROOT = PROJECT_ROOT / "data" / "permanent_store" / "modules"
DB_PATH = PROJECT_ROOT / "data" / "database" / "spt_time_tracking.db"

TERMINAL_STATUSES = {"暫停", "下班", "完工", "已結束", "結束", "PAUSE", "OFF_DUTY", "FINISH", "DONE", "ENDED"}
ACTIVE_STATUSES = {"作業中", "START", "START_WORK", "WORKING", "ACTIVE"}
TIME_RECORD_TABLE = "time_records"


def _now_text() -> str:
    try:
        from services.timezone_service import now_text  # type: ignore
        return now_text()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_text() -> str:
    try:
        from services.timezone_service import today_text  # type: ignore
        return today_text()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _clean(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _safe_int(value: Any) -> int | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    text = _clean(value)
    if not text:
        return default
    try:
        if ":" in text:
            parts = [float(x) for x in text.split(":")[:3]]
            while len(parts) < 3:
                parts.append(0.0)
            return (parts[0] * 3600 + parts[1] * 60 + parts[2]) / 3600.0
        return float(text)
    except Exception:
        return default


def _date_part(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = text.replace("/", "-").replace("T", " ")
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return text[:10]


def _timestamp_text(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = text.replace("/", "-").replace("T", " ")
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return text[:19]


def _row_get(row: dict[str, Any], *names: str) -> str:
    for name in names:
        if name in row:
            v = _clean(row.get(name))
            if v:
                return v
    return ""


def _employee_id(row: dict[str, Any]) -> str:
    emp = _row_get(row, "employee_id", "工號 / Employee ID", "工號 / Employee", "工號", "Employee ID")
    if emp:
        return emp
    rk = _record_key(row)
    if "|" in rk:
        return rk.split("|", 1)[0].strip()
    return ""


def _employee_name(row: dict[str, Any]) -> str:
    return _row_get(row, "employee_name", "姓名 / Name", "姓名", "Employee Name", "name")


def _work_order(row: dict[str, Any]) -> str:
    return _row_get(row, "work_order", "製令 / Work Order", "製令", "Work Order")


def _process_name(row: dict[str, Any]) -> str:
    return _row_get(row, "process_name", "工段 / Process", "製程 / Process", "工段", "製程", "Process")


def _record_key(row: dict[str, Any]) -> str:
    return _row_get(row, "record_key", "紀錄鍵 / Record Key", "Record Key")


def _record_id(row: dict[str, Any]) -> int | None:
    return _safe_int(row.get("id", row.get("ID", row.get("ID / ID"))))


def _start_ts(row: dict[str, Any]) -> str:
    ts = _row_get(row, "start_timestamp", "開始時間戳 / Start Timestamp", "Start Timestamp", "開始時間")
    if ts:
        return _timestamp_text(ts)
    d = _row_get(row, "start_date", "work_date", "日期 / Date", "開始日期", "工作日期")
    t = _row_get(row, "start_time", "開始時間 / Start Time", "Start Time")
    if d and t:
        return _timestamp_text(f"{d} {t}")
    return _timestamp_text(d)


def _end_ts(row: dict[str, Any]) -> str:
    return _timestamp_text(_row_get(row, "end_timestamp", "結束時間戳 / End Timestamp", "End Timestamp", "結束時間"))


def _work_date(row: dict[str, Any]) -> str:
    d = _row_get(row, "start_date", "work_date", "日期 / Date", "工作日期")
    if d:
        return _date_part(d)
    return _date_part(_start_ts(row))


def _status(row: dict[str, Any]) -> str:
    return _row_get(row, "status", "狀態 / Status", "狀態", "Status")


def _is_terminal(row: dict[str, Any]) -> bool:
    st = _status(row).strip()
    if st in TERMINAL_STATUSES:
        return True
    if _end_ts(row):
        return True
    wh = _row_get(row, "work_hours", "工時 / Work Hours", "工時")
    return _safe_float(wh, 0.0) > 0 and st != "作業中"


def _is_active(row: dict[str, Any]) -> bool:
    st = _status(row).strip()
    return (st in ACTIVE_STATUSES or st == "") and not _end_ts(row)


def _business_key(row: dict[str, Any]) -> str:
    emp = _employee_id(row)
    name = _employee_name(row)
    wo = _work_order(row)
    proc = _process_name(row)
    start = _start_ts(row)
    if emp and wo and proc and start:
        return f"biz|{emp}|{name}|{wo}|{proc}|{start}"
    return ""


def _strong_key(row: dict[str, Any]) -> str:
    rk = _record_key(row)
    if rk:
        return "rk|" + rk
    bk = _business_key(row)
    if bk:
        return bk
    rid = _record_id(row)
    if rid is not None:
        return "id|" + str(rid)
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return "hash|" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _updated_score(row: dict[str, Any]) -> tuple[int, str, int]:
    terminal_score = 1 if _is_terminal(row) else 0
    ts = _row_get(row, "updated_at", "Update Time", "最後更新", "end_timestamp", "created_at", "start_timestamp")
    filled = sum(1 for v in row.values() if _clean(v))
    return (terminal_score, _timestamp_text(ts), filled)


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _authority_rows(module_key: str, table: str = TIME_RECORD_TABLE) -> list[dict[str, Any]]:
    try:
        from services.permanent_authority_service import load_tables  # type: ignore
        rows = load_tables(module_key, "records").get(table, [])
        return [dict(r) for r in rows if isinstance(r, dict)]
    except Exception:
        p = AUTH_ROOT / module_key / "records.json"
        data = _read_json(p)
        if isinstance(data, dict):
            rows = ((data.get("tables") or {}).get(table) or data.get("records") or data.get("rows") or [])
            return [dict(r) for r in rows if isinstance(r, dict)]
    return []


def _settings(module_key: str) -> dict[str, Any]:
    try:
        from services.permanent_authority_service import load_authority  # type: ignore
        data = load_authority(module_key, "settings")
        if isinstance(data, dict):
            st = data.get("settings") if isinstance(data.get("settings"), dict) else data
            return dict(st) if isinstance(st, dict) else {}
    except Exception:
        pass
    p = AUTH_ROOT / module_key / "settings.json"
    data = _read_json(p)
    if isinstance(data, dict):
        return dict(data.get("settings") if isinstance(data.get("settings"), dict) else data)
    return {}


def _sqlite_table(table: str) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            return []
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _extract_row_from_payload(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        for key in ("row", "record", "time_record", "time_record_row"):
            if isinstance(data.get(key), dict):
                return dict(data[key])
        tables = data.get("tables")
        if isinstance(tables, dict):
            rows = tables.get(TIME_RECORD_TABLE)
            if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
                return dict(rows[0])
        payload = data.get("payload") or data.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = None
        if isinstance(payload, dict):
            for key in ("row", "record", "time_record", "time_record_row"):
                if isinstance(payload.get(key), dict):
                    return dict(payload[key])
    return None


def _json_rows_under(rel_dir: str) -> list[dict[str, Any]]:
    root = AUTH_ROOT / "02_history" / rel_dir
    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for p in root.rglob("*.json"):
        data = _read_json(p)
        row = _extract_row_from_payload(data)
        if row:
            row.setdefault("_source_file", str(p.relative_to(PROJECT_ROOT)))
            out.append(row)
    return out


def _event_rows() -> list[dict[str, Any]]:
    """Return raw event dictionaries from event journal JSON files when present."""
    root = AUTH_ROOT / "02_history" / "time_record_events"
    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for p in root.rglob("*.json"):
        data = _read_json(p)
        if isinstance(data, dict):
            event = dict(data.get("event") if isinstance(data.get("event"), dict) else data)
            event.setdefault("_source_file", str(p.relative_to(PROJECT_ROOT)))
            out.append(event)
    return out


def _logs_rows() -> list[dict[str, Any]]:
    rows = []
    rows.extend(_authority_rows("06_logs", "system_logs"))
    rows.extend(_authority_rows("06_system_logs", "system_logs"))
    rows.extend(_sqlite_table("system_logs"))
    # De-dupe logs by id + time + action + target.
    dedup: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = f"{_clean(r.get('id'))}|{_clean(r.get('log_time'))}|{_clean(r.get('action_type'))}|{_clean(r.get('target_id'))}|{_clean(r.get('message'))}"
        dedup[k] = r
    return list(dedup.values())


def collect_time_record_sources() -> dict[str, list[dict[str, Any]]]:
    return {
        "01_time_records": _authority_rows("01_time_records"),
        "02_history": _authority_rows("02_history"),
        "sqlite_time_records": _sqlite_table("time_records"),
        "row_shards": _json_rows_under("time_record_rows"),
        "event_rows": [_extract_row_from_payload(e) for e in _event_rows() if _extract_row_from_payload(e)],
    }


def _tombstone_sets() -> tuple[set[int], set[str], list[dict[str, str]]]:
    st = _settings("02_history")
    ids: set[int] = set()
    keys: set[str] = set()
    for x in st.get("deleted_record_ids", []) if isinstance(st.get("deleted_record_ids"), list) else []:
        rid = _safe_int(x)
        if rid is not None:
            ids.add(rid)
    for x in st.get("deleted_record_keys", []) if isinstance(st.get("deleted_record_keys"), list) else []:
        k = _clean(x)
        if k:
            keys.add(k)
    ranges = st.get("delete_ranges", []) if isinstance(st.get("delete_ranges"), list) else []
    clean_ranges = [dict(x) for x in ranges if isinstance(x, dict)]
    return ids, keys, clean_ranges


def _is_tombstoned(row: dict[str, Any]) -> bool:
    ids, keys, ranges = _tombstone_sets()
    rk = _record_key(row)
    if rk and rk in keys:
        return True
    rid = _record_id(row)
    # ID tombstone only applies to rows without record_key to avoid SQLite ID reuse false positive.
    if rid is not None and rid in ids and not rk:
        return True
    d = _work_date(row)
    updated = _timestamp_text(_row_get(row, "updated_at", "created_at", "start_timestamp"))
    for r in ranges:
        sd, ed = _date_part(r.get("start_date")), _date_part(r.get("end_date"))
        deleted_at = _timestamp_text(r.get("deleted_at"))
        if sd and ed and d and sd <= d <= ed:
            if not deleted_at or not updated or updated <= deleted_at:
                return True
    return False


def _row_matches_date(row: dict[str, Any], start_date: str | None, end_date: str | None) -> bool:
    d = _work_date(row)
    if not d:
        return True
    if start_date and d < str(start_date):
        return False
    if end_date and d > str(end_date):
        return False
    return True


def merge_time_records_non_destructive(*, include_sqlite: bool = True, include_shards: bool = True, include_events: bool = True, start_date: str | None = None, end_date: str | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    sources = collect_time_record_sources()
    ordered = ["02_history", "01_time_records"]
    if include_sqlite:
        ordered.append("sqlite_time_records")
    if include_shards:
        ordered.append("row_shards")
    if include_events:
        ordered.append("event_rows")
    merged: dict[str, dict[str, Any]] = {}
    source_counts: dict[str, int] = {}
    for src in ordered:
        rows = [dict(r) for r in sources.get(src, []) if isinstance(r, dict)]
        source_counts[src] = len(rows)
        for row in rows:
            if not _row_matches_date(row, start_date, end_date):
                continue
            if src not in {"02_history", "01_time_records"} and _is_tombstoned(row):
                continue
            k = _strong_key(row)
            old = merged.get(k)
            row = dict(row)
            row.setdefault("_recovered_from", src)
            if old is None or _updated_score(row) >= _updated_score(old):
                # Preserve original source trace if replacing.
                merged[k] = row
    rows = list(merged.values())
    if rows:
        df = pd.DataFrame(rows)
        if "id" in df.columns:
            try:
                df["_v153_id_sort"] = pd.to_numeric(df["id"], errors="coerce")
                df = df.sort_values(["_v153_id_sort", "start_timestamp"], ascending=[False, False], kind="stable").drop(columns=["_v153_id_sort"], errors="ignore")
            except Exception:
                pass
        return df.reset_index(drop=True), source_counts
    return pd.DataFrame(), source_counts


def _log_start_rows(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    out = []
    for r in _logs_rows():
        action = _clean(r.get("action_type") or r.get("動作 / Action")).upper()
        msg = _clean(r.get("message") or r.get("操作內容 / Message"))
        if "START_WORK" not in action and "開始" not in msg:
            continue
        d = _date_part(r.get("log_time") or r.get("LOG時間 / Log Time"))
        if start_date and d and d < str(start_date):
            continue
        if end_date and d and d > str(end_date):
            continue
        out.append(r)
    return out


def _parse_start_log(row: dict[str, Any]) -> dict[str, Any]:
    msg = _clean(row.get("message") or row.get("操作內容 / Message"))
    user = _clean(row.get("user_name") or row.get("帳號 / User"))
    target_id = _safe_int(row.get("target_id") or row.get("目標ID / Target ID"))
    log_time = _timestamp_text(row.get("log_time") or row.get("LOG時間 / Log Time"))
    name = ""
    work_order = ""
    process = ""
    # Examples: 胡瑄芸 開始 26M0021-01 / Packing
    m = re.search(r"(?P<name>.*?)\s*開始\s+(?P<wo>[^/／]+)\s*[/／]\s*(?P<proc>.+)$", msg)
    if m:
        name = _clean(m.group("name"))
        work_order = _clean(m.group("wo"))
        process = _clean(m.group("proc"))
    return {"employee_id": user, "employee_name": name, "work_order": work_order, "process_name": process, "target_id": target_id, "log_time": log_time, "message": msg}


def _records_index(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {"id": set(), "record_key": set(), "biz_weak": set()}
    for r in rows:
        rid = _record_id(r)
        if rid is not None:
            idx["id"].add(str(rid))
        rk = _record_key(r)
        if rk:
            idx["record_key"].add(rk)
        weak = "|".join([_employee_id(r), _work_order(r), _process_name(r), _work_date(r)])
        if weak.strip("|"):
            idx["biz_weak"].add(weak)
    return idx


def audit_time_record_integrity(start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    start_date = _date_part(start_date) if start_date else None
    end_date = _date_part(end_date) if end_date else None
    sources = collect_time_record_sources()
    merged_df, source_counts = merge_time_records_non_destructive(start_date=start_date, end_date=end_date)
    merged_rows = merged_df.to_dict(orient="records") if not merged_df.empty else []
    merged_idx = _records_index(merged_rows)

    issues: list[dict[str, Any]] = []

    def add_issue(severity: str, category: str, message: str, row: dict[str, Any] | None = None, repairable: bool = False, recommendation: str = "") -> None:
        row = row or {}
        issues.append({
            "嚴重度 / Severity": severity,
            "類別 / Category": category,
            "說明 / Message": message,
            "可自動修復 / Auto Repairable": "YES" if repairable else "NO",
            "建議處理 / Recommendation": recommendation,
            "ID / ID": _record_id(row) or row.get("target_id", ""),
            "Record Key": _record_key(row),
            "工號 / Employee ID": _employee_id(row),
            "姓名 / Name": _employee_name(row),
            "製令 / Work Order": _work_order(row),
            "工段 / Process": _process_name(row),
            "開始時間 / Start": _start_ts(row) or row.get("log_time", ""),
            "來源 / Source": row.get("_recovered_from", row.get("_source_file", "")),
        })

    # 1. LOG START_WORK missing in merged records.
    for log in _log_start_rows(start_date, end_date):
        parsed = _parse_start_log(log)
        found = False
        if parsed["target_id"] is not None and str(parsed["target_id"]) in merged_idx["id"]:
            found = True
        weak = "|".join([parsed.get("employee_id", ""), parsed.get("work_order", ""), parsed.get("process_name", ""), _date_part(parsed.get("log_time"))])
        if weak.strip("|") and weak in merged_idx["biz_weak"]:
            found = True
        if not found:
            add_issue(
                "CRITICAL",
                "LOG_START_MISSING_TIME_RECORD",
                "LOG 有 START_WORK / 開始作業，但 01/02/SQLite/row shard 合併後找不到對應工時資料。",
                parsed,
                repairable=False,
                recommendation="若 SQLite 或 row shard 仍存在，請先執行非破壞式修復；若只剩 LOG，需人工補資料，因 LOG 沒有完整 INSERT 參數。",
            )

    # 2. Duplicates and conflicting states.
    by_key: dict[str, list[dict[str, Any]]] = {}
    all_rows_with_source: list[dict[str, Any]] = []
    for src, rows in sources.items():
        for r in rows:
            rr = dict(r)
            rr["_recovered_from"] = src
            if _row_matches_date(rr, start_date, end_date):
                all_rows_with_source.append(rr)
                by_key.setdefault(_strong_key(rr), []).append(rr)
    for key, rows in by_key.items():
        if len(rows) > 1:
            statuses = {_status(x) for x in rows}
            terminal = any(_is_terminal(x) for x in rows)
            active = any(_is_active(x) for x in rows)
            if terminal and active:
                add_issue(
                    "HIGH",
                    "ACTIVE_TERMINAL_CONFLICT",
                    f"同一筆資料在多來源同時存在作業中與已結束版本，key={key}。",
                    rows[-1],
                    repairable=True,
                    recommendation="以已結束版本為準，重新合併 01/02 權威檔。",
                )
            elif len(statuses) > 1:
                add_issue(
                    "MEDIUM",
                    "MULTI_SOURCE_STATUS_MISMATCH",
                    f"同一筆資料在多來源狀態不同：{sorted(statuses)}，key={key}。",
                    rows[-1],
                    repairable=True,
                    recommendation="執行非破壞式合併，保留最新/已結束版本。",
                )
            elif len(rows) > 2:
                add_issue(
                    "LOW",
                    "DUPLICATE_SAME_RECORD",
                    f"同一筆資料在多來源重複出現 {len(rows)} 次，key={key}。",
                    rows[-1],
                    repairable=True,
                    recommendation="屬於多來源備援，若狀態一致通常可接受；可用合併修復整理 01/02。",
                )

    # 3. 01/02 mismatch.
    k01 = {_strong_key(r) for r in sources.get("01_time_records", []) if _row_matches_date(r, start_date, end_date)}
    k02 = {_strong_key(r) for r in sources.get("02_history", []) if _row_matches_date(r, start_date, end_date)}
    for k in sorted(k01 - k02)[:500]:
        r = next((x for x in sources.get("01_time_records", []) if _strong_key(x) == k), {})
        add_issue("HIGH", "IN_01_NOT_IN_02", "01_time_records 有資料，但 02_history 缺資料。", r, True, "非破壞式合併可補入 02_history。")
    for k in sorted(k02 - k01)[:500]:
        r = next((x for x in sources.get("02_history", []) if _strong_key(x) == k), {})
        add_issue("MEDIUM", "IN_02_NOT_IN_01", "02_history 有資料，但 01_time_records 缺資料。", r, True, "非破壞式合併可補入 01_time_records。")

    # 4. Invalid key fields.
    for r in merged_rows:
        missing = []
        if not _employee_id(r): missing.append("工號")
        if not _work_order(r): missing.append("製令")
        if not _process_name(r): missing.append("工段")
        if not _start_ts(r): missing.append("開始時間")
        if missing:
            add_issue("HIGH", "MISSING_REQUIRED_FIELDS", f"工時紀錄缺少必要欄位：{', '.join(missing)}。", r, False, "需人工確認補齊，避免同人同製令覆蓋或無法追溯。")
        rk = _record_key(r)
        if rk and _employee_id(r) and "|" in rk:
            rk_emp = rk.split("|", 1)[0].strip()
            if rk_emp and rk_emp != _employee_id(r):
                add_issue("HIGH", "IDENTITY_MISMATCH", f"record_key 工號 {rk_emp} 與 employee_id {_employee_id(r)} 不一致。", r, False, "需人工確認資料是否混入他人欄位；不可自動改。")

    # 5. Long active records.
    now = datetime.now()
    for r in merged_rows:
        if not _is_active(r):
            continue
        st = _start_ts(r)
        try:
            dt = pd.to_datetime(st, errors="coerce")
            if not pd.isna(dt) and (now - dt.to_pydatetime()) > timedelta(hours=16):
                add_issue("MEDIUM", "LONG_RUNNING_ACTIVE_RECORD", "作業中紀錄已超過 16 小時未結束。", r, False, "請現場確認是否忘記下班/暫停，避免工時異常。")
        except Exception:
            pass

    # 6. V152 event journal presence.
    event_count = len(_event_rows())
    if event_count == 0:
        add_issue("MEDIUM", "EVENT_JOURNAL_NOT_FOUND", "尚未偵測到 V152 append-only event journal 事件檔。", {}, False, "請確認 V152 是否已套用；事件層是防止 LOG 有但歷史缺資料的關鍵保護。")

    issue_df = pd.DataFrame(issues)
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    if not issue_df.empty:
        issue_df["_sort"] = issue_df["嚴重度 / Severity"].map(lambda x: severity_order.get(str(x), 9))
        issue_df = issue_df.sort_values(["_sort", "類別 / Category"], kind="stable").drop(columns=["_sort"], errors="ignore").reset_index(drop=True)

    summary = {
        "checked_at": _now_text(),
        "date_range": f"{start_date or '-'} ~ {end_date or '-'}",
        "source_counts": source_counts,
        "merged_records": len(merged_rows),
        "log_start_count": len(_log_start_rows(start_date, end_date)),
        "event_journal_count": event_count,
        "issue_count": int(len(issue_df)),
        "critical_count": int((issue_df["嚴重度 / Severity"] == "CRITICAL").sum()) if not issue_df.empty else 0,
        "high_count": int((issue_df["嚴重度 / Severity"] == "HIGH").sum()) if not issue_df.empty else 0,
        "repairable_count": int((issue_df["可自動修復 / Auto Repairable"] == "YES").sum()) if not issue_df.empty else 0,
    }
    return {"summary": summary, "issues": issue_df, "merged_records": merged_df, "sources": source_counts}


def repair_0102_authority_non_destructive(*, github: bool = True, start_date: str | None = None, end_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Merge all recoverable rows and write the same result to 01/02 canonical.

    Safety rules:
    - Never create records from LOG alone.
    - Never delete existing 02_history rows.
    - Never renumber IDs.
    - Reject empty merge.
    """
    merged_df, source_counts = merge_time_records_non_destructive(start_date=start_date, end_date=end_date)
    if merged_df.empty:
        return {"ok": False, "reason": "merged_result_empty_refuse_to_write", "source_counts": source_counts}
    existing_02 = pd.DataFrame(_authority_rows("02_history"))
    base_count = len(existing_02)
    merged_count = len(merged_df)
    if merged_count < base_count:
        return {"ok": False, "reason": f"merged_count_less_than_existing_02_refuse_to_write {merged_count} < {base_count}", "source_counts": source_counts}
    if dry_run:
        return {"ok": True, "dry_run": True, "merged_count": merged_count, "existing_02_count": base_count, "source_counts": source_counts}
    rows = merged_df.drop(columns=[c for c in merged_df.columns if str(c).startswith("_")], errors="ignore").where(pd.notna(merged_df), "").to_dict(orient="records")
    try:
        from services.permanent_authority_service import save_authority  # type: ignore
        r1 = save_authority("01_time_records", records={TIME_RECORD_TABLE: rows}, reason="v153_integrity_center_non_destructive_repair_01", github=bool(github))
        r2 = save_authority("02_history", records={TIME_RECORD_TABLE: rows}, reason="v153_integrity_center_non_destructive_repair_02", github=bool(github))
        return {"ok": True, "merged_count": merged_count, "existing_02_count": base_count, "source_counts": source_counts, "save_01": r1, "save_02": r2}
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "merged_count": merged_count, "existing_02_count": base_count, "source_counts": source_counts}


def export_audit_excel_bytes(audit_result: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    summary = audit_result.get("summary", {}) if isinstance(audit_result, dict) else {}
    issues = audit_result.get("issues") if isinstance(audit_result, dict) else pd.DataFrame()
    merged = audit_result.get("merged_records") if isinstance(audit_result, dict) else pd.DataFrame()
    if not isinstance(issues, pd.DataFrame):
        issues = pd.DataFrame()
    if not isinstance(merged, pd.DataFrame):
        merged = pd.DataFrame()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([summary]).to_excel(writer, sheet_name="摘要", index=False)
        issues.to_excel(writer, sheet_name="異常清單", index=False)
        merged.head(5000).to_excel(writer, sheet_name="合併後資料預覽", index=False)
        pd.DataFrame([audit_result.get("sources", {})]).to_excel(writer, sheet_name="來源統計", index=False)
    return output.getvalue()


# English aliases for scripts/tests.
audit = audit_time_record_integrity
repair = repair_0102_authority_non_destructive
