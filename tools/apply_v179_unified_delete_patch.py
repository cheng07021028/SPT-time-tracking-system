# -*- coding: utf-8 -*-
"""Apply V179 unified delete patch.

This script appends a final backend override to services/time_record_service.py and
patches 01/02 delete button handlers to use the V179 unified delete lane. It does
not change CSS, theme_service, Streamlit visual layout, or table rendering.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRS = ROOT / "services" / "time_record_service.py"
PAGES = ROOT / "pages"
MARK = "# ===================== V179 UNIFIED TIME RECORD DELETE PATCH ====================="

APPEND_BLOCK = r'''

# ===================== V179 UNIFIED TIME RECORD DELETE PATCH =====================
# Backend-only safety layer. Do not change UI/theme/table rendering.
try:
    _v179_prev_delete_time_records = delete_time_records
except Exception:  # pragma: no cover
    _v179_prev_delete_time_records = None
try:
    _v179_prev_load_records = load_records
except Exception:  # pragma: no cover
    _v179_prev_load_records = None
try:
    _v179_prev_today_records = today_records
except Exception:  # pragma: no cover
    _v179_prev_today_records = None
try:
    _v179_prev_get_active_records = get_active_records
except Exception:  # pragma: no cover
    _v179_prev_get_active_records = None
try:
    _v179_prev_get_active_record = get_active_record
except Exception:  # pragma: no cover
    _v179_prev_get_active_record = None


def _v179_filter_deleted_rows(df):
    try:
        from services.time_record_delete_unifier_service import filter_deleted_rows
        return filter_deleted_rows(df)
    except Exception:
        return df


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    """V179 final delete lane: delete from 01/02 authority + SQLite and write tombstones.

    This intentionally bypasses older wrapper chains that may rebuild data from LOG
    recovery, event journal or SQLite and accidentally make deleted rows reappear.
    """
    try:
        from services.time_record_delete_unifier_service import force_delete_time_records
        return int(force_delete_time_records(record_ids, reason=reason, github=False) or 0)
    except Exception as exc:
        try:
            write_log("V179_DELETE_FALLBACK_ERROR", f"統一刪除通道失敗，改用舊刪除：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        if callable(_v179_prev_delete_time_records):
            return int(_v179_prev_delete_time_records(record_ids, reason=reason) or 0)
        return 0


def load_records(start_date: str | None = None, end_date: str | None = None, employee_id: str | None = None, work_order: str | None = None):  # type: ignore[override]
    df = _v179_prev_load_records(start_date=start_date, end_date=end_date, employee_id=employee_id, work_order=work_order) if callable(_v179_prev_load_records) else pd.DataFrame()
    return _v179_filter_deleted_rows(df)


def today_records(include_finished: bool = True, unfinished_only: bool = False):  # type: ignore[override]
    df = _v179_prev_today_records(include_finished=include_finished, unfinished_only=unfinished_only) if callable(_v179_prev_today_records) else pd.DataFrame()
    return _v179_filter_deleted_rows(df)


def get_active_records(employee_id: str | None = None, process_name: str | None = None, start_date: str | None = None, employee_name: str | None = None):  # type: ignore[override]
    df = _v179_prev_get_active_records(employee_id=employee_id, process_name=process_name, start_date=start_date, employee_name=employee_name) if callable(_v179_prev_get_active_records) else pd.DataFrame()
    return _v179_filter_deleted_rows(df)


def get_active_record(employee_id: str):  # type: ignore[override]
    df = get_active_records(employee_id=employee_id)
    if df is None or getattr(df, "empty", True):
        return None
    try:
        if "id" in df.columns:
            df = df.copy()
            df["_v179_id"] = pd.to_numeric(df["id"], errors="coerce")
            df = df.sort_values("_v179_id", ascending=False).drop(columns=["_v179_id"], errors="ignore")
        return dict(df.iloc[0])
    except Exception:
        return None

# =================== END V179 UNIFIED TIME RECORD DELETE PATCH ===================
'''


def append_time_record_patch() -> None:
    txt = TRS.read_text(encoding="utf-8")
    if MARK not in txt:
        TRS.write_text(txt.rstrip() + APPEND_BLOCK + "\n", encoding="utf-8")


def _find_page(prefix: str, marker: str) -> Path | None:
    for p in sorted(PAGES.glob(f"{prefix}_*.py")):
        try:
            txt = p.read_text(encoding="utf-8")
            if marker in txt:
                return p
        except Exception:
            continue
    return None


def patch_02_page() -> None:
    p = _find_page("02", "歷史紀錄")
    if not p:
        return
    txt = p.read_text(encoding="utf-8")
    if "delete_selected_time_records_from_editor" not in txt:
        txt = txt.replace(
            "from services.time_record_service import (",
            "from services.time_record_service import (",
            1,
        )
        # Add a separate import after the time_record_service import block by placing it after first import section marker.
        anchor = "from services.table_ui_service import"
        if anchor in txt:
            idx = txt.find(anchor)
            line_end = txt.find("\n", idx)
            txt = txt[:line_end+1] + "from services.time_record_delete_unifier_service import delete_selected_time_records_from_editor\n" + txt[line_end+1:]
        else:
            txt = "from services.time_record_delete_unifier_service import delete_selected_time_records_from_editor\n" + txt
    old = '''                    else:
                        count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")
                        st.session_state[delete_select_key] = []
                        st.session_state[recalc_select_key] = []
                        _add_history_result("success", f"已刪除 {count} 筆歷史紀錄。", append=False)
                        _history_refresh_editor()
                        rerun()
'''
    new = '''                    else:
                        try:
                            count = delete_selected_time_records_from_editor(edited, delete_col_label, reason="02 歷史紀錄啟動編輯後整列刪除 V179")
                        except Exception:
                            count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除 V179 fallback")
                        st.session_state[delete_select_key] = []
                        st.session_state[recalc_select_key] = []
                        if int(count or 0) <= 0:
                            _add_history_result("warning", "沒有刪除成功：請確認已勾選刪除欄，或該筆是否已被刪除。", append=False)
                        else:
                            _add_history_result("success", f"已刪除 {count} 筆歷史紀錄，並同步 01/02/SQLite 與 tombstone 防復活。", append=False)
                        _history_refresh_editor()
                        rerun()
'''
    if old in txt and "V179 fallback" not in txt:
        txt = txt.replace(old, new)
    p.write_text(txt, encoding="utf-8")


def patch_01_page() -> None:
    p = _find_page("01", "工時紀錄")
    if not p:
        return
    txt = p.read_text(encoding="utf-8")
    if "delete_selected_time_records_from_editor" not in txt:
        anchor = "from services.table_ui_service import"
        if anchor in txt:
            idx = txt.find(anchor)
            line_end = txt.find("\n", idx)
            txt = txt[:line_end+1] + "from services.time_record_delete_unifier_service import delete_selected_time_records_from_editor\n" + txt[line_end+1:]
        else:
            txt = "from services.time_record_delete_unifier_service import delete_selected_time_records_from_editor\n" + txt
    old = '''                        else:
                            count = delete_time_records(checked_ids, reason="01 工時紀錄管理員維護區刪除")
                            st.session_state[admin_select_key] = []
                            try:
                                clear_today_records_fast_cache()
                            except Exception:
                                pass
                            st.success(f"已由管理員刪除 {count} 筆今日工時紀錄。")
                            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                            st.rerun()
'''
    new = '''                        else:
                            try:
                                count = delete_selected_time_records_from_editor(edited_admin, delete_col, reason="01 工時紀錄管理員維護區刪除 V179")
                            except Exception:
                                count = delete_time_records(checked_ids, reason="01 工時紀錄管理員維護區刪除 V179 fallback")
                            st.session_state[admin_select_key] = []
                            try:
                                clear_today_records_fast_cache()
                            except Exception:
                                pass
                            if int(count or 0) <= 0:
                                st.warning("沒有刪除成功：請確認已勾選刪除欄，或該筆是否已被刪除。")
                            else:
                                st.success(f"已由管理員刪除 {count} 筆今日工時紀錄，並同步 01/02/SQLite 與 tombstone 防復活。")
                            st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                            st.rerun()
'''
    if old in txt and "V179 fallback" not in txt:
        txt = txt.replace(old, new)
    p.write_text(txt, encoding="utf-8")


def main() -> int:
    append_time_record_patch()
    patch_01_page()
    patch_02_page()
    print("V179 unified delete patch applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
