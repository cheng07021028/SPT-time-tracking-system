# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from services.theme_service import apply_theme, render_header
from services.github_cloud_storage_service import (
    DB_PATH,
    LATEST_SETTINGS,
    LATEST_STATE,
    STATE_DIR,
    create_and_upload_permanent_files,
    create_permanent_files,
    github_config,
    upload_existing_permanent_files,
)

apply_theme()
render_header("09", "資料永久保存與備份", "資料存 GitHub 雲端，不靠 Streamlit Cloud 暫存、不靠 git push")

st.subheader("GitHub 雲端永久保存 / GitHub Cloud Permanent Storage")
st.info(
    "本頁改用 GitHub Contents API 上傳 JSON 永久檔，不使用 git push，"
    "因此不會再出現 Host key verification failed 或 Author identity unknown。"
)

cfg = github_config()
with st.expander("GitHub 雲端設定檢查 / Cloud Settings", expanded=True):
    c1, c2, c3 = st.columns(3)
    c1.metric("Repository", cfg.get("repo") or "未設定")
    c2.metric("Branch", cfg.get("branch") or "main")
    c3.metric("Token", "已設定" if cfg.get("token") else "未設定")
    if not cfg.get("token"):
        st.warning(
            "請到 Streamlit Cloud → App settings → Secrets 加入：\n\n"
            'GITHUB_TOKEN = "你的 GitHub Token"\n'
            'GITHUB_REPOSITORY = "cheng07021028/SPT-time-tracking-system"\n'
            'GITHUB_BRANCH = "main"'
        )

st.divider()

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("建立本機永久檔 / Create Local Permanent Files", use_container_width=True):
        res = create_permanent_files()
        if res.get("ok"):
            st.success("永久檔案已建立")
            st.json(res)
        else:
            st.error(res.get("message", "建立失敗"))

with c2:
    if st.button("上傳既有永久檔到 GitHub 雲端", use_container_width=True):
        res = upload_existing_permanent_files()
        if res.get("ok"):
            st.success("已上傳既有永久檔到 GitHub 雲端")
        else:
            st.error(res.get("message", "上傳失敗"))
        st.json(res)

with c3:
    if st.button("建立永久檔並上傳 GitHub 雲端", use_container_width=True):
        res = create_and_upload_permanent_files()
        if res.get("ok"):
            st.success("永久備份完成，已存到 GitHub 雲端")
        else:
            st.error("永久備份建立完成，但 GitHub 雲端上傳有失敗項目")
        st.json(res)

st.divider()

st.subheader("目前永久檔狀態 / Permanent File Status")
status_rows = [
    {"項目 / Item": "SQLite DB", "路徑 / Path": str(DB_PATH), "存在 / Exists": DB_PATH.exists(), "大小 / Size": DB_PATH.stat().st_size if DB_PATH.exists() else 0},
    {"項目 / Item": "永久資料 latest", "路徑 / Path": str(LATEST_STATE), "存在 / Exists": LATEST_STATE.exists(), "大小 / Size": LATEST_STATE.stat().st_size if LATEST_STATE.exists() else 0},
    {"項目 / Item": "模組設定 latest", "路徑 / Path": str(LATEST_SETTINGS), "存在 / Exists": LATEST_SETTINGS.exists(), "大小 / Size": LATEST_SETTINGS.stat().st_size if LATEST_SETTINGS.exists() else 0},
]
st.dataframe(status_rows, use_container_width=True, hide_index=True)

if LATEST_STATE.exists():
    with st.expander("預覽永久資料 latest / Preview Permanent State", expanded=False):
        try:
            data = json.loads(LATEST_STATE.read_text(encoding="utf-8"))
            st.json({"export_time": data.get("export_time"), "table_counts": data.get("table_counts", {})})
        except Exception as exc:
            st.error(str(exc))

st.caption("GitHub 保存路徑：data/persistent_state/ 與 data/persistent_state/history/。history 檔案使用時間戳，不會覆蓋舊檔。")
