# -*- coding: utf-8 -*-
from __future__ import annotations

import re

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd


# ===== V95 RAW DATA EDITOR HELPER =====
def _v95_raw_data_editor(data=None, *args, **kwargs):
    """Bypass global column-settings wrapper for the 01 admin maintenance editor.

    The wrapper can render another settings editor with the same generated key and
    trigger StreamlitDuplicateElementKey. 01 admin table already manages its own
    column order/config, so bypassing the wrapper here does not remove features.
    """
    try:
        import services.column_settings_service as _css
        _orig = getattr(_css, "_ORIGINAL_DATA_EDITOR", None)
        if callable(_orig):
            return _orig(data, *args, **kwargs)
    except Exception:
        pass
    return st.data_editor(data, *args, **kwargs)
# ===== V95 RAW DATA EDITOR HELPER END =====

from services.theme_service import apply_theme, render_header
from services.ui_size_service import apply_dropdown_menu_size_only
from services.security_service import (
    check_permission,
    get_current_user,
    require_module_access,
    render_post_record_continue_prompt,
    trigger_post_record_continue_prompt,
)
from services.master_data_service import (
    load_employees_for_time_record_fast,
    load_work_orders_for_time_record_fast,
    has_master_data_for_time_record_fast,
)
from services.time_record_service import (
    clear_today_records_fast_cache,
    clear_today_finished_from_work_page,
    delete_time_records,
    recalculate_time_records,
    finish_work,
    get_active_group,
    get_active_record,
    get_conflicting_active_records,
    get_active_same_work,
    refresh_active_records_for_employee,
    save_time_records,
    start_work,
    today_records,
)
from services.db_service import query_one
from services.table_ui_service import render_table, render_width_settings
from services.system_settings_service import get_process_options_by_category_exact, get_default_process_category, load_process_category_choices, get_live_page_reset_time

st.set_page_config(page_title="01. 工時紀錄", page_icon="⏱", layout="wide")
apply_theme()
apply_dropdown_menu_size_only(560)
require_module_access("01_time_record")
render_header("01｜工時紀錄", "快速開始、同步作業、暫停、下班、完工｜自動記錄時間與扣除休息")
render_post_record_continue_prompt()


# ===== V100 WORK ORDER MANUAL INPUT + FUZZY SEARCH FIX =====
def _v100_inject_work_order_input_css() -> None:
    """Page-level override: readable dark inputs and yellow glow only on Work Order controls."""
    st.markdown(
        """
<style>
/* V103｜01 工時紀錄：維持深色可讀性；黃色光暈只套用在製令輸入/下拉，不影響其他按鈕與表格 */
.stSelectbox div[data-baseweb="select"] > div,
.stTextInput div[data-baseweb="input"] > div,
.stTextInput input {
    background: linear-gradient(135deg, rgba(18, 28, 68, 0.98), rgba(28, 41, 91, 0.94)) !important;
    border: 1px solid rgba(103, 239, 255, 0.92) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 0 16px rgba(79,229,255,0.22) !important;
}
.stSelectbox div[data-baseweb="select"] span,
.stSelectbox div[data-baseweb="select"] p,
.stSelectbox div[data-baseweb="select"] div,
.stSelectbox div[data-baseweb="select"] input,
.stSelectbox div[data-baseweb="select"] div[role="combobox"],
.stTextInput input,
.stTextInput input::placeholder,
div[data-baseweb="popover"] [role="option"],
div[data-baseweb="popover"] [role="option"] * {
    color: #eaffff !important;
    -webkit-text-fill-color: #eaffff !important;
    font-weight: 850 !important;
    text-shadow: 0 0 10px rgba(121,237,255,0.26) !important;
}
div[data-baseweb="popover"] > div {
    background: #07162b !important;
    border: 1px solid rgba(103,239,255,0.55) !important;
    box-shadow: 0 18px 46px rgba(0,0,0,0.58), 0 0 28px rgba(79,229,255,0.18) !important;
}
div[data-baseweb="popover"] [role="option"]:hover,
div[data-baseweb="popover"] [aria-selected="true"] {
    background: rgba(79,229,255,0.18) !important;
}
/* V104: 黃色光暈只套用在「製令關鍵字」手動輸入格；下方「製令｜Work Order」下拉不加黃色光暈，避免影響其他下拉欄位。 */
div[data-testid="stTextInput"]:has(input[aria-label*="製令關鍵字"]) {
    border-radius: 16px !important;
    filter: drop-shadow(0 0 14px rgba(255, 221, 87, 0.40));
}
div[data-testid="stTextInput"]:has(input[aria-label*="製令關鍵字"]) div[data-baseweb="input"] > div {
    border: 1.5px solid rgba(255, 221, 87, 0.98) !important;
    box-shadow: 0 0 0 1px rgba(255,221,87,0.28), 0 0 22px rgba(255,221,87,0.42), inset 0 1px 0 rgba(255,255,255,0.10) !important;
}
</style>
""",
        unsafe_allow_html=True,
    )

def _v100_norm(value) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def _v100_work_order_label(row) -> str:
    parts = [
        str(row.get("work_order") or "").strip(),
        str(row.get("part_no") or "").strip(),
        str(row.get("type_name") or "").strip(),
    ]
    return "｜".join([x for x in parts if x])


def _v100_fuzzy_work_order_options(work_orders_df: pd.DataFrame, keyword: str, limit: int = 80) -> list[str]:
    """Return scored fuzzy-search labels without touching the original work-order table."""
    if work_orders_df is None or work_orders_df.empty:
        return []
    keyword_raw = str(keyword or "").strip()
    keyword_norm = _v100_norm(keyword_raw)
    if not keyword_norm:
        return [_v100_work_order_label(r) for _, r in work_orders_df.head(limit).iterrows()]

    tokens = [_v100_norm(x) for x in re.split(r"[\s,，/|｜]+", keyword_raw) if _v100_norm(x)]
    scored: list[tuple[int, str]] = []
    for _, row in work_orders_df.iterrows():
        label = _v100_work_order_label(row)
        searchable = " ".join(
            str(row.get(c) or "")
            for c in ["work_order", "part_no", "type_name", "assembly_location", "customer", "note"]
            if c in work_orders_df.columns
        )
        n_label = _v100_norm(label)
        n_search = _v100_norm(searchable)
        score = 0
        wo_norm = _v100_norm(row.get("work_order"))
        if wo_norm == keyword_norm:
            score += 1000
        if wo_norm.startswith(keyword_norm):
            score += 720
        if keyword_norm in wo_norm:
            score += 620
        if keyword_norm in n_label:
            score += 520
        if keyword_norm in n_search:
            score += 420
        if tokens and all(t in n_search for t in tokens):
            score += 260 + len(tokens)
        if score:
            scored.append((score, label))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _, label in scored:
        if label and label not in seen:
            seen.add(label)
            out.append(label)
        if len(out) >= limit:
            break
    return out



def _v103_work_order_option_to_no(option: str, query: str = "") -> str:
    s = str(option or "").strip()
    manual_prefix = "＋ 使用手動輸入："
    if s.startswith(manual_prefix):
        return str(query or "").strip()
    if "｜" in s:
        return s.split("｜", 1)[0].strip()
    return s.strip()


def _v103_work_order_filtered_options(work_orders_df: pd.DataFrame, query: str, limit: int = 120) -> list[str]:
    q = str(query or "").strip()
    labels = _v100_fuzzy_work_order_options(work_orders_df, q, limit=limit) if q else [
        _v100_work_order_label(r) for _, r in work_orders_df.head(limit).iterrows()
    ]
    labels = [x for x in labels if str(x or "").strip()]
    if q:
        q_norm = _v100_norm(q)
        exact = False
        for label in labels:
            if _v100_norm(str(label).split("｜", 1)[0]) == q_norm:
                exact = True
                break
        if not exact:
            labels.append(f"＋ 使用手動輸入：{q}")
    return labels or ([f"＋ 使用手動輸入：{q}"] if q else [])

def _v100_find_work_order_dict(work_orders_df: pd.DataFrame, work_order_no: str) -> dict:
    wo_no = str(work_order_no or "").strip()
    if not wo_no:
        return {}
    if work_orders_df is not None and not work_orders_df.empty and "work_order" in work_orders_df.columns:
        mask = work_orders_df["work_order"].fillna("").astype(str).str.strip().str.upper() == wo_no.upper()
        match = work_orders_df[mask]
        if not match.empty:
            return match.iloc[0].fillna("").to_dict()
    row = query_one("SELECT * FROM work_orders WHERE UPPER(TRIM(work_order))=UPPER(TRIM(?))", (wo_no,))
    if row:
        return row
    # 手動輸入但主檔沒有時，仍允許建立工時紀錄；P/N、機型保留空白，不影響既有 start_work 邏輯。
    return {"work_order": wo_no, "part_no": "", "type_name": "", "assembly_location": ""}


_v100_inject_work_order_input_css()
# ===== V100 WORK ORDER MANUAL INPUT + FUZZY SEARCH FIX END =====


# ===== V105 WORK ORDER KEYWORD LIVE URL SYNC =====
def _v105_qp_get(name: str) -> str:
    try:
        raw = st.query_params.get(name, "")
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        return str(raw or "")
    except Exception:
        try:
            raw = st.experimental_get_query_params().get(name, [""])
            return str(raw[0] if isinstance(raw, list) and raw else raw or "")
        except Exception:
            return ""


def _v105_prepare_live_work_order_keyword_state(key: str = "start_work_order_manual_query_v103") -> None:
    url_kw = _v105_qp_get("spt_wo_kw").strip()
    last = st.session_state.get("_spt_wo_kw_url_applied", None)
    if url_kw:
        if st.session_state.get(key, "") != url_kw or last != url_kw:
            st.session_state[key] = url_kw
            st.session_state["_spt_wo_kw_url_applied"] = url_kw
    elif last not in (None, ""):
        st.session_state[key] = ""
        st.session_state["_spt_wo_kw_url_applied"] = ""


def _v105_inject_live_work_order_keyword_sync() -> None:
    """讓製令關鍵字輸入後自動刷新下方製令下拉，不需 Enter。"""
    components.html(
        """
<script>
(function(){
  const PARAM = 'spt_wo_kw';
  const LABEL = '製令關鍵字';
  const DEBOUNCE_MS = 420;
  function bind(){
    const doc = window.parent && window.parent.document ? window.parent.document : document;
    const inputs = Array.from(doc.querySelectorAll('input')).filter(function(inp){
      const aria = inp.getAttribute('aria-label') || '';
      return aria.indexOf(LABEL) >= 0;
    });
    if(!inputs.length){ setTimeout(bind, 300); return; }
    const input = inputs[0];
    if(input.dataset.sptWoLiveBound === '1') return;
    input.dataset.sptWoLiveBound = '1';
    let timer = null;
    function sync(){
      const val = (input.value || '').trim();
      const url = new URL(window.parent.location.href);
      const cur = (url.searchParams.get(PARAM) || '').trim();
      if(cur === val) return;
      if(val){ url.searchParams.set(PARAM, val); }
      else { url.searchParams.delete(PARAM); }
      window.parent.location.replace(url.toString());
    }
    input.addEventListener('input', function(){
      if(timer) clearTimeout(timer);
      timer = setTimeout(sync, DEBOUNCE_MS);
    }, true);
  }
  bind();
})();
</script>
""",
        height=0,
        width=0,
    )
# ===== END V105 WORK ORDER KEYWORD LIVE URL SYNC =====




# ===== V126 LOGIN EMPLOYEE DEFAULT FIX =====
def _v126_employee_options_and_login_index(employees_df: pd.DataFrame) -> tuple[list[str], int]:
    """Default Employee selectors to the logged-in account's employee.

    50 人同時使用時，畫面上方登入者與 01 開始/結束人員下拉若不同，
    現場會誤以為系統把別人的帳號帶入。這裡只調整預設 index，
    不移除其他選項、不鎖定管理員選擇，不影響既有按鈕與權限。
    """
    if employees_df is None or employees_df.empty:
        return [], 0
    labels = employees_df.apply(lambda r: f"{str(r.get('employee_id','')).strip()}｜{str(r.get('employee_name','')).strip()}", axis=1).tolist()
    try:
        auth_emp = str(st.session_state.get('auth_employee_id') or '').strip().lower()
        auth_user = str(st.session_state.get('auth_username') or '').strip().lower()
        auth_name = str(st.session_state.get('auth_display_name') or '').strip().lower()
        for i, (_, r) in enumerate(employees_df.iterrows()):
            emp_id = str(r.get('employee_id') or '').strip().lower()
            emp_name = str(r.get('employee_name') or '').strip().lower()
            if auth_emp and emp_id == auth_emp:
                return labels, i
            if auth_user and emp_id == auth_user:
                return labels, i
            if auth_name and emp_name == auth_name:
                return labels, i
    except Exception:
        pass
    return labels, 0

# ===== END V126 LOGIN EMPLOYEE DEFAULT FIX =====


# ===== V127 EMPLOYEE SELECTBOX SESSION ISOLATION =====
def _v127_employee_select_key(base: str) -> str:
    """Use a per-auth-session selectbox key so one browser/user cannot keep a stale employee.

    Streamlit selectbox keeps its value by key.  V126 corrected the default index, but if
    the key already existed from a previous user or a previous bad cache, Streamlit kept
    that old value.  V127 makes the key include auth_session_id/employee_id so login user
    changes reset the employee selector safely.
    """
    sid = str(st.session_state.get("auth_session_id") or "").strip()
    emp = str(st.session_state.get("auth_employee_id") or "").strip()
    user = str(st.session_state.get("auth_username") or "").strip()
    raw = "_".join([base, sid[:16] or user or "anon", emp or "noemp"])
    return "".join(ch if ch.isalnum() or ch in "_-." else "_" for ch in raw)


def _v127_clear_legacy_employee_select_state() -> None:
    """Remove stale V126 fixed-key employee selectors after V127 is active."""
    for k in ("start_emp_v126", "end_emp_v126"):
        try:
            st.session_state.pop(k, None)
        except Exception:
            pass

# ===== END V127 EMPLOYEE SELECTBOX SESSION ISOLATION =====


# ===== V141 SELECTED EMPLOYEE / ACTIVE WORK STRICT BINDING =====
def _v141_norm_employee_text(value) -> str:
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


def _v141_parse_employee_label(label: str) -> tuple[str, str]:
    """Support both fullwidth and normal separators: SPT001｜王小明 / SPT001 | 王小明."""
    text = _v141_norm_employee_text(label)
    if not text:
        return "", ""
    parts = [p.strip() for p in re.split(r"\s*[｜|]\s*", text, maxsplit=1)]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return text, ""


def _v141_selected_employee(label: str, employees_df: pd.DataFrame) -> tuple[str, str, dict]:
    emp_id, emp_name = _v141_parse_employee_label(label)
    if employees_df is None or employees_df.empty:
        return emp_id, emp_name, {}
    work = employees_df.copy()
    for c in ["employee_id", "employee_name"]:
        if c not in work.columns:
            work[c] = ""
    emp_id_key = emp_id.casefold()
    emp_name_key = emp_name.casefold()
    match = work[work["employee_id"].fillna("").astype(str).str.strip().str.casefold() == emp_id_key]
    if emp_name_key and not match.empty:
        named = match[match["employee_name"].fillna("").astype(str).str.strip().str.casefold() == emp_name_key]
        if not named.empty:
            match = named
    if match.empty and emp_name_key:
        match = work[work["employee_name"].fillna("").astype(str).str.strip().str.casefold() == emp_name_key]
    if match.empty:
        row = query_one("SELECT * FROM employees WHERE lower(trim(employee_id))=?", (emp_id_key,)) or {}
        return emp_id, emp_name, row
    row = match.iloc[0].fillna("").to_dict()
    return str(row.get("employee_id") or emp_id).strip(), str(row.get("employee_name") or emp_name).strip(), row


def _v141_active_matches_employee(active_row: dict | None, employee_id: str, employee_name: str = "") -> bool:
    if not active_row:
        return False
    got_id = _v141_norm_employee_text(active_row.get("employee_id") or active_row.get("工號 / Employee ID") or active_row.get("工號"))
    got_name = _v141_norm_employee_text(active_row.get("employee_name") or active_row.get("姓名 / Name") or active_row.get("姓名"))
    if employee_id and got_id.casefold() != str(employee_id).strip().casefold():
        return False
    if employee_name and got_name and got_name.casefold() != str(employee_name).strip().casefold():
        return False
    return True
# ===== END V141 SELECTED EMPLOYEE / ACTIVE WORK STRICT BINDING =====


# ===== V143 ACTIVE WORK UI STRICT IDENTITY GUARD =====
def _v143_ui_norm(value) -> str:
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


def _v143_ui_key(value) -> str:
    return _v143_ui_norm(value).casefold()


def _v143_ui_record_key_emp(row: dict) -> str:
    rk = _v143_ui_norm(row.get("record_key") or row.get("紀錄鍵 / Record Key") or row.get("Record Key"))
    return rk.split("|", 1)[0].strip() if "|" in rk else ""


def _v143_ui_identity_values(row: dict, cols: list[str]) -> list[str]:
    vals = []
    for c in cols:
        v = _v143_ui_norm(row.get(c))
        if v and v not in vals:
            vals.append(v)
    return vals


def _v143_ui_row_matches_selected(row: dict | pd.Series | None, employee_id: str, employee_name: str = "") -> bool:
    if row is None:
        return False
    if hasattr(row, "to_dict"):
        row = row.to_dict()
    emp_id = _v143_ui_key(employee_id)
    emp_name = _v143_ui_key(employee_name)
    id_cols = ["employee_id", "工號 / Employee ID", "工號", "Employee ID", "員工編號", "人員工號"]
    name_cols = ["employee_name", "姓名 / Name", "姓名", "Name", "員工姓名", "人員姓名"]
    id_vals = _v143_ui_identity_values(row, id_cols)
    rk_emp = _v143_ui_record_key_emp(row)
    if rk_emp:
        id_vals.append(rk_emp)
    id_keys = {_v143_ui_key(v) for v in id_vals if _v143_ui_key(v)}
    name_keys = {_v143_ui_key(v) for v in _v143_ui_identity_values(row, name_cols) if _v143_ui_key(v)}
    if emp_id:
        if not id_keys:
            return False
        if any(k != emp_id for k in id_keys):
            return False
    if emp_name and name_keys and any(k != emp_name for k in name_keys):
        return False
    return True


def _v143_ui_filter_group_for_selected(group_df: pd.DataFrame, employee_id: str, employee_name: str = "") -> pd.DataFrame:
    if group_df is None or not isinstance(group_df, pd.DataFrame) or group_df.empty:
        return pd.DataFrame()
    keep = []
    for _, row in group_df.iterrows():
        if _v143_ui_row_matches_selected(row, employee_id, employee_name):
            keep.append(row.to_dict())
    if not keep:
        return pd.DataFrame(columns=group_df.columns)
    out = pd.DataFrame(keep)
    # 避免畫面上雙語欄位顯示舊人員：若欄位存在，強制與目前選擇人員一致。
    for c in ["employee_id", "工號 / Employee ID", "工號", "Employee ID"]:
        if c in out.columns:
            out[c] = employee_id
    for c in ["employee_name", "姓名 / Name", "姓名", "Name"]:
        if c in out.columns and employee_name:
            out[c] = employee_name
    return out.reset_index(drop=True)


def _v143_ui_identity_debug_text(row: dict | None) -> str:
    if not row:
        return ""
    if hasattr(row, "to_dict"):
        row = row.to_dict()
    fields = []
    for c in ["id", "employee_id", "工號 / Employee ID", "employee_name", "姓名 / Name", "record_key"]:
        v = _v143_ui_norm(row.get(c))
        if v:
            fields.append(f"{c}={v}")
    return "；".join(fields)
# ===== END V143 ACTIVE WORK UI STRICT IDENTITY GUARD =====

# V13: 01 opens from latest memory files/SQLite without doing heavy master restore inline.
employees = load_employees_for_time_record_fast(active_only=True, in_factory_only=False)
work_orders = load_work_orders_for_time_record_fast(active_only=True)

# V11: master-data existence must be checked before employee account filtering.
# A normal operator may only see one employee, or zero if not bound.  That should
# not be treated as missing 03/04 master data.
has_employees_master, has_work_orders_master = has_master_data_for_time_record_fast(employees, work_orders)

if employees.empty or work_orders.empty:
    if st.session_state.get("_spt_employee_binding_required"):
        st.warning("該人員未在人員名單，請洽管理員設定。")
    elif not has_employees_master or not has_work_orders_master:
        st.warning("請先到『03. 製令管理』與『04. 人員名單』匯入或新增資料。")
    else:
        st.warning("目前帳號可用資料為空，請確認帳號是否已綁定人員或是否具備此模組權限。")
    st.stop()

left, right = st.columns([1.1, 1])
_employee_options_v126, _login_employee_index_v126 = _v126_employee_options_and_login_index(employees)
_v127_clear_legacy_employee_select_state()

with left:
    st.subheader("開始作業 / Start Work")
    emp_label = st.selectbox("工號 / 姓名｜Employee", _employee_options_v126, index=_login_employee_index_v126, key=_v127_employee_select_key("start_emp_v127"))
    emp_id, emp_name, employee = _v141_selected_employee(emp_label, employees)

    # V105：製令欄改為「輸入關鍵字 → 自動刷新 → 下方製令下拉跟著縮小範圍」。
    # 不需要按 Enter；輸入停頓後會以 URL query 觸發一次 rerun，避免另外做遮罩搜尋層。
    _v105_prepare_live_work_order_keyword_state("start_work_order_manual_query_v103")
    wo_manual_query = st.text_input(
        "製令關鍵字｜Work Order Keyword（可手動輸入；輸入 25M 會篩選下方製令）",
        value="",
        key="start_work_order_manual_query_v103",
        placeholder="輸入 2、25M、21M0241、P/N、機型關鍵字；需按 Enter，下方製令會自動篩選",
    )
    _v105_inject_live_work_order_keyword_sync()
    _wo_query = str(wo_manual_query or "").strip()
    _wo_options = _v103_work_order_filtered_options(work_orders, _wo_query, limit=120)
    if not _wo_options:
        _wo_options = ["＋ 使用手動輸入：" + _wo_query] if _wo_query else []
    wo_label = st.selectbox(
        "製令｜Work Order",
        _wo_options,
        index=0,
        key=f"start_work_order_select_v103_{_v100_norm(_wo_query)[:40] or 'all'}",
        help="會依上方輸入即時篩選；若主檔沒有資料，可選擇『使用手動輸入』直接記錄。",
    )
    wo_no = _v103_work_order_option_to_no(wo_label, _wo_query)
    work_order = _v100_find_work_order_dict(work_orders, wo_no)
    if _wo_query:
        matched_count = len([x for x in _wo_options if not str(x).startswith("＋ 使用手動輸入：")])
        st.caption(f"已依『{_wo_query}』篩選出 {matched_count} 筆相關製令，目前使用：{wo_no}")

    category_choices = load_process_category_choices(include_common=True)
    default_category = get_default_process_category()
    if default_category not in category_choices:
        category_choices.append(default_category)
    selected_category = st.selectbox(
        "類別｜Category",
        category_choices,
        index=category_choices.index(default_category) if default_category in category_choices else 0,
        key="time_record_process_category_v333",
    )
    PROCESS_OPTIONS = get_process_options_by_category_exact(selected_category)
    st.caption(f"目前工段類別 / Current Category：{selected_category or '全部 / 通用'}")
    if PROCESS_OPTIONS:
        process = st.selectbox("工段名稱｜Process", PROCESS_OPTIONS)
        no_process_options = False
    else:
        process = ""
        no_process_options = True
        st.warning(
            f"目前類別『{selected_category}』尚未在 13｜系統設定 → 一、類別與工段名稱設定 / Category & Process Options 設定任何啟用的工段名稱。請先完成設定並永久儲存。"
        )
    remark = st.text_area("備註｜Remark", height=90)
    auto_pause = st.checkbox("切換不同工段時，自動暫停同人員其他未結束作業｜Auto pause different process", value=True)

    try:
        refresh_active_records_for_employee(emp_id, str(employee.get("employee_name") or "").strip(), reason="01_start_active_visible_v133")
    except Exception:
        pass
    active = get_active_record(emp_id)
    duplicate = None if no_process_options else get_active_same_work(emp_id, wo_no, process, employee_name=str(employee.get("employee_name") or "").strip())
    conflicts = pd.DataFrame() if no_process_options else get_conflicting_active_records(emp_id, process, employee_name=str(employee.get("employee_name") or "").strip())
    if active:
        group = get_active_group(int(active["id"]))
        st.info(f"目前作業中：{active['process_name']}，同步計時 {len(group)} 筆。同工段不同製令可同步作業；不同工段需先暫停舊紀錄。")
    if duplicate:
        st.error(f"禁止重複紀錄：此人員已有相同製令與工段正在計時：{wo_no} / {process}")
    confirm_pause = True
    if not conflicts.empty:
        st.warning(f"此人員目前有 {len(conflicts)} 筆不同工段正在計時。若要開始新工段，系統會先暫停前一工段紀錄，請確認。")
        render_table(conflicts, "start_conflicting_active_records", editable=False, height=180)
        confirm_pause = st.checkbox("我確認先暫停前一個不同工段紀錄，再開始新紀錄", value=False, key="confirm_pause_before_start")

    if st.button("⏱ 開始作業 / Start", use_container_width=True, disabled=no_process_options or bool(duplicate) or (not confirm_pause)):
        if not check_permission("01_time_record", "can_create"):
            st.error("權限不足：你沒有新增工時紀錄權限。")
        else:
            try:
                rid = start_work(employee, work_order, process, remark, auto_pause_old=(confirm_pause if not conflicts.empty else auto_pause))
                trigger_post_record_continue_prompt(
                    f"已開始作業，紀錄編號：{rid}。請確認是否繼續操作下一筆紀錄；若不繼續，系統會立即登出帳號。",
                    title="已開始計時",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

with right:
    st.subheader("結束目前作業 / Finish Work")
    emp_label2 = st.selectbox("選擇人員｜Employee", _employee_options_v126, index=_login_employee_index_v126, key=_v127_employee_select_key("end_emp_v127"))
    emp_id2, _emp2_name, _emp2_row = _v141_selected_employee(emp_label2, employees)
    try:
        refresh_active_records_for_employee(emp_id2, _emp2_name, reason="01_finish_active_visible_v141")
    except Exception:
        pass
    try:
        active2 = get_active_record(emp_id2, employee_name=_emp2_name)
    except TypeError:
        active2 = get_active_record(emp_id2)
    if active2 and (not _v141_active_matches_employee(active2, emp_id2, _emp2_name) or not _v143_ui_row_matches_selected(active2, emp_id2, _emp2_name)):
        st.error(
            "Active Work 人員不一致，已停止顯示其他人員資料。"
            f"目前選擇：{emp_id2} {_emp2_name}；讀到資料：{_v143_ui_identity_debug_text(active2)}。"
            "請按重新整理；若仍出現，代表 01/02 權威檔有舊版身份欄位污染，需由管理員執行資料修復。"
        )
        active2 = None
    if not active2:
        st.success("此人員目前沒有未結束作業。")
    else:
        raw_group_df = get_active_group(int(active2["id"]))
        group_df = _v143_ui_filter_group_for_selected(raw_group_df, emp_id2, _emp2_name)
        if group_df.empty:
            st.error(
                "目前作業中資料已被擋下：系統讀到的群組資料不屬於目前選擇人員，為避免誤結束他人工時，已停止顯示。請重新整理；若仍出現，請由管理員檢查 01/02 權威檔身份欄位。"
            )
        else:
            st.markdown(
                f"""
<div class="spt-card spt-glow">
<b>目前作業中 / Active Work</b><br>
選擇人員：{emp_id2} {_emp2_name}<br>
工段：{active2['process_name']}<br>
同步計時：{len(group_df)} 筆<br>
說明：按下暫停、下班或完工時，會同步結束同一人員、同一天、同一工段的所有未結束計時，並平均分配工時。<br>
</div>
""",
                unsafe_allow_html=True,
            )
            render_table(group_df, "active_parallel_group", editable=False, height=230)
        end_remark = st.text_input("結束備註｜Finish Remark", key="end_remark", disabled=group_df.empty)
        c1, c2, c3 = st.columns(3)
        if c1.button("⏸ 暫停 / Pause", use_container_width=True, disabled=group_df.empty):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                n = finish_work(active2["id"], "暫停", end_remark, finish_parallel_group=True)
                trigger_post_record_continue_prompt(f"已同步暫停 {n} 筆並平均計算工時。", title="工時已暫停")
                st.rerun()
        if c2.button("⟡ 完工 / Complete", use_container_width=True):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                n = finish_work(active2["id"], "完工", end_remark, finish_parallel_group=True)
                trigger_post_record_continue_prompt(f"已同步完工 {n} 筆並平均計算工時。", title="工時已完工")
                st.rerun()
        if c3.button("◐ 下班 / Off Duty", use_container_width=True, disabled=group_df.empty):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                n = finish_work(active2["id"], "下班", end_remark, finish_parallel_group=True)
                trigger_post_record_continue_prompt(f"已同步下班 {n} 筆並平均計算工時。", title="工時已結束")
                st.rerun()

st.divider()
st.subheader("今日工時紀錄 / Today Records")
try:
    _reset_time = get_live_page_reset_time()
except Exception:
    _reset_time = "02:00"
st.caption(f"顯示規則：重新整理前會顯示當日作業明細；每日 {_reset_time} 後會自動隱藏已結束紀錄。按下立即重新整理後，會立刻隱藏目前所有已結束紀錄，只保留未結束作業；02｜歷史紀錄不受影響。")
user = get_current_user() or {}
is_admin = "admin" in [str(x).lower() for x in user.get("roles", [])]
show_unfinished_only = False
if is_admin:
    c_filter1, c_filter2 = st.columns([1.3, 2.7])
    with c_filter1:
        show_unfinished_only = st.checkbox("只顯示未結束目前作業 / Unfinished only", value=False, key="today_unfinished_only")
    with c_filter2:
        if st.button("⚡ 立即重新整理 01 顯示（隱藏舊週期已完工，不影響 02 歷史紀錄）", use_container_width=True, key="clear_today_finished_view"):
            n = clear_today_finished_from_work_page()
            try:
                clear_today_records_fast_cache()
            except Exception:
                pass
            st.success(f"已重新整理 01 頁顯示；02 歷史紀錄不受影響。已隱藏目前已結束筆數：{n}")
            st.rerun()
df = today_records(include_finished=not show_unfinished_only, unfinished_only=show_unfinished_only)
if is_admin and not df.empty:
    with st.expander("▤ 01 工時紀錄表格欄位位置順序調整 / Admin Column Order Settings", expanded=False):
        st.caption("此區僅系統管理員可見。可調整今日工時紀錄表格的欄位寬度與欄位位置順序；設定會永久保存。")
        render_width_settings("01.time_records.main", df, title="01 工時紀錄欄位順序與欄寬設定 / Column Order and Width")
render_table(df, "01.time_records.main", editable=False, height=420)

# V1.81 + V92：修改、刪除、存檔功能只允許管理員看見與操作。
# V92：所有維護區按鈕改成「同一次 rerun 立即生效」，不再依賴先 st.rerun 再期待 data_editor 狀態更新。
#      同時直接合併 data_editor widget delta，避免勾選/編輯被舊前端草稿蓋回。
def _v92_to_int_id(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    s = str(value).strip()
    if not s or s.lower() in {"none", "nan", "nat", "<na>"}:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _v92_find_id_col(frame: pd.DataFrame) -> str:
    for col in ["id", "ID", "ID / ID", "ID / ID / ID", "紀錄編號", "record_id"]:
        if col in frame.columns:
            vals = frame[col].dropna().tolist()
            if any(_v92_to_int_id(x) is not None for x in vals):
                return col
    return ""


def _v92_editor_state_to_df(base_df: pd.DataFrame, returned_df, editor_key: str) -> pd.DataFrame:
    """Merge Streamlit data_editor deltas into a DataFrame before action buttons run."""
    if isinstance(returned_df, pd.DataFrame):
        out = returned_df.copy()
    else:
        out = base_df.copy()
    try:
        state = st.session_state.get(editor_key, {})
        if isinstance(state, dict):
            edited_rows = state.get("edited_rows") or {}
            for row_idx, changes in edited_rows.items():
                try:
                    idx = int(row_idx)
                except Exception:
                    continue
                if not isinstance(changes, dict) or idx < 0 or idx >= len(out):
                    continue
                for col, val in changes.items():
                    if col in out.columns:
                        out.iat[idx, out.columns.get_loc(col)] = val
            deleted_rows = state.get("deleted_rows") or []
            if deleted_rows:
                drop_idx = []
                for row_idx in deleted_rows:
                    try:
                        idx = int(row_idx)
                        if 0 <= idx < len(out):
                            drop_idx.append(out.index[idx])
                    except Exception:
                        pass
                if drop_idx:
                    out = out.drop(index=drop_idx).reset_index(drop=True)
            added_rows = state.get("added_rows") or []
            if added_rows:
                rows = [r for r in added_rows if isinstance(r, dict)]
                if rows:
                    out = pd.concat([out, pd.DataFrame(rows)], ignore_index=True)
    except Exception:
        pass
    return out.reset_index(drop=True)


def _v92_checked_ids(frame: pd.DataFrame, delete_col: str, id_col: str) -> list[int]:
    ids: list[int] = []
    if frame is None or frame.empty or not delete_col or not id_col:
        return ids
    if delete_col not in frame.columns or id_col not in frame.columns:
        return ids
    try:
        def _checked(v):
            if isinstance(v, str):
                return v.strip().lower() in {"1", "true", "yes", "y", "on", "是", "勾選"}
            return bool(v)
        mask = frame[delete_col].map(_checked)
        for x in frame.loc[mask, id_col].tolist():
            rid = _v92_to_int_id(x)
            if rid is not None and rid not in ids:
                ids.append(rid)
    except Exception:
        return []
    return ids


if is_admin:
    st.divider()
    with st.expander("▤ 管理員工時紀錄維護｜修改、刪除、存檔", expanded=False):
        st.warning("此區僅管理員可見。V92 起維護按鈕會在同一次畫面立即生效，並同步合併表格最新勾選/編輯狀態。")
        admin_load_key = "today_records_admin_load_v92"
        admin_select_key = "_spt_select_today_records_admin_delete_ids_v92"
        editor_version_key = "today_records_admin_editor_version_v92"
        if editor_version_key not in st.session_state:
            st.session_state[editor_version_key] = 0

        ca, cb, cc = st.columns([1.2, 1.2, 2.2])
        load_clicked = ca.button("▤ 載入維護表格 / Load", use_container_width=True, key="today_records_admin_load_btn_v92")
        unload_clicked = cb.button("⟳ 卸載維護表格 / Unload", use_container_width=True, key="today_records_admin_unload_btn_v92")
        cc.caption("一般開始/暫停/完工/下班不會重建此表格；正式修改時再載入，可縮短 01 頁面點選時間。")

        if load_clicked:
            st.session_state[admin_load_key] = True
            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
            try:
                clear_today_records_fast_cache()
            except Exception:
                pass
        if unload_clicked:
            st.session_state[admin_load_key] = False
            st.session_state[admin_select_key] = []
            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1

        if not st.session_state.get(admin_load_key, False):
            st.info("管理員維護表格尚未載入。平常作業記錄不需要載入此區，避免拖慢 01 工時紀錄。")
        else:
            try:
                clear_today_records_fast_cache()
            except Exception:
                pass
            admin_source_df = today_records(include_finished=not show_unfinished_only, unfinished_only=show_unfinished_only)
            if admin_source_df is None or admin_source_df.empty:
                st.info("今日目前沒有可維護的工時紀錄。")
            else:
                admin_df = admin_source_df.copy().reset_index(drop=True)
                _id_col = _v92_find_id_col(admin_df)
                _all_admin_ids: list[int] = []
                if _id_col:
                    for _x in admin_df[_id_col].tolist():
                        _rid = _v92_to_int_id(_x)
                        if _rid is not None and _rid not in _all_admin_ids:
                            _all_admin_ids.append(_rid)
                _all_admin_id_set = set(_all_admin_ids)

                sc1, sc2, sc3 = st.columns([1, 1, 3])
                select_clicked = sc1.button("◈ 勾選全部紀錄 / Select All", use_container_width=True, key="today_admin_select_all_rows_v92")
                clear_clicked = sc2.button("◌ 取消全部勾選 / Clear All", use_container_width=True, key="today_admin_clear_all_rows_v92")
                sc3.caption("勾選會保留到你手動取消、刪除成功或卸載本表格；按下全選/取消會立即反映，不必等下一次 rerun。")

                if select_clicked:
                    st.session_state[admin_select_key] = list(_all_admin_ids)
                    st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                elif clear_clicked:
                    st.session_state[admin_select_key] = []
                    st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1

                _selected_admin_ids: set[int] = set()
                for _x in st.session_state.get(admin_select_key, []):
                    _rid = _v92_to_int_id(_x)
                    if _rid is not None and _rid in _all_admin_id_set:
                        _selected_admin_ids.add(_rid)

                delete_col = "刪除 / Delete"
                if delete_col in admin_df.columns:
                    admin_df = admin_df.drop(columns=[delete_col], errors="ignore")
                if _id_col:
                    admin_df.insert(0, delete_col, admin_df[_id_col].map(lambda x: (_v92_to_int_id(x) in _selected_admin_ids)))
                else:
                    admin_df.insert(0, delete_col, False)
                    st.warning("此表格找不到可用 ID 欄位，刪除/重算按鈕將無法定位正式紀錄。")

                editor_key = f"today_records_admin_editor_v92_{st.session_state[editor_version_key]}"
                st.info("V92：載入、卸載、全選、取消、儲存、重算、刪除按鈕已改成即時狀態同步，不再只改畫面草稿。")

                try:
                    from services.table_ui_service import apply_column_order, build_column_config
                    display_admin = apply_column_order("today_records_admin_maintenance", admin_df)
                    column_cfg = build_column_config("today_records_admin_maintenance", display_admin)
                except Exception:
                    display_admin = admin_df.copy()
                    column_cfg = {}
                # V94：避免共用 column_config 將文字欄誤設成 Checkbox/Number 造成 StreamlitAPIException。
                #      先確保刪除欄為純 bool，再只保留目前表格實際存在的 column_config；若仍失敗，改用最小設定 fallback。
                if delete_col in display_admin.columns:
                    display_admin[delete_col] = display_admin[delete_col].map(lambda v: _v92_to_int_id(v) is not None if str(v).strip().isdigit() else bool(v)).astype(bool)
                try:
                    column_cfg = {k: v for k, v in dict(column_cfg).items() if k in display_admin.columns}
                except Exception:
                    column_cfg = {}
                column_cfg[delete_col] = st.column_config.CheckboxColumn("刪除 / Delete", width=120)
                disabled_cols = [c for c in ["id", "ID", "ID / ID", "ID / ID / ID", "record_key", "紀錄鍵 / Record Key", "created_at", "建立時間 / Created At", "updated_at", "更新時間 / Updated At"] if c in display_admin.columns]
                # V120：管理員維護表改成穩定送出模式。
                # data_editor 與儲存 / 重算 / 刪除放在同一個 form，避免修改一格就 rerun 跳頁。
                with st.form("v120_today_admin_maintenance_stable_editor_form", clear_on_submit=False):
                    try:
                        edited_admin_return = _v95_raw_data_editor(
                            display_admin,
                            use_container_width=True,
                            hide_index=True,
                            column_config=column_cfg,
                            disabled=disabled_cols,
                            num_rows="fixed",
                            key=editor_key,
                            height=460,
                        )
                    except Exception as _v94_editor_error:
                        st.warning(f"維護表格欄位型態設定已自動降級，避免畫面中斷：{_v94_editor_error}")
                        safe_column_cfg = {delete_col: st.column_config.CheckboxColumn("刪除 / Delete", width=120)}
                        edited_admin_return = _v95_raw_data_editor(
                            display_admin,
                            use_container_width=True,
                            hide_index=True,
                            column_config=safe_column_cfg,
                            disabled=disabled_cols,
                            num_rows="fixed",
                            key=f"{editor_key}_safe",
                            height=460,
                        )
                        editor_key = f"{editor_key}_safe"
                    b1, b2, b3 = st.columns(3)
                    do_save = b1.form_submit_button("💾 僅儲存修改 / Save", type="primary", use_container_width=True)
                    do_recalc = b2.form_submit_button("🧮 重算勾選工時並同步 02 / Recalc", use_container_width=True)
                    do_delete = b3.form_submit_button("🗑 刪除勾選整列 / Delete", use_container_width=True)

                edited_admin = _v92_editor_state_to_df(display_admin, edited_admin_return, editor_key)

                manual_ids = _v92_checked_ids(edited_admin, delete_col, _id_col)
                if manual_ids or clear_clicked:
                    st.session_state[admin_select_key] = manual_ids

                if do_save or do_recalc or do_delete:
                    edited_admin = _v92_editor_state_to_df(display_admin, edited_admin_return, editor_key)
                    checked_ids = _v92_checked_ids(edited_admin, delete_col, _id_col)
                    if not checked_ids:
                        checked_ids = [rid for rid in [_v92_to_int_id(x) for x in st.session_state.get(admin_select_key, [])] if rid is not None]
                    checked_ids = [rid for rid in checked_ids if rid in _all_admin_id_set]
                    st.session_state[admin_select_key] = checked_ids

                    if do_save:
                        save_df = edited_admin.drop(columns=[delete_col], errors="ignore")
                        count = save_time_records(save_df)
                        try:
                            clear_today_records_fast_cache()
                        except Exception:
                            pass
                        st.success(f"已由管理員存檔修改 {count} 筆今日工時紀錄。")
                        st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                        st.rerun()
                    elif do_recalc:
                        if not checked_ids:
                            st.warning("請先在『刪除 / Delete』勾選欄勾選要重新計算的紀錄，或按『勾選全部紀錄』，再按重算。")
                        else:
                            save_df = edited_admin.drop(columns=[delete_col], errors="ignore")
                            save_time_records(save_df, recalc_edited_timestamps=True)
                            count = recalculate_time_records(checked_ids)
                            try:
                                clear_today_records_fast_cache()
                            except Exception:
                                pass
                            st.success(f"已先同步修改後的開始/結束日期時間，並重新計算 {count} 筆工時，同步更新到 02 歷史紀錄。")
                            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                            st.rerun()
                    elif do_delete:
                        if not checked_ids:
                            st.warning("請先在『刪除 / Delete』勾選欄勾選要刪除的紀錄，或按『勾選全部紀錄』，再按刪除。")
                        else:
                            count = delete_time_records(checked_ids, reason="01 工時紀錄管理員維護區刪除")
                            st.session_state[admin_select_key] = []
                            try:
                                clear_today_records_fast_cache()
                            except Exception:
                                pass
                            st.success(f"已由管理員刪除 {count} 筆今日工時紀錄。")
                            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                            st.rerun()

