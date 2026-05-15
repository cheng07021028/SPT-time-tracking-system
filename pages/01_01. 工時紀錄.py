# -*- coding: utf-8 -*-
from __future__ import annotations

import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import (
    check_permission,
    get_current_user,
    require_module_access,
    render_post_record_continue_prompt,
    trigger_post_record_continue_prompt,
)
from services.master_data_service import load_employees, load_work_orders
from services.time_record_service import (
    delete_time_records,
    recalculate_time_records,
    finish_work,
    get_active_group,
    get_active_record,
    save_time_records,
    start_work,
    today_records,
)
from services.db_service import query_one
from services.table_ui_service import render_table
from services.system_settings_service import get_process_options

st.set_page_config(page_title="01. 工時紀錄", page_icon="▶️", layout="wide")
apply_theme()
require_module_access("01_time_record")
render_header("01｜工時紀錄", "快速開始、同步作業、暫停、下班、完工｜自動記錄時間與扣除休息")
render_post_record_continue_prompt()

PROCESS_OPTIONS = get_process_options()

employees = load_employees(active_only=True, in_factory_only=False)
work_orders = load_work_orders(active_only=True)

if employees.empty or work_orders.empty:
    if st.session_state.get("_spt_employee_binding_required"):
        st.warning("該人員未在人員名單，請洽管理員設定。")
    else:
        st.warning("請先到『03. 製令管理』與『04. 人員名單』匯入或新增資料。")
    st.stop()

left, right = st.columns([1.1, 1])
with left:
    st.subheader("開始作業 / Start Work")
    emp_label = st.selectbox("工號 / 姓名｜Employee", employees.apply(lambda r: f"{r['employee_id']}｜{r['employee_name']}", axis=1).tolist())
    emp_id = emp_label.split("｜")[0]
    employee = query_one("SELECT * FROM employees WHERE employee_id=?", (emp_id,))

    wo_label = st.selectbox("製令｜Work Order", work_orders.apply(lambda r: f"{r['work_order']}｜{r.get('part_no','')}｜{r.get('type_name','')}", axis=1).tolist())
    wo_no = wo_label.split("｜")[0]
    work_order = query_one("SELECT * FROM work_orders WHERE work_order=?", (wo_no,))

    process = st.selectbox("工段名稱｜Process", PROCESS_OPTIONS)
    remark = st.text_area("備註｜Remark", height=90)
    auto_pause = st.checkbox("切換不同工段時，自動暫停同人員其他未結束作業｜Auto pause different process", value=True)

    active = get_active_record(emp_id)
    if active:
        group = get_active_group(int(active["id"]))
        st.info(f"目前作業中：{active['process_name']}，同步計時 {len(group)} 筆。開始其中任一不同工段時，舊工段會自動暫停。")

    if st.button("▶ 開始作業 / Start", use_container_width=True):
        if not check_permission("01_time_record", "can_create"):
            st.error("權限不足：你沒有新增工時紀錄權限。")
        else:
            rid = start_work(employee, work_order, process, remark, auto_pause_old=auto_pause)
            trigger_post_record_continue_prompt(
                f"已開始作業，紀錄編號：{rid}。請確認是否繼續操作下一筆紀錄；若不繼續，系統會立即登出帳號。",
                title="已開始計時",
            )
            st.rerun()

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
        if c2.button("🏁 完工 / Complete", use_container_width=True):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                n = finish_work(active2["id"], "完工", end_remark, finish_parallel_group=True)
                trigger_post_record_continue_prompt(f"已同步完工 {n} 筆並平均計算工時。", title="工時已完工")
                st.rerun()
        if c3.button("🌙 下班 / Off Duty", use_container_width=True):
            if not check_permission("01_time_record", "can_edit"):
                st.error("權限不足：你沒有結束 / 編輯工時權限。")
            else:
                n = finish_work(active2["id"], "下班", end_remark, finish_parallel_group=True)
                trigger_post_record_continue_prompt(f"已同步下班 {n} 筆並平均計算工時。", title="工時已結束")
                st.rerun()

st.divider()
st.subheader("今日工時紀錄 / Today Records")
df = today_records()
render_table(df, "today_records", editable=False, height=420)

# V1.81：修改、刪除、存檔功能只允許管理員看見與操作。
# 一般作業人員只能開始/暫停/下班/完工，不顯示人工維護工具，避免冒用或誤刪資料。
user = get_current_user() or {}
is_admin = "admin" in [str(x).lower() for x in user.get("roles", [])]

if is_admin:
    st.divider()
    with st.expander("🔐 管理員工時紀錄維護｜修改、刪除、存檔", expanded=False):
        st.warning("此區僅管理員可見。修改或刪除會直接影響正式工時紀錄，請確認後再存檔。")
        if df.empty:
            st.info("今日目前沒有可維護的工時紀錄。")
        else:
            admin_df = df.copy()
            admin_df.insert(0, "刪除", False)
            edited_admin = render_table(
                admin_df,
                "today_records_admin_maintenance",
                editable=True,
                disabled=["id", "record_key", "created_at", "updated_at"],
                key="today_records_admin_editor",
                height=460,
            )
            if edited_admin is not None:
                b1, b2 = st.columns(2)
                if b1.button("💾 管理員存檔修改", use_container_width=True, key="admin_save_today_records"):
                    save_df = edited_admin.drop(columns=["刪除"], errors="ignore")
                    count = save_time_records(save_df)
                    st.success(f"已由管理員存檔修改 {count} 筆今日工時紀錄。")
                    st.rerun()

                delete_ids = []
                try:
                    delete_rows = edited_admin[edited_admin["刪除"].astype(bool)]
                    delete_ids = [int(x) for x in delete_rows["id"].dropna().tolist()]
                except Exception:
                    delete_ids = []

                delete_disabled = len(delete_ids) == 0
                if b2.button(
                    f"🗑️ 管理員刪除勾選紀錄（{len(delete_ids)}）",
                    use_container_width=True,
                    key="admin_delete_today_records",
                    disabled=delete_disabled,
                ):
                    count = delete_time_records(delete_ids, reason="01 工時紀錄管理員維護區刪除")
                    st.success(f"已由管理員刪除 {count} 筆今日工時紀錄。")
                    st.rerun()

                if st.button("🧮 管理員重新計算勾選紀錄工時並同步 02 歷史紀錄", use_container_width=True, key="admin_recalc_today_records", disabled=delete_disabled):
                    count = recalculate_time_records(delete_ids)
                    st.success(f"已重新計算 {count} 筆工時，並同步更新到 02 歷史紀錄。")
                    st.rerun()
