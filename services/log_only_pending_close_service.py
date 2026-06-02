# -*- coding: utf-8 -*-
"""V166B LOG-only pending recovery close service.

Purpose
-------
V164B can restore START_WORK rows that exist only in LOG as conservative
"待人工確認" rows.  Those rows must not be pushed back into the normal 01 Active
Work flow because they are historical rescue rows, not live shop-floor tasks.

This service provides an explicit manual settlement path:
- list pending V164B LOG-only rows;
- suggest an end time from the same employee's next start timestamp;
- close selected rows after an operator/admin confirms the end timestamp;
- calculate work hours with the existing rest-period engine;
- update 01/02 authority files, append V152 event proof, and write V151 row shards.

Safety rules
------------
- Never deletes rows.
- Never renumbers IDs.
- Never marks a pending row as live/active.
- Rejects rows that are already ended.
- Respects V163 daily close lock.
- Does not use a partial UI table to overwrite unrelated history.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
import json
import re

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIME_RECORD_TABLE = "time_records"
PENDING_SOURCE = "V164B_LOG_ONLY_RECOVERY"
CLOSED_SOURCE = "V166B_LOG_ONLY_MANUAL_CLOSED"
VERSION = "V166B_LOG_ONLY_PENDING_CLOSE"

_ALLOWED_CLOSE_STATUSES = {"下班", "暫停", "完工", "補登結束"}


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


def _clean(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan", "nat", "null", "<na>"}:
        return ""
    return text


def _date_part(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = text.replace("/", "-").replace("T", " ")
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
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
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        return _date_part(text) + " 00:00:00"
    return text[:19]


def _parse_dt(value: Any) -> datetime | None:
    ts = _timestamp_text(value)
    if not ts:
        return None
    try:
        dt = pd.to_datetime(ts, errors="coerce")
        if not pd.isna(dt):
            return dt.to_pydatetime().replace(tzinfo=None)
    except Exception:
        pass
    return None


def _hms_from_hours(hours: Any) -> str:
    try:
        total = int(round(float(hours or 0) * 3600))
    except Exception:
        total = 0
    if total < 0:
        total = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _row_get(row: dict[str, Any], *names: str) -> str:
    for name in names:
        if name in row:
            v = _clean(row.get(name))
            if v:
                return v
    return ""


def _record_key(row: dict[str, Any]) -> str:
    return _row_get(row, "record_key", "紀錄鍵 / Record Key", "Record Key")


def _record_id(row: dict[str, Any]) -> str:
    return _row_get(row, "id", "ID", "ID / ID")


def _employee_id(row: dict[str, Any]) -> str:
    emp = _row_get(row, "employee_id", "工號 / Employee ID", "工號", "Employee ID")
    if emp:
        return emp
    rk = _record_key(row)
    if "|" in rk:
        return rk.split("|", 1)[0].strip()
    return ""


def _employee_name(row: dict[str, Any]) -> str:
    return _row_get(row, "employee_name", "姓名 / Name", "姓名", "Employee Name")


def _work_order(row: dict[str, Any]) -> str:
    return _row_get(row, "work_order", "製令 / Work Order", "製令", "Work Order")


def _process_name(row: dict[str, Any]) -> str:
    return _row_get(row, "process_name", "工段 / Process", "製程 / Process", "工段", "製程", "Process")


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
    d = _row_get(row, "start_date", "work_date", "日期 / Date", "開始日期", "工作日期")
    if d:
        return _date_part(d)
    return _date_part(_start_ts(row))


def _status(row: dict[str, Any]) -> str:
    return _row_get(row, "status", "狀態 / Status", "狀態", "Status")


def _is_pending_log_only(row: dict[str, Any]) -> bool:
    if _end_ts(row):
        return False
    source = _clean(row.get("source"))
    recovery = _clean(row.get("recovery_status"))
    status = _status(row)
    remark = _clean(row.get("remark"))
    if source == PENDING_SOURCE:
        return True
    if recovery == "待人工確認":
        return True
    if status == "待人工確認" and PENDING_SOURCE in remark:
        return True
    return False


def _identity_key(row: dict[str, Any]) -> str:
    rk = _record_key(row)
    if rk:
        return "rk|" + rk
    emp = _employee_id(row)
    name = _employee_name(row)
    wo = _work_order(row)
    proc = _process_name(row)
    st = _start_ts(row)
    if emp and wo and proc and st:
        return "biz|" + "|".join([emp, name, wo, proc, st])
    rid = _record_id(row)
    if rid:
        return "id|" + rid
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    import hashlib
    return "hash|" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _row_matches_date(row: dict[str, Any], start_date: str | None, end_date: str | None) -> bool:
    d = _work_date(row)
    if not d:
        return True
    s = _date_part(start_date) if start_date else ""
    e = _date_part(end_date) if end_date else ""
    if s and d < s:
        return False
    if e and d > e:
        return False
    return True


def _load_authority_rows(module_key: str) -> list[dict[str, Any]]:
    try:
        from services.permanent_authority_service import load_tables  # type: ignore
        rows = (load_tables(module_key, "records") or {}).get(TIME_RECORD_TABLE, [])
        return [dict(r) for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def _save_authority_rows(module_key: str, rows: list[dict[str, Any]], reason: str, github: bool) -> dict[str, Any]:
    from services.permanent_authority_service import save_authority  # type: ignore
    return save_authority(module_key, records={TIME_RECORD_TABLE: rows}, reason=reason, github=bool(github))


def _merged_rows_for_suggestion(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    try:
        from services.time_record_integrity_service import merge_time_records_non_destructive  # type: ignore
        df, _counts = merge_time_records_non_destructive(start_date=start_date, end_date=end_date)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return [dict(r) for _, r in df.where(pd.notna(df), "").iterrows()]
    except Exception:
        pass
    rows = _load_authority_rows("01_time_records") + _load_authority_rows("02_history")
    by_key: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_key.setdefault(_identity_key(r), r)
    return list(by_key.values())


def _suggest_next_start(row: dict[str, Any], all_rows: list[dict[str, Any]], *, max_hours: int = 18) -> tuple[str, str]:
    emp = _employee_id(row)
    start = _parse_dt(_start_ts(row))
    if not emp or start is None:
        return "", "無法建議：缺少工號或開始時間"
    limit = start + timedelta(hours=max(1, int(max_hours)))
    same_day = start.strftime("%Y-%m-%d")
    best: datetime | None = None
    best_row: dict[str, Any] = {}
    this_key = _identity_key(row)
    for cand in all_rows:
        if _identity_key(cand) == this_key:
            continue
        if _employee_id(cand) != emp:
            continue
        cstart = _parse_dt(_start_ts(cand))
        if cstart is None or cstart <= start or cstart > limit:
            continue
        # Prefer same work date. Cross-day within max_hours is allowed only if no same-day exists.
        if _date_part(cstart) != same_day and best is not None and _date_part(best) == same_day:
            continue
        if best is None or cstart < best:
            best = cstart
            best_row = cand
    if best is None:
        return "", f"找不到同工號 {max_hours} 小時內的下一筆開始時間，需手動輸入"
    wo = _work_order(best_row)
    proc = _process_name(best_row)
    return best.strftime("%Y-%m-%d %H:%M:%S"), f"同工號下一筆開始：{wo} / {proc}"


def collect_log_only_pending_close_candidates(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    suggestion_max_hours: int = 18,
) -> dict[str, Any]:
    """Collect pending V164B LOG-only records for manual settlement."""
    s = _date_part(start_date) if start_date else None
    e = _date_part(end_date) if end_date else None
    all_rows = _merged_rows_for_suggestion(start_date=s, end_date=e)
    pending: dict[str, dict[str, Any]] = {}
    # Prefer explicit 01/02 authority rows so we do not accidentally present old event snapshots.
    for r in _load_authority_rows("01_time_records") + _load_authority_rows("02_history"):
        if not _row_matches_date(r, s, e):
            continue
        if not _is_pending_log_only(r):
            continue
        pending.setdefault(_identity_key(r), dict(r))

    table_rows: list[dict[str, Any]] = []
    for key, row in sorted(pending.items(), key=lambda kv: (_start_ts(kv[1]), _employee_id(kv[1]), _work_order(kv[1]))):
        suggested_end, reason = _suggest_next_start(row, all_rows, max_hours=suggestion_max_hours)
        default_status = "暫停" if suggested_end else "補登結束"
        table_rows.append({
            "結算 / Close": False,
            "identity_key": key,
            "record_key": _record_key(row),
            "id": _record_id(row),
            "工號 / Employee ID": _employee_id(row),
            "姓名 / Name": _employee_name(row),
            "製令 / Work Order": _work_order(row),
            "工段 / Process": _process_name(row),
            "開始時間 / Start": _start_ts(row),
            "建議結束時間 / Suggested End": suggested_end,
            "結束時間 / End Timestamp": suggested_end,
            "結束狀態 / Close Status": default_status,
            "補登備註 / Close Note": "",
            "建議來源 / Suggestion": reason,
            "source": _clean(row.get("source")),
            "recovery_status": _clean(row.get("recovery_status")),
        })
    df = pd.DataFrame(table_rows)
    return {
        "ok": True,
        "version": VERSION,
        "checked_at": _now_text(),
        "start_date": s,
        "end_date": e,
        "pending_count": len(table_rows),
        "suggested_count": int(sum(1 for r in table_rows if _clean(r.get("建議結束時間 / Suggested End")))),
        "rows": table_rows,
        "dataframe": df,
    }


def _normalize_request(req: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_key": _clean(req.get("identity_key")),
        "record_key": _clean(req.get("record_key")),
        "id": _clean(req.get("id")),
        "end_timestamp": _timestamp_text(req.get("end_timestamp") or req.get("結束時間 / End Timestamp") or req.get("end_ts")),
        "close_status": _clean(req.get("close_status") or req.get("結束狀態 / Close Status") or "補登結束"),
        "note": _clean(req.get("note") or req.get("補登備註 / Close Note")),
    }


def _request_key(req: dict[str, Any]) -> str:
    if req.get("identity_key"):
        return str(req["identity_key"])
    if req.get("record_key"):
        return "rk|" + str(req["record_key"])
    if req.get("id"):
        return "id|" + str(req["id"])
    return ""


def _assert_dates_open(start_ts: str, end_ts: str) -> None:
    try:
        from services.daily_close_service import assert_work_date_open  # type: ignore
        sd = _date_part(start_ts)
        ed = _date_part(end_ts)
        if sd:
            assert_work_date_open(sd, operation="V166B LOG-only 補登結算")
        if ed and ed != sd:
            assert_work_date_open(ed, operation="V166B LOG-only 補登結算")
    except ImportError:
        return


def _calculate_hours(start_ts: str, end_ts: str) -> float:
    from services.calculation_service import calculate_work_hours  # type: ignore
    return float(calculate_work_hours(start_ts, end_ts))


def _close_one_row(row: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    if not _is_pending_log_only(row):
        raise ValueError("此紀錄不是 V164B LOG-only 待人工確認資料，拒絕結算。")
    if _end_ts(row):
        raise ValueError("此紀錄已經有結束時間，拒絕重複結算。")
    start_ts = _start_ts(row)
    end_ts = _timestamp_text(req.get("end_timestamp"))
    if not start_ts:
        raise ValueError("缺少開始時間，無法計算工時。")
    if not end_ts:
        raise ValueError("缺少結束時間，請手動輸入。")
    sdt = _parse_dt(start_ts)
    edt = _parse_dt(end_ts)
    if sdt is None or edt is None:
        raise ValueError("開始或結束時間格式無法解析。")
    if edt <= sdt:
        raise ValueError(f"結束時間必須大於開始時間：start={start_ts}, end={end_ts}")
    if edt - sdt > timedelta(hours=24):
        raise ValueError("補登結算時間跨度超過 24 小時，請人工拆分或重新確認。")
    _assert_dates_open(start_ts, end_ts)
    status = _clean(req.get("close_status")) or "補登結束"
    if status not in _ALLOWED_CLOSE_STATUSES:
        raise ValueError(f"不支援的結束狀態：{status}")
    hours = round(_calculate_hours(start_ts, end_ts), 6)
    hms = _hms_from_hours(hours)
    now = _now_text()
    note = _clean(req.get("note"))
    old_remark = _clean(row.get("remark"))
    add_remark = f"V166B_LOG_ONLY_MANUAL_CLOSED：人工補登結算，結束時間={end_ts}，工時={hms}。"
    if note:
        add_remark += f" 備註：{note}"
    remark = (old_remark + "；" if old_remark else "") + add_remark
    out = dict(row)
    out.update({
        "status": status,
        "end_action": status,
        "end_timestamp": end_ts,
        "end_date": _date_part(end_ts),
        "end_time": end_ts[11:19] if len(end_ts) >= 19 else "",
        "work_hours": hours,
        "work_hours_hms": hms,
        "remark": remark,
        "source": CLOSED_SOURCE,
        "recovery_status": "已人工結算",
        "recovery_closed_at": now,
        "recovery_closed_source": VERSION,
        "updated_at": now,
    })
    return out


def _apply_updates(rows: list[dict[str, Any]], requests_by_key: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    out_rows: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    matched: set[str] = set()
    for row in rows:
        key = _identity_key(row)
        req = requests_by_key.get(key)
        if req is None:
            out_rows.append(row)
            continue
        matched.add(key)
        try:
            new_row = _close_one_row(row, req)
            out_rows.append(new_row)
            updated.append(new_row)
        except Exception as exc:
            out_rows.append(row)
            errors.append({"identity_key": key, "record_key": _record_key(row), "error": str(exc)})
    for key, req in requests_by_key.items():
        if key not in matched:
            errors.append({"identity_key": key, "record_key": req.get("record_key", ""), "error": "在 01/02 權威檔找不到對應待補紀錄"})
    return out_rows, updated, errors


def _write_durable_layers(rows: list[dict[str, Any]], *, reason: str, github: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"event_ids": [], "row_shards": 0, "log_ok": False, "warnings": []}
    if not rows:
        return result
    try:
        from services.time_record_event_journal_service import append_time_record_event  # type: ignore
        event_ids = append_time_record_event(
            "MANUAL_CLOSE_LOG_ONLY_RECOVERY",
            rows,
            reason=reason,
            payload_extra={"version": VERSION, "source": CLOSED_SOURCE},
            schedule_upload=True,
        )
        result["event_ids"] = event_ids
    except Exception as exc:
        result["warnings"].append(f"event_journal_write_failed: {exc}")
    try:
        # V151 private helper is intentionally reused as a best-effort compatibility bridge.
        import services.time_record_service as trs  # type: ignore
        fn = getattr(trs, "_v151_write_row_shards", None)
        if callable(fn):
            result["row_shards"] = int(fn(rows, reason, github=bool(github)) or 0)
        else:
            result["warnings"].append("row_shard_helper_unavailable")
    except Exception as exc:
        result["warnings"].append(f"row_shard_write_failed: {exc}")
    try:
        from services.log_service import write_log  # type: ignore
        write_log(
            "MANUAL_CLOSE_LOG_ONLY_RECOVERY",
            f"V166B LOG-only 待補紀錄人工結算 {len(rows)} 筆",
            "time_records",
            ",".join(_record_id(r) or _record_key(r) for r in rows[:20]),
            json.dumps({"count": len(rows), "version": VERSION}, ensure_ascii=False),
            "INFO",
        )
        result["log_ok"] = True
    except Exception as exc:
        result["warnings"].append(f"write_log_failed: {exc}")
    return result


def close_log_only_pending_records(
    requests: Iterable[dict[str, Any]],
    *,
    github: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Close selected V164B LOG-only pending rows after manual confirmation.

    requests accepts dictionaries with:
    - identity_key or record_key or id
    - end_timestamp
    - close_status: 下班 / 暫停 / 完工 / 補登結束
    - note
    """
    normalized = [_normalize_request(dict(r or {})) for r in requests or []]
    normalized = [r for r in normalized if _request_key(r)]
    if not normalized:
        return {"ok": False, "reason": "no_selected_requests", "version": VERSION}

    req_by_key: dict[str, dict[str, Any]] = {}
    for req in normalized:
        key = _request_key(req)
        if key:
            req_by_key[key] = req

    existing_01 = _load_authority_rows("01_time_records")
    existing_02 = _load_authority_rows("02_history")
    rows_01, updated_01, errors_01 = _apply_updates(existing_01, req_by_key)
    rows_02, updated_02, errors_02 = _apply_updates(existing_02, req_by_key)

    # Consolidate updated rows by identity key so event/shard proof is not duplicated.
    updated_map: dict[str, dict[str, Any]] = {}
    for r in updated_01 + updated_02:
        updated_map[_identity_key(r)] = r
    updated_rows = list(updated_map.values())
    errors = errors_01 + [e for e in errors_02 if e not in errors_01]
    if not updated_rows:
        return {
            "ok": False,
            "version": VERSION,
            "dry_run": bool(dry_run),
            "reason": "no_rows_updated",
            "requested_count": len(req_by_key),
            "errors": errors[:100],
        }

    result: dict[str, Any] = {
        "ok": len(errors) == 0,
        "version": VERSION,
        "dry_run": bool(dry_run),
        "requested_count": len(req_by_key),
        "closed_count": len(updated_rows),
        "errors_count": len(errors),
        "errors": errors[:100],
        "closed_preview": [
            {
                "record_key": _record_key(r),
                "id": _record_id(r),
                "employee_id": _employee_id(r),
                "employee_name": _employee_name(r),
                "work_order": _work_order(r),
                "process_name": _process_name(r),
                "start_timestamp": _start_ts(r),
                "end_timestamp": _end_ts(r),
                "status": _status(r),
                "work_hours": r.get("work_hours", ""),
                "work_hours_hms": r.get("work_hours_hms", ""),
            }
            for r in updated_rows[:100]
        ],
    }
    if dry_run:
        result["ok"] = True if updated_rows else False
        return result

    try:
        save_01 = _save_authority_rows("01_time_records", rows_01, "v166b_log_only_pending_manual_close_01", github=bool(github))
        save_02 = _save_authority_rows("02_history", rows_02, "v166b_log_only_pending_manual_close_02", github=bool(github))
        durable = _write_durable_layers(updated_rows, reason="v166b_log_only_pending_manual_close", github=False)
        result.update({"save_01": save_01, "save_02": save_02, "durable": durable})
        result["ok"] = len(errors) == 0
        try:
            from services.db_service import clear_query_cache, mark_data_changed  # type: ignore
            clear_query_cache()
            mark_data_changed()
        except Exception:
            pass
        return result
    except Exception as exc:
        result["ok"] = False
        result["reason"] = str(exc)
        return result


def export_pending_close_excel_bytes(snapshot: dict[str, Any]) -> bytes:
    output = BytesIO()
    rows = snapshot.get("rows", []) if isinstance(snapshot, dict) else []
    summary = {k: v for k, v in (snapshot or {}).items() if k not in {"rows", "dataframe"}}
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([summary]).to_excel(writer, sheet_name="摘要", index=False)
        pd.DataFrame(rows).to_excel(writer, sheet_name="待補結算", index=False)
    return output.getvalue()


# Backward/English aliases for future tools.
collect_pending_close_candidates = collect_log_only_pending_close_candidates
close_pending_log_only_records = close_log_only_pending_records
export_pending_close_excel = export_pending_close_excel_bytes
