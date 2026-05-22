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
            append = (append + "；" if append else "") + f"同步作業平均分配：{len(group_ids)}筆，群組總工時={total_hours:.2f}，平均={avg_hours:.2f}"
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
        f"結束工時紀錄 #{record_id}，同步結束={len(group_ids)}筆，狀態={status}，群組總工時={total_hours:.2f}，平均工時={avg_hours:.2f}",
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
