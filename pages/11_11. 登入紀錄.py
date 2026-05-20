# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta
import pandas as pd
from services.timezone_service import today_date
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.audit_log_service import (
    bootstrap_audit_log_service,
    migrate_security_login_logs_to_login_logs,
    load_login_logs,
    get_login_log_stats,
    delete_login_logs_by_date_range,
    export_audit_logs_to_permanent_file,
    restore_audit_logs_from_permanent_file,
    upload_audit_logs_to_github,
    get_audit_permanent_status,
    auto_record_session_login,
)

from services.security_service import require_module_access

apply_theme()
require_module_access("11_login_logs", "can_view")

render_header("11｜登入紀錄", "登入、登出、閒置自動登出、權限不足與安全事件查詢")

# Make sure the current logged-in session is represented at least once.
try:
    auto_record_session_login(
        username=st.session_state.get("auth_username", st.session_state.get("username", "")),
        display_name=st.session_state.get("auth_display_name", st.session_state.get("display_name", "")),
        roles=",".join(st.session_state.get("auth_roles", [])) if isinstance(st.session_state.get("auth_roles"), list) else str(st.session_state.get("auth_roles", "")),
        module_code="11_login_logs",
    )
except Exception:
    pass

bootstrap_audit_log_service()
with st.expander("⧠ 使用說明 / User Guide", expanded=False):
    st.markdown("""
- 本頁讀取兩種登入紀錄來源：新版 `login_logs` 與舊版 `security_login_logs`。
- 若更新版本後紀錄顯示 0，請先按「同步舊登入紀錄」。
- 登入紀錄可建立獨立永久檔，並可上傳到 GitHub，避免重開或更新後遺失。
- 清除紀錄前，建議先建立登入紀錄永久檔或上傳 GitHub。
""")

st.markdown("### 登入紀錄永久保存狀態 / Audit Log Permanent Status")
status = get_audit_permanent_status()
c1, c2, c3 = st.columns(3)
c1.metric("永久檔 / Permanent File", "Exists" if status.get("exists") else "Not Found")
c2.metric("匯出時間 / Exported At", status.get("exported_at") or "-")
c3.metric("永久檔筆數 / Saved Logs", status.get("count", 0))

b1, b2, b3, b4 = st.columns(4)
with b1:
    if st.button("⟳ 同步舊登入紀錄 / Sync Legacy Logs", use_container_width=True):
        n = migrate_security_login_logs_to_login_logs()
        st.success(f"已同步 {n} 筆舊登入紀錄 / Synced {n} legacy logs")
        st.rerun()
with b2:
    if st.button("⧉ 建立登入紀錄永久檔 / Create Audit Permanent File", use_container_width=True):
        res = export_audit_logs_to_permanent_file(create_history=True)
        st.success(res.get("message", "完成"))
        st.json(res)
with b3:
    if st.button("⟲ 從永久檔還原登入紀錄 / Restore Audit Logs", use_container_width=True):
        res = restore_audit_logs_from_permanent_file()
        if res.get("ok"):
            st.success(res.get("message"))
            st.rerun()
        else:
            st.error(res.get("message"))
with b4:
    if st.button("⟰ 上傳登入紀錄到 GitHub / Upload Audit Logs", use_container_width=True):
        res = upload_audit_logs_to_github()
        if res.get("ok"):
            st.success(res.get("message"))
        else:
            st.error(res.get("message"))
        st.json(res)

st.divider()
st.markdown("### 登入紀錄查詢 / Login Log Search")
fc1, fc2, fc3 = st.columns([1, 1, 2])
with fc1:
    start = st.date_input("開始日期 / Start Date", value=today_date() - timedelta(days=30))
with fc2:
    end = st.date_input("結束日期 / End Date", value=today_date())
with fc3:
    keyword = st.text_input("關鍵字 / Keyword", value="", placeholder="帳號、姓名、事件、訊息...")

limit = st.slider("讀取筆數 / Limit", min_value=100, max_value=10000, value=1000, step=100)

stats = get_login_log_stats(str(start), str(end), keyword)
s1, s2, s3 = st.columns(3)
s1.metric("筆數 / Records", stats.get("records", 0))
s2.metric("成功 / Success", stats.get("success", 0))
s3.metric("失敗 / Failed", stats.get("failed", 0))

logs = load_login_logs(start_date=str(start), end_date=str(end), keyword=keyword, limit=limit, include_legacy=True)
if isinstance(logs, list):
    logs = pd.DataFrame(logs)

if logs.empty:
    st.info("查無登入紀錄 / No login logs")
else:
    rename = {
        "id": "ID / ID",
        "source": "來源 / Source",
        "username": "帳號 / Username",
        "display_name": "姓名 / Name",
        "event_type": "事件 / Event",
        "result": "結果 / Result",
        "message": "訊息 / Message",
        "module_code": "模組代碼 / Module Code",
        "login_time": "登入時間 / Login Time",
        "logout_time": "登出時間 / Logout Time",
        "idle_minutes": "閒置分鐘 / Idle Minutes",
        "ip_address": "IP / IP",
        "user_agent": "裝置 / User Agent",
        "created_at": "建立時間 / Created At",
    }
    show = logs.rename(columns=rename)
    st.dataframe(show, use_container_width=True, hide_index=True, height=420)
    st.download_button(
        "⬇️ 匯出登入紀錄 CSV / Export CSV",
        data=show.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"login_logs_{start}_{end}.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()
st.markdown("### 清除登入紀錄 / Clear Login Logs")
st.warning("刪除前建議先建立登入紀錄永久檔或上傳 GitHub，避免稽核紀錄遺失。")

# V1.99：改成點選確認，不再要求輸入 DELETE。
# 深色主題下文字輸入框容易看不清楚，也不符合使用者要求的「點選確認」。
# V8：Streamlit 1.4x 後不允許在同一次 rerun 中，於 widget 建立後直接修改同 key 的 session_state。
# 因此刪除成功時先寫入 reset flag，下一次 rerun 在 checkbox 建立前再重設勾選狀態。
if st.session_state.pop("_v8_reset_confirm_delete_login_logs", False):
    st.session_state["v199_confirm_delete_login_logs"] = False

confirm_delete_logs = st.checkbox(
    "我確認要清除目前日期區間內的登入紀錄 / Confirm delete login logs in selected date range",
    value=False,
    key="v199_confirm_delete_login_logs",
)
if st.button("⊖ 確認清除日期區間內登入紀錄 / Delete Logs in Date Range", type="secondary", use_container_width=True):
    if not confirm_delete_logs:
        st.error("請先勾選確認刪除，系統不會使用文字輸入 DELETE。")
    else:
        count = delete_login_logs_by_date_range(str(start), str(end))
        st.success(f"已清除 {count} 筆登入紀錄 / Deleted {count} logs")
        st.session_state["_v8_reset_confirm_delete_login_logs"] = True
        st.rerun()
