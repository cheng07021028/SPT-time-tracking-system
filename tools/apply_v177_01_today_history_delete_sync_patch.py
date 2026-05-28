# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "time_record_service.py"
PAGE_CANDIDATES = [
    ROOT / "pages" / "01_01. 工時紀錄.py",
    ROOT / "pages" / "01_01. #U5de5#U6642#U7d00#U9304.py",
]
MARKER = "# ===================== V177 01 TODAY/HISTORY DELETE SYNC AUTHORITY FIX ====================="
PATCH = r'''
# ===================== V177 01 TODAY/HISTORY DELETE SYNC AUTHORITY FIX =====================
# 目的：
# 1) 01 今日工時紀錄 / Today Records 必須與 02 歷史紀錄 / Editable History 使用同一份 02_history canonical。
# 2) 01 管理員工時紀錄維護的刪除、存檔，必須同步 01_time_records / 02_history / SQLite 快取。
# 3) 02 已刪除的資料不得再因 SQLite、event journal、row shard 或顯示快取回到 01。
# 4) 不改畫面、不改 CSS、不改 theme、不改表格渲染、不重新編號 ID。

try:
    _v177_prev_save_time_records = save_time_records
except Exception:  # pragma: no cover
    _v177_prev_save_time_records = None
try:
    _v177_prev_delete_time_records = delete_time_records
except Exception:  # pragma: no cover
    _v177_prev_delete_time_records = None
try:
    _v177_prev_today_records = today_records
except Exception:  # pragma: no cover
    _v177_prev_today_records = None
try:
    _v177_prev_load_records = load_records
except Exception:  # pragma: no cover
    _v177_prev_load_records = None

_V177_UI_COLS = {
    "刪除", "刪除 / Delete", "Delete", "重算", "重算 / Recalc", "Recalc",
    "選取", "Select", "selected", "__selected__", "_selected", "_row_selected",
}
_V177_TERMINAL_STATUS = {"下班", "暫停", "完工", "已結束", "結束", "Off Duty", "Pause", "Complete", "Finished"}


def _v177_now_text() -> str:
    try:
        return _now() if "_now" in globals() else now_text()
    except Exception:
        try:
            from services.timezone_service import now_text as _tz_now_text
            return _tz_now_text()
        except Exception:
            from datetime import datetime as _dt
            return _dt.now().strftime("%Y-%m-%d %H:%M:%S")


def _v177_blank(v) -> bool:
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return v is None or str(v).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v177_text(v) -> str:
    if _v177_blank(v):
        return ""
    try:
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(v, date):
            return v.strftime("%Y-%m-%d")
    except Exception:
        pass
    return str(v).strip()


def _v177_int(v):
    if _v177_blank(v):
        return None
    try:
        i = int(float(str(v).strip()))
        return i if i > 0 else None
    except Exception:
        return None


def _v177_checked(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on", "是", "勾選", "checked"}
    return bool(v)


def _v177_clean_df(df) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    try:
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    except Exception:
        pass
    drop = [c for c in out.columns if str(c).strip() in _V177_UI_COLS]
    if drop:
        out = out.drop(columns=drop, errors="ignore")
    try:
        out = out.where(pd.notna(out), "")
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v177_table_rows(df: pd.DataFrame) -> list[dict]:
    clean = _v177_clean_df(df)
    try:
        from services.permanent_authority_service import table_from_df as _pa_table_from_df
        return _pa_table_from_df(clean)
    except Exception:
        try:
            return clean.to_dict(orient="records")
        except Exception:
            return []


def _v177_authority_df(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table as _pa_df_from_table
        df = _pa_df_from_table(module_key, "time_records")
        if isinstance(df, pd.DataFrame):
            return _v177_clean_df(df)
    except Exception:
        pass
    # fallback：相容舊 helper
    for fn_name in ("_v175_authority_df", "_v137_authority_df", "_v134_authority_df", "_v98_authority_df", "_v96_fast_authority_df", "_v89_authority_df"):
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                df = fn(module_key)
                if isinstance(df, pd.DataFrame):
                    return _v177_clean_df(df)
        except Exception:
            pass
    return pd.DataFrame()


def _v177_history_settings() -> dict:
    try:
        from services.permanent_authority_service import load_settings as _pa_load_settings
        data = _pa_load_settings("02_history")
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        try:
            return _v94_history_settings() if "_v94_history_settings" in globals() else {}
        except Exception:
            return {}


def _v177_save_history_settings(settings: dict, reason: str = "v177_history_settings") -> None:
    try:
        from services.permanent_authority_service import save_settings as _pa_save_settings
        _pa_save_settings("02_history", settings or {}, reason=reason, github=False)
    except Exception:
        try:
            if "_v94_save_history_settings" in globals():
                _v94_save_history_settings(settings or {}, reason)
        except Exception:
            pass


def _v177_tombstones() -> tuple[set[int], set[str]]:
    try:
        stg = _v177_history_settings()
        ids: set[int] = set()
        keys: set[str] = set()
        for x in stg.get("deleted_record_ids", []) if isinstance(stg.get("deleted_record_ids", []), list) else []:
            i = _v177_int(x)
            if i is not None:
                ids.add(i)
        for x in stg.get("deleted_record_keys", []) if isinstance(stg.get("deleted_record_keys", []), list) else []:
            s = str(x or "").strip()
            if s:
                keys.add(s)
        return ids, keys
    except Exception:
        return set(), set()


def _v177_id_col(df: pd.DataFrame) -> str:
    for c in ("id", "ID", "ID / ID", "ID / ID / ID", "紀錄編號", "record_id"):
        if c in df.columns:
            return c
    return ""


def _v177_value_from(row: dict, *cols: str) -> str:
    for c in cols:
        if c in row and not _v177_blank(row.get(c)):
            return _v177_text(row.get(c))
    return ""


def _v177_record_key(row: dict) -> str:
    direct = _v177_value_from(row, "record_key", "紀錄鍵 / Record Key", "Record Key")
    if direct:
        return direct
    emp_id = _v177_value_from(row, "employee_id", "工號", "工號 / Employee ID", "Employee ID")
    emp_name = _v177_value_from(row, "employee_name", "姓名", "姓名 / Name", "Name")
    wo = _v177_value_from(row, "work_order", "製令", "製令 / Work Order", "Work Order")
    proc = _v177_value_from(row, "process_name", "工段", "工段 / Process", "Process")
    start_ts = _v177_value_from(row, "start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp")
    if not start_ts:
        sd = _v177_value_from(row, "start_date", "開始日期 / Start Date", "開始日期")
        stime = _v177_value_from(row, "start_time", "開始時刻 / Start Time", "開始時刻")
        start_ts = (sd + " " + stime).strip()
    parts = [emp_id, emp_name, wo, proc, start_ts]
    return "|".join(parts) if any(parts) else ""


def _v177_row_date(row: dict) -> str:
    for c in ("start_date", "開始日期 / Start Date", "開始日期", "work_date", "日期"):
        if c in row and not _v177_blank(row.get(c)):
            return _v177_text(row.get(c))[:10]
    for c in ("start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp", "開始時間"):
        if c in row and not _v177_blank(row.get(c)):
            return _v177_text(row.get(c))[:10]
    return ""


def _v177_is_terminal(row: dict) -> bool:
    status = _v177_value_from(row, "status", "狀態 / Status", "狀態")
    end_ts = _v177_value_from(row, "end_timestamp", "結束時間戳 / End Timestamp", "結束時間 / End Timestamp", "結束時間")
    end_date = _v177_value_from(row, "end_date", "結束日期 / End Date", "結束日期")
    end_time = _v177_value_from(row, "end_time", "結束時刻 / End Time", "結束時刻")
    return status in _V177_TERMINAL_STATUS or bool(end_ts) or bool(end_date and end_time)


def _v177_is_active(row: dict) -> bool:
    status = _v177_value_from(row, "status", "狀態 / Status", "狀態")
    if status and status != "作業中":
        return False
    return not _v177_is_terminal(row)


def _v177_filter_tombstones(df: pd.DataFrame) -> pd.DataFrame:
    out = _v177_clean_df(df)
    if out.empty:
        return out
    ids, keys = _v177_tombstones()
    if not ids and not keys:
        return out
    mask = pd.Series([True] * len(out), index=out.index)
    id_col = _v177_id_col(out)
    if id_col and ids:
        mask &= ~out[id_col].map(lambda x: (_v177_int(x) in ids))
    if keys:
        row_keys = out.apply(lambda r: _v177_record_key(dict(r)), axis=1)
        mask &= ~row_keys.astype(str).str.strip().isin(keys)
    return out.loc[mask].copy().reset_index(drop=True)


def _v177_sort(df: pd.DataFrame) -> pd.DataFrame:
    out = _v177_clean_df(df)
    if out.empty:
        return out
    try:
        if "start_timestamp" in out.columns:
            out["_v177_ts"] = pd.to_datetime(out["start_timestamp"], errors="coerce")
        id_col = _v177_id_col(out)
        if id_col:
            out["_v177_id"] = pd.to_numeric(out[id_col], errors="coerce")
        sort_cols = [c for c in ("_v177_ts", "_v177_id") if c in out.columns]
        if sort_cols:
            out = out.sort_values(sort_cols, ascending=[False] * len(sort_cols), kind="stable")
    except Exception:
        pass
    return out.drop(columns=["_v177_ts", "_v177_id"], errors="ignore").reset_index(drop=True)


def _v177_save_0102(df: pd.DataFrame, reason: str, *, github: bool = False) -> int:
    safe = _v177_filter_tombstones(df)
    rows = _v177_table_rows(_v177_sort(safe))
    try:
        from services.permanent_authority_service import save_authority as _pa_save_authority
        _pa_save_authority("01_time_records", records={"time_records": rows}, reason=reason + "_01", github=bool(github))
        _pa_save_authority("02_history", records={"time_records": rows}, reason=reason + "_02", github=bool(github))
    except Exception as exc:
        try:
            write_log("V177_AUTHORITY_SAVE_ERROR", f"V177 01/02 權威檔同步失敗：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
    try:
        _v177_sync_sqlite_from_authority(safe)
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


def _v177_existing_sqlite_cols() -> list[str]:
    try:
        rows = query_df("PRAGMA table_info(time_records)")
        if isinstance(rows, pd.DataFrame) and not rows.empty and "name" in rows.columns:
            return [str(x) for x in rows["name"].tolist() if str(x)]
    except Exception:
        pass
    return []


def _v177_sync_sqlite_from_authority(df: pd.DataFrame) -> int:
    cols = _v177_existing_sqlite_cols()
    if not cols:
        return 0
    clean = _v177_filter_tombstones(df)
    for c in cols:
        if c not in clean.columns:
            clean[c] = None
    clean = clean[cols].where(pd.notna(clean[cols]), None)
    rows = clean.to_dict(orient="records")
    import sqlite3 as _sqlite3
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    conn = _sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN")
        conn.execute("DELETE FROM time_records")
        if rows:
            quoted = ",".join([f'"{c}"' for c in cols])
            placeholders = ",".join(["?"] * len(cols))
            sql = f"INSERT INTO time_records ({quoted}) VALUES ({placeholders})"
            conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
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


def _v177_history_df() -> pd.DataFrame:
    hist = _v177_filter_tombstones(_v177_authority_df("02_history"))
    if isinstance(hist, pd.DataFrame) and not hist.empty:
        return _v177_sort(hist)
    # 只有 02 權威檔完全空時，才用 01 fallback；但仍套 tombstone。
    live = _v177_filter_tombstones(_v177_authority_df("01_time_records"))
    return _v177_sort(live)


def _v177_apply_filters(df: pd.DataFrame, start_date=None, end_date=None, employee_id=None, work_order=None) -> pd.DataFrame:
    out = _v177_filter_tombstones(df)
    if out.empty:
        return out
    if start_date:
        dates = out.apply(lambda r: _v177_row_date(dict(r)), axis=1)
        out = out.loc[dates.astype(str) >= str(start_date)[:10]].copy()
    if end_date:
        dates = out.apply(lambda r: _v177_row_date(dict(r)), axis=1)
        out = out.loc[dates.astype(str) <= str(end_date)[:10]].copy()
    if employee_id:
        emp_cols = [c for c in ("employee_id", "工號", "工號 / Employee ID", "Employee ID") if c in out.columns]
        if emp_cols:
            mask = pd.Series([False] * len(out), index=out.index)
            for c in emp_cols:
                mask = mask | out[c].astype(str).str.strip().eq(str(employee_id).strip())
            out = out.loc[mask].copy()
    if work_order:
        wo_cols = [c for c in ("work_order", "製令", "製令 / Work Order", "Work Order") if c in out.columns]
        if wo_cols:
            mask = pd.Series([False] * len(out), index=out.index)
            for c in wo_cols:
                mask = mask | out[c].astype(str).str.strip().eq(str(work_order).strip())
            out = out.loc[mask].copy()
    return _v177_sort(out)


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None) -> pd.DataFrame:  # type: ignore[override]
    """V177: 02 Editable History authority is the visible source of truth."""
    df = _v177_history_df()
    return _v177_apply_filters(df, start_date=start_date, end_date=end_date, employee_id=employee_id, work_order=work_order)


def today_records(include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:  # type: ignore[override]
    """V177: 01 Today Records mirrors 02 Editable History and never resurrects deleted rows."""
    df = _v177_history_df()
    if df.empty:
        return pd.DataFrame()
    try:
        cycle_start = _business_cycle_start_date() if "_business_cycle_start_date" in globals() else today_text()
    except Exception:
        cycle_start = today_text() if "today_text" in globals() else _v177_now_text()[:10]
    rows = []
    for _, rr in df.iterrows():
        r = dict(rr)
        active = _v177_is_active(r)
        if unfinished_only or not include_finished:
            if active:
                rows.append(r)
            continue
        row_date = _v177_row_date(r)
        if active or (row_date and row_date >= str(cycle_start)[:10]):
            rows.append(r)
    if not rows:
        return pd.DataFrame(columns=list(df.columns))
    return _v177_sort(pd.DataFrame(rows))


def save_time_records(df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:  # type: ignore[override]
    """V177: merge editor rows into 02 canonical, then mirror 01 and SQLite cache."""
    edit = _v177_clean_df(df)
    if edit.empty:
        return 0
    # Keep existing calculation normalization if available, but do not let older wrappers replace authority with partial data.
    if recalc_edited_timestamps:
        try:
            normalized_rows = []
            for _, rr in edit.iterrows():
                row = dict(rr)
                fn = globals().get("normalize_record_datetime_fields")
                if callable(fn):
                    row = fn(row, recalc_work_hours=True)
                normalized_rows.append(row)
            edit = pd.DataFrame(normalized_rows)
        except Exception:
            pass
    auth = _v177_history_df()
    if auth.empty:
        auth = pd.DataFrame(columns=list(edit.columns))
    all_cols: list[str] = []
    for c in list(auth.columns) + list(edit.columns):
        sc = str(c)
        if sc not in all_cols:
            all_cols.append(sc)
    if "id" not in all_cols:
        all_cols.insert(0, "id")
    for c in all_cols:
        if c not in auth.columns:
            auth[c] = ""
        if c not in edit.columns:
            edit[c] = ""
    auth = auth[all_cols].copy()
    edit = edit[all_cols].copy()

    id_col = _v177_id_col(auth) or "id"
    by_id: dict[int, int] = {}
    by_key: dict[str, int] = {}
    if id_col in auth.columns:
        for idx, val in auth[id_col].items():
            rid = _v177_int(val)
            if rid is not None:
                by_id[rid] = idx
    for idx, rr in auth.iterrows():
        k = _v177_record_key(dict(rr))
        if k:
            by_key[k] = idx
    try:
        next_id = int(pd.to_numeric(auth[id_col], errors="coerce").max()) + 1 if id_col in auth.columns and not auth.empty else 1
    except Exception:
        next_id = 1
    updated = 0
    for _, rr in edit.iterrows():
        row = dict(rr)
        rid = _v177_int(row.get(id_col)) or _v177_int(row.get("id")) or _v177_int(row.get("ID")) or _v177_int(row.get("ID / ID"))
        key = _v177_record_key(row)
        idx = by_id.get(rid) if rid is not None else None
        if idx is None and key:
            idx = by_key.get(key)
        if idx is None:
            if rid is None:
                rid = next_id
                next_id += 1
            row["id"] = rid
            if id_col != "id":
                row[id_col] = rid
            new_row = {c: row.get(c, "") for c in auth.columns}
            auth = pd.concat([auth, pd.DataFrame([new_row])], ignore_index=True)
            idx = int(auth.index[-1])
            by_id[int(rid)] = idx
            if key:
                by_key[key] = idx
        else:
            for c, v in row.items():
                if c not in auth.columns:
                    auth[c] = ""
                auth.at[idx, c] = v
        if "updated_at" in auth.columns:
            auth.at[idx, "updated_at"] = _v177_now_text()
        updated += 1
    _v177_save_0102(auth, "save_time_records_v177_01_02_consistent", github=False)
    try:
        write_log("SAVE_TIME_RECORDS", f"V177 已儲存/更新 {updated} 筆，01 Today Records 與 02 Editable History 已同步。", "time_records")
    except Exception:
        pass
    return int(updated)


def _v177_add_tombstones(deleted_df: pd.DataFrame, ids: set[int], keys: set[str]) -> None:
    if deleted_df is not None and isinstance(deleted_df, pd.DataFrame) and not deleted_df.empty:
        id_col = _v177_id_col(deleted_df)
        for _, rr in deleted_df.iterrows():
            row = dict(rr)
            if id_col:
                i = _v177_int(row.get(id_col))
                if i is not None:
                    ids.add(i)
            k = _v177_record_key(row)
            if k:
                keys.add(k)
    stg = _v177_history_settings()
    old_ids, old_keys = _v177_tombstones()
    ids |= old_ids
    keys |= old_keys
    stg["deleted_record_ids"] = sorted(ids)
    stg["deleted_record_keys"] = sorted(keys)
    stg["delete_tombstone_updated_at"] = _v177_now_text()
    _v177_save_history_settings(stg, "delete_tombstone_v177")


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    """V177: delete from 02 canonical first, then mirror 01 and SQLite.

    This intentionally does not call older event-journal merge delete wrappers because
    those layers can re-merge old SQLite/event rows into display.  Event proof is still
    written as LOG before final save when possible.
    """
    ids = {i for i in (_v177_int(x) for x in (record_ids or [])) if i is not None}
    if not ids:
        return 0
    auth = _v177_history_df()
    if auth.empty:
        return 0
    id_col = _v177_id_col(auth)
    if not id_col:
        return 0
    id_series = auth[id_col].map(_v177_int)
    delete_mask = id_series.map(lambda x: x in ids)
    deleted_df = auth.loc[delete_mask].copy()
    if deleted_df.empty:
        return 0
    keys = {k for k in deleted_df.apply(lambda r: _v177_record_key(dict(r)), axis=1).tolist() if str(k).strip()}
    _v177_add_tombstones(deleted_df, set(ids), set(keys))
    remaining = auth.loc[~delete_mask].copy().reset_index(drop=True)
    _v177_save_0102(remaining, "delete_time_records_v177_01_02_consistent", github=False)
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：V177 已刪除 {len(deleted_df)} 筆，01 Today Records / 02 Editable History / SQLite 快取同步完成。", "time_records", target_id=",".join(str(x) for x in sorted(ids)), level="WARN")
    except Exception:
        pass
    return int(len(deleted_df))


def delete_time_records_from_editor_df(editor_df: pd.DataFrame, delete_column: str = "刪除 / Delete", reason: str = "01 管理員維護表刪除") -> int:
    """Fallback for 01 admin editor when Streamlit checkbox delta exists but ID list was not captured.

    The page can call this if delete_time_records(checked_ids) returns 0.
    It resolves selected rows by id first, then record_key/business key.
    """
    df = editor_df.copy() if isinstance(editor_df, pd.DataFrame) else pd.DataFrame()
    if df.empty or delete_column not in df.columns:
        return 0
    selected = df.loc[df[delete_column].map(_v177_checked)].copy()
    if selected.empty:
        return 0
    id_col = _v177_id_col(selected)
    ids = []
    if id_col:
        for x in selected[id_col].tolist():
            i = _v177_int(x)
            if i is not None and i not in ids:
                ids.append(i)
    count = delete_time_records(ids, reason=reason) if ids else 0
    if count:
        return count

    # Key-based delete fallback.
    auth = _v177_history_df()
    if auth.empty:
        return 0
    target_keys = {_v177_record_key(dict(r)) for _, r in selected.iterrows()}
    target_keys = {k for k in target_keys if str(k).strip()}
    if not target_keys:
        return 0
    auth_keys = auth.apply(lambda r: _v177_record_key(dict(r)), axis=1)
    mask = auth_keys.astype(str).str.strip().isin(target_keys)
    deleted_df = auth.loc[mask].copy()
    if deleted_df.empty:
        return 0
    id_col_auth = _v177_id_col(deleted_df)
    ids2 = set()
    if id_col_auth:
        ids2 = {i for i in (deleted_df[id_col_auth].map(_v177_int).tolist()) if i is not None}
    _v177_add_tombstones(deleted_df, ids2, set(target_keys))
    remaining = auth.loc[~mask].copy().reset_index(drop=True)
    _v177_save_0102(remaining, "delete_time_records_from_editor_df_v177", github=False)
    try:
        write_log("DELETE_TIME_RECORDS", f"{reason}：V177 已依 record_key/business key 刪除 {len(deleted_df)} 筆，01/02 已同步。", "time_records", level="WARN")
    except Exception:
        pass
    return int(len(deleted_df))


def sync_time_records_01_02_now(reason: str = "v177_manual_sync_02_to_01", *, github: bool = True) -> int:  # type: ignore[override]
    df = _v177_history_df()
    return _v177_save_0102(df, reason, github=bool(github))
# =================== END V177 01 TODAY/HISTORY DELETE SYNC AUTHORITY FIX ===================
'''


def patch_service() -> None:
    if not SERVICE.exists():
        raise FileNotFoundError(SERVICE)
    text = SERVICE.read_text(encoding="utf-8")
    if MARKER in text:
        print("V177 service patch already applied.")
        return
    backup = SERVICE.with_suffix(SERVICE.suffix + ".v177.bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    SERVICE.write_text(text.rstrip() + "\n\n" + PATCH + "\n", encoding="utf-8")
    print(f"Applied V177 service patch: {SERVICE}")


def patch_page(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "delete_time_records_from_editor_df" not in text:
        old = "    delete_time_records,\n"
        if old in text:
            text = text.replace(old, old + "    delete_time_records_from_editor_df,\n", 1)
    old_call = 'count = delete_time_records(checked_ids, reason="01 工時紀錄管理員維護區刪除")'
    new_call = '''count = delete_time_records(checked_ids, reason="01 工時紀錄管理員維護區刪除")
                            if count <= 0:
                                try:
                                    count = delete_time_records_from_editor_df(edited_admin, delete_column=delete_col, reason="01 工時紀錄管理員維護區刪除")
                                except Exception:
                                    pass'''
    if old_call in text and new_call not in text:
        backup = path.with_suffix(path.suffix + ".v177.bak")
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")
        text = text.replace(old_call, new_call, 1)
        path.write_text(text, encoding="utf-8")
        print(f"Applied V177 page patch: {path}")
    else:
        # If service import was added only, still write it.
        path.write_text(text, encoding="utf-8")
        print(f"Checked V177 page patch: {path}")


def main() -> int:
    patch_service()
    for p in PAGE_CANDIDATES:
        patch_page(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
