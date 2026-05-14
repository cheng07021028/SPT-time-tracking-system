# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import (
    PERMISSION_COLUMNS,
    create_or_update_user,
    get_idle_timeout_minutes,
    permissions_df,
    require_module_access,
    roles_df,
    save_permissions,
    set_idle_timeout_minutes,
    users_df,
)

st.set_page_config(page_title="10. 權限管理", page_icon="🔐", layout="wide")
apply_theme()
require_module_access("10_permissions", "can_manage")
render_header("10｜權限管理", "帳號、角色、模組權限、閒置自動登出與安全設定")

st.warning("正式上線前，請先修改預設帳號密碼，並確認 09 資料永久保存已可上傳 GitHub。")

tab_users, tab_permissions, tab_settings = st.tabs(["帳號管理", "角色權限矩陣", "安全設定"])

with tab_users:
    st.subheader("帳號管理 / User Management")
    role_options = roles_df()["role_code"].tolist()

    with st.expander("新增 / 修改帳號", expanded=True):
        c1, c2, c3 = st.columns(3)
        username = c1.text_input("帳號 / Username")
        display_name = c2.text_input("顯示名稱 / Display Name")
        employee_id = c3.text_input("工號 / Employee ID")
        c4, c5, c6 = st.columns(3)
        email = c4.text_input("Email")
        password = c5.text_input("新密碼 / New Password", type="password", help="新增帳號必填；修改帳號時留空代表不改密碼。")
        active = c6.checkbox("啟用 / Active", value=True)
        selected_roles = st.multiselect("角色 / Roles", role_options, default=["operator"] if "operator" in role_options else [])
        if st.button("💾 儲存帳號 / Save User", use_container_width=True):
            try:
                create_or_update_user(username, display_name, password, employee_id, email, active, selected_roles)
                st.success("帳號已儲存。")
                st.rerun()
            except Exception as e:
                st.error(f"帳號儲存失敗：{e}")

    df = users_df()
    st.dataframe(df, use_container_width=True, height=420)
    st.caption("安全設計：密碼只保存雜湊值，不保存明碼。角色以逗號顯示；若需調整角色，請在上方輸入帳號後重新儲存。")

with tab_permissions:
    st.subheader("角色 × 模組 × 權限矩陣 / Role Permission Matrix")
    st.caption("勾選代表授權；沒有勾選就是沒有權限。Admin 預設具備全部權限。")
    df = permissions_df()
    edited = st.data_editor(
        df,
        use_container_width=True,
        height=640,
        hide_index=True,
        disabled=["role_code", "module_no", "module_code", "module_name", "module_name_en", "updated_at"],
        column_config={
            "role_code": "角色 / Role",
            "module_no": "模組 / No.",
            "module_code": "模組代碼 / Module Code",
            "module_name": "模組名稱 / Module",
            "module_name_en": "英文 / English",
            "can_view": "可進入 / View",
            "can_create": "新增 / Create",
            "can_edit": "編輯 / Edit",
            "can_delete": "刪除 / Delete",
            "can_import": "匯入 / Import",
            "can_export": "匯出 / Export",
            "can_backup": "備份 / Backup",
            "can_restore": "還原 / Restore",
            "can_manage": "管理 / Manage",
        },
        key="permission_matrix_editor",
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("💾 儲存權限矩陣 / Save Permissions", use_container_width=True):
        save_permissions(edited)
        st.success("權限矩陣已儲存。")
        st.rerun()
    if c2.button("✅ 目前畫面全部勾選", use_container_width=True):
        tmp = edited.copy()
        for col in PERMISSION_COLUMNS:
            tmp[col] = True
        st.session_state["permission_matrix_editor"] = tmp
        st.rerun()
    if c3.button("⬜ 目前畫面全部取消", use_container_width=True):
        tmp = edited.copy()
        for col in PERMISSION_COLUMNS:
            tmp[col] = False
        st.session_state["permission_matrix_editor"] = tmp
        st.rerun()

with tab_settings:
    st.subheader("安全設定 / Security Settings")
    current_idle = get_idle_timeout_minutes()
    idle = st.number_input("閒置自動登出時間，單位分鐘 / Idle auto logout minutes", min_value=1, max_value=240, value=int(current_idle), step=1)
    if st.button("💾 儲存閒置登出設定 / Save Idle Timeout", use_container_width=True):
        set_idle_timeout_minutes(int(idle))
        st.success(f"已設定閒置 {int(idle)} 分鐘自動登出。")
        st.rerun()

    st.markdown("### 建議權限設計")
    st.markdown("""
- Admin：全部權限。
- Manager：可查詢、匯出、維護製令與人員，備份但不建議還原。
- Leader：可操作工時、勾選人員在廠 / 今日出勤、查看現場報表。
- Operator：只操作工時與查看自己的資料。
- Viewer：只讀報表。
- Auditor：查看歷史紀錄、LOG、登入紀錄與匯出稽核資料。
""")
