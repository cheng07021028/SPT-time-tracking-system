# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, date, timedelta
import sqlite3
import uuid
import pandas as pd

from services.timezone_service import now_text, now_stamp, today_text, today_date, taiwan_now

from .db_service import DB_PATH, clear_query_cache, execute, mark_data_changed, query_df, query_one
from .calculation_service import calculate_work_hours, split_timestamp
from .log_service import write_log
from .duration_service import hms_to_hours



def ensure_time_records_available(trigger: str = "time_record_service") -> None:
    """V3.02: restore 01/02 shared records if DB was recreated empty after update."""
    try:
        from services.time_records_guard_service import rescue_time_records_if_empty
        rescue_time_records_if_empty(trigger=trigger)
    except Exception:
        pass

def _now() -> str:
    return now_text()



def _is_blank_value(value) -> bool:
    """Return True for empty / None / NaN / textual None values from Streamlit data_editor."""
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"none", "nan", "nat", "null"}


def _clean_text_value(value):
    if _is_blank_value(value):
        return None
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _normalize_time_text(value) -> str | None:
    if _is_blank_value(value):
        return None
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    try:
        # pandas/Excel may provide datetime.time-like objects.
        if hasattr(value, "hour") and hasattr(value, "minute"):
            sec = int(getattr(value, "second", 0) or 0)
            return f"{int(value.hour):02d}:{int(value.minute):02d}:{sec:02d}"
    except Exception:
        pass
    text = str(value).strip().replace("：", ":")
    if " " in text and any(sep in text for sep in ("-", "/")):
        text = text.split(" ")[-1]
    if "T" in text:
        text = text.split("T")[-1]
    parts = text.split(":")
    try:
        h = int(float(parts[0]))
        m = int(float(parts[1])) if len(parts) > 1 else 0
        sec = int(float(parts[2])) if len(parts) > 2 else 0
        if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= sec <= 59:
            return f"{h:02d}:{m:02d}:{sec:02d}"
    except Exception:
        return text[:8] if text else None
    return None


def _normalize_date_text(value) -> str | None:
    if _is_blank_value(value):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if not pd.isna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    text = text.replace("/", "-")
    return text[:10]


def _normalize_timestamp_value(timestamp_value=None, date_value=None, time_value=None) -> str | None:
    """Normalize timestamp/date/time edits into 'YYYY-MM-DD HH:MM:SS'.

    Priority:
    1. If timestamp contains a date/time, use it.
    2. If timestamp is date-only and time field exists, combine them.
    3. If timestamp is empty, combine date + time.

    This is used after manual edits in 01/02 so changing Start Timestamp or End
    Timestamp also refreshes Start Date/Time and End Date/Time consistently.
    """
    ts = None if _is_blank_value(timestamp_value) else timestamp_value
    d = _normalize_date_text(date_value)
    t = _normalize_time_text(time_value)

    if ts is not None:
        if isinstance(ts, datetime):
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(ts, date):
            return f"{ts.strftime('%Y-%m-%d')} {t or '00:00:00'}"
        text = str(ts).strip().replace("/", "-").replace("T", " ")
        # Try pandas first to support 2026/5/7 8:03, Timestamp, Excel-like strings.
        try:
            dt = pd.to_datetime(text, errors="coerce")
            if not pd.isna(dt):
                # If user typed date-only timestamp and provided a time field, keep that time.
                if (":" not in text) and t:
                    return f"{dt.strftime('%Y-%m-%d')} {t}"
                return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        # Fallback: split manually.
        if " " in text:
            date_part, time_part = text.split(" ", 1)
            nd = _normalize_date_text(date_part)
            nt = _normalize_time_text(time_part)
            if nd:
                return f"{nd} {nt or t or '00:00:00'}"
        nd = _normalize_date_text(text)
        if nd:
            return f"{nd} {t or '00:00:00'}"

    if d:
        return f"{d} {t or '00:00:00'}"
    return None


def normalize_record_datetime_fields(row: dict | pd.Series, recalc_work_hours: bool = False) -> dict:
    """Return normalized time/date fields for an edited time-record row.

    If Start/End Timestamp is edited manually, this function confirms and rewrites:
    - start_date / start_time
    - end_date / end_time
    - work_hours when recalc_work_hours=True and both timestamps exist
    """
    get = row.get if hasattr(row, "get") else lambda k, default=None: default
    start_ts = _normalize_timestamp_value(get("start_timestamp"), get("start_date"), get("start_time"))
    end_ts = _normalize_timestamp_value(get("end_timestamp"), get("end_date"), get("end_time"))

    out: dict = {}
    if start_ts:
        out["start_timestamp"] = start_ts
        out["start_date"], out["start_time"] = split_timestamp(start_ts)
    else:
        out["start_timestamp"] = None
        out["start_date"] = _normalize_date_text(get("start_date"))
        out["start_time"] = _normalize_time_text(get("start_time"))

    if end_ts:
        out["end_timestamp"] = end_ts
        out["end_date"], out["end_time"] = split_timestamp(end_ts)
    else:
        out["end_timestamp"] = None
        out["end_date"] = None
        out["end_time"] = None

    if recalc_work_hours and start_ts and end_ts:
        out["work_hours"] = calculate_work_hours(start_ts, end_ts)
    return out

def make_record_key(employee_id: str, work_order: str, process_name: str, start_ts: str) -> str:
    return f"{employee_id}|{work_order}|{process_name}|{start_ts}|{uuid.uuid4().hex[:8]}"


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM time_records WHERE end_timestamp IS NULL"
    params: list[str] = []
    if employee_id:
        sql += " AND employee_id=?"
        params.append(str(employee_id).strip())
    if employee_name:
        # 同步/重複判斷必須同時符合工號與姓名，避免不同人員被誤判為同一人。
        sql += " AND COALESCE(employee_name,'')=?"
        params.append(str(employee_name).strip())
    if process_name:
        sql += " AND process_name=?"
        params.append(str(process_name).strip())
    if start_date:
        sql += " AND start_date=?"
        params.append(str(start_date).strip())
    sql += " ORDER BY employee_id, employee_name, process_name, start_timestamp, id"
    return query_df(sql, params)


def get_active_record(employee_id: str) -> dict | None:
    return query_one(
        """
        SELECT * FROM time_records
        WHERE employee_id=? AND end_timestamp IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (employee_id,),
    )


def get_active_group(record_id: int) -> pd.DataFrame:
    rec = query_one("SELECT * FROM time_records WHERE id=?", (record_id,))
    if not rec:
        return pd.DataFrame()
    return get_active_records(
        employee_id=rec.get("employee_id"),
        employee_name=rec.get("employee_name"),
        process_name=rec.get("process_name"),
        start_date=rec.get("start_date"),
    )


def _pause_conflicting_active_records(employee_id: str, employee_name: str, process_name: str, start_date: str) -> int:
    """Pause only the same employee/name active records in a different process/day."""
    active = get_active_records(employee_id=employee_id, employee_name=employee_name)
    if active.empty:
        return 0
    conflict = active[(active["process_name"].astype(str) != str(process_name)) | (active["start_date"].astype(str) != str(start_date))]
    closed = 0
    for _, row in conflict.iterrows():
        finish_work(int(row["id"]), "暫停", "系統自動暫停：同一人員切換不同工段或不同日期作業", finish_parallel_group=True)
        closed += 1
    return closed


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> dict | None:
    start_date = start_date or today_text()
    sql = """
        SELECT * FROM time_records
        WHERE employee_id=? AND work_order=? AND process_name=? AND start_date=? AND end_timestamp IS NULL
    """
    params: list = [str(employee_id).strip(), str(work_order).strip(), str(process_name).strip(), str(start_date).strip()]
    if employee_name:
        sql += " AND COALESCE(employee_name,'')=?"
        params.append(str(employee_name).strip())
    sql += " ORDER BY id DESC LIMIT 1"
    return query_one(sql, params)


def get_conflicting_active_records(employee_id: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    """Active records that must be paused before starting a new non-parallel process.

    Same employee/name + same process + same date but different work order is allowed
    and will be treated as parallel/synchronized work.
    """
    start_date = start_date or today_text()
    active = get_active_records(employee_id=employee_id, employee_name=employee_name)
    if active.empty:
        return active
    return active[(active["process_name"].astype(str) != str(process_name)) | (active["start_date"].astype(str) != str(start_date))].copy()

def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:
    now = _now()
    start_date, start_time = split_timestamp(now)
    employee_id = str(employee.get("employee_id") or "").strip()
    employee_name = str(employee.get("employee_name") or "").strip()
    wo_no = str(work_order.get("work_order") or "").strip()
    process_name = str(process_name or "").strip()

    if not employee_id or not wo_no or not process_name:
        raise ValueError("工號、製令、工段名稱不可空白。")

    # 規則 1：同工號/姓名、同製令、同工段名稱不可重複計時。
    duplicate = get_active_same_work(employee_id, wo_no, process_name, start_date, employee_name=employee_name)
    if duplicate:
        raise ValueError(f"此人員已有相同製令與工段正在計時，禁止重複紀錄：{wo_no} / {process_name}")

    # 規則 2：同人員同工段、不同製令可視為同步作業；不同工段必須先暫停前一個作業。
    conflicts = get_conflicting_active_records(employee_id, process_name, start_date, employee_name=employee_name)
    if not conflicts.empty:
        if not auto_pause_old:
            raise ValueError("此人員已有不同工段正在計時，請先確認暫停前一筆作業後再開始新紀錄。")
        _pause_conflicting_active_records(employee_id, employee_name, process_name, start_date)

    record_key = make_record_key(employee_id, wo_no, process_name, now)
    group_key = f"{employee_id}|{process_name}|{start_date}"
    rid = execute(
        """
        INSERT INTO time_records(
            record_key, status, work_order, part_no, type_name, process_name,
            employee_id, employee_name, start_action, start_timestamp,
            remark, start_date, start_time, assembly_location,
            group_key, is_group_work, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_key,
            "作業中",
            wo_no,
            work_order.get("part_no", ""),
            work_order.get("type_name", ""),
            process_name,
            employee_id,
            employee_name,
            "開始",
            now,
            remark,
            start_date,
            start_time,
            work_order.get("assembly_location", ""),
            group_key,
            0,
            "streamlit",
            now,
            now,
        ),
    )

    parallel = get_active_records(employee_id=employee_id, employee_name=employee_name, process_name=process_name, start_date=start_date)
    if len(parallel) > 1:
        execute(
            "UPDATE time_records SET is_group_work=1, group_key=?, updated_at=? WHERE employee_id=? AND COALESCE(employee_name,'')=? AND process_name=? AND start_date=? AND end_timestamp IS NULL",
            (group_key, now, employee_id, employee_name, process_name, start_date),
        )
    write_log("START_WORK", f"{employee_name} 開始 {wo_no} / {process_name}", "time_records", rid)
    return rid
def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:
    """Finish work record.

    V1.3 core rule:
    - Same employee + same day + same process = parallel active group.
    - Ending any one record ends all records in that active group.
    - The elapsed group hours from earliest start to end now, after rest deduction, are averaged back to each record.
    """
    rec = query_one("SELECT * FROM time_records WHERE id=?", (record_id,))
    if not rec:
        raise ValueError("找不到工時紀錄")
    if rec.get("end_timestamp"):
        return 0

    now = _now()
    end_date, end_time = split_timestamp(now)
    status = end_action if end_action in ("下班", "暫停", "完工") else "已結束"

    if finish_parallel_group:
        group = get_active_group(record_id)
    else:
        group = pd.DataFrame([rec])

    if group.empty:
        group = pd.DataFrame([rec])

    group_ids = [int(x) for x in group["id"].tolist()]
    earliest_start = min(str(x) for x in group["start_timestamp"].dropna().tolist())
    total_hours = calculate_work_hours(earliest_start, now)
    avg_hours = round(total_hours / max(len(group_ids), 1), 2)
    is_group = 1 if len(group_ids) > 1 else int(rec.get("is_group_work") or 0)
    group_key = rec.get("group_key") or f"{rec.get('employee_id')}|{rec.get('process_name')}|{rec.get('start_date')}"

    for rid in group_ids:
        old = query_one("SELECT remark FROM time_records WHERE id=?", (rid,)) or {}
        new_remark = old.get("remark") or ""
        append = remark or ""
        if len(group_ids) > 1:
            append = (append + "；" if append else "") + _v138_parallel_summary_text(len(group_ids), total_hours, avg_hours)
        if append:
            new_remark = (new_remark + "；" if new_remark else "") + append
        execute(
            """
            UPDATE time_records
            SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?,
                work_hours=?, remark=?, group_key=?, is_group_work=?, updated_at=?
            WHERE id=? AND end_timestamp IS NULL
            """,
            (status, end_action, now, end_date, end_time, avg_hours, new_remark, group_key, is_group, now, rid),
        )

    write_log(
        "END_WORK_GROUP" if len(group_ids) > 1 else "END_WORK",
        f"結束工時紀錄 #{record_id}，同步結束={len(group_ids)}筆，狀態={status}，群組總工時={_v138_hours_to_hms_label(total_hours)}，平均工時={_v138_hours_to_hms_label(avg_hours)}",
        "time_records",
        record_id,
        detail=",".join(str(x) for x in group_ids),
    )
    return len(group_ids)


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    ensure_time_records_available("load_records")
    sql = "SELECT * FROM time_records WHERE 1=1"
    params = []
    if start_date:
        sql += " AND start_date>=?"
        params.append(start_date)
    if end_date:
        sql += " AND start_date<=?"
        params.append(end_date)
    if employee_id:
        sql += " AND employee_id=?"
        params.append(employee_id)
    if work_order:
        sql += " AND work_order=?"
        params.append(work_order)
    sql += " ORDER BY id DESC"
    return query_df(sql, params)


def _business_cycle_start_date() -> str:
    """Return current 01 live-record cycle start date using admin setting.

    Default reset time is 02:00. Before reset time, the current work cycle still
    belongs to yesterday. After reset time, completed records from the previous
    cycle are hidden from 01, while unfinished records remain visible.
    """
    try:
        from services.system_settings_service import get_live_page_reset_time
        reset = get_live_page_reset_time()
    except Exception:
        reset = "02:00"
    now_dt = taiwan_now()
    try:
        h, m = [int(x) for x in str(reset).split(":")[:2]]
    except Exception:
        h, m = 2, 0
    start_day = now_dt.date()
    if (now_dt.hour, now_dt.minute) < (h, m):
        start_day = start_day - timedelta(days=1)
    return start_day.strftime("%Y-%m-%d")


def _parse_reset_hour_minute() -> tuple[int, int]:
    try:
        from services.system_settings_service import get_live_page_reset_time
        reset = get_live_page_reset_time()
    except Exception:
        reset = "02:00"
    try:
        h, m = [int(x) for x in str(reset).split(":")[:2]]
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h, m
    except Exception:
        return 2, 0


def _current_reset_timestamp() -> str | None:
    """Return today's scheduled display-reset timestamp if it has already passed.

    This is only a display cutoff for 01｜工時紀錄. It never deletes or changes
    02｜歷史紀錄.
    """
    now_dt = taiwan_now()
    h, m = _parse_reset_hour_minute()
    reset_dt = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
    if now_dt >= reset_dt:
        return reset_dt.strftime("%Y-%m-%d %H:%M:%S")
    return None


def _safe_app_setting_value(setting_key: str) -> str | None:
    """Read a lightweight app setting without breaking page load when schema is absent.

    V3.04 hotfix:
    Some deployed databases were created before the app_settings table existed.
    01｜工時紀錄 calls this while rendering, so a missing table must be created
    or safely treated as no setting instead of crashing the page.
    """
    key = str(setting_key or "").strip()
    if not key:
        return None
    try:
        _ensure_app_settings_table()
        row = query_one("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)) or {}
        val = row.get("setting_value")
        return str(val).strip() if val else None
    except sqlite3.OperationalError:
        # Startup-safe fallback: if the DB/table is still being repaired, do not
        # block 01 page rendering. The setting simply behaves as unset.
        try:
            _ensure_app_settings_table()
        except Exception:
            pass
        return None
    except Exception:
        return None


def _manual_refresh_timestamp() -> str | None:
    return _safe_app_setting_value("live_page_manual_refresh_timestamp")


def _restore_hidden_reset_key() -> str | None:
    """Return the reset-cutoff key for which admin has restored hidden rows."""
    return _safe_app_setting_value("live_page_restore_hidden_reset_key")


def _effective_refresh_cutoff_for_now() -> str | None:
    """Cutoff used by manual refresh.

    Business rule V2.15:
    The admin setting time is the boundary for cleaning the live 01 display.
    Pressing 「立即重新整理 01 顯示」 after that boundary should hide rows that
    were already finished before the configured boundary; it must not cause rows
    finished after the boundary to disappear immediately.
    """
    scheduled = _current_reset_timestamp()
    return scheduled or now_stamp()


def _live_page_cutoff_timestamp() -> str | None:
    """Latest cutoff used to hide completed rows from 01 display.

    V2.15 rule:
    - Before the configured reset time, 01 shows current-cycle rows regardless of
      whether they have ended.
    - After the configured reset time, 01 hides only rows that were already ended
      at or before that reset-time cutoff.
    - Pressing 「立即重新整理 01 顯示」 uses the configured reset-time cutoff, not
      the current click time, so ending a job after the reset time will not
      immediately disappear unless the next refresh boundary applies.
    - 「恢復已隱藏紀錄」 cancels the current reset cutoff display filtering until
      the next reset boundary changes.
    """
    scheduled = _current_reset_timestamp()
    manual = _manual_refresh_timestamp()
    restore_key = _restore_hidden_reset_key()

    # If admin restored the records for this reset boundary, ignore that scheduled
    # cutoff. A future day/reset has a different key and will work normally.
    if scheduled and restore_key == scheduled:
        scheduled = None

    candidates = [x for x in [scheduled, manual] if x]
    return max(candidates) if candidates else None


def _unfinished_live_where() -> str:
    """SQL condition for records that are still allowed to remain on 01 display.

    Business rule V2.10:
    - 01｜工時紀錄 after scheduled/manual refresh should keep only records
      that are genuinely still working.
    - Any row whose status is not 作業中 is treated as already ended for 01
      display, even if legacy data has inconsistent timestamp values.
    - Any row with an end timestamp is also treated as ended.
    - This is display-only and never changes 02｜歷史紀錄.
    """
    return """
        COALESCE(status, '')='作業中'
        AND (
            end_timestamp IS NULL
            OR TRIM(COALESCE(end_timestamp, ''))=''
            OR LOWER(TRIM(COALESCE(end_timestamp, '')))='none'
        )
    """


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:
    """Records shown on 01｜工時紀錄. 02｜歷史紀錄 is never affected.

    Correct display rule V2.14:
    - If admin selects unfinished_only, show only genuinely active records.
    - Before any scheduled/manual display refresh cutoff, show all records in the
      current work cycle plus unfinished older records.
    - After a scheduled/manual display refresh cutoff, hide only records that had
      already ended at or before that cutoff.
    - Records started/ended after the cutoff must still appear on 01 until the
      next refresh. This prevents pressing 暫停/完工/下班 after a refresh from
      making the new record disappear immediately.
    """
    cycle_start = _business_cycle_start_date()
    unfinished_where = _unfinished_live_where()

    if unfinished_only:
        return query_df(f"SELECT * FROM time_records WHERE {unfinished_where} ORDER BY id DESC")

    cutoff = _live_page_cutoff_timestamp()
    if cutoff:
        # Keep all unfinished rows and all current-cycle rows whose finished marker
        # is after the cutoff. Hide only rows that were already ended before the
        # configured reset boundary. Finished is determined by status, end timestamp,
        # or non-zero work_hours, because legacy records may have inconsistent fields.
        return query_df(
            f"""
            SELECT * FROM time_records
            WHERE
                ({unfinished_where})
                OR (
                    start_date>=?
                    AND NOT (
                        (
                            COALESCE(status,'')<>'作業中'
                            OR (end_timestamp IS NOT NULL AND TRIM(COALESCE(end_timestamp,''))<>'' AND LOWER(TRIM(COALESCE(end_timestamp,'')))<>'none')
                            OR CAST(COALESCE(work_hours, 0) AS REAL) > 0
                        )
                        AND COALESCE(NULLIF(TRIM(COALESCE(end_timestamp,'')), ''), updated_at, start_timestamp, created_at, '') <= ?
                    )
                )
            ORDER BY id DESC
            """,
            (cycle_start, cutoff),
        )

    return query_df(
        """
        SELECT * FROM time_records
        WHERE start_date>=? OR (
            COALESCE(status, '')='作業中'
            AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='' OR LOWER(TRIM(COALESCE(end_timestamp,'')))='none')
        )
        ORDER BY id DESC
        """,
        (cycle_start,),
    )

def _ensure_app_settings_table() -> None:
    """Ensure the lightweight app_settings table exists and has required columns."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            note TEXT,
            updated_at TEXT
        )
        """
    )
    # Compatibility: older deployments may already have app_settings with fewer
    # columns. Add optional columns without touching existing values.
    try:
        info = query_df("PRAGMA table_info(app_settings)")
        cols = set(info.get("name", pd.Series(dtype=str)).astype(str).tolist()) if isinstance(info, pd.DataFrame) else set()
        if "note" not in cols:
            execute("ALTER TABLE app_settings ADD COLUMN note TEXT")
        if "updated_at" not in cols:
            execute("ALTER TABLE app_settings ADD COLUMN updated_at TEXT")
    except Exception:
        pass


def _upsert_app_setting(key: str, value: str, note: str) -> None:
    _ensure_app_settings_table()
    execute(
        """
        INSERT INTO app_settings(setting_key, setting_value, note, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value=excluded.setting_value,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (key, value, note, _now()),
    )


def clear_today_finished_from_work_page() -> int:
    """Manual refresh for 01 page display only; does not delete 02 history.

    V2.15: Use the configured reset-time boundary as cutoff. This means records
    finished after the configured boundary remain visible until the next boundary
    or another rule applies; pressing 暫停/完工/下班 after the reset time will not
    make the row disappear immediately.
    """
    cutoff = _effective_refresh_cutoff_for_now()
    row = query_one(
        """
        SELECT COUNT(*) AS n FROM time_records
        WHERE (
            COALESCE(status,'')<>'作業中'
            OR (end_timestamp IS NOT NULL AND TRIM(COALESCE(end_timestamp,''))<>'' AND LOWER(TRIM(COALESCE(end_timestamp,'')))<>'none')
            OR CAST(COALESCE(work_hours, 0) AS REAL) > 0
        )
        AND COALESCE(NULLIF(TRIM(COALESCE(end_timestamp,'')), ''), updated_at, start_timestamp, created_at, '') <= ?
        """,
        (cutoff,),
    ) or {}
    n = int(row.get("n") or 0)
    _upsert_app_setting(
        "live_page_manual_refresh_timestamp",
        cutoff,
        "01 工時紀錄手動重新整理顯示截止時間；依系統設定時間判斷，只影響 01 顯示，不刪除 02 歷史紀錄",
    )
    # Manual refresh cancels a previous restore for the same boundary.
    execute("DELETE FROM app_settings WHERE setting_key='live_page_restore_hidden_reset_key'")
    clear_query_cache()
    write_log(
        "CLEAR_TODAY_FINISHED_VIEW",
        f"01 工時紀錄手動重新整理顯示：cutoff={cutoff}，隱藏設定時間前已結束紀錄，不影響 02 歷史紀錄，筆數={n}",
        "time_records",
    )
    return n


def restore_today_hidden_records() -> int:
    """Restore rows hidden from 01 display for the current reset boundary."""
    scheduled = _current_reset_timestamp()
    manual = _manual_refresh_timestamp()
    key = scheduled or manual or now_stamp()
    _upsert_app_setting(
        "live_page_restore_hidden_reset_key",
        key,
        "恢復 01 工時紀錄已隱藏紀錄；只影響 01 顯示，不刪除或更改 02 歷史紀錄",
    )
    execute("DELETE FROM app_settings WHERE setting_key='live_page_manual_refresh_timestamp'")
    clear_query_cache()
    write_log(
        "RESTORE_TODAY_HIDDEN_VIEW",
        f"恢復 01 工時紀錄已隱藏紀錄：reset_key={key}，不影響 02 歷史紀錄",
        "time_records",
    )
    return 1

def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:
    """Save administrator edits from 01/02 tables.

    Important V2.26 behavior:
    - If Start Timestamp or End Timestamp was edited, confirm/sync the related
      date/time columns again.
    - When recalc_edited_timestamps=True, also recalculate work_hours from the
      edited timestamps.
    - Keeps normal save behavior for all other columns.
    """
    if df is None or df.empty:
        return 0
    update_cols = [
        "status", "work_order", "part_no", "type_name", "process_name", "employee_id", "employee_name",
        "start_action", "start_timestamp", "end_action", "end_timestamp", "remark", "start_date", "start_time",
        "end_date", "end_time", "work_hours", "assembly_location", "group_key", "is_group_work", "source",
    ]
    count = 0
    now = _now()
    for _, r in df.iterrows():
        if pd.isna(r.get("id")):
            continue

        # Normalize timestamp/date/time consistency before saving.
        normalized_dt = normalize_record_datetime_fields(r, recalc_work_hours=recalc_edited_timestamps)
        row_values = dict(r)
        row_values.update(normalized_dt)

        vals = []
        for c in update_cols:
            v = row_values.get(c, "")
            if pd.isna(v) if not isinstance(v, (list, tuple, dict)) else False:
                v = None
            if c == "work_hours" and v is not None:
                # If recalculated, v is already decimal hours; otherwise UI may display HH:MM:SS.
                try:
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        v = float(v)
                    else:
                        v = hms_to_hours(v)
                except Exception:
                    v = hms_to_hours(v)
            if c == "is_group_work" and v is not None:
                v = int(bool(v))
            vals.append(v)
        vals += [now, int(r["id"])]
        execute(
            f"""
            UPDATE time_records
            SET {', '.join([c+'=?' for c in update_cols])}, updated_at=?
            WHERE id=?
            """,
            vals,
        )
        count += 1
    write_log("SAVE_TIME_RECORDS", f"人工編輯並儲存工時紀錄 {count} 筆；已同步確認日期/時間欄位", "time_records")
    return count


def _audit_user_name() -> str:
    try:
        import streamlit as st  # type: ignore
        user = st.session_state.get("user") or st.session_state.get("current_user") or {}
        if isinstance(user, dict):
            return str(user.get("username") or user.get("account") or user.get("user_name") or "system")
    except Exception:
        pass
    return "system"


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:
    """Fast delete selected time records in one transaction.

    V1.90: the old implementation used execute() for each DELETE and write_log()
    for each audit row.  execute() triggered permanent export / possible GitHub
    sync, so deleting one row could take ~20 seconds.  This version performs
    SELECT + DELETE + LOG in one SQLite transaction, then only marks data as
    pending backup once.
    """
    ids: list[int] = []
    for rid in record_ids or []:
        try:
            i = int(rid)
            if i > 0 and i not in ids:
                ids.append(i)
        except Exception:
            continue
    if not ids:
        return 0

    now = _now()
    user_name = _audit_user_name()
    deleted = 0
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN")
        for rid in ids:
            rec = conn.execute("SELECT * FROM time_records WHERE id=?", (rid,)).fetchone()
            if not rec:
                continue
            rec_dict = dict(rec)
            conn.execute("DELETE FROM time_records WHERE id=?", (rid,))
            conn.execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    user_name,
                    "DELETE_TIME_RECORD",
                    "time_records",
                    str(rid),
                    f"{reason}：#{rid} {rec_dict.get('employee_id','')} {rec_dict.get('employee_name','')} {rec_dict.get('work_order','')} {rec_dict.get('process_name','')}",
                    str(rec_dict),
                    "WARN",
                ),
            )
            deleted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if deleted:
        clear_query_cache()
        mark_data_changed(f"已刪除工時紀錄 {deleted} 筆，待手動永久備份。", "FAST_DELETE time_records")
    return deleted


def recalculate_time_records(record_ids: list[int] | None = None) -> int:
    """Recalculate selected records only and update in one transaction.

    V1.90: avoids per-row execute() so recalculating a few selected records does
    not repeatedly export permanent JSON or trigger cloud work.
    """
    if record_ids:
        ids = []
        for x in record_ids:
            try:
                i = int(x)
                if i > 0 and i not in ids:
                    ids.append(i)
            except Exception:
                continue
        if not ids:
            return 0
        placeholder = ",".join(["?"] * len(ids))
        df = query_df(f"SELECT * FROM time_records WHERE id IN ({placeholder}) ORDER BY id", ids)
    else:
        # Safety: administrator page should pass selected IDs.  If not, keep the
        # old behavior but this can be heavy on large history tables.
        df = query_df("SELECT * FROM time_records WHERE start_timestamp IS NOT NULL AND end_timestamp IS NOT NULL ORDER BY id")
    if df.empty:
        return 0

    updates: list[tuple[float, str, str, str, str, str, str, int]] = []
    errors: list[str] = []
    now = _now()
    for _, r in df.iterrows():
        start_ts = r.get("start_timestamp")
        end_ts = r.get("end_timestamp")
        if not start_ts or not end_ts or pd.isna(start_ts) or pd.isna(end_ts):
            continue
        try:
            normalized = normalize_record_datetime_fields(r, recalc_work_hours=True)
            start_ts2 = normalized.get("start_timestamp")
            end_ts2 = normalized.get("end_timestamp")
            if not start_ts2 or not end_ts2:
                continue
            hours = normalized.get("work_hours")
            start_date = normalized.get("start_date")
            start_time = normalized.get("start_time")
            end_date = normalized.get("end_date")
            end_time = normalized.get("end_time")
            status = r.get("status") or "已結束"
            if str(status) == "作業中":
                status = r.get("end_action") or "已結束"
            updates.append((hours, start_ts2, end_ts2, start_date, start_time, end_date, end_time, status, now, int(r["id"])))
        except Exception as exc:
            errors.append(f"重新計算工時失敗 #{r.get('id')}: {exc}")

    if not updates and not errors:
        return 0

    user_name = _audit_user_name()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN")
        if updates:
            conn.executemany(
                """
                UPDATE time_records
                SET work_hours=?, start_timestamp=?, end_timestamp=?, start_date=?, start_time=?, end_date=?, end_time=?, status=?, updated_at=?
                WHERE id=?
                """,
                updates,
            )
            conn.execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, user_name, "RECALC_TIME_RECORDS", "time_records", "", f"管理員重新計算工時 {len(updates)} 筆，已同步反映至 02 歷史紀錄", "", "INFO"),
            )
        for msg in errors[:50]:
            conn.execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, user_name, "RECALC_TIME_RECORD_ERROR", "time_records", "", msg, "", "ERROR"),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    clear_query_cache()
    mark_data_changed(f"已重新計算工時 {len(updates)} 筆，待手動永久備份。", "FAST_RECALC time_records")
    return len(updates)


def _to_clean_value(v):
    """Normalize values coming from Excel/paste imports before DB writes."""
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (datetime, date)):
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return v.strftime("%Y-%m-%d")
    text = str(v).strip() if v is not None else ""
    return text if text != "" else None


def _combine_date_time(date_value, time_value) -> str | None:
    d = _to_clean_value(date_value)
    t = _to_clean_value(time_value)
    if not d:
        return None
    if t:
        return f"{str(d)[:10]} {str(t)}"[:19]
    # If d already looks like a timestamp, keep it.
    return str(d)[:19]


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:
    """Import parsed history/time records from 02 History Excel/Paste.

    Added back in V2.03 because pages/02 imports this function.  It performs a
    single transaction and returns counts, so importing history does not cause
    partial writes or repeated slow cloud sync work.
    """
    result = {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}
    if df is None or df.empty:
        return result

    now = _now()
    user_name = _audit_user_name()
    insert_cols = [
        "record_key", "status", "work_order", "part_no", "type_name", "process_name",
        "employee_id", "employee_name", "start_action", "start_timestamp", "end_action",
        "end_timestamp", "remark", "start_date", "start_time", "end_date", "end_time",
        "work_hours", "assembly_location", "group_key", "is_group_work", "source",
        "created_at", "updated_at",
    ]
    update_cols = [c for c in insert_cols if c not in ("record_key", "created_at")]

    rows_to_insert = []
    rows_to_update = []
    errors = []

    for idx, r in df.iterrows():
        try:
            employee_id = _to_clean_value(r.get("employee_id"))
            work_order = _to_clean_value(r.get("work_order"))
            process_name = _to_clean_value(r.get("process_name"))
            start_ts = _to_clean_value(r.get("start_timestamp"))
            end_ts = _to_clean_value(r.get("end_timestamp"))

            if not start_ts:
                start_ts = _combine_date_time(r.get("start_date"), r.get("start_time"))
            if not end_ts:
                end_ts = _combine_date_time(r.get("end_date"), r.get("end_time"))

            # V2.43: normalize timestamp text before duplicate-key comparison.
            # This prevents the same record being inserted twice when Excel uses
            # 2026/2/2 09:19 or Timestamp values while existing records use
            # 2026-02-02 09:19:00.
            try:
                if start_ts:
                    start_ts = pd.to_datetime(start_ts).strftime("%Y-%m-%d %H:%M:%S")
                if end_ts:
                    end_ts = pd.to_datetime(end_ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

            if not (employee_id and work_order and process_name and start_ts):
                result["skipped"] += 1
                errors.append(f"第 {idx + 1} 筆缺少必要欄位：工號、製令、工段或開始時間。")
                continue

            try:
                start_date, start_time = split_timestamp(str(start_ts))
            except Exception:
                start_date = _to_clean_value(r.get("start_date")) or str(start_ts)[:10]
                start_time = _to_clean_value(r.get("start_time")) or (str(start_ts)[11:19] if len(str(start_ts)) >= 19 else "")
            if end_ts:
                try:
                    end_date, end_time = split_timestamp(str(end_ts))
                except Exception:
                    end_date = _to_clean_value(r.get("end_date")) or str(end_ts)[:10]
                    end_time = _to_clean_value(r.get("end_time")) or (str(end_ts)[11:19] if len(str(end_ts)) >= 19 else "")
            else:
                end_date, end_time = _to_clean_value(r.get("end_date")), _to_clean_value(r.get("end_time"))

            work_hours = _to_clean_value(r.get("work_hours"))
            if recalc and start_ts and end_ts:
                try:
                    work_hours = calculate_work_hours(str(start_ts), str(end_ts))
                except Exception as exc:
                    errors.append(f"第 {idx + 1} 筆工時計算失敗，保留原工時：{exc}")
            elif work_hours is not None:
                work_hours = hms_to_hours(work_hours)
            else:
                work_hours = 0

            status = _to_clean_value(r.get("status")) or ("已結束" if end_ts else "作業中")
            record_key = _to_clean_value(r.get("record_key")) or make_record_key(str(employee_id), str(work_order), str(process_name), str(start_ts))
            is_group_work = r.get("is_group_work", 0)
            try:
                is_group_work = int(bool(is_group_work))
            except Exception:
                is_group_work = 0

            record = {
                "record_key": record_key,
                "status": status,
                "work_order": work_order,
                "part_no": _to_clean_value(r.get("part_no")),
                "type_name": _to_clean_value(r.get("type_name")),
                "process_name": process_name,
                "employee_id": employee_id,
                "employee_name": _to_clean_value(r.get("employee_name")),
                "start_action": _to_clean_value(r.get("start_action")) or "開始",
                "start_timestamp": str(start_ts),
                "end_action": _to_clean_value(r.get("end_action")) or ("完工" if end_ts else None),
                "end_timestamp": str(end_ts) if end_ts else None,
                "remark": _to_clean_value(r.get("remark")),
                "start_date": start_date,
                "start_time": start_time,
                "end_date": end_date,
                "end_time": end_time,
                "work_hours": work_hours,
                "assembly_location": _to_clean_value(r.get("assembly_location")),
                "group_key": _to_clean_value(r.get("group_key")),
                "is_group_work": is_group_work,
                "source": source,
                "created_at": now,
                "updated_at": now,
            }
            rid = _to_clean_value(r.get("id"))
            if rid:
                try:
                    rows_to_update.append((int(rid), record))
                except Exception:
                    rows_to_insert.append(record)
            else:
                rows_to_insert.append(record)
        except Exception as exc:
            result["skipped"] += 1
            errors.append(f"第 {idx + 1} 筆匯入失敗：{exc}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN")
        for rid, record in rows_to_update:
            exists = conn.execute("SELECT id FROM time_records WHERE id=?", (rid,)).fetchone()
            if not exists:
                rows_to_insert.append(record)
                continue
            vals = [record[c] for c in update_cols] + [rid]
            conn.execute(
                f"UPDATE time_records SET {', '.join([c + '=?' for c in update_cols])} WHERE id=?",
                vals,
            )
            result["updated"] += 1
        for record in rows_to_insert:
            # V2.43: stronger duplicate protection.  Prefer record_key, then
            # composite business key: 工號 + 姓名 + 製令 + 工段 + 開始時間戳.
            existing = conn.execute("SELECT id FROM time_records WHERE record_key=?", (record.get("record_key"),)).fetchone()
            if not existing:
                existing = conn.execute(
                    """
                    SELECT id FROM time_records
                    WHERE COALESCE(employee_id,'')=?
                      AND COALESCE(employee_name,'')=?
                      AND COALESCE(work_order,'')=?
                      AND COALESCE(process_name,'')=?
                      AND COALESCE(start_timestamp,'')=?
                    LIMIT 1
                    """,
                    (str(record.get("employee_id") or ""), str(record.get("employee_name") or ""),
                     str(record.get("work_order") or ""), str(record.get("process_name") or ""),
                     str(record.get("start_timestamp") or "")),
                ).fetchone()
            if existing:
                rid = int(existing[0])
                vals = [record[c] for c in update_cols] + [rid]
                conn.execute(
                    f"UPDATE time_records SET {', '.join([c + '=?' for c in update_cols])} WHERE id=?",
                    vals,
                )
                result["updated"] += 1
            else:
                vals = [record[c] for c in insert_cols]
                placeholders = ",".join(["?"] * len(insert_cols))
                conn.execute(
                    f"INSERT INTO time_records ({', '.join(insert_cols)}) VALUES ({placeholders})",
                    vals,
                )
                result["inserted"] += 1
        conn.execute(
            """
            INSERT INTO system_logs
            (log_time, user_name, action_type, target_table, target_id, message, detail, level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, user_name, "IMPORT_TIME_RECORDS", "time_records", "", f"歷史紀錄匯入：新增 {result['inserted']}，更新 {result['updated']}，略過 {result['skipped']}", source, "INFO"),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    clear_query_cache()
    if result["inserted"] or result["updated"]:
        mark_data_changed("歷史紀錄匯入已變更，待手動永久備份。", "IMPORT time_records")
    result["errors"] = errors
    return result





# ========================= V28 Permanent Authority Overrides =========================
try:
    from services.permanent_authority_service import update_tables as _v28_update_tables, table_from_df as _v28_table_from_df, df_from_table as _v28_df_from_table
except Exception:
    _v28_update_tables = _v28_table_from_df = _v28_df_from_table = None  # type: ignore

_original_v28_save_time_records = save_time_records
_original_v28_load_records = load_records

def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    # 02/01 讀取先走 canonical，避免刪除後被 SQLite 舊快取救回。
    if _v28_df_from_table is not None:
        df = _v28_df_from_table("02_history", "time_records")
        if df is not None and not df.empty:
            if start_date and "work_date" in df.columns: df = df[df["work_date"].astype(str) >= str(start_date)]
            if end_date and "work_date" in df.columns: df = df[df["work_date"].astype(str) <= str(end_date)]
            if employee_id and "employee_id" in df.columns: df = df[df["employee_id"].astype(str) == str(employee_id)]
            if work_order and "work_order" in df.columns: df = df[df["work_order"].astype(str) == str(work_order)]
            return df.reset_index(drop=True)
    return _original_v28_load_records(start_date, end_date, employee_id, work_order)

def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = _original_v28_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps)
    try:
        rows = _v28_table_from_df(df) if _v28_table_from_df is not None else []
        if _v28_update_tables is not None:
            _v28_update_tables("01_time_records", {"time_records": rows}, reason="save_time_records_01_v28")
            _v28_update_tables("02_history", {"time_records": rows}, reason="save_time_records_02_v28")
    except Exception:
        pass
    return n



# ========================= V33 HISTORY DELETE SQLITE HOTFIX =========================
# 目的：02.歷史紀錄刪除勾選資料時，舊版 delete_time_records 直接使用 sqlite3.connect(DB_PATH)
# 與 conn.execute("SELECT * FROM time_records...")，會繞過 db_service 的 query_one/execute_transaction
# 自我修復與權威檔同步機制。Streamlit Cloud 上若 SQLite schema/corruption/lock 異常，會直接
# sqlite3.OperationalError。此覆寫版以 canonical records.json 為權威，SQLite 只當快取；
# 即使 SQLite 快取暫時失敗，也不阻斷刪除權威檔，避免 Reboot 後資料復活。

def _v33_normalize_record_ids(record_ids) -> list[int]:
    ids: list[int] = []
    for rid in record_ids or []:
        try:
            i = int(float(str(rid).strip()))
            if i > 0 and i not in ids:
                ids.append(i)
        except Exception:
            continue
    return ids


def _v33_delete_from_authority(ids: list[int]) -> tuple[int, pd.DataFrame | None]:
    """Delete ids from canonical authority files first.

    Returns (deleted_count, remaining_df).  It updates both 01_time_records and
    02_history because these modules share the same time_records table.
    """
    if not ids:
        return 0, None
    try:
        if _v28_df_from_table is not None:
            df = _v28_df_from_table("02_history", "time_records")
        else:
            df = pd.DataFrame()
    except Exception:
        df = pd.DataFrame()

    if df is None or df.empty:
        try:
            df = _original_v28_load_records() if '_original_v28_load_records' in globals() else load_records()
        except Exception:
            df = pd.DataFrame()

    if df is None or df.empty or "id" not in df.columns:
        return 0, df

    id_series = pd.to_numeric(df["id"], errors="coerce").fillna(-1).astype(int)
    mask_delete = id_series.isin(ids)
    deleted = int(mask_delete.sum())
    if deleted <= 0:
        return 0, df

    remaining = df.loc[~mask_delete].copy().reset_index(drop=True)
    try:
        rows = _v28_table_from_df(remaining) if _v28_table_from_df is not None else remaining.to_dict(orient="records")
        if _v28_update_tables is not None:
            _v28_update_tables("01_time_records", {"time_records": rows}, reason="delete_time_records_01_v33")
            _v28_update_tables("02_history", {"time_records": rows}, reason="delete_time_records_02_v33")
    except Exception:
        # 不讓 GitHub/JSON write-through 的暫時錯誤中斷頁面。SQLite 刪除仍會繼續嘗試。
        pass
    return deleted, remaining


def _v33_delete_from_sqlite_cache(ids: list[int], reason: str, deleted_hint: int = 0) -> int:
    """Best-effort delete from SQLite cache through db_service repairable paths."""
    if not ids:
        return 0
    try:
        from services.db_service import execute_transaction as _execute_transaction, query_one as _safe_query_one
    except Exception:
        _execute_transaction = None
        _safe_query_one = None

    now = _now()
    user_name = _audit_user_name()
    operations: list[tuple[str, tuple]] = []
    logged = 0
    for rid in ids:
        rec_dict = {}
        try:
            if _safe_query_one is not None:
                rec_dict = _safe_query_one("SELECT * FROM time_records WHERE id=?", (rid,)) or {}
        except Exception:
            rec_dict = {}
        operations.append(("DELETE FROM time_records WHERE id=?", (rid,)))
        operations.append((
            """
            INSERT INTO system_logs
            (log_time, user_name, action_type, target_table, target_id, message, detail, level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                user_name,
                "DELETE_TIME_RECORD",
                "time_records",
                str(rid),
                f"{reason}：#{rid} {rec_dict.get('employee_id','')} {rec_dict.get('employee_name','')} {rec_dict.get('work_order','')} {rec_dict.get('process_name','')}",
                str(rec_dict)[:3000],
                "WARN",
            ),
        ))
        logged += 1

    try:
        if _execute_transaction is not None:
            _execute_transaction(
                operations,
                mark_changed=False,
                reason=f"delete_time_records_v33 sqlite cache delete {len(ids)} rows",
                source_sql="DELETE time_records V33",
            )
        else:
            # Last-resort direct SQLite path with schema initialization.  Do not re-raise.
            from services.db_service import ensure_database as _ensure_database, _open_connection as _open_conn  # type: ignore
            _ensure_database()
            with _open_conn() as conn:  # type: ignore
                cur = conn.cursor()
                for sql, params in operations:
                    cur.execute(sql, params)
                conn.commit()
    except Exception:
        # SQLite is only cache in the authority architecture.  If cache delete fails,
        # canonical records have already been updated, so do not crash the page.
        return int(deleted_hint or 0)
    return int(deleted_hint or len(ids) or logged)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    """Delete selected time records using canonical authority first, SQLite cache second.

    This fixes sqlite3.OperationalError in 02.歷史紀錄 by removing the direct
    conn.execute SELECT path and preventing stale SQLite/history backup from reviving
    deleted records after Reboot App.
    """
    ids = _v33_normalize_record_ids(record_ids)
    if not ids:
        return 0

    deleted, _remaining = _v33_delete_from_authority(ids)

    # Keep SQLite cache in sync as best effort.  Do not let cache failure block the user.
    sqlite_deleted = _v33_delete_from_sqlite_cache(ids, reason=reason, deleted_hint=deleted)
    final_deleted = int(deleted or sqlite_deleted or 0)

    if final_deleted:
        try:
            clear_query_cache()
        except Exception:
            pass
        try:
            mark_data_changed(f"已刪除工時紀錄 {final_deleted} 筆；已刷新 01/02 權威檔。", "DELETE time_records V33")
        except Exception:
            pass
        try:
            write_log("DELETE_TIME_RECORDS", f"{reason}：已刪除 {final_deleted} 筆，01/02 權威檔已更新", "time_records")
        except Exception:
            pass
    return final_deleted
# ======================= END V33 HISTORY DELETE SQLITE HOTFIX =======================


# ========================= V70 01/02 shared records sync hardening =========================
# 目的：01 工時紀錄與 02 歷史紀錄共用同一份 time_records 權威資料。
# 修正舊版 save_time_records 只用「目前畫面/篩選後 dataframe」寫權威檔，可能讓未顯示資料被覆蓋的風險。
# 也補上重新計算工時後，將 SQLite 最新結果同步寫回 01/02 權威檔，確保 Reboot 後不回復舊工時。

def _v70_sync_time_records_authority_from_sqlite(reason: str = "v70_sync_time_records") -> int:
    try:
        full_df = query_df("SELECT * FROM time_records ORDER BY id")
    except Exception:
        full_df = pd.DataFrame()
    if full_df is None or full_df.empty:
        return 0
    try:
        rows = _v28_table_from_df(full_df) if _v28_table_from_df is not None else full_df.fillna("").to_dict(orient="records")
        if _v28_update_tables is not None:
            _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01")
            _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02")
        try:
            mark_data_changed(f"01/02 工時紀錄權威檔已同步 {len(rows)} 筆。", f"V70 {reason}")
        except Exception:
            pass
        return int(len(rows))
    except Exception as exc:
        try:
            write_log("TIME_RECORD_AUTHORITY_SYNC_ERROR", f"01/02 權威檔同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return 0


# 覆寫 V28 save_time_records：仍先用原始 SQL 更新選取列，再以 SQLite 全量資料同步 01/02 權威檔。
def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = _original_v28_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps)
    if n:
        synced = _v70_sync_time_records_authority_from_sqlite("save_time_records_v70")
        try:
            write_log("SYNC_TIME_RECORDS_01_02", f"人工儲存後已同步 01/02 權威檔，共 {synced} 筆。", "time_records")
        except Exception:
            pass
    return n


_v70_original_recalculate_time_records = recalculate_time_records

def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    count = _v70_original_recalculate_time_records(record_ids)
    if count:
        synced = _v70_sync_time_records_authority_from_sqlite("recalculate_time_records_v70")
        try:
            write_log(
                "SYNC_RECALC_TIME_RECORDS_01_02",
                f"重新計算工時已扣除 13 系統設定休息時間，並同步 01/02 權威檔；重算 {count} 筆，同步 {synced} 筆。",
                "time_records",
            )
        except Exception:
            pass
    return count


_v70_original_import_time_records = import_time_records

def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    result = _v70_original_import_time_records(df, recalc=recalc, source=source)
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        synced = _v70_sync_time_records_authority_from_sqlite("import_time_records_v70")
        try:
            write_log("SYNC_IMPORT_TIME_RECORDS_01_02", f"匯入後已同步 01/02 權威檔，共 {synced} 筆。", "time_records")
        except Exception:
            pass
    return result
# ======================= END V70 01/02 shared records sync hardening =======================


# ========================= V75 01 admin save/delete persistence stabilization =========================
# 目的：修正 01 工時紀錄管理員維護區「刪除後又出現 / 儲存後被暫存資料蓋回 / Reboot 後 01-02 不同步」。
# 原則：SQLite 是目前畫面即時資料；每次真正儲存、重算、刪除後，再把 SQLite 全量同步到 01/02 權威檔與舊永久檔。

def _v75_json_default(v):
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v.strftime("%Y-%m-%d")
    return str(v)


def _v75_table_rows_from_df(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    try:
        if _v28_table_from_df is not None:
            return _v28_table_from_df(df)
    except Exception:
        pass
    try:
        return [dict(r) for _, r in df.fillna("").iterrows()]
    except Exception:
        return []


def _v75_atomic_json(path, payload: dict) -> None:
    try:
        import json, os
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_v75_json_default), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _v75_write_legacy_time_record_files(rows: list[dict], reason: str = "v75_sync") -> None:
    """Mirror shared time_records into legacy permanent locations used by older restore guards."""
    try:
        from pathlib import Path
        project = Path(__file__).resolve().parents[1]
        payload = {
            "version": "V75_TIME_RECORDS_SYNC",
            "updated_at": _now(),
            "reason": reason,
            "tables": {"time_records": rows},
            "table_counts": {"time_records": len(rows)},
        }
        targets = [
            project / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_records.json",
            project / "data" / "permanent_store" / "persistent_modules" / "02_history" / "02_history_records.json",
            project / "data" / "persistent_modules" / "01_time_records" / "01_time_records_records.json",
            project / "data" / "persistent_modules" / "02_history" / "02_history_records.json",
            project / "data" / "persistent_state" / "time_records_latest.json",
        ]
        for t in targets:
            _v75_atomic_json(t, payload)
    except Exception:
        pass


def _v75_sync_time_records_authority_from_sqlite(reason: str = "v75_sync_time_records") -> int:
    """Fast shared 01/02 authority sync after real SQLite mutations.

    01 and 02 share one business table.  To reduce button wait time, 01 is saved
    local-only and 02 performs the GitHub write-through.  Legacy mirror files are
    also written so older restore guards do not revive deleted rows.
    """
    try:
        full_df = query_df("SELECT * FROM time_records ORDER BY id")
    except Exception:
        full_df = pd.DataFrame()
    rows = _v75_table_rows_from_df(full_df)
    _v75_write_legacy_time_record_files(rows, reason=reason)
    try:
        if _v28_update_tables is not None:
            try:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01", github=False)
            except TypeError:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01")
            try:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02", github=True)
            except TypeError:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02")
    except Exception as exc:
        try:
            write_log("TIME_RECORD_AUTHORITY_SYNC_ERROR", f"V75 01/02 權威同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


def _v75_normalize_ids(record_ids) -> list[int]:
    out: list[int] = []
    for rid in record_ids or []:
        try:
            i = int(float(str(rid).strip()))
            if i > 0 and i not in out:
                out.append(i)
        except Exception:
            continue
    return out


def _v75_delete_sqlite_first(record_ids: list[int], reason: str) -> int:
    ids = _v75_normalize_ids(record_ids)
    if not ids:
        return 0
    now = _now()
    user_name = _audit_user_name()
    deleted = 0
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN")
        for rid in ids:
            rec = conn.execute("SELECT * FROM time_records WHERE id=?", (rid,)).fetchone()
            rec_dict = dict(rec) if rec else {}
            cur = conn.execute("DELETE FROM time_records WHERE id=?", (rid,))
            if cur.rowcount and cur.rowcount > 0:
                deleted += int(cur.rowcount)
            conn.execute(
                """
                INSERT INTO system_logs
                (log_time, user_name, action_type, target_table, target_id, message, detail, level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    user_name,
                    "DELETE_TIME_RECORD",
                    "time_records",
                    str(rid),
                    f"{reason}：#{rid} {rec_dict.get('employee_id','')} {rec_dict.get('employee_name','')} {rec_dict.get('work_order','')} {rec_dict.get('process_name','')}",
                    str(rec_dict)[:3000],
                    "WARN",
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return deleted


# Use the original SQL implementations when possible to avoid older authority-first wrappers writing stale data back.
_v75_base_save_time_records = globals().get("_original_v28_save_time_records", save_time_records)
_v75_base_recalculate_time_records = globals().get("_v70_original_recalculate_time_records", recalculate_time_records)
_v75_base_import_time_records = globals().get("_v70_original_import_time_records", import_time_records)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = _v75_base_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps)
    if n:
        synced = _v75_sync_time_records_authority_from_sqlite("save_time_records_v75")
        try:
            write_log("SYNC_TIME_RECORDS_01_02", f"人工儲存後已同步 01/02 權威檔；儲存 {n} 筆，同步 {synced} 筆。", "time_records")
        except Exception:
            pass
    return n


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    count = _v75_base_recalculate_time_records(record_ids)
    if count:
        synced = _v75_sync_time_records_authority_from_sqlite("recalculate_time_records_v75")
        try:
            write_log("SYNC_RECALC_TIME_RECORDS_01_02", f"重新計算工時已扣除 13 系統設定休息時間；重算 {count} 筆，同步 {synced} 筆。", "time_records")
        except Exception:
            pass
    return count


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    result = _v75_base_import_time_records(df, recalc=recalc, source=source)
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v75_sync_time_records_authority_from_sqlite("import_time_records_v75")
    return result


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = _v75_normalize_ids(record_ids)
    if not ids:
        return 0
    deleted = _v75_delete_sqlite_first(ids, reason)
    # Whether SQLite reports rows deleted or not, sync the current SQLite table to
    # both authority files. This prevents stale authority JSON from resurrecting
    # rows that the user just deleted from the live table.
    synced = _v75_sync_time_records_authority_from_sqlite("delete_time_records_v75")
    try:
        mark_data_changed(f"已刪除工時紀錄 {deleted} 筆；01/02 權威檔同步 {synced} 筆。", "DELETE time_records V75")
    except Exception:
        pass
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：已刪除 {deleted} 筆，01/02 權威檔已同步 {synced} 筆。", "time_records")
    except Exception:
        pass
    return int(deleted)
# ======================= END V75 01 admin save/delete persistence stabilization =======================

# ======================= V75 FINAL 01/02 live-history sync + SQLite-first read =======================
# 修正重點：
# 1) 01 開始/暫停/下班/完工後，02 歷史紀錄立即可讀到同一份 SQLite 資料。
# 2) 02 讀取不再優先讀可能過期的 02_history JSON；SQLite 有資料時以 SQLite 為準。
# 3) 管理員儲存、重算、刪除後同步 01/02 權威檔與舊永久檔，避免刪除後又被舊暫存救回。
# 4) 開始/結束作業只做本機權威同步，不打 GitHub，避免一般作業按鈕變慢。

_v75_final_original_start_work = start_work
_v75_final_original_finish_work = finish_work
_v75_final_original_load_records = globals().get("_original_v28_load_records", load_records)


def _v75_apply_load_filters(df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if start_date:
        if "start_date" in out.columns:
            out = out[out["start_date"].astype(str) >= str(start_date)]
        elif "work_date" in out.columns:
            out = out[out["work_date"].astype(str) >= str(start_date)]
    if end_date:
        if "start_date" in out.columns:
            out = out[out["start_date"].astype(str) <= str(end_date)]
        elif "work_date" in out.columns:
            out = out[out["work_date"].astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str) == str(work_order)]
    try:
        if "id" in out.columns:
            out["_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_sort_id", ascending=False).drop(columns=["_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v75_sqlite_has_any_time_records() -> bool:
    try:
        row = query_one("SELECT COUNT(*) AS n FROM time_records") or {}
        return int(row.get("n") or 0) > 0
    except Exception:
        return False


def _v75_load_records_from_authority(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    try:
        if _v28_df_from_table is not None:
            df = _v28_df_from_table("02_history", "time_records")
            return _v75_apply_load_filters(df, start_date, end_date, employee_id, work_order)
    except Exception:
        pass
    return pd.DataFrame()


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    """SQLite-first history read for 01/02 shared time records.

    When SQLite contains rows, it is the live source of truth.  Authority JSON is
    used only as a reboot/empty-database fallback.  This prevents 02 history from
    showing stale JSON after 01 just recorded a new start/end action.
    """
    try:
        ensure_time_records_available("load_records_v75_final")
    except Exception:
        pass
    try:
        df = _v75_final_original_load_records(start_date, end_date, employee_id, work_order)
        if isinstance(df, pd.DataFrame) and (not df.empty or _v75_sqlite_has_any_time_records()):
            return df.reset_index(drop=True)
    except Exception:
        pass
    return _v75_load_records_from_authority(start_date, end_date, employee_id, work_order)


def _v75_sync_time_records_authority_from_sqlite_fast(reason: str = "v75_final_sync", *, github: bool = False) -> int:
    """Sync current SQLite table to 01/02 authority files.

    github=False is used for normal start/end actions to keep 01 fast.  Admin
    save/recalc/delete may pass github=True through the older V75 sync wrapper.
    """
    try:
        full_df = query_df("SELECT * FROM time_records ORDER BY id")
    except Exception:
        full_df = pd.DataFrame()
    rows = _v75_table_rows_from_df(full_df)
    _v75_write_legacy_time_record_files(rows, reason=reason)
    try:
        if _v28_update_tables is not None:
            try:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01", github=False)
            except TypeError:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01")
            try:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02", github=bool(github))
            except TypeError:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02")
    except Exception as exc:
        try:
            write_log("TIME_RECORD_AUTHORITY_SYNC_ERROR", f"V75 final 01/02 權威同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    rid = _v75_final_original_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old)
    # 01 新紀錄後立即同步到 02 可讀來源，但不打 GitHub，避免一般作業卡住。
    if rid:
        try:
            _v75_sync_time_records_authority_from_sqlite_fast("start_work_v75_final", github=False)
        except Exception:
            pass
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    count = _v75_final_original_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group)
    # 暫停 / 下班 / 完工後，02 歷史紀錄立即讀到結束時間與扣休後工時。
    if count:
        try:
            _v75_sync_time_records_authority_from_sqlite_fast("finish_work_v75_final", github=False)
        except Exception:
            pass
    return count
# ===================== END V75 FINAL 01/02 live-history sync + SQLite-first read =====================



# ======================= V76 HARD 01/02 LIVE SYNC FIX =======================
# 目的：修正 01 工時紀錄新增/暫停/完工/下班後，02 歷史紀錄仍看不到新紀錄的問題。
# 原因：先前部分流程仍可能讀到 query cache / 舊 authority JSON / 舊 wrapper。
# 原則：
# 1) 01/02 共用 SQLite time_records 作為即時來源。
# 2) 02 歷史紀錄 load_records 直接讀 SQLite，不再經過可能讀舊 JSON 的 wrapper。
# 3) 01 每次 start_work / finish_work 後，直接用 SQLite 全表刷新 01_time_records + 02_history 權威檔。
# 4) 一般作業同步不打 GitHub，避免 01 頁面慢；管理員儲存/重算/刪除/匯入才允許 github=True。

def _v76_direct_sqlite_time_records_df() -> pd.DataFrame:
    """Read live time_records directly from SQLite, bypassing cached query_df wrappers."""
    try:
        from services.db_service import ensure_database as _ensure_database
        _ensure_database()
    except Exception:
        pass
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA busy_timeout=8000")
            except Exception:
                pass
            try:
                rows = conn.execute("SELECT * FROM time_records ORDER BY id DESC").fetchall()
            except sqlite3.OperationalError as exc:
                # 舊 DB 尚未建立 time_records 時，不讓頁面崩潰。
                if "no such table" in str(exc).lower():
                    return pd.DataFrame()
                raise
            return pd.DataFrame([dict(r) for r in rows])
    except Exception as exc:
        try:
            write_log("V76_DIRECT_SQLITE_READ_ERROR", f"直接讀取 time_records 失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return pd.DataFrame()


def _v76_filter_records_df(df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if start_date:
        if "start_date" in out.columns:
            out = out[out["start_date"].astype(str) >= str(start_date)]
        elif "work_date" in out.columns:
            out = out[out["work_date"].astype(str) >= str(start_date)]
    if end_date:
        if "start_date" in out.columns:
            out = out[out["start_date"].astype(str) <= str(end_date)]
        elif "work_date" in out.columns:
            out = out[out["work_date"].astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str) == str(work_order)]
    try:
        if "id" in out.columns:
            out["_v76_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v76_sort_id", ascending=False).drop(columns=["_v76_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v76_rows_from_sqlite() -> list[dict]:
    df = _v76_direct_sqlite_time_records_df()
    if df is None or df.empty:
        return []
    # 權威檔存放時用 id 遞增較容易人工檢查；畫面 load 再用 id DESC。
    try:
        if "id" in df.columns:
            df = df.assign(_v76_id=pd.to_numeric(df["id"], errors="coerce")).sort_values("_v76_id").drop(columns=["_v76_id"], errors="ignore")
    except Exception:
        pass
    return _v75_table_rows_from_df(df)


def sync_time_records_01_02_now(reason: str = "v76_manual_sync", *, github: bool = False) -> int:
    """Public helper: sync live SQLite time_records into both 01 and 02 authority files."""
    rows = _v76_rows_from_sqlite()
    try:
        _v75_write_legacy_time_record_files(rows, reason=reason)
    except Exception:
        pass
    try:
        if _v28_update_tables is not None:
            try:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01", github=False)
            except TypeError:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01")
            try:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02", github=bool(github))
            except TypeError:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02")
    except Exception as exc:
        try:
            write_log("V76_01_02_SYNC_ERROR", f"01/02 權威同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


# Preserve the latest working implementations, then layer a direct SQLite sync/read on top.
_v76_prev_start_work = start_work
_v76_prev_finish_work = finish_work
_v76_prev_save_time_records = save_time_records
_v76_prev_recalculate_time_records = recalculate_time_records
_v76_prev_delete_time_records = delete_time_records
_v76_prev_import_time_records = import_time_records
_v76_prev_load_records = load_records


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    rid = _v76_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old)
    if rid:
        # 01 新增開始紀錄後，02 歷史紀錄立即可讀；不打 GitHub，避免慢。
        sync_time_records_01_02_now("start_work_v76_live_to_history", github=False)
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    count = _v76_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group)
    if count:
        # 暫停/完工/下班後，02 立即同步結束時間、狀態、扣休後工時。
        sync_time_records_01_02_now("finish_work_v76_live_to_history", github=False)
    return count


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = _v76_prev_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps)
    if n:
        sync_time_records_01_02_now("save_time_records_v76", github=True)
    return n


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    n = _v76_prev_recalculate_time_records(record_ids)
    if n:
        sync_time_records_01_02_now("recalculate_time_records_v76", github=True)
    return n


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    n = _v76_prev_delete_time_records(record_ids, reason=reason)
    # 不論回傳刪除幾筆，都以 SQLite 現況覆蓋 01/02，避免刪除列復活。
    sync_time_records_01_02_now("delete_time_records_v76", github=True)
    return n


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    result = _v76_prev_import_time_records(df, recalc=recalc, source=source)
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        sync_time_records_01_02_now("import_time_records_v76", github=True)
    return result


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    """02 歷史紀錄即時讀取 SQLite。只有 SQLite 空表時才 fallback 權威檔。"""
    try:
        ensure_time_records_available("load_records_v76_sqlite_first")
    except Exception:
        pass
    live_df = _v76_direct_sqlite_time_records_df()
    if live_df is not None and not live_df.empty:
        return _v76_filter_records_df(live_df, start_date, end_date, employee_id, work_order)
    # SQLite 沒資料才讀權威檔，避免 01 剛新增後 02 還讀舊 JSON。
    try:
        auth_df = _v75_load_records_from_authority(start_date, end_date, employee_id, work_order)
        if isinstance(auth_df, pd.DataFrame) and not auth_df.empty:
            return auth_df.reset_index(drop=True)
    except Exception:
        pass
    try:
        return _v76_prev_load_records(start_date, end_date, employee_id, work_order)
    except Exception:
        return pd.DataFrame()
# ===================== END V76 HARD 01/02 LIVE SYNC FIX =====================

# ======================= V77 01 FAST PAGE + ADMIN ACTION HARD FIX =======================
# 目的：
# 1) 01 工時紀錄每次點選都重跑很久：避免 start/finish/save/delete 走多層舊 wrapper 重複同步與 GitHub 寫入。
# 2) 管理員維護區全選/取消/刪除：由 pages/01 以真實 id 欄位修正，本層確保刪除後不被舊權威檔救回。
# 3) 01 -> 02 歷史紀錄：仍以 SQLite time_records 為即時來源，並同步 01/02 本機權威檔；不在一般點擊時打 GitHub。

_V77_APP_SETTING_CACHE: dict[str, tuple[float, str | None]] = {}
_V77_SETTING_TTL_SECONDS = 8.0


def _safe_app_setting_value(setting_key: str) -> str | None:  # type: ignore[override]
    """Cached lightweight app setting reader for 01 page reruns."""
    key = str(setting_key or "").strip()
    if not key:
        return None
    try:
        import time as _time
        now = _time.time()
        cached = _V77_APP_SETTING_CACHE.get(key)
        if cached and (now - float(cached[0])) <= _V77_SETTING_TTL_SECONDS:
            return cached[1]
        _ensure_app_settings_table()
        row = query_one("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)) or {}
        val = row.get("setting_value")
        out = str(val).strip() if val else None
        _V77_APP_SETTING_CACHE[key] = (now, out)
        return out
    except sqlite3.OperationalError:
        try:
            _ensure_app_settings_table()
        except Exception:
            pass
        return None
    except Exception:
        return None


def _v77_direct_query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=8) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
            rows = conn.execute(sql, tuple(params or ())).fetchall()
            return pd.DataFrame([dict(r) for r in rows])
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return pd.DataFrame()
        raise
    except Exception:
        return pd.DataFrame()


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    """Fast 01 live records read. Same business rule, fewer wrappers/cache layers."""
    cycle_start = _business_cycle_start_date()
    unfinished_where = _unfinished_live_where()
    if unfinished_only:
        return _v77_direct_query_df(f"SELECT * FROM time_records WHERE {unfinished_where} ORDER BY id DESC")
    cutoff = _live_page_cutoff_timestamp()
    if cutoff:
        return _v77_direct_query_df(
            f"""
            SELECT * FROM time_records
            WHERE
                ({unfinished_where})
                OR (
                    start_date>=?
                    AND NOT (
                        (
                            COALESCE(status,'')<>'作業中'
                            OR (end_timestamp IS NOT NULL AND TRIM(COALESCE(end_timestamp,''))<>'' AND LOWER(TRIM(COALESCE(end_timestamp,'')))<>'none')
                            OR CAST(COALESCE(work_hours, 0) AS REAL) > 0
                        )
                        AND COALESCE(NULLIF(TRIM(COALESCE(end_timestamp,'')), ''), updated_at, start_timestamp, created_at, '') <= ?
                    )
                )
            ORDER BY id DESC
            """,
            (cycle_start, cutoff),
        )
    return _v77_direct_query_df(
        f"""
        SELECT * FROM time_records
        WHERE start_date>=? OR ({unfinished_where})
        ORDER BY id DESC
        """,
        (cycle_start,),
    )


def _v77_sync_time_records_local(reason: str = "v77_sync") -> int:
    """Local-first 01/02 sync. No GitHub API during 01 page interactions."""
    rows = _v76_rows_from_sqlite() if "_v76_rows_from_sqlite" in globals() else []
    try:
        _v75_write_legacy_time_record_files(rows, reason=reason)
    except Exception:
        pass
    try:
        if _v28_update_tables is not None:
            try:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01", github=False)
            except TypeError:
                _v28_update_tables("01_time_records", {"time_records": rows}, reason=f"{reason}_01")
            try:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02", github=False)
            except TypeError:
                _v28_update_tables("02_history", {"time_records": rows}, reason=f"{reason}_02")
    except Exception as exc:
        try:
            write_log("V77_01_02_LOCAL_SYNC_ERROR", f"01/02 本機權威同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        _V77_APP_SETTING_CACHE.clear()
    except Exception:
        pass
    return int(len(rows))


# Use SQL/business implementations captured before V75/V76 wrapper layers, then sync once.
def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    base = globals().get("_v75_final_original_start_work") or globals().get("_v76_prev_start_work")
    rid = base(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) if callable(base) else 0
    if rid:
        _v77_sync_time_records_local("start_work_v77_fast_local")
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    base = globals().get("_v75_final_original_finish_work") or globals().get("_v76_prev_finish_work")
    count = base(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) if callable(base) else 0
    if count:
        _v77_sync_time_records_local("finish_work_v77_fast_local")
    return count


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    base = globals().get("_v75_base_save_time_records") or globals().get("_original_v28_save_time_records")
    n = base(df, recalc_edited_timestamps=recalc_edited_timestamps) if callable(base) else 0
    if n:
        synced = _v77_sync_time_records_local("save_time_records_v77_fast_local")
        try:
            write_log("SYNC_TIME_RECORDS_01_02", f"人工儲存後已同步 01/02 本機權威檔；儲存 {n} 筆，同步 {synced} 筆。", "time_records")
        except Exception:
            pass
    return int(n or 0)


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    base = globals().get("_v75_base_recalculate_time_records") or globals().get("_v70_original_recalculate_time_records")
    count = base(record_ids) if callable(base) else 0
    if count:
        synced = _v77_sync_time_records_local("recalculate_time_records_v77_fast_local")
        try:
            write_log("SYNC_RECALC_TIME_RECORDS_01_02", f"重新計算工時已扣除 13 系統設定休息時間；重算 {count} 筆，同步 {synced} 筆。", "time_records")
        except Exception:
            pass
    return int(count or 0)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = _v75_normalize_ids(record_ids) if "_v75_normalize_ids" in globals() else [int(x) for x in record_ids or []]
    if not ids:
        return 0
    if "_v75_delete_sqlite_first" in globals():
        deleted = _v75_delete_sqlite_first(ids, reason)
    else:
        placeholders = ",".join(["?"] * len(ids))
        execute(f"DELETE FROM time_records WHERE id IN ({placeholders})", tuple(ids))
        deleted = len(ids)
    synced = _v77_sync_time_records_local("delete_time_records_v77_fast_local")
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：已刪除 {deleted} 筆，01/02 本機權威檔已同步 {synced} 筆。", "time_records")
    except Exception:
        pass
    return int(deleted or 0)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    base = globals().get("_v75_base_import_time_records") or globals().get("_v70_original_import_time_records")
    result = base(df, recalc=recalc, source=source) if callable(base) else {"inserted": 0, "updated": 0}
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v77_sync_time_records_local("import_time_records_v77_fast_local")
    return result
# ===================== END V77 01 FAST PAGE + ADMIN ACTION HARD FIX =====================

# ======================= V79 01 PAGE FAST DISPLAY + STRICT LOCAL SYNC =======================
# Purpose:
# - 01 page should not spend a long time on every click/rerun.
# - Today Records and Admin Maintenance must show the same current SQLite data.
# - 01 -> 02 sync remains immediate, but normal 01 operations do not call GitHub or heavy legacy wrappers.

_V79_TODAY_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_V79_TODAY_CACHE_TTL = 1.2


def _v79_clear_fast_caches() -> None:
    try:
        _V79_TODAY_CACHE.clear()
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        _V77_APP_SETTING_CACHE.clear()  # type: ignore[name-defined]
    except Exception:
        pass


def _v79_rows_from_sqlite() -> list[dict]:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=8) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
            rows = conn.execute("SELECT * FROM time_records ORDER BY id").fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _v79_atomic_json(path, payload: dict) -> None:
    from pathlib import Path as _Path
    import json as _json
    p = _Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(_json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(p)


def _v79_write_0102_latest_files(rows: list[dict], reason: str) -> None:
    """Write only fixed latest files. No history scan, no GitHub, no heavy module wrapper."""
    try:
        from pathlib import Path as _Path
        project = _Path(__file__).resolve().parents[1]
        payload = {
            "version": "V79_TIME_RECORDS_FAST_LATEST",
            "updated_at": _now(),
            "reason": reason,
            "tables": {"time_records": rows},
            "table_counts": {"time_records": len(rows)},
            "description": "01/02 shared time_records latest mirror. SQLite is the runtime authority; these files prevent reboot restore from using stale records.",
        }
        targets = [
            project / "data" / "permanent_store" / "persistent_modules" / "01_time_records" / "01_time_records_records.json",
            project / "data" / "permanent_store" / "persistent_modules" / "02_history" / "02_history_records.json",
            project / "data" / "permanent_store" / "persistent_state" / "time_records_latest.json",
            # compatibility for older restore guards still reading pre-permanent_store paths
            project / "data" / "persistent_modules" / "01_time_records" / "01_time_records_records.json",
            project / "data" / "persistent_modules" / "02_history" / "02_history_records.json",
            project / "data" / "persistent_state" / "time_records_latest.json",
        ]
        for t in targets:
            _v79_atomic_json(t, payload)
    except Exception as exc:
        try:
            write_log("V79_TIME_RECORD_LATEST_WRITE_ERROR", f"01/02 latest mirror failed: {exc}", "time_records", level="ERROR")
        except Exception:
            pass


def _v79_sync_time_records_fast(reason: str = "v79_fast_sync") -> int:
    rows = _v79_rows_from_sqlite()
    _v79_write_0102_latest_files(rows, reason)
    _v79_clear_fast_caches()
    try:
        # Lightweight pending marker only; avoids GitHub API during 01 clicks.
        mark_data_changed("01/02 工時紀錄已變更，已寫入本機最新永久檔。", "time_records")
    except Exception:
        pass
    return int(len(rows))


_v79_base_today_records = today_records


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    """V79 cached fast 01 display. Cache is cleared after any time-record mutation."""
    import time as _time
    key = (bool(include_finished), bool(unfinished_only), _business_cycle_start_date(), _live_page_cutoff_timestamp() or "")
    now = _time.time()
    cached = _V79_TODAY_CACHE.get(key)
    if cached and (now - float(cached[0])) <= _V79_TODAY_CACHE_TTL:
        return cached[1].copy()
    df = _v79_base_today_records(include_finished=include_finished, unfinished_only=unfinished_only)
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    _V79_TODAY_CACHE[key] = (now, df.copy())
    return df.reset_index(drop=True)


def sync_time_records_01_02_now(reason: str = "v79_manual_sync", *, github: bool = False) -> int:  # type: ignore[override]
    # github argument intentionally ignored on 01 realtime path to keep page responsive.
    return _v79_sync_time_records_fast(reason)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    base = globals().get("_v75_final_original_start_work") or globals().get("_v76_prev_start_work")
    rid = base(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) if callable(base) else 0
    if rid:
        _v79_sync_time_records_fast("start_work_v79_fast")
    return int(rid or 0)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    base = globals().get("_v75_final_original_finish_work") or globals().get("_v76_prev_finish_work")
    count = base(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) if callable(base) else 0
    if count:
        _v79_sync_time_records_fast("finish_work_v79_fast")
    return int(count or 0)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    base = globals().get("_v75_base_save_time_records") or globals().get("_original_v28_save_time_records")
    n = base(df, recalc_edited_timestamps=recalc_edited_timestamps) if callable(base) else 0
    if n:
        _v79_sync_time_records_fast("save_time_records_v79_fast")
    return int(n or 0)


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    base = globals().get("_v75_base_recalculate_time_records") or globals().get("_v70_original_recalculate_time_records")
    count = base(record_ids) if callable(base) else 0
    if count:
        _v79_sync_time_records_fast("recalculate_time_records_v79_fast")
    return int(count or 0)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = _v75_normalize_ids(record_ids) if "_v75_normalize_ids" in globals() else [int(x) for x in record_ids or [] if str(x).strip()]
    if not ids:
        return 0
    if "_v75_delete_sqlite_first" in globals():
        deleted = _v75_delete_sqlite_first(ids, reason)
    else:
        placeholders = ",".join(["?"] * len(ids))
        execute(f"DELETE FROM time_records WHERE id IN ({placeholders})", tuple(ids))
        deleted = len(ids)
    _v79_sync_time_records_fast("delete_time_records_v79_fast")
    return int(deleted or 0)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    base = globals().get("_v75_base_import_time_records") or globals().get("_v70_original_import_time_records")
    result = base(df, recalc=recalc, source=source) if callable(base) else {"inserted": 0, "updated": 0}
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v79_sync_time_records_fast("import_time_records_v79_fast")
    return result
# ===================== END V79 01 PAGE FAST DISPLAY + STRICT LOCAL SYNC =====================


# ========================= V84 01/02 SINGLE AUTHORITY SYNC =========================
# 01 工時紀錄與 02 歷史紀錄：回復 V28 權威檔方式，但嚴格改成只讀/寫 canonical records.json。
# 不再寫 persistent_modules / persistent_state 舊鏡像，避免刪除/修改後 Reboot 又被舊資料復活。

def _v84_table_rows_from_df(df: pd.DataFrame) -> list[dict]:
    try:
        from services.permanent_authority_service import table_from_df as _pa_table_from_df
        return _pa_table_from_df(df)
    except Exception:
        try:
            return [dict(r) for _, r in df.fillna("").iterrows()]
        except Exception:
            return []


def _v84_authority_file_exists(module_key: str, kind: str = "records") -> bool:
    try:
        from services.permanent_authority_service import authority_file_exists as _pa_exists
        return bool(_pa_exists(module_key, kind))
    except Exception:
        try:
            from services.permanent_authority_service import canonical_path as _pa_path
            return bool(_pa_path(module_key, kind).exists())
        except Exception:
            return False


def _v84_load_time_authority_df(module_key: str = "02_history") -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df_from_table
        df = _pa_df_from_table(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _v84_sync_time_records_canonical_from_sqlite(reason: str = "v84_time_sync", *, github: bool = True) -> int:
    try:
        full_df = query_df("SELECT * FROM time_records ORDER BY id")
    except Exception:
        full_df = pd.DataFrame()
    rows = _v84_table_rows_from_df(full_df if isinstance(full_df, pd.DataFrame) else pd.DataFrame())
    try:
        from services.permanent_authority_service import save_authority as _pa_save_authority
        # 01 與 02 都是正式 canonical 權威檔；只寫同一路徑，不再寫舊鏡像。
        _pa_save_authority("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
        _pa_save_authority("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
    except Exception as exc:
        try:
            write_log("V84_TIME_AUTHORITY_SYNC_ERROR", f"01/02 canonical 權威檔同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        _v79_clear_fast_caches()  # type: ignore[name-defined]
    except Exception:
        pass
    return int(len(rows))


def _v84_filter_records_df(df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    if start_date:
        col = "work_date" if "work_date" in out.columns else "start_date"
        if col in out.columns:
            out = out[out[col].astype(str) >= str(start_date)]
    if end_date:
        col = "work_date" if "work_date" in out.columns else "start_date"
        if col in out.columns:
            out = out[out[col].astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str) == str(work_order)]
    if "id" in out.columns:
        try:
            out = out.sort_values("id", ascending=False, kind="stable")
        except Exception:
            pass
    return out.reset_index(drop=True)


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    # 02 歷史紀錄只讀 02_history canonical。若檔案存在，即使空檔也代表正式資料，不得 fallback SQLite/舊檔。
    if _v84_authority_file_exists("02_history", "records"):
        return _v84_filter_records_df(_v84_load_time_authority_df("02_history"), start_date, end_date, employee_id, work_order)
    base = globals().get("_original_v28_load_records") or globals().get("_v79_base_load_records")
    if callable(base):
        return base(start_date, end_date, employee_id, work_order)
    return pd.DataFrame()


def _v84_is_unfinished_df(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype=bool)
    status = df.get("status", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    end_ts = df.get("end_timestamp", pd.Series("", index=df.index)).fillna("").astype(str).str.strip().str.lower()
    return status.eq("作業中") & (end_ts.eq("") | end_ts.eq("none") | end_ts.eq("nan") | end_ts.eq("nat"))


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    # 01 今日工時紀錄只要 canonical 存在就從 01_time_records 讀；防止 SQLite 舊快取與管理員表不同步。
    if not _v84_authority_file_exists("01_time_records", "records"):
        base = globals().get("_v79_base_today_records")
        return base(include_finished=include_finished, unfinished_only=unfinished_only) if callable(base) else pd.DataFrame()
    df = _v84_load_time_authority_df("01_time_records")
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    unfinished = _v84_is_unfinished_df(out)
    if unfinished_only:
        out = out.loc[unfinished].copy()
    else:
        cycle_start = _business_cycle_start_date() if "_business_cycle_start_date" in globals() else today_text()
        if "start_date" in out.columns:
            current_cycle = out["start_date"].astype(str) >= str(cycle_start)
            out = out.loc[current_cycle | unfinished].copy()
    if "id" in out.columns:
        try:
            out["_id_sort"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_id_sort", ascending=False, kind="stable").drop(columns=["_id_sort"], errors="ignore")
        except Exception:
            pass
    return out.reset_index(drop=True)


# Save/mutate wrappers: execute business logic, then sync only canonical authority files.
def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    base = globals().get("_v75_final_original_start_work") or globals().get("_v76_prev_start_work")
    rid = base(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) if callable(base) else 0
    if rid:
        _v84_sync_time_records_canonical_from_sqlite("start_work_v84", github=True)
    return int(rid or 0)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    base = globals().get("_v75_final_original_finish_work") or globals().get("_v76_prev_finish_work")
    count = base(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) if callable(base) else 0
    if count:
        _v84_sync_time_records_canonical_from_sqlite("finish_work_v84", github=True)
    return int(count or 0)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    base = globals().get("_v75_base_save_time_records") or globals().get("_original_v28_save_time_records")
    n = base(df, recalc_edited_timestamps=recalc_edited_timestamps) if callable(base) else 0
    if n:
        _v84_sync_time_records_canonical_from_sqlite("save_time_records_v84", github=True)
    return int(n or 0)


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    base = globals().get("_v75_base_recalculate_time_records") or globals().get("_v70_original_recalculate_time_records")
    count = base(record_ids) if callable(base) else 0
    if count:
        _v84_sync_time_records_canonical_from_sqlite("recalculate_time_records_v84", github=True)
    return int(count or 0)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = _v75_normalize_ids(record_ids) if "_v75_normalize_ids" in globals() else [int(float(str(x))) for x in record_ids or [] if str(x).strip()]
    if not ids:
        return 0
    if "_v75_delete_sqlite_first" in globals():
        deleted = _v75_delete_sqlite_first(ids, reason)
    else:
        placeholders = ",".join(["?"] * len(ids))
        execute(f"DELETE FROM time_records WHERE id IN ({placeholders})", tuple(ids))
        deleted = len(ids)
    _v84_sync_time_records_canonical_from_sqlite("delete_time_records_v84", github=True)
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：已刪除 {deleted} 筆，01/02 canonical 權威檔已同步。", "time_records")
    except Exception:
        pass
    return int(deleted or 0)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    base = globals().get("_v75_base_import_time_records") or globals().get("_v70_original_import_time_records")
    result = base(df, recalc=recalc, source=source) if callable(base) else {"inserted": 0, "updated": 0}
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v84_sync_time_records_canonical_from_sqlite("import_time_records_v84", github=True)
    return result


def sync_time_records_01_02_now(reason: str = "v84_manual_sync", *, github: bool = True) -> int:  # type: ignore[override]
    return _v84_sync_time_records_canonical_from_sqlite(reason, github=github)
# ======================= END V84 01/02 SINGLE AUTHORITY SYNC =====================


# ======================= V86 01 FAST LOAD / SYNC OVERRIDE =======================
# 目標：01 工時紀錄為作業人員主要頁面，開始/結束作業後不得因 GitHub/重型查詢卡住。
# 原則：
# 1. 業務規則不改：仍走原 start_work / finish_work / save / recalc / delete。
# 2. 01/02 權威檔仍同步，但一般作業先做本機 canonical；管理員操作可依設定做 GitHub。
# 3. today_records 加短暫快取，資料異動後立即清除。
# 4. 建立 SQLite 索引，加速目前作業與今日紀錄查詢。

_V86_TODAY_CACHE: dict[tuple[bool, bool], tuple[float, pd.DataFrame]] = {}
_V86_INDEX_READY = False
_V86_TODAY_CACHE_SECONDS = 5.0

try:
    _v86_prev_today_records = today_records
except Exception:
    _v86_prev_today_records = None
try:
    _v86_prev_start_work = start_work
except Exception:
    _v86_prev_start_work = None
try:
    _v86_prev_finish_work = finish_work
except Exception:
    _v86_prev_finish_work = None
try:
    _v86_prev_save_time_records = save_time_records
except Exception:
    _v86_prev_save_time_records = None
try:
    _v86_prev_recalculate_time_records = recalculate_time_records
except Exception:
    _v86_prev_recalculate_time_records = None
try:
    _v86_prev_delete_time_records = delete_time_records
except Exception:
    _v86_prev_delete_time_records = None
try:
    _v86_prev_import_time_records = import_time_records
except Exception:
    _v86_prev_import_time_records = None


def _v86_time_now_seconds() -> float:
    try:
        import time as _time
        return float(_time.time())
    except Exception:
        return 0.0


def clear_today_records_fast_cache() -> None:
    """Public cache clear hook for 01 page / other services."""
    try:
        _V86_TODAY_CACHE.clear()
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass


def _v86_ensure_time_record_indexes_once() -> None:
    global _V86_INDEX_READY
    if _V86_INDEX_READY:
        return
    _V86_INDEX_READY = True
    stmts = [
        "CREATE INDEX IF NOT EXISTS idx_time_records_start_date ON time_records(start_date)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_employee_active ON time_records(employee_id, end_timestamp, status)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_group_active ON time_records(employee_id, employee_name, process_name, start_date, end_timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_updated_at ON time_records(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_time_records_work_order ON time_records(work_order)",
    ]
    for sql in stmts:
        try:
            execute(sql)
        except Exception:
            pass


def _v86_fast_sync_time_authority(reason: str, *, github: bool = False) -> int:
    """Sync 01/02 canonical files without forcing slow GitHub during operator clicks."""
    try:
        if "_v84_sync_time_records_canonical_from_sqlite" in globals():
            return int(_v84_sync_time_records_canonical_from_sqlite(reason, github=github))
    except Exception as exc:
        try:
            write_log("V86_FAST_SYNC_ERROR", f"01/02 權威檔快速同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    return 0


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    _v86_ensure_time_record_indexes_once()
    key = (bool(include_finished), bool(unfinished_only))
    now_s = _v86_time_now_seconds()
    cached = _V86_TODAY_CACHE.get(key)
    if cached and (now_s - cached[0] <= _V86_TODAY_CACHE_SECONDS):
        return cached[1].copy()
    if callable(_v86_prev_today_records):
        df = _v86_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only)
    else:
        df = pd.DataFrame()
    if df is None:
        df = pd.DataFrame()
    _V86_TODAY_CACHE[key] = (now_s, df.copy())
    return df.copy()


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    _v86_ensure_time_record_indexes_once()
    rid = _v86_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) if callable(_v86_prev_start_work) else 0
    clear_today_records_fast_cache()
    # 作業員點選開始時不做重型 GitHub；本機 canonical 立即同步，02 歷史可即時讀到。
    if rid:
        _v86_fast_sync_time_authority("start_work_v86_fast", github=False)
    return int(rid or 0)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    _v86_ensure_time_record_indexes_once()
    count = _v86_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) if callable(_v86_prev_finish_work) else 0
    clear_today_records_fast_cache()
    if count:
        _v86_fast_sync_time_authority("finish_work_v86_fast", github=False)
    return int(count or 0)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = _v86_prev_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps) if callable(_v86_prev_save_time_records) else 0
    clear_today_records_fast_cache()
    if n:
        # 管理員明確存檔才允許 GitHub，但底層有 unchanged skip 與短逾時。
        _v86_fast_sync_time_authority("save_time_records_v86", github=True)
    return int(n or 0)


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    count = _v86_prev_recalculate_time_records(record_ids) if callable(_v86_prev_recalculate_time_records) else 0
    clear_today_records_fast_cache()
    if count:
        _v86_fast_sync_time_authority("recalculate_time_records_v86", github=True)
    return int(count or 0)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    deleted = _v86_prev_delete_time_records(record_ids, reason=reason) if callable(_v86_prev_delete_time_records) else 0
    clear_today_records_fast_cache()
    if deleted:
        _v86_fast_sync_time_authority("delete_time_records_v86", github=True)
    return int(deleted or 0)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    result = _v86_prev_import_time_records(df, recalc=recalc, source=source) if callable(_v86_prev_import_time_records) else {"inserted": 0, "updated": 0}
    clear_today_records_fast_cache()
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v86_fast_sync_time_authority("import_time_records_v86", github=True)
    return result


def sync_time_records_01_02_now(reason: str = "v86_manual_sync", *, github: bool = True) -> int:  # type: ignore[override]
    clear_today_records_fast_cache()
    return _v86_fast_sync_time_authority(reason, github=github)
# ===================== END V86 01 FAST LOAD / SYNC OVERRIDE =====================

# ======================= V89 02 HISTORY STRICT AUTHORITY-FIRST =======================
# 修正目的：
# 1. 02 歷史紀錄刪除後，不得再因 SQLite 舊快取 / 舊 wrapper / 編輯存檔而復活。
# 2. 02 的讀、寫、刪除、重算均以 canonical 權威檔為準：
#    data/permanent_store/modules/02_history/records.json
# 3. 01/02 共用 time_records，因此 02 修改完成後同步寫入 01_time_records canonical，
#    SQLite 僅作快取，並由 canonical 覆蓋快取，避免舊資料救回。

try:
    _v89_prev_start_work = start_work
except Exception:
    _v89_prev_start_work = None
try:
    _v89_prev_finish_work = finish_work
except Exception:
    _v89_prev_finish_work = None
try:
    _v89_prev_import_time_records = import_time_records
except Exception:
    _v89_prev_import_time_records = None
try:
    _v89_prev_today_records = today_records
except Exception:
    _v89_prev_today_records = None

_V89_CHECKBOX_COLS = {
    "刪除", "重算", "刪除 / Delete", "重算 / Recalc", "選取", "Select", "selected",
    "__selected__", "_selected", "_row_selected", "Delete", "Recalc",
}


def _v89_normalize_record_id(value) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        rid = int(float(str(value).strip()))
        return rid if rid > 0 else None
    except Exception:
        return None


def _v89_id_list(values) -> list[int]:
    out: list[int] = []
    for v in values or []:
        rid = _v89_normalize_record_id(v)
        if rid is not None and rid not in out:
            out.append(rid)
    return out


def _v89_authority_df(module_key: str = "02_history") -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df_from_table
        df = _pa_df_from_table(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _v89_table_rows_from_df(df: pd.DataFrame) -> list[dict]:
    if df is None:
        return []
    try:
        from services.permanent_authority_service import table_from_df as _pa_table_from_df
        return _pa_table_from_df(df)
    except Exception:
        rows: list[dict] = []
        try:
            clean = df.copy()
            clean = clean.where(pd.notna(clean), None)
            for _, r in clean.iterrows():
                rows.append(dict(r))
        except Exception:
            pass
        return rows


def _v89_sort_records(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "id" in out.columns:
        try:
            out["_v89_id_sort"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v89_id_sort", ascending=False, kind="stable").drop(columns=["_v89_id_sort"], errors="ignore")
            return out.reset_index(drop=True)
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v89_save_time_authority_df(df: pd.DataFrame, reason: str = "v89_save_time_authority", *, github: bool = True) -> int:
    """Save one canonical time_records DataFrame to both 01 and 02 authority files."""
    rows = _v89_table_rows_from_df(_v89_sort_records(df))
    try:
        from services.permanent_authority_service import save_authority as _pa_save_authority
        _pa_save_authority("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
        _pa_save_authority("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
    except Exception as exc:
        try:
            write_log("V89_TIME_AUTHORITY_SAVE_ERROR", f"01/02 權威檔寫入失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_today_records_fast_cache()  # type: ignore[name-defined]
    except Exception:
        try:
            clear_query_cache()
        except Exception:
            pass
    return int(len(rows))


def _v89_existing_time_columns() -> list[str]:
    try:
        rows = query_df("PRAGMA table_info(time_records)")
        if isinstance(rows, pd.DataFrame) and not rows.empty and "name" in rows.columns:
            return [str(x) for x in rows["name"].tolist() if str(x)]
    except Exception:
        pass
    return []


def _v89_sync_sqlite_cache_from_authority(df: pd.DataFrame) -> int:
    """Rewrite SQLite cache from canonical authority.

    SQLite 在此架構下只是快取。02 刪除或編輯後，必須用 canonical 覆蓋快取，
    不能再用 SQLite 反向覆蓋 canonical，否則刪除資料會復活。
    """
    try:
        cols = _v89_existing_time_columns()
        if not cols:
            return 0
        clean = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if clean.empty:
            rows: list[dict] = []
        else:
            # 補齊 DB 欄位，只寫入 DB 既有欄位，避免新增 UI 欄位造成 SQL 失敗。
            for c in cols:
                if c not in clean.columns:
                    clean[c] = None
            clean = clean[cols].where(pd.notna(clean[cols]), None)
            rows = clean.to_dict(orient="records")
        import sqlite3 as _sqlite3
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _sqlite3.connect(DB_PATH, timeout=15)
        try:
            conn.execute("PRAGMA busy_timeout=8000")
            conn.execute("BEGIN")
            conn.execute("DELETE FROM time_records")
            if rows:
                placeholders = ",".join(["?"] * len(cols))
                quoted_cols = ",".join([f'"{c}"' for c in cols])
                sql = f'INSERT INTO time_records ({quoted_cols}) VALUES ({placeholders})'
                vals = [tuple(r.get(c) for c in cols) for r in rows]
                conn.executemany(sql, vals)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        try:
            clear_query_cache()
        except Exception:
            pass
        return len(rows)
    except Exception as exc:
        try:
            write_log("V89_SQLITE_CACHE_SYNC_ERROR", f"SQLite 快取由權威檔覆蓋失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return 0


def _v89_next_id(df: pd.DataFrame) -> int:
    try:
        if df is not None and not df.empty and "id" in df.columns:
            max_id = pd.to_numeric(df["id"], errors="coerce").dropna().max()
            if pd.notna(max_id):
                return int(max_id) + 1
    except Exception:
        pass
    return 1


def _v89_clean_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    drop_cols = [c for c in out.columns if str(c).strip() in _V89_CHECKBOX_COLS]
    if drop_cols:
        out = out.drop(columns=drop_cols, errors="ignore")
    # 移除完全空白新增列。
    if not out.empty:
        try:
            non_id_cols = [c for c in out.columns if str(c) not in {"id", "ID", "ID / ID"}]
            if non_id_cols:
                mask_any = out[non_id_cols].apply(lambda r: any(not _is_blank_value(v) for v in r), axis=1)
                out = out.loc[mask_any].copy()
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v89_normalize_row_for_save(row: dict, *, recalc_work_hours: bool = False) -> dict:
    out = dict(row)
    try:
        normalized_dt = normalize_record_datetime_fields(out, recalc_work_hours=recalc_work_hours)
        out.update(normalized_dt)
    except Exception:
        pass
    # 工時欄可能是 HH:MM:SS 顯示格式，存回 decimal hours。
    if "work_hours" in out and not _is_blank_value(out.get("work_hours")):
        try:
            v = out.get("work_hours")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out["work_hours"] = float(v)
            else:
                out["work_hours"] = hms_to_hours(v)
        except Exception:
            pass
    if "is_group_work" in out and not _is_blank_value(out.get("is_group_work")):
        try:
            out["is_group_work"] = int(bool(out.get("is_group_work")))
        except Exception:
            pass
    out["updated_at"] = _now()
    if not out.get("created_at"):
        out["created_at"] = _now()
    if not out.get("record_key"):
        try:
            out["record_key"] = make_record_key(
                str(out.get("employee_id") or ""),
                str(out.get("work_order") or ""),
                str(out.get("process_name") or ""),
                str(out.get("start_timestamp") or ""),
            )
        except Exception:
            out["record_key"] = uuid.uuid4().hex
    return out


def _v89_filter_records_df(df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    if start_date:
        col = "work_date" if "work_date" in out.columns else "start_date"
        if col in out.columns:
            out = out[out[col].fillna("").astype(str) >= str(start_date)]
    if end_date:
        col = "work_date" if "work_date" in out.columns else "start_date"
        if col in out.columns:
            out = out[out[col].fillna("").astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].fillna("").astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].fillna("").astype(str) == str(work_order)]
    return _v89_sort_records(out)


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    # V89：02 歷史紀錄只讀 02_history canonical。SQLite 永遠只是快取，不作為 02 來源。
    df = _v89_authority_df("02_history")
    return _v89_filter_records_df(df, start_date, end_date, employee_id, work_order)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    """V89 authority-first save.

    編輯表格只更新/新增畫面中的列，不會用 SQLite 舊資料覆蓋 canonical。
    """
    edit_df = _v89_clean_editor_df(df)
    if edit_df.empty:
        return 0
    auth_df = _v89_authority_df("02_history")
    if auth_df is None:
        auth_df = pd.DataFrame()

    # 用 canonical 欄位 + 編輯欄位聯集，避免欄位遺失。
    cols: list[str] = []
    for c in list(auth_df.columns if isinstance(auth_df, pd.DataFrame) else []) + list(edit_df.columns):
        if str(c) not in cols:
            cols.append(str(c))
    if "id" not in cols:
        cols.insert(0, "id")
    if auth_df.empty:
        auth_df = pd.DataFrame(columns=cols)
    else:
        for c in cols:
            if c not in auth_df.columns:
                auth_df[c] = None
        auth_df = auth_df[cols].copy()

    next_id = _v89_next_id(auth_df)
    updated = 0
    by_id: dict[int, int] = {}
    if not auth_df.empty and "id" in auth_df.columns:
        for idx, val in auth_df["id"].items():
            rid = _v89_normalize_record_id(val)
            if rid is not None:
                by_id[rid] = idx

    for _, r in edit_df.iterrows():
        row = dict(r)
        rid = _v89_normalize_record_id(row.get("id")) or _v89_normalize_record_id(row.get("ID")) or _v89_normalize_record_id(row.get("ID / ID"))
        if rid is None:
            rid = next_id
            next_id += 1
        row["id"] = rid
        row = _v89_normalize_row_for_save(row, recalc_work_hours=bool(recalc_edited_timestamps))
        for c in row.keys():
            if c not in auth_df.columns:
                auth_df[c] = None
        if rid in by_id:
            idx = by_id[rid]
            for c, v in row.items():
                auth_df.at[idx, c] = v
        else:
            new_row = {c: None for c in auth_df.columns}
            for c, v in row.items():
                if c not in new_row:
                    auth_df[c] = None
                    new_row[c] = v
                else:
                    new_row[c] = v
            auth_df = pd.concat([auth_df, pd.DataFrame([new_row])], ignore_index=True)
            by_id[rid] = int(auth_df.index[-1])
        updated += 1

    _v89_save_time_authority_df(auth_df, "save_time_records_v89_authority_first", github=True)
    _v89_sync_sqlite_cache_from_authority(auth_df)
    try:
        write_log("SAVE_TIME_RECORDS", f"V89 權威檔優先：已儲存/更新歷史紀錄 {updated} 筆，並同步 01/02 canonical。", "time_records")
    except Exception:
        pass
    return int(updated)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = set(_v89_id_list(record_ids))
    if not ids:
        return 0
    auth_df = _v89_authority_df("02_history")
    if auth_df is None or auth_df.empty or "id" not in auth_df.columns:
        return 0
    id_series = auth_df["id"].map(_v89_normalize_record_id)
    before = len(auth_df)
    remaining = auth_df.loc[~id_series.isin(ids)].copy()
    deleted = before - len(remaining)
    if deleted:
        _v89_save_time_authority_df(remaining, "delete_time_records_v89_authority_first", github=True)
        _v89_sync_sqlite_cache_from_authority(remaining)
        try:
            write_log("DELETE_TIME_RECORDS", f"{reason}：V89 權威檔優先已刪除 {deleted} 筆，SQLite 快取已由 canonical 覆蓋，不會復活。", "time_records", level="WARN")
        except Exception:
            pass
    return int(deleted)


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    auth_df = _v89_authority_df("02_history")
    if auth_df is None or auth_df.empty:
        return 0
    ids = set(_v89_id_list(record_ids)) if record_ids else set()
    if "id" not in auth_df.columns:
        return 0
    target_mask = auth_df["id"].map(_v89_normalize_record_id).map(lambda x: bool(x in ids) if ids else True)
    count = 0
    for idx in auth_df.loc[target_mask].index:
        row = dict(auth_df.loc[idx])
        start_ts = row.get("start_timestamp")
        end_ts = row.get("end_timestamp")
        if _is_blank_value(start_ts) or _is_blank_value(end_ts):
            continue
        normalized = normalize_record_datetime_fields(row, recalc_work_hours=True)
        if not normalized.get("start_timestamp") or not normalized.get("end_timestamp"):
            continue
        for c, v in normalized.items():
            if c not in auth_df.columns:
                auth_df[c] = None
            auth_df.at[idx, c] = v
        status = str(auth_df.at[idx, "status"] if "status" in auth_df.columns else "").strip()
        if not status or status == "作業中":
            if "status" not in auth_df.columns:
                auth_df["status"] = None
            auth_df.at[idx, "status"] = row.get("end_action") or "已結束"
        if "updated_at" not in auth_df.columns:
            auth_df["updated_at"] = None
        auth_df.at[idx, "updated_at"] = _now()
        count += 1
    if count:
        _v89_save_time_authority_df(auth_df, "recalculate_time_records_v89_authority_first", github=True)
        _v89_sync_sqlite_cache_from_authority(auth_df)
        try:
            write_log("RECALC_TIME_RECORDS", f"V89 權威檔優先：已重新計算 {count} 筆工時，並同步 01/02 canonical。", "time_records")
        except Exception:
            pass
    return int(count)


def sync_time_records_01_02_now(reason: str = "v89_manual_sync", *, github: bool = True) -> int:  # type: ignore[override]
    """V89：手動同步時，以 02_history canonical 為準同步 01 與 SQLite 快取。"""
    auth_df = _v89_authority_df("02_history")
    _v89_save_time_authority_df(auth_df, reason, github=bool(github))
    _v89_sync_sqlite_cache_from_authority(auth_df)
    return int(len(auth_df) if isinstance(auth_df, pd.DataFrame) else 0)
# ===================== END V89 02 HISTORY STRICT AUTHORITY-FIRST =====================

# ===================== V89B 01 ACTION BASELINE FROM AUTHORITY =====================
# 防止 01 開始/完工使用舊 SQLite 快取後，又把已刪除的 02 紀錄同步回 canonical。

def _v89_baseline_sqlite_from_canonical(reason: str = "v89_baseline") -> int:
    df = _v89_authority_df("02_history")
    return _v89_sync_sqlite_cache_from_authority(df)


def _v89_sync_canonical_from_sqlite_after_live_action(reason: str, *, github: bool = False) -> int:
    try:
        if "_v84_sync_time_records_canonical_from_sqlite" in globals():
            return int(_v84_sync_time_records_canonical_from_sqlite(reason, github=bool(github)))
    except Exception as exc:
        try:
            write_log("V89_LIVE_SYNC_ERROR", f"01 live action 後由 SQLite 同步 canonical 失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    return 0


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    _v89_baseline_sqlite_from_canonical("start_work_v89_baseline")
    rid = _v89_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) if callable(_v89_prev_start_work) else 0
    try:
        clear_today_records_fast_cache()  # type: ignore[name-defined]
    except Exception:
        pass
    if rid:
        _v89_sync_canonical_from_sqlite_after_live_action("start_work_v89", github=False)
    return int(rid or 0)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    _v89_baseline_sqlite_from_canonical("finish_work_v89_baseline")
    count = _v89_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) if callable(_v89_prev_finish_work) else 0
    try:
        clear_today_records_fast_cache()  # type: ignore[name-defined]
    except Exception:
        pass
    if count:
        _v89_sync_canonical_from_sqlite_after_live_action("finish_work_v89", github=False)
    return int(count or 0)


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    # 匯入前先讓 SQLite 快取等於 canonical，避免舊 SQLite 殘留列被匯入同步流程帶回。
    _v89_baseline_sqlite_from_canonical("import_time_records_v89_baseline")
    result = _v89_prev_import_time_records(df, recalc=recalc, source=source) if callable(_v89_prev_import_time_records) else {"inserted": 0, "updated": 0}
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v89_sync_canonical_from_sqlite_after_live_action("import_time_records_v89", github=True)
        try:
            clear_today_records_fast_cache()  # type: ignore[name-defined]
        except Exception:
            pass
    return result
# =================== END V89B 01 ACTION BASELINE FROM AUTHORITY ===================

# ===================== V90 01 FINISH-WORK AUTHORITY MERGE FIX =====================
# 修正 V89：finish_work 前先用 02_history canonical 覆蓋 SQLite，會把 01 頁面剛查到的作業中 id 洗掉，
# 導致「找不到工時紀錄」。V90 結束作業不再先 baseline；改成直接更新目前 SQLite 中的作業中列，
# 再只把本次受影響的列 upsert 到 01/02 canonical 權威檔，最後以 canonical 回寫 SQLite 快取。


def _v90_id_list(ids) -> list[int]:
    out: list[int] = []
    for x in ids or []:
        try:
            if pd.isna(x):
                continue
        except Exception:
            pass
        try:
            out.append(int(float(str(x).strip())))
        except Exception:
            continue
    seen: set[int] = set()
    deduped: list[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped


def _v90_query_records_by_ids(ids: list[int]) -> pd.DataFrame:
    clean_ids = _v90_id_list(ids)
    if not clean_ids:
        return pd.DataFrame()
    placeholders = ",".join(["?"] * len(clean_ids))
    try:
        return query_df(f"SELECT * FROM time_records WHERE id IN ({placeholders}) ORDER BY id", clean_ids)
    except Exception:
        rows = []
        for rid in clean_ids:
            r = query_one("SELECT * FROM time_records WHERE id=?", (rid,)) or {}
            if r:
                rows.append(r)
        return pd.DataFrame(rows)


def _v90_upsert_rows_to_0102_authority(rows_df: pd.DataFrame, reason: str = "finish_work_v90", *, github: bool = False) -> int:
    if rows_df is None or not isinstance(rows_df, pd.DataFrame) or rows_df.empty:
        return 0
    if "id" not in rows_df.columns:
        return 0
    try:
        auth_df = _v89_authority_df("02_history") if "_v89_authority_df" in globals() else pd.DataFrame()
    except Exception:
        auth_df = pd.DataFrame()
    if auth_df is None or not isinstance(auth_df, pd.DataFrame):
        auth_df = pd.DataFrame()

    rows = rows_df.copy()
    rows = rows.loc[:, ~pd.Index(rows.columns).duplicated()].copy()
    auth_df = auth_df.loc[:, ~pd.Index(auth_df.columns).duplicated()].copy() if not auth_df.empty else pd.DataFrame()

    # 欄位聯集，避免 01/02 顯示欄位或後續重算欄位被洗掉。
    all_cols: list[str] = []
    for c in list(auth_df.columns) + list(rows.columns):
        sc = str(c)
        if sc not in all_cols:
            all_cols.append(sc)
    if "id" not in all_cols:
        all_cols.insert(0, "id")
    if auth_df.empty:
        auth_df = pd.DataFrame(columns=all_cols)
    else:
        for c in all_cols:
            if c not in auth_df.columns:
                auth_df[c] = None
        auth_df = auth_df[all_cols].copy()
    for c in all_cols:
        if c not in rows.columns:
            rows[c] = None
    rows = rows[all_cols].copy()

    by_id: dict[int, int] = {}
    if "id" in auth_df.columns:
        for idx, val in auth_df["id"].items():
            rid = _v89_normalize_record_id(val) if "_v89_normalize_record_id" in globals() else None
            if rid is None:
                try:
                    rid = int(float(str(val).strip()))
                except Exception:
                    rid = None
            if rid is not None:
                by_id[int(rid)] = idx

    changed = 0
    for _, row in rows.iterrows():
        rid = _v89_normalize_record_id(row.get("id")) if "_v89_normalize_record_id" in globals() else None
        if rid is None:
            try:
                rid = int(float(str(row.get("id")).strip()))
            except Exception:
                continue
        row_dict = row.to_dict()
        if "_v89_normalize_row_for_save" in globals():
            try:
                row_dict = _v89_normalize_row_for_save(row_dict, recalc_work_hours=False)
            except Exception:
                pass
        for c in row_dict.keys():
            if c not in auth_df.columns:
                auth_df[c] = None
        if int(rid) in by_id:
            idx = by_id[int(rid)]
            for c, v in row_dict.items():
                auth_df.at[idx, c] = v
        else:
            new_row = {c: None for c in auth_df.columns}
            for c, v in row_dict.items():
                if c not in auth_df.columns:
                    auth_df[c] = None
                    new_row[c] = v
                else:
                    new_row[c] = v
            auth_df = pd.concat([auth_df, pd.DataFrame([new_row])], ignore_index=True)
            by_id[int(rid)] = int(auth_df.index[-1])
        changed += 1

    if changed:
        if "_v89_save_time_authority_df" in globals():
            _v89_save_time_authority_df(auth_df, reason, github=bool(github))
        elif "_v84_sync_time_records_canonical_from_sqlite" in globals():
            _v84_sync_time_records_canonical_from_sqlite(reason, github=bool(github))
        # 以 canonical 覆蓋 SQLite 快取，可清掉 02 已刪除但 SQLite 仍殘留的紀錄。
        try:
            if "_v89_sync_sqlite_cache_from_authority" in globals():
                _v89_sync_sqlite_cache_from_authority(auth_df)
        except Exception as exc:
            try:
                write_log("V90_SQLITE_CACHE_SYNC_WARN", f"V90 結束作業後同步 SQLite 快取失敗：{exc}", "time_records", level="WARN")
            except Exception:
                pass
    return int(changed)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    """V90：01 結束/暫停/完工不再先用 02 權威檔覆蓋 SQLite。

    直接對目前作業中的 SQLite 紀錄完成結束動作，然後只把本次受影響列合併回 01/02 權威檔。
    這可避免 V89 的「先 baseline」把畫面剛取得的 record_id 洗掉，造成找不到工時紀錄。
    """
    try:
        if "_v86_ensure_time_record_indexes_once" in globals():
            _v86_ensure_time_record_indexes_once()
    except Exception:
        pass

    try:
        rid0 = int(float(str(record_id).strip()))
    except Exception:
        raise ValueError("工時紀錄編號異常，請重新整理頁面後再操作。")

    rec = query_one("SELECT * FROM time_records WHERE id=?", (rid0,))
    if not rec:
        # 只有找不到時才嘗試由 canonical 補回 SQLite；避免一開始就覆蓋掉現場作業中的列。
        try:
            if "_v89_baseline_sqlite_from_canonical" in globals():
                _v89_baseline_sqlite_from_canonical("finish_work_v90_missing_record_retry")
        except Exception:
            pass
        rec = query_one("SELECT * FROM time_records WHERE id=?", (rid0,))
        if not rec:
            raise ValueError("找不到工時紀錄；此筆可能已刪除、已結束，或畫面資料尚未重新整理。請重新整理 01. 工時紀錄後再操作。")
    if rec.get("end_timestamp"):
        return 0

    now = _now()
    end_date, end_time = split_timestamp(now)
    status = end_action if end_action in ("下班", "暫停", "完工") else "已結束"

    if finish_parallel_group:
        try:
            group = get_active_group(rid0)
        except Exception:
            group = pd.DataFrame([rec])
    else:
        group = pd.DataFrame([rec])
    if group is None or not isinstance(group, pd.DataFrame) or group.empty:
        group = pd.DataFrame([rec])

    group_ids = _v90_id_list(group.get("id", pd.Series([rid0])).tolist())
    if not group_ids:
        group_ids = [rid0]
    try:
        starts = [str(x) for x in group.get("start_timestamp", pd.Series(dtype=object)).dropna().tolist() if str(x).strip()]
        earliest_start = min(starts) if starts else str(rec.get("start_timestamp") or now)
    except Exception:
        earliest_start = str(rec.get("start_timestamp") or now)
    total_hours = calculate_work_hours(earliest_start, now)
    avg_hours = round(total_hours / max(len(group_ids), 1), 2)
    try:
        is_group = 1 if len(group_ids) > 1 else int(rec.get("is_group_work") or 0)
    except Exception:
        is_group = 1 if len(group_ids) > 1 else 0
    group_key = rec.get("group_key") or f"{rec.get('employee_id')}|{rec.get('process_name')}|{rec.get('start_date')}"

    updated_ids: list[int] = []
    for rid in group_ids:
        old = query_one("SELECT remark FROM time_records WHERE id=?", (rid,)) or {}
        new_remark = old.get("remark") or ""
        append = remark or ""
        if len(group_ids) > 1:
            append = (append + "；" if append else "") + _v138_parallel_summary_text(len(group_ids), total_hours, avg_hours)
        if append:
            new_remark = (new_remark + "；" if new_remark else "") + append
        try:
            execute(
                """
                UPDATE time_records
                SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?,
                    work_hours=?, remark=?, group_key=?, is_group_work=?, updated_at=?
                WHERE id=? AND end_timestamp IS NULL
                """,
                (status, end_action, now, end_date, end_time, avg_hours, new_remark, group_key, is_group, now, int(rid)),
            )
            updated_ids.append(int(rid))
        except Exception as exc:
            try:
                write_log("V90_FINISH_UPDATE_ERROR", f"更新工時紀錄 #{rid} 失敗：{exc}", "time_records", rid, level="ERROR")
            except Exception:
                pass

    updated_ids = _v90_id_list(updated_ids)
    if not updated_ids:
        return 0

    try:
        rows_df = _v90_query_records_by_ids(updated_ids)
        _v90_upsert_rows_to_0102_authority(rows_df, "finish_work_v90_authority_merge", github=False)
    finally:
        try:
            clear_today_records_fast_cache()  # type: ignore[name-defined]
        except Exception:
            pass

    try:
        write_log(
            "END_WORK_GROUP" if len(updated_ids) > 1 else "END_WORK",
            f"V90 結束工時紀錄 #{rid0}，同步結束={len(updated_ids)}筆，狀態={status}，群組總工時={_v138_hours_to_hms_label(total_hours)}，平均工時={_v138_hours_to_hms_label(avg_hours)}",
            "time_records",
            rid0,
            detail=",".join(str(x) for x in updated_ids),
        )
    except Exception:
        pass
    return int(len(updated_ids))
# =================== END V90 01 FINISH-WORK AUTHORITY MERGE FIX ===================


# ===================== V94 02 HISTORY DELETE TOMBSTONE + 01 EDITOR SAFETY =====================
# 目的：02 歷史紀錄刪除後，任何後續編輯/01同步/SQLite舊快取都不得把已刪紀錄救回。
# 作法：在 02_history/settings.json 記錄 deleted_record_ids / deleted_record_keys，所有 save/upsert 都會過濾 tombstone。

try:
    _v94_prev_save_time_records = save_time_records
except Exception:
    _v94_prev_save_time_records = None
try:
    _v94_prev_delete_time_records = delete_time_records
except Exception:
    _v94_prev_delete_time_records = None
try:
    _v94_prev_v90_upsert_rows_to_0102_authority = _v90_upsert_rows_to_0102_authority
except Exception:
    _v94_prev_v90_upsert_rows_to_0102_authority = None


def _v94_history_settings() -> dict:
    try:
        from services.permanent_authority_service import load_settings as _pa_load_settings
        data = _pa_load_settings("02_history")
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _v94_save_history_settings(settings: dict, reason: str = "history_settings_v94") -> None:
    try:
        from services.permanent_authority_service import save_settings as _pa_save_settings
        _pa_save_settings("02_history", settings or {}, reason=reason, github=True)
    except Exception:
        pass


def _v94_deleted_ids_keys() -> tuple[set[int], set[str]]:
    stg = _v94_history_settings()
    ids = set()
    keys = set()
    for x in stg.get("deleted_record_ids", []) if isinstance(stg.get("deleted_record_ids", []), list) else []:
        rid = _v89_normalize_record_id(x) if "_v89_normalize_record_id" in globals() else None
        if rid is not None:
            ids.add(int(rid))
    for x in stg.get("deleted_record_keys", []) if isinstance(stg.get("deleted_record_keys", []), list) else []:
        sx = str(x or "").strip()
        if sx:
            keys.add(sx)
    return ids, keys


def _v94_record_key_from_row(row) -> str:
    try:
        if isinstance(row, dict):
            v = row.get("record_key") or row.get("紀錄鍵 / Record Key")
        else:
            v = row.get("record_key") if "record_key" in row.index else (row.get("紀錄鍵 / Record Key") if "紀錄鍵 / Record Key" in row.index else "")
        return str(v or "").strip()
    except Exception:
        return ""


def _v94_filter_deleted_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    ids, keys = _v94_deleted_ids_keys()
    if not ids and not keys:
        return df
    out = df.copy()
    mask = pd.Series([True] * len(out), index=out.index)
    id_col = None
    for c in ["id", "ID", "ID / ID", "ID / ID / ID"]:
        if c in out.columns:
            id_col = c; break
    if id_col and ids:
        mask &= ~out[id_col].map(lambda x: (_v89_normalize_record_id(x) if "_v89_normalize_record_id" in globals() else None) in ids)
    key_col = None
    for c in ["record_key", "紀錄鍵 / Record Key"]:
        if c in out.columns:
            key_col = c; break
    if key_col and keys:
        mask &= ~out[key_col].fillna("").astype(str).str.strip().isin(keys)
    return out.loc[mask].copy().reset_index(drop=True)


def _v94_add_history_tombstones(df_or_rows) -> None:
    stg = _v94_history_settings()
    ids = set(stg.get("deleted_record_ids", []) if isinstance(stg.get("deleted_record_ids", []), list) else [])
    keys = set(stg.get("deleted_record_keys", []) if isinstance(stg.get("deleted_record_keys", []), list) else [])
    try:
        if isinstance(df_or_rows, pd.DataFrame):
            rows = [r for _, r in df_or_rows.iterrows()]
        else:
            rows = list(df_or_rows or [])
    except Exception:
        rows = []
    for r in rows:
        try:
            rid = None
            if isinstance(r, dict):
                for c in ["id", "ID", "ID / ID", "ID / ID / ID"]:
                    rid = _v89_normalize_record_id(r.get(c)) if "_v89_normalize_record_id" in globals() else None
                    if rid is not None:
                        break
            else:
                for c in ["id", "ID", "ID / ID", "ID / ID / ID"]:
                    if c in r.index:
                        rid = _v89_normalize_record_id(r.get(c)) if "_v89_normalize_record_id" in globals() else None
                        if rid is not None:
                            break
            if rid is not None:
                ids.add(int(rid))
            k = _v94_record_key_from_row(r)
            if k:
                keys.add(k)
        except Exception:
            continue
    stg["deleted_record_ids"] = sorted({int(x) for x in ids if _v89_normalize_record_id(x) is not None})
    stg["deleted_record_keys"] = sorted({str(x) for x in keys if str(x).strip()})
    stg["delete_tombstone_updated_at"] = _now() if "_now" in globals() else now_text()
    _v94_save_history_settings(stg, "v94_history_delete_tombstone")


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v89_authority_df("02_history") if "_v89_authority_df" in globals() else pd.DataFrame()
    df = _v94_filter_deleted_df(df)
    return _v89_filter_records_df(df, start_date, end_date, employee_id, work_order) if "_v89_filter_records_df" in globals() else df


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    safe_df = _v94_filter_deleted_df(_v89_clean_editor_df(df) if "_v89_clean_editor_df" in globals() else df)
    if safe_df is None or safe_df.empty:
        return 0
    n = _v94_prev_save_time_records(safe_df, recalc_edited_timestamps=recalc_edited_timestamps) if callable(_v94_prev_save_time_records) else 0
    # 儲存後再次清洗 canonical，防止舊 wrapper 或 SQLite 快取帶回已刪列。
    try:
        auth_df = _v94_filter_deleted_df(_v89_authority_df("02_history"))
        if "_v89_save_time_authority_df" in globals():
            _v89_save_time_authority_df(auth_df, "save_time_records_v94_tombstone_filter", github=True)
        if "_v89_sync_sqlite_cache_from_authority" in globals():
            _v89_sync_sqlite_cache_from_authority(auth_df)
    except Exception:
        pass
    return int(n or 0)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = set(_v89_id_list(record_ids) if "_v89_id_list" in globals() else [int(x) for x in record_ids or []])
    if not ids:
        return 0
    auth_df = _v89_authority_df("02_history") if "_v89_authority_df" in globals() else pd.DataFrame()
    if auth_df is None or auth_df.empty:
        _v94_add_history_tombstones([{"id": x} for x in ids])
        return 0
    id_col = "id" if "id" in auth_df.columns else ("ID" if "ID" in auth_df.columns else None)
    if not id_col:
        _v94_add_history_tombstones([{"id": x} for x in ids])
        return 0
    match_mask = auth_df[id_col].map(lambda x: (_v89_normalize_record_id(x) if "_v89_normalize_record_id" in globals() else None) in ids)
    deleted_rows = auth_df.loc[match_mask].copy()
    _v94_add_history_tombstones(deleted_rows if not deleted_rows.empty else [{"id": x} for x in ids])
    remaining = _v94_filter_deleted_df(auth_df.loc[~match_mask].copy())
    deleted = int(len(auth_df) - len(remaining))
    if "_v89_save_time_authority_df" in globals():
        _v89_save_time_authority_df(remaining, "delete_time_records_v94_tombstone", github=True)
    if "_v89_sync_sqlite_cache_from_authority" in globals():
        _v89_sync_sqlite_cache_from_authority(remaining)
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：V94 已刪除 {deleted} 筆並建立 tombstone，後續編輯/SQLite 不會復活。", "time_records", level="WARN")
    except Exception:
        pass
    return deleted


def _v90_upsert_rows_to_0102_authority(rows_df: pd.DataFrame, reason: str = "finish_work_v94", *, github: bool = False) -> int:  # type: ignore[override]
    rows_df = _v94_filter_deleted_df(rows_df)
    if rows_df is None or rows_df.empty:
        return 0
    n = _v94_prev_v90_upsert_rows_to_0102_authority(rows_df, reason=reason, github=github) if callable(_v94_prev_v90_upsert_rows_to_0102_authority) else 0
    try:
        auth_df = _v94_filter_deleted_df(_v89_authority_df("02_history"))
        if "_v89_save_time_authority_df" in globals():
            _v89_save_time_authority_df(auth_df, f"{reason}_v94_final_filter", github=bool(github))
        if "_v89_sync_sqlite_cache_from_authority" in globals():
            _v89_sync_sqlite_cache_from_authority(auth_df)
    except Exception:
        pass
    return int(n or 0)
# =================== END V94 02 HISTORY DELETE TOMBSTONE + 01 EDITOR SAFETY ===================

# ===================== V96 01 FAST START + 01/02 DELETE AUTHORITY HARD FIX =====================
# 目的：
# 1) 01 開始作業不再 baseline / 全量同步 / GitHub，改為核心插入 + 單筆 upsert 到 01/02 權威檔。
# 2) 01 管理員刪除必須同時刪 SQLite、01_time_records、02_history，並建立 02 tombstone，避免 02 復活。
# 3) 不改扣休、群組平均、工時規則；只改同步與刪除寫入路徑。


def _v96_id_set(ids) -> set[int]:
    out: set[int] = set()
    for x in ids or []:
        try:
            if pd.isna(x):
                continue
        except Exception:
            pass
        try:
            out.add(int(float(str(x).strip())))
        except Exception:
            continue
    return out


def _v96_fast_authority_df(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df
        df = _pa_df(module_key, "time_records")
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _v96_table_rows(df: pd.DataFrame) -> list[dict]:
    try:
        from services.permanent_authority_service import table_from_df as _pa_table
        return _pa_table(df)
    except Exception:
        try:
            return [dict(r) for _, r in df.fillna("").iterrows()]
        except Exception:
            return []


def _v96_save_0102_df(df: pd.DataFrame, reason: str = "v96_time_authority", *, github: bool = False) -> int:
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    try:
        df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    except Exception:
        pass
    try:
        if "id" in df.columns:
            df["_sort_id"] = pd.to_numeric(df["id"], errors="coerce")
            df = df.sort_values("_sort_id").drop(columns=["_sort_id"], errors="ignore")
    except Exception:
        pass
    rows = _v96_table_rows(df)
    try:
        from services.permanent_authority_service import save_authority as _pa_save
        _pa_save("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
        _pa_save("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
    except Exception as exc:
        try:
            write_log("V96_TIME_AUTH_SAVE_ERROR", f"V96 01/02 權威檔寫入失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    return int(len(rows))


def _v96_filter_tombstone(df: pd.DataFrame) -> pd.DataFrame:
    try:
        return _v94_filter_deleted_df(df) if "_v94_filter_deleted_df" in globals() else df
    except Exception:
        return df


def _v96_upsert_rows_to_authority(rows_df: pd.DataFrame, reason: str = "v96_upsert", *, github: bool = False) -> int:
    if rows_df is None or not isinstance(rows_df, pd.DataFrame) or rows_df.empty or "id" not in rows_df.columns:
        return 0
    rows_df = rows_df.loc[:, ~pd.Index(rows_df.columns).duplicated()].copy()
    auth_df = _v96_fast_authority_df("02_history")
    auth_df = _v96_filter_tombstone(auth_df)
    if auth_df is None or not isinstance(auth_df, pd.DataFrame) or auth_df.empty:
        auth_df = pd.DataFrame(columns=list(rows_df.columns))
    auth_df = auth_df.loc[:, ~pd.Index(auth_df.columns).duplicated()].copy()
    all_cols = []
    for c in list(auth_df.columns) + list(rows_df.columns):
        if c not in all_cols:
            all_cols.append(c)
    if "id" not in all_cols:
        all_cols.insert(0, "id")
    for c in all_cols:
        if c not in auth_df.columns:
            auth_df[c] = None
        if c not in rows_df.columns:
            rows_df[c] = None
    auth_df = auth_df[all_cols].copy(); rows_df = rows_df[all_cols].copy()
    id_to_idx = {}
    for idx, val in auth_df["id"].items():
        try:
            id_to_idx[int(float(str(val).strip()))] = idx
        except Exception:
            pass
    changed = 0
    for _, r in rows_df.iterrows():
        try:
            rid = int(float(str(r.get("id")).strip()))
        except Exception:
            continue
        if rid in id_to_idx:
            idx = id_to_idx[rid]
            for c, v in r.to_dict().items():
                auth_df.at[idx, c] = v
        else:
            auth_df = pd.concat([auth_df, pd.DataFrame([r.to_dict()])], ignore_index=True)
            id_to_idx[rid] = int(auth_df.index[-1])
        changed += 1
    auth_df = _v96_filter_tombstone(auth_df)
    if changed:
        _v96_save_0102_df(auth_df, reason, github=github)
    return int(changed)


def _v96_query_rows_by_ids(ids) -> pd.DataFrame:
    clean = sorted(_v96_id_set(ids))
    if not clean:
        return pd.DataFrame()
    try:
        ph = ",".join(["?"] * len(clean))
        return query_df(f"SELECT * FROM time_records WHERE id IN ({ph}) ORDER BY id", list(clean))
    except Exception:
        rows = []
        for rid in clean:
            r = query_one("SELECT * FROM time_records WHERE id=?", (rid,)) or {}
            if r:
                rows.append(r)
        return pd.DataFrame(rows)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    """V96：核心快速開始作業。避免 V89 baseline + 全量同步造成 1 分鐘以上等待。"""
    try:
        if "_v86_ensure_time_record_indexes_once" in globals():
            _v86_ensure_time_record_indexes_once()
    except Exception:
        pass
    now = _now()
    start_date, start_time = split_timestamp(now)
    employee_id = str(employee.get("employee_id") or "").strip()
    employee_name = str(employee.get("employee_name") or "").strip()
    wo_no = str(work_order.get("work_order") or "").strip()
    process_name = str(process_name or "").strip()
    if not employee_id or not wo_no or not process_name:
        raise ValueError("工號、製令、工段名稱不可空白。")
    duplicate = get_active_same_work(employee_id, wo_no, process_name, start_date, employee_name=employee_name)
    if duplicate:
        raise ValueError(f"此人員已有相同製令與工段正在計時，禁止重複紀錄：{wo_no} / {process_name}")
    conflicts = get_conflicting_active_records(employee_id, process_name, start_date, employee_name=employee_name)
    if not conflicts.empty:
        if not auto_pause_old:
            raise ValueError("此人員已有不同工段正在計時，請先確認暫停前一筆作業後再開始新紀錄。")
        _pause_conflicting_active_records(employee_id, employee_name, process_name, start_date)
    record_key = make_record_key(employee_id, wo_no, process_name, now)
    group_key = f"{employee_id}|{process_name}|{start_date}"
    rid = execute(
        """
        INSERT INTO time_records(
            record_key, status, work_order, part_no, type_name, process_name,
            employee_id, employee_name, start_action, start_timestamp,
            remark, start_date, start_time, assembly_location,
            group_key, is_group_work, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_key, "作業中", wo_no, work_order.get("part_no", ""), work_order.get("type_name", ""),
            process_name, employee_id, employee_name, "開始", now, remark, start_date, start_time,
            work_order.get("assembly_location", ""), group_key, 0, "streamlit", now, now,
        ),
    )
    parallel = get_active_records(employee_id=employee_id, employee_name=employee_name, process_name=process_name, start_date=start_date)
    affected = [rid]
    if len(parallel) > 1:
        execute(
            "UPDATE time_records SET is_group_work=1, group_key=?, updated_at=? WHERE employee_id=? AND COALESCE(employee_name,'')=? AND process_name=? AND start_date=? AND end_timestamp IS NULL",
            (group_key, now, employee_id, employee_name, process_name, start_date),
        )
        try:
            affected = [int(x) for x in parallel.get("id", pd.Series([rid])).tolist()] + [int(rid)]
        except Exception:
            affected = [rid]
    rows_df = _v96_query_rows_by_ids(affected)
    _v96_upsert_rows_to_authority(rows_df, "start_work_v96_fast_upsert", github=False)
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        write_log("START_WORK", f"{employee_name} 開始 {wo_no} / {process_name}", "time_records", rid)
    except Exception:
        pass
    return int(rid or 0)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    """V96：快速結束/暫停，不做全量 SQLite<->authority 洗資料。"""
    try:
        rid0 = int(float(str(record_id).strip()))
    except Exception:
        raise ValueError("工時紀錄編號異常，請重新整理頁面後再操作。")
    rec = query_one("SELECT * FROM time_records WHERE id=?", (rid0,))
    if not rec:
        raise ValueError("找不到工時紀錄；此筆可能已刪除、已結束，或畫面資料尚未重新整理。")
    if rec.get("end_timestamp"):
        return 0
    now = _now()
    end_date, end_time = split_timestamp(now)
    status = end_action if end_action in ("下班", "暫停", "完工") else "已結束"
    group = get_active_group(rid0) if finish_parallel_group else pd.DataFrame([rec])
    if group is None or group.empty:
        group = pd.DataFrame([rec])
    group_ids = [int(x) for x in group["id"].tolist()]
    earliest_start = min(str(x) for x in group["start_timestamp"].dropna().tolist()) if "start_timestamp" in group.columns else str(rec.get("start_timestamp") or now)
    total_hours = calculate_work_hours(earliest_start, now)
    avg_hours = round(total_hours / max(len(group_ids), 1), 2)
    is_group = 1 if len(group_ids) > 1 else int(rec.get("is_group_work") or 0)
    group_key = rec.get("group_key") or f"{rec.get('employee_id')}|{rec.get('process_name')}|{rec.get('start_date')}"
    updated = []
    for rid in group_ids:
        old = query_one("SELECT remark FROM time_records WHERE id=?", (rid,)) or {}
        new_remark = old.get("remark") or ""
        append = remark or ""
        if len(group_ids) > 1:
            append = (append + "；" if append else "") + _v138_parallel_summary_text(len(group_ids), total_hours, avg_hours)
        if append:
            new_remark = (new_remark + "；" if new_remark else "") + append
        execute(
            """
            UPDATE time_records
            SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?,
                work_hours=?, remark=?, group_key=?, is_group_work=?, updated_at=?
            WHERE id=? AND end_timestamp IS NULL
            """,
            (status, end_action, now, end_date, end_time, avg_hours, new_remark, group_key, is_group, now, int(rid)),
        )
        updated.append(int(rid))
    rows_df = _v96_query_rows_by_ids(updated)
    _v96_upsert_rows_to_authority(rows_df, "finish_work_v96_fast_upsert", github=False)
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        write_log("END_WORK_GROUP" if len(updated) > 1 else "END_WORK", f"V96 結束工時紀錄 #{rid0}，同步結束={len(updated)}筆，狀態={status}", "time_records", rid0, detail=",".join(str(x) for x in updated))
    except Exception:
        pass
    return int(len(updated))


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = _v96_id_set(record_ids)
    if not ids:
        return 0
    # 建立 tombstone：即使 02 / SQLite 舊快取殘留，也不得復活。
    try:
        rows_for_tombstone = _v96_query_rows_by_ids(sorted(ids))
        if rows_for_tombstone is None or rows_for_tombstone.empty:
            rows_for_tombstone = pd.DataFrame([{"id": x} for x in sorted(ids)])
        if "_v94_add_history_tombstones" in globals():
            _v94_add_history_tombstones(rows_for_tombstone)
    except Exception:
        pass
    # 刪 SQLite 快取。
    deleted_sqlite = 0
    try:
        ph = ",".join(["?"] * len(ids))
        before = query_one(f"SELECT COUNT(*) AS n FROM time_records WHERE id IN ({ph})", list(ids)) or {}
        deleted_sqlite = int(before.get("n") or 0)
        execute(f"DELETE FROM time_records WHERE id IN ({ph})", tuple(sorted(ids)))
    except Exception as exc:
        try:
            write_log("V96_DELETE_SQLITE_ERROR", f"SQLite 刪除失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    # 權威檔以 02_history 為主；同步移除 01/02。
    auth_df = _v96_fast_authority_df("02_history")
    if auth_df is None or auth_df.empty:
        auth_df = _v96_fast_authority_df("01_time_records")
    if auth_df is None or not isinstance(auth_df, pd.DataFrame):
        auth_df = pd.DataFrame()
    if not auth_df.empty:
        auth_df = auth_df.loc[:, ~pd.Index(auth_df.columns).duplicated()].copy()
        id_col = "id" if "id" in auth_df.columns else ("ID" if "ID" in auth_df.columns else "")
        if id_col:
            before_n = len(auth_df)
            auth_df = auth_df[~auth_df[id_col].map(lambda x: (_v96_id_set([x]).pop() if _v96_id_set([x]) else None) in ids)].copy()
            auth_df = _v96_filter_tombstone(auth_df)
            deleted_auth = before_n - len(auth_df)
        else:
            deleted_auth = 0
    else:
        deleted_auth = 0
    _v96_save_0102_df(auth_df, "delete_time_records_v96_0102_sync", github=True)
    try:
        clear_today_records_fast_cache()
        clear_query_cache()
    except Exception:
        pass
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：V96 已刪除 SQLite {deleted_sqlite} 筆、01/02 權威檔 {deleted_auth} 筆，並建立 tombstone。", "time_records", level="WARN")
    except Exception:
        pass
    return int(max(deleted_sqlite, deleted_auth, len(ids)))


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v96_fast_authority_df("02_history")
    df = _v96_filter_tombstone(df)
    return _v89_filter_records_df(df, start_date, end_date, employee_id, work_order) if "_v89_filter_records_df" in globals() else df

# =================== END V96 01 FAST START + 01/2 DELETE AUTHORITY HARD FIX ===================

# =================== V97 01/02 SYNC TOMBSTONE-ID REUSE HARD FIX ===================
# 修正重點：
# - 舊版 02 tombstone 同時記錄 id 與 record_key。SQLite 重建後 id 可能被重用，
#   造成 01 新增成功但同步 02 時被舊 id tombstone 誤殺。
# - V97 改為 record_key 優先；只有 row 沒有 record_key 時，才允許 id-only tombstone 生效。
# - 新開始作業完成後若新 record_key 不在刪除清單，會移除同 id 的舊 tombstone，避免後續再被誤過濾。

_v97_prev_start_work = start_work


def _v97_filter_deleted_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    try:
        ids, keys = _v94_deleted_ids_keys() if "_v94_deleted_ids_keys" in globals() else (set(), set())
    except Exception:
        ids, keys = set(), set()
    if not ids and not keys:
        return df
    out = df.copy()
    id_col = next((c for c in ["id", "ID", "ID / ID", "ID / ID / ID"] if c in out.columns), "")
    key_col = next((c for c in ["record_key", "紀錄鍵 / Record Key"] if c in out.columns), "")
    mask = pd.Series([True] * len(out), index=out.index)

    if key_col and keys:
        key_s = out[key_col].fillna("").astype(str).str.strip()
        mask &= ~key_s.isin(keys)

    # ID tombstone 僅處理沒有 record_key 的舊資料；避免 SQLite id 重用造成新資料無法同步 02。
    if id_col and ids:
        if key_col:
            key_s = out[key_col].fillna("").astype(str).str.strip()
            no_key = key_s.eq("")
        else:
            no_key = pd.Series([True] * len(out), index=out.index)
        id_deleted = out[id_col].map(lambda x: (_v89_normalize_record_id(x) if "_v89_normalize_record_id" in globals() else None) in ids)
        mask &= ~(no_key & id_deleted)
    return out.loc[mask].copy().reset_index(drop=True)


def _v97_clear_reused_id_tombstone(record_id: int, record_key: str) -> None:
    try:
        stg = _v94_history_settings() if "_v94_history_settings" in globals() else {}
        keys = {str(x).strip() for x in stg.get("deleted_record_keys", []) if str(x).strip()}
        if str(record_key or "").strip() in keys:
            return
        rid = _v89_normalize_record_id(record_id) if "_v89_normalize_record_id" in globals() else None
        if rid is None:
            return
        old_ids = stg.get("deleted_record_ids", []) if isinstance(stg.get("deleted_record_ids", []), list) else []
        new_ids = []
        changed = False
        for x in old_ids:
            xid = _v89_normalize_record_id(x) if "_v89_normalize_record_id" in globals() else None
            if xid == rid:
                changed = True
                continue
            if xid is not None:
                new_ids.append(int(xid))
        if changed:
            stg["deleted_record_ids"] = sorted(set(new_ids))
            stg["delete_tombstone_updated_at"] = _now() if "_now" in globals() else now_text()
            # 開始作業路徑必須維持秒級；清除 SQLite id 重用 tombstone 只寫本地權威檔，避免同步 GitHub 阻塞人員操作。
            try:
                from services.permanent_authority_service import save_settings as _pa_save_settings
                _pa_save_settings("02_history", stg, reason="v97_clear_reused_sqlite_id_tombstone", github=False)
            except Exception:
                _v94_save_history_settings(stg, "v97_clear_reused_sqlite_id_tombstone")
    except Exception:
        pass


def _v96_filter_tombstone(df: pd.DataFrame) -> pd.DataFrame:  # type: ignore[override]
    try:
        return _v97_filter_deleted_df(df)
    except Exception:
        return df


def _v94_filter_deleted_df(df: pd.DataFrame) -> pd.DataFrame:  # type: ignore[override]
    try:
        return _v97_filter_deleted_df(df)
    except Exception:
        return df


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    rid = int(_v97_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    try:
        row = _v96_query_rows_by_ids([rid]) if "_v96_query_rows_by_ids" in globals() else pd.DataFrame()
        record_key = ""
        if isinstance(row, pd.DataFrame) and not row.empty and "record_key" in row.columns:
            record_key = str(row.iloc[0].get("record_key") or "").strip()
        _v97_clear_reused_id_tombstone(rid, record_key)
        if isinstance(row, pd.DataFrame) and not row.empty and "_v96_upsert_rows_to_authority" in globals():
            _v96_upsert_rows_to_authority(row, "start_work_v97_reused_id_safe_upsert", github=False)
    except Exception as exc:
        try:
            write_log("V97_START_SYNC_ERROR", f"01 開始作業後同步 02 權威檔失敗：{exc}", "time_records", rid, level="ERROR")
        except Exception:
            pass
    return rid
# ================= END V97 01/02 SYNC TOMBSTONE-ID REUSE HARD FIX =================

# ========================= V98 01/02 TRUE WRITE-THROUGH + DISPLAY SELF-REPAIR =========================
# 修正目的：
# 1) 01 開始作業先前為了速度 github=False，只寫本機 authority；Streamlit Cloud Reboot 後會消失。
# 2) 今日工時紀錄 / 02 歷史紀錄若遇到空 authority，但 SQLite 已有作業中資料，畫面會顯示 No data。
# 3) 01/02 必須共用同一批 time_records，任何開始、結束、刪除、重算、匯入後都同步 canonical 權威檔。

_v98_prev_today_records = today_records
_v98_prev_load_records = load_records
_v98_prev_start_work = start_work
_v98_prev_finish_work = finish_work
_v98_prev_save_time_records = save_time_records
_v98_prev_recalculate_time_records = recalculate_time_records
_v98_prev_delete_time_records = delete_time_records
_v98_prev_import_time_records = globals().get("import_time_records")


def _v98_is_nonempty_df(df: pd.DataFrame) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty


def _v98_sqlite_time_records_df() -> pd.DataFrame:
    try:
        df = query_df("SELECT * FROM time_records ORDER BY id")
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _v98_sort_records(df: pd.DataFrame, descending: bool = False) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    if "id" in out.columns:
        try:
            out["_v98_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v98_sort_id", ascending=not descending, kind="stable").drop(columns=["_v98_sort_id"], errors="ignore")
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v98_filter_deleted(df: pd.DataFrame) -> pd.DataFrame:
    try:
        if "_v97_filter_deleted_df" in globals():
            return _v97_filter_deleted_df(df)
        if "_v96_filter_tombstone" in globals():
            return _v96_filter_tombstone(df)
    except Exception:
        pass
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _v98_table_rows(df: pd.DataFrame) -> list[dict]:
    try:
        from services.permanent_authority_service import table_from_df as _pa_table
        return _pa_table(df)
    except Exception:
        try:
            clean = df.copy().where(pd.notna(df), "")
            return [dict(r) for _, r in clean.iterrows()]
        except Exception:
            return []


def _v98_force_upload_time_authority(reason: str = "v98_force_upload") -> None:
    try:
        from services.permanent_authority_service import force_upload_authority_file as _pa_force_upload
        _pa_force_upload("01_time_records", "records", reason=reason)
        _pa_force_upload("02_history", "records", reason=reason)
    except Exception:
        pass


def _v98_save_0102_authority_df(df: pd.DataFrame, reason: str = "v98_save_0102", *, github: bool = True) -> int:
    out = _v98_sort_records(_v98_filter_deleted(df), descending=False)
    rows = _v98_table_rows(out)
    try:
        from services.permanent_authority_service import save_authority as _pa_save
        # 先寫本機 canonical，再強制上傳。即使本機內容 unchanged，也要確保 GitHub 有最新檔。
        _pa_save("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=False)
        _pa_save("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=False)
        if github:
            _v98_force_upload_time_authority(reason)
    except Exception as exc:
        try:
            write_log("V98_TIME_AUTHORITY_SAVE_ERROR", f"V98 01/02 權威檔寫入失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


def _v98_sync_0102_from_sqlite(reason: str = "v98_sync_from_sqlite", *, github: bool = True) -> int:
    return _v98_save_0102_authority_df(_v98_sqlite_time_records_df(), reason=reason, github=github)


def _v98_authority_df(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df
        df = _pa_df(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return _v98_filter_deleted(df.copy())
    except Exception:
        pass
    return pd.DataFrame()


def _v98_authority_or_sqlite_df(module_key: str, reason: str = "v98_display_repair") -> pd.DataFrame:
    auth_df = _v98_authority_df(module_key)
    if _v98_is_nonempty_df(auth_df):
        return _v98_sort_records(auth_df, descending=True)
    # 畫面自我修復：authority 空但 SQLite 有資料時，不能讓使用者看到 No data。
    sqlite_df = _v98_filter_deleted(_v98_sqlite_time_records_df())
    if _v98_is_nonempty_df(sqlite_df):
        # V98B：這是異常自我修復路徑。若 SQLite 有資料但 authority 空，
        # 代表前一版曾經沒有寫入 GitHub 權威檔；此時必須立即寫回並上傳，
        # 否則 Streamlit Cloud 下一次 Reboot 還是會再次消失。
        _v98_save_0102_authority_df(sqlite_df, reason=reason, github=True)
        return _v98_sort_records(sqlite_df, descending=True)
    return pd.DataFrame()


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    df = _v98_authority_or_sqlite_df("01_time_records", reason="today_records_v98_sqlite_fallback")
    if not _v98_is_nonempty_df(df):
        return pd.DataFrame()
    out = df.copy()
    unfinished = _v84_is_unfinished_df(out) if "_v84_is_unfinished_df" in globals() else pd.Series([True] * len(out), index=out.index)
    if unfinished_only:
        out = out.loc[unfinished].copy()
    else:
        try:
            cycle_start = _business_cycle_start_date()
        except Exception:
            cycle_start = today_text()
        if "start_date" in out.columns:
            current_cycle = out["start_date"].astype(str) >= str(cycle_start)
            out = out.loc[current_cycle | unfinished].copy()
    return _v98_sort_records(out, descending=True)


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v98_authority_or_sqlite_df("02_history", reason="load_records_v98_sqlite_fallback")
    if not _v98_is_nonempty_df(df):
        return pd.DataFrame()
    out = df.copy()
    if start_date and "start_date" in out.columns:
        out = out[out["start_date"].astype(str) >= str(start_date)]
    if end_date and "start_date" in out.columns:
        out = out[out["start_date"].astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str) == str(work_order)]
    return _v98_sort_records(out, descending=True)


def _v98_rows_by_ids(ids) -> pd.DataFrame:
    try:
        if "_v96_query_rows_by_ids" in globals():
            return _v96_query_rows_by_ids(ids)
    except Exception:
        pass
    clean = []
    for x in ids or []:
        try:
            i = int(float(str(x).strip()))
            if i > 0 and i not in clean:
                clean.append(i)
        except Exception:
            continue
    if not clean:
        return pd.DataFrame()
    try:
        ph = ",".join(["?"] * len(clean))
        return query_df(f"SELECT * FROM time_records WHERE id IN ({ph}) ORDER BY id", clean)
    except Exception:
        return pd.DataFrame()


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    rid = int(_v98_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    if rid:
        try:
            row = _v98_rows_by_ids([rid])
            if _v98_is_nonempty_df(row):
                if "record_key" in row.columns:
                    _v97_clear_reused_id_tombstone(rid, str(row.iloc[0].get("record_key") or "")) if "_v97_clear_reused_id_tombstone" in globals() else None
                # V98：先本機 upsert，再強制上傳 GitHub，避免 Reboot App 後 01/02 空白。
                try:
                    if "_v96_upsert_rows_to_authority" in globals():
                        _v96_upsert_rows_to_authority(row, "start_work_v98_write_through_upsert", github=False)
                except Exception:
                    pass
                _v98_force_upload_time_authority("start_work_v98_write_through")
            else:
                _v98_sync_0102_from_sqlite("start_work_v98_full_repair", github=True)
        except Exception as exc:
            try:
                write_log("V98_START_WRITE_THROUGH_ERROR", f"01 開始作業後權威檔/GitHub 同步失敗：{exc}", "time_records", rid, level="ERROR")
            except Exception:
                pass
        try:
            clear_today_records_fast_cache()
        except Exception:
            pass
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    n = int(_v98_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        _v98_sync_0102_from_sqlite("finish_work_v98_write_through", github=True)
    return n


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    n = int(_v98_prev_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps) or 0)
    if n:
        _v98_sync_0102_from_sqlite("save_time_records_v98_write_through", github=True)
    return n


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    n = int(_v98_prev_recalculate_time_records(record_ids) or 0)
    if n:
        _v98_sync_0102_from_sqlite("recalculate_time_records_v98_write_through", github=True)
    return n


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    n = int(_v98_prev_delete_time_records(record_ids, reason=reason) or 0)
    # 刪除後即使 DB/authority 變空，也要把空權威檔上傳，避免 Reboot 復活。
    _v98_sync_0102_from_sqlite("delete_time_records_v98_write_through", github=True)
    return n


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    if callable(_v98_prev_import_time_records):
        result = _v98_prev_import_time_records(df, recalc=recalc, source=source)
    else:
        result = {"inserted": 0, "updated": 0}
    try:
        changed = int(result.get("inserted", 0) or 0) + int(result.get("updated", 0) or 0)
    except Exception:
        changed = 0
    if changed:
        _v98_sync_0102_from_sqlite("import_time_records_v98_write_through", github=True)
    return result


def sync_time_records_01_02_now(reason: str = "v98_manual_sync", *, github: bool = True) -> int:  # type: ignore[override]
    return _v98_sync_0102_from_sqlite(reason, github=github)
# ======================= END V98 01/02 TRUE WRITE-THROUGH + DISPLAY SELF-REPAIR =======================


# ======================= V104 01 ACTIVE WORK AUTHORITY/SQLITE ALIGNMENT FIX =======================
# 修正重點：
# 1) 今日工時紀錄 / Today Records 讀 01_time_records 權威檔，但結束目前作業 / Finish Work 舊版只讀 SQLite。
#    Streamlit Cloud Reboot 或 SQLite cache 尚未回填時，會出現「今日有紀錄，但 Finish Work 說沒有未結束作業」。
# 2) V104 將 get_active_record / get_active_records / get_active_group 先讀 SQLite；若沒有，再用 01/02 權威檔自動回填 SQLite cache。
# 3) finish_work 前若 SQLite 找不到該筆 id，會先以權威檔完整回填 cache，再執行原 finish_work 流程，避免 01/02 狀態不同步。
# 4) 不改 01 頁 UI、不改 10/11 權限與登入紀錄，避免覆蓋 V101~V103 修正。

_v104_prev_get_active_records = get_active_records
_v104_prev_get_active_record = get_active_record
_v104_prev_get_active_group = get_active_group
_v104_prev_get_active_same_work = get_active_same_work
_v104_prev_get_conflicting_active_records = get_conflicting_active_records
_v104_prev_finish_work = finish_work


def _v104_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    s = str(value).strip()
    return s == "" or s.lower() in {"none", "nan", "nat", "null", "<na>"}


def _v104_clean_sql_value(value):
    if _v104_blank(value):
        return None
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    try:
        if hasattr(value, "item"):
            value = value.item()
    except Exception:
        pass
    return value


def _v104_time_record_columns() -> list[str]:
    return [
        "id", "record_key", "status", "work_order", "part_no", "type_name", "process_name",
        "employee_id", "employee_name", "start_action", "start_timestamp", "end_action", "end_timestamp",
        "remark", "start_date", "start_time", "end_date", "end_time", "work_hours", "assembly_location",
        "group_key", "is_group_work", "source", "created_at", "updated_at",
    ]


def _v104_to_int(value):
    if _v104_blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _v104_authority_df_for_active() -> pd.DataFrame:
    # 先讀正式 01_time_records；若舊資料只在 02_history，才讀 02_history。
    frames = []
    try:
        if "_v98_authority_df" in globals():
            df1 = _v98_authority_df("01_time_records")
            if isinstance(df1, pd.DataFrame) and not df1.empty:
                frames.append(df1)
            df2 = _v98_authority_df("02_history")
            if isinstance(df2, pd.DataFrame) and not df2.empty:
                frames.append(df2)
    except Exception:
        pass
    if not frames:
        try:
            from services.permanent_authority_service import df_from_table as _pa_df
            for module_key in ("01_time_records", "02_history"):
                df = _pa_df(module_key, "time_records")
                if isinstance(df, pd.DataFrame) and not df.empty:
                    frames.append(df)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    try:
        out = pd.concat(frames, ignore_index=True)
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
        # 以 record_key 優先去重，沒有 record_key 才以 id 去重。
        if "record_key" in out.columns:
            rk = out["record_key"].astype(str).str.strip()
            has_rk = rk.ne("") & rk.str.lower().ne("nan")
            a = out.loc[has_rk].drop_duplicates(subset=["record_key"], keep="last")
            b = out.loc[~has_rk]
            if "id" in b.columns:
                b = b.drop_duplicates(subset=["id"], keep="last")
            out = pd.concat([a, b], ignore_index=True)
        elif "id" in out.columns:
            out = out.drop_duplicates(subset=["id"], keep="last")
        return _v98_sort_records(_v98_filter_deleted(out), descending=False) if "_v98_sort_records" in globals() else out.reset_index(drop=True)
    except Exception:
        return frames[0]


def _v104_unfinished_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.Series([], dtype=bool)
    if "end_timestamp" in df.columns:
        mask = df["end_timestamp"].map(_v104_blank)
    else:
        mask = pd.Series([True] * len(df), index=df.index)
    # 狀態若明確是結束類，視為非作業中；避免舊髒資料 end_timestamp 空但 status 已結束。
    if "status" in df.columns:
        ended = df["status"].astype(str).str.strip().isin(["下班", "暫停", "完工", "已結束", "結束"])
        mask = mask & (~ended)
    return mask


def _v104_filter_active_authority(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    df = _v104_authority_df_for_active()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.loc[_v104_unfinished_mask(df)].copy()
    if out.empty:
        return out
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str).str.strip() == str(employee_id).strip()]
    if employee_name and "employee_name" in out.columns:
        out = out[out["employee_name"].astype(str).str.strip() == str(employee_name).strip()]
    if process_name and "process_name" in out.columns:
        out = out[out["process_name"].astype(str).str.strip() == str(process_name).strip()]
    if start_date and "start_date" in out.columns:
        out = out[out["start_date"].astype(str).str.strip() == str(start_date).strip()]
    return _v98_sort_records(out, descending=False) if "_v98_sort_records" in globals() else out.reset_index(drop=True)


def _v104_sqlite_row_count() -> int:
    try:
        r = query_one("SELECT COUNT(*) AS n FROM time_records") or {}
        return int(r.get("n") or 0)
    except Exception:
        return 0


def _v104_upsert_rows_to_sqlite(df: pd.DataFrame, *, replace_all_if_empty: bool = False) -> int:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    cols = _v104_time_record_columns()
    try:
        if replace_all_if_empty and _v104_sqlite_row_count() == 0:
            execute("DELETE FROM time_records")
    except Exception:
        pass
    changed = 0
    for _, row in df.iterrows():
        rid = _v104_to_int(row.get("id")) if hasattr(row, "get") else None
        record_key = "" if _v104_blank(row.get("record_key")) else str(row.get("record_key")).strip()
        values = []
        insert_cols = []
        for c in cols:
            v = row.get(c, None) if hasattr(row, "get") else None
            if c == "id":
                if rid is None:
                    continue
                v = rid
            if c == "work_hours":
                try:
                    v = float(v) if not _v104_blank(v) else 0.0
                except Exception:
                    v = 0.0
            if c == "is_group_work":
                try:
                    v = int(float(v)) if not _v104_blank(v) else 0
                except Exception:
                    v = 0
            insert_cols.append(c)
            values.append(_v104_clean_sql_value(v))
        if not insert_cols:
            continue
        try:
            qcols = ", ".join(insert_cols)
            ph = ", ".join(["?"] * len(insert_cols))
            # SQLite 是快取；authority 為準。使用 OR REPLACE 可修復 Reboot 後空 cache 或 id cache 錯位。
            execute(f"INSERT OR REPLACE INTO time_records ({qcols}) VALUES ({ph})", tuple(values))
            changed += 1
        except Exception as exc:
            try:
                write_log("V104_SQLITE_HYDRATE_ROW_ERROR", f"回填工時 SQLite cache 失敗 id={rid} record_key={record_key}: {exc}", "time_records", rid or "", level="ERROR")
            except Exception:
                pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return changed


def _v104_hydrate_sqlite_from_authority(*, active_only: bool = False, employee_id: str | None = None, record_id: int | None = None, reason: str = "v104_hydrate") -> int:
    df = _v104_authority_df_for_active()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    if active_only:
        df = df.loc[_v104_unfinished_mask(df)].copy()
    if employee_id and "employee_id" in df.columns:
        df = df[df["employee_id"].astype(str).str.strip() == str(employee_id).strip()]
    if record_id is not None and "id" in df.columns:
        df = df[df["id"].map(_v104_to_int) == int(record_id)]
    if df.empty:
        return 0
    n = _v104_upsert_rows_to_sqlite(df, replace_all_if_empty=True)
    try:
        write_log("V104_TIME_AUTHORITY_TO_SQLITE", f"{reason}: 已由 01/02 權威檔回填 SQLite cache {n} 筆", "time_records", record_id or "", level="INFO")
    except Exception:
        pass
    return int(n)


def _v104_authority_active_to_display(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    return _v98_sort_records(df, descending=False) if "_v98_sort_records" in globals() else df.reset_index(drop=True)


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v104_prev_get_active_records(employee_id=employee_id, process_name=process_name, start_date=start_date, employee_name=employee_name)
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df
    # SQLite 沒有，但 Today Records/authority 有未結束資料時，立即回填 cache。
    auth_active = _v104_filter_active_authority(employee_id=employee_id, process_name=process_name, start_date=start_date, employee_name=employee_name)
    if auth_active is None or auth_active.empty:
        return pd.DataFrame()
    _v104_hydrate_sqlite_from_authority(active_only=False, reason="get_active_records_v104_cache_repair")
    df2 = _v104_prev_get_active_records(employee_id=employee_id, process_name=process_name, start_date=start_date, employee_name=employee_name)
    if isinstance(df2, pd.DataFrame) and not df2.empty:
        return df2
    return _v104_authority_active_to_display(auth_active)


def get_active_record(employee_id: str) -> dict | None:  # type: ignore[override]
    rec = _v104_prev_get_active_record(employee_id)
    if rec:
        return rec
    auth_active = _v104_filter_active_authority(employee_id=employee_id)
    if auth_active is None or auth_active.empty:
        return None
    _v104_hydrate_sqlite_from_authority(active_only=False, reason="get_active_record_v104_cache_repair")
    rec2 = _v104_prev_get_active_record(employee_id)
    if rec2:
        return rec2
    try:
        row = auth_active.sort_values("id", ascending=False, kind="stable").iloc[0].where(pd.notna(auth_active.iloc[0]), None).to_dict() if "id" in auth_active.columns else auth_active.iloc[-1].where(pd.notna(auth_active.iloc[-1]), None).to_dict()
        return row
    except Exception:
        return None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        return pd.DataFrame()
    df = _v104_prev_get_active_group(rid)
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df
    _v104_hydrate_sqlite_from_authority(active_only=False, record_id=rid, reason="get_active_group_v104_cache_repair")
    df2 = _v104_prev_get_active_group(rid)
    if isinstance(df2, pd.DataFrame) and not df2.empty:
        return df2
    auth_all = _v104_authority_df_for_active()
    if auth_all is None or auth_all.empty or "id" not in auth_all.columns:
        return pd.DataFrame()
    recs = auth_all[auth_all["id"].map(_v104_to_int) == rid]
    if recs.empty:
        return pd.DataFrame()
    rec = recs.iloc[0]
    return _v104_filter_active_authority(
        employee_id=str(rec.get("employee_id") or "").strip(),
        employee_name=str(rec.get("employee_name") or "").strip(),
        process_name=str(rec.get("process_name") or "").strip(),
        start_date=str(rec.get("start_date") or "").strip(),
    )


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    rec = _v104_prev_get_active_same_work(employee_id, work_order, process_name, start_date=start_date, employee_name=employee_name)
    if rec:
        return rec
    auth = _v104_filter_active_authority(employee_id=employee_id, process_name=process_name, start_date=start_date or today_text(), employee_name=employee_name)
    if auth is None or auth.empty or "work_order" not in auth.columns:
        return None
    auth = auth[auth["work_order"].astype(str).str.strip() == str(work_order).strip()]
    if auth.empty:
        return None
    _v104_hydrate_sqlite_from_authority(active_only=False, reason="get_active_same_work_v104_cache_repair")
    return auth.iloc[-1].where(pd.notna(auth.iloc[-1]), None).to_dict()


def get_conflicting_active_records(employee_id: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v104_prev_get_conflicting_active_records(employee_id, process_name, start_date=start_date, employee_name=employee_name)
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df
    start_date = start_date or today_text()
    active = _v104_filter_active_authority(employee_id=employee_id, employee_name=employee_name)
    if active is None or active.empty:
        return pd.DataFrame()
    out = active[(active["process_name"].astype(str) != str(process_name)) | (active["start_date"].astype(str) != str(start_date))].copy()
    if not out.empty:
        _v104_hydrate_sqlite_from_authority(active_only=False, reason="get_conflicting_active_records_v104_cache_repair")
    return out


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        raise ValueError("工時紀錄編號異常，請重新整理頁面後再操作。")
    rec = query_one("SELECT * FROM time_records WHERE id=?", (rid,))
    if not rec:
        # 若 Finish Work 由 authority 顯示出的 active record 觸發，但 SQLite cache 空，先完整回填。
        _v104_hydrate_sqlite_from_authority(active_only=False, reason="finish_work_v104_pre_hydrate")
    n = int(_v104_prev_finish_work(rid, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        try:
            # 補做一次 01/02 權威檔一致化，確保結束後 Today Records 與 02 History 同步。
            if "_v98_sync_0102_from_sqlite" in globals():
                _v98_sync_0102_from_sqlite("finish_work_v104_authority_alignment", github=True)
        except Exception as exc:
            try:
                write_log("V104_FINISH_AUTHORITY_SYNC_ERROR", f"Finish Work 後 01/02 權威檔同步失敗：{exc}", "time_records", rid, level="ERROR")
            except Exception:
                pass
    return n


def repair_time_record_active_cache_now(reason: str = "manual_v104_active_cache_repair") -> int:
    """手動/測試用：將 01/02 權威檔目前所有工時紀錄回填到 SQLite cache。"""
    return _v104_hydrate_sqlite_from_authority(active_only=False, reason=reason)

# ===================== END V104 01 ACTIVE WORK AUTHORITY/SQLITE ALIGNMENT FIX =====================


# ===================== V108 01 START/FINISH FAST ASYNC AUTHORITY UPLOAD =====================
# 修正目的：
# 1) V98 為了避免 Streamlit Cloud Reboot 後資料消失，在 01 開始/結束時同步 force upload GitHub。
#    GitHub Contents API 偶發延遲時，會讓「開始作業」卡 1~2 分鐘。
# 2) V108 改為「本機 canonical 權威檔立即寫入 + GitHub 背景合併上傳」。
#    使用者按開始作業後先進入下一步，背景執行 01_time_records / 02_history 上傳。
# 3) 不改 01 頁 UI、不改 10/11 權限/登入、不改刪除 tombstone、不改 01/02 同步規則。
# 4) 管理員儲存/刪除/重算仍保留原先同步權威邏輯；本段只覆蓋高頻的 start_work / finish_work。

try:
    _v108_core_start_work = _v98_prev_start_work  # V97/V96 core: SQL insert + local authority upsert, no V98 force upload.
except Exception:  # pragma: no cover
    _v108_core_start_work = None

try:
    _v108_core_finish_work = _v98_prev_finish_work  # V96/V90 core: SQL finish + local authority upsert, no V98 force upload.
except Exception:  # pragma: no cover
    _v108_core_finish_work = None

_v108_upload_state = {
    "running": False,
    "pending": False,
    "reason": "",
    "last_start": 0.0,
    "last_finish": 0.0,
    "last_error": "",
}


def _v108_log(level: str, message: str, record_id: int | str | None = None) -> None:
    try:
        write_log("V108_TIME_AUTH_ASYNC", message, "time_records", record_id or "", level=level)
    except Exception:
        pass


def _v108_schedule_time_authority_upload(reason: str = "v108_async_time_authority_upload", *, delay_sec: float = 0.35) -> None:
    """Coalesced background GitHub upload for 01/02 canonical authority files.

    The local authority files are already updated before this function is called.
    This function only publishes the latest local files to GitHub in a daemon thread
    so high-frequency shop-floor actions do not wait for network round trips.
    """
    try:
        import threading as _threading
        import time as _time
    except Exception:
        return

    def _worker() -> None:
        # Small delay allows multiple rapid start/finish actions to collapse into one GitHub publish.
        try:
            _time.sleep(max(float(delay_sec or 0), 0.0))
        except Exception:
            pass
        while True:
            reason_now = ""
            try:
                reason_now = str(_v108_upload_state.get("reason") or reason or "v108_async_time_authority_upload")
                _v108_upload_state["pending"] = False
            except Exception:
                reason_now = reason
            try:
                if "_v98_force_upload_time_authority" in globals():
                    _v98_force_upload_time_authority(reason_now)
                elif "_v98_sync_0102_from_sqlite" in globals():
                    _v98_sync_0102_from_sqlite(reason_now, github=True)
                _v108_upload_state["last_finish"] = _time.time()
                _v108_upload_state["last_error"] = ""
            except Exception as exc:
                _v108_upload_state["last_error"] = str(exc)[:500]
                _v108_log("ERROR", f"背景上傳 01/02 權威檔失敗：{exc}")
            try:
                if not bool(_v108_upload_state.get("pending")):
                    _v108_upload_state["running"] = False
                    return
                # Another action arrived while uploading; wait briefly and upload newest local files once more.
                _time.sleep(0.2)
            except Exception:
                _v108_upload_state["running"] = False
                return

    try:
        _v108_upload_state["reason"] = str(reason or "v108_async_time_authority_upload")
        _v108_upload_state["pending"] = True
        if bool(_v108_upload_state.get("running")):
            return
        _v108_upload_state["running"] = True
        _v108_upload_state["last_start"] = _time.time()
        t = _threading.Thread(target=_worker, name="SPT-V108-TimeAuthorityUpload", daemon=True)
        t.start()
    except Exception as exc:
        _v108_upload_state["running"] = False
        _v108_upload_state["last_error"] = str(exc)[:500]
        _v108_log("ERROR", f"啟動背景上傳 01/02 權威檔失敗：{exc}")


def flush_time_record_authority_upload_now(reason: str = "manual_flush_time_authority_v108") -> bool:
    """Optional diagnostic/manual helper: synchronously upload latest local 01/02 authority files."""
    try:
        if "_v98_force_upload_time_authority" in globals():
            _v98_force_upload_time_authority(reason)
            return True
    except Exception as exc:
        _v108_upload_state["last_error"] = str(exc)[:500]
        _v108_log("ERROR", f"手動同步 01/02 權威檔失敗：{exc}")
    return False


def get_time_authority_upload_status() -> dict:
    """Small status helper for diagnostics without forcing a GitHub call."""
    try:
        return dict(_v108_upload_state)
    except Exception:
        return {"running": False, "pending": False, "last_error": "status_unavailable"}


def _v108_local_upsert_started_row(rid: int) -> None:
    try:
        row = _v98_rows_by_ids([rid]) if "_v98_rows_by_ids" in globals() else pd.DataFrame()
        if isinstance(row, pd.DataFrame) and not row.empty:
            if "record_key" in row.columns and "_v97_clear_reused_id_tombstone" in globals():
                try:
                    _v97_clear_reused_id_tombstone(int(rid), str(row.iloc[0].get("record_key") or ""))
                except Exception:
                    pass
            if "_v96_upsert_rows_to_authority" in globals():
                _v96_upsert_rows_to_authority(row, "start_work_v108_fast_local_upsert", github=False)
        elif "_v98_sync_0102_from_sqlite" in globals():
            _v98_sync_0102_from_sqlite("start_work_v108_fast_local_repair", github=False)
    except Exception as exc:
        _v108_log("ERROR", f"開始作業後本機 01/02 權威檔同步失敗：{exc}", rid)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    """V108 fast path for 01 Start Work.

    Synchronous path: SQLite business insert + local canonical authority write.
    Asynchronous path: GitHub publish of latest 01/02 authority files.
    """
    core = _v108_core_start_work if callable(_v108_core_start_work) else None
    if core is None:
        # Last-resort fallback keeps app functional, but should not happen in current build.
        core = _v98_prev_start_work if callable(globals().get("_v98_prev_start_work")) else None
    if core is None:
        raise RuntimeError("start_work core implementation is unavailable")
    rid = int(core(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    if rid:
        _v108_local_upsert_started_row(rid)
        try:
            clear_today_records_fast_cache()
        except Exception:
            pass
        try:
            clear_query_cache()
        except Exception:
            pass
        _v108_schedule_time_authority_upload("start_work_v108_async_publish")
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    """V108 fast path for 01 Finish Work.

    Also avoids waiting for GitHub when ending/pause/complete/off-duty from 01.
    """
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        raise ValueError("工時紀錄編號異常，請重新整理頁面後再操作。")
    try:
        rec = query_one("SELECT * FROM time_records WHERE id=?", (rid,))
        if not rec and "_v104_hydrate_sqlite_from_authority" in globals():
            _v104_hydrate_sqlite_from_authority(active_only=False, reason="finish_work_v108_pre_hydrate")
    except Exception:
        pass
    core = _v108_core_finish_work if callable(_v108_core_finish_work) else None
    if core is None:
        core = _v98_prev_finish_work if callable(globals().get("_v98_prev_finish_work")) else None
    if core is None:
        raise RuntimeError("finish_work core implementation is unavailable")
    n = int(core(rid, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        try:
            if "_v98_sync_0102_from_sqlite" in globals():
                _v98_sync_0102_from_sqlite("finish_work_v108_fast_local_sync", github=False)
        except Exception as exc:
            _v108_log("ERROR", f"結束作業後本機 01/02 權威檔同步失敗：{exc}", rid)
        try:
            clear_today_records_fast_cache()
        except Exception:
            pass
        try:
            clear_query_cache()
        except Exception:
            pass
        _v108_schedule_time_authority_upload("finish_work_v108_async_publish")
    return n

# =================== END V108 01 START/FINISH FAST ASYNC AUTHORITY UPLOAD =====================

# ===================== V109 01/02 RECALC BIDIRECTIONAL AUTHORITY SYNC =====================
# 修正目的：
# 1) 01「重算勾選工時並同步」完成後，01_time_records 與 02_history 必須同一批資料、同一個工時計算結果。
# 2) 02「重算勾選工時」完成後，也必須同步回 01_time_records，不可只更新 02 畫面或 SQLite cache。
# 3) 重算後的最終來源改為 canonical 權威檔合併結果，不再由 SQLite 舊快取反向覆蓋剛算好的資料。
# 4) 不改 01/02 頁面 UI、不改 10 權限、不改 11 登入紀錄、不改開始作業 V108 秒級化。

_v109_prev_recalculate_time_records = recalculate_time_records


def _v109_to_int(value):
    try:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        s = str(value).strip()
        if not s or s.lower() in {"nan", "none", "null", "<na>"}:
            return None
        return int(float(s))
    except Exception:
        return None


def _v109_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "nan", "none", "null", "nat", "<na>"}


def _v109_row_key(row: dict) -> str:
    rk = str(row.get("record_key") or "").strip()
    if rk and rk.lower() not in {"nan", "none", "null"}:
        return "rk:" + rk
    rid = _v109_to_int(row.get("id") if "id" in row else row.get("ID"))
    if rid is not None:
        return "id:" + str(rid)
    try:
        # 最後防線：用業務主鍵避免無 id 的列被全部丟掉。
        return "biz:" + make_record_key(
            str(row.get("employee_id") or ""),
            str(row.get("work_order") or ""),
            str(row.get("process_name") or ""),
            str(row.get("start_timestamp") or ""),
        )
    except Exception:
        return "tmp:" + str(len(str(row))) + ":" + str(row)[:80]


def _v109_updated_score(row: dict) -> str:
    # ISO-like 字串可直接排序；缺值放前面，避免覆蓋較新的 authority。
    for c in ("updated_at", "Update Time", "最後更新", "created_at", "start_timestamp"):
        v = row.get(c)
        if not _v109_blank(v):
            return str(v)
    return ""


def _v109_df_rows(df: pd.DataFrame | None) -> list[dict]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    try:
        clean = df.copy().where(pd.notna(df), "")
        return [dict(r) for _, r in clean.iterrows()]
    except Exception:
        return []


def _v109_authority_df(module_key: str) -> pd.DataFrame:
    try:
        if "_v98_authority_df" in globals():
            df = _v98_authority_df(module_key)
            if isinstance(df, pd.DataFrame):
                return df.copy()
    except Exception:
        pass
    try:
        from services.permanent_authority_service import df_from_table as _pa_df
        df = _pa_df(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _v109_sqlite_df() -> pd.DataFrame:
    try:
        if "_v98_sqlite_time_records_df" in globals():
            df = _v98_sqlite_time_records_df()
            if isinstance(df, pd.DataFrame):
                return df.copy()
    except Exception:
        pass
    try:
        return query_df("SELECT * FROM time_records ORDER BY id")
    except Exception:
        return pd.DataFrame()


def _v109_filter_deleted(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    for fn_name in ("_v98_filter_deleted", "_v94_filter_deleted_df"):
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                out = fn(out)
        except Exception:
            pass
    return out


def _v109_merged_authority_df(record_ids: list[int] | set[int] | None = None, *, sqlite_fallback: bool = True) -> pd.DataFrame:
    """Merge 01/02 authority safely.

    Important: SQLite is cache only.  To avoid bringing back rows that were already
    deleted from authority, SQLite rows are included only when authority is empty,
    or when a selected id exists only in SQLite.
    """
    ids = {_v109_to_int(x) for x in (record_ids or [])}
    ids = {x for x in ids if x is not None}

    authority_sources: list[tuple[int, pd.DataFrame]] = [
        (10, _v109_authority_df("02_history")),
        (20, _v109_authority_df("01_time_records")),
    ]
    chosen: dict[str, tuple[str, int, dict]] = {}
    all_cols: list[str] = []

    def _add_rows(source_rank: int, df: pd.DataFrame, *, only_selected_missing: bool = False) -> None:
        existing_ids = {
            _v109_to_int(v[2].get("id"))
            for v in chosen.values()
            if _v109_to_int(v[2].get("id")) is not None
        }
        for r in _v109_df_rows(df):
            rid = _v109_to_int(r.get("id"))
            if only_selected_missing:
                if not ids or rid not in ids or rid in existing_ids:
                    continue
            for c in r.keys():
                if c not in all_cols:
                    all_cols.append(c)
            k = _v109_row_key(r)
            score = _v109_updated_score(r)
            old = chosen.get(k)
            if old is None or (score, source_rank) >= (old[0], old[1]):
                chosen[k] = (score, source_rank, r)

    for source_rank, df in authority_sources:
        _add_rows(source_rank, df)

    if sqlite_fallback:
        sqlite_df = _v109_sqlite_df()
        if not chosen:
            # First-run/authority-missing repair only.
            _add_rows(30, sqlite_df)
        elif ids:
            # For selected recalculation, use SQLite only to rescue selected rows missing from authority.
            _add_rows(30, sqlite_df, only_selected_missing=True)

    rows = []
    for _, _, r in chosen.values():
        rows.append({c: r.get(c, "") for c in all_cols})
    out = pd.DataFrame(rows, columns=all_cols) if rows else pd.DataFrame(columns=all_cols)
    out = _v109_filter_deleted(out)
    try:
        if "_v98_sort_records" in globals():
            out = _v98_sort_records(out, descending=True)
        elif "_v89_sort_records" in globals():
            out = _v89_sort_records(out)
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v109_save_0102_and_cache(df: pd.DataFrame, reason: str, *, github: bool = True) -> int:
    safe = _v109_filter_deleted(df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame())
    try:
        if "_v89_save_time_authority_df" in globals():
            n = int(_v89_save_time_authority_df(safe, reason, github=bool(github)) or 0)
        elif "_v98_save_0102_authority_df" in globals():
            n = int(_v98_save_0102_authority_df(safe, reason=reason, github=bool(github)) or 0)
        else:
            from services.permanent_authority_service import save_authority as _pa_save, table_from_df as _pa_table
            rows = _pa_table(safe)
            _pa_save("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
            _pa_save("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
            n = len(rows)
    except Exception as exc:
        try:
            write_log("V109_RECALC_AUTHORITY_SAVE_ERROR", f"V109 01/02 權威檔同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        n = 0
    try:
        if "_v89_sync_sqlite_cache_from_authority" in globals():
            _v89_sync_sqlite_cache_from_authority(safe)
    except Exception as exc:
        try:
            write_log("V109_RECALC_SQLITE_SYNC_ERROR", f"V109 SQLite cache 回寫失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(n)


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    """V109 authority-first bidirectional recalculation.

    Called by both 01 and 02 pages.  The result is saved to both:
      - data/permanent_store/modules/01_time_records/records.json
      - data/permanent_store/modules/02_history/records.json
    and then SQLite is refreshed from that same authority data.
    """
    ids = {_v109_to_int(x) for x in (record_ids or [])}
    ids = {x for x in ids if x is not None}

    auth_df = _v109_merged_authority_df(list(ids), sqlite_fallback=True)
    if auth_df is None or auth_df.empty:
        return 0
    if "id" not in auth_df.columns:
        return 0

    id_series = auth_df["id"].map(_v109_to_int)
    target_mask = id_series.isin(ids) if ids else pd.Series([True] * len(auth_df), index=auth_df.index)
    count = 0
    for idx in auth_df.loc[target_mask].index:
        row = dict(auth_df.loc[idx])
        start_ts = row.get("start_timestamp") or row.get("Start Timestamp") or row.get("開始時間")
        end_ts = row.get("end_timestamp") or row.get("End Timestamp") or row.get("結束時間")
        if _v109_blank(start_ts) or _v109_blank(end_ts):
            continue
        try:
            normalized = normalize_record_datetime_fields(row, recalc_work_hours=True)
        except Exception:
            normalized = {}
        if not normalized:
            continue
        for c, v in normalized.items():
            if c not in auth_df.columns:
                auth_df[c] = ""
            auth_df.at[idx, c] = v
        if "status" not in auth_df.columns:
            auth_df["status"] = ""
        status_now = str(auth_df.at[idx, "status"] or "").strip()
        if not status_now or status_now == "作業中":
            auth_df.at[idx, "status"] = row.get("end_action") or "已結束"
        if "updated_at" not in auth_df.columns:
            auth_df["updated_at"] = ""
        try:
            auth_df.at[idx, "updated_at"] = _now()
        except Exception:
            auth_df.at[idx, "updated_at"] = now_text() if "now_text" in globals() else ""
        count += 1

    if count:
        _v109_save_0102_and_cache(auth_df, "recalculate_time_records_v109_bidirectional_authority", github=True)
        try:
            write_log(
                "RECALC_TIME_RECORDS_0102_SYNC",
                f"V109：已重算 {count} 筆，並將同一批權威資料同步寫入 01 工時紀錄與 02 歷史紀錄。",
                "time_records",
            )
        except Exception:
            pass
    return int(count)


def sync_time_records_01_02_now(reason: str = "v109_manual_0102_authority_sync", *, github: bool = True) -> int:  # type: ignore[override]
    """Manual helper: merge 01/02/SQLite, then save the same authority set to both modules."""
    df = _v109_merged_authority_df(None, sqlite_fallback=True)
    if df is None:
        df = pd.DataFrame()
    return _v109_save_0102_and_cache(df, reason, github=bool(github))

# =================== END V109 01/02 RECALC BIDIRECTIONAL AUTHORITY SYNC =====================

# ===================== V122 FINISH WORK SAME-PERSON HARD GUARD =====================
# 目的：多人同時使用時，任一人按「結束目前作業」只能結束同一工號、姓名、工段、日期的同步群組；
# 舊資料若工號/姓名空白，不可擴大成全體未結束作業。

def _v122_finish_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}

try:
    _v122_prev_get_active_group = get_active_group
except Exception:
    _v122_prev_get_active_group = None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        return pd.DataFrame()
    rec = query_one("SELECT * FROM time_records WHERE id=?", (rid,))
    if not rec:
        return pd.DataFrame()
    emp_id = str(rec.get("employee_id") or "").strip()
    emp_name = str(rec.get("employee_name") or "").strip()
    process = str(rec.get("process_name") or "").strip()
    start_date = str(rec.get("start_date") or "").strip()
    # 防呆：缺少人員關鍵欄時，只允許結束目前單筆。
    if _v122_finish_blank(emp_id) or _v122_finish_blank(emp_name) or _v122_finish_blank(process) or _v122_finish_blank(start_date):
        return pd.DataFrame([rec])
    try:
        df = _v122_prev_get_active_group(rid) if callable(_v122_prev_get_active_group) else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        df = get_active_records(employee_id=emp_id, employee_name=emp_name, process_name=process, start_date=start_date)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame([rec])
    out = df.copy()
    for col in ["employee_id", "employee_name", "process_name", "start_date"]:
        if col not in out.columns:
            out[col] = ""
    mask = (
        out["employee_id"].astype(str).str.strip().eq(emp_id)
        & out["employee_name"].astype(str).str.strip().eq(emp_name)
        & out["process_name"].astype(str).str.strip().eq(process)
        & out["start_date"].astype(str).str.strip().eq(start_date)
    )
    if "end_timestamp" in out.columns:
        mask = mask & out["end_timestamp"].map(_v122_finish_blank)
    out = out.loc[mask].copy()
    if out.empty:
        return pd.DataFrame([rec])
    return out

# =================== END V122 FINISH WORK SAME-PERSON HARD GUARD ===================

# ===================== V123 MULTI-USER RECORD OPERATION LOCK =====================
# 目的：多人同時開始/結束作業時，同一人員同一時間的操作加鎖；不同人員不互相阻塞。
# 這只包住最終 start_work / finish_work，不改原本計算、同步、權威檔與按鈕流程。
import threading as _v123_time_threading

_V123_TIME_LOCKS: dict[str, _v123_time_threading.RLock] = {}
_V123_TIME_LOCK_GUARD = _v123_time_threading.RLock()


def _v123_time_lock(key: str) -> _v123_time_threading.RLock:
    key = str(key or "global")
    with _V123_TIME_LOCK_GUARD:
        lock = _V123_TIME_LOCKS.get(key)
        if lock is None:
            lock = _v123_time_threading.RLock()
            _V123_TIME_LOCKS[key] = lock
        return lock


def _v123_clean_key_part(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _v123_start_lock_key(employee: dict, process_name: str) -> str:
    emp_id = _v123_clean_key_part((employee or {}).get("employee_id") or (employee or {}).get("工號") or (employee or {}).get("id"))
    emp_name = _v123_clean_key_part((employee or {}).get("employee_name") or (employee or {}).get("name") or (employee or {}).get("姓名"))
    proc = _v123_clean_key_part(process_name)
    if emp_id or emp_name:
        return f"employee:{emp_id}|{emp_name}|{proc}"
    return "employee:unknown"


def _v123_finish_lock_key(record_id: int) -> str:
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        return f"record:{record_id}"
    rec = None
    try:
        rec = query_one("SELECT * FROM time_records WHERE id=?", (rid,))
    except Exception:
        rec = None
    if not rec:
        return f"record:{rid}"
    emp_id = _v123_clean_key_part(rec.get("employee_id"))
    emp_name = _v123_clean_key_part(rec.get("employee_name"))
    proc = _v123_clean_key_part(rec.get("process_name"))
    start_date = _v123_clean_key_part(rec.get("start_date"))
    if emp_id or emp_name:
        return f"finish:{emp_id}|{emp_name}|{proc}|{start_date}"
    return f"record:{rid}"


try:
    _v123_prev_start_work = start_work
except Exception:  # pragma: no cover
    _v123_prev_start_work = None


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if not callable(_v123_prev_start_work):
        raise RuntimeError("start_work core implementation is unavailable")
    key = _v123_start_lock_key(employee or {}, process_name)
    with _v123_time_lock(key):
        return int(_v123_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)


try:
    _v123_prev_finish_work = finish_work
except Exception:  # pragma: no cover
    _v123_prev_finish_work = None


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v123_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    key = _v123_finish_lock_key(record_id)
    with _v123_time_lock(key):
        return int(_v123_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)

# =================== END V123 MULTI-USER RECORD OPERATION LOCK ===================

# ===================== V133 01 ACTIVE REFRESH + LOGOUT FLUSH HELPERS =====================
# 目的：
# 1) 進入 01 工時紀錄時，若 SQLite/query cache 尚未帶出本人未結束作業，從 01/02 本機權威檔輕量回補，避免必須切換模組才看得到。
# 2) 登出前可由 security_service 呼叫 flush_time_record_authority_upload_now，將 V108 背景佇列盡量補送 GitHub，降低網路慢造成登出後資料未發布的風險。

def refresh_active_records_for_employee(employee_id: str | None = None, employee_name: str | None = None, *, reason: str = "v133_01_active_refresh") -> int:
    """Lightweight cache repair for 01 Active Work display.

    This function does not change business records. It only repairs SQLite/query cache
    from existing local 01/02 canonical files when the runtime cache is stale.
    """
    emp_id = str(employee_id or "").strip()
    emp_name = str(employee_name or "").strip()
    try:
        clear_query_cache()
    except Exception:
        pass

    def _sql_active_count() -> int:
        try:
            base_get = globals().get("_v104_prev_get_active_records")
            if callable(base_get):
                df = base_get(employee_id=emp_id or None, employee_name=emp_name or None)
            else:
                params = []
                sql = "SELECT COUNT(*) AS c FROM time_records WHERE end_timestamp IS NULL"
                if emp_id:
                    sql += " AND employee_id=?"
                    params.append(emp_id)
                if emp_name:
                    sql += " AND COALESCE(employee_name,'')=?"
                    params.append(emp_name)
                row = query_one(sql, tuple(params))
                return int((row or {}).get("c", 0) or 0)
            return int(len(df)) if isinstance(df, pd.DataFrame) else 0
        except Exception:
            return 0

    before = _sql_active_count()
    if before > 0:
        return before
    try:
        hydrator = globals().get("_v104_hydrate_sqlite_from_authority")
        if callable(hydrator):
            hydrator(active_only=False, employee_id=emp_id or None, reason=reason)
    except TypeError:
        try:
            globals().get("_v104_hydrate_sqlite_from_authority")(active_only=False, reason=reason)
        except Exception:
            pass
    except Exception as exc:
        try:
            write_log("V133_ACTIVE_REFRESH_ERROR", f"01 Active Work 快取回補失敗：{exc}", "time_records", emp_id, level="ERROR")
        except Exception:
            pass
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return _sql_active_count()

try:
    _v133_prev_flush_time_record_authority_upload_now = flush_time_record_authority_upload_now  # type: ignore[name-defined]
except Exception:
    _v133_prev_flush_time_record_authority_upload_now = None


def flush_time_record_authority_upload_now(reason: str = "v133_logout_flush_time_authority") -> bool:  # type: ignore[override]
    """Best-effort synchronous publish before logout / diagnostics.

    It keeps V108 fast Start/Finish unchanged. Only callers that explicitly request
    a flush, such as logout, may wait for the GitHub write-through.
    """
    ok = False
    try:
        if callable(_v133_prev_flush_time_record_authority_upload_now):
            ok = bool(_v133_prev_flush_time_record_authority_upload_now(reason))
    except Exception as exc:
        try:
            write_log("V133_TIME_AUTH_FLUSH_ERROR", f"登出前 01/02 權威檔補送失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    if not ok:
        try:
            if "sync_time_records_01_02_now" in globals():
                sync_time_records_01_02_now(reason, github=True)
                ok = True
        except Exception as exc:
            try:
                write_log("V133_TIME_AUTH_FLUSH_ERROR", f"登出前 01/02 權威檔同步失敗：{exc}", "time_records", level="ERROR")
            except Exception:
                pass
    return bool(ok)

# =================== END V133 01 ACTIVE REFRESH + LOGOUT FLUSH HELPERS ===================

# ===================== V134 LOG INSERT MISSING 01/02 CANONICAL REPAIR =====================
# 修正目的：
# 1) 已確認會出現：system_logs / SQLite 有 INSERT time_records 與 START_WORK，
#    但 01_time_records / 02_history canonical 權威檔沒有同步新增 row，導致 01、02 畫面看不到。
# 2) 原因是 01/02 顯示層以 canonical 權威檔為準；若 start_work 在 SQLite INSERT 後，
#    GitHub/authority upsert 被背景上傳、tombstone、快取或例外中斷，LOG 仍會有紀錄，畫面卻讀不到。
# 3) V134 在 start_work / finish_work / today_records / load_records 加最後保險：
#    只把 SQLite 中「本次新增 id」或「仍在作業中的 missing row」合併回 01/02 canonical。
# 4) 不做全量舊資料復活；仍套用 tombstone 過濾，避免 02 已刪除資料被 SQLite 舊快取救回。
# 5) 一般開始/結束作業仍不等待 GitHub；先本機 canonical 可見，再沿用 V108 背景上傳。

try:
    _v134_prev_start_work = start_work
except Exception:  # pragma: no cover
    _v134_prev_start_work = None
try:
    _v134_prev_finish_work = finish_work
except Exception:  # pragma: no cover
    _v134_prev_finish_work = None
try:
    _v134_prev_today_records = today_records
except Exception:  # pragma: no cover
    _v134_prev_today_records = None
try:
    _v134_prev_load_records = load_records
except Exception:  # pragma: no cover
    _v134_prev_load_records = None

_V134_LAST_DISPLAY_REPAIR_AT = 0.0
_V134_DISPLAY_REPAIR_TTL_SEC = 2.0


def _v134_now_seconds() -> float:
    try:
        import time as _time
        return float(_time.time())
    except Exception:
        return 0.0


def _v134_is_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v134_to_int(value):
    if _v134_is_blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _v134_row_identity(row: dict) -> str:
    rk = str(row.get("record_key") or row.get("紀錄鍵 / Record Key") or "").strip()
    if rk and rk.lower() not in {"none", "nan", "null", "<na>"}:
        return "rk:" + rk
    rid = _v134_to_int(row.get("id") if "id" in row else row.get("ID"))
    if rid is not None:
        return "id:" + str(rid)
    return "tmp:" + str(row)[:160]


def _v134_read_sqlite_time_records(record_ids: list[int] | None = None) -> pd.DataFrame:
    """Direct SQLite read, bypassing query cache/wrappers.

    V134 uses this only as a repair source when canonical missed a newly inserted row.
    """
    try:
        from services.db_service import ensure_database as _ensure_database  # type: ignore
        _ensure_database()
    except Exception:
        pass
    try:
        ids: list[int] = []
        for x in record_ids or []:
            rid = _v134_to_int(x)
            if rid is not None and rid not in ids:
                ids.append(int(rid))
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=8) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
            if ids:
                ph = ",".join(["?"] * len(ids))
                rows = conn.execute(f"SELECT * FROM time_records WHERE id IN ({ph}) ORDER BY id", tuple(ids)).fetchall()
            else:
                # Display repair only needs not-ended rows; avoids resurrecting old deleted history rows.
                rows = conn.execute(
                    """
                    SELECT * FROM time_records
                    WHERE (
                        COALESCE(status,'')='作業中'
                        OR end_timestamp IS NULL
                        OR TRIM(COALESCE(end_timestamp,''))=''
                        OR LOWER(TRIM(COALESCE(end_timestamp,''))) IN ('none','nan','nat')
                    )
                    ORDER BY id
                    """
                ).fetchall()
            return pd.DataFrame([dict(r) for r in rows])
    except Exception as exc:
        try:
            write_log("V134_SQLITE_REPAIR_READ_ERROR", f"V134 直接讀取 SQLite time_records 失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return pd.DataFrame()


def _v134_authority_df(module_key: str = "02_history") -> pd.DataFrame:
    try:
        if "_v98_authority_df" in globals():
            df = _v98_authority_df(module_key)
            if isinstance(df, pd.DataFrame):
                return df.copy()
    except Exception:
        pass
    try:
        from services.permanent_authority_service import df_from_table as _pa_df_from_table
        df = _pa_df_from_table(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return df.copy()
    except Exception:
        pass
    return pd.DataFrame()


def _v134_filter_deleted(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    for fn_name in ("_v97_filter_deleted_df", "_v98_filter_deleted", "_v94_filter_deleted_df", "_v96_filter_tombstone"):
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                out = fn(out)
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v134_df_to_rows(df: pd.DataFrame) -> list[dict]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    try:
        clean = df.copy().where(pd.notna(df), "")
        return [dict(r) for _, r in clean.iterrows()]
    except Exception:
        return []


def _v134_merge_rows(base_df: pd.DataFrame, incoming_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    base = base_df.copy() if isinstance(base_df, pd.DataFrame) else pd.DataFrame()
    incoming = incoming_df.copy() if isinstance(incoming_df, pd.DataFrame) else pd.DataFrame()
    if incoming.empty:
        return base.reset_index(drop=True), 0
    base = base.loc[:, ~pd.Index(base.columns).duplicated()].copy() if not base.empty else pd.DataFrame()
    incoming = incoming.loc[:, ~pd.Index(incoming.columns).duplicated()].copy()

    all_cols: list[str] = []
    for c in list(base.columns) + list(incoming.columns):
        sc = str(c)
        if sc not in all_cols:
            all_cols.append(sc)
    if "id" not in all_cols:
        all_cols.insert(0, "id")

    if base.empty:
        base = pd.DataFrame(columns=all_cols)
    for c in all_cols:
        if c not in base.columns:
            base[c] = ""
        if c not in incoming.columns:
            incoming[c] = ""
    base = base[all_cols].copy()
    incoming = incoming[all_cols].copy()

    key_to_idx: dict[str, int] = {}
    for idx, r in base.iterrows():
        key_to_idx[_v134_row_identity(dict(r))] = idx

    changed = 0
    for _, r in incoming.iterrows():
        row_dict = dict(r)
        key = _v134_row_identity(row_dict)
        if key in key_to_idx:
            idx = key_to_idx[key]
            row_changed = False
            for c, v in row_dict.items():
                old_v = base.at[idx, c] if c in base.columns else ""
                if str(old_v) != str(v):
                    base.at[idx, c] = v
                    row_changed = True
            if row_changed:
                changed += 1
        else:
            base = pd.concat([base, pd.DataFrame([row_dict])], ignore_index=True)
            key_to_idx[key] = int(base.index[-1])
            changed += 1
    try:
        if "id" in base.columns:
            base["_v134_sort_id"] = pd.to_numeric(base["id"], errors="coerce")
            base = base.sort_values("_v134_sort_id", ascending=True, kind="stable").drop(columns=["_v134_sort_id"], errors="ignore")
    except Exception:
        pass
    return base.reset_index(drop=True), int(changed)


def _v134_save_0102_authority(df: pd.DataFrame, reason: str, *, github: bool = False) -> int:
    safe = _v134_filter_deleted(df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame())
    try:
        if "_v98_save_0102_authority_df" in globals():
            return int(_v98_save_0102_authority_df(safe, reason=reason, github=bool(github)) or 0)
        if "_v89_save_time_authority_df" in globals():
            return int(_v89_save_time_authority_df(safe, reason, github=bool(github)) or 0)
        from services.permanent_authority_service import save_authority as _pa_save_authority, table_from_df as _pa_table_from_df
        rows = _pa_table_from_df(safe)
        _pa_save_authority("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
        _pa_save_authority("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
        return int(len(rows))
    except Exception as exc:
        try:
            write_log("V134_AUTHORITY_SAVE_ERROR", f"V134 01/02 權威檔寫入失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return 0


def _v134_publish_async(reason: str) -> None:
    # 不阻塞 01 開始作業；沿用 V108 背景上傳機制。
    try:
        scheduler = globals().get("_v108_schedule_time_authority_upload")
        if callable(scheduler):
            scheduler(reason)
            return
    except Exception:
        pass


def repair_missing_time_records_from_sqlite(record_ids: list[int] | None = None, *, reason: str = "v134_repair_missing_time_records", github: bool = False) -> int:
    """Repair rows that exist in SQLite but are missing from 01/02 canonical authority.

    This is intentionally narrow:
    - record_ids provided: repair those exact ids after start/finish.
    - record_ids not provided: repair only currently-unfinished rows.
    - all candidates pass tombstone filtering so deleted 02 rows are not revived.
    """
    sqlite_df = _v134_filter_deleted(_v134_read_sqlite_time_records(record_ids))
    if sqlite_df is None or sqlite_df.empty:
        return 0

    auth_02 = _v134_filter_deleted(_v134_authority_df("02_history"))
    auth_01 = _v134_filter_deleted(_v134_authority_df("01_time_records"))
    # Use the richer current authority as base.
    if len(auth_02) >= len(auth_01):
        base = auth_02
    else:
        base = auth_01

    merged, changed = _v134_merge_rows(base, sqlite_df)
    if changed <= 0:
        return 0
    saved = _v134_save_0102_authority(merged, reason, github=bool(github))
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        write_log(
            "V134_REPAIR_TIME_RECORD_CANONICAL",
            f"V134 已將 SQLite 中 missing time_records 補回 01/02 canonical；修復 {changed} 筆，同步後 {saved} 筆。",
            "time_records",
            ",".join(str(x) for x in (record_ids or [])),
            level="WARN",
        )
    except Exception:
        pass
    if not github:
        _v134_publish_async(reason + "_async_publish")
    return int(changed)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if not callable(_v134_prev_start_work):
        raise RuntimeError("start_work core implementation is unavailable")
    rid = int(_v134_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    if rid:
        # 核心修正：LOG/SQLite 已 INSERT 後，立即確認 01/02 canonical 有同一筆 id。
        repair_missing_time_records_from_sqlite([rid], reason="start_work_v134_sqlite_to_0102_canonical", github=False)
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v134_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    try:
        group_before = get_active_group(int(float(str(record_id).strip())))
        ids_before = [int(x) for x in group_before.get("id", pd.Series(dtype=object)).tolist()] if isinstance(group_before, pd.DataFrame) and not group_before.empty else [int(float(str(record_id).strip()))]
    except Exception:
        ids_before = [int(float(str(record_id).strip()))] if str(record_id).strip() else []
    n = int(_v134_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        repair_missing_time_records_from_sqlite(ids_before, reason="finish_work_v134_sqlite_to_0102_canonical", github=False)
    return n


def _v134_display_repair_once(reason: str) -> int:
    global _V134_LAST_DISPLAY_REPAIR_AT
    now_s = _v134_now_seconds()
    if now_s and (now_s - float(_V134_LAST_DISPLAY_REPAIR_AT or 0.0)) < _V134_DISPLAY_REPAIR_TTL_SEC:
        return 0
    _V134_LAST_DISPLAY_REPAIR_AT = now_s
    return repair_missing_time_records_from_sqlite(None, reason=reason, github=False)


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    # 若上一輪 start_work 只完成 SQLite/LOG，先補 canonical，再交回既有顯示規則。
    try:
        _v134_display_repair_once("today_records_v134_display_self_repair")
    except Exception:
        pass
    if callable(_v134_prev_today_records):
        return _v134_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only)
    return pd.DataFrame()


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    # 02 歷史紀錄載入前也做同樣保險，修補「LOG 有、02 看不到」情境。
    try:
        _v134_display_repair_once("load_records_v134_display_self_repair")
    except Exception:
        pass
    if callable(_v134_prev_load_records):
        return _v134_prev_load_records(start_date, end_date, employee_id, work_order)
    return pd.DataFrame()

# =================== END V134 LOG INSERT MISSING 01/02 CANONICAL REPAIR ===================

# ===================== V137 50-USER HISTORY SAFE MERGE + PARALLEL FINISH FIX =====================
# 目標：
# - 01 同一人多筆同步作業結束時，02 歷史紀錄必須完整保留群組每一筆，不可只補第一筆。
# - 02 歷史紀錄允許「同一製令 + 同一製程」多人同時紀錄，不可以被第二個人覆蓋。
# - 合併主鍵一律使用 record_key；缺 record_key 時才用「工號+姓名+製令+製程+開始時間」；絕不只用製令+製程。
# - 寫入 01/02 canonical 權威檔時加鎖，降低 50 人同時操作時的最後寫入覆蓋風險。

import threading as _v137_threading

_V137_AUTH_LOCK = _v137_threading.RLock()

try:
    _v137_prev_start_work = start_work
except Exception:
    _v137_prev_start_work = None
try:
    _v137_prev_delete_time_records = delete_time_records
except Exception:
    _v137_prev_delete_time_records = None
try:
    _v137_prev_import_time_records = import_time_records
except Exception:
    _v137_prev_import_time_records = None


def _v137_blank(v) -> bool:
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    if v is None:
        return True
    return str(v).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v137_text(v) -> str:
    if _v137_blank(v):
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _v137_int(v):
    if _v137_blank(v):
        return None
    try:
        return int(float(str(v).strip()))
    except Exception:
        return None


def _v137_clean_df(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    try:
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
        out = out.where(pd.notna(out), "")
    except Exception:
        pass
    drop = []
    ui_cols = {"刪除", "刪除 / Delete", "重算", "重算 / Recalc", "選取", "Select", "selected", "__selected__", "_selected", "_row_selected", "Delete", "Recalc"}
    for c in out.columns:
        if str(c).strip() in ui_cols:
            drop.append(c)
    if drop:
        out = out.drop(columns=drop, errors="ignore")
    return out.reset_index(drop=True)


def _v137_row(row) -> dict:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row.to_dict())
    except Exception:
        return {}


def _v137_identity(row: dict) -> str:
    rk = _v137_text(row.get("record_key") or row.get("紀錄鍵 / Record Key"))
    if rk:
        return "rk:" + rk
    emp_id = _v137_text(row.get("employee_id") or row.get("工號") or row.get("Employee ID"))
    emp_name = _v137_text(row.get("employee_name") or row.get("姓名") or row.get("Employee Name"))
    wo = _v137_text(row.get("work_order") or row.get("製令") or row.get("製令 / Work Order"))
    proc = _v137_text(row.get("process_name") or row.get("工段") or row.get("製程") or row.get("Process"))
    start_ts = _v137_text(row.get("start_timestamp") or row.get("Start Timestamp") or row.get("開始時間"))
    if not start_ts:
        start_ts = ( _v137_text(row.get("start_date")) + " " + _v137_text(row.get("start_time")) ).strip()
    if emp_id or emp_name or wo or proc or start_ts:
        return "biz:" + "|".join([emp_id, emp_name, wo, proc, start_ts])
    rid = _v137_int(row.get("id") if "id" in row else row.get("ID"))
    if rid is not None:
        return "id:" + str(rid)
    return "tmp:" + str(hash(str(sorted(row.items()))))


def _v137_filter_deleted(df: pd.DataFrame) -> pd.DataFrame:
    out = _v137_clean_df(df)
    if out.empty:
        return out
    for name in ("_v97_filter_deleted_df", "_v94_filter_deleted_df", "_v96_filter_tombstone", "_v98_filter_deleted"):
        try:
            fn = globals().get(name)
            if callable(fn):
                tmp = fn(out)
                if isinstance(tmp, pd.DataFrame):
                    out = _v137_clean_df(tmp)
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v137_authority_df(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df
        return _v137_filter_deleted(_pa_df(module_key, "time_records"))
    except Exception:
        return pd.DataFrame()


def _v137_sqlite_df(ids: list[int] | None = None) -> pd.DataFrame:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA busy_timeout=8000")
            except Exception:
                pass
            if ids:
                clean = [int(x) for x in ids if _v137_int(x) is not None]
                if not clean:
                    return pd.DataFrame()
                ph = ",".join(["?"] * len(clean))
                rows = conn.execute(f"SELECT * FROM time_records WHERE id IN ({ph}) ORDER BY id", clean).fetchall()
            else:
                rows = conn.execute("SELECT * FROM time_records ORDER BY id").fetchall()
        return _v137_filter_deleted(pd.DataFrame([dict(r) for r in rows]))
    except Exception:
        return pd.DataFrame()


def _v137_assign_ids(df: pd.DataFrame) -> pd.DataFrame:
    out = _v137_clean_df(df)
    if out.empty:
        return out
    if "id" not in out.columns:
        out.insert(0, "id", "")
    existing = [_v137_int(x) for x in out["id"].tolist()]
    existing = [int(x) for x in existing if x is not None]
    next_id = (max(existing) + 1) if existing else 1
    used: set[int] = set()
    ids = []
    for _, r in out.iterrows():
        rid = _v137_int(r.get("id"))
        if rid is None or rid in used:
            while next_id in used:
                next_id += 1
            rid = next_id
            next_id += 1
        used.add(int(rid))
        ids.append(int(rid))
    out["id"] = ids
    try:
        out["_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
        out = out.sort_values("_sort_id", ascending=True, kind="stable").drop(columns=["_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v137_merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    chosen: dict[str, tuple[str, int, dict]] = {}
    cols: list[str] = []
    seq = 0
    for rank, df in enumerate(frames, start=1):
        df = _v137_filter_deleted(df)
        if df.empty:
            continue
        for _, rr in df.iterrows():
            r = _v137_row(rr)
            key = _v137_identity(r)
            for c in r.keys():
                if c not in cols:
                    cols.append(c)
            score = _v137_text(r.get("updated_at") or r.get("created_at") or r.get("end_timestamp") or r.get("start_timestamp"))
            old = chosen.get(key)
            # 後面的 frame 通常是本次新增/更新資料，rank 較大可覆蓋同一 record_key 的舊資料。
            if old is None or (score, rank, seq) >= (old[0], old[1], seq):
                chosen[key] = (score, rank, r)
            seq += 1
    if "id" not in cols:
        cols.insert(0, "id")
    rows = [{c: r.get(c, "") for c in cols} for _, _, r in chosen.values()]
    return _v137_assign_ids(pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols))


def _v137_current_merged(include_sqlite: bool = False) -> pd.DataFrame:
    frames = [_v137_authority_df("02_history"), _v137_authority_df("01_time_records")]
    if include_sqlite:
        frames.append(_v137_sqlite_df())
    return _v137_merge_frames(frames)


def _v137_rows_to_table(df: pd.DataFrame) -> list[dict]:
    try:
        from services.permanent_authority_service import table_from_df as _pa_table
        return _pa_table(_v137_clean_df(df))
    except Exception:
        clean = _v137_clean_df(df)
        return [dict(r) for _, r in clean.iterrows()]


def _v137_save_0102(df: pd.DataFrame, reason: str, *, github: bool = False) -> int:
    safe = _v137_assign_ids(_v137_filter_deleted(df))
    rows = _v137_rows_to_table(safe)
    with _V137_AUTH_LOCK:
        try:
            from services.permanent_authority_service import save_authority as _pa_save
            _pa_save("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
            _pa_save("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
        except Exception as exc:
            try:
                write_log("V137_0102_AUTHORITY_SAVE_ERROR", f"V137 01/02 權威檔寫入失敗：{exc}", "time_records", level="ERROR")
            except Exception:
                pass
    try:
        clear_today_records_fast_cache()  # type: ignore[name-defined]
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


def _v137_upsert_rows(rows_df: pd.DataFrame, reason: str, *, github: bool = False) -> int:
    rows_df = _v137_filter_deleted(rows_df)
    if rows_df.empty:
        return 0
    with _V137_AUTH_LOCK:
        base = _v137_current_merged(include_sqlite=False)
        merged = _v137_merge_frames([base, rows_df])
        return _v137_save_0102(merged, reason, github=github)


def _v137_schedule_upload(reason: str) -> None:
    try:
        scheduler = globals().get("_v108_schedule_time_authority_upload")
        if callable(scheduler):
            scheduler(reason)
    except Exception:
        pass


def _v137_group_ids(record_id: int) -> list[int]:
    rid = _v137_int(record_id)
    if rid is None:
        return []
    rec = query_one("SELECT * FROM time_records WHERE id=?", (rid,))
    if not rec:
        try:
            if "_v104_hydrate_sqlite_from_authority" in globals():
                _v104_hydrate_sqlite_from_authority(active_only=False, reason="v137_group_pre_hydrate")
        except Exception:
            pass
        rec = query_one("SELECT * FROM time_records WHERE id=?", (rid,))
    if not rec:
        return []
    emp_id = _v137_text(rec.get("employee_id"))
    emp_name = _v137_text(rec.get("employee_name"))
    proc = _v137_text(rec.get("process_name"))
    sdate = _v137_text(rec.get("start_date"))
    if not emp_id or not emp_name or not proc or not sdate:
        return [rid]
    try:
        df = get_active_records(employee_id=emp_id, employee_name=emp_name, process_name=proc, start_date=sdate)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return [rid]
    ids = []
    for x in df.get("id", pd.Series(dtype=object)).tolist():
        ix = _v137_int(x)
        if ix is not None and ix not in ids:
            ids.append(int(ix))
    return ids or [rid]


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if not callable(_v137_prev_start_work):
        raise RuntimeError("start_work core implementation is unavailable")
    rid = int(_v137_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    if rid:
        rows = _v137_sqlite_df([rid])
        if rows.empty:
            rows = _v137_sqlite_df()
        _v137_upsert_rows(rows[rows["id"].map(_v137_int).eq(rid)] if (not rows.empty and "id" in rows.columns) else rows, "start_work_v137_identity_safe_upsert", github=False)
        _v137_schedule_upload("start_work_v137_async_publish")
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    rid0 = _v137_int(record_id)
    if rid0 is None:
        raise ValueError("工時紀錄編號異常，請重新整理頁面後再操作。")
    rec = query_one("SELECT * FROM time_records WHERE id=?", (rid0,))
    if not rec:
        try:
            if "_v104_hydrate_sqlite_from_authority" in globals():
                _v104_hydrate_sqlite_from_authority(active_only=False, reason="finish_work_v137_pre_hydrate")
        except Exception:
            pass
        rec = query_one("SELECT * FROM time_records WHERE id=?", (rid0,))
    if not rec:
        raise ValueError("找不到工時紀錄；此筆可能已刪除、已結束，或畫面資料尚未重新整理。")
    if not _v137_blank(rec.get("end_timestamp")):
        return 0

    # 關鍵修正：先抓完整同步群組 id，再一次更新全部筆數，再把全部更新列 upsert 到 01/02。
    group_ids = _v137_group_ids(rid0) if finish_parallel_group else [rid0]
    if not group_ids:
        group_ids = [rid0]
    group_df = _v137_sqlite_df(group_ids)
    if group_df.empty:
        group_df = pd.DataFrame([rec])
        group_ids = [rid0]

    emp_id = _v137_text(rec.get("employee_id"))
    emp_name = _v137_text(rec.get("employee_name"))
    proc = _v137_text(rec.get("process_name"))
    sdate = _v137_text(rec.get("start_date"))
    if finish_parallel_group and not group_df.empty:
        for c in ["employee_id", "employee_name", "process_name", "start_date", "end_timestamp"]:
            if c not in group_df.columns:
                group_df[c] = ""
        mask = (
            group_df["employee_id"].astype(str).str.strip().eq(emp_id)
            & group_df["employee_name"].astype(str).str.strip().eq(emp_name)
            & group_df["process_name"].astype(str).str.strip().eq(proc)
            & group_df["start_date"].astype(str).str.strip().eq(sdate)
            & group_df["end_timestamp"].map(_v137_blank)
        )
        group_df = group_df.loc[mask].copy()
        group_ids = [int(x) for x in group_df.get("id", pd.Series(dtype=object)).map(_v137_int).dropna().tolist()]
    if not group_ids:
        group_ids = [rid0]
        group_df = pd.DataFrame([rec])

    now = _now()
    end_date, end_time = split_timestamp(now)
    status = end_action if end_action in ("下班", "暫停", "完工") else "已結束"
    starts = [str(x) for x in group_df.get("start_timestamp", pd.Series(dtype=object)).dropna().tolist() if _v137_text(x)]
    earliest_start = min(starts) if starts else _v137_text(rec.get("start_timestamp")) or now
    total_hours = calculate_work_hours(earliest_start, now)
    avg_hours = round(total_hours / max(len(group_ids), 1), 2)
    is_group = 1 if len(group_ids) > 1 else int(rec.get("is_group_work") or 0)
    group_key = rec.get("group_key") or f"{rec.get('employee_id')}|{rec.get('process_name')}|{rec.get('start_date')}"

    updated: list[int] = []
    for rid in group_ids:
        old = query_one("SELECT remark FROM time_records WHERE id=?", (int(rid),)) or {}
        new_remark = old.get("remark") or ""
        append = remark or ""
        if len(group_ids) > 1:
            append = (append + "；" if append else "") + _v138_parallel_summary_text(len(group_ids), total_hours, avg_hours)
        if append:
            new_remark = (new_remark + "；" if new_remark else "") + append
        execute(
            """
            UPDATE time_records
            SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?,
                work_hours=?, remark=?, group_key=?, is_group_work=?, updated_at=?
            WHERE id=? AND (end_timestamp IS NULL OR TRIM(COALESCE(end_timestamp,''))='')
            """,
            (status, end_action, now, end_date, end_time, avg_hours, new_remark, group_key, is_group, now, int(rid)),
        )
        updated.append(int(rid))

    rows = _v137_sqlite_df(updated)
    _v137_upsert_rows(rows, "finish_work_v137_all_parallel_rows_upsert", github=False)
    try:
        write_log(
            "END_WORK_GROUP" if len(updated) > 1 else "END_WORK",
            f"V137 結束工時紀錄 #{rid0}；同步結束={len(updated)}筆；狀態={status}；群組總工時={_v138_hours_to_hms_label(total_hours)}；平均工時={_v138_hours_to_hms_label(avg_hours)}",
            "time_records",
            rid0,
            detail=",".join(str(x) for x in updated),
        )
    except Exception:
        pass
    try:
        clear_today_records_fast_cache()  # type: ignore[name-defined]
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    _v137_schedule_upload("finish_work_v137_async_publish")
    return int(len(updated))


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v137_current_merged(include_sqlite=True)
    if df.empty:
        return pd.DataFrame()
    # V134 延伸：如果 SQLite 有但 02 canonical 漏資料，載入時補回本機 canonical。
    try:
        if len(df) > len(_v137_authority_df("02_history")):
            _v137_save_0102(df, "load_records_v137_display_repair", github=False)
            _v137_schedule_upload("load_records_v137_async_publish")
    except Exception:
        pass
    out = df.copy()
    if start_date and "start_date" in out.columns:
        out = out[out["start_date"].astype(str) >= str(start_date)]
    if end_date and "start_date" in out.columns:
        out = out[out["start_date"].astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str) == str(work_order)]
    try:
        out["_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
        out = out.sort_values("_sort_id", ascending=False, kind="stable").drop(columns=["_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    df = _v137_current_merged(include_sqlite=True)
    if df.empty:
        return pd.DataFrame()
    try:
        if len(df) > len(_v137_authority_df("01_time_records")):
            _v137_save_0102(df, "today_records_v137_display_repair", github=False)
            _v137_schedule_upload("today_records_v137_async_publish")
    except Exception:
        pass
    out = df.copy()
    status = out.get("status", pd.Series("", index=out.index)).fillna("").astype(str).str.strip()
    end_ts = out.get("end_timestamp", pd.Series("", index=out.index)).fillna("").astype(str).str.strip().str.lower()
    unfinished = status.eq("作業中") & (end_ts.eq("") | end_ts.eq("none") | end_ts.eq("nan") | end_ts.eq("nat"))
    if unfinished_only:
        out = out.loc[unfinished].copy()
    else:
        try:
            cycle_start = _business_cycle_start_date()
        except Exception:
            cycle_start = today_text()
        if "start_date" in out.columns:
            out = out.loc[(out["start_date"].astype(str) >= str(cycle_start)) | unfinished].copy()
    try:
        out["_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
        out = out.sort_values("_sort_id", ascending=False, kind="stable").drop(columns=["_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    edit = _v137_clean_df(df)
    if edit.empty:
        return 0
    try:
        cols = [c for c in edit.columns if str(c).lower() != "id"]
        if cols:
            edit = edit.loc[edit[cols].apply(lambda r: any(not _v137_blank(v) for v in r), axis=1)].copy()
    except Exception:
        pass
    if edit.empty:
        return 0
    rows = []
    for _, rr in edit.iterrows():
        r = _v137_row(rr)
        if recalc_edited_timestamps:
            try:
                r.update(normalize_record_datetime_fields(r, recalc_work_hours=True))
            except Exception:
                pass
        if not _v137_text(r.get("record_key")):
            try:
                r["record_key"] = make_record_key(_v137_text(r.get("employee_id")), _v137_text(r.get("work_order")), _v137_text(r.get("process_name")), _v137_text(r.get("start_timestamp")))
            except Exception:
                r["record_key"] = uuid.uuid4().hex
        r["updated_at"] = _now()
        rows.append(r)
    edit = pd.DataFrame(rows)
    with _V137_AUTH_LOCK:
        base = _v137_current_merged(include_sqlite=False)
        merged = _v137_merge_frames([base, edit])
        _v137_save_0102(merged, "save_time_records_v137_identity_safe", github=True)
        try:
            if "_v89_sync_sqlite_cache_from_authority" in globals():
                _v89_sync_sqlite_cache_from_authority(merged)
        except Exception:
            pass
    try:
        write_log("SAVE_TIME_RECORDS", f"V137 已安全合併儲存 {len(edit)} 筆；多人同製令同製程不覆蓋。", "time_records")
    except Exception:
        pass
    return int(len(edit))


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    df = _v137_current_merged(include_sqlite=True)
    if df.empty or "id" not in df.columns:
        return 0
    ids = {_v137_int(x) for x in (record_ids or [])}
    ids = {int(x) for x in ids if x is not None}
    mask = df["id"].map(_v137_int).isin(ids) if ids else pd.Series([True] * len(df), index=df.index)
    count = 0
    for idx in df.loc[mask].index:
        r = _v137_row(df.loc[idx])
        if _v137_blank(r.get("start_timestamp")) or _v137_blank(r.get("end_timestamp")):
            continue
        try:
            normalized = normalize_record_datetime_fields(r, recalc_work_hours=True)
        except Exception:
            normalized = {}
        if not normalized:
            continue
        for c, v in normalized.items():
            if c not in df.columns:
                df[c] = ""
            df.at[idx, c] = v
        if "status" not in df.columns:
            df["status"] = ""
        if _v137_text(df.at[idx, "status"]) == "作業中":
            df.at[idx, "status"] = r.get("end_action") or "已結束"
        if "updated_at" not in df.columns:
            df["updated_at"] = ""
        df.at[idx, "updated_at"] = _now()
        count += 1
    if count:
        _v137_save_0102(df, "recalculate_time_records_v137_identity_safe", github=True)
        try:
            if "_v89_sync_sqlite_cache_from_authority" in globals():
                _v89_sync_sqlite_cache_from_authority(df)
        except Exception:
            pass
    return int(count)


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    ids = {_v137_int(x) for x in (record_ids or [])}
    ids = {int(x) for x in ids if x is not None}
    if not ids:
        return 0
    prev_n = 0
    try:
        if callable(_v137_prev_delete_time_records):
            prev_n = int(_v137_prev_delete_time_records(list(ids), reason=reason) or 0)
    except Exception:
        prev_n = 0
    df = _v137_current_merged(include_sqlite=False)
    if "id" in df.columns:
        before = len(df)
        df = df.loc[~df["id"].map(_v137_int).isin(ids)].copy()
        deleted = before - len(df)
    else:
        deleted = 0
    _v137_save_0102(df, "delete_time_records_v137_identity_safe", github=True)
    try:
        if "_v89_sync_sqlite_cache_from_authority" in globals():
            _v89_sync_sqlite_cache_from_authority(df)
    except Exception:
        pass
    return int(max(prev_n, deleted, len(ids)))


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    result = _v137_prev_import_time_records(df, recalc=recalc, source=source) if callable(_v137_prev_import_time_records) else {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}
    try:
        merged = _v137_current_merged(include_sqlite=True)
        _v137_save_0102(merged, "import_time_records_v137_identity_safe", github=True)
        if isinstance(result, dict):
            result["authority_synced"] = int(len(merged))
    except Exception as exc:
        if isinstance(result, dict):
            result.setdefault("errors", []).append(f"V137 authority sync failed: {exc}")
    return result


def sync_time_records_01_02_now(reason: str = "v137_manual_0102_sync", *, github: bool = True) -> int:  # type: ignore[override]
    merged = _v137_current_merged(include_sqlite=True)
    n = _v137_save_0102(merged, reason, github=bool(github))
    try:
        if "_v89_sync_sqlite_cache_from_authority" in globals():
            _v89_sync_sqlite_cache_from_authority(merged)
    except Exception:
        pass
    return int(n)

# =================== END V137 50-USER HISTORY SAFE MERGE + PARALLEL FINISH FIX ===================

# ===================== V137B SAME-GROUP FINISH LOCK WRAPPER =====================
# 補強：V137 已直接處理同步群組全部結束；此段只把最終 finish_work 再包一次同人員群組鎖，
# 避免兩個頁面同時對同一人員群組按結束造成重複更新。
try:
    _v137b_prev_finish_work = finish_work
except Exception:
    _v137b_prev_finish_work = None


def _v137b_finish_lock_key(record_id) -> str:
    rid = _v137_int(record_id) if "_v137_int" in globals() else None
    if rid is None:
        return f"finish:{record_id}"
    try:
        rec = query_one("SELECT * FROM time_records WHERE id=?", (int(rid),)) or {}
        emp_id = _v137_text(rec.get("employee_id")) if "_v137_text" in globals() else str(rec.get("employee_id") or "").strip()
        emp_name = _v137_text(rec.get("employee_name")) if "_v137_text" in globals() else str(rec.get("employee_name") or "").strip()
        proc = _v137_text(rec.get("process_name")) if "_v137_text" in globals() else str(rec.get("process_name") or "").strip()
        sdate = _v137_text(rec.get("start_date")) if "_v137_text" in globals() else str(rec.get("start_date") or "").strip()
        if emp_id or emp_name:
            return f"finish:{emp_id}|{emp_name}|{proc}|{sdate}"
    except Exception:
        pass
    return f"finish_record:{rid}"


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v137b_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    key = _v137b_finish_lock_key(record_id)
    try:
        lock = _v123_time_lock(key) if "_v123_time_lock" in globals() else _V137_AUTH_LOCK
    except Exception:
        lock = _V137_AUTH_LOCK
    with lock:
        return int(_v137b_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
# =================== END V137B SAME-GROUP FINISH LOCK WRAPPER ===================


# ===================== V138B PARALLEL WORK HOURS HMS DISPLAY FIX =====================
# 目的：
# 1) 01 工時紀錄、02 歷史紀錄中「同步作業平均分配」說明不再顯示 0.08 / 0.02 這類十進位小時。
# 2) 統一顯示為 00:00:00，不在文字中顯示「時:分:秒」。
# 3) work_hours 欄位仍保留 decimal hours 供計算、重算、平均分攤使用；只改備註/畫面文字表示。
# 4) 舊資料若備註已經存在「群組總工時=0.xx，平均=0.xx」或 V138 的「HH:MM:SS時:分:秒」，在 01/02 顯示時也會自動轉為 HH:MM:SS。

try:
    _v138_prev_finish_work = finish_work
except Exception:
    _v138_prev_finish_work = None
try:
    _v138_prev_load_records = load_records
except Exception:
    _v138_prev_load_records = None
try:
    _v138_prev_today_records = today_records
except Exception:
    _v138_prev_today_records = None


def _v138_hours_to_hms_label(hours_value) -> str:
    """Convert decimal hours to 'HH:MM:SS'."""
    try:
        if hours_value is None:
            total_seconds = 0
        else:
            text = str(hours_value).strip()
            # Already HH:MM:SS-like.
            if ":" in text:
                base = text.split("時")[0].strip()
                parts = base.split(":")
                if len(parts) >= 3:
                    h = int(float(parts[0] or 0)); m = int(float(parts[1] or 0)); sec = int(float(parts[2] or 0))
                    return f"{h:02d}:{m:02d}:{sec:02d}"
            total_seconds = int(round(float(text) * 3600))
    except Exception:
        total_seconds = 0
    if total_seconds < 0:
        total_seconds = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _v138_parallel_summary_text(count: int, total_hours, avg_hours) -> str:
    return (
        f"同步作業平均分配：{int(count)}筆，"
        f"群組總工時={_v138_hours_to_hms_label(total_hours)}，"
        f"平均={_v138_hours_to_hms_label(avg_hours)}"
    )


def _v138_convert_parallel_remark_text(value):
    """Convert old decimal-hour parallel summary text inside remark to HH:MM:SS display."""
    try:
        if value is None:
            return value
        try:
            if pd.isna(value):
                return value
        except Exception:
            pass
        text = str(value)
        if "同步作業平均分配" not in text:
            return value
        import re as _re
        pattern = _re.compile(r"同步作業平均分配：\s*(\d+)\s*筆，\s*群組總工時\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*，\s*平均\s*=\s*([0-9]+(?:\.[0-9]+)?)")
        def _repl(m):
            return _v138_parallel_summary_text(int(m.group(1)), m.group(2), m.group(3))
        converted = pattern.sub(_repl, text)
        # V138B: remove the explanatory suffix that V138 briefly appended.
        converted = converted.replace("時:分:秒", "")
        return converted
    except Exception:
        return value


def _v138_format_remark_column(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    for col in ["remark", "備註", "備註 / Remark"]:
        if col in out.columns:
            try:
                out[col] = out[col].map(_v138_convert_parallel_remark_text)
            except Exception:
                pass
    return out


def _v138_update_sqlite_and_authority_remarks(record_ids) -> None:
    """After legacy finish_work writes decimal remark, convert affected rows and sync 01/02."""
    clean_ids = []
    for x in record_ids or []:
        try:
            ix = int(float(str(x).strip()))
            if ix > 0 and ix not in clean_ids:
                clean_ids.append(ix)
        except Exception:
            continue
    if not clean_ids:
        return
    for rid in clean_ids:
        try:
            row = query_one("SELECT remark FROM time_records WHERE id=?", (rid,)) or {}
            old_remark = row.get("remark")
            new_remark = _v138_convert_parallel_remark_text(old_remark)
            if new_remark != old_remark:
                execute("UPDATE time_records SET remark=?, updated_at=? WHERE id=?", (new_remark, _now(), int(rid)))
        except Exception:
            pass
    try:
        if "_v137_sqlite_df" in globals() and "_v137_upsert_rows" in globals():
            rows = _v137_sqlite_df(clean_ids)
            if isinstance(rows, pd.DataFrame) and not rows.empty:
                _v137_upsert_rows(rows, "finish_work_v138_hms_remark_upsert", github=False)
    except Exception:
        pass
    try:
        scheduler = globals().get("_v108_schedule_time_authority_upload") or globals().get("_v137_schedule_upload")
        if callable(scheduler):
            scheduler("finish_work_v138_hms_remark_async_publish")
    except Exception:
        pass


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v138_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    # 先記住可能受影響群組，因為舊 finish_work 完成後就不再是 active group。
    affected_ids = []
    try:
        if finish_parallel_group and "_v137_group_ids" in globals():
            affected_ids = list(_v137_group_ids(int(float(str(record_id).strip()))))
    except Exception:
        affected_ids = []
    if not affected_ids:
        try:
            affected_ids = [int(float(str(record_id).strip()))]
        except Exception:
            affected_ids = []

    n = int(_v138_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        _v138_update_sqlite_and_authority_remarks(affected_ids)
        try:
            clear_today_records_fast_cache()  # type: ignore[name-defined]
        except Exception:
            pass
        try:
            clear_query_cache()
        except Exception:
            pass
    return n


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    if not callable(_v138_prev_load_records):
        return pd.DataFrame()
    return _v138_format_remark_column(_v138_prev_load_records(start_date, end_date, employee_id, work_order))


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    if not callable(_v138_prev_today_records):
        return pd.DataFrame()
    return _v138_format_remark_column(_v138_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only))

# =================== END V138B PARALLEL WORK HOURS HMS DISPLAY FIX ===================

# ===================== V139 01/02 FINAL STATE RECONCILIATION + ACTIVE DISPLAY FIX =====================
# 修正目的：
# 1) 01 今日工時紀錄仍顯示「作業中」，但 02 歷史紀錄同一筆已經是「下班/暫停/完工」時，
#    以已結束狀態為準，避免 01 與 Active Work 顯示假作業中。
# 2) SQLite / 01_time_records / 02_history 三方可能短暫不同步；V139 以 record_key / 業務主鍵合併，
#    已結束版本永遠優先於同一筆的舊作業中版本。
# 3) Active Work、get_active_records、get_active_group 改讀調和後資料，防止已下班的同步作業仍出現在目前作業中。
# 4) 保留 Today Records 當日明細顯示規則：已結束紀錄可以留在今日表，但狀態必須正確顯示為下班/暫停/完工。

try:
    _v139_prev_today_records = today_records
except Exception:
    _v139_prev_today_records = None
try:
    _v139_prev_load_records = load_records
except Exception:
    _v139_prev_load_records = None
try:
    _v139_prev_get_active_records = get_active_records
except Exception:
    _v139_prev_get_active_records = None
try:
    _v139_prev_get_active_record = get_active_record
except Exception:
    _v139_prev_get_active_record = None
try:
    _v139_prev_get_active_group = get_active_group
except Exception:
    _v139_prev_get_active_group = None
try:
    _v139_prev_get_active_same_work = get_active_same_work
except Exception:
    _v139_prev_get_active_same_work = None
try:
    _v139_prev_get_conflicting_active_records = get_conflicting_active_records
except Exception:
    _v139_prev_get_conflicting_active_records = None
try:
    _v139_prev_finish_work = finish_work
except Exception:
    _v139_prev_finish_work = None
try:
    _v139_prev_start_work = start_work
except Exception:
    _v139_prev_start_work = None

_V139_TERMINAL_STATUS = {"下班", "暫停", "完工", "已結束", "結束", "停止"}


def _v139_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v139_text(value) -> str:
    if _v139_blank(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _v139_int(value):
    if _v139_blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _v139_float(value, default: float = 0.0) -> float:
    try:
        if _v139_blank(value):
            return default
        text = str(value).strip()
        if ":" in text:
            return hms_to_hours(text)
        return float(text)
    except Exception:
        return default


def _v139_clean_df(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    try:
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
        out = out.where(pd.notna(out), "")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v139_table_df(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df
        df = _pa_df(module_key, "time_records")
        return _v139_clean_df(df)
    except Exception:
        return pd.DataFrame()


def _v139_sqlite_all_df() -> pd.DataFrame:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA busy_timeout=8000")
            except Exception:
                pass
            rows = conn.execute("SELECT * FROM time_records ORDER BY id").fetchall()
        return _v139_clean_df(pd.DataFrame([dict(r) for r in rows]))
    except Exception:
        return pd.DataFrame()


def _v139_filter_deleted(df: pd.DataFrame) -> pd.DataFrame:
    out = _v139_clean_df(df)
    if out.empty:
        return out
    for name in ("_v97_filter_deleted_df", "_v94_filter_deleted_df", "_v96_filter_tombstone", "_v98_filter_deleted", "_v137_filter_deleted"):
        try:
            fn = globals().get(name)
            if callable(fn):
                tmp = fn(out)
                if isinstance(tmp, pd.DataFrame):
                    out = _v139_clean_df(tmp)
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v139_identity(row: dict) -> str:
    # record_key 是最準的跨 01/02 同筆識別。
    rk = _v139_text(row.get("record_key") or row.get("紀錄鍵 / Record Key"))
    if rk:
        return "rk:" + rk
    emp_id = _v139_text(row.get("employee_id") or row.get("工號") or row.get("Employee ID"))
    emp_name = _v139_text(row.get("employee_name") or row.get("姓名") or row.get("Employee Name"))
    wo = _v139_text(row.get("work_order") or row.get("製令") or row.get("製令 / Work Order"))
    proc = _v139_text(row.get("process_name") or row.get("工段") or row.get("製程") or row.get("Process"))
    start_ts = _v139_text(row.get("start_timestamp") or row.get("Start Timestamp") or row.get("開始時間戳") or row.get("開始時間"))
    if not start_ts:
        start_ts = (_v139_text(row.get("start_date")) + " " + _v139_text(row.get("start_time"))).strip()
    if emp_id or emp_name or wo or proc or start_ts:
        return "biz:" + "|".join([emp_id, emp_name, wo, proc, start_ts])
    rid = _v139_int(row.get("id") if "id" in row else row.get("ID"))
    if rid is not None:
        return "id:" + str(rid)
    return "tmp:" + str(hash(str(sorted(row.items()))))


def _v139_is_terminal_row(row: dict) -> bool:
    status = _v139_text(row.get("status") or row.get("狀態") or row.get("Status"))
    end_action = _v139_text(row.get("end_action") or row.get("結束動作") or row.get("End Action"))
    end_ts = _v139_text(row.get("end_timestamp") or row.get("End Timestamp") or row.get("結束時間戳") or row.get("結束時間"))
    if status in _V139_TERMINAL_STATUS:
        return True
    if end_action in _V139_TERMINAL_STATUS:
        return True
    if end_ts:
        return True
    return False


def _v139_is_active_row(row: dict) -> bool:
    status = _v139_text(row.get("status") or row.get("狀態") or row.get("Status"))
    end_ts = _v139_text(row.get("end_timestamp") or row.get("End Timestamp") or row.get("結束時間戳") or row.get("結束時間"))
    if status and status != "作業中":
        return False
    return not bool(end_ts)


def _v139_score(row: dict, source_rank: int, seq: int) -> tuple:
    # 已結束狀態優先，避免 01 舊作業中覆蓋 02 已下班。
    terminal = 1 if _v139_is_terminal_row(row) else 0
    # 完整欄位多者優先，可避免空列覆蓋完整列。
    completeness = sum(1 for v in row.values() if not _v139_blank(v))
    time_score = "|".join([
        _v139_text(row.get("updated_at")),
        _v139_text(row.get("end_timestamp")),
        _v139_text(row.get("created_at")),
        _v139_text(row.get("start_timestamp")),
    ])
    return (terminal, time_score, completeness, source_rank, seq)


def _v139_merge_sources(frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    chosen: dict[str, tuple[tuple, dict]] = {}
    cols: list[str] = []
    seq = 0
    for source_rank, (_name, df) in enumerate(frames, start=1):
        df = _v139_filter_deleted(df)
        if df.empty:
            continue
        for _, rr in df.iterrows():
            try:
                row = dict(rr.to_dict())
            except Exception:
                row = {}
            if not row:
                continue
            # 忽略完全空白列。
            if not any(not _v139_blank(v) for v in row.values()):
                continue
            for c in row.keys():
                if c not in cols:
                    cols.append(c)
            key = _v139_identity(row)
            score = _v139_score(row, source_rank, seq)
            old = chosen.get(key)
            if old is None or score >= old[0]:
                chosen[key] = (score, row)
            seq += 1
    if "id" not in cols:
        cols.insert(0, "id")
    rows = [{c: row.get(c, "") for c in cols} for _score, row in chosen.values()]
    out = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    try:
        if "id" in out.columns:
            out["_v139_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v139_sort_id", ascending=True, kind="stable").drop(columns=["_v139_sort_id"], errors="ignore")
    except Exception:
        pass
    return _v139_filter_deleted(out).reset_index(drop=True)


def _v139_reconciled_df(include_sqlite: bool = True) -> pd.DataFrame:
    frames: list[tuple[str, pd.DataFrame]] = [
        ("01_time_records", _v139_table_df("01_time_records")),
        ("02_history", _v139_table_df("02_history")),
    ]
    if include_sqlite:
        frames.append(("sqlite", _v139_sqlite_all_df()))
    return _v139_merge_sources(frames)


def _v139_rows_to_table(df: pd.DataFrame) -> list[dict]:
    try:
        from services.permanent_authority_service import table_from_df as _pa_table
        return _pa_table(_v139_clean_df(df))
    except Exception:
        clean = _v139_clean_df(df)
        return [dict(r) for _, r in clean.iterrows()]


def _v139_save_reconciled(df: pd.DataFrame, reason: str = "v139_reconcile_0102", *, github: bool = False, sync_sqlite: bool = True) -> int:
    safe = _v139_filter_deleted(df)
    rows = _v139_rows_to_table(safe)
    try:
        from services.permanent_authority_service import save_authority as _pa_save
        _pa_save("01_time_records", records={"time_records": rows}, reason=f"{reason}_01", github=bool(github))
        _pa_save("02_history", records={"time_records": rows}, reason=f"{reason}_02", github=bool(github))
    except Exception as exc:
        try:
            write_log("V139_0102_RECONCILE_SAVE_ERROR", f"V139 01/02 調和權威檔寫入失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    if sync_sqlite:
        try:
            if "_v89_sync_sqlite_cache_from_authority" in globals():
                _v89_sync_sqlite_cache_from_authority(safe)
        except Exception:
            pass
    try:
        clear_today_records_fast_cache()  # type: ignore[name-defined]
    except Exception:
        pass
    try:
        clear_query_cache()
    except Exception:
        pass
    return int(len(rows))


def _v139_repair_if_needed(reason: str = "v139_display_repair") -> pd.DataFrame:
    df = _v139_reconciled_df(include_sqlite=True)
    if df.empty:
        return df
    # 若 01 / 02 與調和後資料不同，立即以調和結果覆蓋兩邊本機 canonical。
    try:
        df01 = _v139_table_df("01_time_records")
        df02 = _v139_table_df("02_history")
        n = len(df)
        mismatch = (len(df01) != n) or (len(df02) != n)
        if not mismatch:
            # 快速檢查作業中/已結束狀態是否一致。
            rec_map = {}
            for _, r in df.iterrows():
                row = dict(r.to_dict())
                rec_map[_v139_identity(row)] = _v139_is_terminal_row(row)
            for source_df in (df01, df02):
                for _, rr in source_df.iterrows():
                    row = dict(rr.to_dict())
                    key = _v139_identity(row)
                    if key in rec_map and rec_map[key] != _v139_is_terminal_row(row):
                        mismatch = True
                        break
                if mismatch:
                    break
        if mismatch:
            _v139_save_reconciled(df, reason, github=False, sync_sqlite=True)
            try:
                scheduler = globals().get("_v108_schedule_time_authority_upload") or globals().get("_v137_schedule_upload")
                if callable(scheduler):
                    scheduler(f"{reason}_async_publish")
            except Exception:
                pass
    except Exception:
        pass
    return df


def _v139_filter_params(df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    out = _v139_clean_df(df)
    if out.empty:
        return out
    if start_date:
        col = "start_date" if "start_date" in out.columns else ("work_date" if "work_date" in out.columns else "")
        if col:
            out = out[out[col].astype(str) >= str(start_date)]
    if end_date:
        col = "start_date" if "start_date" in out.columns else ("work_date" if "work_date" in out.columns else "")
        if col:
            out = out[out[col].astype(str) <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str).str.strip() == str(employee_id).strip()]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str).str.strip() == str(work_order).strip()]
    try:
        out["_v139_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
        out = out.sort_values("_v139_sort_id", ascending=False, kind="stable").drop(columns=["_v139_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v139_active_df(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    df = _v139_repair_if_needed("v139_active_repair")
    if df.empty:
        return pd.DataFrame()
    rows = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        if _v139_is_active_row(row):
            rows.append(row)
    out = pd.DataFrame(rows) if rows else pd.DataFrame(columns=df.columns)
    if out.empty:
        return out
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str).str.strip() == str(employee_id).strip()]
    if employee_name and "employee_name" in out.columns:
        out = out[out["employee_name"].astype(str).str.strip() == str(employee_name).strip()]
    if process_name and "process_name" in out.columns:
        out = out[out["process_name"].astype(str).str.strip() == str(process_name).strip()]
    if start_date and "start_date" in out.columns:
        out = out[out["start_date"].astype(str).str.strip() == str(start_date).strip()]
    try:
        out["_v139_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
        out = out.sort_values("_v139_sort_id", ascending=True, kind="stable").drop(columns=["_v139_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    df = _v139_repair_if_needed("today_records_v139_final_state_reconcile")
    if df.empty:
        return pd.DataFrame()
    out = df.copy()
    active_mask = out.apply(lambda r: _v139_is_active_row(dict(r.to_dict())), axis=1)
    if unfinished_only:
        out = out.loc[active_mask].copy()
    else:
        try:
            cycle_start = _business_cycle_start_date()
        except Exception:
            cycle_start = today_text()
        if "start_date" in out.columns:
            out = out.loc[(out["start_date"].astype(str) >= str(cycle_start)) | active_mask].copy()
    try:
        if "_v138_format_remark_column" in globals():
            out = _v138_format_remark_column(out)
    except Exception:
        pass
    try:
        out["_v139_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
        out = out.sort_values("_v139_sort_id", ascending=False, kind="stable").drop(columns=["_v139_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    df = _v139_repair_if_needed("load_records_v139_final_state_reconcile")
    out = _v139_filter_params(df, start_date, end_date, employee_id, work_order)
    try:
        if "_v138_format_remark_column" in globals():
            out = _v138_format_remark_column(out)
    except Exception:
        pass
    return out.reset_index(drop=True)


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    return _v139_active_df(employee_id=employee_id, process_name=process_name, start_date=start_date, employee_name=employee_name)


def get_active_record(employee_id: str) -> dict | None:  # type: ignore[override]
    df = _v139_active_df(employee_id=employee_id)
    if df.empty:
        return None
    try:
        if "id" in df.columns:
            df["_v139_sort_id"] = pd.to_numeric(df["id"], errors="coerce")
            df = df.sort_values("_v139_sort_id", ascending=False, kind="stable").drop(columns=["_v139_sort_id"], errors="ignore")
        return df.iloc[0].where(pd.notna(df.iloc[0]), None).to_dict()
    except Exception:
        return None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    rid = _v139_int(record_id)
    if rid is None:
        return pd.DataFrame()
    df = _v139_repair_if_needed("get_active_group_v139_final_state_reconcile")
    if df.empty or "id" not in df.columns:
        return pd.DataFrame()
    recs = df[df["id"].map(_v139_int) == int(rid)].copy()
    if recs.empty:
        return pd.DataFrame()
    row = dict(recs.iloc[0].to_dict())
    if not _v139_is_active_row(row):
        return pd.DataFrame()
    emp_id = _v139_text(row.get("employee_id"))
    emp_name = _v139_text(row.get("employee_name"))
    proc = _v139_text(row.get("process_name"))
    sdate = _v139_text(row.get("start_date"))
    if not emp_id or not emp_name or not proc or not sdate:
        return recs.reset_index(drop=True)
    return _v139_active_df(employee_id=emp_id, employee_name=emp_name, process_name=proc, start_date=sdate)


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v139_active_df(employee_id=employee_id, employee_name=employee_name, process_name=process_name, start_date=start_date or today_text())
    if df.empty or "work_order" not in df.columns:
        return None
    df = df[df["work_order"].astype(str).str.strip() == str(work_order).strip()].copy()
    if df.empty:
        return None
    try:
        return df.iloc[-1].where(pd.notna(df.iloc[-1]), None).to_dict()
    except Exception:
        return None


def get_conflicting_active_records(employee_id: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    start_date = start_date or today_text()
    active = _v139_active_df(employee_id=employee_id, employee_name=employee_name)
    if active.empty:
        return pd.DataFrame()
    for c in ["process_name", "start_date"]:
        if c not in active.columns:
            active[c] = ""
    return active[(active["process_name"].astype(str) != str(process_name)) | (active["start_date"].astype(str) != str(start_date))].copy().reset_index(drop=True)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if not callable(_v139_prev_start_work):
        raise RuntimeError("start_work core implementation is unavailable")
    rid = int(_v139_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    if rid:
        df = _v139_reconciled_df(include_sqlite=True)
        _v139_save_reconciled(df, "start_work_v139_final_state_reconcile", github=False, sync_sqlite=False)
        try:
            scheduler = globals().get("_v108_schedule_time_authority_upload") or globals().get("_v137_schedule_upload")
            if callable(scheduler):
                scheduler("start_work_v139_async_publish")
        except Exception:
            pass
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v139_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    n = int(_v139_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        df = _v139_reconciled_df(include_sqlite=True)
        _v139_save_reconciled(df, "finish_work_v139_final_state_reconcile", github=False, sync_sqlite=True)
        try:
            scheduler = globals().get("_v108_schedule_time_authority_upload") or globals().get("_v137_schedule_upload")
            if callable(scheduler):
                scheduler("finish_work_v139_async_publish")
        except Exception:
            pass
    return n


def reconcile_time_records_final_state_now(reason: str = "manual_v139_reconcile", *, github: bool = True) -> int:
    """Manual helper for 01/02: reconcile SQLite + 01 canonical + 02 canonical and save same final state to both."""
    df = _v139_reconciled_df(include_sqlite=True)
    return _v139_save_reconciled(df, reason, github=bool(github), sync_sqlite=True)

# =================== END V139 01/02 FINAL STATE RECONCILIATION + ACTIVE DISPLAY FIX ===================

# ===================== V140 HISTORY ID INTEGRITY + NON-DESTRUCTIVE 01/02 SAVE GUARD =====================
# 修正目的：
# 1) 02 歷史資料不應因 01/02/SQLite 任一來源的暫時空表、篩選表或舊快取而被整批覆蓋消失。
# 2) ID / ID 是資料庫 surrogate row id，不保證連號；但已存在的歷史列必須保留，不可被弱主鍵合併誤刪。
# 3) 任何非刪除類同步，都先把既有 02_history canonical 納入合併，再寫回 01/02。
# 4) 刪除類操作仍尊重 tombstone，不會把已刪除資料救回。

try:
    _v140_prev_v139_save_reconciled = _v139_save_reconciled  # type: ignore[name-defined]
except Exception:  # pragma: no cover
    _v140_prev_v139_save_reconciled = None

_V140_DELETE_REASON_WORDS = (
    "delete", "deleted", "tombstone", "purge", "remove", "clear_history", "clear_time_records",
    "刪除", "清除"
)


def _v140_is_delete_reason(reason: str | None) -> bool:
    text = str(reason or "").lower()
    return any(word.lower() in text for word in _V140_DELETE_REASON_WORDS)


def _v140_nonempty_df(df) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty


def _v140_history_preserve_merge(incoming_df: pd.DataFrame, reason: str = "v140_preserve") -> pd.DataFrame:
    """Merge incoming data with existing 01/02 authority before non-delete saves.

    This is the core guard against history disappearing.  If a page passes a partial
    dataframe, the existing 02_history rows are preserved unless they are explicitly
    removed through delete/tombstone paths.
    """
    incoming = _v139_clean_df(incoming_df) if "_v139_clean_df" in globals() else (incoming_df.copy() if isinstance(incoming_df, pd.DataFrame) else pd.DataFrame())
    if _v140_is_delete_reason(reason):
        return incoming

    frames: list[tuple[str, pd.DataFrame]] = []
    try:
        df02 = _v139_table_df("02_history") if "_v139_table_df" in globals() else pd.DataFrame()
        if _v140_nonempty_df(df02):
            frames.append(("existing_02_history", df02))
    except Exception:
        pass
    try:
        df01 = _v139_table_df("01_time_records") if "_v139_table_df" in globals() else pd.DataFrame()
        if _v140_nonempty_df(df01):
            frames.append(("existing_01_time_records", df01))
    except Exception:
        pass
    if _v140_nonempty_df(incoming):
        frames.append(("incoming", incoming))
    if not frames:
        return pd.DataFrame()
    try:
        merged = _v139_merge_sources(frames) if "_v139_merge_sources" in globals() else pd.concat([x[1] for x in frames], ignore_index=True)
    except Exception:
        try:
            merged = pd.concat([x[1] for x in frames if isinstance(x[1], pd.DataFrame)], ignore_index=True)
        except Exception:
            merged = incoming
    try:
        if "_v139_filter_deleted" in globals():
            merged = _v139_filter_deleted(merged)
    except Exception:
        pass
    return merged.reset_index(drop=True) if isinstance(merged, pd.DataFrame) else pd.DataFrame()


def _v139_save_reconciled(df: pd.DataFrame, reason: str = "v139_reconcile_0102", *, github: bool = False, sync_sqlite: bool = True) -> int:  # type: ignore[override]
    """V140 override: all non-delete 01/02 saves are non-destructive.

    The previous reconciler could write the currently visible/repaired set back to
    authority.  If one source was temporarily incomplete, visible history looked as
    if many ID rows disappeared.  V140 always preserves existing 02_history rows
    unless the reason is an explicit delete/tombstone operation.
    """
    safe_df = _v140_history_preserve_merge(df, reason=reason)
    if callable(_v140_prev_v139_save_reconciled):
        return int(_v140_prev_v139_save_reconciled(safe_df, reason=reason, github=github, sync_sqlite=sync_sqlite) or 0)
    return int(len(safe_df) if isinstance(safe_df, pd.DataFrame) else 0)


def diagnose_time_record_id_gaps(start_date: str | None = None, end_date: str | None = None) -> dict:
    """Diagnostic helper for 02 History ID gaps.

    ID gaps alone do not mean data loss because SQLite row ids are not business
    sequence numbers.  This helper reports gaps and row counts so admins can compare
    them with delete logs / tombstones.
    """
    try:
        df = load_records(start_date=start_date, end_date=end_date)  # type: ignore[misc]
    except Exception:
        df = pd.DataFrame()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "id" not in df.columns:
        return {"row_count": 0, "min_id": None, "max_id": None, "missing_count": 0, "missing_ids": []}
    ids = []
    for v in df["id"].tolist():
        try:
            i = int(float(str(v).strip()))
            if i > 0:
                ids.append(i)
        except Exception:
            continue
    if not ids:
        return {"row_count": len(df), "min_id": None, "max_id": None, "missing_count": 0, "missing_ids": []}
    existing = set(ids)
    missing = [i for i in range(min(existing), max(existing) + 1) if i not in existing]
    return {
        "row_count": int(len(df)),
        "id_count": int(len(ids)),
        "min_id": int(min(existing)),
        "max_id": int(max(existing)),
        "missing_count": int(len(missing)),
        "missing_ids": missing[:500],
        "note": "ID 是資料庫流水號，不保證連續；若 missing_count 增加，需比對 DELETE_TIME_RECORDS / tombstone / 匯入覆蓋紀錄。V140 已加上非刪除同步保護，避免部分資料表覆蓋完整歷史。",
    }

# =================== END V140 HISTORY ID INTEGRITY + NON-DESTRUCTIVE 01/02 SAVE GUARD ===================

# ===================== V141 STRICT SELECTED-EMPLOYEE ACTIVE WORK FILTER =====================
# 修正目的：
# 1) 01「結束目前作業 / Finish Work」選擇 SSS 時，Active Work 不得顯示 SPT243 羅丹等其他人員未結束紀錄。
# 2) 病根：前面多版為了修 01/02 權威檔與 SQLite cache 不同步，Active Work 會合併 01_time_records、02_history、SQLite；
#    若合併後欄位是 UI 顯示欄名（例如「工號 / Employee ID」）或 selectbox label 解析出現 sss | sss，
#    舊版只在存在 employee_id 欄時才套用篩選，欄位不一致時會跳過篩選，導致回傳第一筆作業中資料。
# 3) V141：所有 Active Work 查詢先把欄位轉成 canonical 欄位，再用 工號 + 姓名 + 工段 + 日期 做嚴格篩選；
#    若指定人員查不到未結束資料，必須回傳空，不可 fallback 成其他人員。

_V141_FIELD_ALIASES = {
    "id": ["id", "ID", "ID / ID", "ID/ID", "編號", "序號"],
    "employee_id": ["employee_id", "工號", "工號 / Employee ID", "Employee ID", "員工編號"],
    "employee_name": ["employee_name", "姓名", "姓名 / Name", "Name", "員工姓名"],
    "status": ["status", "狀態", "狀態 / Status", "Status"],
    "work_order": ["work_order", "製令", "製令 / Work Order", "Work Order"],
    "process_name": ["process_name", "工段", "工段名稱", "工段名稱 / Process", "製程", "Process"],
    "start_date": ["start_date", "開始日期", "開始日期 / Start Date", "Work Date", "work_date"],
    "start_time": ["start_time", "開始時間", "開始時間 / Start Time"],
    "start_timestamp": ["start_timestamp", "開始時間戳", "開始時間戳 / Start Timestamp", "Start Timestamp", "開始時間"],
    "end_timestamp": ["end_timestamp", "結束時間戳", "結束時間戳 / End Timestamp", "End Timestamp", "結束時間"],
    "end_action": ["end_action", "結束動作", "結束動作 / End Action", "End Action"],
    "record_key": ["record_key", "紀錄鍵", "紀錄鍵 / Record Key", "Record Key"],
    "group_key": ["group_key", "群組鍵", "群組鍵 / Group Key", "Group Key"],
}


def _v141_norm_text(value) -> str:
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


def _v141_norm_key(value) -> str:
    return _v141_norm_text(value).casefold()


def _v141_parse_employee_label(value) -> tuple[str, str]:
    """Accept both 'SPT001｜王小明' and 'SPT001 | 王小明'."""
    text = _v141_norm_text(value)
    if not text:
        return "", ""
    import re as _re
    parts = [p.strip() for p in _re.split(r"\s*[｜|]\s*", text, maxsplit=1)]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return text, ""


def _v141_first_existing_col(df: pd.DataFrame, names: list[str]) -> str | None:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    existing = {str(c).strip(): c for c in df.columns}
    existing_fold = {str(c).strip().casefold(): c for c in df.columns}
    for n in names:
        if n in existing:
            return existing[n]
        fn = str(n).strip().casefold()
        if fn in existing_fold:
            return existing_fold[fn]
    return None


def _v141_canonical_active_df(df: pd.DataFrame | None) -> pd.DataFrame:
    """Make sure active-work filtering always has canonical columns.

    It does not remove original display columns; it only adds canonical columns when
    a display/bilingual alias exists. This keeps render_table behavior unchanged.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    if out.empty:
        return out
    try:
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    except Exception:
        pass
    for canonical, aliases in _V141_FIELD_ALIASES.items():
        if canonical not in out.columns:
            src = _v141_first_existing_col(out, aliases)
            if src is not None:
                out[canonical] = out[src]
    return out.reset_index(drop=True)


def _v141_is_active_row(row: dict) -> bool:
    try:
        if "_v139_is_active_row" in globals():
            return bool(_v139_is_active_row(row))
    except Exception:
        pass
    status = _v141_norm_text(row.get("status"))
    end_ts = _v141_norm_text(row.get("end_timestamp"))
    if status and status != "作業中":
        return False
    return not bool(end_ts)


def _v141_reconciled_active_source(reason: str = "v141_active_filter") -> pd.DataFrame:
    try:
        if "_v139_repair_if_needed" in globals():
            return _v141_canonical_active_df(_v139_repair_if_needed(reason))
    except Exception:
        pass
    try:
        if "_v139_reconciled_df" in globals():
            return _v141_canonical_active_df(_v139_reconciled_df(include_sqlite=True))
    except Exception:
        pass
    try:
        return _v141_canonical_active_df(query_df("SELECT * FROM time_records ORDER BY id"))
    except Exception:
        return pd.DataFrame()


def _v141_filter_active_df(
    employee_id: str | None = None,
    process_name: str | None = None,
    start_date: str | None = None,
    employee_name: str | None = None,
    reason: str = "v141_filter_active",
) -> pd.DataFrame:
    emp_id, parsed_name = _v141_parse_employee_label(employee_id)
    emp_name = _v141_norm_text(employee_name) or parsed_name
    proc = _v141_norm_text(process_name)
    sdate = _v141_norm_text(start_date)

    df = _v141_reconciled_active_source(reason)
    if df.empty:
        return pd.DataFrame()

    active_rows = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        if _v141_is_active_row(row):
            active_rows.append(row)
    out = pd.DataFrame(active_rows) if active_rows else pd.DataFrame(columns=df.columns)
    out = _v141_canonical_active_df(out)
    if out.empty:
        return out

    # 指定 employee_id 時必須嚴格篩選；欄位不存在也不可回傳其他人。
    if emp_id:
        if "employee_id" not in out.columns:
            return pd.DataFrame(columns=out.columns)
        out = out[out["employee_id"].map(_v141_norm_key) == _v141_norm_key(emp_id)].copy()
    if emp_name:
        if "employee_name" not in out.columns:
            return pd.DataFrame(columns=out.columns)
        out = out[out["employee_name"].map(_v141_norm_key) == _v141_norm_key(emp_name)].copy()
    if proc:
        if "process_name" not in out.columns:
            return pd.DataFrame(columns=out.columns)
        out = out[out["process_name"].map(_v141_norm_key) == _v141_norm_key(proc)].copy()
    if sdate:
        if "start_date" not in out.columns:
            return pd.DataFrame(columns=out.columns)
        out = out[out["start_date"].map(_v141_norm_text) == sdate].copy()
    try:
        if "id" in out.columns:
            out["_v141_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v141_sort_id", ascending=True, kind="stable").drop(columns=["_v141_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    return _v141_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        process_name=process_name,
        start_date=start_date,
        reason="get_active_records_v141_strict_selected_employee",
    )


def get_active_record(employee_id: str, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v141_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        reason="get_active_record_v141_strict_selected_employee",
    )
    if df.empty:
        return None
    try:
        if "id" in df.columns:
            df["_v141_sort_id"] = pd.to_numeric(df["id"], errors="coerce")
            df = df.sort_values("_v141_sort_id", ascending=False, kind="stable").drop(columns=["_v141_sort_id"], errors="ignore")
        row = df.iloc[0].where(pd.notna(df.iloc[0]), None).to_dict()
        # 最後防線：確認回傳者仍等於指定人員。
        emp_id, parsed_name = _v141_parse_employee_label(employee_id)
        emp_name = _v141_norm_text(employee_name) or parsed_name
        if emp_id and _v141_norm_key(row.get("employee_id")) != _v141_norm_key(emp_id):
            return None
        if emp_name and _v141_norm_key(row.get("employee_name")) != _v141_norm_key(emp_name):
            return None
        return row
    except Exception:
        return None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        return pd.DataFrame()
    df = _v141_reconciled_active_source("get_active_group_v141_strict_selected_employee")
    df = _v141_canonical_active_df(df)
    if df.empty or "id" not in df.columns:
        return pd.DataFrame()
    try:
        recs = df[df["id"].map(lambda x: int(float(str(x).strip())) if _v141_norm_text(x) else -1) == rid].copy()
    except Exception:
        recs = pd.DataFrame()
    if recs.empty:
        return pd.DataFrame()
    row = dict(recs.iloc[0].to_dict())
    if not _v141_is_active_row(row):
        return pd.DataFrame()
    emp_id = _v141_norm_text(row.get("employee_id"))
    emp_name = _v141_norm_text(row.get("employee_name"))
    proc = _v141_norm_text(row.get("process_name"))
    sdate = _v141_norm_text(row.get("start_date"))
    if not emp_id:
        return recs.reset_index(drop=True)
    return _v141_filter_active_df(
        employee_id=emp_id,
        employee_name=emp_name or None,
        process_name=proc or None,
        start_date=sdate or None,
        reason="get_active_group_v141_strict_selected_employee_group",
    )


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v141_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        process_name=process_name,
        start_date=start_date or today_text(),
        reason="get_active_same_work_v141_strict_selected_employee",
    )
    if df.empty:
        return None
    if "work_order" not in df.columns:
        return None
    df = df[df["work_order"].map(_v141_norm_key) == _v141_norm_key(work_order)].copy()
    if df.empty:
        return None
    try:
        return df.iloc[-1].where(pd.notna(df.iloc[-1]), None).to_dict()
    except Exception:
        return None


def get_conflicting_active_records(employee_id: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    start_date = start_date or today_text()
    active = _v141_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        reason="get_conflicting_active_records_v141_strict_selected_employee",
    )
    if active.empty:
        return pd.DataFrame()
    for c in ["process_name", "start_date"]:
        if c not in active.columns:
            active[c] = ""
    out = active[(active["process_name"].map(_v141_norm_key) != _v141_norm_key(process_name)) | (active["start_date"].map(_v141_norm_text) != _v141_norm_text(start_date))].copy()
    return out.reset_index(drop=True)


def repair_active_work_employee_filter_now(reason: str = "manual_v141_active_employee_filter_repair") -> dict:
    """Diagnostic helper for 01 Active Work mismatch."""
    df = _v141_reconciled_active_source(reason)
    out = _v141_canonical_active_df(df)
    active = _v141_filter_active_df(reason=reason + "_active_only")
    return {
        "total_rows": int(len(out)) if isinstance(out, pd.DataFrame) else 0,
        "active_rows": int(len(active)) if isinstance(active, pd.DataFrame) else 0,
        "columns": list(out.columns) if isinstance(out, pd.DataFrame) else [],
        "note": "V141 已強制 Active Work 依選擇人員的工號與姓名過濾；指定人員查無未結束紀錄時回傳空，不會顯示其他人員。",
    }

# =================== END V141 STRICT SELECTED-EMPLOYEE ACTIVE WORK FILTER ===================

# ===================== V143 ACTIVE WORK SELECTED-EMPLOYEE IDENTITY HARD GUARD =====================
# 修正目的：
# 1) 01 右側「結束目前作業 / Active Work」必須嚴格對應使用者選擇的人員。
# 2) 若同一列同時存在 canonical 欄位與雙語顯示欄位，且兩者人員資訊不一致，視為污染列，不得顯示給其他人。
# 3) record_key 內的工號也納入比對，防止 employee_id 欄被舊合併流程覆蓋但 record_key 仍屬其他人。
# 4) 只修讀取/顯示/篩選防線，不重新編號、不刪歷史、不改 02 正式資料。

_V143_EMPLOYEE_ID_COLS = [
    "employee_id", "工號 / Employee ID", "工號", "Employee ID", "員工編號", "人員工號",
]
_V143_EMPLOYEE_NAME_COLS = [
    "employee_name", "姓名 / Name", "姓名", "Name", "員工姓名", "人員姓名",
]
_V143_PROCESS_COLS = ["process_name", "工段名稱 / Process", "工段 / Process", "工段", "Process"]
_V143_START_DATE_COLS = ["start_date", "開始日期 / Start Date", "開始日期", "Start Date"]
_V143_STATUS_COLS = ["status", "狀態 / Status", "狀態", "Status"]
_V143_END_TS_COLS = ["end_timestamp", "結束時間戳 / End Timestamp", "結束時間 / End Timestamp", "結束時間戳", "End Timestamp"]


def _v143_norm(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in {"none", "nan", "nat", "null", "<na>"}:
        return ""
    return s


def _v143_key(value) -> str:
    return _v143_norm(value).casefold()


def _v143_existing_cols(df: pd.DataFrame, candidates: list[str]) -> list:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    exact = {str(c).strip(): c for c in df.columns}
    folded = {str(c).strip().casefold(): c for c in df.columns}
    out = []
    for c in candidates:
        found = None
        if c in exact:
            found = exact[c]
        else:
            found = folded.get(str(c).strip().casefold())
        if found is not None and found not in out:
            out.append(found)
    return out


def _v143_values_from_row(row: dict, cols: list[str]) -> list[str]:
    vals: list[str] = []
    for c in cols:
        v = _v143_norm(row.get(c))
        if v and v not in vals:
            vals.append(v)
    return vals


def _v143_record_key_employee_id(row: dict) -> str:
    rk = _v143_norm(row.get("record_key") or row.get("紀錄鍵 / Record Key") or row.get("Record Key"))
    if not rk or "|" not in rk:
        return ""
    first = rk.split("|", 1)[0].strip()
    return first if first and first.lower() not in {"none", "nan", "null"} else ""


def _v143_add_canonical_columns(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    if out.empty:
        return out
    try:
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    except Exception:
        pass

    def _copy_if_missing(canonical: str, aliases: list[str]) -> None:
        if canonical in out.columns:
            return
        for src in _v143_existing_cols(out, aliases):
            out[canonical] = out[src]
            return

    _copy_if_missing("employee_id", _V143_EMPLOYEE_ID_COLS)
    _copy_if_missing("employee_name", _V143_EMPLOYEE_NAME_COLS)
    _copy_if_missing("process_name", _V143_PROCESS_COLS)
    _copy_if_missing("start_date", _V143_START_DATE_COLS)
    _copy_if_missing("status", _V143_STATUS_COLS)
    _copy_if_missing("end_timestamp", _V143_END_TS_COLS)
    return out.reset_index(drop=True)


def _v143_is_active_row(row: dict) -> bool:
    # 同時檢查 canonical 與雙語欄位；任一欄明確已結束，就不列為 Active Work。
    statuses = _v143_values_from_row(row, _V143_STATUS_COLS)
    end_values = _v143_values_from_row(row, _V143_END_TS_COLS)
    ended_status = {"下班", "暫停", "完工", "已結束", "結束"}
    if any(s in ended_status for s in statuses):
        return False
    if end_values:
        return False
    # 若有狀態，必須是作業中；若無狀態但沒有結束時間，仍視為可能未結束，交由人員篩選。
    return (not statuses) or any(s == "作業中" for s in statuses)


def _v143_identity_matches_selected(row: dict, employee_id: str | None, employee_name: str | None = None) -> bool:
    """Strict identity check across canonical fields, display aliases, and record_key.

    If the selected employee is SSS, a row showing SPT243 in any employee-id display
    field is rejected even if another hidden/canonical field says SSS. This prevents
    mixed rows from being shown in the wrong user's Active Work area.
    """
    selected_id = _v143_key(employee_id)
    selected_name = _v143_key(employee_name)

    id_values = _v143_values_from_row(row, _V143_EMPLOYEE_ID_COLS)
    rk_emp = _v143_record_key_employee_id(row)
    if rk_emp:
        id_values.append(rk_emp)
    id_keys = {_v143_key(v) for v in id_values if _v143_key(v)}

    name_values = _v143_values_from_row(row, _V143_EMPLOYEE_NAME_COLS)
    name_keys = {_v143_key(v) for v in name_values if _v143_key(v)}

    if selected_id:
        if not id_keys:
            return False
        # 任一非空工號欄位與選擇人員不一致，即視為污染列，不顯示。
        if any(k != selected_id for k in id_keys):
            return False
    if selected_name:
        # 姓名欄若存在，全部都必須一致；姓名全空時不擋，避免舊資料缺姓名造成無法結束。
        if name_keys and any(k != selected_name for k in name_keys):
            return False
    return True


def _v143_reconciled_active_source(reason: str = "v143_active_source") -> pd.DataFrame:
    try:
        if "_v139_repair_if_needed" in globals():
            return _v143_add_canonical_columns(_v139_repair_if_needed(reason))
    except Exception:
        pass
    try:
        if "_v139_reconciled_df" in globals():
            return _v143_add_canonical_columns(_v139_reconciled_df(include_sqlite=True))
    except Exception:
        pass
    try:
        return _v143_add_canonical_columns(query_df("SELECT * FROM time_records ORDER BY id"))
    except Exception:
        return pd.DataFrame()


def _v143_filter_active_df(
    employee_id: str | None = None,
    process_name: str | None = None,
    start_date: str | None = None,
    employee_name: str | None = None,
    reason: str = "v143_filter_active",
) -> pd.DataFrame:
    emp_id = _v143_norm(employee_id)
    emp_name = _v143_norm(employee_name)
    proc = _v143_norm(process_name)
    sdate = _v143_norm(start_date)
    df = _v143_reconciled_active_source(reason)
    if df is None or df.empty:
        return pd.DataFrame()

    rows = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        if not _v143_is_active_row(row):
            continue
        if emp_id and not _v143_identity_matches_selected(row, emp_id, emp_name):
            continue
        if proc:
            proc_values = {_v143_key(v) for v in _v143_values_from_row(row, _V143_PROCESS_COLS) if _v143_key(v)}
            if proc_values and _v143_key(proc) not in proc_values:
                continue
            if not proc_values:
                continue
        if sdate:
            date_values = {_v143_norm(v) for v in _v143_values_from_row(row, _V143_START_DATE_COLS) if _v143_norm(v)}
            if date_values and sdate not in date_values:
                continue
            if not date_values:
                continue
        rows.append(row)

    out = _v143_add_canonical_columns(pd.DataFrame(rows)) if rows else pd.DataFrame(columns=df.columns)
    if out.empty:
        return out
    try:
        if "id" in out.columns:
            out["_v143_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v143_sort_id", ascending=True, kind="stable").drop(columns=["_v143_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    return _v143_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        process_name=process_name,
        start_date=start_date,
        reason="get_active_records_v143_all_identity_columns_strict",
    )


def get_active_record(employee_id: str, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v143_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        reason="get_active_record_v143_all_identity_columns_strict",
    )
    if df.empty:
        return None
    try:
        if "id" in df.columns:
            df["_v143_sort_id"] = pd.to_numeric(df["id"], errors="coerce")
            df = df.sort_values("_v143_sort_id", ascending=False, kind="stable").drop(columns=["_v143_sort_id"], errors="ignore")
        row = df.iloc[0].where(pd.notna(df.iloc[0]), None).to_dict()
        if not _v143_identity_matches_selected(row, employee_id, employee_name):
            return None
        return row
    except Exception:
        return None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        return pd.DataFrame()
    df = _v143_reconciled_active_source("get_active_group_v143_all_identity_columns_strict")
    if df.empty or "id" not in df.columns:
        return pd.DataFrame()
    try:
        base = df[df["id"].map(lambda x: int(float(str(x).strip())) if _v143_norm(x) else -1) == rid].copy()
    except Exception:
        base = pd.DataFrame()
    if base.empty:
        return pd.DataFrame()
    base_row = dict(base.iloc[0].to_dict())
    if not _v143_is_active_row(base_row):
        return pd.DataFrame()
    emp_id = _v143_norm(base_row.get("employee_id") or base_row.get("工號 / Employee ID") or _v143_record_key_employee_id(base_row))
    emp_name = _v143_norm(base_row.get("employee_name") or base_row.get("姓名 / Name"))
    if not emp_id or not _v143_identity_matches_selected(base_row, emp_id, emp_name):
        # 資料列本身的身份欄位互相矛盾，不可拿來當結束群組基準。
        return pd.DataFrame()
    return _v143_filter_active_df(
        employee_id=emp_id,
        employee_name=emp_name or None,
        process_name=_v143_norm(base_row.get("process_name") or base_row.get("工段名稱 / Process")) or None,
        start_date=_v143_norm(base_row.get("start_date") or base_row.get("開始日期 / Start Date")) or None,
        reason="get_active_group_v143_all_identity_columns_strict_group",
    )


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v143_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        process_name=process_name,
        start_date=start_date or today_text(),
        reason="get_active_same_work_v143_all_identity_columns_strict",
    )
    if df.empty:
        return None
    # Work order may have aliases, so inspect both canonical and bilingual labels.
    order_cols = ["work_order", "製令 / Work Order", "製令", "Work Order"]
    target = _v143_key(work_order)
    keep = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        vals = {_v143_key(v) for v in _v143_values_from_row(row, order_cols) if _v143_key(v)}
        if target in vals:
            keep.append(row)
    if not keep:
        return None
    try:
        return pd.DataFrame(keep).iloc[-1].where(pd.notna(pd.DataFrame(keep).iloc[-1]), None).to_dict()
    except Exception:
        return keep[-1]


def get_conflicting_active_records(employee_id: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    start_date = start_date or today_text()
    active = _v143_filter_active_df(
        employee_id=employee_id,
        employee_name=employee_name,
        reason="get_conflicting_active_records_v143_all_identity_columns_strict",
    )
    if active.empty:
        return pd.DataFrame()
    rows = []
    for _, rr in active.iterrows():
        row = dict(rr.to_dict())
        proc_values = {_v143_key(v) for v in _v143_values_from_row(row, _V143_PROCESS_COLS) if _v143_key(v)}
        date_values = {_v143_norm(v) for v in _v143_values_from_row(row, _V143_START_DATE_COLS) if _v143_norm(v)}
        if (_v143_key(process_name) not in proc_values) or (_v143_norm(start_date) not in date_values):
            rows.append(row)
    return _v143_add_canonical_columns(pd.DataFrame(rows)) if rows else pd.DataFrame()


def inspect_active_work_identity_conflicts(employee_id: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    """Diagnostic helper: list active rows whose identity columns conflict.

    This is read-only and can be called from a temporary debug cell if needed.
    """
    df = _v143_reconciled_active_source("inspect_active_work_identity_conflicts_v143")
    rows = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        if not _v143_is_active_row(row):
            continue
        id_vals = _v143_values_from_row(row, _V143_EMPLOYEE_ID_COLS)
        rk = _v143_record_key_employee_id(row)
        if rk:
            id_vals.append(rk)
        name_vals = _v143_values_from_row(row, _V143_EMPLOYEE_NAME_COLS)
        id_keys = {_v143_key(v) for v in id_vals if _v143_key(v)}
        name_keys = {_v143_key(v) for v in name_vals if _v143_key(v)}
        conflict = len(id_keys) > 1 or len(name_keys) > 1
        if employee_id and not _v143_identity_matches_selected(row, employee_id, employee_name):
            conflict = True
        if conflict:
            rows.append({
                "id": row.get("id"),
                "record_key": row.get("record_key"),
                "employee_id_values": " | ".join(id_vals),
                "employee_name_values": " | ".join(name_vals),
                "status_values": " | ".join(_v143_values_from_row(row, _V143_STATUS_COLS)),
                "process": row.get("process_name") or row.get("工段名稱 / Process"),
                "work_order": row.get("work_order") or row.get("製令 / Work Order"),
            })
    return pd.DataFrame(rows)

# =================== END V143 ACTIVE WORK SELECTED-EMPLOYEE IDENTITY HARD GUARD ===================

# ===================== V147 TIME RECORD FLUSH + PERFORMANCE SAFE QUEUE HOOK =====================
# 目的：保留 V108 開始/結束作業秒級回應；登出或手動刷新時，才主動補送 GitHub 佇列。
try:
    _v147_prev_flush_time_record_authority_upload_now = flush_time_record_authority_upload_now  # type: ignore[name-defined]
except Exception:
    _v147_prev_flush_time_record_authority_upload_now = None


def flush_time_record_authority_upload_now(reason: str = "v147_flush_time_authority") -> bool:  # type: ignore[override]
    ok = False
    try:
        if callable(_v147_prev_flush_time_record_authority_upload_now):
            ok = bool(_v147_prev_flush_time_record_authority_upload_now(reason))
    except Exception:
        ok = False
    try:
        from services.permanent_authority_service import flush_authority_upload_queue_now
        res = flush_authority_upload_queue_now(reason=reason, max_seconds=8.0)
        ok = bool(ok or res.get("ok") or int(res.get("pending") or 0) == 0)
    except Exception:
        pass
    try:
        from services.log_service import flush_log_authority_batch_now
        flush_log_authority_batch_now(reason=f"{reason}_log_flush")
    except Exception:
        pass
    return bool(ok)


def get_time_record_performance_status() -> dict:
    """診斷用，不觸發資料寫入。"""
    out = {}
    try:
        from services.permanent_authority_service import get_authority_upload_queue_status
        out["authority_upload_queue"] = get_authority_upload_queue_status()
    except Exception as exc:
        out["authority_upload_queue"] = {"error": str(exc)[:300]}
    try:
        from services.log_service import get_log_batch_status
        out["log_batch"] = get_log_batch_status()
    except Exception as exc:
        out["log_batch"] = {"error": str(exc)[:300]}
    return out
# =================== END V147 TIME RECORD FLUSH + PERFORMANCE SAFE QUEUE HOOK ===================

# ===================== V149 ACTIVE WORK TERMINAL STATE CROSS-SOURCE GUARD =====================
# 修正目的：
# 1) 01「目前作業中 / Active Work」不得顯示已在 02 歷史紀錄標記為暫停/下班/完工的同一筆資料。
# 2) 同一筆資料可能在 SQLite、01_time_records、02_history 中有不同版本；Active Work 必須以最終狀態為準。
# 3) 為避免 SQLite id 重用誤殺新資料，ID 只在業務主鍵或 record_key 可佐證時才作為終止狀態判斷依據。
# 4) 僅加強讀取/顯示與 Active Work 判斷，不刪除歷史、不重新編號、不用畫面局部資料覆蓋完整權威檔。

_V149_TERMINAL_STATUS = {"下班", "暫停", "完工", "已結束", "結束", "停止", "已停止", "closed", "finished", "complete", "completed", "pause", "paused", "off duty"}
_V149_ACTIVE_STATUS = {"作業中", "working", "active", "in progress"}

_V149_ID_COLS = ["id", "ID", "ID / ID", "紀錄編號", "record_id"]
_V149_RECORD_KEY_COLS = ["record_key", "紀錄鍵 / Record Key", "紀錄鍵", "Record Key"]
_V149_EMP_ID_COLS = ["employee_id", "工號 / Employee ID", "工號", "Employee ID", "員工編號", "人員工號"]
_V149_EMP_NAME_COLS = ["employee_name", "姓名 / Name", "姓名", "Name", "員工姓名", "人員姓名"]
_V149_WORK_ORDER_COLS = ["work_order", "製令 / Work Order", "製令", "Work Order", "製令單號"]
_V149_PROCESS_COLS = ["process_name", "工段名稱 / Process", "工段 / Process", "工段", "製程", "Process"]
_V149_START_TS_COLS = ["start_timestamp", "開始時間戳 / Start Timestamp", "開始時間戳", "Start Timestamp", "開始時間"]
_V149_START_DATE_COLS = ["start_date", "開始日期 / Start Date", "開始日期", "Start Date", "work_date", "日期"]
_V149_START_TIME_COLS = ["start_time", "開始時間 / Start Time", "開始時間", "Start Time"]
_V149_STATUS_COLS = ["status", "狀態 / Status", "狀態", "Status"]
_V149_END_ACTION_COLS = ["end_action", "結束動作 / End Action", "結束動作", "End Action"]
_V149_END_TS_COLS = ["end_timestamp", "結束時間戳 / End Timestamp", "結束時間 / End Timestamp", "結束時間戳", "結束時間", "End Timestamp"]


def _v149_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v149_norm(value) -> str:
    if _v149_blank(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _v149_key(value) -> str:
    return _v149_norm(value).replace("｜", "|").strip().lower()


def _v149_first(row: dict, cols: list[str]) -> str:
    for c in cols:
        if c in row and not _v149_blank(row.get(c)):
            return _v149_norm(row.get(c))
    return ""


def _v149_values(row: dict, cols: list[str]) -> list[str]:
    out: list[str] = []
    for c in cols:
        if c in row and not _v149_blank(row.get(c)):
            v = _v149_norm(row.get(c))
            if v and v not in out:
                out.append(v)
    return out


def _v149_int(value):
    if _v149_blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _v149_row_id(row: dict):
    for c in _V149_ID_COLS:
        if c in row:
            rid = _v149_int(row.get(c))
            if rid is not None and rid > 0:
                return rid
    return None


def _v149_record_key(row: dict) -> str:
    for c in _V149_RECORD_KEY_COLS:
        if c in row and not _v149_blank(row.get(c)):
            return _v149_norm(row.get(c))
    return ""


def _v149_record_key_employee(row: dict) -> str:
    rk = _v149_record_key(row)
    if not rk or "|" not in rk:
        return ""
    return rk.split("|", 1)[0].strip()


def _v149_start_timestamp(row: dict) -> str:
    ts = _v149_first(row, _V149_START_TS_COLS)
    if ts:
        try:
            dt = pd.to_datetime(ts, errors="coerce")
            if not pd.isna(dt):
                return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        return ts[:19]
    d = _v149_first(row, _V149_START_DATE_COLS)
    t = _v149_first(row, _V149_START_TIME_COLS)
    if d:
        d = d.replace("/", "-")[:10]
        t = (t or "00:00:00").replace("：", ":")[:8]
        if len(t) == 5:
            t += ":00"
        return f"{d} {t}"
    return ""


def _v149_business_key(row: dict) -> str:
    emp = _v149_first(row, _V149_EMP_ID_COLS) or _v149_record_key_employee(row)
    wo = _v149_first(row, _V149_WORK_ORDER_COLS)
    proc = _v149_first(row, _V149_PROCESS_COLS)
    start_ts = _v149_start_timestamp(row)
    if emp and wo and proc and start_ts:
        return "biz:" + "|".join([_v149_key(emp), _v149_key(wo), _v149_key(proc), _v149_key(start_ts)])
    return ""


def _v149_loose_identity(row: dict) -> tuple[str, str, str, str]:
    emp = _v149_key(_v149_first(row, _V149_EMP_ID_COLS) or _v149_record_key_employee(row))
    wo = _v149_key(_v149_first(row, _V149_WORK_ORDER_COLS))
    proc = _v149_key(_v149_first(row, _V149_PROCESS_COLS))
    start_ts = _v149_key(_v149_start_timestamp(row))
    return emp, wo, proc, start_ts


def _v149_is_terminal_row(row: dict) -> bool:
    statuses = {_v149_key(x) for x in _v149_values(row, _V149_STATUS_COLS)}
    end_actions = {_v149_key(x) for x in _v149_values(row, _V149_END_ACTION_COLS)}
    end_values = [_v149_norm(x) for x in _v149_values(row, _V149_END_TS_COLS) if _v149_norm(x)]
    terminal_keys = {_v149_key(x) for x in _V149_TERMINAL_STATUS}
    if statuses and any(s in terminal_keys for s in statuses):
        return True
    if end_actions and any(a in terminal_keys for a in end_actions):
        return True
    if end_values:
        return True
    return False


def _v149_is_active_row(row: dict) -> bool:
    if _v149_is_terminal_row(row):
        return False
    statuses = {_v149_key(x) for x in _v149_values(row, _V149_STATUS_COLS)}
    active_keys = {_v149_key(x) for x in _V149_ACTIVE_STATUS}
    if statuses:
        return any(s in active_keys for s in statuses) and not any(s not in active_keys for s in statuses)
    return True


def _v149_raw_time_sources() -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for module_key in ("01_time_records", "02_history"):
        try:
            if "_v139_table_df" in globals():
                df = _v139_table_df(module_key)
            else:
                from services.permanent_authority_service import df_from_table as _pa_df
                df = _pa_df(module_key, "time_records")
            if isinstance(df, pd.DataFrame) and not df.empty:
                frames.append(df.copy())
        except Exception:
            pass
    try:
        if "_v139_sqlite_all_df" in globals():
            df = _v139_sqlite_all_df()
        else:
            df = query_df("SELECT * FROM time_records ORDER BY id")
        if isinstance(df, pd.DataFrame) and not df.empty:
            frames.append(df.copy())
    except Exception:
        pass
    return frames


def _v149_clean_df(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    try:
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
        out = out.where(pd.notna(out), "")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v149_filter_deleted(df: pd.DataFrame) -> pd.DataFrame:
    out = _v149_clean_df(df)
    for name in ("_v139_filter_deleted", "_v98_filter_deleted", "_v97_filter_deleted_df", "_v94_filter_deleted_df", "_v96_filter_tombstone"):
        try:
            fn = globals().get(name)
            if callable(fn):
                tmp = fn(out)
                if isinstance(tmp, pd.DataFrame):
                    out = _v149_clean_df(tmp)
        except Exception:
            pass
    return out


def _v149_terminal_index() -> dict:
    """Build final-state markers from all live sources without mutating data."""
    rks: set[str] = set()
    biz: set[str] = set()
    by_id: dict[int, list[dict]] = {}
    rows: list[dict] = []
    for df in _v149_raw_time_sources():
        df = _v149_filter_deleted(df)
        if df.empty:
            continue
        for _, rr in df.iterrows():
            row = dict(rr.to_dict())
            if not _v149_is_terminal_row(row):
                continue
            rows.append(row)
            rk = _v149_record_key(row)
            if rk:
                rks.add(_v149_key(rk))
            b = _v149_business_key(row)
            if b:
                biz.add(b)
            rid = _v149_row_id(row)
            if rid is not None:
                by_id.setdefault(int(rid), []).append(row)
    return {"record_keys": rks, "business_keys": biz, "by_id": by_id, "rows": rows}


def _v149_same_logical_record_by_id(active_row: dict, terminal_row: dict) -> bool:
    """Use id only when additional fields support that both rows are the same record.

    This avoids the old SQLite id-reuse problem: a new active row must not be hidden
    merely because an old terminal row reused the same numeric id.
    """
    ark = _v149_record_key(active_row)
    trk = _v149_record_key(terminal_row)
    if ark and trk:
        return _v149_key(ark) == _v149_key(trk)
    abiz = _v149_business_key(active_row)
    tbiz = _v149_business_key(terminal_row)
    if abiz and tbiz:
        return abiz == tbiz

    a_emp, a_wo, a_proc, a_start = _v149_loose_identity(active_row)
    t_emp, t_wo, t_proc, t_start = _v149_loose_identity(terminal_row)
    required_pairs = [(a_emp, t_emp), (a_wo, t_wo), (a_proc, t_proc)]
    if not all(a and b and a == b for a, b in required_pairs):
        return False
    # 開始時間若雙方都有，必須一致；若任一方缺開始時間，至少同工號+製令+工段才視為同筆 id 的舊/新版本。
    if a_start and t_start:
        return a_start == t_start
    return True


def _v149_has_terminal_twin(row: dict, terminal_index: dict | None = None) -> bool:
    if terminal_index is None:
        terminal_index = _v149_terminal_index()
    rk = _v149_record_key(row)
    if rk and _v149_key(rk) in terminal_index.get("record_keys", set()):
        return True
    b = _v149_business_key(row)
    if b and b in terminal_index.get("business_keys", set()):
        return True
    rid = _v149_row_id(row)
    if rid is not None:
        for trow in terminal_index.get("by_id", {}).get(int(rid), []):
            if _v149_same_logical_record_by_id(row, trow):
                return True
    return False


def _v149_source_for_active(reason: str = "v149_active_source") -> pd.DataFrame:
    try:
        if "_v139_reconciled_df" in globals():
            df = _v139_reconciled_df(include_sqlite=True)
        elif "_v143_reconciled_active_source" in globals():
            df = _v143_reconciled_active_source(reason)
        else:
            df = query_df("SELECT * FROM time_records ORDER BY id")
    except Exception:
        df = pd.DataFrame()
    try:
        if "_v143_add_canonical_columns" in globals():
            df = _v143_add_canonical_columns(df)
    except Exception:
        pass
    return _v149_filter_deleted(df)


def _v149_identity_matches(row: dict, employee_id: str | None, employee_name: str | None = None) -> bool:
    try:
        if "_v143_identity_matches_selected" in globals():
            return bool(_v143_identity_matches_selected(row, employee_id, employee_name))
    except Exception:
        pass
    selected_id = _v149_key(employee_id)
    selected_name = _v149_key(employee_name)
    id_values = _v149_values(row, _V149_EMP_ID_COLS)
    rk_emp = _v149_record_key_employee(row)
    if rk_emp:
        id_values.append(rk_emp)
    ids = {_v149_key(x) for x in id_values if _v149_key(x)}
    names = {_v149_key(x) for x in _v149_values(row, _V149_EMP_NAME_COLS) if _v149_key(x)}
    if selected_id and (not ids or any(x != selected_id for x in ids)):
        return False
    if selected_name and names and any(x != selected_name for x in names):
        return False
    return True


def _v149_filter_active_df(
    employee_id: str | None = None,
    process_name: str | None = None,
    start_date: str | None = None,
    employee_name: str | None = None,
    reason: str = "v149_filter_active",
) -> pd.DataFrame:
    df = _v149_source_for_active(reason)
    if df.empty:
        return pd.DataFrame()
    terminal_index = _v149_terminal_index()
    rows: list[dict] = []
    emp_id = _v149_norm(employee_id)
    emp_name = _v149_norm(employee_name)
    proc_key = _v149_key(process_name)
    sdate = _v149_norm(start_date)
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        if not _v149_is_active_row(row):
            continue
        if _v149_has_terminal_twin(row, terminal_index):
            # 核心修正：任何來源已標記同筆資料為暫停/下班/完工，Active Work 不可再顯示作業中舊版。
            continue
        if emp_id and not _v149_identity_matches(row, emp_id, emp_name):
            continue
        if proc_key:
            proc_values = {_v149_key(v) for v in _v149_values(row, _V149_PROCESS_COLS) if _v149_key(v)}
            if proc_key not in proc_values:
                continue
        if sdate:
            # start_date 比 timestamp 寬鬆；避免 timestamp 造成日期欄缺失時無法結束舊筆。
            date_values = {_v149_norm(v)[:10] for v in _v149_values(row, _V149_START_DATE_COLS) if _v149_norm(v)}
            ts = _v149_start_timestamp(row)
            if ts:
                date_values.add(ts[:10])
            if sdate[:10] not in date_values:
                continue
        rows.append(row)
    out = pd.DataFrame(rows) if rows else pd.DataFrame(columns=df.columns)
    try:
        if "_v143_add_canonical_columns" in globals():
            out = _v143_add_canonical_columns(out)
    except Exception:
        pass
    if not out.empty and "id" in out.columns:
        try:
            out["_v149_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v149_sort_id", ascending=True, kind="stable").drop(columns=["_v149_sort_id"], errors="ignore")
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v149_remove_stale_active_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Display guard for Today/History: remove old active rows when a terminal twin exists."""
    out = _v149_filter_deleted(df)
    if out.empty:
        return out
    terminal_index = _v149_terminal_index()
    keep_rows: list[dict] = []
    for _, rr in out.iterrows():
        row = dict(rr.to_dict())
        if _v149_is_active_row(row) and _v149_has_terminal_twin(row, terminal_index):
            continue
        keep_rows.append(row)
    clean = pd.DataFrame(keep_rows) if keep_rows else pd.DataFrame(columns=out.columns)
    return clean.reset_index(drop=True)


# Save previous public functions before overriding.
try:
    _v149_prev_today_records = today_records
except Exception:
    _v149_prev_today_records = None
try:
    _v149_prev_load_records = load_records
except Exception:
    _v149_prev_load_records = None
try:
    _v149_prev_finish_work = finish_work
except Exception:
    _v149_prev_finish_work = None


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    return _v149_filter_active_df(employee_id=employee_id, employee_name=employee_name, process_name=process_name, start_date=start_date, reason="get_active_records_v149_terminal_guard")


def get_active_record(employee_id: str, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v149_filter_active_df(employee_id=employee_id, employee_name=employee_name, reason="get_active_record_v149_terminal_guard")
    if df.empty:
        return None
    try:
        if "id" in df.columns:
            df["_v149_sort_id"] = pd.to_numeric(df["id"], errors="coerce")
            df = df.sort_values("_v149_sort_id", ascending=False, kind="stable").drop(columns=["_v149_sort_id"], errors="ignore")
        row = df.iloc[0].where(pd.notna(df.iloc[0]), None).to_dict()
        if not _v149_identity_matches(row, employee_id, employee_name):
            return None
        if _v149_has_terminal_twin(row):
            return None
        return row
    except Exception:
        return None


def get_active_group(record_id: int) -> pd.DataFrame:  # type: ignore[override]
    rid = _v149_int(record_id)
    if rid is None:
        return pd.DataFrame()
    df = _v149_source_for_active("get_active_group_v149_terminal_guard")
    if df.empty or "id" not in df.columns:
        return pd.DataFrame()
    try:
        base = df[df["id"].map(_v149_int) == int(rid)].copy()
    except Exception:
        base = pd.DataFrame()
    if base.empty:
        return pd.DataFrame()
    terminal_index = _v149_terminal_index()
    # If any same logical record is already terminal, there is no active group to finish.
    for _, rr in base.iterrows():
        brow = dict(rr.to_dict())
        if _v149_is_terminal_row(brow) or _v149_has_terminal_twin(brow, terminal_index):
            return pd.DataFrame()
    base_row = dict(base.iloc[0].to_dict())
    emp_id = _v149_first(base_row, _V149_EMP_ID_COLS) or _v149_record_key_employee(base_row)
    emp_name = _v149_first(base_row, _V149_EMP_NAME_COLS)
    proc = _v149_first(base_row, _V149_PROCESS_COLS)
    sdate = _v149_first(base_row, _V149_START_DATE_COLS) or _v149_start_timestamp(base_row)[:10]
    if not emp_id or not _v149_identity_matches(base_row, emp_id, emp_name):
        return pd.DataFrame()
    return _v149_filter_active_df(employee_id=emp_id, employee_name=emp_name or None, process_name=proc or None, start_date=sdate or None, reason="get_active_group_v149_terminal_guard_group")


def get_active_same_work(employee_id: str, work_order: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> dict | None:  # type: ignore[override]
    df = _v149_filter_active_df(employee_id=employee_id, employee_name=employee_name, process_name=process_name, start_date=start_date or today_text(), reason="get_active_same_work_v149_terminal_guard")
    if df.empty:
        return None
    target = _v149_key(work_order)
    keep: list[dict] = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        vals = {_v149_key(v) for v in _v149_values(row, _V149_WORK_ORDER_COLS) if _v149_key(v)}
        if target in vals:
            keep.append(row)
    if not keep:
        return None
    try:
        row = pd.DataFrame(keep).iloc[-1]
        return row.where(pd.notna(row), None).to_dict()
    except Exception:
        return keep[-1]


def get_conflicting_active_records(employee_id: str, process_name: str, start_date: str | None = None, employee_name: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    start_date = start_date or today_text()
    active = _v149_filter_active_df(employee_id=employee_id, employee_name=employee_name, reason="get_conflicting_active_records_v149_terminal_guard")
    if active.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    proc_key = _v149_key(process_name)
    date_key = _v149_norm(start_date)[:10]
    for _, rr in active.iterrows():
        row = dict(rr.to_dict())
        proc_values = {_v149_key(v) for v in _v149_values(row, _V149_PROCESS_COLS) if _v149_key(v)}
        dates = {_v149_norm(v)[:10] for v in _v149_values(row, _V149_START_DATE_COLS) if _v149_norm(v)}
        ts = _v149_start_timestamp(row)
        if ts:
            dates.add(ts[:10])
        if proc_key not in proc_values or date_key not in dates:
            rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame()


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    if callable(_v149_prev_today_records):
        df = _v149_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only)
    else:
        df = pd.DataFrame()
    out = _v149_remove_stale_active_duplicates(df)
    if unfinished_only and not out.empty:
        rows = [dict(r.to_dict()) for _, r in out.iterrows() if _v149_is_active_row(dict(r.to_dict())) and not _v149_has_terminal_twin(dict(r.to_dict()))]
        out = pd.DataFrame(rows) if rows else pd.DataFrame(columns=out.columns)
    return out.reset_index(drop=True) if isinstance(out, pd.DataFrame) else pd.DataFrame()


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    if callable(_v149_prev_load_records):
        df = _v149_prev_load_records(start_date=start_date, end_date=end_date, employee_id=employee_id, work_order=work_order)
    else:
        df = pd.DataFrame()
    return _v149_remove_stale_active_duplicates(df)


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v149_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    n = int(_v149_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    if n:
        # 結束動作完成後，清除快取並本機調和一次；不強制等待 GitHub，避免 50 人操作變慢。
        try:
            if "clear_today_records_fast_cache" in globals():
                clear_today_records_fast_cache()
        except Exception:
            pass
        try:
            if "clear_query_cache" in globals():
                clear_query_cache()
        except Exception:
            pass
        try:
            if "_v139_reconciled_df" in globals() and "_v139_save_reconciled" in globals():
                _v139_save_reconciled(_v139_reconciled_df(include_sqlite=True), "finish_work_v149_terminal_guard_reconcile", github=False, sync_sqlite=True)
        except Exception as exc:
            try:
                write_log("V149_FINISH_RECONCILE_WARN", f"V149 結束後本機調和失敗：{exc}", "time_records", record_id, level="WARN")
            except Exception:
                pass
    return n


def inspect_active_work_terminal_conflicts(employee_id: str | None = None, employee_name: str | None = None) -> pd.DataFrame:
    """Read-only diagnostic: active rows that are hidden because another source says terminal."""
    df = _v149_source_for_active("inspect_active_work_terminal_conflicts_v149")
    if df.empty:
        return pd.DataFrame()
    terminal_index = _v149_terminal_index()
    rows: list[dict] = []
    for _, rr in df.iterrows():
        row = dict(rr.to_dict())
        if not _v149_is_active_row(row):
            continue
        if employee_id and not _v149_identity_matches(row, employee_id, employee_name):
            continue
        if _v149_has_terminal_twin(row, terminal_index):
            rows.append({
                "id": _v149_row_id(row),
                "employee_id": _v149_first(row, _V149_EMP_ID_COLS) or _v149_record_key_employee(row),
                "employee_name": _v149_first(row, _V149_EMP_NAME_COLS),
                "work_order": _v149_first(row, _V149_WORK_ORDER_COLS),
                "process_name": _v149_first(row, _V149_PROCESS_COLS),
                "start_timestamp": _v149_start_timestamp(row),
                "status_values": " | ".join(_v149_values(row, _V149_STATUS_COLS)),
                "record_key": _v149_record_key(row),
                "reason": "同一筆資料在其他來源已是暫停/下班/完工，Active Work 已隱藏舊作業中版本",
            })
    return pd.DataFrame(rows)

# =================== END V149 ACTIVE WORK TERMINAL STATE CROSS-SOURCE GUARD ===================

# ===================== V151 TIME RECORD DURABLE ROW SHARD + NON-DESTRUCTIVE MERGE =====================
# 修正目的：
# 1) LOG 有 START_WORK / INSERT，但 02 歷史紀錄缺該筆資料，代表 SQLite 已寫入但 01/02 canonical 未確實保留。
# 2) 50 人同時操作時，舊版以整包 records.json 讀取→合併→覆蓋寫回，容易發生 last-writer-wins，
#    造成 A 使用者剛新增的資料被 B 使用者用舊版 authority 覆蓋掉。
# 3) V151 新增「單筆 row shard」耐久層：每次開始/結束，除了原本 SQLite 與 canonical 外，
#    會把該筆工時以 record_key/business key 存成單筆 JSON。顯示與匯出時會把 records.json、SQLite、row shards
#    做非破壞式合併，避免任何一個來源漏資料造成歷史消失。
# 4) 刪除仍尊重 tombstone；已刪除資料不會因 row shard 被救回。

try:
    _v151_prev_start_work = start_work
except Exception:  # pragma: no cover
    _v151_prev_start_work = None
try:
    _v151_prev_finish_work = finish_work
except Exception:  # pragma: no cover
    _v151_prev_finish_work = None
try:
    _v151_prev_load_records = load_records
except Exception:  # pragma: no cover
    _v151_prev_load_records = None
try:
    _v151_prev_today_records = today_records
except Exception:  # pragma: no cover
    _v151_prev_today_records = None
try:
    _v151_prev_sync_time_records_01_02_now = sync_time_records_01_02_now
except Exception:  # pragma: no cover
    _v151_prev_sync_time_records_01_02_now = None

import hashlib as _v151_hashlib
import json as _v151_json
import os as _v151_os
from pathlib import Path as _v151_Path
import threading as _v151_threading

_V151_ROW_SHARD_LOCK = _v151_threading.RLock()
_V151_PROJECT_ROOT = _v151_Path(__file__).resolve().parents[1]
_V151_SHARD_MODULES = ("01_time_records", "02_history")
_V151_TERMINAL_STATUSES = {"下班", "暫停", "完工", "已結束", "結束", "停止", "已停止", "closed", "finished", "complete", "completed", "pause", "paused", "off duty"}


def _v151_text(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if value is None:
        return ""
    return str(value).strip()


def _v151_json_default(value):
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value.strftime("%Y-%m-%d")
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    return str(value)


def _v151_row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


def _v151_first(row: dict, cols: list[str]) -> str:
    for c in cols:
        if c in row:
            v = _v151_text(row.get(c))
            if v:
                return v
    return ""


def _v151_record_key(row: dict) -> str:
    return _v151_first(row, ["record_key", "紀錄鍵 / Record Key", "紀錄鍵", "Record Key"])


def _v151_employee_id(row: dict) -> str:
    rk = _v151_record_key(row)
    from_rk = rk.split("|", 1)[0].strip() if "|" in rk else ""
    return _v151_first(row, ["employee_id", "工號 / Employee ID", "工號", "Employee ID", "員工編號"]) or from_rk


def _v151_employee_name(row: dict) -> str:
    return _v151_first(row, ["employee_name", "姓名 / Name", "姓名", "Name", "員工姓名"])


def _v151_work_order(row: dict) -> str:
    return _v151_first(row, ["work_order", "製令 / Work Order", "製令", "Work Order", "製令單號"])


def _v151_process(row: dict) -> str:
    return _v151_first(row, ["process_name", "工段名稱 / Process", "工段 / Process", "工段", "製程", "Process"])


def _v151_start_ts(row: dict) -> str:
    ts = _v151_first(row, ["start_timestamp", "開始時間戳 / Start Timestamp", "開始時間戳", "Start Timestamp", "開始時間"])
    if ts:
        return ts
    d = _v151_first(row, ["start_date", "開始日期 / Start Date", "開始日期", "Start Date", "work_date", "日期"])
    t = _v151_first(row, ["start_time", "開始時間 / Start Time", "開始時間", "Start Time"])
    return (d + " " + t).strip()


def _v151_row_id(row: dict) -> str:
    return _v151_first(row, ["id", "ID", "ID / ID", "紀錄編號", "record_id"])


def _v151_identity_key(row: dict) -> str:
    rk = _v151_record_key(row)
    if rk:
        return "rk:" + rk
    emp = _v151_employee_id(row)
    name = _v151_employee_name(row)
    wo = _v151_work_order(row)
    proc = _v151_process(row)
    st = _v151_start_ts(row)
    if emp and wo and proc and st:
        return "biz:" + "|".join([emp, name, wo, proc, st])
    rid = _v151_row_id(row)
    if rid:
        # ID 只做最後 fallback，避免 SQLite id 重用誤覆蓋不同人的資料。
        return "id:" + rid
    raw = _v151_json.dumps(row, ensure_ascii=False, sort_keys=True, default=_v151_json_default)
    return "hash:" + _v151_hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _v151_shard_name(row: dict) -> str:
    key = _v151_identity_key(row)
    digest = _v151_hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    rid = _v151_row_id(row) or "noid"
    sdate = (_v151_start_ts(row)[:10] or today_text()).replace("/", "-")
    safe_rid = "".join(ch if ch.isalnum() else "_" for ch in str(rid))[:40]
    return f"{sdate}/tr_{safe_rid}_{digest}.json"


def _v151_shard_path(module_key: str, row: dict) -> _v151_Path:
    return _V151_PROJECT_ROOT / "data" / "permanent_store" / "modules" / str(module_key) / "time_record_rows" / _v151_shard_name(row)


def _v151_status_key(value) -> str:
    return _v151_text(value).lower().replace(" ", "")


def _v151_is_terminal(row: dict) -> bool:
    try:
        if "_v149_is_terminal" in globals() and callable(globals().get("_v149_is_terminal")):
            return bool(globals()["_v149_is_terminal"](row))
    except Exception:
        pass
    vals = []
    for c in ["status", "狀態 / Status", "狀態", "Status", "end_action", "結束動作 / End Action", "結束動作"]:
        if c in row:
            vals.append(row.get(c))
    if _v151_first(row, ["end_timestamp", "結束時間戳 / End Timestamp", "結束時間", "End Timestamp"]):
        return True
    terminal = {_v151_status_key(x) for x in _V151_TERMINAL_STATUSES}
    return any(_v151_status_key(x) in terminal for x in vals)


def _v151_updated_score(row: dict) -> tuple[int, str, str]:
    terminal = 1 if _v151_is_terminal(row) else 0
    ts = _v151_first(row, ["updated_at", "更新時間 / Updated At", "updated_time", "end_timestamp", "結束時間戳 / End Timestamp", "start_timestamp", "created_at"])
    rid = _v151_row_id(row)
    return (terminal, ts, rid)


def _v151_merge_rows(*row_groups) -> list[dict]:
    """Non-destructive merge; terminal/latest rows win but columns are unioned."""
    merged: dict[str, dict] = {}
    scores: dict[str, tuple[int, str, str]] = {}
    for group in row_groups:
        if group is None:
            continue
        if isinstance(group, pd.DataFrame):
            iterable = [dict(r) for _, r in group.where(pd.notna(group), "").iterrows()]
        else:
            iterable = group if isinstance(group, list) else []
        for raw in iterable:
            row = _v151_row_dict(raw)
            if not row:
                continue
            key = _v151_identity_key(row)
            score = _v151_updated_score(row)
            if key not in merged:
                merged[key] = dict(row)
                scores[key] = score
                continue
            old = merged[key]
            old_score = scores.get(key, (0, "", ""))
            # keep all nonblank fields; if current row is newer/terminal it can replace conflicting fields.
            newer = score >= old_score
            combined = dict(old)
            for c, v in row.items():
                sv = _v151_text(v)
                if newer:
                    if sv or not _v151_text(combined.get(c)):
                        combined[c] = v
                else:
                    if c not in combined or not _v151_text(combined.get(c)):
                        combined[c] = v
            if newer:
                merged[key] = combined
                scores[key] = score
            else:
                merged[key] = combined
    rows = list(merged.values())
    try:
        rows.sort(key=lambda r: int(float(_v151_row_id(r) or 0)))
    except Exception:
        rows.sort(key=lambda r: _v151_start_ts(r))
    # Apply delete tombstone last so deliberately deleted rows do not revive.
    try:
        if rows and "_v94_filter_deleted_df" in globals() and callable(globals().get("_v94_filter_deleted_df")):
            df = pd.DataFrame(rows)
            df = globals()["_v94_filter_deleted_df"](df)
            rows = [dict(r) for _, r in df.where(pd.notna(df), "").iterrows()]
    except Exception:
        pass
    return rows


def _v151_sqlite_all_rows() -> list[dict]:
    try:
        df = query_df("SELECT * FROM time_records ORDER BY id")
        if isinstance(df, pd.DataFrame) and not df.empty:
            return [dict(r) for _, r in df.where(pd.notna(df), "").iterrows()]
    except Exception:
        pass
    return []


def _v151_query_rows_by_ids(ids) -> pd.DataFrame:
    clean: list[int] = []
    for x in ids or []:
        try:
            i = int(float(str(x).strip()))
            if i > 0 and i not in clean:
                clean.append(i)
        except Exception:
            continue
    if not clean:
        return pd.DataFrame()
    try:
        ph = ",".join(["?"] * len(clean))
        return query_df(f"SELECT * FROM time_records WHERE id IN ({ph}) ORDER BY id", clean)
    except Exception:
        rows = []
        for i in clean:
            try:
                r = query_one("SELECT * FROM time_records WHERE id=?", (i,)) or {}
                if r:
                    rows.append(r)
            except Exception:
                pass
        return pd.DataFrame(rows)


def _v151_load_authority_rows(module_key: str) -> list[dict]:
    try:
        from services.permanent_authority_service import load_tables as _pa_load_tables
        rows = (_pa_load_tables(module_key, "records") or {}).get("time_records", [])
        return [dict(r) for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def _v151_load_shard_rows() -> list[dict]:
    rows: list[dict] = []
    seen_files: set[str] = set()
    for module_key in _V151_SHARD_MODULES:
        root = _V151_PROJECT_ROOT / "data" / "permanent_store" / "modules" / module_key / "time_record_rows"
        if not root.exists():
            continue
        for p in sorted(root.glob("**/*.json")):
            sp = str(p.resolve())
            if sp in seen_files:
                continue
            seen_files.add(sp)
            try:
                data = _v151_json.loads(p.read_text(encoding="utf-8"))
                row = data.get("row") if isinstance(data, dict) else None
                if isinstance(row, dict):
                    rows.append(dict(row))
            except Exception:
                continue
    return rows


def _v151_atomic_write_json(path: _v151_Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_v151_json.dumps(payload, ensure_ascii=False, indent=2, default=_v151_json_default), encoding="utf-8")
    # Validate before replace.
    _v151_json.loads(tmp.read_text(encoding="utf-8"))
    _v151_os.replace(tmp, path)


def _v151_github_upload_file(path: _v151_Path, reason: str) -> dict:
    try:
        # Row shards are small and path-unique. Uploading them prevents Reboot from losing rows while avoiding full records.json races.
        if str(_v151_os.environ.get("SPT_TIME_RECORD_ROW_SHARD_GITHUB", "1")).strip().lower() in {"0", "false", "no", "off"}:
            return {"ok": True, "skipped": True, "reason": "disabled_by_env"}
        from services.permanent_authority_service import github_put_file as _pa_github_put_file
        return _pa_github_put_file(path, path.read_text(encoding="utf-8"), f"SPT V151 time record row shard: {reason}")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _v151_write_row_shards(rows, reason: str = "v151_row_shard", *, github: bool = True) -> int:
    if isinstance(rows, pd.DataFrame):
        iterable = [dict(r) for _, r in rows.where(pd.notna(rows), "").iterrows()]
    elif isinstance(rows, list):
        iterable = [dict(r) for r in rows if isinstance(r, dict)]
    elif isinstance(rows, dict):
        iterable = [dict(rows)]
    else:
        iterable = []
    if not iterable:
        return 0
    wrote = 0
    with _V151_ROW_SHARD_LOCK:
        for row in iterable:
            if not row:
                continue
            payload = {
                "schema": "SPT-TimeRecordRowShard-V151",
                "reason": reason,
                "saved_at": _now() if "_now" in globals() else now_text(),
                "identity_key": _v151_identity_key(row),
                "row": row,
            }
            # local mirror to both modules for current runtime; GitHub upload only needs 02_history shard.
            for module_key in _V151_SHARD_MODULES:
                p = _v151_shard_path(module_key, row)
                try:
                    _v151_atomic_write_json(p, payload)
                    wrote += 1
                except Exception as exc:
                    try:
                        write_log("V151_ROW_SHARD_WRITE_ERROR", f"寫入 row shard 失敗 {p}: {exc}", "time_records", _v151_row_id(row), level="ERROR")
                    except Exception:
                        pass
            if github:
                try:
                    p2 = _v151_shard_path("02_history", row)
                    res = _v151_github_upload_file(p2, reason)
                    if not res.get("ok"):
                        write_log("V151_ROW_SHARD_GITHUB_ERROR", f"row shard 上傳 GitHub 失敗：{res}", "time_records", _v151_row_id(row), level="ERROR")
                except Exception:
                    pass
    return wrote


def _v151_save_canonical_non_destructive(extra_rows=None, reason: str = "v151_non_destructive_merge", *, github: bool = False) -> int:
    try:
        existing01 = _v151_load_authority_rows("01_time_records")
        existing02 = _v151_load_authority_rows("02_history")
        shards = _v151_load_shard_rows()
        sqlite_rows = _v151_sqlite_all_rows()
        if isinstance(extra_rows, pd.DataFrame):
            extra = [dict(r) for _, r in extra_rows.where(pd.notna(extra_rows), "").iterrows()]
        elif isinstance(extra_rows, list):
            extra = [dict(r) for r in extra_rows if isinstance(r, dict)]
        elif isinstance(extra_rows, dict):
            extra = [dict(extra_rows)]
        else:
            extra = []
        merged = _v151_merge_rows(existing01, existing02, shards, sqlite_rows, extra)
        from services.permanent_authority_service import save_authority as _pa_save_authority
        # Full records.json is a snapshot only; V151 row_shards are the durable row-level source. Keep full snapshot local-first to avoid full-file races on GitHub.
        _pa_save_authority("01_time_records", records={"time_records": merged}, reason=f"{reason}_01", github=False)
        _pa_save_authority("02_history", records={"time_records": merged}, reason=f"{reason}_02", github=bool(github))
        return int(len(merged))
    except Exception as exc:
        try:
            write_log("V151_CANONICAL_MERGE_ERROR", f"非破壞式合併 01/02 工時權威檔失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return 0


def _v151_filter_records_df(df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if start_date:
        if "start_date" in out.columns:
            out = out[out["start_date"].astype(str) >= str(start_date)]
        elif "start_timestamp" in out.columns:
            out = out[out["start_timestamp"].astype(str).str[:10] >= str(start_date)]
    if end_date:
        if "start_date" in out.columns:
            out = out[out["start_date"].astype(str) <= str(end_date)]
        elif "start_timestamp" in out.columns:
            out = out[out["start_timestamp"].astype(str).str[:10] <= str(end_date)]
    if employee_id and "employee_id" in out.columns:
        out = out[out["employee_id"].astype(str) == str(employee_id)]
    if work_order and "work_order" in out.columns:
        out = out[out["work_order"].astype(str) == str(work_order)]
    try:
        if "id" in out.columns:
            out["_v151_sort_id"] = pd.to_numeric(out["id"], errors="coerce")
            out = out.sort_values("_v151_sort_id", ascending=False, kind="stable").drop(columns=["_v151_sort_id"], errors="ignore")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v151_all_records_df() -> pd.DataFrame:
    rows = _v151_merge_rows(
        _v151_load_authority_rows("01_time_records"),
        _v151_load_authority_rows("02_history"),
        _v151_load_shard_rows(),
        _v151_sqlite_all_rows(),
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    base_df = pd.DataFrame()
    try:
        if callable(_v151_prev_load_records):
            base_df = _v151_prev_load_records(start_date, end_date, employee_id, work_order)
    except Exception:
        base_df = pd.DataFrame()
    all_rows = _v151_merge_rows(
        base_df if isinstance(base_df, pd.DataFrame) else pd.DataFrame(),
        _v151_load_authority_rows("01_time_records"),
        _v151_load_authority_rows("02_history"),
        _v151_load_shard_rows(),
        _v151_sqlite_all_rows(),
    )
    return _v151_filter_records_df(pd.DataFrame(all_rows), start_date, end_date, employee_id, work_order)


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    base_df = pd.DataFrame()
    try:
        if callable(_v151_prev_today_records):
            base_df = _v151_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only)
    except Exception:
        base_df = pd.DataFrame()
    rows = _v151_merge_rows(base_df, _v151_load_shard_rows(), _v151_sqlite_all_rows())
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if df.empty:
        return df
    try:
        cycle_start = _business_cycle_start_date() if "_business_cycle_start_date" in globals() else today_text()
    except Exception:
        cycle_start = today_text()
    def _is_active_row(r: dict) -> bool:
        return (not _v151_is_terminal(r)) and (_v151_text(r.get("end_timestamp")) == "") and (_v151_text(r.get("status")) in {"", "作業中"})
    active_mask = df.apply(lambda r: _is_active_row(dict(r)), axis=1)
    if unfinished_only:
        df = df.loc[active_mask].copy()
    else:
        if "start_date" in df.columns:
            current = df["start_date"].astype(str) >= str(cycle_start)
        elif "start_timestamp" in df.columns:
            current = df["start_timestamp"].astype(str).str[:10] >= str(cycle_start)
        else:
            current = pd.Series([True] * len(df), index=df.index)
        df = df.loc[current | active_mask].copy()
    return _v151_filter_records_df(df)


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if not callable(_v151_prev_start_work):
        raise RuntimeError("start_work core implementation is unavailable")
    rid = int(_v151_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)
    if rid:
        rows_df = _v151_query_rows_by_ids([rid])
        if isinstance(rows_df, pd.DataFrame) and not rows_df.empty:
            _v151_write_row_shards(rows_df, "start_work_v151_durable_row", github=True)
            _v151_save_canonical_non_destructive(rows_df, "start_work_v151_non_destructive_snapshot", github=False)
        try:
            clear_query_cache()
        except Exception:
            pass
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if not callable(_v151_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    before_ids: list[int] = []
    try:
        group = get_active_group(int(float(str(record_id).strip()))) if finish_parallel_group else pd.DataFrame()
        if isinstance(group, pd.DataFrame) and not group.empty and "id" in group.columns:
            before_ids = [int(float(str(x))) for x in group["id"].tolist() if _v151_text(x)]
    except Exception:
        before_ids = []
    if not before_ids:
        try:
            before_ids = [int(float(str(record_id).strip()))]
        except Exception:
            before_ids = []
    n = int(_v151_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)
    ids = before_ids or [record_id]
    rows_df = _v151_query_rows_by_ids(ids)
    if isinstance(rows_df, pd.DataFrame) and not rows_df.empty:
        _v151_write_row_shards(rows_df, "finish_work_v151_durable_row", github=True)
        _v151_save_canonical_non_destructive(rows_df, "finish_work_v151_non_destructive_snapshot", github=False)
    try:
        clear_query_cache()
    except Exception:
        pass
    return n


def sync_time_records_01_02_now(reason: str = "v151_manual_non_destructive_sync", *, github: bool = True) -> int:  # type: ignore[override]
    # Manual sync consolidates records + row_shards + SQLite into a safe snapshot. It never uses a smaller partial table to erase history.
    n = _v151_save_canonical_non_destructive(None, reason, github=bool(github))
    return int(n or 0)


def audit_time_record_integrity_v151() -> dict:
    """Diagnostic helper for 09/12/manual checks; no writes."""
    try:
        authority = _v151_merge_rows(_v151_load_authority_rows("01_time_records"), _v151_load_authority_rows("02_history"))
        shards = _v151_load_shard_rows()
        sqlite_rows = _v151_sqlite_all_rows()
        merged = _v151_merge_rows(authority, shards, sqlite_rows)
        return {
            "authority_rows": len(authority),
            "row_shards": len(shards),
            "sqlite_rows": len(sqlite_rows),
            "merged_rows": len(merged),
            "missing_from_authority_recoverable": max(0, len(merged) - len(authority)),
        }
    except Exception as exc:
        return {"error": str(exc)[:500]}

# =================== END V151 TIME RECORD DURABLE ROW SHARD + NON-DESTRUCTIVE MERGE ===================
