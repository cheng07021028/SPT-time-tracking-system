# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from services.theme_service import apply_theme, render_header
except Exception:
    def apply_theme():
        pass

    def render_header(title: str, subtitle: str = ""):
        st.title(title)
        if subtitle:
            st.caption(subtitle)

from services.security_service import require_module_access
from services.persistence_service import (
    BACKUP_DIR,
    create_persistent_backup,
    create_backup_and_push_to_github,
    git_backup_push,
    list_database_tables,
    load_latest_manifest,
    read_table,
)

st.set_page_config(
    page_title="09. 資料永久保存與備份",
    page_icon="💾",
    layout="wide",
)

apply_theme()
require_module_access("09_persistence")
render_header(
    "09｜資料永久保存與備份",
    "Permanent Data Backup｜SQLite → JSON / Excel / CSV → GitHub",
)

st.info(
    "此頁會將目前資料庫內的工時紀錄、歷史紀錄、製令、人員名單、LOG 等資料，"
    "輸出到 data/persistent_backups/，並可上傳到 GitHub 做永久保存。"
)

tables = list_database_tables()

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("資料表 / Tables", len(tables))
with c2:
    st.metric("備份資料夾 / Backup Folder", "persistent_backups")
with c3:
    st.metric("備份格式 / Formats", "JSON / XLSX / CSV")
with c4:
    manifest = load_latest_manifest()
    st.metric("最近備份 / Latest", manifest.get("backup_time", "尚未備份") if manifest else "尚未備份")

st.divider()

st.subheader("目前資料表 / Current Database Tables")

if not tables:
    st.warning("目前找不到資料表。請先確認資料庫已初始化。")
else:
    summary_rows = []
    for table in tables:
        try:
            df = read_table(table)
            summary_rows.append({
                "資料表 / Table": table,
                "筆數 / Records": len(df),
                "欄位數 / Columns": len(df.columns),
            })
        except Exception as exc:
            summary_rows.append({
                "資料表 / Table": table,
                "筆數 / Records": 0,
                "欄位數 / Columns": 0,
                "錯誤 / Error": str(exc),
            })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

st.divider()

st.subheader("建立永久備份 / Create Permanent Backup")

col_a, col_b, col_c = st.columns([1, 1, 2])

with col_a:
    include_excel = st.checkbox("產生 Excel / XLSX", value=True)
with col_b:
    include_csv = st.checkbox("產生 CSV", value=True)

with col_c:
    st.caption("JSON 一定會產生，適合 GitHub 長期保存與資料還原。Excel 適合主管查閱。CSV 適合稽核與程式分析。")

b1, b2, b3 = st.columns(3)

with b1:
    if st.button("建立永久備份", type="primary", use_container_width=True):
        with st.spinner("正在建立永久備份..."):
            result = create_persistent_backup(include_excel=include_excel, include_csv=include_csv)
        if result.ok:
            st.success(result.message)
            st.write("備份位置：", result.backup_dir)
            st.write(result.files)
        else:
            st.error(result.message)

with b2:
    if st.button("只上傳既有備份到 GitHub", use_container_width=True):
        with st.spinner("正在執行 git add / commit / push..."):
            result = git_backup_push()
        if result.ok:
            st.success(result.message)
        else:
            st.error(result.message)
        if result.git_output:
            st.code(result.git_output)

with b3:
    if st.button("建立備份並上傳 GitHub", use_container_width=True):
        with st.spinner("正在建立備份並上傳 GitHub..."):
            result = create_backup_and_push_to_github(include_excel=include_excel, include_csv=include_csv)
        if result.ok:
            st.success(result.message)
            st.write("備份位置：", result.backup_dir)
            st.write(result.files)
        else:
            st.error(result.message)
        if result.git_output:
            st.code(result.git_output)

st.divider()

st.subheader("最近備份資訊 / Latest Backup Manifest")

manifest = load_latest_manifest()
if manifest:
    st.json(manifest)
else:
    st.caption("尚未建立備份。")

st.divider()

st.subheader("操作建議 / Recommended Workflow")

st.markdown(
    """
1. 每天下班前按 **建立備份並上傳 GitHub**。  
2. 若公司電腦有排程需求，可執行根目錄的 `backup_to_github.bat`。  
3. SQLite 主資料庫 `data/database/spt_time_tracking.db` 不建議直接上傳 GitHub；GitHub 上保存的是可稽核、可還原的備份檔。  
4. 若未來要多人同時使用，建議升級 PostgreSQL / Supabase，避免多人同時寫入 SQLite 造成鎖定。
"""
)

st.caption(f"永久備份資料夾：{BACKUP_DIR}")
