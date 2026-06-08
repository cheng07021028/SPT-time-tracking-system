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

from services.security_service import require_module_access, get_online_users

apply_theme()
require_module_access("11_login_logs", "can_view")

render_header("11｜登入紀錄", "登入、登出、閒置自動登出、權限不足與安全事件查詢")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("11", "登入紀錄")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


# V67：目前 session 的登入紀錄與 audit bootstrap 只需執行一次。
# 避免進入 11 頁或操作篩選時重複寫入/掃描 Neon。
if not st.session_state.get("_spt_v67_11_session_login_recorded", False):
    try:
        auto_record_session_login(
            username=st.session_state.get("auth_username", st.session_state.get("username", "")),
            display_name=st.session_state.get("auth_display_name", st.session_state.get("display_name", "")),
            roles=",".join(st.session_state.get("auth_roles", [])) if isinstance(st.session_state.get("auth_roles"), list) else str(st.session_state.get("auth_roles", "")),
            module_code="11_login_logs",
        )
    except Exception:
        pass
    st.session_state["_spt_v67_11_session_login_recorded"] = True

if not st.session_state.get("_spt_v67_11_bootstrap_ready", False):
    bootstrap_info = bootstrap_audit_log_service()
    st.session_state["_spt_v67_11_bootstrap_info"] = bootstrap_info
    st.session_state["_spt_v67_11_bootstrap_ready"] = True
else:
    bootstrap_info = st.session_state.get("_spt_v67_11_bootstrap_info", {})
try:
    removed_bad = int(bootstrap_info.get("removed_invalid_login_rows", 0) or 0)
    if removed_bad:
        st.info(f"已自動排除 {removed_bad} 筆非登入紀錄資料，登入紀錄只顯示帳號登入 / 登出 / 權限安全事件。")
except Exception:
    pass
with st.expander("⧠ 使用說明 / User Guide", expanded=False):
    st.markdown("""
- 本頁讀取兩種登入紀錄來源：新版 `login_logs` 與舊版 `security_login_logs`。
- 若更新版本後紀錄顯示 0，請先按「同步舊登入紀錄」。
- 登入紀錄可建立獨立永久檔，並可上傳到 GitHub，避免重開或更新後遺失。
- 清除紀錄前，建議先建立登入紀錄永久檔或上傳 GitHub。
""")

st.markdown("### 登入紀錄狀態 / Login Log Authority Status")
st.caption("V94：狀態改成按鈕載入一次並快取；不再每次 rerun 都全表 COUNT 或重讀在線人員，避免畫面一直運轉。")

_status_cols = st.columns([1, 1])
with _status_cols[0]:
    _load_status_clicked = st.button(
        "載入登入紀錄狀態與在線人員 / Load Status",
        use_container_width=True,
        key="v94_load_login_status_once",
    )
with _status_cols[1]:
    _clear_status_clicked = st.button(
        "清除狀態顯示 / Clear Status",
        use_container_width=True,
        key="v94_clear_login_status_cache",
    )

if _clear_status_clicked:
    for _k in ("v94_login_status_cached", "v94_login_status_loaded_at"):
        st.session_state.pop(_k, None)
    st.session_state["v34_login_status_loaded"] = False
    st.rerun()

if _load_status_clicked:
    with st.spinner("正在載入登入紀錄狀態，僅讀取輕量摘要..."):
        try:
            status = get_audit_permanent_status()
        except Exception as exc:
            status = {"exists": False, "count": 0, "db_count": 0, "authority_schema": "Unknown", "error": str(exc)}
        try:
            online_df = get_online_users()
        except Exception as exc:
            online_df = pd.DataFrame()
            status["online_error"] = str(exc)
        st.session_state["v94_login_status_cached"] = {"status": status, "online_df": online_df}
        st.session_state["v94_login_status_loaded_at"] = str(pd.Timestamp.now())
        st.session_state["v34_login_status_loaded"] = True

_cached_status_payload = st.session_state.get("v94_login_status_cached")
if _cached_status_payload:
    status = _cached_status_payload.get("status") or {}
    online_df = _cached_status_payload.get("online_df")
    if online_df is None:
        online_df = pd.DataFrame()
    c1, c2, c3 = st.columns(3)
    c1.metric("權威來源 / Authority", status.get("authority_schema", "Neon/PostgreSQL"))
    _count_label = "估算筆數 / Estimated Rows" if status.get("estimated") else "目前有效筆數 / Active Rows"
    c2.metric(_count_label, status.get("count", 0))
    c3.metric("快取/資料庫筆數 / DB Rows", status.get("db_count", 0))
    if status.get("estimated"):
        st.caption("此狀態為快速估算，不執行全表 COUNT；請用下方『套用查詢』讀取實際日期區間明細。")
    if status.get("error"):
        st.warning(f"狀態讀取警告：{status.get('error')}")
    if status.get("online_error"):
        st.warning(f"在線人員名單讀取警告：{status.get('online_error')}")
    st.caption(f"資料來源：{status.get('path', 'neon://auth_login_logs')}｜DeleteState：{status.get('delete_state_path', 'neon://deleted_at')}｜載入時間：{st.session_state.get('v94_login_status_loaded_at', '-')}")

    with st.expander("目前在線人員名單 / Current Online Users", expanded=False):
        if online_df is None or online_df.empty:
            st.info("目前沒有偵測到在線人員，或尚未產生 heartbeat。")
        else:
            oc1, oc2 = st.columns([1, 3])
            oc1.metric("在線人數 / Online", len(online_df))
            oc2.caption("同一帳號開多個瀏覽器分頁會以不同 Session 顯示。")
            st.dataframe(online_df, use_container_width=True, hide_index=True, height=min(360, 82 + len(online_df) * 36))
else:
    st.info("登入紀錄查詢區已可直接使用；狀態與在線清單請按上方按鈕載入。")

st.divider()
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
st.info("V39：日期、關鍵字、讀取筆數只會先暫存；按『套用查詢』後才查 Neon，避免每次選單/輸入變更就長時間運轉。")
_default_login_filters = {
    "start": today_date() - timedelta(days=30),
    "end": today_date(),
    "keyword": "",
    "limit": 300,
}
_applied_login_filters = st.session_state.get("v39_login_log_filters_applied", _default_login_filters.copy())
with st.form("v39_login_log_search_form", clear_on_submit=False):
    fc1, fc2, fc3, fc4 = st.columns([1, 1, 2, 1])
    with fc1:
        pending_start = st.date_input("開始日期 / Start Date", value=_applied_login_filters.get("start", _default_login_filters["start"]))
    with fc2:
        pending_end = st.date_input("結束日期 / End Date", value=_applied_login_filters.get("end", _default_login_filters["end"]))
    with fc3:
        pending_keyword = st.text_input("關鍵字 / Keyword", value=str(_applied_login_filters.get("keyword", "")), placeholder="帳號、姓名、事件、訊息...")
    with fc4:
        pending_limit = st.number_input("讀取筆數 / Limit", min_value=100, max_value=2000, value=int(_applied_login_filters.get("limit", 300)), step=100)
    q1, q2 = st.columns([1, 1])
    with q1:
        apply_query = st.form_submit_button("🔎 套用查詢 / Apply Search", type="primary", use_container_width=True)
    with q2:
        reset_query = st.form_submit_button("↺ 恢復預設 / Reset", use_container_width=True)
if reset_query:
    st.session_state["v39_login_log_filters_applied"] = _default_login_filters.copy()
    st.session_state.pop("_spt_v67_login_logs_cached", None)
    st.session_state.pop("_spt_v67_login_logs_signature", None)
    st.session_state["_spt_v67_login_logs_loaded"] = False
    st.rerun()
if apply_query:
    st.session_state["v39_login_log_filters_applied"] = {
        "start": pending_start,
        "end": pending_end,
        "keyword": pending_keyword,
        "limit": int(pending_limit),
    }
    st.session_state["_spt_v67_login_logs_force_query"] = True
    st.rerun()
_applied_login_filters = st.session_state.get("v39_login_log_filters_applied", _default_login_filters.copy())
start = _applied_login_filters.get("start", _default_login_filters["start"])
end = _applied_login_filters.get("end", _default_login_filters["end"])
keyword = str(_applied_login_filters.get("keyword", ""))
limit = int(_applied_login_filters.get("limit", 300))

_login_query_signature = (str(start), str(end), keyword, int(limit))
_login_force = bool(st.session_state.pop("_spt_v67_login_logs_force_query", False))
_login_loaded = bool(st.session_state.get("_spt_v67_login_logs_loaded", False))
if _login_force or (_login_loaded and st.session_state.get("_spt_v67_login_logs_signature") != _login_query_signature):
    stats = get_login_log_stats(str(start), str(end), keyword)  # SQL COUNT only after Apply.
    logs = load_login_logs(start_date=str(start), end_date=str(end), keyword=keyword, limit=limit, include_legacy=True)
    if isinstance(logs, list):
        logs = pd.DataFrame(logs)
    st.session_state["_spt_v67_login_logs_cached"] = {"stats": stats, "logs": logs}
    st.session_state["_spt_v67_login_logs_signature"] = _login_query_signature
    st.session_state["_spt_v67_login_logs_loaded"] = True
elif _login_loaded:
    _login_cached = st.session_state.get("_spt_v67_login_logs_cached") or {}
    stats = _login_cached.get("stats", {})
    logs = _login_cached.get("logs", pd.DataFrame())
else:
    stats = {"records": 0, "success": 0, "failed": 0}
    logs = pd.DataFrame()
    st.info("請按『套用查詢』後再讀取登入紀錄，避免進入 11 頁就掃描 Neon。")

s1, s2, s3 = st.columns(3)
s1.metric("筆數 / Records", stats.get("records", 0))
s2.metric("成功 / Success", stats.get("success", 0))
s3.metric("失敗 / Failed", stats.get("failed", 0))

if logs.empty:
    st.info("查無登入紀錄 / No login logs")
else:
    # V74：登入紀錄頁只顯示登入 / 登出 / 權限安全事件欄位。
    # 避免把其他模組資料表欄位誤顯示成帳號、事件、訊息。
    raw_cols = [
        "id", "username", "display_name", "event_type", "result",
        "login_time", "logout_time", "idle_minutes", "module_code",
        "message", "source", "ip_address", "user_agent", "created_at",
    ]
    logs = logs.loc[:, ~pd.Index(logs.columns).duplicated()].copy()
    for c in raw_cols:
        if c not in logs.columns:
            logs[c] = ""
    show = logs[raw_cols].copy()
    show.insert(0, "序號 / No.", range(1, len(show) + 1))
    rename = {
        "id": "資料ID / Data ID",
        "username": "帳號 / Username",
        "display_name": "姓名 / Name",
        "event_type": "事件 / Event",
        "result": "結果 / Result",
        "login_time": "登入時間 / Login Time",
        "logout_time": "登出時間 / Logout Time",
        "idle_minutes": "閒置分鐘 / Idle Minutes",
        "module_code": "模組 / Module",
        "message": "訊息 / Message",
        "source": "來源 / Source",
        "ip_address": "IP / IP",
        "user_agent": "裝置 / User Agent",
        "created_at": "建立時間 / Created At",
    }
    show = show.rename(columns=rename)
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
st.warning("V95：清除會以 Neon deleted_at 軟刪除登入紀錄，並另外寫入 system_logs / operation_logs 永久刪除稽核紀錄；Reboot 後不會復活，也能追查誰在何時清除哪個日期區間。")

# V1.99：改成點選確認，不再要求輸入 DELETE。
# 深色主題下文字輸入框容易看不清楚，也不符合使用者要求的「點選確認」。
# V11: reset checkbox before widget creation. Streamlit does not allow
# assigning to the same checkbox key after the widget has been instantiated.
if st.session_state.pop("v11_reset_confirm_delete_login_logs", False):
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
        _login_clear_operator = str(st.session_state.get("auth_username") or st.session_state.get("username") or "admin")
        count = delete_login_logs_by_date_range(str(start), str(end), operator=_login_clear_operator)
        st.session_state.pop("_spt_v67_login_logs_cached", None)
        st.session_state.pop("_spt_v67_login_logs_signature", None)
        st.session_state["_spt_v67_login_logs_loaded"] = False
        status_after = get_audit_permanent_status()
        st.success(f"已清除 {count} 筆登入紀錄，權威檔目前 {status_after.get('count', 0)} 筆 / Deleted {count} logs; authority now has {status_after.get('count', 0)} rows")
        st.caption(f"權威資料已更新：{status_after.get('path', '-')}｜DeleteState：{status_after.get('delete_state_path', '-')}｜本次刪除稽核已寫入 system_logs / operation_logs。")
        st.session_state["v11_reset_confirm_delete_login_logs"] = True
        st.rerun()

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

