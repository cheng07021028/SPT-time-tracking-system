# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, date
import sqlite3
import uuid
import pandas as pd

from .db_service import DB_PATH, clear_query_cache, execute, mark_data_changed, query_df, query_one
from .calculation_service import calculate_work_hours, split_timestamp
from .log_service import write_log
from .duration_service import hms_to_hours


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def make_record_key(employee_id: str, work_order: str, process_name: str, start_ts: str) -> str:
    return f"{employee_id}|{work_order}|{process_name}|{start_ts}|{uuid.uuid4().hex[:8]}"


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM time_records WHERE end_timestamp IS NULL"
    params: list[str] = []
    if employee_id:
        sql += " AND employee_id=?"
        params.append(employee_id)
    if process_name:
        sql += " AND process_name=?"
        params.append(process_name)
    if start_date:
        sql += " AND start_date=?"
        params.append(start_date)
    sql += " ORDER BY employee_id, process_name, start_timestamp, id"
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
        process_name=rec.get("process_name"),
        start_date=rec.get("start_date"),
    )


def _pause_conflicting_active_records(employee_id: str, process_name: str, start_date: str) -> int:
    """Same employee may run parallel records only within same day + same process.

    When starting a different process/day, close all other active records as paused.
    """
    active = get_active_records(employee_id=employee_id)
    if active.empty:
        return 0
    conflict = active[(active["process_name"].astype(str) != str(process_name)) | (active["start_date"].astype(str) != str(start_date))]
    closed = 0
    for _, row in conflict.iterrows():
        finish_work(int(row["id"]), "暫停", "系統自動暫停：同一人員切換不同工段或不同日期作業", finish_parallel_group=True)
        closed += 1
    return closed


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:
    now = _now()
    start_date, start_time = split_timestamp(now)
    employee_id = employee.get("employee_id")

    # V1.3 規則：同一人、同一天、同一工段可以同時多筆製令計時；不同工段才自動暫停舊作業。
    if auto_pause_old:
        _pause_conflicting_active_records(employee_id, process_name, start_date)

    record_key = make_record_key(employee_id, work_order.get("work_order"), process_name, now)
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
            work_order.get("work_order"),
            work_order.get("part_no", ""),
            work_order.get("type_name", ""),
            process_name,
            employee_id,
            employee.get("employee_name"),
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

    parallel = get_active_records(employee_id=employee_id, process_name=process_name, start_date=start_date)
    if len(parallel) > 1:
        execute(
            "UPDATE time_records SET is_group_work=1, group_key=?, updated_at=? WHERE employee_id=? AND process_name=? AND start_date=? AND end_timestamp IS NULL",
            (group_key, now, employee_id, process_name, start_date),
        )
    write_log("START_WORK", f"{employee.get('employee_name')} 開始 {work_order.get('work_order')} / {process_name}", "time_records", rid)
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


def today_records() -> pd.DataFrame:
    return load_records(date.today().strftime("%Y-%m-%d"), date.today().strftime("%Y-%m-%d"))


def save_time_records(df: pd.DataFrame) -> int:
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
        vals = []
        for c in update_cols:
            v = r.get(c, "")
            if pd.isna(v):
                v = None
            if c == "work_hours" and v is not None:
                # UI displays 00:00:00, database keeps decimal hours for calculation.
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
    write_log("SAVE_TIME_RECORDS", f"人工編輯並儲存工時紀錄 {count} 筆", "time_records")
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
            hours = calculate_work_hours(str(start_ts), str(end_ts))
            start_date, start_time = split_timestamp(str(start_ts))
            end_date, end_time = split_timestamp(str(end_ts))
            status = r.get("status") or "已結束"
            if str(status) == "作業中":
                status = r.get("end_action") or "已結束"
            updates.append((hours, start_date, start_time, end_date, end_time, status, now, int(r["id"])))
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
                SET work_hours=?, start_date=?, start_time=?, end_date=?, end_time=?, status=?, updated_at=?
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
