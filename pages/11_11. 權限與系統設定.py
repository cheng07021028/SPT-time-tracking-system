from __future__ import annotations

import pandas as pd
import streamlit as st

from services.data_loader import clear_data_cache, load_table
from services.page_utils import clear_managed_table_state, render_configurable_view, render_module_report_download, render_saveable_table
from services.permission_service import MODULES, PERMISSION_COLUMNS, ROLES, ensure_role_permissions, permissions_for_role, role_options_from_users, save_permissions_for_role
from services.persistent_store import save_authority_df
from services.ui_theme import apply_tech_theme, render_hero, render_human_help

st.set_page_config(page_title="11. 權限與系統設定", page_icon="🔐", layout="wide")
apply_tech_theme()
render_hero("11. 權限與系統設定", "比照工時紀錄系統模式：角色選擇、模組權限、帳號與 SOP 都可在系統內永久保存。")
render_human_help([
    "先選擇角色，再勾選各模組的查看、新增、編輯、刪除、匯出與 GitHub 同步權限。",
    "按『套用並永久保存角色權限』後，權限會寫入 data/persistent/authority/role_permissions.json。",
    "使用者帳號可指定角色；正式登入流程接入後，會以這裡的角色權限為準。",
])

st.subheader("新增帳號")
with st.expander("快速新增帳號（角色下拉選單）", expanded=True):
    with st.form("quick_add_user_form"):
        u1, u2, u3, u4 = st.columns([1.2, 1.2, 1.2, 1])
        account = u1.text_input("帳號")
        user_name = u2.text_input("姓名")
        user_role = u3.selectbox("角色", list(ROLES), index=0)
        enabled = u4.selectbox("啟用", ["是", "否"], index=0)
        note = st.text_input("備註", value="")
        add_user = st.form_submit_button("新增帳號並永久保存", type="primary")
    if add_user:
        if not account.strip():
            st.warning("請輸入帳號。")
        else:
            users_df = load_table("users").copy()
            if users_df.empty:
                users_df = pd.DataFrame(columns=["帳號", "姓名", "角色", "啟用", "可查看模組", "可編輯模組", "備註"])
            if "帳號" in users_df.columns and account.strip() in users_df["帳號"].dropna().astype(str).str.strip().tolist():
                st.warning("此帳號已存在，請直接在下方表格編輯。")
            else:
                users_df.loc[len(users_df)] = {
                    "帳號": account.strip(),
                    "姓名": user_name.strip(),
                    "角色": user_role,
                    "啟用": enabled,
                    "可查看模組": "依角色權限",
                    "可編輯模組": "依角色權限",
                    "備註": note,
                }
                save_authority_df("users", users_df, user="streamlit")
                clear_data_cache()
                clear_managed_table_state("users")
                st.success(f"已新增帳號 {account.strip()}，角色：{user_role}。")
                st.rerun()

st.subheader("角色模組權限管理")
users_preview = render_saveable_table("users", "11. 使用者與角色權限", height=320, helper_text="可維護帳號、姓名、角色、啟用狀態、可查看模組與可編輯模組。角色會對應下方模組權限。")
permissions = ensure_role_permissions()
role_options = role_options_from_users(users_preview)

st.markdown('<div class="permission-panel">', unsafe_allow_html=True)
with st.form("role_permission_form"):
    role = st.selectbox("選擇角色", role_options, index=0, help="選擇角色後設定此角色可使用哪些模組與功能。")
    role_df = permissions_for_role(role, permissions)
    st.caption("勾選後請按下方『套用並永久保存角色權限』，不會因離開頁面而消失。")
    edited_rows: list[dict[str, object]] = []
    header = st.columns([0.7, 2.1, 0.8, 0.8, 0.8, 0.8, 0.8, 1.05])
    labels = ["編號", "模組", "查看", "新增", "編輯", "刪除", "匯出", "GitHub同步"]
    for col, label in zip(header, labels):
        col.markdown(f"**{label}**")
    for _, row in role_df.iterrows():
        module_no = str(row.get("模組編號", ""))
        module_name = str(row.get("模組名稱", ""))
        cols = st.columns([0.7, 2.1, 0.8, 0.8, 0.8, 0.8, 0.8, 1.05])
        cols[0].markdown(f"`{module_no}`")
        cols[1].markdown(f"**{module_name}**")
        values = {}
        for idx, permission_col in enumerate(PERMISSION_COLUMNS, start=2):
            default = str(row.get(permission_col, "否")) == "是"
            values[permission_col] = "是" if cols[idx].checkbox(" ", value=default, key=f"perm_{role}_{module_no}_{permission_col}", label_visibility="collapsed") else "否"
        edited_rows.append({
            "角色": role,
            "模組編號": module_no,
            "模組名稱": module_name,
            **values,
            "備註": str(row.get("備註", "")),
        })
    c1, c2, c3 = st.columns([1.4, 1.2, 3.6])
    apply = c1.form_submit_button("套用並永久保存角色權限", type="primary")
    full = c2.form_submit_button("此角色全開")
    view_only = c3.form_submit_button("此角色只保留查看/匯出")

if apply or full or view_only:
    new_df = pd.DataFrame(edited_rows)
    if full:
        for col in PERMISSION_COLUMNS:
            new_df[col] = "是"
    if view_only:
        for col in PERMISSION_COLUMNS:
            new_df[col] = "否"
        new_df["可查看"] = "是"
        new_df["可匯出"] = "是"
    save_permissions_for_role(role, new_df, user="streamlit")
    clear_data_cache()
    st.success(f"已永久保存角色『{role}』的模組權限。")
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

st.subheader("角色權限總表")
permissions = ensure_role_permissions()
render_configurable_view(permissions, "role_permissions", "11. 角色權限總表", height=420)

st.subheader("模組備註 / SOP")
notes = render_saveable_table("module_notes", "11. 模組備註", height=360, helper_text="可將每個模組的操作方式、欄位定義與注意事項保存於系統內，方便交接與日常使用。")

st.subheader("11. 模組完整匯出")
render_module_report_download(
    "11.權限與系統設定",
    {"使用者權限": users_preview, "角色模組權限": permissions, "模組備註": notes, "系統模組清單": pd.DataFrame(MODULES, columns=["模組編號", "模組名稱"])},
    metadata={"模組": "11. 權限與系統設定", "匯出內容": "使用者權限、角色模組權限與模組備註"},
    key="export_permissions_module",
)
