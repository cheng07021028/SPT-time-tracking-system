# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
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
from services.github_retention_service import (
    REMOTE_ALLOWED_ROOTS,
    audit_module_github_links,
    cleanup_github_files_by_date,
    load_cleanup_settings,
    preview_github_cleanup,
    run_due_github_cleanup_if_needed,
    save_cleanup_settings,
    upload_all_module_persistent_files_to_github,
)

# V1.45: keep page 09 header style consistent with other modules.
# Use the common two-argument render_header format to avoid showing only the module number.

apply_theme()
require_module_access("09_persistence", "can_view")
render_header("09｜資料永久保存與備份", "GitHub 雲端永久保存｜啟動自動還原｜防止空資料覆蓋")

try:
    from services.performance_profiler_service import start_page_event as _spt_v40_start_page_event, finish_page_event as _spt_v40_finish_page_event
    _SPT_V40_PAGE_TOKEN = _spt_v40_start_page_event("09", "資料永久保存與備份")
except Exception:
    _SPT_V40_PAGE_TOKEN = None


# V300.34: Keep page 09 light on Streamlit reruns.
# - Backup/restore actions remain explicit buttons.
# - Local/GitHub status reads are cached or manually triggered.
# - Neon/PostgreSQL authority is not changed by this page optimization.
V30034_GITHUB_CFG_CACHE_KEY = "v30034_09_github_cfg_cache"
V30034_CLEANUP_CFG_CACHE_KEY = "v30034_09_cleanup_cfg_cache"
V30034_PENDING_CACHE_KEY = "v30034_09_pending_status_cache"
V30034_LATEST_PREVIEW_KEY = "v30034_09_latest_state_preview"
V30034_PENDING_TTL_SECONDS = 8.0
V30034_SETTINGS_TTL_SECONDS = 300.0


def _v30034_now_ts() -> float:
    try:
        return float(time.time())
    except Exception:
        return 0.0


def _v30034_file_signature(path: Path) -> tuple[bool, int, int]:
    try:
        if not path.exists():
            return (False, 0, 0)
        stat = path.stat()
        return (True, int(stat.st_size), int(stat.st_mtime))
    except Exception:
        return (False, 0, 0)


def _v30034_get_cached_payload(key: str, ttl: float) -> dict | None:
    payload = st.session_state.get(key)
    if not isinstance(payload, dict):
        return None
    if ttl > 0 and (_v30034_now_ts() - float(payload.get("cached_at", 0.0) or 0.0)) > ttl:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _v30034_set_cached_payload(key: str, data: dict) -> dict:
    st.session_state[key] = {"cached_at": _v30034_now_ts(), "data": data}
    return data


def _v30034_github_config_cached(force: bool = False) -> dict:
    if not force:
        cached = _v30034_get_cached_payload(V30034_GITHUB_CFG_CACHE_KEY, V30034_SETTINGS_TTL_SECONDS)
        if cached is not None:
            return cached
    return _v30034_set_cached_payload(V30034_GITHUB_CFG_CACHE_KEY, github_config())


def _v30034_load_cleanup_settings_cached(force: bool = False) -> dict:
    if not force:
        cached = _v30034_get_cached_payload(V30034_CLEANUP_CFG_CACHE_KEY, V30034_SETTINGS_TTL_SECONDS)
        if cached is not None:
            return cached
    return _v30034_set_cached_payload(V30034_CLEANUP_CFG_CACHE_KEY, load_cleanup_settings())


def _v30034_save_cleanup_settings_cached(cfg: dict) -> dict:
    saved = save_cleanup_settings(cfg)
    settings = saved.get("settings") if isinstance(saved, dict) else None
    if isinstance(settings, dict):
        _v30034_set_cached_payload(V30034_CLEANUP_CFG_CACHE_KEY, settings)
    else:
        st.session_state.pop(V30034_CLEANUP_CFG_CACHE_KEY, None)
    return saved


def _v30034_pending_backup_status_cached(force: bool = False) -> dict:
    if not force:
        cached = _v30034_get_cached_payload(V30034_PENDING_CACHE_KEY, V30034_PENDING_TTL_SECONDS)
        if cached is not None:
            return cached
    return _v30034_set_cached_payload(V30034_PENDING_CACHE_KEY, pending_backup_status())


def _v30034_clear_pending_status_cache() -> None:
    st.session_state.pop(V30034_PENDING_CACHE_KEY, None)


def _v30034_latest_state_preview(force: bool = False) -> dict | None:
    sig = _v30034_file_signature(LATEST_STATE)
    cached = st.session_state.get(V30034_LATEST_PREVIEW_KEY)
    if not force and isinstance(cached, dict) and cached.get("signature") == sig:
        preview = cached.get("preview")
        return preview if isinstance(preview, dict) else None
    if not sig[0]:
        st.session_state.pop(V30034_LATEST_PREVIEW_KEY, None)
        return None
    try:
        data = json.loads(LATEST_STATE.read_text(encoding="utf-8"))
        preview = {
            "export_time": data.get("export_time") or data.get("exported_at"),
            "version": data.get("version") or data.get("schema_version"),
            "business_row_count": data.get("business_row_count"),
            "table_counts": data.get("table_counts", {}),
            "skipped": data.get("skipped"),
            "warning": data.get("warning"),
            "file_size": sig[1],
            "file_mtime": sig[2],
        }
        st.session_state[V30034_LATEST_PREVIEW_KEY] = {"signature": sig, "preview": preview}
        return preview
    except Exception as exc:
        preview = {"error": str(exc), "file_size": sig[1], "file_mtime": sig[2]}
        st.session_state[V30034_LATEST_PREVIEW_KEY] = {"signature": sig, "preview": preview}
        return preview


st.subheader("資料防消失中心 / Data Guard Center")
st.caption("V3.06：本頁只做備份紀錄、GitHub 備份狀態、手動雲端備份/還原查詢；每日自動備份排程統一在 13｜系統設定。")
st.info(
    "V1.30 已加入啟動自動還原：Streamlit Cloud 更新模組或重新部署後，如果 SQLite 不存在或主資料為 0，"
    "系統會先從 GitHub 的 data/permanent_store/persistent_state/spt_permanent_state.json 下載並還原。"
)

cfg = _v30034_github_config_cached()
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

# V3.26: GitHub module persistent-file audit and cleanup center.
with st.expander("GitHub 模組備份連結檢查 / Module Backup Link Audit", expanded=True):
    st.caption("檢查每個模組在 data/permanent_store/persistent_modules 的 records/settings 是否也有對應 GitHub 檔案。這可避免 Reboot App 後 SQLite 空白但 GitHub 沒有主檔可還原。")
    ga1, ga2, ga3 = st.columns(3)
    if ga1.button("檢查所有模組 GitHub 連結 / Audit Links", use_container_width=True, key="v326_audit_module_github_links"):
        res = audit_module_github_links(check_remote=True)
        st.session_state["v326_module_github_audit"] = res
    if ga2.button("上傳/修復模組資料與設定檔 / Sync Module Files", use_container_width=True, key="v326_upload_module_files"):
        res = upload_all_module_persistent_files_to_github()
        st.session_state["v326_module_upload_result"] = res
        if res.get("ok"):
            st.success("已同步所有可用的模組 records/settings 到 GitHub。")
        else:
            st.warning("部分模組檔案未同步，請查看結果。")
    if ga3.button("執行到期的 GitHub 定期清理 / Run Due Cleanup", use_container_width=True, key="v326_run_due_cleanup"):
        res = run_due_github_cleanup_if_needed()
        st.session_state["v326_due_cleanup_result"] = res
        st.info(res.get("message", "已執行檢查。"))

    audit = st.session_state.get("v326_module_github_audit")
    if audit:
        summary = audit.get("summary", {})
        ac1, ac2, ac3 = st.columns(3)
        ac1.metric("模組數", summary.get("modules", 0))
        ac2.metric("Records 已連結", summary.get("records_linked", 0))
        ac3.metric("Settings 已連結", summary.get("settings_linked", 0))
        st.dataframe(pd.DataFrame(audit.get("rows", [])), use_container_width=True, hide_index=True, height=360)
    if st.session_state.get("v326_module_upload_result"):
        with st.expander("模組檔案同步結果 / Sync Result", expanded=False):
            st.json(st.session_state.get("v326_module_upload_result"))

with st.expander("GitHub 備份檔清理 / GitHub Backup Cleanup", expanded=False):
    st.caption("安全規則：預設只清理有時間戳的 history/backup 檔，不刪 latest 主檔，避免影響目前系統顯示與功能。")
    cleanup_cfg = _v30034_load_cleanup_settings_cached()
    roots_default = cleanup_cfg.get("roots", ["data/permanent_store/persistent_state/history", "data/permanent_store/persistent_state/audit_history", "data/permanent_store/persistent_modules"])
    selected_roots = st.multiselect(
        "清理範圍 / Cleanup Roots",
        REMOTE_ALLOWED_ROOTS,
        default=[r for r in roots_default if r in REMOTE_ALLOWED_ROOTS],
        key="v326_cleanup_roots",
    )
    dc1, dc2, dc3 = st.columns(3)
    start_date = dc1.date_input("開始日期 / Start", value=pd.Timestamp.today().date() - pd.Timedelta(days=180), key="v326_cleanup_start")
    end_date = dc2.date_input("結束日期 / End", value=pd.Timestamp.today().date() - pd.Timedelta(days=90), key="v326_cleanup_end")
    include_undated = dc3.checkbox("允許刪除無日期檔案 / Include undated files", value=False, key="v326_cleanup_undated")
    pc1, pc2 = st.columns(2)
    if pc1.button("預覽清理清單 / Preview Cleanup", use_container_width=True, key="v326_preview_cleanup"):
        res = preview_github_cleanup(start_date, end_date, selected_roots, delete_undated_files=include_undated)
        st.session_state["v326_cleanup_preview"] = res
    confirm_delete = pc2.checkbox("我確認刪除 GitHub 上述範圍檔案 / Confirm Delete", value=False, key="v326_confirm_cleanup_delete")
    preview = st.session_state.get("v326_cleanup_preview")
    if preview:
        st.metric("待刪除候選檔 / Candidates", len(preview.get("candidates", [])))
        st.dataframe(pd.DataFrame(preview.get("candidates", [])), use_container_width=True, hide_index=True, height=260)
    if st.button("正式刪除預覽範圍 GitHub 檔案 / Delete GitHub Files", use_container_width=True, disabled=not confirm_delete, key="v326_delete_cleanup"):
        res = cleanup_github_files_by_date(start_date, end_date, selected_roots, delete_undated_files=include_undated, dry_run=False)
        st.session_state["v326_cleanup_result"] = res
        st.warning(f"GitHub 清理完成：刪除 {res.get('deleted_count', 0)} 個檔案。")
    if st.session_state.get("v326_cleanup_result"):
        with st.expander("GitHub 清理狀態 / Cleanup Status", expanded=False):
            st.json(st.session_state.get("v326_cleanup_result"))

    st.markdown("#### 定期清理設定 / Scheduled Cleanup")
    sc1, sc2, sc3, sc4 = st.columns(4)
    sched_enabled = sc1.checkbox("啟用定期清理", value=bool(cleanup_cfg.get("enabled", False)), key="v326_cleanup_sched_enabled")
    frequency = sc2.selectbox("週期", ["daily", "weekly", "monthly"], index=["daily", "weekly", "monthly"].index(str(cleanup_cfg.get("frequency", "weekly"))) if str(cleanup_cfg.get("frequency", "weekly")) in ["daily", "weekly", "monthly"] else 1, key="v326_cleanup_frequency")
    keep_days = sc3.number_input("保留天數", min_value=7, max_value=3650, value=int(cleanup_cfg.get("keep_days", 90)), step=1, key="v326_cleanup_keep_days")
    sc4.metric("上次清理", cleanup_cfg.get("last_run_at") or "尚未執行")
    if st.button("儲存 GitHub 定期清理設定 / Save Cleanup Schedule", use_container_width=True, key="v326_save_cleanup_schedule"):
        saved = _v30034_save_cleanup_settings_cached({
            **cleanup_cfg,
            "enabled": bool(sched_enabled),
            "frequency": frequency,
            "keep_days": int(keep_days),
            "roots": selected_roots,
            "delete_undated_files": bool(include_undated),
        })
        st.success("GitHub 定期清理設定已保存到 data/permanent_store/config/github_cleanup_settings.json。")
        st.json(saved)

st.divider()

st.subheader("待備份狀態 / Pending Backup Status")
pending = _v30034_pending_backup_status_cached()
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
            _v30034_clear_pending_status_cache()
            st.success("永久檔案已建立，待備份標記已清除。")
        else:
            st.warning(res.get("message", "建立失敗或被安全機制阻擋。"))
        st.json(res)
with c2:
    if st.button("上傳既有永久檔到 GitHub", use_container_width=True):
        res = upload_existing_permanent_files(archive=True)
        if res.get("ok"):
            clear_pending_backup_marker()
            _v30034_clear_pending_status_cache()
            st.success("已上傳既有永久檔到 GitHub，待備份標記已清除。")
        else:
            st.error(res.get("message", "上傳失敗"))
        st.json(res)
with c3:
    if st.button("建立永久檔並上傳 GitHub", use_container_width=True):
        res = create_and_upload_permanent_files()
        if res.get("ok"):
            clear_pending_backup_marker()
            _v30034_clear_pending_status_cache()
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
        st.json(github_cloud_file_status(metadata_only=True, include_summary=False))
with c6:
    if st.button("修正舊路徑 date → data", use_container_width=True):
        res = migrate_legacy_date_path_to_data_path()
        if res.get("ok"):
            st.success("已將舊路徑資料搬到正確 data/permanent_store/persistent_state。")
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
if st.button("載入永久檔狀態 / Load Permanent File Status", use_container_width=True, key="v69_load_permanent_file_status"):
    try:
        main_count = database_business_row_count()
    except Exception:
        main_count = 0
    st.session_state["v69_permanent_status_rows"] = [
        {"項目 / Item": "SQLite DB", "路徑 / Path": str(DB_PATH), "存在 / Exists": DB_PATH.exists(), "大小 / Size": DB_PATH.stat().st_size if DB_PATH.exists() else 0, "主資料筆數 / Business Rows": main_count},
        {"項目 / Item": "永久資料 latest", "路徑 / Path": str(LATEST_STATE), "存在 / Exists": LATEST_STATE.exists(), "大小 / Size": LATEST_STATE.stat().st_size if LATEST_STATE.exists() else 0, "主資料筆數 / Business Rows": ""},
        {"項目 / Item": "模組設定 latest", "路徑 / Path": str(LATEST_SETTINGS), "存在 / Exists": LATEST_SETTINGS.exists(), "大小 / Size": LATEST_SETTINGS.stat().st_size if LATEST_SETTINGS.exists() else 0, "主資料筆數 / Business Rows": ""},
    ]
status_rows = st.session_state.get("v69_permanent_status_rows", [])
if status_rows:
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
else:
    st.info("V69：永久檔狀態不再於開頁自動查詢資料庫，請按上方按鈕。")

if LATEST_STATE.exists():
    lp1, lp2 = st.columns([1, 3])
    if lp1.button("載入 latest 預覽", use_container_width=True, key="v30034_load_latest_preview"):
        _v30034_latest_state_preview(force=True)
    preview_payload = _v30034_latest_state_preview(force=False) if isinstance(st.session_state.get(V30034_LATEST_PREVIEW_KEY), dict) else None
    if preview_payload:
        with st.expander("預覽永久資料 latest / Preview Permanent State", expanded=False):
            if preview_payload.get("error"):
                st.error(preview_payload.get("error"))
            else:
                st.json(preview_payload)
    else:
        lp2.info("V300.34：latest JSON 可能很大，頁面不再自動讀取；需要時請按左側按鈕載入預覽。")

st.caption("GitHub 正確保存路徑：data/permanent_store/persistent_state/ 與 data/permanent_store/persistent_state/history/。history 檔案使用時間戳，不會覆蓋舊檔。")

try:
    _spt_v40_finish_page_event(_SPT_V40_PAGE_TOKEN)
except Exception:
    pass

