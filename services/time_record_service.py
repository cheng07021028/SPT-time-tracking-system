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


def _manual_refresh_timestamp() -> str | None:
    row = query_one("SELECT setting_value FROM app_settings WHERE setting_key='live_page_manual_refresh_timestamp'") or {}
    val = row.get("setting_value")
    return str(val).strip() if val else None


def _restore_hidden_reset_key() -> str | None:
    """Return the reset-cutoff key for which admin has restored hidden rows."""
    row = query_one("SELECT setting_value FROM app_settings WHERE setting_key='live_page_restore_hidden_reset_key'") or {}
    val = row.get("setting_value")
    return str(val).strip() if val else None


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


# ===== V18.0 refresh latest time-record memory after history edits/deletes =====
# 目的：02 歷史紀錄刪除/儲存後立即刷新 01/02 latest 記憶檔，避免 Reboot 後舊資料復活。
_V18_ORIGINAL_SAVE_TIME_RECORDS = save_time_records
_V18_ORIGINAL_DELETE_TIME_RECORDS = delete_time_records


def _v18_refresh_time_records_latest(reason: str = "time_records_changed") -> None:
    try:
        from services.time_records_guard_service import mirror_time_records_to_module_files
        rows_df = query_df("SELECT * FROM time_records ORDER BY id")
        rows = rows_df.where(pd.notna(rows_df), "").to_dict(orient="records") if rows_df is not None and not rows_df.empty else []
        # 空表也是有效狀態：若使用者刪到 0 筆，要寫入空 latest，避免 Reboot 從舊檔救回。
        if not rows:
            try:
                import json
                from pathlib import Path
                from services.time_records_guard_service import PERSIST_ROOT, CANONICAL_01, HISTORY_02, now_text
                payload = {"schema_version": "V18-empty-valid", "exported_at": now_text(), "reason": reason, "tables": {"time_records": []}, "counts": {"time_records": 0}}
                for code, zh, en in [(CANONICAL_01, "工時紀錄", "Time Records"), (HISTORY_02, "歷史紀錄", "History")]:
                    p = PERSIST_ROOT / code / f"{code}_records.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_suffix(p.suffix + ".tmp")
                    data = dict(payload); data.update({"module_code": code, "module_name_zh": zh, "module_name_en": en})
                    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    tmp.replace(p)
            except Exception:
                pass
        else:
            mirror_time_records_to_module_files(rows, reason=reason)
        try:
            from services.permanent_write_through_service import write_through_paths
            from services.time_records_guard_service import PERSIST_ROOT, CANONICAL_01, HISTORY_02
            write_through_paths([
                PERSIST_ROOT / CANONICAL_01 / f"{CANONICAL_01}_records.json",
                PERSIST_ROOT / HISTORY_02 / f"{HISTORY_02}_records.json",
            ], reason=reason)
        except Exception:
            pass
    except Exception:
        pass


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    count = _V18_ORIGINAL_SAVE_TIME_RECORDS(df, recalc_edited_timestamps=recalc_edited_timestamps)
    if count:
        clear_query_cache()
        _v18_refresh_time_records_latest("save_time_records_v18")
    return count


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    count = _V18_ORIGINAL_DELETE_TIME_RECORDS(record_ids, reason=reason)
    # 即使 count=0 也刷新一次 latest，避免畫面與檔案狀態不一致。
    clear_query_cache()
    _v18_refresh_time_records_latest("delete_time_records_v18")
    return count

# ===== V20.0 immediate 01-to-02 history sync patch START =====
# 目的：01｜工時紀錄按「開始/結束」後，02｜歷史紀錄與 01/02 latest JSON 立刻同步，
# 不需要等待其他頁面觸發匯出，也避免 Reboot 後讀回舊 latest。
try:
    _V20_ORIGINAL_START_WORK = start_work  # type: ignore[name-defined]
    _V20_ORIGINAL_FINISH_WORK = finish_work  # type: ignore[name-defined]
except Exception:
    _V20_ORIGINAL_START_WORK = None  # type: ignore[assignment]
    _V20_ORIGINAL_FINISH_WORK = None  # type: ignore[assignment]


def _v20_refresh_after_time_action(reason: str) -> None:
    try:
        clear_query_cache()
    except Exception:
        pass
    try:
        _v18_refresh_time_records_latest(reason)
    except Exception:
        pass


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    if _V20_ORIGINAL_START_WORK is None:
        raise RuntimeError("start_work original function is not available")
    rid = _V20_ORIGINAL_START_WORK(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old)
    _v20_refresh_after_time_action("start_work_v20_immediate_history_sync")
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    if _V20_ORIGINAL_FINISH_WORK is None:
        raise RuntimeError("finish_work original function is not available")
    count = _V20_ORIGINAL_FINISH_WORK(record_id, end_action, remark, finish_parallel_group=finish_parallel_group)
    _v20_refresh_after_time_action("finish_work_v20_immediate_history_sync")
    return count
# ===== V20.0 immediate 01-to-02 history sync patch END =====
