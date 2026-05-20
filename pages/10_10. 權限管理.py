# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from services.auth_service import require_module, load_users, save_users, load_permissions, save_permissions, load_security_settings, save_security_settings, current_user
from services.app_config import MODULES, ACTIONS, ROLE_OPTIONS
from services.ui import apply_theme, page_header, configurable_editor, df_to_rows
from services.permanent_store import log_event

MODULE = "10_permissions"
apply_theme(); require_module(MODULE, "manage")
page_header(MODULE)

st.warning("權限管理允許重新整理與刪除；但儲存後只寫入 data/permanent_store/system，不會再回復舊版預設。")

st.subheader("帳號清單編輯 / Editable Account Master")
users = []
for u in load_users():
    r = {k:v for k,v in u.items() if k != "password_hash"}
    r.setdefault("密碼", "********")
    users.append(r)
udf = pd.DataFrame(users)
for c in ["帳號", "密碼", "姓名", "角色", "啟用", "備註"]:
    if c not in udf.columns: udf[c] = ""
edited = configurable_editor(MODULE, "users", udf[["帳號", "密碼", "姓名", "角色", "啟用", "備註"]], allow_edit=True, allow_delete=True)
if st.button("套用並永久儲存帳號", type="primary"):
    save_users(df_to_rows(edited))
    log_event(MODULE, "save_users", current_user(), "OK", f"{len(edited)} users")
    st.success("帳號清單已永久保存。")
    st.rerun()

st.divider()
st.subheader("角色權限設定")
perms = load_permissions()
role = st.selectbox("選擇角色", ROLE_OPTIONS, index=0)
role_perm = perms.get(role, {}) if isinstance(perms, dict) else {}
rows = []
for m in MODULES:
    mp = role_perm.get(m.key, {}) if isinstance(role_perm, dict) else {}
    row = {"模組代碼": m.key, "模組名稱": f"{m.no} {m.title}"}
    for a in ACTIONS:
        row[a] = bool(mp.get(a, role == "admin"))
    rows.append(row)
pdf = pd.DataFrame(rows)
ped = st.data_editor(pdf, use_container_width=True, hide_index=True, num_rows="fixed")
if st.button("套用並永久儲存角色權限"):
    perms.setdefault(role, {})
    for r in ped.to_dict("records"):
        perms[role][r["模組代碼"]] = {a: bool(r.get(a)) for a in ACTIONS}
    save_permissions(perms)
    log_event(MODULE, "save_permissions", current_user(), "OK", role)
    st.success("角色權限已永久保存。")

st.divider()
st.subheader("安全設定")
sec = load_security_settings()
idle = st.number_input("閒置自動登出分鐘數", min_value=1, max_value=1440, value=int(sec.get("idle_timeout_minutes", 60)))
login_required = st.checkbox("啟用登入", value=bool(sec.get("login_required", True)))
if st.button("套用並永久儲存安全設定"):
    save_security_settings({"idle_timeout_minutes": int(idle), "login_required": bool(login_required)})
    log_event(MODULE, "save_security", current_user(), "OK", str(idle))
    st.success("安全設定已永久保存。")
