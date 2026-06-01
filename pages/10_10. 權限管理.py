# -*- coding: utf-8 -*-
from __future__ import annotations

from io import StringIO, BytesIO
from datetime import datetime
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
    restore_default_accounts_once_v57,
)
try:
    from services.permission_service import save_account_master as _v94_save_account_master
except Exception:
    _v94_save_account_master = None

apply_theme()
require_module_access("10_permissions", "can_manage")
render_header("10 | 權限管理", "帳號密碼總表、帳號匯入、帳號貼上、帳號級模組權限 / Account & Permission Management")
init_permission_tables()
try:
    # V57：補回原始六個預設帳號（只新增缺少帳號，不覆蓋已存在帳號資料）
    restore_default_accounts_once_v57()
except Exception:
    pass

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


# ===== V95 FAST RAW EDITOR HELPER =====
def _v95_raw_data_editor(data=None, *args, **kwargs):
    """Use Streamlit native data_editor for 10. 權限管理 heavy editors.

    The global column-settings wrapper renders an extra settings data_editor for every
    table. In this module it caused 2~3 minute reruns and duplicate-key failures.
    This helper bypasses that wrapper only for the two permission-management editors.
    """
    try:
        import services.column_settings_service as _css
        _orig = getattr(_css, "_ORIGINAL_DATA_EDITOR", None)
        if callable(_orig):
            return _orig(data, *args, **kwargs)
    except Exception:
        pass
    return st.data_editor(data, *args, **kwargs)
# ===== V95 FAST RAW EDITOR HELPER END =====

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

def _role_text(info, key: str, fallback_key: str = "", default: str = "") -> str:
    """V300 clean compatibility: role metadata may come from old/new schema."""
    if not isinstance(info, dict):
        return default
    value = info.get(key)
    if value not in (None, ""):
        return str(value)
    if fallback_key:
        value = info.get(fallback_key)
        if value not in (None, ""):
            return str(value)
    return default

with st.expander("⌖ 角色權限說明 / Role Permission Description", expanded=False):
    st.dataframe(pd.DataFrame([
        {
            "角色代碼 / Role Code": role_code,
            "中文角色 / Chinese Role": _role_text(info, "zh", "label", role_code),
            "英文角色 / English Role": _role_text(info, "en", "role_en", role_code),
            "建議用途 / Recommendation": _role_text(info, "desc", "description", ""),
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


def _v93_safe_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _v93_bool_text(value) -> str:
    return "是 / Yes" if _as_bool_value(value, default=False) else "否 / No"


def _v93_account_export_df() -> pd.DataFrame:
    raw = pd.DataFrame(get_users())
    if raw.empty:
        return pd.DataFrame(columns=[
            "帳號 / Username", "密碼狀態 / Password Status", "新密碼 / New Password",
            "工號 / Employee ID", "姓名 / Display Name", "Email", "角色 / Role",
            "啟用 / Active", "強制改密碼 / Force Change", "備註 / Note",
            "最後登入 / Last Login", "更新時間 / Updated At",
        ])
    out = pd.DataFrame()
    out["帳號 / Username"] = raw.get("username", "").map(_v93_safe_text)
    # 系統不輸出既有密碼明碼，也不輸出 password_hash；只輸出畫面使用的遮罩狀態。
    out["密碼狀態 / Password Status"] = raw.get("password_display", "********").map(_v93_safe_text) if "password_display" in raw else "********"
    out["新密碼 / New Password"] = ""
    out["工號 / Employee ID"] = raw.get("employee_id", "").map(_v93_safe_text) if "employee_id" in raw else ""
    out["姓名 / Display Name"] = raw.get("display_name", "").map(_v93_safe_text) if "display_name" in raw else ""
    out["Email"] = raw.get("email", "").map(_v93_safe_text) if "email" in raw else ""
    out["角色 / Role"] = raw.get("role_code", "").map(_v93_safe_text) if "role_code" in raw else ""
    out["啟用 / Active"] = raw.get("is_active", 1).map(_v93_bool_text) if "is_active" in raw else "是 / Yes"
    out["強制改密碼 / Force Change"] = raw.get("force_password_change", 0).map(_v93_bool_text) if "force_password_change" in raw else "否 / No"
    out["備註 / Note"] = raw.get("note", "").map(_v93_safe_text) if "note" in raw else ""
    out["最後登入 / Last Login"] = raw.get("last_login_at", "").map(_v93_safe_text) if "last_login_at" in raw else ""
    out["更新時間 / Updated At"] = raw.get("updated_at", "").map(_v93_safe_text) if "updated_at" in raw else ""
    return out


def _v93_permission_export_df() -> pd.DataFrame:
    raw = pd.DataFrame(get_account_permissions())
    base_cols = ["username", "display_name", "role_code", "module_code", "module_name_zh", "module_name_en"]
    if raw.empty:
        raw = pd.DataFrame(columns=base_cols + ACTION_COLS)
    out = pd.DataFrame()
    col_map = {
        "username": "帳號 / Username",
        "display_name": "姓名 / Name",
        "role_code": "角色 / Role",
        "module_code": "模組代碼 / Module Code",
        "module_name_zh": "模組中文 / Module Chinese",
        "module_name_en": "模組英文 / Module English",
    }
    for src, dst in col_map.items():
        out[dst] = raw[src].map(_v93_safe_text) if src in raw.columns else ""
    action_map = {key: f"{zh} / {en}" for key, zh, en in ACTIONS}
    for key in ACTION_COLS:
        dst = action_map.get(key, key)
        out[dst] = raw[key].map(_v93_bool_text) if key in raw.columns else "否 / No"
    return out


def _v93_security_export_df() -> pd.DataFrame:
    settings = get_security_settings() or {}
    labels = {
        "idle_timeout_minutes": "閒置自動登出分鐘數 / Idle Auto Logout Minutes",
        "ask_continue_after_record": "工時完成後詢問是否繼續記錄 / Ask Continue After Time Record",
    }
    rows = []
    for key in sorted(settings.keys()):
        value = settings.get(key, "")
        display_value = _v93_safe_text(value)
        if key == "ask_continue_after_record":
            display_value = "啟用 / Enabled" if str(value) != "0" else "停用 / Disabled"
        rows.append({
            "設定鍵 / Setting Key": key,
            "設定名稱 / Setting Name": labels.get(key, key),
            "設定值 / Setting Value": display_value,
        })
    if not rows:
        rows.append({"設定鍵 / Setting Key": "", "設定名稱 / Setting Name": "", "設定值 / Setting Value": ""})
    return pd.DataFrame(rows)


def _v93_write_dataframe_sheet(wb, sheet_name: str, df: pd.DataFrame, title: str):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet(sheet_name)
    ws.cell(row=1, column=1, value=title)
    ws.cell(row=2, column=1, value=f"匯出時間 / Export Time：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    ws.cell(row=3, column=1, value="說明 / Note：既有密碼不輸出明碼；密碼欄僅提供狀態或匯入更新用空欄。")
    header_row = 5
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    title_fill = PatternFill("solid", fgColor="17365D")
    ws.cell(row=1, column=1).fill = title_fill
    ws.cell(row=1, column=1).font = Font(color="FFFFFF", bold=True, size=14)
    for col_idx, col_name in enumerate(df.columns.tolist(), start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row_idx, row in enumerate(df.itertuples(index=False), start=header_row + 1):
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = ws.dimensions
    for col_idx, col_name in enumerate(df.columns.tolist(), start=1):
        values = [str(col_name)] + [str(v) for v in df.iloc[:, col_idx - 1].head(200).tolist()] if not df.empty else [str(col_name)]
        width = min(max(max(len(v) for v in values) + 2, 12), 42)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    return ws


def _build_permission_excel_export_v93() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    default_ws = wb.active
    wb.remove(default_ws)
    _v93_write_dataframe_sheet(
        wb,
        "帳號密碼總表",
        _v93_account_export_df(),
        "帳號密碼總表 / Account Password Master",
    )
    _v93_write_dataframe_sheet(
        wb,
        "帳號模組權限",
        _v93_permission_export_df(),
        "帳號模組權限 / Account Module Permissions",
    )
    _v93_write_dataframe_sheet(
        wb,
        "安全設定",
        _v93_security_export_df(),
        "安全設定 / Security",
    )
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


with st.expander("⟰ 權限管理 Excel 下載 / Permission Management Excel Export", expanded=False):
    st.caption("V95：Excel 檔改成按下產生後才建立，不再每次進入 10 頁或勾選 checkbox 都重新產生，避免拖慢頁面。")
    cex1, cex2 = st.columns([1, 1])
    with cex1:
        if st.button("▣ 產生權限管理 Excel / Build Permission Workbook", use_container_width=True, key="v95_build_permission_management_excel"):
            try:
                st.session_state["v95_permission_management_excel_bytes"] = _build_permission_excel_export_v93()
                st.session_state["v95_permission_management_excel_ts"] = datetime.now().strftime('%Y%m%d_%H%M%S')
                st.success("Excel 下載檔已產生 / Workbook generated")
            except Exception as ex:
                st.session_state.pop("v95_permission_management_excel_bytes", None)
                st.warning(f"Excel 下載檔建立失敗 / Export failed：{ex}")
    with cex2:
        excel_bytes = st.session_state.get("v95_permission_management_excel_bytes")
        if excel_bytes:
            st.download_button(
                "⬇ 下載權限管理 Excel / Download Permission Workbook",
                data=excel_bytes,
                file_name=f"SPT_permission_management_{st.session_state.get('v95_permission_management_excel_ts', datetime.now().strftime('%Y%m%d_%H%M%S'))}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="v95_permission_management_excel_download",
            )
        else:
            st.info("請先按左側產生 Excel。")


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
        if st.button("◇ 啟動編輯 / Enable Edit", use_container_width=True, disabled=_edit_on, key="v169_enable_account_edit_top"):
            st.session_state["v166_account_edit_enabled"] = True
            st.rerun()
    with c_edit2:
        if st.button("◌ 停止編輯 / Lock Edit", use_container_width=True, disabled=not _edit_on, key="v169_disable_account_edit_top"):
            # V101：停止編輯只切換唯讀保護，不重新載入權威檔。
            # 舊版在這裡呼叫 _users_for_editor()；若 GitHub/權威檔短暫讀到空表，
            # 會把目前畫面草稿覆蓋成空白，造成「啟動編輯 → 停止編輯 → 全部資料消失」。
            # 正式重新載入請使用「重新載入 / Reload」按鈕；未儲存的草稿仍留在 session_state。
            st.session_state["v166_account_edit_enabled"] = False
            st.rerun()
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

        def _v56_touch_account_editor() -> None:
            """V56：批次按鈕後換新 editor key，避免 st.data_editor 舊前端狀態蓋回 checkbox。"""
            try:
                for _k0 in list(st.session_state.keys()):
                    if str(_k0).startswith(("v171_account_password_editor_", "v56_account_password_editor_")):
                        st.session_state.pop(_k0, None)
            except Exception:
                pass
            try:
                from services.column_settings_service import clear_editor_draft
                clear_editor_draft("v171_account_password_editor")
                clear_editor_draft("v56_account_password_editor")
                clear_editor_draft("account")
            except Exception:
                pass
            st.session_state["v235_account_editor_rev"] = int(st.session_state.get("v235_account_editor_rev", 0)) + 1

        def _v56_prepare_account_draft() -> pd.DataFrame:
            """V56：統一 checkbox 欄位型別，確保 data_editor 以 bool checkbox 顯示。

            V97C：移除 session_state 內可能殘留的重複欄位，避免 data_editor
            顯示兩個「刪除 / Delete」欄，造成使用者誤判與勾選狀態錯亂。
            """
            df0 = st.session_state.get("v133_users_df")
            if not isinstance(df0, pd.DataFrame):
                df0 = _users_for_editor()
            df0 = df0.copy()
            try:
                df0 = df0.loc[:, ~pd.Index(df0.columns).duplicated()].copy()
            except Exception:
                pass
            for _col, _default in [
                ("刪除 / Delete", False),
                ("啟用 / Active", True),
                ("強制改密碼 / Force Change", False),
            ]:
                if _col not in df0.columns:
                    df0[_col] = _default
                df0[_col] = _to_bool_series(df0, _col).fillna(bool(_default)).astype(bool)
            st.session_state["v133_users_df"] = df0
            return df0

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            if st.button("⊕ 新增帳號 / Add User", use_container_width=True, disabled=not account_edit_enabled, key="v56_add_user_row_once"):
                base_df = _v56_prepare_account_draft()
                st.session_state["v133_users_df"] = pd.concat([base_df, pd.DataFrame([_blank_user_row()])], ignore_index=True)
                _v56_touch_account_editor()
                st.rerun()
        with c2:
            if st.button("☑ 刪除全選 / Select Delete", use_container_width=True, disabled=not account_edit_enabled, key="v56_account_select_delete"):
                df0 = _v56_prepare_account_draft()
                df0["刪除 / Delete"] = True
                st.session_state["v133_users_df"] = df0.copy()
                _v56_touch_account_editor()
                st.rerun()
        with c3:
            if st.button("☐ 刪除取消 / Clear Delete", use_container_width=True, disabled=not account_edit_enabled, key="v56_account_clear_delete"):
                df0 = _v56_prepare_account_draft()
                df0["刪除 / Delete"] = False
                st.session_state["v133_users_df"] = df0.copy()
                _v56_touch_account_editor()
                st.rerun()
        with c4:
            if st.button("☑ 啟用全選 / Active All", use_container_width=True, disabled=not account_edit_enabled, key="v56_account_active_all"):
                df0 = _v56_prepare_account_draft()
                df0["啟用 / Active"] = True
                st.session_state["v133_users_df"] = df0.copy()
                _v56_touch_account_editor()
                st.rerun()
        with c5:
            if st.button("☐ 啟用取消 / Inactive All", use_container_width=True, disabled=not account_edit_enabled, key="v56_account_inactive_all"):
                df0 = _v56_prepare_account_draft()
                df0["啟用 / Active"] = False
                st.session_state["v133_users_df"] = df0.copy()
                _v56_touch_account_editor()
                st.rerun()
        with c6:
            if st.button("⟳ 重新載入 / Reload", use_container_width=True, key="v56_account_reload"):
                st.session_state["v133_users_df"] = _users_for_editor()
                _v56_touch_account_editor()
                st.rerun()

        # V107：只新增「強制改密碼」批次按鈕；不調整原本六顆按鈕、不改表格欄位、不改儲存流程。
        fc1, fc2, fc_spacer = st.columns([1, 1, 4])
        with fc1:
            if st.button("☑ 強制改密碼全選 / Force Change All", use_container_width=True, disabled=not account_edit_enabled, key="v107_account_force_change_all"):
                df0 = _v56_prepare_account_draft()
                df0["強制改密碼 / Force Change"] = True
                st.session_state["v133_users_df"] = df0.copy()
                _v56_touch_account_editor()
                st.rerun()
        with fc2:
            if st.button("☐ 強制改密碼取消 / Clear Force Change", use_container_width=True, disabled=not account_edit_enabled, key="v107_account_force_change_clear"):
                df0 = _v56_prepare_account_draft()
                df0["強制改密碼 / Force Change"] = False
                st.session_state["v133_users_df"] = df0.copy()
                _v56_touch_account_editor()
                st.rerun()

        st.warning("V107：帳號總表為穩定送出模式。批次按鈕只更新畫面草稿；修改完成後請按表格下方『套用並儲存』才會正式寫入權威檔。")

        account_editor_key = f"v102_account_password_editor_{st.session_state.get('v235_account_editor_rev', 0)}"
        draft_df = _v56_prepare_account_draft()

        # V102：data_editor 放入 form，讓 checkbox / cell edits 留在前端草稿，
        # 不因每次點擊觸發整頁 rerun；送出時再一次讀回並寫權威檔。
        with st.form("v102_account_editor_commit_form", clear_on_submit=False):
            edited_users = _v95_raw_data_editor(
                draft_df,
                key=account_editor_key,
                use_container_width=True,
                num_rows="fixed",
                hide_index=True,
                disabled=not account_edit_enabled,
                height=360,
                # V97C：欄位順序保留「刪除」在第一欄，但不可重複加入同名欄位。
                column_order=list(dict.fromkeys(["刪除 / Delete"] + [c for c in draft_df.columns if c != "刪除 / Delete"])),
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

            submitted_accounts = st.form_submit_button(
                "▣ 套用並儲存帳號密碼總表 / Apply and Save Account Master",
                type="primary",
                use_container_width=True,
                disabled=not account_edit_enabled,
            )

        # 未送出時不把 data_editor 回傳值寫回 session_state，避免 widget 前端草稿
        # 在 rerun 時被舊資料蓋掉。統計顯示 session 草稿值，正式送出才更新。
        metric_df = st.session_state.get("v133_users_df", draft_df)
        if not isinstance(metric_df, pd.DataFrame):
            metric_df = draft_df
        active_count = int(_to_bool_series(metric_df, "啟用 / Active").sum())
        delete_count = int(_to_bool_series(metric_df, "刪除 / Delete").sum())
        new_password_count = int(sum(1 for _, _row in metric_df.iterrows() if _password_from_editor_row(_row)))
        m1, m2, m3 = st.columns(3)
        m1.metric("啟用帳號 / Active", active_count)
        m2.metric("待刪除 / Pending Delete", delete_count)
        m3.metric("密碼異動 / Password Changes", new_password_count)

        if submitted_accounts:
            df = edited_users.copy() if isinstance(edited_users, pd.DataFrame) else draft_df.copy()
            try:
                df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
            except Exception:
                pass
            for _col, _default in [
                ("刪除 / Delete", False),
                ("啟用 / Active", True),
                ("強制改密碼 / Force Change", False),
            ]:
                if _col not in df.columns:
                    df[_col] = _default
                df[_col] = _to_bool_series(df, _col).fillna(bool(_default)).astype(bool)
            # 送出瞬間同步 session 草稿，避免 checkbox delta 尚未併入 dataframe 時漏判。
            st.session_state["v133_users_df"] = df.copy()
            to_delete = _selected_delete_usernames(df, account_editor_key)
            if to_delete:
                save_df = df.loc[~df["帳號 / Username"].astype(str).str.strip().isin(to_delete)].copy()
            else:
                save_df = df.copy()
            service_rows = _users_to_service_rows(save_df)
            if callable(_v94_save_account_master):
                master_result = _v94_save_account_master(service_rows, delete_usernames=to_delete)
                result = {"saved": int(master_result.get("saved", 0)), "skipped": master_result.get("skipped", [])}
                deleted = int(master_result.get("deleted", 0))
            else:
                result = save_users(service_rows)
                deleted = delete_users(to_delete)
            if to_delete and deleted == 0:
                st.warning("已偵測到刪除勾選，但未刪除任何帳號；admin 系統帳號不可刪除，其他帳號請確認帳號欄位是否有效。")
            st.success(f"帳號已儲存：{result['saved']} 筆；刪除：{deleted} 筆 / Accounts saved and deleted")
            _v125_rec = master_result.get("permission_reconcile") if callable(_v94_save_account_master) and isinstance(master_result, dict) else result.get("permission_reconcile")
            if isinstance(_v125_rec, dict):
                st.info(
                    "權限矩陣已同步核對 / Permission matrix reconciled："
                    f"帳號 {_v125_rec.get('users', 0)}，權限列 {_v125_rec.get('permissions', 0)}，"
                    f"補齊 {_v125_rec.get('added', 0)}，修正 {_v125_rec.get('upgraded', 0)}。"
                )
            if result.get("skipped"):
                st.warning("；".join(result["skipped"]))
            st.session_state.pop("v133_users_df", None)
            st.session_state["v166_account_edit_enabled"] = False
            _v56_touch_account_editor()
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
        if st.button("◈ 可進入全選 / Select View", use_container_width=True):
            view_df["can_view"] = True
            st.session_state["v235_permission_editor_rev"] = int(st.session_state.get("v235_permission_editor_rev", 0)) + 1
    with b2:
        if st.button("◌ 可進入取消 / Clear View", use_container_width=True):
            view_df["can_view"] = False
            st.session_state["v235_permission_editor_rev"] = int(st.session_state.get("v235_permission_editor_rev", 0)) + 1
    with b3:
        if st.button("◈ 編輯全選 / Select Edit", use_container_width=True):
            view_df["can_edit"] = True
            st.session_state["v235_permission_editor_rev"] = int(st.session_state.get("v235_permission_editor_rev", 0)) + 1
    with b4:
        if st.button("⟰ 匯出全選 / Select Export", use_container_width=True):
            view_df["can_export"] = True
            st.session_state["v235_permission_editor_rev"] = int(st.session_state.get("v235_permission_editor_rev", 0)) + 1
    with b5:
        if st.button("⛨ 管理全選 / Select Manage", use_container_width=True):
            view_df["can_manage"] = True
            st.session_state["v235_permission_editor_rev"] = int(st.session_state.get("v235_permission_editor_rev", 0)) + 1
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
        edited_perm = _v95_raw_data_editor(view_df[base_cols + ACTION_COLS], key=f"v189_permission_editor_{st.session_state.get('v235_permission_editor_rev', 0)}", use_container_width=True, hide_index=True, column_config=col_cfg)
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