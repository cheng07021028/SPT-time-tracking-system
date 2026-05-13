# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime, date
import uuid
import pandas as pd
from .db_service import execute, query_df, query_one
from .calculation_service import calculate_work_hours, split_timestamp
from .log_service import write_log


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def make_record_key(employee_id: str, work_order: str, process_name: str, start_ts: str) -> str:
    return f"{employee_id}|{work_order}|{process_name}|{start_ts}|{uuid.uuid4().hex[:8]}"


def get_active_record(employee_id: str) -> dict | None:
    return query_one(
        """
        SELECT * FROM time_records
        WHERE employee_id=? AND end_timestamp IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (employee_id,),
    )


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:
    now = _now()
    active = get_active_record(employee["employee_id"])
    if active and auto_pause_old:
        finish_work(active["id"], "暫停", "系統自動暫停：同一人員開始新的作業")

    start_date, start_time = split_timestamp(now)
    record_key = make_record_key(employee["employee_id"], work_order["work_order"], process_name, now)
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
            employee.get("employee_id"),
            employee.get("employee_name"),
            "開始",
            now,
            remark,
            start_date,
            start_time,
            work_order.get("assembly_location", ""),
            f"{work_order.get('work_order')}|{process_name}|{start_date}|{start_time[:5]}",
            0,
            "streamlit",
            now,
            now,
        ),
    )
    write_log("START_WORK", f"{employee.get('employee_name')} 開始 {work_order.get('work_order')} / {process_name}", "time_records", rid)
    return rid


def finish_work(record_id: int, end_action: str, remark: str = "") -> None:
    rec = query_one("SELECT * FROM time_records WHERE id=?", (record_id,))
    if not rec:
        raise ValueError("找不到工時紀錄")
    if rec.get("end_timestamp"):
        return
    now = _now()
    end_date, end_time = split_timestamp(now)
    hours = calculate_work_hours(rec["start_timestamp"], now)
    status = end_action if end_action in ("下班", "暫停", "完工") else "已結束"
    new_remark = rec.get("remark") or ""
    if remark:
        new_remark = (new_remark + "；" if new_remark else "") + remark
    execute(
        """
        UPDATE time_records
        SET status=?, end_action=?, end_timestamp=?, end_date=?, end_time=?, work_hours=?, remark=?, updated_at=?
        WHERE id=?
        """,
        (status, end_action, now, end_date, end_time, hours, new_remark, now, record_id),
    )
    write_log("END_WORK", f"結束工時紀錄 #{record_id}，狀態={status}，工時={hours}", "time_records", record_id)


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
