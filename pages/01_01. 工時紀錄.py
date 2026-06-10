# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

try:
    from services.performance_profiler_service import record_event as _spt_perf_record_event
except Exception:  # pragma: no cover
    _spt_perf_record_event = None  # type: ignore

try:
    from services.log_service import write_log as _spt_perf_write_log
except Exception:  # pragma: no cover
    _spt_perf_write_log = None  # type: ignore

_SPT_01_PAGE_T0 = time.perf_counter()


def _spt_perf_tick(name: str, start: float, *, threshold_ms: float = 300.0, detail: dict | None = None) -> float:
    duration_ms = (time.perf_counter() - start) * 1000.0
    if callable(_spt_perf_record_event):
        try:
            _spt_perf_record_event(
                category="01_page",
                name=name,
                duration_ms=duration_ms,
                ok=True,
                threshold_ms=threshold_ms,
                detail=detail or {},
            )
        except Exception:
            pass
    # V96: page-load profiling must not synchronously write LOG records.
    # The LOG write itself can open Neon connections while 01 is rendering and make
    # a slow page even slower.  Keep lightweight in-process profiler events only;
    # 99 diagnostics can read those, and write paths still keep formal operation logs.
    if False and duration_ms >= 3000 and callable(_spt_perf_write_log):
        try:
            _spt_perf_write_log(
                "PERF_01_SLOW",
                f"01 工時紀錄慢動作：{name} = {duration_ms:.0f} ms",
                "performance",
                detail=str(detail or {}),
                level="WARN",
            )
        except Exception:
            pass
    return time.perf_counter()


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


# ===== V259 FOREGROUND DISPLAY ISOLATION =====
# Goal: keep the operation panels usable immediately. Heavy read-only tables are
# loaded only when the user asks for them, and cached in session state so every
# button/rerun does not rebuild the entire page.
V259_TODAY_TABLE_KEY = "v259_01_today_records_df"
V259_TODAY_TABLE_TS_KEY = "v259_01_today_records_loaded_at"
V259_TODAY_TABLE_META_KEY = "v259_01_today_records_meta_v96"
V259_TODAY_TABLE_VISIBLE_KEY = "v103_01_today_records_visible"
V259_FINISHED_KEY_PREFIX = "v259_01_finished_today_df_"
V259_FINISHED_TS_PREFIX = "v259_01_finished_today_loaded_at_"
V259_FINISHED_VISIBLE_PREFIX = "v103_01_finished_today_visible_"


def _v259_now_label() -> str:
    try:
        from services.timezone_service import now_text
        return str(now_text())
    except Exception:
        try:
            from datetime import datetime
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""


def _v259_finish_key(employee_id: str, employee_name: str) -> tuple[str, str]:
    safe = re.sub(r"[^0-9A-Za-z_\-]+", "_", f"{employee_id}_{employee_name}")[:80]
    return V259_FINISHED_KEY_PREFIX + safe, V259_FINISHED_TS_PREFIX + safe


def _v103_finished_visible_key(employee_id: str, employee_name: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_\-]+", "_", f"{employee_id}_{employee_name}")[:80]
    return V259_FINISHED_VISIBLE_PREFIX + safe


def _v259_clear_display_cache() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith(V259_FINISHED_KEY_PREFIX) or str(key).startswith(V259_FINISHED_TS_PREFIX) or str(key).startswith(V259_FINISHED_VISIBLE_PREFIX):
            try:
                del st.session_state[key]
            except Exception:
                pass
    for key in [V259_TODAY_TABLE_KEY, V259_TODAY_TABLE_TS_KEY, V259_TODAY_TABLE_META_KEY, V259_TODAY_TABLE_VISIBLE_KEY]:
        try:
            st.session_state.pop(key, None)
        except Exception:
            pass


def _v259_notice_cached(label: str, ts_key: str) -> None:
    ts = st.session_state.get(ts_key)
    if ts:
        st.caption(f"{label}：已有快取資料，最後刷新 {ts}。為加快 01 開頁速度，重表格只在按下顯示/重新整理後渲染。")
    else:
        st.caption(f"{label}：為避免每次操作卡住，預設不自動載入重表格；請按重新整理載入。")


def _v103_light_table_controls(prefix: str, visible_key: str, *, has_data: bool) -> tuple[bool, bool]:
    """Return (show_clicked, hide_clicked) for heavy read-only sections.

    Streamlit reruns the full page on every widget interaction.  If cached tables
    are rendered automatically after they were once loaded, simply entering 01
    can rebuild several large table components and make the page appear stuck.
    These controls keep cached data in memory/permanent storage, but render the
    heavy component only when the operator explicitly asks to display it.
    """
    if not has_data:
        return False, False
    c1, c2, c3 = st.columns([1.15, 1.15, 2.7])
    show_clicked = c1.button(f"顯示{prefix}", use_container_width=True, key=f"v103_show_{_v84_safe_widget_part(prefix)}")
    hide_clicked = c2.button(f"隱藏{prefix}", use_container_width=True, key=f"v103_hide_{_v84_safe_widget_part(prefix)}")
    if show_clicked:
        st.session_state[visible_key] = True
    if hide_clicked:
        st.session_state[visible_key] = False
    c3.caption("資料快取仍保留；隱藏時不建立表格元件，可加快 01 頁完整顯示。")
    return show_clicked, hide_clicked


def _v84_safe_widget_part(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-]+", "_", str(text or "")).strip("_")[:90] or "table"


def _v84_current_column_order(table_key: str, df: pd.DataFrame) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    current = [str(c) for c in df.columns]
    current_set = set(current)
    try:
        saved = [str(c) for c in load_column_order(table_key)]
    except Exception:
        saved = []
    out: list[str] = []
    seen: set[str] = set()
    for col in saved:
        if col in current_set and col not in seen:
            out.append(col)
            seen.add(col)
    for col in current:
        if col not in seen:
            out.append(col)
            seen.add(col)
    return out


def _v84_render_column_settings_panel(table_key: str, df: pd.DataFrame, title: str) -> None:
    """Explicit column settings panel for 01 tables.

    V84 restores the missing Apply/Save button without re-enabling the old global
    column-setting wrapper.  Nothing is auto-saved while the user types; widths and
    order are written only when the form submit button is pressed.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return
    safe_key = _v84_safe_widget_part(table_key)
    # V96: building the full column-settings editor on every 01 render was one
    # major reason the page appeared late.  Render a lightweight expander first;
    # only build the text_area/data_editor settings UI when the user explicitly
    # opens it.  Saved column order/widths are still applied by _v84_apply_table_layout.
    with st.expander(title, expanded=False):
        st.caption("此區只管理本表格欄位順序與欄寬；不會修改工時資料。設定只會在按下『套用並永久儲存欄位設定』後寫入。")
        open_settings = st.toggle(
            "顯示欄位設定 / Show column settings（需要調整時才開啟）",
            value=False,
            key=f"v96_show_column_settings_{safe_key}",
        )
        if not open_settings:
            st.caption("目前只套用已永久儲存的欄位設定；未載入欄位設定編輯器，以加快 01 頁面顯示。")
            return

        current_cols = [str(c) for c in df.columns]
        widths = {}
        try:
            widths = {str(k): int(v) for k, v in load_widths(table_key).items()}
        except Exception:
            widths = {}
        ordered = _v84_current_column_order(table_key, df)
        if not ordered:
            ordered = current_cols

        settings_rows = []
        for col in ordered:
            if col not in current_cols:
                continue
            settings_rows.append({
                "欄位 / Column": col,
                "欄寬 / Width": int(widths.get(col, 140)),
            })
        if not settings_rows:
            settings_rows = [{"欄位 / Column": c, "欄寬 / Width": int(widths.get(c, 140))} for c in current_cols]

        with st.form(f"v84_column_settings_form_{safe_key}", clear_on_submit=False):
            order_text = st.text_area(
                "欄位順序 / Column order（每行一個欄位；上方越前面越靠左）",
                value="\n".join([r["欄位 / Column"] for r in settings_rows]),
                height=220,
                key=f"v84_column_order_text_{safe_key}",
            )
            try:
                width_df = _v95_raw_data_editor(
                    pd.DataFrame(settings_rows),
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed",
                    key=f"v84_width_editor_{safe_key}",
                    column_config={
                        "欄位 / Column": st.column_config.TextColumn("欄位 / Column"),
                        "欄寬 / Width": st.column_config.NumberColumn("欄寬 / Width", min_value=60, max_value=700, step=10),
                    },
                    disabled=["欄位 / Column"],
                    height=300,
                )
            except Exception:
                width_df = pd.DataFrame(settings_rows)
                for idx, row in enumerate(settings_rows):
                    c1, c2 = st.columns([2.8, 1.2])
                    c1.caption(str(row["欄位 / Column"]))
                    width_df.at[idx, "欄寬 / Width"] = c2.number_input(
                        "欄寬", min_value=60, max_value=700, value=int(row.get("欄寬 / Width", 140)), step=10,
                        key=f"v84_width_fallback_{safe_key}_{idx}",
                    )
            b1, b2 = st.columns([1.4, 1])
            apply_settings = b1.form_submit_button("✅ 套用並永久儲存欄位設定 / Apply & Save", type="primary", use_container_width=True)
            reset_settings = b2.form_submit_button("↺ 恢復預設順序 / Reset order", use_container_width=True)

        if apply_settings:
            raw_order = [x.strip() for x in str(order_text or "").splitlines() if x.strip()]
            seen: set[str] = set()
            clean_order: list[str] = []
            for col in raw_order:
                if col in current_cols and col not in seen:
                    clean_order.append(col)
                    seen.add(col)
            for col in current_cols:
                if col not in seen:
                    clean_order.append(col)
                    seen.add(col)
            clean_widths: dict[str, int] = {}
            try:
                for _, row in width_df.iterrows():
                    col = str(row.get("欄位 / Column", "")).strip()
                    if not col or col not in current_cols:
                        continue
                    try:
                        w = int(float(row.get("欄寬 / Width", 140)))
                    except Exception:
                        w = 140
                    clean_widths[col] = max(60, min(700, w))
            except Exception:
                clean_widths = {c: int(widths.get(c, 140)) for c in current_cols}
            try:
                save_widths(table_key, clean_widths)
                save_column_order(table_key, clean_order)
                st.success("欄位設定已套用並永久儲存。")
                st.rerun()
            except Exception as exc:
                st.error(f"欄位設定儲存失敗：{exc}")
        elif reset_settings:
            try:
                save_column_order(table_key, current_cols)
                save_widths(table_key, {c: int(widths.get(c, 140)) for c in current_cols})
                st.success("已恢復本表格預設欄位順序。")
                st.rerun()
            except Exception as exc:
                st.error(f"恢復預設失敗：{exc}")


def _v84_apply_table_layout(table_key: str, df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df, {}
    try:
        out = apply_column_order(table_key, df.copy())
    except Exception:
        out = df.copy()
    try:
        cfg = build_column_config(table_key, out)
    except Exception:
        cfg = {}
    return out, cfg


# ===== V98 01 HOT-PATH READ DEDUP / EDIT-CONFIRM ONLY HELPERS =====
V98_LIGHT_CACHE_TTL_SECONDS = 300.0


def _v98_cache_get(key: str, ttl_seconds: float = V98_LIGHT_CACHE_TTL_SECONDS):
    try:
        item = st.session_state.get(key)
        if not isinstance(item, dict):
            return None
        ts = float(item.get("ts", 0.0) or 0.0)
        if ts and (time.perf_counter() - ts) <= ttl_seconds:
            return item.get("value")
    except Exception:
        pass
    return None


def _v98_cache_set(key: str, value) -> None:
    try:
        st.session_state[key] = {"ts": time.perf_counter(), "value": value}
    except Exception:
        pass


def _v98_load_process_category_bundle_cached() -> tuple[list[str], str]:
    cached = _v98_cache_get("v98_01_process_category_bundle")
    if isinstance(cached, tuple) and len(cached) == 2:
        return list(cached[0] or []), str(cached[1] or "")
    try:
        choices = list(load_process_category_choices(include_common=True))
    except Exception:
        choices = []
    try:
        default = str(get_default_process_category() or "")
    except Exception:
        default = ""
    _v98_cache_set("v98_01_process_category_bundle", (choices, default))
    return choices, default


def _v98_get_process_options_cached(category: str) -> list[str]:
    cache_key = "v98_01_process_options_" + _v84_safe_widget_part(category or "blank")
    cached = _v98_cache_get(cache_key)
    if isinstance(cached, list):
        return list(cached)
    try:
        options = list(get_process_options_by_category_exact(category))
    except Exception:
        options = []
    _v98_cache_set(cache_key, options)
    return options


def _v98_admin_editor_should_parse(*flags: bool) -> bool:
    """Only parse the editable maintenance dataframe when a confirm button was pressed.

    Streamlit reruns while the editor is visible for unrelated controls such as row-limit,
    selection buttons, or column settings.  The 01 maintenance editor must behave like 02:
    editing is foreground draft state only; comparison, timestamp sync, recalculation and
    Neon writes happen only on explicit Save/Recalc/Delete submit buttons.
    """
    return any(bool(x) for x in flags)
# ===== V98 01 HOT-PATH READ DEDUP / EDIT-CONFIRM ONLY HELPERS END =====
# ===== V84 EXPLICIT FIELD SETTINGS END =====
# ===== V259 FOREGROUND DISPLAY ISOLATION END =====

from services.theme_service import apply_theme, render_header
from services.ui_size_service import apply_dropdown_menu_size_only
from services.security_service import (
    check_permission,
    get_current_user,
    require_module_access,
    render_post_record_continue_prompt,
    trigger_post_record_continue_prompt,
    logout,
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
    delete_time_records_from_editor_df,
    recalculate_time_records,
    finish_work,
    get_active_group,
    get_active_record,
    get_active_records,
    get_conflicting_active_records,
    load_records,
    get_active_same_work,
    refresh_active_records_for_employee,
    save_time_records,
    start_work,
    today_records,
)
from services.db_service import query_one
from services.table_ui_service import (
    render_table,
    load_widths,
    save_widths,
    load_column_order,
    save_column_order,
    apply_column_order,
    build_column_config,
)
from services.time_record_delete_unifier_service import delete_selected_time_records_from_editor
from services.system_settings_service import get_process_options_by_category_exact, get_default_process_category, load_process_category_choices, get_live_page_reset_time
from services.timezone_service import now_text, today_text

st.set_page_config(page_title="01. 工時紀錄", page_icon="⏱", layout="wide")
apply_theme()
apply_dropdown_menu_size_only(560)
require_module_access("01_time_record")
render_header("01｜工時紀錄", "快速開始、同步作業、暫停、下班、完工｜自動記錄時間與扣除休息")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("01", "工時紀錄")
except Exception:
    _SPT_V40_PAGE_TOKEN = None

render_post_record_continue_prompt()
_spt_perf_after_header = _spt_perf_tick("01_header_auth_theme", _SPT_01_PAGE_T0, threshold_ms=500.0)


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
    """V77：停用 URL replace 型即時刷新，避免 01 頁在 Streamlit Cloud 反覆整頁 reload。

    製令關鍵字仍保留；使用者按 Enter 或離開輸入框時，Streamlit 會正常 rerun 並篩選下方製令。
    這比前端強制改網址穩定，不會造成看起來像無限運轉的瀏覽器 reload loop。
    """
    return None
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




# ===== V207 ADMIN FINISH WORK IDENTITY GUARD BYPASS =====
def _v207_current_user_is_admin() -> bool:
    """Return True when the logged-in account is a system administrator.

    V208 keeps the same visual UI, but makes the admin check more tolerant:
    username=admin, role/role_code/admin flags, and session-state roles all count.
    Normal users still keep identity protection.
    """
    try:
        user = get_current_user() or {}
    except Exception:
        user = {}
    username = str(user.get("username") or st.session_state.get("auth_username") or "").strip().casefold()
    role_code = str(user.get("role_code") or user.get("role") or st.session_state.get("auth_role_code") or st.session_state.get("auth_role") or "").strip().casefold()
    roles_raw = user.get("roles") or st.session_state.get("auth_roles") or []
    if isinstance(roles_raw, str):
        roles = {r.strip().casefold() for r in re.split(r"[,;|]", roles_raw) if r.strip()}
    else:
        roles = {str(r).strip().casefold() for r in roles_raw if str(r).strip()}
    flags = {str(user.get(k) or st.session_state.get(k) or "").strip().casefold() for k in ("is_admin", "admin", "auth_is_admin")}
    return username == "admin" or role_code == "admin" or "admin" in roles or bool(flags & {"1", "true", "yes", "y"})


def _v208_current_user_can_proxy_employee() -> bool:
    """System admin can select any employee and perform 01 actions on that account.

    This does not alter button appearance or table rendering. It only prevents the
    Finish Work identity guard from blocking admin repair/operation workflows.
    """
    return _v207_current_user_is_admin()
# ===== END V207 ADMIN FINISH WORK IDENTITY GUARD BYPASS =====


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
    """Return True if the row positively belongs to the selected employee.

    V143 was intentionally strict, but it treated any stale bilingual/record_key
    identity value as a hard conflict.  After LOG recovery / 01-02 repair, some
    rows can contain the correct employee_id plus a stale record_key prefix or
    blank/old display-name field.  That caused the same account (e.g. SSS/SSS)
    to be blocked.

    V208 rule:
    - A direct employee_id match is enough to allow the row.
    - If no employee_id is available, a name match is accepted.
    - A stale record_key prefix is only used when no normal employee_id columns
      exist; it must not override a correct employee_id.
    """
    if row is None:
        return False
    if hasattr(row, "to_dict"):
        row = row.to_dict()
    emp_id = _v143_ui_key(employee_id)
    emp_name = _v143_ui_key(employee_name)
    id_cols = ["employee_id", "工號 / Employee ID", "工號", "Employee ID", "員工編號", "人員工號"]
    name_cols = ["employee_name", "姓名 / Name", "姓名", "Name", "員工姓名", "人員姓名"]
    normal_id_keys = {_v143_ui_key(v) for v in _v143_ui_identity_values(row, id_cols) if _v143_ui_key(v)}
    name_keys = {_v143_ui_key(v) for v in _v143_ui_identity_values(row, name_cols) if _v143_ui_key(v)}
    rk_emp = _v143_ui_key(_v143_ui_record_key_emp(row))

    # Correct employee_id wins over stale/legacy display fields.
    if emp_id and emp_id in normal_id_keys:
        return True
    # Only use record_key when there is no trustworthy employee_id field.
    if emp_id and not normal_id_keys and rk_emp == emp_id:
        return True
    # Some legacy/recovery rows only have name, not employee_id.
    if emp_name and emp_name in name_keys and not normal_id_keys:
        return True
    # If no selected id was provided, fall back to name only.
    if not emp_id and emp_name and emp_name in name_keys:
        return True
    return False


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


# ===== V148 TODAY FINISHED RECORDS READ-ONLY PANEL =====
def _v148_blank(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if value is None:
        return True
    return str(value).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _v148_text(value) -> str:
    return "" if _v148_blank(value) else str(value).strip()


def _v148_date_text_from_row(row: dict) -> str:
    for c in ["start_date", "工作日期 / Work Date", "work_date", "開始日期 / Start Date", "開始日期"]:
        v = row.get(c)
        if not _v148_blank(v):
            try:
                dt = pd.to_datetime(v, errors="coerce")
                if not pd.isna(dt):
                    return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
            s = str(v).strip().replace("/", "-")
            if len(s) >= 10:
                return s[:10]
    for c in ["start_timestamp", "開始時間戳 / Start Timestamp", "開始時間 / Start Timestamp", "開始時間"]:
        v = row.get(c)
        if not _v148_blank(v):
            try:
                dt = pd.to_datetime(v, errors="coerce")
                if not pd.isna(dt):
                    return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
            s = str(v).strip().replace("/", "-")
            if len(s) >= 10:
                return s[:10]
    return ""


def _v148_is_finished_row(row: dict) -> bool:
    status = _v148_text(row.get("status") or row.get("狀態 / Status") or row.get("狀態"))
    end_ts = _v148_text(row.get("end_timestamp") or row.get("結束時間戳 / End Timestamp") or row.get("結束時間 / End Timestamp") or row.get("結束時間"))
    end_date = _v148_text(row.get("end_date") or row.get("結束日期 / End Date") or row.get("結束日期"))
    end_time = _v148_text(row.get("end_time") or row.get("結束時刻 / End Time") or row.get("結束時刻"))
    ended_status = status in {"下班", "暫停", "完工", "已結束", "結束", "Off Duty", "Pause", "Complete", "Finished"}
    if status == "作業中" and not end_ts and not end_date and not end_time:
        return False
    return bool(ended_status or end_ts or (end_date and end_time))


def _v148_sort_finished_records(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    sort_col = None
    for c in ["end_timestamp", "結束時間戳 / End Timestamp", "start_timestamp", "開始時間戳 / Start Timestamp", "id", "ID / ID"]:
        if c in out.columns:
            sort_col = c
            break
    if sort_col:
        try:
            if sort_col in {"id", "ID / ID"}:
                out["_v148_sort"] = pd.to_numeric(out[sort_col], errors="coerce")
            else:
                out["_v148_sort"] = pd.to_datetime(out[sort_col], errors="coerce")
            out = out.sort_values("_v148_sort", ascending=False, kind="stable").drop(columns=["_v148_sort"], errors="ignore")
        except Exception:
            pass
    return out.reset_index(drop=True)


def _v148_dedupe_records(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for key_col in ["record_key", "紀錄鍵 / Record Key"]:
        if key_col in out.columns:
            key = out[key_col].fillna("").astype(str).str.strip()
            with_key = out.loc[key.ne("")].drop_duplicates(subset=[key_col], keep="last")
            without_key = out.loc[key.eq("")]
            out = pd.concat([with_key, without_key], ignore_index=True)
            break
    for id_col in ["id", "ID / ID"]:
        if id_col in out.columns:
            try:
                out["_v148_id_key"] = pd.to_numeric(out[id_col], errors="coerce")
                has_id = out["_v148_id_key"].notna()
                out = pd.concat([
                    out.loc[has_id].drop_duplicates(subset=["_v148_id_key"], keep="last"),
                    out.loc[~has_id],
                ], ignore_index=True).drop(columns=["_v148_id_key"], errors="ignore")
            except Exception:
                out = out.drop(columns=["_v148_id_key"], errors="ignore")
            break
    return out.reset_index(drop=True)


def _v148_load_today_finished_records_for_employee(employee_id: str, employee_name: str = "") -> pd.DataFrame:
    """Read-only list for operators to verify today's completed records.

    V98: avoid duplicate reads.  The previous implementation queried both
    load_records(today) and today_records(), then merged/deduped them.  That made
    pressing 「重新整理已結束紀錄」 do two Neon reads for the same date.  Prefer the
    already-loaded Today Records session table when present; otherwise do a single
    bounded history query.
    """
    target_date = today_text()
    source_df = st.session_state.get(V259_TODAY_TABLE_KEY)
    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        try:
            source_df = load_records(start_date=target_date, end_date=target_date)
        except Exception:
            source_df = pd.DataFrame()
    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        return pd.DataFrame()
    merged = _v148_dedupe_records(source_df.copy().reset_index(drop=True))
    keep: list[dict] = []
    for _, row in merged.iterrows():
        row_dict = row.to_dict()
        if _v148_date_text_from_row(row_dict) != str(target_date):
            continue
        if not _v148_is_finished_row(row_dict):
            continue
        if not _v143_ui_row_matches_selected(row_dict, employee_id, employee_name):
            continue
        keep.append(row_dict)
    if not keep:
        return pd.DataFrame()
    return _v148_sort_finished_records(pd.DataFrame(keep))
# ===== END V148 TODAY FINISHED RECORDS READ-ONLY PANEL =====


# ===== V72 ACTIVE-WORK FRONTEND GUARD =====
# Restore the previous 01 behavior without putting heavy calculation on Neon:
# - selected employee's active work is loaded into session cache and rendered as a table;
# - if any active work exists, Start is disabled in the foreground;
# - Start is a two-step confirmation; choosing No logs out immediately;
# - work-hour calculations remain Python-side in time_record_service, Neon only persists transactions.
V72_ACTIVE_CACHE_PREFIX = "v72_01_active_df_"
V72_ACTIVE_LOADED_PREFIX = "v72_01_active_loaded_"
V72_START_CONFIRM_KEY = "v72_01_pending_start_confirm"
V72_ACTIVE_TTL_SECONDS = 45


def _v72_safe_key(*parts) -> str:
    text = "_".join(str(x or "") for x in parts)
    return re.sub(r"[^0-9A-Za-z_\-]+", "_", text)[:120]


def _v72_active_cache_keys(employee_id: str, employee_name: str) -> tuple[str, str]:
    suffix = _v72_safe_key(employee_id, employee_name)
    return V72_ACTIVE_CACHE_PREFIX + suffix, V72_ACTIVE_LOADED_PREFIX + suffix


def _v72_load_active_df(employee_id: str, employee_name: str = "", *, force: bool = False) -> pd.DataFrame:
    df_key, ts_key = _v72_active_cache_keys(employee_id, employee_name)
    now_perf = time.perf_counter()
    cached = st.session_state.get(df_key)
    loaded_perf = float(st.session_state.get(ts_key + "_perf", 0.0) or 0.0)
    if (not force) and isinstance(cached, pd.DataFrame) and loaded_perf and (now_perf - loaded_perf) < V72_ACTIVE_TTL_SECONDS:
        return cached.copy()
    try:
        # V300.26 Neon Free compute guard:
        # Normal active-work refreshes must not evict db_service SELECT caches.
        # The old path called refresh_active_records_for_employee(), which clears
        # backend query caches before every active check when the 45-second
        # foreground TTL expires.  That makes unrelated employee/work-order/today
        # reads miss cache and wakes Neon more often.  Use a normal bounded SELECT
        # for automatic checks; keep the explicit refresh button as the only path
        # that clears backend caches.  Button writes still clear caches immediately.
        if force:
            try:
                df = refresh_active_records_for_employee(employee_id, employee_name=employee_name)
            except TypeError:
                df = refresh_active_records_for_employee(employee_id)
        else:
            df = get_active_records(employee_id=employee_id, employee_name=employee_name)
    except Exception:
        df = pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    st.session_state[df_key] = df.reset_index(drop=True)
    st.session_state[ts_key] = _v259_now_label()
    st.session_state[ts_key + "_perf"] = now_perf
    return st.session_state[df_key].copy()


def _v72_clear_active_cache(employee_id: str = "", employee_name: str = "") -> None:
    if employee_id or employee_name:
        df_key, ts_key = _v72_active_cache_keys(employee_id, employee_name)
        for k in [df_key, ts_key, ts_key + "_perf"]:
            st.session_state.pop(k, None)
        return
    for k in list(st.session_state.keys()):
        if str(k).startswith(V72_ACTIVE_CACHE_PREFIX) or str(k).startswith(V72_ACTIVE_LOADED_PREFIX):
            st.session_state.pop(k, None)


def _v99_elapsed_minutes_from_start(start_series: pd.Series) -> pd.Series:
    """Calculate active elapsed minutes using Taiwan app time, not Streamlit server UTC.

    Streamlit Cloud servers may run in UTC.  Active work timestamps are stored as
    Asia/Taipei local text from services.timezone_service.now_text().  Using
    pd.Timestamp.now() directly makes current time about 8 hours earlier than the
    start timestamp and produces values such as -480 minutes.
    """
    try:
        now_dt = pd.to_datetime(now_text(), errors="coerce")
    except Exception:
        now_dt = pd.Timestamp.now()
    st_dt = pd.to_datetime(start_series, errors="coerce")
    elapsed = ((now_dt - st_dt).dt.total_seconds() / 60.0).round(1)
    try:
        # Active work should never show negative elapsed minutes.  If a record has
        # a future timestamp because of legacy timezone data, display 0.0 instead
        # of a confusing negative value while keeping the raw timestamp visible.
        elapsed = elapsed.mask(elapsed < 0, 0.0)
    except Exception:
        pass
    return elapsed


def _v102_active_work_subtotal_from_start(start_series: pd.Series) -> pd.Series:
    """Return active-work subtotal as HH:MM:SS for display only.

    This replaces the previous decimal-minute display in the Active Work panel.
    It is intentionally a lightweight in-memory calculation and does not query or
    write Neon.  The value is capped at 00:00:00 for future/invalid timestamps so
    operators never see negative running time.
    """
    try:
        now_dt = pd.to_datetime(now_text(), errors="coerce")
    except Exception:
        now_dt = pd.Timestamp.now()
    st_dt = pd.to_datetime(start_series, errors="coerce")
    seconds = (now_dt - st_dt).dt.total_seconds()
    try:
        seconds = seconds.mask(seconds < 0, 0)
        seconds = seconds.fillna(0)
    except Exception:
        pass

    def _fmt(value) -> str:
        try:
            total = int(max(0, float(value)))
        except Exception:
            total = 0
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    try:
        return seconds.apply(_fmt)
    except Exception:
        return pd.Series(["00:00:00"] * len(start_series), index=start_series.index)


def _v99_label_active_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Use the same bilingual labels as Today Records while keeping lightweight HTML."""
    labels = {
        "id": "ID / ID",
        "status": "狀態 / Status",
        "employee_id": "工號 / Employee ID",
        "employee_name": "姓名 / Name",
        "work_order": "製令 / Work Order",
        "work_order_no": "製令號碼 / Work Order No.",
        "part_no": "P/N / Part No.",
        "type_name": "機型 / Type",
        "process_name": "工段名稱 / Process",
        "start_action": "開始動作 / Start Action",
        "start_date": "開始日期 / Start Date",
        "start_time": "開始時間 / Start Time",
        "start_timestamp": "開始時間戳 / Start Timestamp",
        "工時小計 / Work Subtotal": "工時小計 / Work Subtotal",
        "已進行分鐘 / Elapsed Min": "工時小計 / Work Subtotal",
        "remark": "備註 / Remark",
    }
    return df.rename(columns={k: v for k, v in labels.items() if k in df.columns})


def _v72_active_display_df(active_df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(active_df, pd.DataFrame) or active_df.empty:
        return pd.DataFrame()
    df = active_df.copy()
    if "start_timestamp" in df.columns:
        df["工時小計 / Work Subtotal"] = _v102_active_work_subtotal_from_start(df["start_timestamp"])
    columns = [
        "id", "status", "employee_id", "employee_name",
        "work_order", "work_order_no", "part_no", "type_name",
        "process_name", "start_action", "start_date", "start_time",
        "start_timestamp", "工時小計 / Work Subtotal", "remark",
    ]
    keep = [c for c in columns if c in df.columns]
    if not keep:
        return df.head(20)
    out = df[keep].head(20).copy()
    return _v99_label_active_columns(out)


def _v72_render_active_guard(employee_id: str, employee_name: str) -> tuple[pd.DataFrame, bool]:
    c1, c2 = st.columns([1.25, 2.75])
    force = c1.button("重新檢查開始中作業", use_container_width=True, key=f"v72_refresh_active_before_start_{employee_id}_{employee_name}")
    active_df = _v72_load_active_df(employee_id, employee_name, force=force)
    _, ts_key = _v72_active_cache_keys(employee_id, employee_name)
    ts = st.session_state.get(ts_key, "")
    if ts:
        c2.caption(f"開始防呆狀態：{ts} 已檢查。為避免每次下拉都慢，45 秒內使用前台快取；按左側可重新檢查。")
    has_active = isinstance(active_df, pd.DataFrame) and not active_df.empty
    if has_active:
        st.warning("此人員已有開始中的作業。請先在右側按『暫停 / 完工 / 下班』結束後，才可開始新作業。")
        _v77_html_table(_v72_active_display_df(active_df), max_rows=8)
    else:
        st.success("此人員目前沒有開始中的作業，可以開始新作業。")
    return active_df, has_active


def _v72_store_start_confirmation(employee: dict, work_order: dict, process: str, remark: str) -> None:
    st.session_state[V72_START_CONFIRM_KEY] = {
        "employee": dict(employee or {}),
        "work_order": dict(work_order or {}),
        "process": str(process or ""),
        "remark": str(remark or ""),
        "created_at": _v259_now_label(),
    }


def _v72_render_start_confirmation() -> bool:
    """Deprecated by V74.

    Start Work now writes the record immediately, then shows the existing modal via
    trigger_post_record_continue_prompt().  Clear any stale V72 pre-start pending state
    so the old duplicated confirmation block cannot return after deploy.
    """
    try:
        st.session_state.pop(V72_START_CONFIRM_KEY, None)
    except Exception:
        pass
    return False

def _v75_norm_text(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _v75_row_value(row, *cols) -> str:
    for col in cols:
        try:
            if col in row and _v75_norm_text(row.get(col)):
                return _v75_norm_text(row.get(col))
        except Exception:
            pass
    return ""


def _v75_active_start_policy(active_df: pd.DataFrame, selected_process: str, selected_work_order: str) -> dict:
    """Decide whether Start should be enabled.

    Site rule V75:
    - Same employee + same process + different work order is synchronous work and must be allowed.
    - Same employee + same process + same work order is duplicate and must be blocked.
    - Same employee + different process still blocks start until the active work is ended.
    """
    policy = {"has_active": False, "blocked": False, "reason": "", "mode": "new"}
    if not isinstance(active_df, pd.DataFrame) or active_df.empty:
        policy["reason"] = "此人員目前沒有開始中的作業，可以開始新作業。"
        return policy
    proc = _v75_norm_text(selected_process)
    wo = _v75_norm_text(selected_work_order)
    policy["has_active"] = True
    rows = []
    try:
        rows = [r for _, r in active_df.iterrows()]
    except Exception:
        rows = []
    same_process = []
    other_process = []
    duplicate = []
    for row in rows:
        row_proc = _v75_row_value(row, "process_name", "工段", "工段名稱", "Process")
        row_wo = _v75_row_value(row, "work_order", "work_order_no", "製令", "製令號碼", "Work Order")
        if proc and row_proc == proc:
            same_process.append(row)
            if wo and row_wo == wo:
                duplicate.append(row)
        else:
            other_process.append(row)
    if duplicate:
        policy.update({
            "blocked": True,
            "mode": "duplicate",
            "reason": f"此人員已有相同製令與工段正在計時：{wo} / {proc}，不可重複開始。",
        })
    elif other_process:
        policy.update({
            "blocked": True,
            "mode": "other_process",
            "reason": "此人員已有不同工段的開始中作業，請先在右側暫停 / 完工 / 下班後，才能開始新工段。",
        })
    elif same_process:
        policy.update({
            "blocked": False,
            "mode": "sync_same_process",
            "reason": "此人員已有同工段開始中作業；不同製令、同工段可繼續開始同步作業。結束任一筆時會同步結束同工段所有開始中紀錄並平均工時。",
        })
    else:
        policy.update({
            "blocked": True,
            "mode": "unknown",
            "reason": "此人員已有開始中作業，但系統無法判斷同步工段，請先在右側結束目前作業後再開始。",
        })
    return policy


def _v74_render_start_status(active_df: pd.DataFrame, selected_process: str = "", selected_work_order: str = "") -> dict:
    """Render one compact status block and return V75 start policy."""
    policy = _v75_active_start_policy(active_df, selected_process, selected_work_order)
    mode = policy.get("mode")
    msg = str(policy.get("reason") or "")
    if mode == "new":
        st.success(msg)
    elif mode == "sync_same_process":
        st.info(msg)
    elif policy.get("blocked"):
        st.warning(msg)
    else:
        st.info(msg)
    return policy


V101_ACTIVE_WORK_TABLE_KEY = "01.time_records.active_work"


def _v101_active_work_widths(table_key: str, columns: list[str]) -> dict[str, int]:
    """Load saved widths for Active Work without touching the time-record query path."""
    try:
        raw = load_widths(table_key)
        if isinstance(raw, dict):
            out = {str(k): max(60, min(700, int(float(v)))) for k, v in raw.items() if str(k) in columns}
            # V102: keep old saved width useful after renaming Elapsed Min to Work Subtotal.
            old_key = "已進行分鐘 / Elapsed Min"
            new_key = "工時小計 / Work Subtotal"
            if new_key in columns and new_key not in out and old_key in raw:
                try:
                    out[new_key] = max(60, min(700, int(float(raw.get(old_key)))))
                except Exception:
                    out[new_key] = 112
            return out
    except Exception:
        pass
    return {}


def _v101_apply_active_work_layout(df: pd.DataFrame, table_key: str = V101_ACTIVE_WORK_TABLE_KEY) -> pd.DataFrame:
    """Apply persisted Active Work column order only on the in-memory display frame.

    This keeps the right-side Active Work table close to Today Records behavior
    without using st.dataframe/data_editor.  It does not query time records,
    recalculate hours, or write Neon data during render.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    try:
        return apply_column_order(table_key, df.copy())
    except Exception:
        return df.copy()


def _v77_html_table(df: pd.DataFrame, max_rows: int = 12, *, table_key: str = V101_ACTIVE_WORK_TABLE_KEY) -> None:
    """Render small active-work tables as compact HTML, avoiding heavy dataframe components.

    V101 keeps the speed benefit of the lightweight HTML table, but makes the
    table visually closer to Today Records: smaller type, shorter rows, sticky
    header, horizontal scroll, and persisted column order/widths.
    """
    try:
        show = _v101_apply_active_work_layout(df, table_key).head(max_rows).copy()
        show = show.where(pd.notna(show), "").astype(str)
        widths = _v101_active_work_widths(table_key, [str(c) for c in show.columns])
        colgroup = "".join(
            f'<col style="width:{int(widths.get(str(col), 112))}px; min-width:{int(widths.get(str(col), 112))}px;">'
            for col in show.columns
        )
        html = show.to_html(index=False, escape=False, border=0, classes="spt-active-work-table")
        html = html.replace('<table border="0" class="dataframe spt-active-work-table">', f'<table border="0" class="dataframe spt-active-work-table">{colgroup}', 1)
        st.markdown(
            f'<div class="spt-active-work-table-wrap">{html}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            """
<style>
.spt-active-work-table-wrap {
  width: 100%;
  max-height: 240px;
  overflow: auto;
  border: 1px solid rgba(120,220,255,0.20);
  border-radius: 10px;
  background: rgba(6, 22, 38, 0.35);
}
.spt-active-work-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 0.78rem;
  line-height: 1.22;
}
.spt-active-work-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  text-align: left;
  padding: 0.38rem 0.42rem;
  background: rgba(20, 43, 61, 0.96);
  border-bottom: 1px solid rgba(120,220,255,0.26);
  color: #eaffff;
  white-space: normal;
  overflow-wrap: anywhere;
}
.spt-active-work-table tbody td {
  padding: 0.34rem 0.42rem;
  border-bottom: 1px solid rgba(120,220,255,0.12);
  color: #f2ffff;
  vertical-align: middle;
  white-space: normal;
  overflow-wrap: anywhere;
}
.spt-active-work-table tbody tr:hover td { background: rgba(96,220,255,0.08); }
.spt-active-work-table td:nth-child(1), .spt-active-work-table th:nth-child(1) { text-align: right; }
</style>
""",
            unsafe_allow_html=True,
        )
    except Exception:
        try:
            st.table(df.head(max_rows))
        except Exception:
            st.write(df.head(max_rows).to_dict("records"))


def _v74_select_active_record(active_df: pd.DataFrame, employee_id: str, employee_name: str) -> dict | None:
    """Render active work and return a selected record.

    V77 finalizes the Active Work panel for field stability:
    - no st.dataframe/st.data_editor in the live finish panel, so the component cannot spin forever;
    - always falls back to the first row if selection labels cannot be built;
    - buttons below this function therefore cannot disappear while active records exist.
    """
    if active_df is None or not isinstance(active_df, pd.DataFrame) or active_df.empty:
        return None
    raw_df = active_df.reset_index(drop=True).copy()
    raw_df = raw_df.where(pd.notna(raw_df), "")
    display_df = _v72_active_display_df(raw_df)
    if not isinstance(display_df, pd.DataFrame) or display_df.empty:
        display_df = raw_df.copy()

    # V101: Active Work needs the same persistent column order/width control as
    # Today Records, but must not use the heavy render_table/data_editor path.
    # The settings editor is lazy-loaded behind a toggle, and saved settings only
    # affect this in-memory display table.
    try:
        if bool(_v207_current_user_is_admin()):
            _v84_render_column_settings_panel(
                V101_ACTIVE_WORK_TABLE_KEY,
                display_df,
                "▤ 開始中的作業欄位設定 / Active Work Column Settings",
            )
    except Exception:
        pass
    _v77_html_table(display_df, max_rows=12, table_key=V101_ACTIVE_WORK_TABLE_KEY)

    options: list[tuple[str, int]] = []
    for idx, row in raw_df.iterrows():
        rid = _v75_row_value(row, "id", "ID", "紀錄編號", "record_id") or str(idx + 1)
        wo = _v75_row_value(row, "work_order", "work_order_no", "製令", "製令號碼")
        proc = _v75_row_value(row, "process_name", "工段", "工段名稱")
        sd = _v75_row_value(row, "start_date", "開始日期")
        stime = _v75_row_value(row, "start_time", "開始時間")
        label = f"{rid}｜{wo or '未填製令'}｜{proc or '未填工段'}｜{sd} {stime}".strip()
        options.append((label, int(idx)))
    if not options:
        try:
            return raw_df.iloc[0].fillna("").to_dict()
        except Exception:
            return None
    if len(options) == 1:
        st.caption(f"已自動選取開始中作業：{options[0][0]}")
        selected_idx = options[0][1]
    else:
        labels = [x[0] for x in options]
        selected_label = st.selectbox(
            "選擇要結束的開始中作業｜Select active work",
            labels,
            index=0,
            key=f"v77_active_work_selectbox_{_v72_safe_key(employee_id, employee_name, len(raw_df))}",
        )
        selected_idx = dict(options).get(selected_label, 0)
    try:
        return raw_df.iloc[int(selected_idx)].fillna("").to_dict()
    except Exception:
        try:
            return raw_df.iloc[0].fillna("").to_dict()
        except Exception:
            return None


def _v74_trigger_after_start_prompt(record_id) -> None:
    trigger_post_record_continue_prompt(
        f"已開始記錄這筆作業，紀錄編號：{record_id}。若要繼續下一筆同步作業或其他查詢，請按『是，繼續記錄』；若沒有要繼續，請按『否，登出帳號』避免其他人員誤用此帳號。",
        title="開始作業完成",
    )

# ===== V72 ACTIVE-WORK FRONTEND GUARD END =====

# V13: 01 opens from latest memory files/SQLite without doing heavy master restore inline.
_spt_perf_t = time.perf_counter()
employees = load_employees_for_time_record_fast(active_only=True, in_factory_only=False)
work_orders = load_work_orders_for_time_record_fast(active_only=True)
_spt_perf_t = _spt_perf_tick(
    "01_load_master_data_employees_work_orders",
    _spt_perf_t,
    threshold_ms=500.0,
    detail={"employees": len(employees) if isinstance(employees, pd.DataFrame) else 0, "work_orders": len(work_orders) if isinstance(work_orders, pd.DataFrame) else 0},
)

# V11: master-data existence must be checked before employee account filtering.
# A normal operator may only see one employee, or zero if not bound.  That should
# not be treated as missing 03/04 master data.
has_employees_master, has_work_orders_master = has_master_data_for_time_record_fast(employees, work_orders)
_spt_perf_t = _spt_perf_tick("01_check_master_data_available", _spt_perf_t, threshold_ms=300.0)

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
        placeholder="輸入 2、25M、21M0241、P/N、機型關鍵字；按 Enter 或離開欄位後篩選",
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

    _spt_perf_t = time.perf_counter()
    category_choices, default_category = _v98_load_process_category_bundle_cached()
    _spt_perf_t = _spt_perf_tick(
        "01_load_process_categories_default_cached",
        _spt_perf_t,
        threshold_ms=300.0,
        detail={"category_count": len(category_choices)},
    )
    if default_category not in category_choices:
        default_category = category_choices[0] if category_choices else ""
    # V48: use a new widget key so stale deleted values such as 全部 / 通用 from
    # older sessions cannot remain selected after 13. 系統設定 removed them.
    try:
        if st.session_state.get("time_record_process_category_v48") not in category_choices:
            st.session_state.pop("time_record_process_category_v48", None)
        st.session_state.pop("time_record_process_category_v333", None)
    except Exception:
        pass
    if category_choices:
        selected_category = st.selectbox(
            "類別｜Category",
            category_choices,
            index=category_choices.index(default_category) if default_category in category_choices else 0,
            key="time_record_process_category_v48",
        )
    else:
        selected_category = ""
        st.error("13｜系統設定目前沒有任何啟用類別，請先建立類別並永久儲存。")
    _spt_perf_t = time.perf_counter()
    PROCESS_OPTIONS = _v98_get_process_options_cached(selected_category)
    _spt_perf_t = _spt_perf_tick(
        "01_load_process_options_for_category_cached",
        _spt_perf_t,
        threshold_ms=300.0,
        detail={"category": selected_category, "process_count": len(PROCESS_OPTIONS)},
    )
    st.caption(f"目前工段類別 / Current Category：{selected_category or '未設定'}")
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
    auto_pause = st.checkbox("防呆模式：前一項作業未停止時禁止開始新作業｜Start disabled until previous work is finished", value=False, disabled=True)

    active_before_start_df = _v72_load_active_df(emp_id, emp_name)
    start_policy = _v74_render_start_status(active_before_start_df, process, wo_no)
    start_disabled = bool(no_process_options or start_policy.get("blocked"))

    if st.button("⏱ 開始作業 / Start", use_container_width=True, disabled=start_disabled):
        if not check_permission("01_time_record", "can_create"):
            st.error("權限不足：你沒有新增工時紀錄權限。")
        elif start_policy.get("blocked"):
            st.warning(str(start_policy.get("reason") or "此人員已有未完成作業，請先處理右側開始中作業。"))
        else:
            try:
                _spt_button_t = time.perf_counter()
                rid = start_work(employee, work_order, process, remark, auto_pause_old=False)
                _v72_clear_active_cache(emp_id, emp_name)
                _v259_clear_display_cache()
                _spt_perf_tick("01_button_start_work_action", _spt_button_t, threshold_ms=3000.0, detail={"record_id": rid, "sync_mode": start_policy.get("mode")})
                _v74_trigger_after_start_prompt(rid)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

with right:
    st.subheader("開始中的作業 / Active Work")
    emp_id2, _emp2_name = emp_id, emp_name
    st.caption(f"目前人員：{emp_id2}｜{_emp2_name}。右側自動顯示開始中作業，不再需要另外按『查詢目前作業』。")

    active_right_df = active_before_start_df if isinstance(active_before_start_df, pd.DataFrame) else pd.DataFrame()
    if active_right_df.empty:
        st.success("此人員目前沒有開始中的作業。")
        active2 = None
    else:
        st.warning("此人員已有開始中的作業。請直接選取下表作業，按『暫停 / 完工 / 下班』結束；若同工段不同製令，左側仍可開始同步作業。")
        active2 = _v74_select_active_record(active_right_df, emp_id2, _emp2_name)

    _v207_admin_finish_bypass = _v207_current_user_is_admin()
    if (not _v207_admin_finish_bypass) and active2 and (not _v141_active_matches_employee(active2, emp_id2, _emp2_name) or not _v143_ui_row_matches_selected(active2, emp_id2, _emp2_name)):
        st.error(
            "Active Work 人員不一致，已停止顯示其他人員資料。"
            f"目前選擇：{emp_id2} {_emp2_name}；讀到資料：{_v143_ui_identity_debug_text(active2)}。"
            "請重新整理；若仍出現，代表 01/02 權威資料有舊版身份欄位污染，需由管理員執行資料修復。"
        )
        active2 = None

    if active2:
        try:
            st.caption(f"已選取紀錄 ID：{active2.get('id', '')}。操作按鈕會同步結束同一人員、同日、同工段的未結束作業並平均工時。")
        except Exception:
            pass
        end_remark = st.text_input("結束備註｜Finish Remark", key="end_remark", disabled=False)
        _v208_finish_parallel_group = True
        c1, c2, c3 = st.columns(3)
        if c1.button("⏸ 暫停 / Pause", use_container_width=True, key=f"v74_finish_pause_{active2.get('id')}"):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                try:
                    _spt_button_t = time.perf_counter()
                    n = finish_work(active2["id"], "暫停", end_remark, finish_parallel_group=_v208_finish_parallel_group)
                    _v259_clear_display_cache()
                    _v72_clear_active_cache(emp_id2, _emp2_name)
                    _spt_perf_tick("01_button_finish_pause_action", _spt_button_t, threshold_ms=3000.0, detail={"active_id": active2.get("id"), "rows": n})
                    trigger_post_record_continue_prompt(f"已同步暫停 {n} 筆並平均計算工時。", title="工時已暫停")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        if c2.button("⟡ 完工 / Complete", use_container_width=True, key=f"v74_finish_complete_{active2.get('id')}"):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                try:
                    _spt_button_t = time.perf_counter()
                    n = finish_work(active2["id"], "完工", end_remark, finish_parallel_group=_v208_finish_parallel_group)
                    _v259_clear_display_cache()
                    _v72_clear_active_cache(emp_id2, _emp2_name)
                    _spt_perf_tick("01_button_finish_complete_action", _spt_button_t, threshold_ms=3000.0, detail={"active_id": active2.get("id"), "rows": n})
                    trigger_post_record_continue_prompt(f"已同步完工 {n} 筆並平均計算工時。", title="工時已完工")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        if c3.button("◐ 下班 / Off Duty", use_container_width=True, key=f"v74_finish_off_duty_{active2.get('id')}"):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                try:
                    _spt_button_t = time.perf_counter()
                    n = finish_work(active2["id"], "下班", end_remark, finish_parallel_group=_v208_finish_parallel_group)
                    _v259_clear_display_cache()
                    _v72_clear_active_cache(emp_id2, _emp2_name)
                    _spt_perf_tick("01_button_finish_off_duty_action", _spt_button_t, threshold_ms=3000.0, detail={"active_id": active2.get("id"), "rows": n})
                    trigger_post_record_continue_prompt(f"已同步下班 {n} 筆並平均計算工時。", title="工時已結束")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        with st.expander("同步群組預覽 / Group Preview（手動載入）", expanded=False):
            if st.button("載入同步群組預覽", use_container_width=True, key=f"v74_load_group_preview_{active2.get('id')}"):
                try:
                    _spt_perf_t = time.perf_counter()
                    raw_group_df = get_active_group(int(active2["id"]))
                    group_preview_df = raw_group_df.copy().reset_index(drop=True) if isinstance(raw_group_df, pd.DataFrame) else pd.DataFrame()
                    _spt_perf_tick(
                        "01_finish_panel_group_preview_query",
                        _spt_perf_t,
                        threshold_ms=3000.0,
                        detail={"active_id": active2.get("id"), "group_rows": len(group_preview_df)},
                    )
                    if group_preview_df.empty:
                        st.info("目前沒有可顯示的同步群組明細；結束按鈕仍會以目前作業為主進行處理。")
                    else:
                        render_table(group_preview_df, "active_parallel_group_preview_v74", editable=False, height=230)
                except Exception as exc:
                    st.warning(f"同步群組預覽載入失敗，仍可直接按暫停 / 完工 / 下班：{exc}")

    # V93: define admin permission before the first column-settings block uses it.
    # A previous patch referenced is_admin in Today Finished Records before it was
    # initialized later in the Today Records section, causing NameError on 01 page load.
    try:
        is_admin = bool(_v207_current_user_is_admin())
    except Exception:
        is_admin = False

    st.markdown("#### 今日已結束紀錄 / Today Finished Records")
    _finished_key, _finished_ts_key = _v259_finish_key(emp_id2, _emp2_name)
    fc1, fc2 = st.columns([1, 3])
    load_finished_clicked = fc1.button("重新整理已結束紀錄", use_container_width=True, key=f"v259_load_finished_{emp_id2}")
    _v259_notice_cached("今日已結束紀錄", _finished_ts_key)
    _finished_visible_key = _v103_finished_visible_key(emp_id2, _emp2_name)
    if load_finished_clicked:
        _spt_perf_t = time.perf_counter()
        finished_today_df = _v148_load_today_finished_records_for_employee(emp_id2, _emp2_name)
        st.session_state[_finished_key] = finished_today_df
        st.session_state[_finished_ts_key] = _v259_now_label()
        st.session_state[_finished_visible_key] = True
        _spt_perf_t = _spt_perf_tick(
            "01_load_finished_today_for_employee",
            _spt_perf_t,
            threshold_ms=500.0,
            detail={"employee_id": emp_id2, "rows": len(finished_today_df) if isinstance(finished_today_df, pd.DataFrame) else 0},
        )
    finished_today_df = st.session_state.get(_finished_key, pd.DataFrame())
    if isinstance(finished_today_df, pd.DataFrame) and not finished_today_df.empty:
        st.caption("只顯示目前選擇人員今日已下班、暫停或完工的紀錄；此區為唯讀查閱，不會寫入、覆蓋或刪除資料。")
        _v103_light_table_controls("已結束紀錄表格", _finished_visible_key, has_data=True)
        if bool(st.session_state.get(_finished_visible_key, False)):
            # V91: Today Finished Records uses its own persistent table UI key.
            # Column order/width settings only affect display and are saved on explicit Apply;
            # they do not reload time records, recalculate hours, or touch Neon authority data.
            _v91_finished_table_key = "01.time_records.today_finished"
            if is_admin:
                _v84_render_column_settings_panel(
                    _v91_finished_table_key,
                    finished_today_df,
                    "▤ 今日已結束紀錄欄位設定 / Today Finished Records Column Settings",
                )
            render_table(
                finished_today_df,
                _v91_finished_table_key,
                editable=False,
                height=260,
                show_width_settings=False,
            )
        else:
            st.info(f"已結束紀錄已快取 {len(finished_today_df)} 筆；目前為加速 01 開頁而暫不建立表格，按『顯示已結束紀錄表格』即可查看。")
    else:
        st.info("此區已改為手動刷新，避免整頁顯示完成被已結束紀錄查詢拖慢。")

st.divider()
st.subheader("今日工時紀錄 / Today Records")
try:
    _reset_time = get_live_page_reset_time()
except Exception:
    _reset_time = "02:00"
st.caption(f"顯示規則：重新整理前會顯示當日作業明細；每日 {_reset_time} 後會自動隱藏已結束紀錄。按下立即重新整理後，會立刻隱藏目前所有已結束紀錄，只保留未結束作業；02｜歷史紀錄不受影響。")
user = get_current_user() or {}
try:
    # V93: keep the same tolerant admin rule used by the upper 01 page sections.
    is_admin = bool(is_admin) or bool(_v207_current_user_is_admin())
except Exception:
    is_admin = bool(is_admin)
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
tc1, tc2, tc3 = st.columns([1.2, 1.2, 2.6])
load_today_clicked = tc1.button("重新整理今日明細", use_container_width=True, key="v259_load_today_records")
clear_today_cache_clicked = tc2.button("清除今日明細快取", use_container_width=True, key="v259_clear_today_records_cache")
with tc3:
    _v259_notice_cached("今日工時紀錄", V259_TODAY_TABLE_TS_KEY)
if clear_today_cache_clicked:
    st.session_state.pop(V259_TODAY_TABLE_KEY, None)
    st.session_state.pop(V259_TODAY_TABLE_TS_KEY, None)
    st.session_state.pop(V259_TODAY_TABLE_META_KEY, None)
    st.session_state.pop(V259_TODAY_TABLE_VISIBLE_KEY, None)
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass
    st.success("已清除今日明細快取；需要時請按『重新整理今日明細』。")
    st.rerun()
if load_today_clicked:
    _spt_perf_t = time.perf_counter()
    with st.spinner("正在載入今日明細，已改用快速查詢路徑..."):
        df_loaded = today_records(include_finished=not show_unfinished_only, unfinished_only=show_unfinished_only)
    if not isinstance(df_loaded, pd.DataFrame):
        df_loaded = pd.DataFrame()
    st.session_state[V259_TODAY_TABLE_KEY] = df_loaded
    st.session_state[V259_TODAY_TABLE_TS_KEY] = _v259_now_label()
    st.session_state[V259_TODAY_TABLE_META_KEY] = {
        "include_finished": bool(not show_unfinished_only),
        "unfinished_only": bool(show_unfinished_only),
    }
    st.session_state[V259_TODAY_TABLE_VISIBLE_KEY] = True
    _spt_perf_t = _spt_perf_tick(
        "01_load_today_records_main_table_data",
        _spt_perf_t,
        threshold_ms=500.0,
        detail={"rows": len(df_loaded) if isinstance(df_loaded, pd.DataFrame) else 0, "unfinished_only": bool(show_unfinished_only)},
    )
    if isinstance(df_loaded, pd.DataFrame) and len(df_loaded) >= 300 and not show_unfinished_only:
        st.caption("今日明細已使用互動查詢上限載入；若需要查完整歷史，請到 02｜歷史紀錄依日期/條件查詢。")
df = st.session_state.get(V259_TODAY_TABLE_KEY, pd.DataFrame())
if isinstance(df, pd.DataFrame) and not df.empty:
    _v103_light_table_controls("今日明細表格", V259_TODAY_TABLE_VISIBLE_KEY, has_data=True)
    if bool(st.session_state.get(V259_TODAY_TABLE_VISIBLE_KEY, False)):
        if is_admin:
            _v84_render_column_settings_panel(
                "01.time_records.main",
                df,
                "▤ 今日工時紀錄欄位設定 / Today Records Column Settings",
            )
        _spt_perf_t = time.perf_counter()
        render_table(df, "01.time_records.main", editable=False, height=420, show_width_settings=False)
        _spt_perf_t = _spt_perf_tick(
            "01_render_today_records_main_table",
            _spt_perf_t,
            threshold_ms=500.0,
            detail={"rows": len(df) if isinstance(df, pd.DataFrame) else 0},
        )
    else:
        st.info(f"今日明細已快取 {len(df)} 筆；目前為加速 01 開頁而暫不建立表格，按『顯示今日明細表格』即可查看。")
else:
    st.info("今日明細表格已改為手動刷新。開始/暫停/完工可先操作；需要看完整表格時再按『重新整理今日明細』。")

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


# ===== V78 ADMIN MAINTENANCE SAVE STABILITY HELPERS =====
def _v78_cell_text(value) -> str:
    """Normalize editor values for safe diffing without treating NaN/None as changes."""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value if value is not None else "").strip()
    if text.lower() in {"nan", "nat", "none", "<na>"}:
        return ""
    # Keep business values readable but avoid false positives from 1.0 vs 1.
    try:
        if text.endswith(".0"):
            return str(int(float(text)))
    except Exception:
        pass
    return text


def _v78_changed_rows(original_df: pd.DataFrame, edited_df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """Return only rows that actually changed in the admin maintenance editor.

    This prevents the Save button from writing every visible row to Neon.  It also
    keeps the editor responsive because unchanged rows do not trigger recalculation,
    log writing, or parallel-group checks.
    """
    if not isinstance(original_df, pd.DataFrame) or not isinstance(edited_df, pd.DataFrame):
        return pd.DataFrame()
    if not id_col or id_col not in original_df.columns or id_col not in edited_df.columns:
        return edited_df.copy().reset_index(drop=True)

    ignore_cols = {
        "刪除 / Delete",
        "updated_at", "更新時間 / Updated At", "建立時間 / Created At", "created_at",
    }
    original_map = {}
    for _, row in original_df.iterrows():
        rid = _v92_to_int_id(row.get(id_col))
        if rid is not None:
            original_map[rid] = row

    changed = []
    compare_cols = [c for c in edited_df.columns if c in original_df.columns and c not in ignore_cols]
    for _, row in edited_df.iterrows():
        rid = _v92_to_int_id(row.get(id_col))
        if rid is None or rid not in original_map:
            changed.append(row)
            continue
        old = original_map[rid]
        for col in compare_cols:
            if _v78_cell_text(row.get(col)) != _v78_cell_text(old.get(col)):
                changed.append(row)
                break
    if not changed:
        return pd.DataFrame(columns=edited_df.columns)
    return pd.DataFrame(changed).reset_index(drop=True)


def _v30025_admin_changed_columns_by_id(original_df: pd.DataFrame, edited_df: pd.DataFrame, id_col: str) -> dict[int, set[str]]:
    """Return per-row changed internal columns for 01 admin maintenance saves.

    This prevents a stale full row from overwriting another admin/operator's
    newer fields when 20 PCs are using the system at the same time.
    """
    if not isinstance(original_df, pd.DataFrame) or not isinstance(edited_df, pd.DataFrame):
        return {}
    if not id_col or id_col not in original_df.columns or id_col not in edited_df.columns:
        return {}
    alias = {
        "ID / ID": "id", "紀錄編號": "id", "ID": "id",
        "狀態 / Status": "status",
        "製令 / Work Order": "work_order",
        "製令號碼 / Work Order No.": "work_order_no",
        "P/N / Part No.": "part_no",
        "機型 / Type": "type_name",
        "工段名稱 / Process": "process_name", "工段 / Process": "process_name",
        "工號 / Employee ID": "employee_id",
        "姓名 / Name": "employee_name",
        "開始動作 / Start Action": "start_action",
        "開始時間戳 / Start Timestamp": "start_timestamp",
        "結束動作 / End Action": "end_action",
        "結束時間戳 / End Timestamp": "end_timestamp",
        "開始日期 / Start Date": "start_date",
        "開始時間 / Start Time": "start_time",
        "結束日期 / End Date": "end_date",
        "結束時間 / End Time": "end_time",
        "工時小計 / Hours": "work_hours",
        "工時分鐘 / Minutes": "work_minutes",
        "備註 / Remark": "remark",
        "組立地點 / Assembly Location": "assembly_location",
    }
    ignore_cols = {"刪除 / Delete", "created_at", "建立時間 / Created At", "updated_at", "更新時間 / Updated At"}
    original_map = {}
    for _, row in original_df.iterrows():
        rid = _v92_to_int_id(row.get(id_col)) if "_v92_to_int_id" in globals() else None
        if rid is not None:
            original_map[int(rid)] = row
    out: dict[int, set[str]] = {}
    compare_cols = [c for c in edited_df.columns if c in original_df.columns and c not in ignore_cols]
    for _, row in edited_df.iterrows():
        rid = _v92_to_int_id(row.get(id_col)) if "_v92_to_int_id" in globals() else None
        if rid is None or int(rid) not in original_map:
            continue
        old = original_map[int(rid)]
        changed: set[str] = set()
        for col in compare_cols:
            if _v78_cell_text(row.get(col)) != _v78_cell_text(old.get(col)):
                changed.add(alias.get(str(col), str(col)))
        if changed:
            out[int(rid)] = changed
    return out


def _v80_first_existing_col(df: pd.DataFrame, names: list[str]) -> str | None:
    if not isinstance(df, pd.DataFrame):
        return None
    cols = set(str(c) for c in df.columns)
    for name in names:
        if name in cols:
            return name
    return None


def _v80_text_cell(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value if value is not None else "").strip()


def _v80_date_text(value) -> str:
    text = _v80_text_cell(value)
    if not text:
        return ""
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return text[:10].replace("/", "-") if len(text) >= 10 else text.replace("/", "-")


def _v80_time_text(value) -> str:
    text = _v80_text_cell(value)
    if not text:
        return ""
    if " " in text:
        text = text.split()[-1]
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%H:%M:%S")
    except Exception:
        pass
    parts = text.split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        try:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(float(parts[2])):02d}"
        except Exception:
            return text
    return text


def _v80_split_timestamp(value) -> tuple[str, str]:
    text = _v80_text_cell(value)
    if not text:
        return "", ""
    try:
        dt = pd.to_datetime(text, errors="coerce")
        if pd.notna(dt):
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
    except Exception:
        pass
    return (text[:10], text[11:19] if len(text) >= 16 else "")


def _v80_sync_datetime_editor_columns(edited_df: pd.DataFrame, original_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Synchronize visible start/end date/time columns before 01 admin save.

    The authority service also performs this normalization before writing Neon.
    This lightweight page-side copy keeps the 01 maintenance table and Today
    Records cache visually consistent immediately after Save/Recalc.
    """
    if not isinstance(edited_df, pd.DataFrame) or edited_df.empty:
        return edited_df.copy() if isinstance(edited_df, pd.DataFrame) else pd.DataFrame()
    out = edited_df.copy()
    id_col = _v92_find_id_col(out) if "_v92_find_id_col" in globals() else ("id" if "id" in out.columns else None)
    original_map = {}
    if isinstance(original_df, pd.DataFrame) and id_col and id_col in original_df.columns:
        for _, old_row in original_df.iterrows():
            rid = _v92_to_int_id(old_row.get(id_col)) if "_v92_to_int_id" in globals() else None
            if rid is not None:
                original_map[rid] = old_row

    aliases = {
        "start": {
            "ts": ["start_timestamp", "開始時間戳 / Start Timestamp", "開始時間戳"],
            "date": ["start_date", "開始日期 / Start Date", "開始日期"],
            "time": ["start_time", "開始時間 / Start Time", "開始時間"],
        },
        "end": {
            "ts": ["end_timestamp", "結束時間戳 / End Timestamp", "結束時間戳"],
            "date": ["end_date", "結束日期 / End Date", "結束日期"],
            "time": ["end_time", "結束時間 / End Time", "結束時間"],
        },
    }
    for prefix, m in aliases.items():
        ts_col = _v80_first_existing_col(out, m["ts"])
        date_col = _v80_first_existing_col(out, m["date"])
        time_col = _v80_first_existing_col(out, m["time"])
        if not any([ts_col, date_col, time_col]):
            continue
        for idx, row in out.iterrows():
            rid = _v92_to_int_id(row.get(id_col)) if id_col and "_v92_to_int_id" in globals() else None
            old = original_map.get(rid)
            cur_ts = _v80_text_cell(row.get(ts_col)) if ts_col else ""
            cur_d = _v80_date_text(row.get(date_col)) if date_col else ""
            cur_t = _v80_time_text(row.get(time_col)) if time_col else ""
            old_ts = _v80_text_cell(old.get(ts_col)) if old is not None and ts_col and ts_col in old.index else ""
            old_d = _v80_date_text(old.get(date_col)) if old is not None and date_col and date_col in old.index else ""
            old_t = _v80_time_text(old.get(time_col)) if old is not None and time_col and time_col in old.index else ""
            if old_ts and (not old_d or not old_t):
                sd, st = _v80_split_timestamp(old_ts)
                old_d = old_d or sd
                old_t = old_t or st
            split_changed = bool(old is not None and ((date_col and cur_d != old_d) or (time_col and cur_t != old_t)))
            ts_changed = bool(old is not None and ts_col and cur_ts != old_ts)
            # V82: timestamp edits are authoritative.  If the user edits
            # 開始時間戳 / 結束時間戳, regenerate 開始日期/開始時間/結束日期/結束時間
            # immediately in the page cache, instead of rebuilding the timestamp
            # from stale split fields.
            if ts_changed and cur_ts:
                sd, st = _v80_split_timestamp(cur_ts)
                if date_col:
                    out.at[idx, date_col] = sd
                if time_col:
                    out.at[idx, time_col] = st
                if ts_col:
                    out.at[idx, ts_col] = f"{sd} {st}".strip() if sd and st else cur_ts
            elif split_changed and cur_d and cur_t:
                new_ts = f"{cur_d} {cur_t}"
                if ts_col:
                    out.at[idx, ts_col] = new_ts
                if date_col:
                    out.at[idx, date_col] = cur_d
                if time_col:
                    out.at[idx, time_col] = cur_t
            elif cur_ts:
                sd, st = _v80_split_timestamp(cur_ts)
                if date_col:
                    out.at[idx, date_col] = sd or cur_d
                if time_col:
                    out.at[idx, time_col] = st or cur_t
                if ts_col and sd and st:
                    out.at[idx, ts_col] = f"{sd} {st}"
            elif cur_d and cur_t and ts_col:
                out.at[idx, ts_col] = f"{cur_d} {cur_t}"
    return out


def _v78_apply_editor_df_to_cache(cache_df: pd.DataFrame, edited_df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """Apply edited rows to the session copy so Save can refresh the page without re-querying."""
    if not isinstance(cache_df, pd.DataFrame) or cache_df.empty:
        return edited_df.copy().reset_index(drop=True) if isinstance(edited_df, pd.DataFrame) else pd.DataFrame()
    if not isinstance(edited_df, pd.DataFrame) or edited_df.empty or not id_col:
        return cache_df.copy().reset_index(drop=True)
    out = cache_df.copy().reset_index(drop=True)
    if id_col not in out.columns or id_col not in edited_df.columns:
        return edited_df.copy().reset_index(drop=True)
    row_pos = {}
    for pos, row in out.iterrows():
        rid = _v92_to_int_id(row.get(id_col))
        if rid is not None:
            row_pos[rid] = pos
    for _, row in edited_df.iterrows():
        rid = _v92_to_int_id(row.get(id_col))
        if rid is None:
            continue
        if rid in row_pos:
            pos = row_pos[rid]
            for col in edited_df.columns:
                if col in out.columns:
                    out.at[pos, col] = row.get(col)
    return out.reset_index(drop=True)


def _v78_remove_ids_from_cache(cache_df: pd.DataFrame, id_col: str, ids: list[int]) -> pd.DataFrame:
    if not isinstance(cache_df, pd.DataFrame) or cache_df.empty or not id_col or id_col not in cache_df.columns or not ids:
        return cache_df.copy() if isinstance(cache_df, pd.DataFrame) else pd.DataFrame()
    id_set = {int(x) for x in ids if _v92_to_int_id(x) is not None}
    return cache_df[~cache_df[id_col].map(lambda x: (_v92_to_int_id(x) in id_set))].reset_index(drop=True)


def _v78_refresh_related_page_caches(clean_df: pd.DataFrame | None, *, admin_data_key: str, ts_key: str) -> None:
    """Synchronize 01 page session tables after admin Save/Recalc/Delete.

    This updates the visible page state immediately and clears only backend query
    caches.  It avoids the previous expensive pattern: save -> clear cache ->
    st.rerun -> reload the full maintenance table from Neon.
    """
    if isinstance(clean_df, pd.DataFrame):
        st.session_state[admin_data_key] = clean_df.copy().reset_index(drop=True)
        if V259_TODAY_TABLE_KEY in st.session_state:
            st.session_state[V259_TODAY_TABLE_KEY] = clean_df.copy().reset_index(drop=True)
            st.session_state[V259_TODAY_TABLE_TS_KEY] = _v259_now_label()
        st.session_state[ts_key] = _v259_now_label()
    try:
        clear_today_records_fast_cache()
    except Exception:
        pass


# ===== V78 ADMIN MAINTENANCE SAVE STABILITY HELPERS END =====


if is_admin:
    st.divider()
    with st.expander("▤ 管理員工時紀錄維護｜修改、刪除、存檔", expanded=False):
        st.warning("此區僅管理員可見。V81 起維護區改為『載入 → 預覽 → 啟動編輯』三段式，避免點擊展開時立即建立大型可編輯表格而卡住。")
        admin_load_key = "today_records_admin_load_v92"
        admin_data_key = "today_records_admin_data_v78"
        admin_data_ts_key = "today_records_admin_data_ts_v78"
        admin_select_key = "_spt_select_today_records_admin_delete_ids_v92"
        editor_version_key = "today_records_admin_editor_version_v92"
        edit_mode_key = "today_records_admin_edit_mode_v81"
        row_limit_key = "today_records_admin_editor_row_limit_v81"
        admin_visible_key = "v103_today_records_admin_visible"
        if admin_visible_key not in st.session_state:
            # Old sessions may still hold a loaded maintenance dataframe.  Do not
            # auto-render it on page entry; the operator can show it explicitly.
            st.session_state[admin_visible_key] = False
        if editor_version_key not in st.session_state:
            st.session_state[editor_version_key] = 0
        if edit_mode_key not in st.session_state:
            st.session_state[edit_mode_key] = False
        if row_limit_key not in st.session_state:
            st.session_state[row_limit_key] = 200

        ca, cb, cc, ce, cd = st.columns([1.05, 1.05, 1.05, 1.05, 2.2])
        load_clicked = ca.button("▤ 載入維護表格 / Load", use_container_width=True, key="today_records_admin_load_btn_v81")
        refresh_clicked = cb.button("⟳ 重新載入 / Refresh", use_container_width=True, key="today_records_admin_refresh_btn_v81")
        unload_clicked = cc.button("□ 卸載 / Unload", use_container_width=True, key="today_records_admin_unload_btn_v81")
        toggle_admin_visible_clicked = ce.button(
            "隱藏內容" if st.session_state.get(admin_visible_key, False) else "顯示內容",
            use_container_width=True,
            key="v103_today_records_admin_toggle_visible",
        )
        if toggle_admin_visible_clicked:
            st.session_state[admin_visible_key] = not bool(st.session_state.get(admin_visible_key, False))
        cd.caption("展開此區不會自動查 DB；已載入資料也可暫時隱藏，避免每次進 01 都重建預覽/編輯表格。")

        if load_clicked or refresh_clicked:
            _load_t0 = time.perf_counter()
            st.session_state[admin_load_key] = True
            st.session_state[admin_visible_key] = True
            # V300.22：載入維護表格只讀資料並顯示輕量預覽；不要沿用上一輪編輯模式或 800 筆 row_limit，
            # 避免一按 Load 就立即建立大型 data_editor，造成管理員維護區一直運轉。
            st.session_state[edit_mode_key] = False
            try:
                st.session_state[row_limit_key] = min(int(st.session_state.get(row_limit_key, 200) or 200), 200)
            except Exception:
                st.session_state[row_limit_key] = 200
            st.session_state[admin_select_key] = []
            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1

            _wanted_meta = {
                "include_finished": bool(not show_unfinished_only),
                "unfinished_only": bool(show_unfinished_only),
            }
            _cached_today = st.session_state.get(V259_TODAY_TABLE_KEY)
            _cached_meta = st.session_state.get(V259_TODAY_TABLE_META_KEY, {})
            _used_today_cache = False
            if (not refresh_clicked) and isinstance(_cached_today, pd.DataFrame) and dict(_cached_meta or {}) == _wanted_meta:
                # V96: loading admin maintenance should be instant if the same Today
                # Records data is already in the foreground cache.  Do not clear the
                # DB query cache for a normal Load click.
                st.session_state[admin_data_key] = _cached_today.copy().reset_index(drop=True)
                _used_today_cache = True
            else:
                if refresh_clicked:
                    try:
                        clear_today_records_fast_cache()
                    except Exception:
                        pass
                st.session_state[admin_data_key] = today_records(include_finished=not show_unfinished_only, unfinished_only=show_unfinished_only)
            st.session_state[admin_data_ts_key] = _v259_now_label()
            _spt_perf_tick(
                "01_admin_maintenance_load_today_records",
                _load_t0,
                threshold_ms=1200.0,
                detail={
                    "rows": len(st.session_state.get(admin_data_key, pd.DataFrame())) if isinstance(st.session_state.get(admin_data_key), pd.DataFrame) else 0,
                    "used_today_cache": bool(_used_today_cache),
                    "refresh": bool(refresh_clicked),
                },
            )
        if unload_clicked:
            st.session_state[admin_load_key] = False
            st.session_state[admin_visible_key] = False
            st.session_state[edit_mode_key] = False
            st.session_state.pop(admin_data_key, None)
            st.session_state.pop(admin_data_ts_key, None)
            st.session_state[admin_select_key] = []
            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1

        if not st.session_state.get(admin_load_key, False):
            st.info("管理員維護表格尚未載入。平常進入 01 工時紀錄不會載入此區，避免拖慢現場作業。需要修改/刪除/存檔時，請按『載入維護表格』。")
        else:
            if not bool(st.session_state.get(admin_visible_key, False)):
                _cached_admin_df = st.session_state.get(admin_data_key)
                _cached_rows = len(_cached_admin_df) if isinstance(_cached_admin_df, pd.DataFrame) else 0
                st.info(f"管理員維護資料已載入 {_cached_rows} 筆，但目前暫時隱藏表格內容以加快 01 頁顯示。需要修改時請按『顯示內容』。")
                admin_source_df = None
            else:
                admin_source_df = st.session_state.get(admin_data_key)
            if admin_source_df is None:
                pass
            elif not isinstance(admin_source_df, pd.DataFrame):
                st.warning("維護表格暫存已不存在，為避免進頁自動重查造成卡住，請按『重新載入』重新讀取。")
            else:
                admin_source_df = admin_source_df.copy().reset_index(drop=True)
                _admin_loaded_at = st.session_state.get(admin_data_ts_key, "")
                st.caption(f"維護資料已載入：{_admin_loaded_at or '本次工作階段'}；目前暫存 {len(admin_source_df)} 筆。")

                if admin_source_df.empty:
                    st.info("今日目前沒有可維護的工時紀錄。")
                else:
                    # V81/V96：先用輕量預覽，點擊展開維護區時不立即建立大型 data_editor。
                    # 啟動/關閉編輯只切換前台狀態，不 st.rerun、不重新查 DB。
                    p1, p2, p3 = st.columns([1.2, 1.2, 2.4])
                    edit_mode_active = bool(st.session_state.get(edit_mode_key, False))
                    start_edit = False
                    stop_edit = False
                    if not edit_mode_active:
                        start_edit = p1.button("✎ 啟動編輯模式 / Edit", type="primary", use_container_width=True, key="today_records_admin_start_edit_v81")
                        if start_edit:
                            st.session_state[edit_mode_key] = True
                            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                            edit_mode_active = True
                    else:
                        stop_edit = p1.button("□ 關閉編輯模式 / Close Edit", use_container_width=True, key="today_records_admin_stop_edit_v81")
                        if stop_edit:
                            st.session_state[edit_mode_key] = False
                            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                            edit_mode_active = False
                    p2.caption("編輯模式才會建立可修改表格；預覽模式只顯示前 50 筆，開啟速度較快。")
                    if not edit_mode_active:
                        try:
                            st.dataframe(admin_source_df.head(50), use_container_width=True, hide_index=True, height=260)
                        except TypeError:
                            st.dataframe(admin_source_df.head(50), use_container_width=True, height=260)
                    else:
                        r1, r2, r3 = st.columns([1.2, 1.2, 2.4])
                        row_limit = r1.selectbox(
                            "本次編輯載入筆數",
                            [100, 200, 400, 800],
                            index=[100, 200, 400, 800].index(int(st.session_state.get(row_limit_key, 200))) if int(st.session_state.get(row_limit_key, 200)) in [100, 200, 400, 800] else 1,
                            key="today_records_admin_row_limit_select_v81",
                            help="資料很多時請先用 100/200 筆編輯，避免 Streamlit data_editor 建立過久。",
                        )
                        st.session_state[row_limit_key] = int(row_limit)
                        r2.caption("若找不到要修改的紀錄，請先在上方今日明細篩選或調高筆數後重新載入。")

                        admin_df = admin_source_df.head(int(row_limit)).copy().reset_index(drop=True)
                        _id_col = _v92_find_id_col(admin_df)
                        _all_admin_ids: list[int] = []
                        if _id_col:
                            for _x in admin_df[_id_col].tolist():
                                _rid = _v92_to_int_id(_x)
                                if _rid is not None and _rid not in _all_admin_ids:
                                    _all_admin_ids.append(_rid)
                        _all_admin_id_set = set(_all_admin_ids)

                        sa, sb, sc = st.columns([1, 1, 3])
                        select_all_clicked = sa.button("☑ 勾選本次顯示", use_container_width=True, key="today_records_admin_select_visible_v81")
                        clear_clicked = sb.button("☐ 取消勾選", use_container_width=True, key="today_records_admin_clear_select_v81")
                        sc.caption("勾選欄用於刪除或重算；『僅儲存修改』不需要勾選，只會存真正變更的列。")
                        if select_all_clicked:
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

                        editor_key = f"today_records_admin_editor_v81_{st.session_state[editor_version_key]}"
                        admin_table_key = "01.time_records.admin_maintenance"
                        display_admin = admin_df.copy()
                        if delete_col in display_admin.columns:
                            display_admin[delete_col] = display_admin[delete_col].map(lambda v: bool(v)).astype(bool)

                        _v84_render_column_settings_panel(
                            admin_table_key,
                            display_admin,
                            "▤ 管理員維護表格欄位設定 / Admin Maintenance Column Settings",
                        )
                        display_admin, column_cfg = _v84_apply_table_layout(admin_table_key, display_admin)
                        column_cfg = dict(column_cfg or {})
                        column_cfg[delete_col] = st.column_config.CheckboxColumn("刪除 / Delete", width=120)
                        disabled_cols = [c for c in ["id", "ID", "ID / ID", "ID / ID / ID", "record_key", "紀錄鍵 / Record Key", "created_at", "建立時間 / Created At", "updated_at", "更新時間 / Updated At"] if c in display_admin.columns]

                        with st.form("v81_today_admin_maintenance_lazy_editor_form", clear_on_submit=False):
                            try:
                                edited_admin_return = _v95_raw_data_editor(
                                    display_admin,
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config=column_cfg,
                                    disabled=disabled_cols,
                                    num_rows="fixed",
                                    key=editor_key,
                                    height=420,
                                )
                            except Exception as _v81_editor_error:
                                st.warning(f"維護表格欄位型態已自動降級：{_v81_editor_error}")
                                edited_admin_return = _v95_raw_data_editor(
                                    display_admin.astype(str),
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config=column_cfg,
                                    disabled=[c for c in disabled_cols if c in display_admin.columns],
                                    num_rows="fixed",
                                    key=f"{editor_key}_safe",
                                    height=420,
                                )
                                editor_key = f"{editor_key}_safe"
                            b1, b2, b3 = st.columns(3)
                            with b1:
                                do_save = st.form_submit_button("💾 僅儲存修改 / Save", type="primary", use_container_width=True)
                            with b2:
                                do_recalc = st.form_submit_button("🧮 重算勾選工時並同步 02 / Recalc", use_container_width=True)
                            with b3:
                                do_delete = st.form_submit_button("🗑 刪除勾選整列 / Delete", use_container_width=True)

                        if _v98_admin_editor_should_parse(do_save, do_recalc, do_delete):
                            edited_admin = _v92_editor_state_to_df(display_admin, edited_admin_return, editor_key)
                            checked_ids = _v92_checked_ids(edited_admin, delete_col, _id_col)
                            if not checked_ids:
                                checked_ids = [rid for rid in [_v92_to_int_id(x) for x in st.session_state.get(admin_select_key, [])] if rid is not None]
                            checked_ids = [rid for rid in checked_ids if rid in _all_admin_id_set]
                            st.session_state[admin_select_key] = checked_ids

                            if do_save:
                                save_df_all = edited_admin.drop(columns=[delete_col], errors="ignore")
                                original_display_for_diff = display_admin.drop(columns=[delete_col], errors="ignore")
                                save_df_all = _v80_sync_datetime_editor_columns(save_df_all, original_display_for_diff)
                                changed_df = _v78_changed_rows(original_display_for_diff, save_df_all, _id_col)
                                try:
                                    changed_df.attrs["_spt_changed_columns_by_id"] = _v30025_admin_changed_columns_by_id(original_display_for_diff, save_df_all, _id_col)
                                except Exception:
                                    pass
                                if changed_df.empty:
                                    st.info("沒有偵測到實際修改；未寫入 Neon，避免無效存檔造成頁面長時間運轉。")
                                else:
                                    _save_t0 = time.perf_counter()
                                    count = save_time_records(changed_df)
                                    updated_cache = _v78_apply_editor_df_to_cache(admin_source_df, save_df_all, _id_col)
                                    _v78_refresh_related_page_caches(updated_cache, admin_data_key=admin_data_key, ts_key=admin_data_ts_key)
                                    st.success(f"已由管理員存檔修改 {count} 筆今日工時紀錄，並同步更新 01 頁面暫存顯示與 02 歷史紀錄權威資料。")
                                    st.session_state[edit_mode_key] = False
                                    st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                                    _spt_perf_tick("01_admin_maintenance_save_changed_rows", _save_t0, threshold_ms=1500.0, detail={"changed_rows": len(changed_df)})
                            elif do_recalc:
                                if not checked_ids:
                                    st.warning("請先在『刪除 / Delete』勾選欄勾選要重新計算的紀錄，或按『勾選本次顯示』，再按重算。")
                                else:
                                    save_df_all = edited_admin.drop(columns=[delete_col], errors="ignore")
                                    original_display_for_diff = display_admin.drop(columns=[delete_col], errors="ignore")
                                    save_df_all = _v80_sync_datetime_editor_columns(save_df_all, original_display_for_diff)
                                    changed_df = _v78_changed_rows(original_display_for_diff, save_df_all, _id_col)
                                    try:
                                        changed_df.attrs["_spt_changed_columns_by_id"] = _v30025_admin_changed_columns_by_id(original_display_for_diff, save_df_all, _id_col)
                                    except Exception:
                                        pass
                                    if not changed_df.empty:
                                        save_time_records(changed_df, recalc_edited_timestamps=True)
                                    _recalc_t0 = time.perf_counter()
                                    count = recalculate_time_records(checked_ids)
                                    updated_cache = _v78_apply_editor_df_to_cache(admin_source_df, save_df_all, _id_col)
                                    _v78_refresh_related_page_caches(updated_cache, admin_data_key=admin_data_key, ts_key=admin_data_ts_key)
                                    st.success(f"已先同步修改後的開始/結束日期時間，並重新計算 {count} 筆工時，同步更新到 02 歷史紀錄。")
                                    st.session_state[edit_mode_key] = False
                                    st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                                    _spt_perf_tick("01_admin_maintenance_recalc_selected", _recalc_t0, threshold_ms=1500.0, detail={"ids": len(checked_ids)})
                            elif do_delete:
                                if not checked_ids:
                                    st.warning("請先在『刪除 / Delete』勾選欄勾選要刪除的紀錄，或按『勾選本次顯示』，再按刪除。")
                                else:
                                    _delete_t0 = time.perf_counter()
                                    count = delete_time_records(checked_ids, reason="01 工時紀錄管理員維護區刪除")
                                    if count <= 0:
                                        try:
                                            count = delete_time_records_from_editor_df(edited_admin, delete_column=delete_col, reason="01 工時紀錄管理員維護區刪除")
                                        except Exception:
                                            pass
                                    st.session_state[admin_select_key] = []
                                    updated_cache = _v78_remove_ids_from_cache(admin_source_df, _id_col, checked_ids)
                                    _v78_refresh_related_page_caches(updated_cache, admin_data_key=admin_data_key, ts_key=admin_data_ts_key)
                                    st.success(f"已由管理員刪除 {count} 筆今日工時紀錄，並同步更新 01 頁面暫存顯示。")
                                    st.session_state[edit_mode_key] = False
                                    st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                                    _spt_perf_tick("01_admin_maintenance_delete_selected", _delete_t0, threshold_ms=1500.0, detail={"ids": len(checked_ids)})

_spt_perf_tick("01_full_page_total_runtime", _SPT_01_PAGE_T0, threshold_ms=1500.0, detail={"is_admin": bool(is_admin)})

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

