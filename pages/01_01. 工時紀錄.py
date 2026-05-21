# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st
import pandas as pd

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
    clear_today_finished_from_work_page,
    delete_time_records,
    recalculate_time_records,
    finish_work,
    get_active_group,
    get_active_record,
    get_conflicting_active_records,
    get_active_same_work,
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
with left:
    st.subheader("開始作業 / Start Work")
    emp_label = st.selectbox("工號 / 姓名｜Employee", employees.apply(lambda r: f"{r['employee_id']}｜{r['employee_name']}", axis=1).tolist())
    emp_id = emp_label.split("｜")[0]
    emp_match = employees[employees["employee_id"].fillna("").astype(str).str.strip() == emp_id]
    employee = emp_match.iloc[0].fillna("").to_dict() if not emp_match.empty else (query_one("SELECT * FROM employees WHERE employee_id=?", (emp_id,)) or {})

    wo_label = st.selectbox("製令｜Work Order", work_orders.apply(lambda r: f"{r['work_order']}｜{r.get('part_no','')}｜{r.get('type_name','')}", axis=1).tolist())
    wo_no = wo_label.split("｜")[0]
    wo_match = work_orders[work_orders["work_order"].fillna("").astype(str).str.strip() == wo_no]
    work_order = wo_match.iloc[0].fillna("").to_dict() if not wo_match.empty else (query_one("SELECT * FROM work_orders WHERE work_order=?", (wo_no,)) or {})

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
    emp_label2 = st.selectbox("選擇人員｜Employee", employees.apply(lambda r: f"{r['employee_id']}｜{r['employee_name']}", axis=1).tolist(), key="end_emp")
    emp_id2 = emp_label2.split("｜")[0]
    active2 = get_active_record(emp_id2)
    if not active2:
        st.success("此人員目前沒有未結束作業。")
    else:
        group_df = get_active_group(int(active2["id"]))
        st.markdown(
            f"""
<div class="spt-card spt-glow">
<b>目前作業中 / Active Work</b><br>
工段：{active2['process_name']}<br>
同步計時：{len(group_df)} 筆<br>
說明：按下暫停、下班或完工時，會同步結束同一人員、同一天、同一工段的所有未結束計時，並平均分配工時。<br>
</div>
""",
            unsafe_allow_html=True,
        )
        render_table(group_df, "active_parallel_group", editable=False, height=230)
        end_remark = st.text_input("結束備註｜Finish Remark", key="end_remark")
        c1, c2, c3 = st.columns(3)
        if c1.button("⏸ 暫停 / Pause", use_container_width=True):
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
        if c3.button("◐ 下班 / Off Duty", use_container_width=True):
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
            st.success(f"已重新整理 01 頁顯示；02 歷史紀錄不受影響。已隱藏目前已結束筆數：{n}")
            st.rerun()
df = today_records(include_finished=not show_unfinished_only, unfinished_only=show_unfinished_only)
if is_admin and not df.empty:
    with st.expander("▤ 01 工時紀錄表格欄位位置順序調整 / Admin Column Order Settings", expanded=False):
        st.caption("此區僅系統管理員可見。可調整今日工時紀錄表格的欄位寬度與欄位位置順序；設定會永久保存。")
        render_width_settings("01.time_records.main", df, title="01 工時紀錄欄位順序與欄寬設定 / Column Order and Width")
render_table(df, "01.time_records.main", editable=False, height=420)

# V1.81：修改、刪除、存檔功能只允許管理員看見與操作。
# 一般作業人員只能開始/暫停/下班/完工，不顯示人工維護工具，避免冒用或誤刪資料。
if is_admin:
    st.divider()
    with st.expander("▤ 管理員工時紀錄維護｜修改、刪除、存檔", expanded=False):
        st.warning("此區僅管理員可見。修改或刪除會直接影響正式工時紀錄，請確認後再存檔。")
        if df.empty:
            st.info("今日目前沒有可維護的工時紀錄。")
        else:
            admin_df = df.copy()
            admin_select_key = "_spt_select_today_records_admin_delete_ids"
            editor_version_key = "today_records_admin_editor_version"
            if editor_version_key not in st.session_state:
                st.session_state[editor_version_key] = 0
            _all_admin_ids = [int(x) for x in admin_df["id"].dropna().tolist()] if "id" in admin_df.columns else []
            _selected_admin_ids = set(int(x) for x in st.session_state.get(admin_select_key, []) if int(x) in set(_all_admin_ids))
            sc1, sc2, sc3 = st.columns([1, 1, 3])
            if sc1.button("◈ 勾選全部紀錄 / Select All", use_container_width=True, key="today_admin_select_all_rows"):
                st.session_state[admin_select_key] = _all_admin_ids
                st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                st.rerun()
            if sc2.button("◌ 取消全部勾選 / Clear All", use_container_width=True, key="today_admin_clear_all_rows"):
                st.session_state[admin_select_key] = []
                st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                st.rerun()
            sc3.caption("勾選會保留到你手動取消、刪除成功或離開本頁；不會因重新計算後自動清空。")
            _selected_admin_ids = set(int(x) for x in st.session_state.get(admin_select_key, []) if int(x) in set(_all_admin_ids))
            admin_df.insert(0, "刪除", admin_df["id"].map(lambda x: int(x) in _selected_admin_ids if str(x).strip() not in {"", "nan", "None"} else False) if "id" in admin_df.columns else False)
            # V2.34：全選/取消全選後必須換新 data_editor key，否則 Streamlit 會沿用舊 widget 暫存，看起來按鈕無作用。
            editor_key = f"today_records_admin_editor_{st.session_state[editor_version_key]}"
            st.info("V2.28：確認執行後會重新載入表格，畫面會同步顯示最新日期、時間與工時小計。")
            with st.form("today_records_admin_commit_form", clear_on_submit=False):
                edited_admin = render_table(
                    admin_df,
                    "today_records_admin_maintenance",
                    editable=True,
                    disabled=["id", "record_key", "created_at", "updated_at"],
                    key=editor_key,
                    height=460,
                )
                st.markdown("**確認後執行動作 / Confirm Action**")
                act_save_col, act_recalc_col, act_delete_col = st.columns([1.1, 1.8, 1.2])
                save_admin_clicked = act_save_col.form_submit_button(
                    "◈ 僅儲存修改 / Save",
                    type="primary",
                    use_container_width=True,
                )
                recalc_admin_clicked = act_recalc_col.form_submit_button(
                    "◇ 重算勾選工時並同步 02 / Recalc Selected",
                    type="primary",
                    use_container_width=True,
                )
                delete_admin_clicked = act_delete_col.form_submit_button(
                    "◉ 刪除勾選整列 / Delete Selected",
                    type="primary",
                    use_container_width=True,
                )
                submitted_admin = bool(save_admin_clicked or recalc_admin_clicked or delete_admin_clicked)
                if save_admin_clicked:
                    admin_action = "僅儲存修改"
                elif recalc_admin_clicked:
                    admin_action = "重新計算勾選紀錄工時並同步 02 歷史紀錄"
                elif delete_admin_clicked:
                    admin_action = "刪除勾選整列紀錄"
                else:
                    admin_action = ""

            if submitted_admin and edited_admin is not None:
                delete_ids = []
                try:
                    delete_rows = edited_admin[edited_admin["刪除"].astype(bool)]
                    delete_ids = [int(x) for x in delete_rows["id"].dropna().tolist()]
                except Exception:
                    delete_ids = []
                # V2.32：保留目前勾選狀態，直到使用者取消、刪除成功或離開頁面。
                st.session_state[admin_select_key] = delete_ids

                if admin_action == "僅儲存修改":
                    save_df = edited_admin.drop(columns=["刪除"], errors="ignore")
                    count = save_time_records(save_df)
                    st.success(f"已由管理員存檔修改 {count} 筆今日工時紀錄。")
                    st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                    st.rerun()
                elif admin_action == "重新計算勾選紀錄工時並同步 02 歷史紀錄":
                    if not delete_ids:
                        st.warning("請先在『刪除』勾選欄勾選要重新計算的紀錄，再按確認執行。")
                    else:
                        # V2.26：若管理員剛修改開始/結束時間戳，先儲存並同步日期/時間欄位，再重新計算。
                        save_df = edited_admin.drop(columns=["刪除"], errors="ignore")
                        save_time_records(save_df, recalc_edited_timestamps=True)
                        count = recalculate_time_records(delete_ids)
                        st.success(f"已先同步修改後的開始/結束日期時間，並重新計算 {count} 筆工時，同步更新到 02 歷史紀錄。")
                        st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                        st.rerun()
                else:
                    if not delete_ids:
                        st.warning("請先在『刪除』勾選欄勾選要刪除的紀錄，再按確認執行。")
                    else:
                        count = delete_time_records(delete_ids, reason="01 工時紀錄管理員維護區刪除")
                        remaining = [x for x in st.session_state.get(admin_select_key, []) if int(x) not in set(delete_ids)]
                        st.session_state[admin_select_key] = remaining
                        st.success(f"已由管理員刪除 {count} 筆今日工時紀錄。")
                        st.session_state[editor_version_key] = int(st.session_state.get(editor_version_key, 0)) + 1
                        st.rerun()
