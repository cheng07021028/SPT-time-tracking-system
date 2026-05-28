# -*- coding: utf-8 -*-
"""V166C LOG full time-record snapshot and precise recovery helpers.

設計目的：
- 06 LOG 仍維持人可讀的 message / detail。
- 針對 time_records 的 START / END / SAVE / RECALC / IMPORT 等動作，在 detail 後方附加
  一段機器可解析的完整 JSON 快照。
- 日後若 01/02 權威檔或 SQLite 被覆蓋，可優先從 row shard / event journal 修復；若仍缺資料，
  可從 V166C LOG 快照精準補回，不再只能建立 V164B「待人工確認」。

安全邊界：
- 本服務預設只讀；只有 recover_records_from_log_snapshots(..., dry_run=False) 會寫入。
- 寫入時只做非破壞式合併，不刪除、不重新編號、不用局部資料覆蓋全量歷史。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

SNAPSHOT_SCHEMA_VERSION = "V166C"
SNAPSHOT_TYPE = "time_record_full_snapshot"
SNAPSHOT_BEGIN = "[V166C_TIME_RECORD_SNAPSHOT_JSON]"
SNAPSHOT_END = "[/V166C_TIME_RECORD_SNAPSHOT_JSON]"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIME_ACTION_KEYWORDS = (
    "START_WORK", "FINISH_WORK", "END_WORK", "END_WORK_GROUP", "PAUSE_WORK", "OFF_DUTY",
    "SAVE_TIME_RECORDS", "RECALC_TIME_RECORDS", "SYNC_RECALC_TIME_RECORDS_01_02",
    "IMPORT_TIME_RECORDS", "SYNC_IMPORT_TIME_RECORDS_01_02", "MANUAL_EDIT",
    "V90", "V96", "V98", "V104", "V109", "V134", "V137", "V151", "V152", "V166B",
)
TERMINAL_STATUS = {"下班", "暫停", "完工", "已結束", "補登結束"}


def _now_text() -> str:
    try:
        from services.timezone_service import now_text  # type: ignore
        return now_text()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _json_safe(value: Any) -> Any:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, (datetime,)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _row_to_clean_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, pd.Series):
        data = row.to_dict()
    elif isinstance(row, dict):
        data = dict(row)
    else:
        data = {}
    out: dict[str, Any] = {}
    for k, v in data.items():
        if str(k).startswith("Unnamed"):
            continue
        val = _json_safe(v)
        if val is None:
            val = ""
        try:
            if isinstance(val, float) and val.is_integer():
                val = int(val)
        except Exception:
            pass
        out[str(k)] = val
    return out


def _get(row: dict[str, Any], *names: str) -> str:
    for name in names:
        if name in row:
            val = _clean(row.get(name))
            if val:
                return val
    low = {str(k).strip().lower(): k for k in row.keys()}
    for name in names:
        k = low.get(str(name).strip().lower())
        if k is not None:
            val = _clean(row.get(k))
            if val:
                return val
    return ""


def record_key_of(row: dict[str, Any]) -> str:
    return _get(row, "record_key", "Record Key", "紀錄鍵", "主鍵")


def business_identity_key(row: dict[str, Any]) -> str:
    rk = record_key_of(row)
    if rk:
        return "record_key:" + rk
    parts = [
        _get(row, "employee_id", "工號 / Employee ID", "工號", "Employee ID"),
        _get(row, "employee_name", "姓名 / Name", "姓名", "Name"),
        _get(row, "work_order", "製令 / Work Order", "製令", "Work Order", "wo_no"),
        _get(row, "process_name", "工段 / Process", "製程", "工段", "Process"),
        _get(row, "start_timestamp", "開始時間 / Start", "開始時間", "Start Timestamp"),
    ]
    return "biz:" + "|".join(parts)


def _row_summary(row: dict[str, Any]) -> dict[str, str]:
    return {
        "record_key": record_key_of(row),
        "identity_key": business_identity_key(row),
        "id": _get(row, "id", "ID / ID", "ID"),
        "employee_id": _get(row, "employee_id", "工號 / Employee ID", "工號", "Employee ID"),
        "employee_name": _get(row, "employee_name", "姓名 / Name", "姓名", "Name"),
        "work_order": _get(row, "work_order", "製令 / Work Order", "製令", "Work Order", "wo_no"),
        "part_no": _get(row, "part_no", "P/N", "料號", "P/N / 料號"),
        "type_name": _get(row, "type_name", "機型", "機型 / Model", "Model"),
        "process_name": _get(row, "process_name", "工段 / Process", "製程", "工段", "Process"),
        "status": _get(row, "status", "狀態 / Status", "狀態", "Status"),
        "start_timestamp": _get(row, "start_timestamp", "開始時間 / Start", "開始時間", "Start Timestamp"),
        "end_timestamp": _get(row, "end_timestamp", "結束時間 / End", "結束時間", "End Timestamp"),
        "work_hours": _get(row, "work_hours", "工時", "工時 / Hours"),
        "work_hours_hms": _get(row, "work_hours_hms", "工時(HH:MM:SS)", "工時 / HH:MM:SS"),
        "source": _get(row, "source", "來源", "Source"),
    }


def _parse_candidate_ids(*texts: Any) -> list[int]:
    ids: list[int] = []
    for value in texts:
        text = _clean(value)
        if not text:
            continue
        # target_id 最常見是單一 id；finish group detail 可能是 1,2,3。
        if re.fullmatch(r"\d+(\s*,\s*\d+)*", text):
            for m in re.findall(r"\d+", text):
                try:
                    i = int(m)
                    if i > 0 and i not in ids:
                        ids.append(i)
                except Exception:
                    pass
            continue
        # 僅解析明確語義的 affected_ids / ids，避免日期時間被誤抓。
        for m in re.finditer(r"(?:affected_ids|record_ids|ids|同步結束)\D+([0-9,\s]+)", text, flags=re.I):
            for n in re.findall(r"\d+", m.group(1)):
                try:
                    i = int(n)
                    if i > 0 and i not in ids:
                        ids.append(i)
                except Exception:
                    pass
    return ids[:100]


def _query_sqlite_rows_by_ids(ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    try:
        from services.db_service import query_df  # type: ignore
        ph = ",".join(["?"] * len(ids))
        df = query_df(f"SELECT * FROM time_records WHERE id IN ({ph}) ORDER BY id", tuple(ids))
        if isinstance(df, pd.DataFrame) and not df.empty:
            return [_row_to_clean_dict(r) | {"_snapshot_source": "sqlite.time_records"} for _, r in df.iterrows()]
    except Exception:
        pass
    return []


def _read_authority_rows(module_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from services.permanent_authority_service import load_tables  # type: ignore
        tables = load_tables(module_key, "records")
        raw = tables.get("time_records") if isinstance(tables, dict) else []
        for r in raw or []:
            if isinstance(r, dict):
                x = _row_to_clean_dict(r)
                x["_snapshot_source"] = f"authority.{module_key}"
                rows.append(x)
    except Exception:
        try:
            p = PROJECT_ROOT / "data" / "permanent_store" / "modules" / module_key / "records.json"
            if p.exists() and p.stat().st_size > 0:
                data = json.loads(p.read_text(encoding="utf-8"))
                raw = []
                if isinstance(data, dict):
                    if isinstance(data.get("tables"), dict):
                        raw = data.get("tables", {}).get("time_records") or []
                    elif isinstance(data.get("records"), list):
                        raw = data.get("records") or []
                for r in raw or []:
                    if isinstance(r, dict):
                        x = _row_to_clean_dict(r)
                        x["_snapshot_source"] = f"authority.{module_key}.file"
                        rows.append(x)
        except Exception:
            pass
    return rows


def _current_all_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from services.db_service import query_df  # type: ignore
        df = query_df("SELECT * FROM time_records ORDER BY id DESC LIMIT 200000")
        if isinstance(df, pd.DataFrame) and not df.empty:
            rows.extend([_row_to_clean_dict(r) | {"_snapshot_source": "sqlite.time_records"} for _, r in df.iterrows()])
    except Exception:
        pass
    rows.extend(_read_authority_rows("01_time_records"))
    rows.extend(_read_authority_rows("02_history"))
    return rows


def _filter_authority_matches(ids: list[int], sqlite_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    id_texts = {str(i) for i in ids}
    rks = {record_key_of(r) for r in sqlite_rows if record_key_of(r)}
    keys = {business_identity_key(r) for r in sqlite_rows if business_identity_key(r)}

    def match(r: dict[str, Any]) -> bool:
        if _get(r, "id") and _get(r, "id") in id_texts:
            return True
        if record_key_of(r) and record_key_of(r) in rks:
            return True
        if business_identity_key(r) in keys:
            return True
        return False

    rows01 = [r for r in _read_authority_rows("01_time_records") if match(r)]
    rows02 = [r for r in _read_authority_rows("02_history") if match(r)]
    return rows01, rows02


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = business_identity_key(r)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _is_time_record_log(action_type: Any, target_table: Any) -> bool:
    table = _clean(target_table).lower()
    action = _clean(action_type).upper()
    if table not in {"time_records", "01_time_records", "02_history", "01 工時紀錄 / 02 歷史紀錄".lower()}:
        return False
    return any(k in action for k in TIME_ACTION_KEYWORDS)


def build_time_record_snapshot_payload(
    action_type: str,
    message: str = "",
    target_table: str = "",
    target_id: str = "",
    detail: str = "",
) -> dict[str, Any] | None:
    """Build a machine-readable full snapshot payload for a time_records LOG row."""
    if not _is_time_record_log(action_type, target_table):
        return None
    if SNAPSHOT_BEGIN in _clean(detail):
        return None
    ids = _parse_candidate_ids(target_id, detail)
    sqlite_rows = _query_sqlite_rows_by_ids(ids)
    auth01, auth02 = _filter_authority_matches(ids, sqlite_rows) if ids or sqlite_rows else ([], [])
    # 優先 02_history，其次 01，再其次 SQLite；若當下 02 還沒同步，SQLite 仍能保留原始輸入。
    best_rows = _dedupe_rows(auth02 + auth01 + sqlite_rows)
    if not best_rows:
        # 不產生空快照，避免 LOG 膨脹；舊 LOG-only recovery 仍會處理這類資料。
        return None
    summaries = [_row_summary(r) for r in best_rows]
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_type": SNAPSHOT_TYPE,
        "captured_at": _now_text(),
        "action_type": _clean(action_type),
        "target_table": _clean(target_table),
        "target_id": _clean(target_id),
        "target_ids": ids,
        "message": _clean(message),
        "recovery_priority": ["row_shard", "time_record_events", "v166c_log_snapshot", "log_only_text"],
        "snapshot_counts": {
            "sqlite_time_records": len(sqlite_rows),
            "authority_01_time_records": len(auth01),
            "authority_02_history": len(auth02),
            "best_rows": len(best_rows),
        },
        "best_summaries": summaries,
        "rows": {
            "best_rows": best_rows,
            "sqlite_time_records": sqlite_rows,
            "authority_01_time_records": auth01,
            "authority_02_history": auth02,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    payload["snapshot_hash"] = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
    return payload


def append_snapshot_to_detail(
    detail: str,
    action_type: str,
    message: str = "",
    target_table: str = "",
    target_id: str = "",
) -> str:
    """Append V166C snapshot JSON to LOG detail when a full row can be located."""
    current = _clean(detail)
    if SNAPSHOT_BEGIN in current:
        return current
    payload = build_time_record_snapshot_payload(action_type, message, target_table, target_id, current)
    if not payload:
        return current
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    prefix = current + "\n\n" if current else ""
    return f"{prefix}{SNAPSHOT_BEGIN}\n{blob}\n{SNAPSHOT_END}"


def extract_snapshot_payloads_from_text(text: Any) -> list[dict[str, Any]]:
    raw = _clean(text)
    if not raw or SNAPSHOT_BEGIN not in raw:
        return []
    out: list[dict[str, Any]] = []
    pattern = re.escape(SNAPSHOT_BEGIN) + r"\s*(\{.*?\})\s*" + re.escape(SNAPSHOT_END)
    for m in re.finditer(pattern, raw, flags=re.S):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict) and data.get("schema_version") == SNAPSHOT_SCHEMA_VERSION:
                out.append(data)
        except Exception:
            continue
    return out


def _payload_best_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    try:
        raw = (((payload or {}).get("rows") or {}).get("best_rows") or [])
        for r in raw:
            if isinstance(r, dict):
                rows.append(_row_to_clean_dict(r))
    except Exception:
        pass
    return rows


def _current_identity_set() -> set[str]:
    keys: set[str] = set()
    for r in _current_all_rows():
        k = business_identity_key(r)
        if k:
            keys.add(k)
    return keys


def _log_key(row: dict[str, Any]) -> str:
    parts = [
        _clean(row.get("id")), _clean(row.get("log_time")), _clean(row.get("action_type")),
        _clean(row.get("target_table")), _clean(row.get("target_id")), _clean(row.get("message")),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()


def collect_log_snapshot_recovery_candidates(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    """Collect V166C snapshot rows and mark whether they are missing from current 01/02/SQLite."""
    try:
        from services.log_service import load_logs  # type: ignore
        logs = load_logs(limit=max(1, int(limit)), start_date=start_date, end_date=end_date, keyword=SNAPSHOT_BEGIN)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "rows": [], "missing_count": 0, "checked_at": _now_text()}
    if not isinstance(logs, pd.DataFrame) or logs.empty:
        return {"ok": True, "rows": [], "candidate_count": 0, "missing_count": 0, "checked_at": _now_text()}
    existing = _current_identity_set()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, lr in logs.iterrows():
        log_row = _row_to_clean_dict(lr)
        payloads = extract_snapshot_payloads_from_text(log_row.get("detail"))
        if not payloads:
            continue
        for payload in payloads:
            for tr in _payload_best_rows(payload):
                identity = business_identity_key(tr)
                uniq = _clean(log_row.get("id")) + "|" + identity
                if not identity or uniq in seen:
                    continue
                seen.add(uniq)
                exists = identity in existing
                s = _row_summary(tr)
                rows.append({
                    "復原 / Recover": not exists,
                    "是否缺失 / Missing": not exists,
                    "log_key": _log_key(log_row),
                    "log_id": _clean(log_row.get("id")),
                    "log_time": _clean(log_row.get("log_time")),
                    "action_type": _clean(log_row.get("action_type")),
                    "target_id": _clean(log_row.get("target_id")),
                    "identity_key": identity,
                    "record_key": s.get("record_key", ""),
                    "id": s.get("id", ""),
                    "工號 / Employee ID": s.get("employee_id", ""),
                    "姓名 / Name": s.get("employee_name", ""),
                    "製令 / Work Order": s.get("work_order", ""),
                    "P/N / 料號": s.get("part_no", ""),
                    "機型 / Model": s.get("type_name", ""),
                    "工段 / Process": s.get("process_name", ""),
                    "狀態 / Status": s.get("status", ""),
                    "開始時間 / Start": s.get("start_timestamp", ""),
                    "結束時間 / End": s.get("end_timestamp", ""),
                    "工時 / Hours": s.get("work_hours", ""),
                    "工時 / HH:MM:SS": s.get("work_hours_hms", ""),
                    "snapshot_hash": _clean(payload.get("snapshot_hash")),
                    "payload": payload,
                    "time_record": tr,
                })
    missing_count = sum(1 for r in rows if r.get("是否缺失 / Missing"))
    return {
        "ok": True,
        "version": "V166C_log_full_snapshot_recovery",
        "checked_at": _now_text(),
        "start_date": start_date or "",
        "end_date": end_date or "",
        "candidate_count": len(rows),
        "missing_count": missing_count,
        "rows": rows,
        "production_write_path_changed": False,
        "safe_recovery_rule": "non_destructive_merge_only",
    }


def _selected_rows_from_snapshot(snapshot: dict[str, Any], selected_keys: list[str] | None = None) -> list[dict[str, Any]]:
    selected = {str(x) for x in (selected_keys or []) if str(x).strip()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in (snapshot or {}).get("rows", []) or []:
        if not isinstance(r, dict):
            continue
        if not bool(r.get("是否缺失 / Missing")):
            continue
        key = str(r.get("identity_key") or "")
        if selected and key not in selected and str(r.get("log_key") or "") not in selected:
            continue
        tr = r.get("time_record") if isinstance(r.get("time_record"), dict) else None
        if not tr:
            continue
        clean = _row_to_clean_dict(tr)
        ik = business_identity_key(clean)
        if not ik or ik in seen:
            continue
        seen.add(ik)
        clean.setdefault("source", "V166C_LOG_FULL_SNAPSHOT_RECOVERY")
        clean["v166c_recovered_from_log"] = "Y"
        clean["v166c_recovered_at"] = _now_text()
        clean["v166c_snapshot_hash"] = _clean(r.get("snapshot_hash"))
        clean["v166c_log_id"] = _clean(r.get("log_id"))
        out.append(clean)
    return out


def recover_records_from_log_snapshots(
    selected_identity_keys: list[str] | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    github: bool = False,
    dry_run: bool = True,
    limit: int = 5000,
) -> dict[str, Any]:
    """Recover missing records from V166C LOG snapshots.

    The function only merges missing records. It never deletes, renumbers, or overwrites existing rows.
    """
    snapshot = collect_log_snapshot_recovery_candidates(start_date=start_date, end_date=end_date, limit=limit)
    if not snapshot.get("ok"):
        snapshot["dry_run"] = dry_run
        return snapshot
    rows = _selected_rows_from_snapshot(snapshot, selected_identity_keys)
    result: dict[str, Any] = {
        "ok": True,
        "version": "V166C_log_full_snapshot_recovery",
        "dry_run": bool(dry_run),
        "checked_at": _now_text(),
        "candidate_count": int(snapshot.get("candidate_count") or 0),
        "missing_count": int(snapshot.get("missing_count") or 0),
        "selected_count": len(rows),
        "recovered_count": 0,
        "github": bool(github),
        "production_write_path_changed": False,
        "recovered_preview": [_row_summary(r) for r in rows[:50]],
    }
    if not rows:
        result["reason"] = "no_selected_missing_rows"
        return result
    if dry_run:
        result["recovered_count"] = len(rows)
        return result
    try:
        import services.time_record_service as trs  # type: ignore
        saved = 0
        save_fn = getattr(trs, "_v151_save_canonical_non_destructive", None)
        if callable(save_fn):
            saved = int(save_fn(pd.DataFrame(rows), "v166c_log_snapshot_precise_recovery", github=bool(github)) or 0)
        else:
            # Fallback: use public save_authority in a non-destructive merge from current all rows + recovered rows.
            existing = _current_all_rows()
            merged = _dedupe_rows(existing + rows)
            from services.permanent_authority_service import save_authority  # type: ignore
            save_authority("01_time_records", records={"time_records": merged}, reason="v166c_log_snapshot_precise_recovery_01", github=bool(github))
            save_authority("02_history", records={"time_records": merged}, reason="v166c_log_snapshot_precise_recovery_02", github=bool(github))
            saved = len(rows)
        durable_fn = getattr(trs, "_v152_write_durable_layers", None)
        if callable(durable_fn):
            durable_fn(pd.DataFrame(rows), "v166c_log_snapshot_precise_recovery", event_type="LOG_SNAPSHOT_RESTORE", github=bool(github), extra={"selected_count": len(rows)})
        try:
            from services.log_service import write_log  # type: ignore
            write_log(
                "V166C_LOG_SNAPSHOT_RECOVERY",
                f"從 V166C LOG 完整快照非破壞式補回 {len(rows)} 筆工時紀錄",
                target_table="time_record_recovery",
                target_id="",
                detail=json.dumps({"selected_count": len(rows), "saved": saved}, ensure_ascii=False),
                level="WARN",
            )
        except Exception:
            pass
        result["recovered_count"] = len(rows)
        result["saved_result"] = saved
        return result
    except Exception as exc:
        result["ok"] = False
        result["reason"] = str(exc)[:800]
        return result


def get_log_snapshot_status(start_date: str | None = None, end_date: str | None = None, limit: int = 2000) -> dict[str, Any]:
    snap = collect_log_snapshot_recovery_candidates(start_date=start_date, end_date=end_date, limit=limit)
    return {
        "ok": bool(snap.get("ok")),
        "version": "V166C",
        "checked_at": _now_text(),
        "candidate_count": int(snap.get("candidate_count") or 0),
        "missing_count": int(snap.get("missing_count") or 0),
        "snapshot_marker": SNAPSHOT_BEGIN,
        "production_write_path_changed": False,
        "reason": snap.get("reason", ""),
    }


def export_log_snapshot_candidates_excel_bytes(snapshot: dict[str, Any]) -> bytes:
    rows = (snapshot or {}).get("rows", []) or []
    # 不把 payload / time_record 大 JSON 塞進 Excel，避免檔案過大。
    flat_rows = []
    for r in rows:
        if isinstance(r, dict):
            x = {k: v for k, v in r.items() if k not in {"payload", "time_record"}}
            flat_rows.append(x)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame(flat_rows).to_excel(writer, index=False, sheet_name="V166C_LOG快照候選")
        pd.DataFrame([{
            "version": (snapshot or {}).get("version", "V166C"),
            "checked_at": (snapshot or {}).get("checked_at", ""),
            "candidate_count": (snapshot or {}).get("candidate_count", 0),
            "missing_count": (snapshot or {}).get("missing_count", 0),
            "rule": "non_destructive_merge_only",
        }]).to_excel(writer, index=False, sheet_name="摘要")
    return bio.getvalue()
