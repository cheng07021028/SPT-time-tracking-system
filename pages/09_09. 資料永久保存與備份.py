# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.db_service import DB_PATH, clear_pending_backup_marker, database_business_row_count, ensure_data_guard_restore, pending_backup_status
from services.github_cloud_storage_service import (
    LATEST_SETTINGS,
    LATEST_STATE,
    REMOTE_STATE_ROOT,
    STATE_DIR,
    create_and_upload_permanent_files,
    create_permanent_files,
    download_latest_permanent_files_from_github,
    github_cloud_file_status,
    github_config,
    migrate_legacy_date_path_to_data_path,
    restore_from_github_if_database_empty,
    upload_existing_permanent_files,
)

# V1.45: keep page 09 header style consistent with other modules.
# Use the common two-argument render_header format to avoid showing only the module number.

apply_theme()
require_module_access("09_persistence", "can_view")
render_header("09｜資料永久保存與備份", "GitHub 雲端永久保存｜啟動自動還原｜防止空資料覆蓋")

st.subheader("資料防消失中心 / Data Guard Center")
st.info(
    "V1.30 已加入啟動自動還原：Streamlit Cloud 更新模組或重新部署後，如果 SQLite 不存在或主資料為 0，"
    "系統會先從 GitHub 的 data/persistent_state/spt_permanent_state.json 下載並還原。"
)

cfg = github_config()
with st.expander("GitHub 雲端設定檢查 / Cloud Settings", expanded=True):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Repository", cfg.get("repo") or "未設定")
    c2.metric("Branch", cfg.get("branch") or "main")
    c3.metric("Token", "已設定" if cfg.get("token") else "未設定")
    c4.metric("正確路徑", REMOTE_STATE_ROOT)
    if not cfg.get("token"):
        st.warning(
            "請到 Streamlit Cloud → App settings → Secrets 加入：\n\n"
            'GITHUB_TOKEN = "你的 GitHub Token"\n'
            'GITHUB_REPOSITORY = "cheng07021028/SPT-time-tracking-system"\n'
            'GITHUB_BRANCH = "main"'
        )

st.divider()

st.subheader("待備份狀態 / Pending Backup Status")
pending = pending_backup_status()
if pending.get("pending"):
    st.warning(
        f"資料已有變更尚未備份：{pending.get('reason', '')}\n\n"
        f"第一次變更：{pending.get('first_pending_at', '')}｜最後變更：{pending.get('updated_at', '')}｜變更次數：{pending.get('change_count', '')}"
    )
else:
    st.success(pending.get("message", "目前沒有待備份變更。"))

st.divider()

st.subheader("一鍵操作 / Actions")
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("建立本機永久檔", use_container_width=True):
        res = create_permanent_files()
        if res.get("ok"):
            clear_pending_backup_marker()
            st.success("永久檔案已建立，待備份標記已清除。")
        else:
            st.warning(res.get("message", "建立失敗或被安全機制阻擋。"))
        st.json(res)
with c2:
    if st.button("上傳既有永久檔到 GitHub", use_container_width=True):
        res = upload_existing_permanent_files(archive=True)
        if res.get("ok"):
            clear_pending_backup_marker()
            st.success("已上傳既有永久檔到 GitHub，待備份標記已清除。")
        else:
            st.error(res.get("message", "上傳失敗"))
        st.json(res)
with c3:
    if st.button("建立永久檔並上傳 GitHub", use_container_width=True):
        res = create_and_upload_permanent_files()
        if res.get("ok"):
            clear_pending_backup_marker()
            st.success("永久備份完成，已存到 GitHub，待備份標記已清除。")
        else:
            st.error(res.get("message", "永久備份未完成；請看 JSON。"))
        st.json(res)
with c4:
    if st.button("立即從 GitHub 還原資料", use_container_width=True):
        res = ensure_data_guard_restore(force=True)
        if res.get("ok"):
            st.success("已執行 GitHub / 本機永久檔還原檢查。")
        else:
            st.error("還原未完成，請看下方 JSON。")
        st.json(res)

st.divider()
st.subheader("雲端檢查與修正 / Cloud Check & Fix")
c5, c6, c7 = st.columns(3)
with c5:
    if st.button("檢查 GitHub 雲端檔案", use_container_width=True):
        st.json(github_cloud_file_status())
with c6:
    if st.button("修正舊路徑 date → data", use_container_width=True):
        res = migrate_legacy_date_path_to_data_path()
        if res.get("ok"):
            st.success("已將舊路徑資料搬到正確 data/persistent_state。")
        else:
            st.warning("沒有搬移成功；可能舊路徑不存在，或 Token 權限不足。")
        st.json(res)
with c7:
    if st.button("只下載 GitHub latest 檔案", use_container_width=True):
        res = download_latest_permanent_files_from_github(allow_legacy=True)
        if res.get("ok"):
            st.success("已下載 GitHub latest 永久檔到本機暫存。")
        else:
            st.error(res.get("message", "下載失敗"))
        st.json(res)

st.divider()

st.subheader("目前永久檔狀態 / Permanent File Status")
try:
    main_count = database_business_row_count()
except Exception:
    main_count = 0
status_rows = [
    {"項目 / Item": "SQLite DB", "路徑 / Path": str(DB_PATH), "存在 / Exists": DB_PATH.exists(), "大小 / Size": DB_PATH.stat().st_size if DB_PATH.exists() else 0, "主資料筆數 / Business Rows": main_count},
    {"項目 / Item": "永久資料 latest", "路徑 / Path": str(LATEST_STATE), "存在 / Exists": LATEST_STATE.exists(), "大小 / Size": LATEST_STATE.stat().st_size if LATEST_STATE.exists() else 0, "主資料筆數 / Business Rows": ""},
    {"項目 / Item": "模組設定 latest", "路徑 / Path": str(LATEST_SETTINGS), "存在 / Exists": LATEST_SETTINGS.exists(), "大小 / Size": LATEST_SETTINGS.stat().st_size if LATEST_SETTINGS.exists() else 0, "主資料筆數 / Business Rows": ""},
]
st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)

if LATEST_STATE.exists():
    with st.expander("預覽永久資料 latest / Preview Permanent State", expanded=True):
        try:
            data = json.loads(LATEST_STATE.read_text(encoding="utf-8"))
            st.json({
                "export_time": data.get("export_time") or data.get("exported_at"),
                "version": data.get("version") or data.get("schema_version"),
                "business_row_count": data.get("business_row_count"),
                "table_counts": data.get("table_counts", {}),
                "skipped": data.get("skipped"),
                "warning": data.get("warning"),
            })
        except Exception as exc:
            st.error(str(exc))

st.caption("GitHub 正確保存路徑：data/persistent_state/ 與 data/persistent_state/history/。history 檔案使用時間戳，不會覆蓋舊檔。")
