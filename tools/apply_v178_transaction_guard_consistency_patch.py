# -*- coding: utf-8 -*-
"""Apply V178 transaction duplicate guard and 01/02 consistency patch.

Safe patch rules:
- append-only patch blocks; no CSS/theme/page rendering changes;
- does not overwrite user data;
- backs up touched Python files;
- idempotent: running twice does not duplicate blocks.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

TIME_RECORD_BLOCK_MARKER = "# ======================= V178 TRANSACTION DUPLICATE GUARD + CONSISTENCY ======================="
LOG_BLOCK_MARKER = "# ======================= V178 TIME-RECORD LOG DEDUPE GUARD ======================="

TIME_RECORD_BLOCK = r'''
# ======================= V178 TRANSACTION DUPLICATE GUARD + CONSISTENCY =======================
# Backend-only safety patch:
# - prevent repeated Streamlit rerun from inserting / logging the same operation several times;
# - keep 01 Today Records and 02 History display aligned by filtering tombstones;
# - block deleted rows from coming back through SQLite / row shard / event journal merge;
# - do not change CSS, theme, page layout, table rendering, or field display.
try:
    from services import time_record_transaction_guard_service as _v178_guard
except Exception:  # pragma: no cover
    _v178_guard = None  # type: ignore

try:
    _v178_prev_start_work = start_work
    _v178_prev_finish_work = finish_work
    _v178_prev_load_records = load_records
    _v178_prev_today_records = today_records
    _v178_prev_delete_time_records = delete_time_records
    _v178_prev_save_time_records = save_time_records
    _v178_prev_recalculate_time_records = recalculate_time_records
    _v178_prev_import_time_records = import_time_records
    _v178_prev_get_active_records = get_active_records
    _v178_prev_get_active_record = get_active_record
    _v178_prev_get_active_group = get_active_group
except Exception:
    pass


def _v178_guard_available() -> bool:
    return _v178_guard is not None


def _v178_safe_log(action: str, message: str, level: str = "INFO") -> None:
    try:
        write_log(action, message, "time_records", level=level)
    except Exception:
        pass


def _v178_filter_df(df):
    try:
        if _v178_guard_available():
            return _v178_guard.filter_and_dedupe_df(df)
    except Exception:
        pass
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _v178_filter_active_df(df):
    try:
        if _v178_guard_available():
            return _v178_guard.filter_active_df(df)
    except Exception:
        pass
    return _v178_filter_df(df)


def _v178_history_authority_df():
    """02_history authority is the preferred display source for 01 Today Records."""
    try:
        from services.permanent_authority_service import df_from_table
        df = df_from_table("02_history", "time_records")
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _v178_filter_records_by_args(df, start_date=None, end_date=None, employee_id=None, work_order=None):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    x = df.copy()
    try:
        date_col = "start_date" if "start_date" in x.columns else ("work_date" if "work_date" in x.columns else None)
        if date_col:
            if start_date:
                x = x[x[date_col].astype(str) >= str(start_date)]
            if end_date:
                x = x[x[date_col].astype(str) <= str(end_date)]
        elif "start_timestamp" in x.columns:
            if start_date:
                x = x[x["start_timestamp"].astype(str).str[:10] >= str(start_date)]
            if end_date:
                x = x[x["start_timestamp"].astype(str).str[:10] <= str(end_date)]
        if employee_id and "employee_id" in x.columns:
            x = x[x["employee_id"].astype(str) == str(employee_id)]
        if work_order and "work_order" in x.columns:
            x = x[x["work_order"].astype(str) == str(work_order)]
    except Exception:
        pass
    return x.reset_index(drop=True)


def _v178_current_cycle_start() -> str:
    try:
        return _business_cycle_start_date()
    except Exception:
        try:
            return today_text()
        except Exception:
            return str(pd.Timestamp.today())[:10]


def _v178_is_active_display_row(row: dict) -> bool:
    try:
        if _v178_guard_available() and not _v178_guard.active_row_is_safe(row):
            return False
    except Exception:
        pass
    status = str((row or {}).get("status") or "").strip()
    end_ts = str((row or {}).get("end_timestamp") or "").strip().lower()
    source = str((row or {}).get("source") or "").strip()
    record_key = str((row or {}).get("record_key") or "").strip()
    if source in {"V164B_LOG_ONLY_RECOVERY", "LOG_ONLY_RECOVERY", "LOGRECOVERY"} or record_key.startswith("LOGRECOVERY|"):
        return False
    return status in {"", "作業中"} and end_ts in {"", "none", "nan", "nat"}


def _v178_today_display_filter(df, unfinished_only: bool = False):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    x = _v178_filter_df(df)
    if x.empty:
        return x
    try:
        active_mask = x.apply(lambda r: _v178_is_active_display_row(dict(r)), axis=1)
        if unfinished_only:
            return x.loc[active_mask].copy().reset_index(drop=True)
        cycle_start = _v178_current_cycle_start()
        if "start_date" in x.columns:
            current = x["start_date"].astype(str) >= str(cycle_start)
        elif "start_timestamp" in x.columns:
            current = x["start_timestamp"].astype(str).str[:10] >= str(cycle_start)
        else:
            current = pd.Series([True] * len(x), index=x.index)
        return x.loc[current | active_mask].copy().reset_index(drop=True)
    except Exception:
        return x


def _v178_write_filtered_authority(reason: str = "v178_consistency_sync", github: bool = False) -> int:
    """Write filtered display-consistent rows to 01/02 authority without GitHub wait."""
    df = pd.DataFrame()
    try:
        if callable(_v178_prev_load_records):
            df = _v178_prev_load_records()
    except Exception:
        df = pd.DataFrame()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        df = _v178_history_authority_df()
    df = _v178_filter_df(df)
    rows = []
    try:
        from services.permanent_authority_service import table_from_df, update_tables
        rows = table_from_df(df) if not df.empty else []
        try:
            update_tables("01_time_records", {"time_records": rows}, reason=reason + "_01", github=bool(github))
        except TypeError:
            update_tables("01_time_records", {"time_records": rows}, reason=reason + "_01")
        try:
            update_tables("02_history", {"time_records": rows}, reason=reason + "_02", github=bool(github))
        except TypeError:
            update_tables("02_history", {"time_records": rows}, reason=reason + "_02")
    except Exception as exc:
        _v178_safe_log("V178_AUTHORITY_SYNC_ERROR", f"V178 01/02 權威同步失敗：{exc}", level="ERROR")
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    """02/01 visible history after V178 tombstone + dedupe filtering."""
    df = _v178_history_authority_df()
    if df is None or df.empty:
        try:
            df = _v178_prev_load_records(start_date, end_date, employee_id, work_order)
            return _v178_filter_df(df)
        except Exception:
            return pd.DataFrame()
    df = _v178_filter_records_by_args(df, start_date, end_date, employee_id, work_order)
    return _v178_filter_df(df)


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    """01 Today Records uses the same 02-history authority, with 01 display rules."""
    df = _v178_history_authority_df()
    if df is None or df.empty:
        try:
            df = _v178_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only)
        except Exception:
            df = pd.DataFrame()
    if not include_finished:
        unfinished_only = True
    return _v178_today_display_filter(df, unfinished_only=bool(unfinished_only))


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    try:
        df = _v178_prev_get_active_records(employee_id=employee_id, process_name=process_name, start_date=start_date, employee_name=employee_name)
    except Exception:
        df = pd.DataFrame()
    return _v178_filter_active_df(df)


def get_active_record(employee_id: str) -> dict | None:  # type: ignore[override]
    try:
        rec = _v178_prev_get_active_record(employee_id)
        if rec and _v178_guard_available() and not _v178_guard.active_row_is_safe(rec):
            return None
        return rec
    except Exception:
        return None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    try:
        df = _v178_prev_get_active_group(record_id)
    except Exception:
        df = pd.DataFrame()
    return _v178_filter_active_df(df)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if not callable(_v178_prev_start_work):
        raise RuntimeError("start_work core implementation unavailable")
    op_key = ""
    claimed = {"claimed": True}
    if _v178_guard_available():
        op_key = _v178_guard.start_op_key(employee or {}, work_order or {}, process_name, bucket_seconds=8)
        claimed = _v178_guard.claim_operation("START_WORK", op_key, ttl_seconds=10, payload={"employee": employee, "work_order": work_order, "process_name": process_name})
        if not claimed.get("claimed"):
            rid = int(claimed.get("result_id") or 0)
            if rid:
                return rid
            # If the first request is still finishing, check whether the active row already exists.
            try:
                emp_id = str((employee or {}).get("employee_id") or "").strip()
                emp_name = str((employee or {}).get("employee_name") or "").strip()
                wo_no = str((work_order or {}).get("work_order") or "").strip()
                proc = str(process_name or "").strip()
                rec = get_active_same_work(emp_id, wo_no, proc, employee_name=emp_name)
                if rec:
                    return int(rec.get("id") or 0)
            except Exception:
                pass
            # Last chance: wait briefly for the claimed operation to complete.
            try:
                import time as _time
                for _ in range(6):
                    _time.sleep(0.25)
                    op = _v178_guard.lookup_operation(op_key)
                    rid = int(op.get("result_id") or 0)
                    if rid:
                        return rid
            except Exception:
                pass
            raise ValueError("偵測到重複開始作業請求，系統已防止重複新增，請重新整理確認目前作業中紀錄。")
    try:
        rid = int(_v178_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
        if _v178_guard_available() and op_key:
            _v178_guard.complete_operation(op_key, result_id=rid, result_count=1, status="DONE")
        if rid:
            try:
                _v178_write_filtered_authority("start_work_v178_consistency", github=False)
            except Exception:
                pass
        return rid
    except Exception:
        if _v178_guard_available() and op_key:
            _v178_guard.complete_operation(op_key, result_id=0, result_count=0, status="ERROR")
        raise


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v178_prev_finish_work):
        raise RuntimeError("finish_work core implementation unavailable")
    op_key = ""
    if _v178_guard_available():
        op_key = _v178_guard.finish_op_key(record_id, end_action, bucket_seconds=8)
        claimed = _v178_guard.claim_operation("FINISH_WORK", op_key, ttl_seconds=10, payload={"record_id": record_id, "end_action": end_action})
        if not claimed.get("claimed"):
            cnt = int(claimed.get("result_count") or 0)
            return cnt
    try:
        n = int(_v178_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
        if _v178_guard_available() and op_key:
            _v178_guard.complete_operation(op_key, result_id=int(record_id or 0), result_count=n, status="DONE")
        if n:
            try:
                _v178_write_filtered_authority("finish_work_v178_consistency", github=False)
            except Exception:
                pass
        return n
    except Exception:
        if _v178_guard_available() and op_key:
            _v178_guard.complete_operation(op_key, result_id=int(record_id or 0), result_count=0, status="ERROR")
        raise


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = []
    for x in record_ids or []:
        try:
            i = int(float(str(x).strip()))
            if i > 0 and i not in ids:
                ids.append(i)
        except Exception:
            pass
    if not ids:
        return 0
    evidence = []
    try:
        if _v178_guard_available():
            evidence = _v178_guard.rows_by_ids(ids)
            _v178_guard.add_tombstones(evidence, reason=reason)
    except Exception:
        evidence = []
    deleted = 0
    try:
        deleted = int(_v178_prev_delete_time_records(ids, reason=reason) or 0)
    except Exception as exc:
        # Keep tombstone protection even when SQLite/cache delete fails.
        _v178_safe_log("V178_DELETE_BASE_ERROR", f"V178 原刪除流程失敗，已保留 tombstone：{exc}", level="ERROR")
    try:
        if _v178_guard_available():
            _v178_guard.purge_tombstoned_from_sqlite()
    except Exception:
        pass
    synced = _v178_write_filtered_authority("delete_time_records_v178_tombstone", github=False)
    final = int(deleted or len(evidence) or 0)
    if final:
        _v178_safe_log("DELETE_TIME_RECORDS_V178", f"{reason}：已建立刪除 tombstone，01/02 顯示同步；刪除 {final} 筆，同步保留 {synced} 筆。", level="WARN")
    return final


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = int(_v178_prev_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps) or 0) if callable(_v178_prev_save_time_records) else 0
    if n:
        try:
            if _v178_guard_available():
                _v178_guard.purge_tombstoned_from_sqlite()
        except Exception:
            pass
        _v178_write_filtered_authority("save_time_records_v178_consistency", github=False)
    return n


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    n = int(_v178_prev_recalculate_time_records(record_ids) or 0) if callable(_v178_prev_recalculate_time_records) else 0
    if n:
        _v178_write_filtered_authority("recalculate_time_records_v178_consistency", github=False)
    return n


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    result = _v178_prev_import_time_records(df, recalc=recalc, source=source) if callable(_v178_prev_import_time_records) else {"inserted": 0, "updated": 0, "skipped": 0}
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        try:
            if _v178_guard_available():
                _v178_guard.purge_tombstoned_from_sqlite()
        except Exception:
            pass
        _v178_write_filtered_authority("import_time_records_v178_consistency", github=False)
    return result


def sync_time_records_01_02_now(reason: str = "v178_manual_consistency_sync", *, github: bool = True) -> int:  # type: ignore[override]
    try:
        if _v178_guard_available():
            _v178_guard.purge_tombstoned_from_sqlite()
    except Exception:
        pass
    return _v178_write_filtered_authority(reason, github=bool(github))


def audit_time_record_integrity_v178() -> dict:
    out = {"version": "V178", "ok": True}
    try:
        if _v178_guard_available():
            out.update(_v178_guard.audit_v178_state())
    except Exception as exc:
        out["ok"] = False
        out["guard_error"] = str(exc)[:300]
    try:
        today_df = today_records()
        hist_df = load_records()
        out["today_visible_rows"] = int(len(today_df)) if isinstance(today_df, pd.DataFrame) else 0
        out["history_visible_rows"] = int(len(hist_df)) if isinstance(hist_df, pd.DataFrame) else 0
    except Exception as exc:
        out["ok"] = False
        out["display_error"] = str(exc)[:300]
    return out

try:
    if _v178_guard_available():
        _v178_guard.ensure_v178_schema()
except Exception:
    pass
# ===================== END V178 TRANSACTION DUPLICATE GUARD + CONSISTENCY =====================
'''

LOG_BLOCK = r'''
# ======================= V178 TIME-RECORD LOG DEDUPE GUARD =======================
# Backend-only LOG de-duplication for exact duplicate time-record logs generated by
# Streamlit rerun/double-click.  It does not remove existing logs and does not change
# the 06 LOG display format.
try:
    _v178_prev_write_log = write_log
except Exception:
    _v178_prev_write_log = None


def _v178_log_guard_key(action_type, message, target_table, target_id, detail, level) -> str:
    try:
        import hashlib, time
        bucket = int(time.time() // 3)
        raw = "|".join([
            str(action_type or ""), str(message or ""), str(target_table or ""),
            str(target_id or ""), str(detail or ""), str(level or ""), str(bucket),
        ])
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
    except Exception:
        return ""


def write_log(action_type: str, message: str, target_table: str = "", target_id: str = "", detail: str = "", level: str = "INFO", user_name: str | None = None) -> None:  # type: ignore[override]
    if callable(_v178_prev_write_log):
        table = str(target_table or "")
        action = str(action_type or "").upper()
        # Only suppress exact duplicates in time-record operation logs.  Other logs are unchanged.
        if table == "time_records" or action in {"START_WORK", "INSERT", "END_WORK", "END_WORK_GROUP", "FINISH_WORK", "DELETE_TIME_RECORDS", "SAVE_TIME_RECORDS"}:
            try:
                from services import time_record_transaction_guard_service as _g
                key = _v178_log_guard_key(action_type, message, target_table, target_id, detail, level)
                claimed = _g.claim_operation("LOG_" + action, key, ttl_seconds=4, payload={"action_type": action_type, "target_table": target_table, "target_id": target_id})
                if not claimed.get("claimed"):
                    return None
                _v178_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name=user_name)
                _g.complete_operation(key, result_id=0, result_count=1, status="DONE")
                return None
            except Exception:
                pass
        return _v178_prev_write_log(action_type, message, target_table, target_id, detail, level, user_name=user_name)
    return None
# ===================== END V178 TIME-RECORD LOG DEDUPE GUARD =====================
'''


def backup(path: Path) -> None:
    if path.exists():
        bak = path.with_suffix(path.suffix + f".bak_v178_{STAMP}")
        shutil.copy2(path, bak)


def append_once(path: Path, marker: str, block: str) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in text:
        return False
    backup(path)
    path.write_text(text.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")
    return True


def main() -> int:
    svc = ROOT / "services" / "time_record_transaction_guard_service.py"
    if not svc.exists():
        raise SystemExit("缺少 services/time_record_transaction_guard_service.py，請確認 V178 修正包已完整複製。")
    changed = []
    tr = ROOT / "services" / "time_record_service.py"
    lg = ROOT / "services" / "log_service.py"
    if append_once(tr, TIME_RECORD_BLOCK_MARKER, TIME_RECORD_BLOCK):
        changed.append(str(tr.relative_to(ROOT)))
    if append_once(lg, LOG_BLOCK_MARKER, LOG_BLOCK):
        changed.append(str(lg.relative_to(ROOT)))
    print("V178 patch applied.")
    if changed:
        print("Modified:")
        for p in changed:
            print(" -", p)
    else:
        print("No changes needed; V178 blocks already exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
