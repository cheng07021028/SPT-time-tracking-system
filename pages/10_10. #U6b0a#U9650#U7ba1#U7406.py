# -*- coding: utf-8 -*-
from __future__ import annotations

from io import StringIO
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
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
require_module_access("10_permissions", "can_manage")
render_header("10 | 權限管理", "帳號密碼總表、帳號匯入、帳號貼上、帳號級模組權限 / Account & Permission Management")
init_permission_tables()

st.caption("V1.78 loaded｜權限管理頁已受 can_manage 管制；帳號、權限、安全設定會永久保存到 GitHub 設定檔。")

ROLE_OPTIONS = ["admin", "manager", "leader", "operator", "viewer", "auditor"]
ACTION_COLS = [a[0] for a in ACTIONS]

ACCOUNT_HEADER_ALIASES = {
    "username": ["帳號", "登入帳號", "使用者", "使用者帳號", "username", "user", "account", "login id", "login_id"],
    "new_password": ["密碼", "新密碼", "預設密碼", "password", "new password", "new_password", "pwd"],
    "employee_id": ["工號", "員工編號", "人員編號", "employee id", "employee_id", "emp id", "emp_id"],
    "display_name": ["姓名", "顯示名稱", "員工姓名", "人員姓名", "display name", "display_name", "name"],
    "email": ["email", "e-mail", "信箱", "電子信箱", "mail"],
    "role_code": ["角色", "角色代碼", "權限角色", "role", "role_code", "role code"],
    "is_active": ["啟用", "啟用狀態", "active", "is_active", "在職", "有效"],
    "force_password_change": ["強制改密碼", "首次登入改密碼", "force change", "force_password_change", "force password change"],
    "note": ["備註", "說明", "note", "remark", "remarks", "memo"],
}

ACCOUNT_DISPLAY_COLUMNS = {
    "username": "帳號 / Username",
    "new_password": "密碼 / Password",
    "employee_id": "工號 / Employee ID",
    "display_name": "姓名 / Display Name",
    "email": "Email",
    "role_code": "角色 / Role",
    "is_active": "啟用 / Active",
    "force_password_change": "強制改密碼 / Force Change",
    "note": "備註 / Note",
}

with st.expander("⧠ 權限設定使用說明 / User Guide", expanded=False):
    st.markdown("""
### 密碼欄位說明 / Password Field Design
- **密碼 / Password** 欄可直接輸入新密碼；既有帳號顯示 `********` 代表維持原密碼。
- 系統不會顯示既有密碼明碼，只顯示 `********` 或狀態提示。
- 要新增或修改密碼，可填 **密碼 / Password** 或 **新密碼 / New Password**；匯入資料中的 **密碼 / Password** 也會套用。
- 空白代表維持原密碼，不會清掉密碼。

### 匯入帳號格式 / Account Import Format
建議 Excel 或貼上資料包含標題列，系統會依標題自動對應欄位：

`帳號、密碼、工號、姓名、Email、角色、啟用、強制改密碼、備註`

角色可填：`admin / manager / leader / operator / viewer / auditor`，也可填中文：系統管理員、製造主管、現場幹部、作業人員、查詢者、稽核。
""")

with st.expander("⌖ 角色權限說明 / Role Permission Description", expanded=False):
    st.dataframe(pd.DataFrame([
        {
            "角色代碼 / Role Code": role_code,
            "中文角色 / Chinese Role": info["zh"],
            "英文角色 / English Role": info["en"],
            "建議用途 / Recommendation": info["desc"],
        }
        for role_code, info in ROLE_DESCRIPTIONS.items()
    ]), use_container_width=True, hide_index=True)


def _as_bool_value(value, default: bool = False) -> bool:
    """Robust checkbox value parser for Streamlit data_editor.

    Streamlit versions may return bool, numpy bool, integers, or text-like values
    after column conversions.  Deletion must not silently fail because the UI
    value came back as a string.
    """
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on", "checked", "☑", "✅", "是", "勾選", "刪除", "delete"}:
        return True
    if text in {"false", "0", "no", "n", "off", "unchecked", "☐", "□", "否", "不刪除", ""}:
        return False
    return default


def _to_bool_series(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index)
    return df[col].map(lambda v: _as_bool_value(v, default=default)).fillna(default).astype(bool)


def _selected_delete_usernames(df: pd.DataFrame, editor_key: str) -> list[str]:
    """Return selected usernames from data_editor + widget delta state.

    In some Streamlit builds, checkbox edits inside a form can be present in the
    widget state even when the returned dataframe is not yet fully refreshed.
    This fallback prevents the 'Delete' checkbox from looking checked but saving
    zero deletions.
    """
    selected: set[str] = set()
    if df is None or df.empty or "帳號 / Username" not in df.columns:
        return []

    mask = _to_bool_series(df, "刪除 / Delete")
    for _, row in df.loc[mask].iterrows():
        username = str(row.get("帳號 / Username", "")).strip()
        if username:
            selected.add(username)

    state = st.session_state.get(editor_key, {})
    if isinstance(state, dict):
        edited_rows = state.get("edited_rows", {}) or {}
        for row_idx, changes in edited_rows.items():
            if not isinstance(changes, dict) or "刪除 / Delete" not in changes:
                continue
            if not _as_bool_value(changes.get("刪除 / Delete"), default=False):
                continue
            try:
                idx = int(row_idx)
            except Exception:
                continue
            if 0 <= idx < len(df):
                username = str(df.iloc[idx].get("帳號 / Username", "")).strip()
                if username:
                    selected.add(username)
    return sorted(selected)


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


def _password_from_editor_row(r: pd.Series) -> str:
    """Return a new password only when the user really typed one.

    V1.76：使用者常誤以為「密碼狀態」不能輸入是錯誤。
    現在允許直接在該欄輸入新密碼；若仍為 ******** 或提示文字，代表維持原密碼。
    """
    explicit = str(r.get("新密碼 / New Password", "") or "").strip()
    if explicit:
        return explicit
    status_value = str(r.get("密碼狀態 / Password Status", "") or "").strip()
    blocked_values = {
        "", "none", "nan", "********", "*******", "******",
        "新帳號請輸入新密碼", "匯入後將更新密碼", "未提供密碼，維持原密碼",
        "已設定", "維持原密碼", "password set",
    }
    if status_value.lower() in blocked_values or set(status_value) == {"*"}:
        return ""
    return status_value


def _users_to_service_rows(df: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "username": str(r.get("帳號 / Username", "")).strip(),
            "new_password": _password_from_editor_row(r),
            "employee_id": str(r.get("工號 / Employee ID", "")).strip(),
            "display_name": str(r.get("姓名 / Display Name", "")).strip(),
            "email": str(r.get("Email", "")).strip(),
            "role_code": str(r.get("角色 / Role", "operator")).strip() or "operator",
            "is_active": bool(r.get("啟用 / Active", True)),
            "force_password_change": bool(r.get("強制改密碼 / Force Change", False)),
            "note": str(r.get("備註 / Note", "")).strip(),
        })
    return rows


def _norm_header(v) -> str:
    return str(v).strip().lower().replace("　", " ").replace("/", " ").replace("\\", " ").replace("-", " ").replace("_", " ")


def _parse_bool_value(v, default: bool = True) -> bool:
    if pd.isna(v):
        return default
    t = str(v).strip().lower()
    if t in ("", "nan", "none"):
        return default
    if t in ("1", "true", "yes", "y", "啟用", "是", "在職", "有效", "active", "勾選", "已啟用"):
        return True
    if t in ("0", "false", "no", "n", "停用", "否", "離職", "無效", "inactive", "取消", "未啟用"):
        return False
    return default


def _normalize_role(v) -> str:
    t = str(v).strip().lower()
    mapping = {
        "系統管理員": "admin", "管理員": "admin", "administrator": "admin", "admin": "admin",
        "製造主管": "manager", "主管": "manager", "manager": "manager",
        "現場幹部": "leader", "幹部": "leader", "leader": "leader", "line leader": "leader",
        "作業人員": "operator", "人員": "operator", "operator": "operator",
        "查詢者": "viewer", "viewer": "viewer", "檢視者": "viewer",
        "稽核": "auditor", "auditor": "auditor", "稽核人員": "auditor",
    }
    return mapping.get(t, t if t in ROLE_OPTIONS else "operator")


def _map_account_headers(headers: list) -> dict:
    mapped = {}
    normalized = [_norm_header(h) for h in headers]
    for internal, aliases in ACCOUNT_HEADER_ALIASES.items():
        alias_norms = {_norm_header(a) for a in aliases}
        for idx, h in enumerate(normalized):
            if h in alias_norms and internal not in mapped:
                mapped[internal] = headers[idx]
                break
    return mapped


def _normalize_account_import_df(df_raw: pd.DataFrame, has_header: bool = True) -> pd.DataFrame:
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=list(ACCOUNT_DISPLAY_COLUMNS.values()))
    df = df_raw.copy().dropna(how="all")
    if df.empty:
        return pd.DataFrame(columns=list(ACCOUNT_DISPLAY_COLUMNS.values()))
    if has_header:
        headers = [str(x).strip() for x in df.iloc[0].tolist()]
        data = df.iloc[1:].copy()
        data.columns = headers
        mapped = _map_account_headers(headers)
        out = pd.DataFrame()
        for internal in ACCOUNT_DISPLAY_COLUMNS:
            src = mapped.get(internal)
            out[ACCOUNT_DISPLAY_COLUMNS[internal]] = data[src] if src in data.columns else ""
    else:
        data = df.copy().reset_index(drop=True)
        out = pd.DataFrame()
        order = list(ACCOUNT_DISPLAY_COLUMNS.keys())
        for idx, internal in enumerate(order):
            out[ACCOUNT_DISPLAY_COLUMNS[internal]] = data.iloc[:, idx] if idx < data.shape[1] else ""
    out = out.dropna(how="all")
    if out.empty:
        return out
    out["帳號 / Username"] = out["帳號 / Username"].fillna("").astype(str).str.strip()
    out["密碼 / Password"] = out["密碼 / Password"].fillna("").astype(str).str.strip()
    out["工號 / Employee ID"] = out["工號 / Employee ID"].fillna("").astype(str).str.strip()
    out["姓名 / Display Name"] = out["姓名 / Display Name"].fillna("").astype(str).str.strip()
    out["Email"] = out["Email"].fillna("").astype(str).str.strip()
    out["角色 / Role"] = out["角色 / Role"].fillna("operator").apply(_normalize_role)
    out["啟用 / Active"] = out["啟用 / Active"].apply(lambda x: _parse_bool_value(x, True))
    out["強制改密碼 / Force Change"] = out["強制改密碼 / Force Change"].apply(lambda x: _parse_bool_value(x, False))
    out["備註 / Note"] = out["備註 / Note"].fillna("").astype(str).str.strip()
    out = out[out["帳號 / Username"] != ""].copy()
    return out.reset_index(drop=True)


def _account_import_to_editor_rows(import_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in import_df.iterrows():
        username = str(r.get("帳號 / Username", "")).strip()
        password = str(r.get("密碼 / Password", "")).strip()
        rows.append({
            "刪除 / Delete": False,
            "帳號 / Username": username,
            "密碼狀態 / Password Status": "匯入後將更新密碼" if password else "未提供密碼，維持原密碼",
            "新密碼 / New Password": password,
            "工號 / Employee ID": str(r.get("工號 / Employee ID", "")).strip(),
            "姓名 / Display Name": str(r.get("姓名 / Display Name", "")).strip() or username,
            "Email": str(r.get("Email", "")).strip(),
            "角色 / Role": _normalize_role(r.get("角色 / Role", "operator")),
            "啟用 / Active": bool(r.get("啟用 / Active", True)),
            "強制改密碼 / Force Change": bool(r.get("強制改密碼 / Force Change", False)),
            "備註 / Note": str(r.get("備註 / Note", "")).strip(),
            "最後登入 / Last Login": "",
            "更新時間 / Updated At": "",
        })
    return pd.DataFrame(rows)


def _merge_users_editor(base_df: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    if base_df is None or base_df.empty:
        return new_rows.copy()
    if new_rows is None or new_rows.empty:
        return base_df.copy()
    base = base_df.copy()
    for _, r in new_rows.iterrows():
        username = str(r.get("帳號 / Username", "")).strip()
        if not username:
            continue
        mask = base["帳號 / Username"].fillna("").astype(str).str.strip().str.lower() == username.lower()
        if mask.any():
            idx = base.index[mask][0]
            for c in new_rows.columns:
                val = r.get(c, "")
                if c == "新密碼 / New Password" and not str(val).strip():
                    continue
                base.at[idx, c] = val
        else:
            base = pd.concat([base, pd.DataFrame([r])], ignore_index=True)
    return base.reset_index(drop=True)


def _save_imported_accounts(import_df: pd.DataFrame) -> dict:
    editor_rows = _account_import_to_editor_rows(import_df)
    return save_users(_users_to_service_rows(editor_rows))


def _permission_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    calc = df.copy()
    for c in ACTION_COLS:
        calc[c] = calc[c].fillna(False).astype(bool).astype(int) if c in calc.columns else 0
    return calc.groupby("username", as_index=False).agg(
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



def _v37_clear_widget_state(prefix: str) -> None:
    # Clear stale data_editor/form widget state. Without this, a Select All button can
    # set values to True, then the old editor delta immediately writes them back to False.
    for k in list(st.session_state.keys()):
        if str(k).startswith(prefix):
            try:
                del st.session_state[k]
            except Exception:
                pass

def _v40_account_delete_true_count(df: pd.DataFrame) -> int:
    try:
        return int(_to_bool_series(df, "刪除 / Delete").sum())
    except Exception:
        return 0


def _v37_touch_account_editor() -> None:
    """Rotate account data_editor key after external button actions.

    Root cause fixed in V40:
    - External buttons changed st.session_state["v133_users_df"].
    - The old data_editor/form widget state then overwrote the changed draft.
    - Previous V37 helper accidentally called itself recursively.

    This helper clears stale widget state and increments editor revision before the
    next data_editor is created, so checkbox 0/1 changes become the source of
    truth for the next render.
    """
    _v37_clear_widget_state("v171_account_password_editor_")
    try:
        st.session_state["v235_account_editor_rev"] = int(st.session_state.get("v235_account_editor_rev", 0)) + 1
    except Exception:
        st.session_state["v235_account_editor_rev"] = 1
    st.session_state["v37_account_bulk_just_applied"] = True
    st.session_state["v40_account_last_action"] = "touch_editor"

# V27: stable account/permission callbacks.
# Important: Enable Edit must NOT reload old JSON/SQLite data over the current
# visible account table. It copies the currently displayed authoritative list
# into the editable draft and rotates the editor key so bulk checkbox buttons
# show the 0/1 changes immediately.
def _v25_account_set_edit(enabled: bool) -> None:
    st.session_state["v166_account_edit_enabled"] = bool(enabled)
    if enabled:
        # Do not reload old records over an existing visible draft.
        if "v133_users_df" not in st.session_state or not isinstance(st.session_state.get("v133_users_df"), pd.DataFrame):
            st.session_state["v133_users_df"] = _users_for_editor()
        st.session_state["v40_account_last_action"] = "enable_edit"
    else:
        # Stop edit intentionally discards unsaved draft and reloads saved authority.
        st.session_state["v133_users_df"] = _users_for_editor()
        st.session_state["v40_account_last_action"] = "disable_edit_reload_saved"
    _v37_touch_account_editor()


def _v25_account_add_blank() -> None:
    df = st.session_state.get("v133_users_df")
    if df is None or not isinstance(df, pd.DataFrame):
        df = _users_for_editor()
    st.session_state["v133_users_df"] = pd.concat([pd.DataFrame([_blank_user_row()]), df.copy()], ignore_index=True)
    st.session_state["v40_account_last_action"] = "add_blank"
    _v37_touch_account_editor()


def _v25_account_delete_flag(flag: bool) -> None:
    df = st.session_state.get("v133_users_df")
    if df is None or not isinstance(df, pd.DataFrame):
        df = _users_for_editor()
    df = df.copy(deep=True).reset_index(drop=True)
    if "刪除 / Delete" not in df.columns:
        df.insert(0, "刪除 / Delete", False)
    df["刪除 / Delete"] = bool(flag)
    st.session_state["v133_users_df"] = df
    st.session_state["v40_account_last_action"] = "select_delete_all" if flag else "clear_delete_all"
    st.session_state["v40_account_last_delete_true"] = _v40_account_delete_true_count(df)
    _v37_touch_account_editor()


def _v25_account_reload() -> None:
    st.session_state["v133_users_df"] = _users_for_editor()
    st.session_state["v40_account_last_action"] = "reload_saved"
    _v37_touch_account_editor()


def _v25_permission_quick(action: str) -> None:
    st.session_state["v25_permission_quick_action"] = str(action or "")
    st.session_state["v235_permission_editor_rev"] = int(st.session_state.get("v235_permission_editor_rev", 0)) + 1


tab_accounts, tab_perm, tab_sec = st.tabs([
    "帳號密碼總表 / Account Password Master",
    "帳號模組權限 / Account Module Permissions",
    "安全設定 / Security",
])

with tab_accounts:
    st.subheader("帳號密碼總表 / Account & Password Master")
    st.info("V1.76：密碼欄可直接輸入新密碼。若顯示 ******** 代表維持原密碼；系統不會顯示既有密碼明碼。也可使用『新密碼 / New Password』欄。")
    account_tab_edit, account_tab_excel, account_tab_paste = st.tabs([
        "帳號清單編輯 / Account Editor", "Excel 匯入 / Excel Import", "貼上資料 / Paste Data"
    ])

    # V1.69: Edit mode is shown BEFORE tab content so it is always visible.
    if "v166_account_edit_enabled" not in st.session_state:
        st.session_state["v166_account_edit_enabled"] = False
    _edit_on = bool(st.session_state.get("v166_account_edit_enabled", False))
    c_edit1, c_edit2, c_edit3 = st.columns([1.2, 1.2, 3])
    with c_edit1:
        st.button("◇ 啟動編輯 / Enable Edit", use_container_width=True, disabled=_edit_on, key="v25_enable_account_edit_top", on_click=_v25_account_set_edit, args=(True,))
    with c_edit2:
        st.button("◌ 停止編輯 / Lock Edit", use_container_width=True, disabled=not _edit_on, key="v25_disable_account_edit_top", on_click=_v25_account_set_edit, args=(False,))
    with c_edit3:
        if _edit_on:
            st.success("目前：已啟動編輯。修改後請按儲存才會正式寫入。")
        else:
            st.info("目前：唯讀保護。請先啟動編輯，再新增、修改、刪除、匯入或貼上帳號。")

    if "v133_users_df" not in st.session_state:
        st.session_state["v133_users_df"] = _users_for_editor()

    with account_tab_edit:
        st.markdown("### 新增帳號專用表單 / Stable Add User Form")
        st.caption("建議新增帳號先使用此表單；送出後會直接寫入資料庫，不會因表格 rerun 造成資料消失。")
        with st.form("v175_create_account_form", clear_on_submit=True):
            f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.2, 1.2])
            with f1:
                new_username = st.text_input("帳號 / Username", key="v175_new_username", disabled=not _edit_on)
                new_emp_id = st.text_input("工號 / Employee ID", key="v175_new_employee_id", disabled=not _edit_on)
            with f2:
                new_password = st.text_input("新密碼 / New Password", type="password", key="v175_new_password", disabled=not _edit_on)
                new_name = st.text_input("姓名 / Display Name", key="v175_new_display_name", disabled=not _edit_on)
            with f3:
                new_email = st.text_input("Email", key="v175_new_email", disabled=not _edit_on)
                new_role = st.selectbox("角色 / Role", ROLE_OPTIONS, index=ROLE_OPTIONS.index("operator"), key="v175_new_role", disabled=not _edit_on)
            with f4:
                new_active = st.checkbox("啟用 / Active", value=True, key="v175_new_active", disabled=not _edit_on)
                new_force_change = st.checkbox("強制改密碼 / Force Change", value=False, key="v175_new_force_change", disabled=not _edit_on)
            new_note = st.text_input("備註 / Note", key="v175_new_note", disabled=not _edit_on)
            submit_new_user = st.form_submit_button("⊕ 建立帳號 / Create User", type="primary", use_container_width=True, disabled=not _edit_on)

        if submit_new_user:
            username = str(new_username or "").strip()
            password = str(new_password or "").strip()
            display_name = str(new_name or "").strip() or username
            if not username:
                st.error("請輸入帳號 / Username is required")
            elif not password:
                st.error("新增帳號必須輸入新密碼 / New password is required for new account")
            else:
                result = save_users([{
                    "username": username,
                    "new_password": password,
                    "employee_id": str(new_emp_id or "").strip(),
                    "display_name": display_name,
                    "email": str(new_email or "").strip(),
                    "role_code": str(new_role or "operator").strip() or "operator",
                    "is_active": bool(new_active),
                    "force_password_change": bool(new_force_change),
                    "note": str(new_note or "").strip(),
                }])
                if result.get("saved", 0) > 0:
                    st.success(f"帳號已建立 / Account created：{username}")
                    st.session_state["v133_users_df"] = _users_for_editor()
                    try:
                        from services.column_settings_service import clear_editor_draft
                        clear_editor_draft("account")
                    except Exception:
                        pass
                    st.rerun()
                if result.get("skipped"):
                    st.warning("；".join(result.get("skipped", [])))


        st.markdown("### 帳號清單編輯 / Editable Account Master")

        # V1.74：啟動/停止編輯只保留頁面上方唯一一組，避免帳號總表區重複顯示。
        if "v166_account_edit_enabled" not in st.session_state:
            st.session_state["v166_account_edit_enabled"] = False
        account_edit_enabled = bool(st.session_state.get("v166_account_edit_enabled", False))
        st.session_state.setdefault("v235_account_editor_rev", 0)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.button("⊕ 新增帳號 / Add User", use_container_width=True, disabled=not account_edit_enabled, key="v25_account_add_user_row", on_click=_v25_account_add_blank)
        with c2:
            st.button("⊖ 刪除欄全選 / Select Delete", use_container_width=True, disabled=not account_edit_enabled, key="v25_account_select_delete", on_click=_v25_account_delete_flag, args=(True,))
        with c3:
            st.button("◌ 刪除欄取消 / Clear Delete", use_container_width=True, disabled=not account_edit_enabled, key="v25_account_clear_delete", on_click=_v25_account_delete_flag, args=(False,))
        with c4:
            st.button("⟳ 重新載入 / Reload", use_container_width=True, key="v25_account_reload", on_click=_v25_account_reload)

        st.warning("V1.76：密碼欄可直接輸入。既有帳號顯示 ******** 代表維持原密碼；新增帳號請輸入密碼後再按下方『套用並儲存』。")

        # V40 diagnostic panel: use this when buttons appear to revert immediately.
        with st.expander("V40 按鈕狀態診斷 / Button State Diagnostics", expanded=False):
            _diag_df = st.session_state.get("v133_users_df")
            _diag_rows = len(_diag_df) if isinstance(_diag_df, pd.DataFrame) else 0
            _diag_delete_true = _v40_account_delete_true_count(_diag_df) if isinstance(_diag_df, pd.DataFrame) else 0
            st.write({
                "page_file": __file__,
                "edit_enabled": bool(st.session_state.get("v166_account_edit_enabled", False)),
                "editor_rev": int(st.session_state.get("v235_account_editor_rev", 0)),
                "draft_rows": _diag_rows,
                "draft_delete_true_count": _diag_delete_true,
                "last_action": st.session_state.get("v40_account_last_action", ""),
                "last_delete_true_count": st.session_state.get("v40_account_last_delete_true", ""),
                "bulk_guard_active": bool(st.session_state.get("v37_account_bulk_just_applied", False)),
            })

        # V1.71：帳號總表使用 st.form 包住 data_editor。
        # 原因：Streamlit 一般 data_editor 每次切換儲存格、勾選、下拉或其他元件互動都可能 rerun，
        # 導致尚未儲存的編輯草稿被資料庫原始資料重建覆蓋。
        # 放入 form 後，編輯期間不 rerun，只有按下 form_submit_button 才送出整張表。
        with st.form("v171_account_master_edit_form", clear_on_submit=False):
            account_editor_key = f"v171_account_password_editor_{st.session_state.get('v235_account_editor_rev', 0)}"
            edited_users = st.data_editor(
                st.session_state["v133_users_df"], key=account_editor_key, use_container_width=True,
                num_rows="fixed", hide_index=True,
                disabled=not account_edit_enabled,
                height=360,
                column_order=[c for c in ["刪除 / Delete"] + list(st.session_state["v133_users_df"].columns) if c in list(st.session_state["v133_users_df"].columns)],
                column_config={
                    "刪除 / Delete": st.column_config.CheckboxColumn("刪除 / Delete"),
                    "帳號 / Username": st.column_config.TextColumn("帳號 / Username", required=True),
                    "密碼狀態 / Password Status": st.column_config.TextColumn("密碼 / Password（輸入修改）", help="可直接輸入新密碼；******** 或提示文字代表維持原密碼"),
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

            active_count = int(_to_bool_series(edited_users, "啟用 / Active").sum())
            delete_count = int(_to_bool_series(edited_users, "刪除 / Delete").sum())
            new_password_count = int(sum(1 for _, _row in edited_users.iterrows() if _password_from_editor_row(_row)))
            m1, m2, m3 = st.columns(3)
            m1.metric("啟用帳號 / Active", active_count)
            m2.metric("待刪除 / Pending Delete", delete_count)
            m3.metric("密碼異動 / Password Changes", new_password_count)
            submitted_accounts = st.form_submit_button(
                "▣ 套用並儲存帳號密碼總表 / Apply and Save Account Master",
                type="primary",
                use_container_width=True,
                disabled=not account_edit_enabled,
            )

        if account_edit_enabled and not st.session_state.pop("v37_account_bulk_just_applied", False):
            # Keep normal manual edits, but do not let a stale data_editor/form return value
            # undo a bulk button result in the same rerun.
            st.session_state["v133_users_df"] = edited_users.copy()

        if submitted_accounts:
            df = edited_users.copy()
            to_delete = _selected_delete_usernames(df, account_editor_key)
            if to_delete:
                save_df = df.loc[~df["帳號 / Username"].astype(str).str.strip().isin(to_delete)].copy()
            else:
                save_df = df.copy()
            result = save_users(_users_to_service_rows(save_df))
            deleted = delete_users(to_delete)
            if to_delete and deleted == 0:
                st.warning("已偵測到刪除勾選，但未刪除任何帳號；admin 系統帳號不可刪除，其他帳號請確認帳號欄位是否有效。")
            st.success(f"帳號已儲存：{result['saved']} 筆；刪除：{deleted} 筆 / Accounts saved and deleted")
            if result.get("skipped"):
                st.warning("；".join(result["skipped"]))
            st.session_state.pop("v133_users_df", None)
            st.session_state["v166_account_edit_enabled"] = False
            st.session_state["v40_account_last_action"] = "saved_accounts"
            st.rerun()

    with account_tab_excel:
        st.markdown("### Excel 匯入帳號密碼設定 / Import Account Password Settings")
        if not st.session_state.get("v166_account_edit_enabled", False):
            st.info("請先到『帳號清單編輯』按『啟動編輯』，再執行匯入或直接儲存。")
        st.caption("若第一列有標題，系統會依標題自動對應欄位。")
        st.code("帳號、密碼、工號、姓名、Email、角色、啟用、強制改密碼、備註", language="text")
        uploaded = st.file_uploader("上傳帳號設定 Excel / Upload Account Excel", type=["xlsx", "xls"], key="v136_account_excel_upload")
        excel_has_header = st.checkbox("Excel 第一列為標題列 / First row is header", value=True, key="v136_account_excel_header")
        if uploaded is not None:
            try:
                raw_excel = pd.read_excel(uploaded, header=None, dtype=str).fillna("")
                import_df = _normalize_account_import_df(raw_excel, has_header=excel_has_header)
                st.success(f"解析完成：{len(import_df)} 筆 / Parsed {len(import_df)} accounts")
                st.dataframe(import_df, use_container_width=True, hide_index=True)
                e1, e2 = st.columns(2)
                with e1:
                    if st.button("⊕ 加入帳號總表編輯 / Add to Account Editor", use_container_width=True, key="v136_excel_add_editor", disabled=not st.session_state.get("v166_account_edit_enabled", False)):
                        new_rows = _account_import_to_editor_rows(import_df)
                        st.session_state["v133_users_df"] = _merge_users_editor(st.session_state.get("v133_users_df", _users_for_editor()), new_rows)
                        st.success("已加入帳號總表編輯頁，請到『帳號清單編輯』確認後儲存。")
                with e2:
                    if st.button("▣ 直接儲存 Excel 帳號 / Save Imported Accounts", type="primary", use_container_width=True, key="v136_excel_save_direct", disabled=not st.session_state.get("v166_account_edit_enabled", False)):
                        result = _save_imported_accounts(import_df)
                        st.success(f"帳號已儲存：{result['saved']} 筆 / Accounts saved")
                        if result.get("skipped"):
                            st.warning("；".join(result["skipped"]))
                        st.session_state.pop("v133_users_df", None)
            except Exception as ex:
                st.error(f"Excel 匯入失敗 / Import failed：{ex}")

    with account_tab_paste:
        st.markdown("### 貼上帳號密碼設定 / Paste Account Password Settings")
        if not st.session_state.get("v166_account_edit_enabled", False):
            st.info("請先到『帳號清單編輯』按『啟動編輯』，再執行貼上或直接儲存。")
        st.caption("支援從 Excel 直接複製貼上，建議包含標題列。")
        st.code("帳號\t密碼\t工號\t姓名\tEmail\t角色\t啟用\t強制改密碼\t備註", language="text")
        paste_text = st.text_area("貼上 Excel 複製資料 / Paste copied Excel data", height=220, key="v136_account_paste_text")
        paste_has_header = st.checkbox("貼上資料第一列為標題列 / First row is header", value=True, key="v136_account_paste_header")
        if paste_text.strip():
            try:
                raw_paste = pd.read_csv(StringIO(paste_text), sep="\t", header=None, dtype=str, engine="python").fillna("")
                if raw_paste.shape[1] <= 1:
                    raw_paste = pd.read_csv(StringIO(paste_text), sep=r"\s{2,}|,", header=None, dtype=str, engine="python").fillna("")
                import_df = _normalize_account_import_df(raw_paste, has_header=paste_has_header)
                st.success(f"解析完成：{len(import_df)} 筆 / Parsed {len(import_df)} accounts")
                st.dataframe(import_df, use_container_width=True, hide_index=True)
                p1, p2 = st.columns(2)
                with p1:
                    if st.button("⊕ 加入帳號總表編輯 / Add to Account Editor", use_container_width=True, key="v136_paste_add_editor", disabled=not st.session_state.get("v166_account_edit_enabled", False)):
                        new_rows = _account_import_to_editor_rows(import_df)
                        st.session_state["v133_users_df"] = _merge_users_editor(st.session_state.get("v133_users_df", _users_for_editor()), new_rows)
                        st.success("已加入帳號總表編輯頁，請到『帳號清單編輯』確認後儲存。")
                with p2:
                    if st.button("▣ 直接儲存貼上帳號 / Save Pasted Accounts", type="primary", use_container_width=True, key="v136_paste_save_direct", disabled=not st.session_state.get("v166_account_edit_enabled", False)):
                        result = _save_imported_accounts(import_df)
                        st.success(f"帳號已儲存：{result['saved']} 筆 / Accounts saved")
                        if result.get("skipped"):
                            st.warning("；".join(result["skipped"]))
                        st.session_state.pop("v133_users_df", None)
            except Exception as ex:
                st.error(f"貼上資料解析失敗 / Paste parse failed：{ex}")

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
    st.session_state.setdefault("v235_permission_editor_rev", 0)
    if selected_user != "全部 / All":
        view_df = view_df[view_df["username"] == selected_user]
    if selected_module != "全部 / All":
        view_df = view_df[view_df["module_code"] == selected_module.split(" ", 1)[0]]
    if selected_role != "全部 / All":
        view_df = view_df[view_df["role_code"] == selected_role]
    st.markdown("#### 快速勾選 / Quick Toggle")
    b1, b2, b3, b4, b5 = st.columns(5)
    with b1:
        st.button("◈ 可進入全選 / Select View", use_container_width=True, key="v25_perm_select_view", on_click=_v25_permission_quick, args=("can_view:on",))
    with b2:
        st.button("◌ 可進入取消 / Clear View", use_container_width=True, key="v25_perm_clear_view", on_click=_v25_permission_quick, args=("can_view:off",))
    with b3:
        st.button("◈ 編輯全選 / Select Edit", use_container_width=True, key="v25_perm_select_edit", on_click=_v25_permission_quick, args=("can_edit:on",))
    with b4:
        st.button("⟰ 匯出全選 / Select Export", use_container_width=True, key="v25_perm_select_export", on_click=_v25_permission_quick, args=("can_export:on",))
    with b5:
        st.button("⛨ 管理全選 / Select Manage", use_container_width=True, key="v25_perm_select_manage", on_click=_v25_permission_quick, args=("can_manage:on",))
    _v25_perm_action = st.session_state.pop("v25_permission_quick_action", None)
    if _v25_perm_action and ":" in _v25_perm_action:
        _col, _mode = _v25_perm_action.split(":", 1)
        if _col in ACTION_COLS and _col in view_df.columns:
            view_df[_col] = (_mode == "on")

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
    st.info("V1.89：權限表已改成確認後才套用。勾選權限時不會每一下都觸發整頁運算。")
    with st.form("permission_editor_commit_form", clear_on_submit=False):
        edited_perm = st.data_editor(view_df[base_cols + ACTION_COLS], key=f"v189_permission_editor_{st.session_state.get('v235_permission_editor_rev', 0)}", use_container_width=True, hide_index=True, column_config=col_cfg)
        submitted_perm = st.form_submit_button("▣ 確認套用並儲存權限 / Apply and Save Permissions", type="primary", use_container_width=True)
    st.markdown("#### 權限摘要預覽 / Permission Summary Preview")
    st.dataframe(_permission_summary(edited_perm), use_container_width=True, hide_index=True)
    if submitted_perm:
        saved = save_account_permissions(edited_perm.to_dict("records"))
        st.success(f"權限已套用並儲存：{saved} 筆 / Permissions saved")
        st.rerun()

with tab_sec:
    st.subheader("安全設定 / Security Settings")
    settings = get_security_settings()
    idle = int(settings.get("idle_timeout_minutes", "15") or 15)
    with st.form("security_settings_commit_form", clear_on_submit=False):
        new_idle = st.number_input("閒置自動登出分鐘數 / Idle Auto Logout Minutes", min_value=1, max_value=240, value=idle, step=1)
        confirm_after_record = st.checkbox("工時完成後詢問是否繼續記錄 / Ask continue after time record", value=settings.get("ask_continue_after_record", "1") != "0")
        submitted_security = st.form_submit_button("⛨ 確認套用安全設定 / Apply Security Settings", type="primary", use_container_width=True)
    if submitted_security:
        save_security_settings({"idle_timeout_minutes": str(int(new_idle)), "ask_continue_after_record": "1" if confirm_after_record else "0"})
        try:
            from services.security_service import set_idle_timeout_minutes
            set_idle_timeout_minutes(int(new_idle))
        except Exception:
            pass
        st.success(f"安全設定已永久儲存：閒置自動登出 {int(new_idle)} 分鐘 / Security settings permanently saved")
        st.rerun()
