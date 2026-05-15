# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.permission_service import (
    ACTIONS,
    MODULES,
    ROLE_DESCRIPTIONS,
    delete_users,
    get_account_permissions,
    get_security_settings,
    get_users,
    init_permission_tables,
    save_account_permissions,
    save_security_settings,
    save_users,
)

apply_theme()
render_header("10 | 權限管理", "帳號密碼總表、帳號級模組權限、角色說明、套用後才儲存 / Account Password & Permission Management")
init_permission_tables()

st.caption("V1.33 loaded｜帳號密碼總表可編輯、帳號可刪除、每個帳號可獨立設定每個模組權限；編輯時只預覽，按套用才正式寫入。")

ROLE_OPTIONS = ["admin", "manager", "leader", "operator", "viewer", "auditor"]
ACTION_COLS = [a[0] for a in ACTIONS]

with st.expander("📘 權限設定使用說明 / User Guide", expanded=False):
    st.markdown("""
### 權限管理邏輯 / Permission Logic

1. **帳號密碼總表 / Account & Password Master**  
   可新增帳號、修改帳號資料、設定新密碼、停用帳號、刪除帳號。  
   密碼基於安全性不會顯示明碼；如需修改密碼，請填寫「新密碼 / New Password」。

2. **帳號模組權限 / Account × Module Permissions**  
   每個帳號都可以針對每一個模組獨立勾選權限，不一定只依角色。  
   例如同樣是 leader，也可以只讓 A 幹部看人員名單，B 幹部可以匯出報表。

3. **先預覽、後套用 / Preview First, Apply Later**  
   表格編輯後會先顯示即時計算結果，但不會立即寫入資料庫。  
   必須按「套用並儲存」才會正式生效。

4. **刪除帳號 / Delete Account**  
   勾選「刪除 / Delete」後按儲存才會刪除。系統保護 admin 帳號，不會刪除預設 admin。

5. **建議 / Recommendation**  
   09 資料永久保存與備份、10 權限管理、11 登入紀錄，建議只開給 Admin 或 Auditor。  
   一般作業人員建議只開放 01 工時紀錄、02 自己歷史、08 自己每日工時。
""")

with st.expander("🧭 角色權限說明 / Role Permission Description", expanded=False):
    role_rows = []
    for role_code, info in ROLE_DESCRIPTIONS.items():
        role_rows.append({
            "角色代碼 / Role Code": role_code,
            "中文角色 / Chinese Role": info["zh"],
            "英文角色 / English Role": info["en"],
            "建議用途 / Recommendation": info["desc"],
        })
    st.dataframe(pd.DataFrame(role_rows), use_container_width=True, hide_index=True)


def _to_bool_series(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df))
    return df[col].fillna(default).astype(bool)


def _blank_user_row() -> dict:
    return {
        "刪除 / Delete": False,
        "帳號 / Username": "",
        "密碼狀態 / Password Status": "新帳號請輸入新密碼",
        "新密碼 / New Password": "",
        "工號 / Employee ID": "",
        "姓名 / Display Name": "",
        "Email": "",
        "角色 / Role": "operator",
        "啟用 / Active": True,
        "強制改密碼 / Force Change": False,
        "備註 / Note": "",
        "最後登入 / Last Login": "",
        "更新時間 / Updated At": "",
    }


def _users_for_editor() -> pd.DataFrame:
    raw = pd.DataFrame(get_users())
    if raw.empty:
        return pd.DataFrame([_blank_user_row()]).iloc[0:0]
    out = pd.DataFrame()
    out["刪除 / Delete"] = False
    out["帳號 / Username"] = raw.get("username", "")
    out["密碼狀態 / Password Status"] = raw.get("password_display", "********")
    out["新密碼 / New Password"] = raw.get("new_password", "")
    out["工號 / Employee ID"] = raw.get("employee_id", "")
    out["姓名 / Display Name"] = raw.get("display_name", "")
    out["Email"] = raw.get("email", "")
    out["角色 / Role"] = raw.get("role_code", "operator")
    out["啟用 / Active"] = raw.get("is_active", 1).fillna(1).astype(bool) if "is_active" in raw else True
    out["強制改密碼 / Force Change"] = raw.get("force_password_change", 0).fillna(0).astype(bool) if "force_password_change" in raw else False
    out["備註 / Note"] = raw.get("note", "")
    out["最後登入 / Last Login"] = raw.get("last_login_at", "")
    out["更新時間 / Updated At"] = raw.get("updated_at", "")
    return out


def _users_to_service_rows(df: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "username": str(r.get("帳號 / Username", "")).strip(),
            "new_password": str(r.get("新密碼 / New Password", "")).strip(),
            "employee_id": str(r.get("工號 / Employee ID", "")).strip(),
            "display_name": str(r.get("姓名 / Display Name", "")).strip(),
            "email": str(r.get("Email", "")).strip(),
            "role_code": str(r.get("角色 / Role", "operator")).strip() or "operator",
            "is_active": bool(r.get("啟用 / Active", True)),
            "force_password_change": bool(r.get("強制改密碼 / Force Change", False)),
            "note": str(r.get("備註 / Note", "")).strip(),
        })
    return rows


def _permission_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    calc = df.copy()
    for c in ACTION_COLS:
        if c in calc.columns:
            calc[c] = calc[c].fillna(False).astype(bool).astype(int)
        else:
            calc[c] = 0
    summary = calc.groupby("username", as_index=False).agg(
        可進入模組數_View=("can_view", "sum"),
        可新增_Create=("can_create", "sum"),
        可編輯_Edit=("can_edit", "sum"),
        可刪除_Delete=("can_delete", "sum"),
        可匯入_Import=("can_import", "sum"),
        可匯出_Export=("can_export", "sum"),
        可備份_Backup=("can_backup", "sum"),
        可還原_Restore=("can_restore", "sum"),
        可管理_Manage=("can_manage", "sum"),
    )
    return summary


tab_accounts, tab_perm, tab_sec = st.tabs([
    "帳號密碼總表 / Account Password Master",
    "帳號模組權限 / Account Module Permissions",
    "安全設定 / Security",
])

with tab_accounts:
    st.subheader("帳號密碼總表 / Account & Password Master")
    st.info("密碼不顯示明碼。要修改密碼時，請在『新密碼 / New Password』填入新密碼；空白代表維持原密碼。勾選刪除後按儲存才會真正刪除。")

    if "v133_users_df" not in st.session_state:
        st.session_state["v133_users_df"] = _users_for_editor()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("➕ 新增帳號 / Add User", use_container_width=True):
            st.session_state["v133_users_df"] = pd.concat([
                st.session_state["v133_users_df"],
                pd.DataFrame([_blank_user_row()]),
            ], ignore_index=True)
    with c2:
        if st.button("🗑️ 刪除欄全選 / Select Delete", use_container_width=True):
            st.session_state["v133_users_df"]["刪除 / Delete"] = True
    with c3:
        if st.button("↩️ 刪除欄取消 / Clear Delete", use_container_width=True):
            st.session_state["v133_users_df"]["刪除 / Delete"] = False
    with c4:
        if st.button("🔄 重新載入 / Reload", use_container_width=True):
            st.session_state["v133_users_df"] = _users_for_editor()
            st.rerun()

    edited_users = st.data_editor(
        st.session_state["v133_users_df"],
        key="v133_account_password_editor",
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "刪除 / Delete": st.column_config.CheckboxColumn("刪除 / Delete"),
            "帳號 / Username": st.column_config.TextColumn("帳號 / Username", required=True, help="登入帳號，不可空白"),
            "密碼狀態 / Password Status": st.column_config.TextColumn("密碼狀態 / Password Status", disabled=True, help="系統不顯示明碼，只顯示是否已有密碼"),
            "新密碼 / New Password": st.column_config.TextColumn("新密碼 / New Password", help="要改密碼才填寫；新增帳號必填"),
            "工號 / Employee ID": st.column_config.TextColumn("工號 / Employee ID"),
            "姓名 / Display Name": st.column_config.TextColumn("姓名 / Display Name", required=True),
            "Email": st.column_config.TextColumn("Email"),
            "角色 / Role": st.column_config.SelectboxColumn("角色 / Role", options=ROLE_OPTIONS, required=True),
            "啟用 / Active": st.column_config.CheckboxColumn("啟用 / Active"),
            "強制改密碼 / Force Change": st.column_config.CheckboxColumn("強制改密碼 / Force Change"),
            "備註 / Note": st.column_config.TextColumn("備註 / Note"),
            "最後登入 / Last Login": st.column_config.TextColumn("最後登入 / Last Login", disabled=True),
            "更新時間 / Updated At": st.column_config.TextColumn("更新時間 / Updated At", disabled=True),
        },
    )

    st.session_state["v133_users_df"] = edited_users.copy()
    active_count = int(_to_bool_series(edited_users, "啟用 / Active").sum())
    delete_count = int(_to_bool_series(edited_users, "刪除 / Delete").sum())
    new_password_count = int((edited_users.get("新密碼 / New Password", pd.Series(dtype=str)).fillna("").astype(str).str.strip() != "").sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("啟用帳號 / Active Accounts", active_count)
    m2.metric("待刪除 / Pending Delete", delete_count)
    m3.metric("密碼異動 / Password Changes", new_password_count)

    if st.button("💾 套用並儲存帳號密碼總表 / Apply and Save Account Master", type="primary", use_container_width=True):
        df = edited_users.copy()
        to_delete = df.loc[_to_bool_series(df, "刪除 / Delete"), "帳號 / Username"].dropna().astype(str).str.strip().tolist()
        save_df = df.loc[~_to_bool_series(df, "刪除 / Delete")].copy()
        result = save_users(_users_to_service_rows(save_df))
        deleted = delete_users(to_delete)
        st.success(f"帳號已儲存：{result['saved']} 筆；刪除：{deleted} 筆 / Accounts saved and deleted")
        if result.get("skipped"):
            st.warning("；".join(result["skipped"]))
        st.session_state.pop("v133_users_df", None)
        st.rerun()

with tab_perm:
    st.subheader("帳號模組權限 / Account × Module Permission Matrix")
    st.info("每個帳號可針對每個模組獨立勾選權限。畫面編輯會即時計算預覽，但只有按『套用並儲存權限』才會生效。")

    perm_df = pd.DataFrame(get_account_permissions())
    if perm_df.empty:
        perm_df = pd.DataFrame(columns=["username", "display_name", "role_code", "module_code", "module_name_zh", "module_name_en"] + ACTION_COLS)

    f1, f2, f3 = st.columns(3)
    with f1:
        user_opts = ["全部 / All"] + sorted(perm_df["username"].dropna().unique().tolist())
        selected_user = st.selectbox("帳號篩選 / Filter Username", user_opts)
    with f2:
        module_opts = ["全部 / All"] + [f"{m['module_code']} {m['module_name_zh']} / {m['module_name_en']}" for m in MODULES]
        selected_module = st.selectbox("模組篩選 / Filter Module", module_opts)
    with f3:
        role_opts = ["全部 / All"] + ROLE_OPTIONS
        selected_role = st.selectbox("角色篩選 / Filter Role", role_opts)

    view_df = perm_df.copy()
    if selected_user != "全部 / All":
        view_df = view_df[view_df["username"] == selected_user]
    if selected_module != "全部 / All":
        mod_code = selected_module.split(" ", 1)[0]
        view_df = view_df[view_df["module_code"] == mod_code]
    if selected_role != "全部 / All":
        view_df = view_df[view_df["role_code"] == selected_role]

    st.markdown("#### 快速勾選 / Quick Toggle")
    b1, b2, b3, b4, b5 = st.columns(5)
    with b1:
        if st.button("✅ 可進入全選 / Select View", use_container_width=True):
            view_df["can_view"] = True
    with b2:
        if st.button("⬜ 可進入取消 / Clear View", use_container_width=True):
            view_df["can_view"] = False
    with b3:
        if st.button("✏️ 編輯全選 / Select Edit", use_container_width=True):
            view_df["can_edit"] = True
    with b4:
        if st.button("📤 匯出全選 / Select Export", use_container_width=True):
            view_df["can_export"] = True
    with b5:
        if st.button("🛡️ 管理全選 / Select Manage", use_container_width=True):
            view_df["can_manage"] = True

    base_cols = ["username", "display_name", "role_code", "module_code", "module_name_zh", "module_name_en"]
    col_cfg = {
        "username": st.column_config.TextColumn("帳號 / Username", disabled=True),
        "display_name": st.column_config.TextColumn("姓名 / Name", disabled=True),
        "role_code": st.column_config.TextColumn("角色 / Role", disabled=True),
        "module_code": st.column_config.TextColumn("模組代碼 / Module Code", disabled=True),
        "module_name_zh": st.column_config.TextColumn("模組中文 / Module Chinese", disabled=True),
        "module_name_en": st.column_config.TextColumn("模組英文 / Module English", disabled=True),
    }
    for key, zh, en in ACTIONS:
        col_cfg[key] = st.column_config.CheckboxColumn(f"{zh} / {en}")

    edited_perm = st.data_editor(
        view_df[base_cols + ACTION_COLS],
        key="v133_permission_editor",
        use_container_width=True,
        hide_index=True,
        column_config=col_cfg,
    )

    st.markdown("#### 即時計算預覽 / Live Calculation Preview")
    st.dataframe(_permission_summary(edited_perm), use_container_width=True, hide_index=True)

    if st.button("✅ 套用並儲存權限 / Apply and Save Permissions", type="primary", use_container_width=True):
        saved = save_account_permissions(edited_perm.to_dict("records"))
        st.success(f"權限已套用並儲存：{saved} 筆 / Permissions saved")
        st.rerun()

with tab_sec:
    st.subheader("安全設定 / Security Settings")
    settings = get_security_settings()
    idle = int(settings.get("idle_timeout_minutes", "15") or 15)
    new_idle = st.number_input("閒置自動登出分鐘數 / Idle Auto Logout Minutes", min_value=1, max_value=240, value=idle, step=1)
    confirm_after_record = st.checkbox("工時完成後詢問是否繼續記錄 / Ask continue after time record", value=settings.get("ask_continue_after_record", "1") != "0")
    if st.button("✅ 套用安全設定 / Apply Security Settings", type="primary", use_container_width=True):
        save_security_settings({
            "idle_timeout_minutes": str(int(new_idle)),
            "ask_continue_after_record": "1" if confirm_after_record else "0",
        })
        st.success("安全設定已儲存 / Security settings saved")
        st.rerun()
