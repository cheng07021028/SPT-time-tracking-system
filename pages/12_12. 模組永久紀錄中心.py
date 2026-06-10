# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.module_persistence_service import (
    MODULE_TABLE_MAP,
    bootstrap_module_persistence,
    export_all_modules,
    export_module_records,
    get_module_status,
    clear_module_status_cache,
    protect_gitignore_rules,
    rebuild_global_index,
)
from services.security_service import require_module_access
from services.table_ui_service import render_table
from services.github_retention_service import audit_module_github_links, upload_all_module_persistent_files_to_github, clear_github_module_audit_cache

st.set_page_config(page_title="12. 模組永久紀錄中心", page_icon="⧠️", layout="wide")
apply_theme()
require_module_access("12_module_persistence", "can_view")
render_header("12｜模組永久紀錄中心", "各模組 records / settings / history 健康檢查，不重複做每日備份設定")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("12", "模組永久紀錄中心")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


username = st.session_state.get("auth_username", st.session_state.get("username", "SYSTEM"))

st.markdown("### 模組永久資料健康檢查 / Module Persistent Data Health")
st.info("V69：本頁不再於開啟時自動重建索引或掃描所有模組；請按下方按鈕後才載入狀態。每日備份排程請到 13｜系統設定；備份紀錄與 GitHub 備份狀態請到 09｜資料永久保存與備份。")

mc1, mc2, mc3 = st.columns([1, 1, 2])
if mc1.button("載入模組狀態 / Load Module Status", use_container_width=True, key="v69_12_load_module_status"):
    try:
        clear_module_status_cache()
        st.session_state["v69_12_status_df"] = pd.DataFrame(get_module_status(force_refresh=True))
        st.session_state["v30037_12_status_loaded_at"] = str(pd.Timestamp.now())
    except Exception as exc:
        st.session_state["v69_12_status_df"] = pd.DataFrame()
        st.warning(f"讀取模組狀態失敗：{exc}")
if mc2.button("重建索引 / Rebuild Index", use_container_width=True, key="v69_12_rebuild_index"):
    try:
        protect_gitignore_rules()
        clear_module_status_cache()
        rebuild_global_index()
        st.session_state["v69_12_status_df"] = pd.DataFrame(get_module_status(force_refresh=True))
        st.session_state["v30037_12_status_loaded_at"] = str(pd.Timestamp.now())
        st.success("已重建模組索引。")
    except Exception as exc:
        st.warning(f"模組永久索引重建時發生警告，但不影響查詢：{exc}")

status_df = st.session_state.get("v69_12_status_df")
if not isinstance(status_df, pd.DataFrame):
    status_df = pd.DataFrame()
if status_df.empty:
    st.warning("尚未載入模組永久紀錄狀態。請按『載入模組狀態』；若索引不存在再按『重建索引』。")
else:
    records_ok = int(status_df.get("紀錄檔 / Records Exists", pd.Series(dtype=bool)).fillna(False).sum())
    settings_ok = int(status_df.get("設定檔 / Settings Exists", pd.Series(dtype=bool)).fillna(False).sum())
    module_count = int(len(status_df))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("模組數", module_count)
    c2.metric("Records 存在", records_ok)
    c3.metric("Settings 存在", settings_ok)
    c4.metric("資料根目錄", "data/permanent_store/persistent_modules")

    if "模組代碼 / Module Code" in status_df.columns:
        codes = set(status_df["模組代碼 / Module Code"].astype(str).tolist())
        if "01_time_record" in codes:
            st.error("偵測到舊代碼 01_time_record。V3.06 已統一為 01_time_records，請覆蓋 services/module_persistence_service.py。")
        if "01_time_records" not in codes:
            st.warning("狀態表缺少 01_time_records，可能會讓 01 工時紀錄永久資料路徑不一致。")
        if "12_module_persistence" not in codes:
            st.error("狀態表缺少 12_module_persistence，請確認 module_persistence_service.py 是否為最新版。")

loaded_at = st.session_state.get("v30037_12_status_loaded_at")
if loaded_at and not status_df.empty:
    st.caption(f"狀態載入時間：{loaded_at}；同一輪狀態檢查已避免重複 COUNT 相同資料表。")

render_table(status_df, "12_module_persistence_status", editable=False, height=460)

with st.expander("GitHub 模組備份連結狀態 / GitHub Module Backup Links", expanded=False):
    st.caption("檢查每個模組的 data/permanent_store/persistent_modules records/settings 是否也同步到 GitHub。Reboot App 後若 SQLite 空白，這些檔案就是救援來源之一。")
    cga1, cga2 = st.columns(2)
    if cga1.button("檢查 GitHub 連結 / Audit GitHub Links", use_container_width=True, key="v326_12_audit_github_links"):
        clear_github_module_audit_cache()
        st.session_state["v326_12_module_github_audit"] = audit_module_github_links(check_remote=True)
    if cga2.button("上傳/修復缺少的 GitHub 模組檔 / Sync Missing Module Files", use_container_width=True, key="v326_12_sync_github_module_files"):
        st.session_state["v326_12_module_github_upload"] = upload_all_module_persistent_files_to_github()
    audit = st.session_state.get("v326_12_module_github_audit")
    if audit:
        summary = audit.get("summary", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("模組數", summary.get("modules", 0))
        c2.metric("Records 已連結", summary.get("records_linked", 0))
        c3.metric("Settings 已連結", summary.get("settings_linked", 0))
        st.dataframe(pd.DataFrame(audit.get("rows", [])), use_container_width=True, hide_index=True, height=320)
    if st.session_state.get("v326_12_module_github_upload"):
        st.json(st.session_state["v326_12_module_github_upload"])

with st.expander("進階手動維護 / Advanced Manual Maintenance", expanded=False):
    st.warning("這裡只做手動補齊、匯出與索引重建。每日自動備份排程請統一到 13｜系統設定，避免功能重複。")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("⧉ 建立 / 補齊永久資料夾 / Bootstrap", use_container_width=True):
            protect_gitignore_rules()
            result = bootstrap_module_persistence(username=username)
            clear_module_status_cache()
            st.session_state.pop("v69_12_status_df", None)
            st.success("已建立或補齊模組永久資料夾與設定索引")
            st.json(result)
            st.rerun()
    with c2:
        if st.button("⟰ 匯出全部模組紀錄 / Export All", use_container_width=True):
            result = export_all_modules(username=username)
            clear_module_status_cache()
            st.session_state.pop("v69_12_status_df", None)
            st.success("全部模組紀錄已匯出到 data/permanent_store/persistent_modules")
            st.json({k: v.get("counts", {}) for k, v in result.items()})
            st.rerun()
    with c3:
        if st.button("⟳ 重建全域索引 / Rebuild Index", use_container_width=True):
            clear_module_status_cache()
            result = rebuild_global_index()
            st.session_state.pop("v69_12_status_df", None)
            st.success("全域索引已重建")
            st.json(result)
            st.rerun()

    st.markdown("#### 單一模組匯出 / Export Single Module")
    module_options = {f'{v["name_zh"]} / {v["name_en"]} ({k})': k for k, v in MODULE_TABLE_MAP.items()}
    selected_label = st.selectbox("選擇模組 / Select Module", list(module_options.keys()))
    if st.button("⟰ 匯出選定模組 / Export Selected Module", use_container_width=True):
        module_code = module_options[selected_label]
        result = export_module_records(module_code, username=username)
        clear_module_status_cache()
        st.session_state.pop("v69_12_status_df", None)
        st.success("已匯出模組永久紀錄")
        st.json({"module_code": module_code, "counts": result.get("counts", {}), "exported_at": result.get("exported_at", ""), "warning": result.get("warning", "")})
        st.rerun()

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

