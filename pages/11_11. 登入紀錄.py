# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta
import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.permission_service import delete_login_logs, get_login_logs, init_permission_tables
from services.persistence_service import audit_state_status, export_audit_state, restore_audit_state

try:
    from services.github_cloud_storage_service import upload_audit_logs_to_github, download_latest_permanent_files_from_github
except Exception:  # local/offline fallback
    upload_audit_logs_to_github = None
    download_latest_permanent_files_from_github = None

apply_theme()
render_header("11 | 登入紀錄", "登入、登出、閒置自動登出、權限不足與安全事件查詢 / Login Audit Logs")
init_permission_tables()

st.caption("V1.37 loaded｜登入紀錄已支援永久 JSON 保存與 GitHub 雲端上傳。")

with st.expander("📘 使用說明 / User Guide", expanded=False):
    st.markdown("""
- 本頁用來查詢登入成功、登入失敗、登出、閒置自動登出、權限不足等紀錄。
- 登入紀錄會先寫入 SQLite，再同步刷新本機永久檔：`data/persistent_state/spt_audit_log_state.json`。
- 若要避免 Streamlit Cloud 重開或更新後紀錄消失，請定期按「上傳登入紀錄到 GitHub 雲端」。
- 清除登入紀錄前，建議先建立永久檔或上傳 GitHub 雲端。
""")

st.subheader("登入紀錄永久保存狀態 / Audit Log Permanent Status")
status = audit_state_status()
s1, s2, s3 = st.columns(3)
s1.metric("永久檔 / Permanent File", "Exists" if status.get("exists") else "Not Found")
s2.metric("匯出時間 / Exported At", status.get("exported_at") or "-")
s3.metric("登入紀錄筆數 / Login Logs", int(status.get("table_counts", {}).get("auth_login_logs", 0) or 0))

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("建立登入紀錄永久檔 / Create Audit Permanent File", use_container_width=True):
        res = export_audit_state(force=True)
        st.success("已建立登入紀錄永久檔。")
        st.json(res)
with b2:
    if st.button("上傳登入紀錄到 GitHub 雲端 / Upload Audit Logs", use_container_width=True):
        export_audit_state(force=True)
        if upload_audit_logs_to_github is None:
            st.error("GitHub API 服務不可用。")
        else:
            res = upload_audit_logs_to_github(archive=True)
            if res.get("ok"):
                st.success("登入紀錄已上傳 GitHub 雲端。")
            else:
                st.error("登入紀錄上傳失敗。")
            st.json(res)
with b3:
    if st.button("從永久檔還原登入紀錄 / Restore Audit Logs", use_container_width=True):
        if download_latest_permanent_files_from_github is not None:
            download_latest_permanent_files_from_github(allow_legacy=True)
        res = restore_audit_state(mode="append")
        if res.get("ok"):
            st.success("已嘗試還原登入紀錄。")
        else:
            st.warning(res.get("message", "還原失敗"))
        st.json(res)

st.divider()

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    start = st.date_input("開始日期 / Start Date", value=date.today() - timedelta(days=30))
with c2:
    end = st.date_input("結束日期 / End Date", value=date.today())
with c3:
    keyword = st.text_input("關鍵字 / Keyword", value="", placeholder="帳號、姓名、模組、訊息...")

logs = pd.DataFrame(get_login_logs(str(start), str(end)))
if not logs.empty and keyword.strip():
    kw = keyword.strip().lower()
    mask = logs.astype(str).apply(lambda col: col.str.lower().str.contains(kw, na=False)).any(axis=1)
    logs = logs[mask]

m1, m2, m3 = st.columns(3)
m1.metric("筆數 / Records", len(logs))
if not logs.empty:
    m2.metric("成功 / Success", int((logs.get("result", "") == "SUCCESS").sum()))
    m3.metric("失敗 / Failed", int((logs.get("result", "") == "FAILED").sum()))
else:
    m2.metric("成功 / Success", 0)
    m3.metric("失敗 / Failed", 0)

if logs.empty:
    st.info("查無登入紀錄 / No login logs")
else:
    rename = {
        "id": "ID / ID",
        "username": "帳號 / Username",
        "display_name": "姓名 / Name",
        "event_time": "時間 / Event Time",
        "event_type": "事件 / Event Type",
        "result": "結果 / Result",
        "module_code": "模組代碼 / Module Code",
        "module_name": "模組 / Module",
        "message": "訊息 / Message",
        "ip_address": "IP / IP",
        "user_agent": "裝置 / User Agent",
    }
    show = logs.rename(columns=rename)
    st.dataframe(show, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ 匯出登入紀錄 CSV / Export CSV",
        data=show.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"login_logs_{start}_{end}.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()
st.subheader("清除登入紀錄 / Clear Login Logs")
st.warning("刪除前建議先按『建立登入紀錄永久檔』或『上傳登入紀錄到 GitHub 雲端』，避免稽核紀錄遺失。")
confirm = st.text_input("若要清除，請輸入 DELETE / Type DELETE to confirm", value="")
if st.button("🗑️ 清除日期區間內登入紀錄 / Delete Logs in Date Range", type="secondary", use_container_width=True):
    if confirm.strip().upper() != "DELETE":
        st.error("未輸入 DELETE，已取消。")
    else:
        export_audit_state(force=True)
        count = delete_login_logs(str(start), str(end))
        export_audit_state(force=True)
        st.success(f"已清除 {count} 筆登入紀錄 / Deleted {count} logs")
        st.rerun()
