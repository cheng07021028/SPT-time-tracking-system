# ===================== V163 DAILY CLOSE LOCK GUARD =====================
# Purpose:
# - If a work date has been daily-closed in 14. 資料健康檢查中心, block accidental
#   future modifications to that date.
# - This protects closed history from being overwritten, deleted, recalculated,
#   imported over, or newly appended after daily settlement.
# - Reopen the date from 14 before making administrative corrections.

try:
    from services.daily_close_service import (
        assert_work_date_open as _v163_assert_work_date_open,
        assert_dataframe_dates_open as _v163_assert_dataframe_dates_open,
    )
except Exception:  # pragma: no cover
    _v163_assert_work_date_open = None  # type: ignore
    _v163_assert_dataframe_dates_open = None  # type: ignore


def _v163_date_from_timestamp_or_today(ts_value=None):
    try:
        if ts_value:
            return split_timestamp(str(ts_value))[0]
    except Exception:
        pass
    try:
        return today_text()
    except Exception:
        return ""


def _v163_row_date(row) -> str:
    try:
        for c in ("start_date", "work_date", "日期 / Date", "開始日期 / Start Date", "日期"):
            v = row.get(c) if hasattr(row, "get") else None
            if v is not None and str(v).strip() and str(v).strip().lower() not in {"nan", "none", "nat", "null"}:
                s = str(v).strip().replace("/", "-")
                if len(s) >= 10:
                    return s[:10]
        for c in ("start_timestamp", "Start Timestamp", "開始時間戳 / Start Timestamp", "created_at"):
            v = row.get(c) if hasattr(row, "get") else None
            if v is not None and str(v).strip() and str(v).strip().lower() not in {"nan", "none", "nat", "null"}:
                return str(v).strip().replace("/", "-")[:10]
    except Exception:
        pass
    return ""


def _v163_assert_date_open(d: str, operation: str) -> None:
    if _v163_assert_work_date_open is None:
        return
    if d:
        _v163_assert_work_date_open(d, operation=operation)


def _v163_assert_df_open(df, operation: str) -> None:
    if _v163_assert_dataframe_dates_open is not None:
        _v163_assert_dataframe_dates_open(df, operation=operation)
        return
    try:
        dates = []
        for _, r in df.iterrows():
            d = _v163_row_date(r)
            if d and d not in dates:
                dates.append(d)
        for d in dates:
            _v163_assert_date_open(d, operation)
    except Exception:
        pass


def _v163_records_df_by_ids(record_ids):
    ids = []
    for x in record_ids or []:
        try:
            i = int(float(str(x).strip()))
            if i > 0 and i not in ids:
                ids.append(i)
        except Exception:
            continue
    if not ids:
        return pd.DataFrame()
    try:
        ph = ",".join(["?"] * len(ids))
        return query_df(f"SELECT * FROM time_records WHERE id IN ({ph})", ids)
    except Exception:
        rows = []
        for rid in ids:
            try:
                r = query_one("SELECT * FROM time_records WHERE id=?", (rid,)) or {}
                if r:
                    rows.append(r)
            except Exception:
                pass
        return pd.DataFrame(rows)


try:
    _v163_prev_start_work = start_work
except Exception:  # pragma: no cover
    _v163_prev_start_work = None


def start_work(employee: dict, work_order: dict, process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:  # type: ignore[override]
    # New work is dated by the current Taiwan timestamp.
    try:
        d, _t = split_timestamp(_now())
    except Exception:
        d = _v163_date_from_timestamp_or_today()
    _v163_assert_date_open(d, "開始作業 / START_WORK")
    if not callable(_v163_prev_start_work):
        raise RuntimeError("start_work core implementation is unavailable")
    return int(_v163_prev_start_work(employee, work_order, process_name, remark, auto_pause_old=auto_pause_old) or 0)


try:
    _v163_prev_finish_work = finish_work
except Exception:  # pragma: no cover
    _v163_prev_finish_work = None


def finish_work(record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:  # type: ignore[override]
    try:
        rid = int(float(str(record_id).strip()))
    except Exception:
        rid = record_id
    try:
        # Protect every active group row that may be ended together.
        group = get_active_group(rid) if finish_parallel_group else _v163_records_df_by_ids([rid])
        if group is None or not isinstance(group, pd.DataFrame) or group.empty:
            group = _v163_records_df_by_ids([rid])
        _v163_assert_df_open(group, f"{end_action} / FINISH_WORK")
    except ValueError:
        raise
    except Exception:
        # If protection check cannot inspect the group, still check the selected row.
        _v163_assert_df_open(_v163_records_df_by_ids([rid]), f"{end_action} / FINISH_WORK")
    if not callable(_v163_prev_finish_work):
        raise RuntimeError("finish_work core implementation is unavailable")
    return int(_v163_prev_finish_work(record_id, end_action, remark, finish_parallel_group=finish_parallel_group) or 0)


try:
    _v163_prev_save_time_records = save_time_records
except Exception:  # pragma: no cover
    _v163_prev_save_time_records = None


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    _v163_assert_df_open(df, "人工儲存工時 / SAVE_TIME_RECORDS")
    if not callable(_v163_prev_save_time_records):
        return 0
    return int(_v163_prev_save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps) or 0)


try:
    _v163_prev_delete_time_records = delete_time_records
except Exception:  # pragma: no cover
    _v163_prev_delete_time_records = None


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    _v163_assert_df_open(_v163_records_df_by_ids(record_ids), "刪除工時 / DELETE_TIME_RECORDS")
    if not callable(_v163_prev_delete_time_records):
        return 0
    return int(_v163_prev_delete_time_records(record_ids, reason=reason) or 0)


try:
    _v163_prev_recalculate_time_records = recalculate_time_records
except Exception:  # pragma: no cover
    _v163_prev_recalculate_time_records = None


def recalculate_time_records(record_ids: list[int] | None = None) -> int:  # type: ignore[override]
    if record_ids:
        target = _v163_records_df_by_ids(record_ids)
    else:
        try:
            target = query_df("SELECT * FROM time_records WHERE start_timestamp IS NOT NULL AND end_timestamp IS NOT NULL")
        except Exception:
            target = pd.DataFrame()
    _v163_assert_df_open(target, "重新計算工時 / RECALCULATE_TIME_RECORDS")
    if not callable(_v163_prev_recalculate_time_records):
        return 0
    return int(_v163_prev_recalculate_time_records(record_ids) or 0)


try:
    _v163_prev_import_time_records = import_time_records
except Exception:  # pragma: no cover
    _v163_prev_import_time_records = None


def import_time_records(df: pd.DataFrame, recalc: bool = True, source: str = "history_import") -> dict:  # type: ignore[override]
    _v163_assert_df_open(df, "匯入工時 / IMPORT_TIME_RECORDS")
    if not callable(_v163_prev_import_time_records):
        return {"inserted": 0, "updated": 0, "skipped": 0, "errors": ["import_time_records core implementation is unavailable"]}
    return _v163_prev_import_time_records(df, recalc=recalc, source=source)

# =================== END V163 DAILY CLOSE LOCK GUARD =====================
