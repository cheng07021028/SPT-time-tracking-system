# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access
from services.db_service import is_postgres_enabled
from services.legacy_neon_migration_service import (
    save_uploaded_zip_and_inspect,
    save_uploaded_zip_and_migrate,
)

st.set_page_config(page_title="15｜舊資料匯入到Neon", page_icon="▣", layout="wide")
apply_theme()

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("15", "舊資料匯入到Neon")
except Exception:
    _SPT_V40_PAGE_TOKEN = None

require_module_access("09_persistence", "can_restore")

render_header(
    "15",
    "舊資料匯入到Neon",
    "舊專案 ZIP 的 SQLite／permanent_store 資料匯入目前 Neon／PostgreSQL｜保留既有介面與功能，不寫入 GitHub",
)

V30040_PREVIEW_KEY = "v30040_legacy_import_preview"
V30040_RESULT_KEY = "v30040_legacy_import_result"
V30040_FILE_SIG_KEY = "v30040_legacy_import_file_sig"


def _v30040_upload_sig(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    return "|".join([
        str(getattr(uploaded_file, "name", "")),
        str(getattr(uploaded_file, "size", "")),
        str(getattr(uploaded_file, "type", "")),
    ])


def _v30040_clear_cached_results_when_file_changed(uploaded_file) -> None:
    sig = _v30040_upload_sig(uploaded_file)
    old_sig = st.session_state.get(V30040_FILE_SIG_KEY, "")
    if sig != old_sig:
        st.session_state[V30040_FILE_SIG_KEY] = sig
        st.session_state.pop(V30040_PREVIEW_KEY, None)
        st.session_state.pop(V30040_RESULT_KEY, None)


def _v30040_show_result(result: dict, *, title: str) -> None:
    st.subheader(title)
    meta = {k: v for k, v in result.items() if k != "tables"}
    st.json(meta)
    rows = []
    for table, info in (result.get("tables") or {}).items():
        row = {"table": table}
        if isinstance(info, dict):
            row.update(info)
        rows.append(row)
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch")
    else:
        st.warning("沒有找到可匯入的資料表。請確認 ZIP 是完整舊專案。")


if not is_postgres_enabled():
    st.error("目前未啟用 Neon/PostgreSQL。請先到 Streamlit Secrets 設定 DATABASE_URL。")
    st.stop()

st.warning("請上傳你原本的舊專案 ZIP。系統會匯入資料庫，不會把舊資料寫進 GitHub。")
up = st.file_uploader("上傳舊專案 ZIP，例如 SPT-time-tracking-system-main (260602).zip", type=["zip"])
_v30040_clear_cached_results_when_file_changed(up)

if up is not None:
    st.info(f"已選擇：{up.name}")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("檢查 ZIP 內容（不寫入 Neon）"):
            with st.spinner("正在檢查 ZIP 內容，不會寫入 Neon..."):
                try:
                    st.session_state[V30040_PREVIEW_KEY] = save_uploaded_zip_and_inspect(up)
                    st.success("ZIP 內容檢查完成，尚未寫入 Neon。")
                except Exception as exc:
                    st.error(f"檢查失敗：{exc}")
                    st.exception(exc)
    with c2:
        if st.button("開始匯入舊資料到 Neon", type="primary"):
            with st.spinner("正在匯入，請勿關閉頁面..."):
                try:
                    result = save_uploaded_zip_and_migrate(up)
                    st.session_state[V30040_RESULT_KEY] = result
                    st.success("匯入完成")
                except Exception as exc:
                    st.error(f"匯入失敗：{exc}")
                    st.exception(exc)

    preview = st.session_state.get(V30040_PREVIEW_KEY)
    if isinstance(preview, dict):
        _v30040_show_result(preview, title="ZIP 內容預覽（未寫入 Neon）")

    result = st.session_state.get(V30040_RESULT_KEY)
    if isinstance(result, dict):
        _v30040_show_result(result, title="匯入結果")

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass
