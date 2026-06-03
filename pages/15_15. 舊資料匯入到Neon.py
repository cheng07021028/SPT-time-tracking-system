# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme
from services.security_service import require_module_access
from services.db_service import is_postgres_enabled
from services.legacy_neon_migration_service import save_uploaded_zip_and_migrate

st.set_page_config(page_title="15｜舊資料匯入到 Neon", page_icon="▣", layout="wide")
apply_theme()

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("15", "舊資料匯入到Neon")
except Exception:
    _SPT_V40_PAGE_TOKEN = None

require_module_access("09_persistence", "can_restore")

st.title("15｜舊資料匯入到 Neon")
st.caption("保留舊系統介面與功能，將舊專案 ZIP 內的 SQLite / permanent_store 資料匯入目前 Neon/PostgreSQL。")

if not is_postgres_enabled():
    st.error("目前未啟用 Neon/PostgreSQL。請先到 Streamlit Secrets 設定 DATABASE_URL。")
    st.stop()

st.warning("請上傳你原本的舊專案 ZIP。系統會匯入資料庫，不會把舊資料寫進 GitHub。")
up = st.file_uploader("上傳舊專案 ZIP，例如 SPT-time-tracking-system-main (260602).zip", type=["zip"])

if up is not None:
    st.info(f"已選擇：{up.name}")
    if st.button("開始匯入舊資料到 Neon", type="primary"):
        with st.spinner("正在匯入，請勿關閉頁面..."):
            try:
                result = save_uploaded_zip_and_migrate(up)
                st.success("匯入完成")
                st.json({k: v for k, v in result.items() if k != "tables"})
                rows = []
                for table, info in result.get("tables", {}).items():
                    row = {"table": table}
                    row.update(info)
                    rows.append(row)
                if rows:
                    st.dataframe(pd.DataFrame(rows), width="stretch")
                else:
                    st.warning("沒有找到可匯入的資料表。請確認 ZIP 是完整舊專案。")
            except Exception as exc:
                st.error(f"匯入失敗：{exc}")
                st.exception(exc)

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

