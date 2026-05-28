# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
import pandas as pd
from services.timezone_service import today_date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.crud_table_service import load_employees, save_employees
from services.time_record_service import load_records, today_records
from services.table_ui_service import render_table

st.set_page_config(page_title="07. 今日未紀錄名單", page_icon="⟁️", layout="wide")
apply_theme()
require_module_access("07_missing")
render_header(
    "07｜今日未紀錄名單",
    "今日出勤與在廠狀態維護、未紀錄工時人員查詢｜同一頁面完成，不再分成兩個頁籤。",
)

STATE_KEY = "v202_today_attendance_editor"
EDITOR_REV_KEY = "v202_today_attendance_editor_rev"
EDITOR_IGNORE_RETURN_KEY = "v263_today_attendance_ignore_next_editor_return"
COLS = [
    "id", "employee_id", "employee_name", "department", "title",
    "is_active", "is_in_factory", "is_today_attendance", "note", "created_at", "updated_at",
]

# V61：今日出勤維護表格也使用與 10｜權限管理相同的中英雙語實際欄名。
DISPLAY_COLUMNS = {
    "id": "ID / ID",
    "employee_id": "工號 / Employee ID",
    "employee_name": "姓名 / Name",
    "department": "單位 / Department",
    "title": "職稱 / Title",
    "is_active": "啟用 / Active",
    "is_in_factory": "在廠 / In Factory",
    "is_today_attendance": "今日出勤 / Today Attendance",
    "note": "備註 / Note",
    "created_at": "建立時間 / Created At",
    "updated_at": "更新時間 / Updated At",
}
DISPLAY_TO_INTERNAL = {v: k for k, v in DISPLAY_COLUMNS.items()}
DISPLAY_ROW_NO = "序號 / No."
# V66：07 頁不再把 SQLite id 直接當成畫面主鍵顯示。
# 人員永久檔若來自 JSON / GitHub，id 可能為 None；實際儲存會以 employee_id 做 UPSERT，
# 所以畫面改顯示穩定序號，避免出現整欄 None 被誤判為缺資料或按鈕失效。
EDITOR_COLS = [DISPLAY_ROW_NO] + [DISPLAY_COLUMNS[c] for c in COLS if c != "id"]
BOOL_INTERNAL_COLS = ["is_active", "is_in_factory", "is_today_attendance"]


def rerun() -> None:
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def _to_bool_value(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except Exception:
        pass
    text = str(v).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "啟用", "在廠", "出勤", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "離職", "不在", "未出勤", "否", ""}:
        return False
    return bool(v)


def ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = out.rename(columns={c: DISPLAY_TO_INTERNAL.get(c, c) for c in out.columns})
    for c in COLS:
        if c not in out.columns:
            out[c] = False if c in {"is_active", "is_in_factory", "is_today_attendance"} else ""
    for c in BOOL_INTERNAL_COLS:
        out[c] = out[c].map(_to_bool_value).fillna(False).astype(bool)
    return out[COLS]


def _to_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_cols(df)
    view = work.rename(columns=DISPLAY_COLUMNS)
    view.insert(0, DISPLAY_ROW_NO, range(1, len(view) + 1))
    return view[EDITOR_COLS]


def _from_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if DISPLAY_ROW_NO in work.columns:
        work = work.drop(columns=[DISPLAY_ROW_NO], errors="ignore")
    # 07 的畫面不顯示 id；回存前補回空 id，save_employees 會用 employee_id 做更新/新增。
    if DISPLAY_COLUMNS["id"] not in work.columns and "id" not in work.columns:
        work["id"] = ""
    return ensure_cols(work)


def _commit_current_editor_widget_state() -> None:
    """V67: commit data_editor widget delta into this page draft before buttons/KPI read it."""
    try:
        from services.data_editor_state_service import commit_editor_widget_state_to_session
        commit_editor_widget_state_to_session(
            state_key=STATE_KEY,
            editor_key=editor_key(),
            to_editor_df=_to_editor_df,
            from_editor_df=_from_editor_df,
            ensure_df=ensure_cols,
        )
    except Exception:
        pass


def reload_employees() -> None:
    st.session_state[STATE_KEY] = ensure_cols(load_employees())
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def touch_editor() -> None:
    # V65：只清除 data_editor widget 本身，不可把 STATE_KEY / REV / IGNORE 一起刪掉。
    # V64 的條件包含「today_attendance_editor」字串，會誤刪 v202_today_attendance_editor，
    # 導致批次按鈕剛改完暫存資料又被 reload_employees() 蓋回，看起來像按鈕無作用。
    protected_keys = {STATE_KEY, EDITOR_REV_KEY, EDITOR_IGNORE_RETURN_KEY}
    try:
        for _k0 in list(st.session_state.keys()):
            sk = str(_k0)
            if sk in protected_keys:
                continue
            if sk.startswith("today_attendance_editor_v202_"):
                st.session_state.pop(_k0, None)
    except Exception:
        pass
    try:
        from services.column_settings_service import clear_editor_draft
        clear_editor_draft("today_attendance_editor")
        clear_editor_draft("today_attendance")
    except Exception:
        pass
    st.session_state[EDITOR_IGNORE_RETURN_KEY] = True
    st.session_state[EDITOR_REV_KEY] = int(st.session_state.get(EDITOR_REV_KEY, 0)) + 1


def _current_internal_df() -> pd.DataFrame:
    _commit_current_editor_widget_state()
    return ensure_cols(st.session_state.get(STATE_KEY, pd.DataFrame()))


def _bulk_set_bool_column(col: str, value: bool) -> None:
    """V65: 批次按鈕重新指定整份 DataFrame，避免 in-place 修改被 data_editor 舊草稿覆蓋。"""
    df = _current_internal_df().copy()
    if col not in df.columns:
        df[col] = False
    df[col] = bool(value)
    st.session_state[STATE_KEY] = ensure_cols(df)
    touch_editor()
    rerun()


def _date_text_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    if "start_date" in df.columns:
        return pd.to_datetime(df["start_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "work_date" in df.columns:
        return pd.to_datetime(df["work_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "start_timestamp" in df.columns:
        return pd.to_datetime(df["start_timestamp"], errors="coerce").dt.strftime("%Y-%m-%d")
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _v148_clean_text(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in {"none", "nan", "nat", "null", "<na>"} else s


def _v148_first_existing_series(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    for c in candidates:
        if c in df.columns:
            return df[c].map(_v148_clean_text)
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _v148_record_key_employee_series(df: pd.DataFrame) -> pd.Series:
    rk = _v148_first_existing_series(df, ["record_key", "紀錄鍵 / Record Key", "Record Key"])
    return rk.map(lambda x: str(x).split("|", 1)[0].strip() if "|" in str(x) else "")


def _v148_record_employee_id_series(df: pd.DataFrame) -> pd.Series:
    emp = _v148_first_existing_series(df, [
        "employee_id", "工號 / Employee ID", "工號", "Employee ID", "員工編號", "人員工號"
    ])
    missing = emp.eq("")
    if missing.any():
        rk_emp = _v148_record_key_employee_series(df)
        emp = emp.mask(missing, rk_emp)
    return emp.map(lambda x: str(x).strip())


def _v148_record_employee_name_series(df: pd.DataFrame) -> pd.Series:
    return _v148_first_existing_series(df, [
        "employee_name", "姓名 / Name", "姓名", "Name", "員工姓名", "人員姓名"
    ]).map(lambda x: str(x).strip())


def _v148_record_date_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    for c in [
        "start_date", "工作日期 / Work Date", "work_date", "開始日期 / Start Date", "開始日期",
        "start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp", "開始時間",
    ]:
        if c in df.columns:
            try:
                s = pd.to_datetime(df[c], errors="coerce").dt.strftime("%Y-%m-%d")
                if s.notna().any():
                    return s.fillna("").astype(str)
            except Exception:
                pass
            return df[c].map(lambda v: _v148_clean_text(v).replace("/", "-")[:10])
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _v148_combine_record_sources(target_date: str) -> pd.DataFrame:
    """Read-only 07 source: 02 history canonical + 01 today display source.

    07 must not decide missing people from only one source. A person has recorded
    time if either 02 history or 01 current/today records contains a row for the
    employee on the selected date. This function does not write, delete, or recalc.
    """
    frames: list[pd.DataFrame] = []
    try:
        hist = load_records(start_date=target_date, end_date=target_date)
        if isinstance(hist, pd.DataFrame) and not hist.empty:
            frames.append(hist)
    except Exception:
        pass
    try:
        today_df = today_records(include_finished=True, unfinished_only=False)
        if isinstance(today_df, pd.DataFrame) and not today_df.empty:
            frames.append(today_df)
    except Exception:
        pass
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    # Dedupe without losing valid rows. record_key first, then id.
    for key_col in ["record_key", "紀錄鍵 / Record Key"]:
        if key_col in out.columns:
            key = out[key_col].map(_v148_clean_text)
            with_key = out.loc[key.ne("")].drop_duplicates(subset=[key_col], keep="last")
            without_key = out.loc[key.eq("")]
            out = pd.concat([with_key, without_key], ignore_index=True, sort=False)
            break
    for id_col in ["id", "ID / ID"]:
        if id_col in out.columns:
            try:
                out["_v148_id"] = pd.to_numeric(out[id_col], errors="coerce")
                has_id = out["_v148_id"].notna()
                out = pd.concat([
                    out.loc[has_id].drop_duplicates(subset=["_v148_id"], keep="last"),
                    out.loc[~has_id],
                ], ignore_index=True, sort=False).drop(columns=["_v148_id"], errors="ignore")
            except Exception:
                out = out.drop(columns=["_v148_id"], errors="ignore")
            break
    return out.reset_index(drop=True)


def _build_missing_today_df(employee_df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """Build today's missing list with robust 01/02 record detection.

    V148 root fix:
    Previous logic only trusted load_records() and only the internal employee_id
    column. If 01 had a current row, or 02 returned bilingual columns / record_key
    based rows, the employee could still appear as missing. This version counts a
    person as recorded when either 01 or 02 has any row for the same employee and
    date, using employee_id, bilingual Employee ID, or record_key prefix.
    """
    emp = ensure_cols(employee_df)
    base_cols = ["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]
    if emp.empty:
        return pd.DataFrame(columns=base_cols)
    for c in BOOL_INTERNAL_COLS:
        emp[c] = emp[c].map(_to_bool_value).fillna(False).astype(bool)
    emp = emp[(emp["is_active"]) & (emp["is_in_factory"]) & (emp["is_today_attendance"])].copy()
    emp["employee_id"] = emp["employee_id"].map(_v148_clean_text)
    emp["employee_name"] = emp["employee_name"].map(_v148_clean_text)
    emp = emp[emp["employee_id"] != ""].copy()
    if emp.empty:
        out = emp.copy()
        out["last_start_time"] = ""
        out["today_record_count"] = 0
        return out[base_cols]

    rec = _v148_combine_record_sources(target_date)
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[base_cols].sort_values("employee_id")

    rec = rec.copy()
    rec["__emp_id"] = _v148_record_employee_id_series(rec)
    rec["__emp_name"] = _v148_record_employee_name_series(rec)
    rec["__record_date"] = _v148_record_date_series(rec)
    rec["__start_time"] = _v148_first_existing_series(rec, [
        "start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp", "開始時間", "start_time", "開始時刻 / Start Time"
    ])
    rec = rec[(rec["__record_date"] == str(target_date)) & ((rec["__emp_id"] != "") | (rec["__emp_name"] != ""))].copy()
    if rec.empty:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[base_cols].sort_values("employee_id")

    rec["__emp_key"] = rec["__emp_id"].astype(str).str.strip().str.casefold()
    emp["__emp_key"] = emp["employee_id"].astype(str).str.strip().str.casefold()

    grp = rec[rec["__emp_key"] != ""].groupby("__emp_key", dropna=False).agg(
        last_start_time=("__start_time", "max"),
        today_record_count=("__emp_key", "size"),
    ).reset_index()

    out = emp.merge(grp, on="__emp_key", how="left")
    out["today_record_count"] = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    out["last_start_time"] = out["last_start_time"].fillna("").astype(str)
    out = out[out["today_record_count"] == 0].copy()
    return out[base_cols].sort_values("employee_id")


# ===================== V150 Missing Today multi-source hard compare =====================
# 問題修正：07 今日未紀錄名單不能只依賴 load_records(start_date=today,end_date=today)。
# 原因：02/01 權威檔、SQLite cache、today_records 顯示來源可能在不同修補層被過濾或欄名不同，
# 造成明明 01/02 有今日紀錄的人仍被列為未紀錄。V150 改成只讀、多來源比對，不寫入、不覆蓋。

_V150_EMP_ID_CANDIDATES = [
    "employee_id", "工號 / Employee ID", "工號 / Employee", "工號 / Emp ID", "工號",
    "Employee ID", "Employee", "員工編號", "人員工號", "工號/Employee ID",
]
_V150_EMP_NAME_CANDIDATES = [
    "employee_name", "姓名 / Name", "姓名 / Employee Name", "姓名", "Name",
    "員工姓名", "人員姓名", "Employee Name", "姓名/Name",
]
_V150_DATE_CANDIDATES = [
    "start_date", "工作日期 / Work Date", "work_date", "日期 / Date", "日期", "工作日期",
    "開始日期 / Start Date", "開始日期", "Start Date", "Work Date",
]
_V150_TIMESTAMP_CANDIDATES = [
    "start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp",
    "開始時間", "Start Timestamp", "created_at", "建立時間 / Created At",
]
_V150_START_TIME_CANDIDATES = [
    "start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp", "開始時間",
    "start_time", "開始時刻 / Start Time", "Start Time",
]


def _v150_safe_df(df) -> pd.DataFrame:
    return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _v150_first_series(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    # 精準欄名優先。
    for c in candidates:
        if c in df.columns:
            return df[c].map(_v148_clean_text)
    # 再做寬鬆比對，處理欄名被截斷或中英順序不同。
    norm_cols = {str(c).lower().replace(" ", "").replace("/", ""): c for c in df.columns}
    for cand in candidates:
        key = str(cand).lower().replace(" ", "").replace("/", "")
        if key in norm_cols:
            return df[norm_cols[key]].map(_v148_clean_text)
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _v148_record_employee_id_series(df: pd.DataFrame) -> pd.Series:  # type: ignore[override]
    emp = _v150_first_series(df, _V150_EMP_ID_CANDIDATES)
    missing = emp.eq("")
    if missing.any():
        rk_emp = _v148_record_key_employee_series(df)
        emp = emp.mask(missing, rk_emp)
    return emp.map(lambda x: str(x).strip())


def _v148_record_employee_name_series(df: pd.DataFrame) -> pd.Series:  # type: ignore[override]
    return _v150_first_series(df, _V150_EMP_NAME_CANDIDATES).map(lambda x: str(x).strip())


def _v150_date_from_series(s: pd.Series, *, require_date_like: bool = False) -> pd.Series:
    if s is None or s.empty:
        return pd.Series(dtype=str)
    txt = s.map(_v148_clean_text).astype(str)
    if require_date_like:
        # 純時間如 16:10:48 不能被 pandas 解析成今天，否則會把無日期資料誤算成今日。
        has_date = txt.str.contains(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", regex=True)
        txt = txt.where(has_date, "")
    try:
        dt = pd.to_datetime(txt, errors="coerce")
        out = dt.dt.strftime("%Y-%m-%d").fillna("").astype(str)
        if out.ne("").any():
            return out
    except Exception:
        pass
    return txt.str.replace("/", "-", regex=False).str.slice(0, 10)


def _v148_record_date_series(df: pd.DataFrame) -> pd.Series:  # type: ignore[override]
    if df is None or df.empty:
        return pd.Series(dtype=str)
    # 日期欄優先。
    for c in _V150_DATE_CANDIDATES:
        if c in df.columns:
            out = _v150_date_from_series(df[c], require_date_like=False)
            if out.ne("").any():
                return out
    # 時間戳欄次之，必須真的含日期。
    for c in _V150_TIMESTAMP_CANDIDATES:
        if c in df.columns:
            out = _v150_date_from_series(df[c], require_date_like=True)
            if out.ne("").any():
                return out
    return pd.Series([""] * len(df), index=df.index, dtype=str)


def _v150_read_authority_time_records(module_key: str) -> pd.DataFrame:
    try:
        from services.permanent_authority_service import df_from_table
        df = df_from_table(module_key, "time_records")
        return _v150_safe_df(df)
    except Exception:
        return pd.DataFrame()


def _v150_read_sqlite_time_records() -> pd.DataFrame:
    try:
        from services.db_service import query_df
        df = query_df("SELECT * FROM time_records")
        return _v150_safe_df(df)
    except Exception:
        return pd.DataFrame()


def _v150_not_deleted_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    for c in ["status", "狀態 / Status", "狀態"]:
        if c in out.columns:
            s = out[c].map(_v148_clean_text).astype(str).str.lower()
            out = out.loc[~s.isin({"刪除", "已刪除", "deleted", "delete", "removed"})].copy()
            break
    return out.reset_index(drop=True)


def _v148_combine_record_sources(target_date: str) -> pd.DataFrame:  # type: ignore[override]
    """V150: read 01/02/SQLite/today sources directly, then filter locally.

    This function is read-only.  It does not call any save/sync/delete/recalc path,
    so it cannot make history disappear or overwrite records.  It only prevents
    employees with real today records from being listed as missing.
    """
    frames: list[pd.DataFrame] = []

    # 02/01 canonical authority are the most important sources for Reboot-safe data.
    for module_key in ("02_history", "01_time_records"):
        df = _v150_read_authority_time_records(module_key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.copy()
            df["__v150_source"] = module_key
            frames.append(df)

    # Existing service functions may include display repairs / caches; read them too, but don't depend on them alone.
    try:
        hist_all = load_records()
        if isinstance(hist_all, pd.DataFrame) and not hist_all.empty:
            hist_all = hist_all.copy()
            hist_all["__v150_source"] = "load_records_all"
            frames.append(hist_all)
    except Exception:
        pass
    try:
        hist_day = load_records(start_date=target_date, end_date=target_date)
        if isinstance(hist_day, pd.DataFrame) and not hist_day.empty:
            hist_day = hist_day.copy()
            hist_day["__v150_source"] = "load_records_day"
            frames.append(hist_day)
    except Exception:
        pass
    try:
        today_df = today_records(include_finished=True, unfinished_only=False)
        if isinstance(today_df, pd.DataFrame) and not today_df.empty:
            today_df = today_df.copy()
            today_df["__v150_source"] = "today_records"
            frames.append(today_df)
    except Exception:
        pass

    # SQLite is runtime cache.  It is read-only here and only used as an additional evidence source.
    sqlite_df = _v150_read_sqlite_time_records()
    if isinstance(sqlite_df, pd.DataFrame) and not sqlite_df.empty:
        sqlite_df = sqlite_df.copy()
        sqlite_df["__v150_source"] = "sqlite_time_records"
        frames.append(sqlite_df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True, sort=False)
    out = _v150_not_deleted_filter(out)
    if out.empty:
        return out

    # 先在合併後建立標準欄，讓後續去重和日期篩選不受欄名影響。
    out["__v150_emp_id"] = _v148_record_employee_id_series(out)
    out["__v150_emp_name"] = _v148_record_employee_name_series(out)
    out["__v150_date"] = _v148_record_date_series(out)
    out["__v150_rk"] = _v150_first_series(out, ["record_key", "紀錄鍵 / Record Key", "Record Key"])

    # 只留下目標日期且能辨識人員的資料；這裡才做日期過濾，避免 service 層過濾失準。
    out = out[(out["__v150_date"] == str(target_date)) & ((out["__v150_emp_id"] != "") | (out["__v150_emp_name"] != ""))].copy()
    if out.empty:
        return out

    # 去重只為了統計不要被多來源重複放大；不能用單一 id 直接覆蓋不同人。
    if "__v150_rk" in out.columns and out["__v150_rk"].astype(str).str.strip().ne("").any():
        has_key = out["__v150_rk"].astype(str).str.strip().ne("")
        keyed = out.loc[has_key].drop_duplicates(subset=["__v150_rk"], keep="last")
        unkeyed = out.loc[~has_key]
        out = pd.concat([keyed, unkeyed], ignore_index=True, sort=False)
    # 對沒有 record_key 的資料，用業務鍵去重，不用單獨 id，避免 SQLite id 重用或不同來源 id 撞號誤蓋。
    biz_cols = ["__v150_emp_id", "__v150_emp_name", "work_order", "製令 / Work Order", "process_name", "工段名稱 / Process", "start_timestamp", "開始時間戳 / Start Timestamp"]
    existing_biz_cols = [c for c in biz_cols if c in out.columns]
    if existing_biz_cols:
        out = out.drop_duplicates(subset=existing_biz_cols, keep="last")
    return out.reset_index(drop=True)


def _build_missing_today_df(employee_df: pd.DataFrame, target_date: str) -> pd.DataFrame:  # type: ignore[override]
    """V150: Missing Today calculation based on real current-day time records.

    A person is NOT missing if any read-only evidence source has a time record for
    the employee today: 02_history, 01_time_records, load_records, today_records,
    or SQLite time_records.  The function never writes back to any authority file.
    """
    emp = ensure_cols(employee_df)
    base_cols = ["employee_id", "employee_name", "department", "title", "is_in_factory", "is_today_attendance", "last_start_time", "today_record_count"]
    if emp.empty:
        return pd.DataFrame(columns=base_cols)
    for c in BOOL_INTERNAL_COLS:
        emp[c] = emp[c].map(_to_bool_value).fillna(False).astype(bool)
    emp = emp[(emp["is_active"]) & (emp["is_in_factory"]) & (emp["is_today_attendance"])].copy()
    emp["employee_id"] = emp["employee_id"].map(_v148_clean_text)
    emp["employee_name"] = emp["employee_name"].map(_v148_clean_text)
    emp = emp[emp["employee_id"] != ""].copy()
    if emp.empty:
        out = emp.copy()
        out["last_start_time"] = ""
        out["today_record_count"] = 0
        return out[base_cols]

    rec = _v148_combine_record_sources(target_date)
    if rec is None or not isinstance(rec, pd.DataFrame) or rec.empty:
        emp["last_start_time"] = ""
        emp["today_record_count"] = 0
        return emp[base_cols].sort_values("employee_id")

    rec = rec.copy()
    rec["__emp_id"] = rec.get("__v150_emp_id", _v148_record_employee_id_series(rec)).map(_v148_clean_text)
    rec["__emp_name"] = rec.get("__v150_emp_name", _v148_record_employee_name_series(rec)).map(_v148_clean_text)
    rec["__record_date"] = rec.get("__v150_date", _v148_record_date_series(rec)).map(_v148_clean_text)
    rec["__start_time"] = _v150_first_series(rec, _V150_START_TIME_CANDIDATES)
    rec = rec[(rec["__record_date"] == str(target_date)) & ((rec["__emp_id"] != "") | (rec["__emp_name"] != ""))].copy()

    emp["__emp_key"] = emp["employee_id"].astype(str).str.strip().str.casefold()
    emp["__name_key"] = emp["employee_name"].astype(str).str.strip().str.casefold()
    rec["__emp_key"] = rec["__emp_id"].astype(str).str.strip().str.casefold()
    rec["__name_key"] = rec["__emp_name"].astype(str).str.strip().str.casefold()

    # 工號為主；若紀錄缺工號但有姓名，才用姓名補判斷。
    id_grp = rec[rec["__emp_key"] != ""].groupby("__emp_key", dropna=False).agg(
        last_start_time=("__start_time", "max"),
        today_record_count=("__emp_key", "size"),
    ).reset_index()
    out = emp.merge(id_grp, on="__emp_key", how="left")

    missing_count = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    need_name_fallback = missing_count.eq(0)
    if need_name_fallback.any():
        name_grp = rec[(rec["__emp_key"] == "") & (rec["__name_key"] != "")].groupby("__name_key", dropna=False).agg(
            last_start_time_by_name=("__start_time", "max"),
            today_record_count_by_name=("__name_key", "size"),
        ).reset_index()
        out = out.merge(name_grp, on="__name_key", how="left")
        by_name_count = pd.to_numeric(out.get("today_record_count_by_name", 0), errors="coerce").fillna(0).astype(int)
        by_name_time = out.get("last_start_time_by_name", "")
        out["today_record_count"] = missing_count.mask(need_name_fallback, by_name_count)
        out["last_start_time"] = out["last_start_time"].fillna("").astype(str).mask(need_name_fallback, by_name_time.fillna("").astype(str))
    else:
        out["today_record_count"] = missing_count
        out["last_start_time"] = out["last_start_time"].fillna("").astype(str)

    out["today_record_count"] = pd.to_numeric(out["today_record_count"], errors="coerce").fillna(0).astype(int)
    out["last_start_time"] = out["last_start_time"].fillna("").astype(str)
    out = out[out["today_record_count"] == 0].copy()
    return out[base_cols].sort_values("employee_id")
# =================== END V150 Missing Today multi-source hard compare ===================


if STATE_KEY not in st.session_state:
    reload_employees()

can_edit = check_permission("07_missing", "can_edit") or check_permission("04_employees", "can_edit")

st.subheader("今日出勤名單編輯 / Today Attendance Editor")
st.info("V66：今日出勤表格改用『序號 / No.』取代空白 SQLite ID；批次按鈕仍只改畫面暫存，按儲存後才寫入正式人員資料。")

if not can_edit:
    st.warning("目前帳號沒有今日出勤 / 人員名單編輯權限，只能查看資料。")
    view_df = st.session_state[STATE_KEY].copy()
    render_table(view_df, "today_attendance_readonly_v202", editable=False, height=460)
else:
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("☑ 在廠全選 / Factory All", use_container_width=True, key="v64_today_factory_all_on"):
        _bulk_set_bool_column("is_in_factory", True)
    if c2.button("☐ 在廠取消 / Clear Factory", use_container_width=True, key="v64_today_factory_all_off"):
        _bulk_set_bool_column("is_in_factory", False)
    if c3.button("☑ 今日出勤全選 / Attendance All", use_container_width=True, key="v64_today_attendance_all_on"):
        _bulk_set_bool_column("is_today_attendance", True)
    if c4.button("☐ 今日出勤取消 / Clear Attendance", use_container_width=True, key="v64_today_attendance_all_off"):
        _bulk_set_bool_column("is_today_attendance", False)

    c5, c6, c7, c8 = st.columns(4)
    if c5.button("☑ 啟用全選 / Active All", use_container_width=True, key="v64_today_active_all_on"):
        _bulk_set_bool_column("is_active", True)
    if c6.button("☐ 啟用取消 / Inactive All", use_container_width=True, key="v64_today_active_all_off"):
        _bulk_set_bool_column("is_active", False)
    if c7.button("⟳ 重新載入 / Reload", use_container_width=True, key="v202_today_reload"):
        reload_employees()
        rerun()
    c8.caption("批次按鈕只改畫面暫存，按儲存後才寫入。")

    editor_key = f"today_attendance_editor_v202_{st.session_state.get(EDITOR_REV_KEY, 0)}"
    _commit_current_editor_widget_state()
    st.session_state[STATE_KEY] = ensure_cols(st.session_state[STATE_KEY])
    editor_df = _to_editor_df(st.session_state[STATE_KEY])
    # V120：穩定編輯模式。把 data_editor 與儲存按鈕放在同一個 form，
    # 避免 checkbox / cell edit 每一下都 rerun 跳頁；批次按鈕與原儲存邏輯不變。
    with st.form("v120_today_attendance_stable_editor_form", clear_on_submit=False):
        edited = st.data_editor(
            editor_df,
            hide_index=True,
            use_container_width=True,
            height=460,
            disabled=[DISPLAY_ROW_NO] + [DISPLAY_COLUMNS[c] for c in ["employee_id", "employee_name", "department", "title", "note", "created_at", "updated_at"]],
            column_order=EDITOR_COLS,
            column_config={
                DISPLAY_ROW_NO: st.column_config.NumberColumn("序號 / No.", width="small"),
                DISPLAY_COLUMNS["employee_id"]: st.column_config.TextColumn("工號 / Employee ID", width="medium"),
                DISPLAY_COLUMNS["employee_name"]: st.column_config.TextColumn("姓名 / Name", width="medium"),
                DISPLAY_COLUMNS["department"]: st.column_config.TextColumn("單位 / Department", width="medium"),
                DISPLAY_COLUMNS["title"]: st.column_config.TextColumn("職稱 / Title", width="medium"),
                DISPLAY_COLUMNS["is_active"]: st.column_config.CheckboxColumn("啟用 / Active", width="medium"),
                DISPLAY_COLUMNS["is_in_factory"]: st.column_config.CheckboxColumn("在廠 / In Factory", width="medium"),
                DISPLAY_COLUMNS["is_today_attendance"]: st.column_config.CheckboxColumn("今日出勤 / Today Attendance", width="medium"),
                DISPLAY_COLUMNS["note"]: st.column_config.TextColumn("備註 / Note", width="large"),
                DISPLAY_COLUMNS["created_at"]: st.column_config.TextColumn("建立時間 / Created At", width="medium"),
                DISPLAY_COLUMNS["updated_at"]: st.column_config.TextColumn("更新時間 / Updated At", width="medium"),
            },
            key=editor_key,
        )
        submitted_today_attendance = st.form_submit_button("▣ 確認儲存今日出勤設定 / Save Today Attendance", type="primary", use_container_width=True)

    ignore_editor_return = bool(st.session_state.pop(EDITOR_IGNORE_RETURN_KEY, False))
    if isinstance(edited, pd.DataFrame) and not ignore_editor_return:
        st.session_state[STATE_KEY] = _from_editor_df(edited)
    if submitted_today_attendance:
        save_df = st.session_state[STATE_KEY].copy()
        save_df.insert(0, "_delete", False)
        result = save_employees(save_df)
        reload_employees()
        st.success(f"今日出勤設定已儲存：目前保留/更新 {len(save_df)} 筆，略過 {result.get('skipped', 0)} 筆。")
        rerun()

st.divider()
st.subheader("今日未紀錄名單 / Missing Today")
today = today_date().strftime("%Y-%m-%d")
current_attendance_df = _current_internal_df() if STATE_KEY in st.session_state else ensure_cols(load_employees())
df = _build_missing_today_df(current_attendance_df, today)

st.metric("今日未紀錄人數 / Missing Records", f"{len(df):,}")
st.caption("V66：此區依目前畫面暫存的『啟用 / 在廠 / 今日出勤』狀態，加上今日工時權威檔即時計算；ID 為空不影響判斷，實際主鍵使用工號。")
render_table(df, "missing_today_v202", editable=False, height=460)
