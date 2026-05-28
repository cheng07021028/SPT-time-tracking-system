# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from services.theme_service import apply_theme, render_header
from services.security_service import require_module_access, check_permission
from services.timezone_service import today_date
from services.time_record_integrity_service import (
    audit_time_record_integrity,
    repair_0102_authority_non_destructive,
    export_audit_excel_bytes,
)

st.set_page_config(page_title="14. 資料健康檢查中心", page_icon="🛡️", layout="wide")
apply_theme()
try:
    require_module_access("12_module_persistence", "can_view")
except Exception:
    # Keep the page guarded by 12 permissions when available.  If a deployment has
    # not yet mapped module 14, require_module_access will already stop unauthorized
    # users; this fallback only prevents older services from crashing imports.
    pass

render_header("14｜資料健康檢查中心", "工時紀錄稽核、資料遺失檢查、01/02 權威檔非破壞式修復")

st.warning(
    "本頁只用於資料健康檢查與非破壞式修復。檢查不寫入；修復只合併缺漏資料到 01/02 權威檔，"
    "不刪除、不重新編號、不用畫面局部資料覆蓋完整歷史。"
)

if "v153_audit_result" not in st.session_state:
    st.session_state["v153_audit_result"] = None

c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
start_date = c1.date_input("檢查開始日期 / Start", value=today_date() - timedelta(days=7), key="v153_start_date")
end_date = c2.date_input("檢查結束日期 / End", value=today_date(), key="v153_end_date")
github_backup = c3.checkbox("修復後同步 GitHub", value=True, help="正式修復建議勾選；若 GitHub 很慢，可先取消，之後再手動備份。")
dry_run = c4.checkbox("只模擬修復 / Dry Run", value=True)

b1, b2, b3 = st.columns([1, 1, 1])
if b1.button("🔍 執行資料健康檢查", use_container_width=True, key="v153_run_audit"):
    if start_date > end_date:
        st.error("開始日期不可大於結束日期。")
        st.stop()
    with st.spinner("正在比對 LOG、01/02 權威檔、SQLite、row shard、event journal..."):
        st.session_state["v153_audit_result"] = audit_time_record_integrity(str(start_date), str(end_date))
    st.rerun()

result = st.session_state.get("v153_audit_result")

if result:
    summary = result.get("summary", {})
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("合併後工時筆數", summary.get("merged_records", 0))
    s2.metric("START LOG 筆數", summary.get("log_start_count", 0))
    s3.metric("異常總數", summary.get("issue_count", 0))
    s4.metric("重大異常", summary.get("critical_count", 0))
    s5.metric("可自動修復", summary.get("repairable_count", 0))

    issues = result.get("issues")
    if isinstance(issues, pd.DataFrame) and not issues.empty:
        st.markdown("### 異常清單 / Issue List")
        st.dataframe(issues, use_container_width=True, hide_index=True, height=520)
    else:
        st.success("目前檢查範圍內未發現工時資料重大異常。")

    with st.expander("來源統計 / Source Counts", expanded=False):
        st.json(summary.get("source_counts", {}))

    with st.expander("合併後資料預覽 / Merged Records Preview", expanded=False):
        merged = result.get("merged_records")
        if isinstance(merged, pd.DataFrame) and not merged.empty:
            st.dataframe(merged.head(500), use_container_width=True, hide_index=True, height=420)
        else:
            st.info("沒有可預覽的合併資料。")

    excel_bytes = export_audit_excel_bytes(result)
    st.download_button(
        "⬇️ 下載資料健康檢查 Excel",
        data=excel_bytes,
        file_name=f"SPT_V153_資料健康檢查_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.divider()
    st.markdown("### 非破壞式修復 / Non-destructive Repair")
    st.caption("修復會把 02_history、01_time_records、SQLite、row shard、event row 中仍可完整還原的工時資料合併後，寫回 01/02 canonical。只剩 LOG 的資料不會自動補，避免產生不完整紀錄。")

    can_repair = False
    try:
        can_repair = bool(check_permission("12_module_persistence", "can_manage") or check_permission("12_module_persistence", "can_edit"))
    except Exception:
        can_repair = True

    if not can_repair:
        st.info("你的帳號沒有資料修復權限。")
    else:
        confirm = st.checkbox("我確認執行非破壞式合併修復", key="v153_confirm_repair")
        if b2.button("🛠️ 執行非破壞式修復", use_container_width=True, disabled=not confirm, key="v153_repair_button"):
            with st.spinner("正在進行非破壞式合併修復..."):
                repair_result = repair_0102_authority_non_destructive(
                    github=bool(github_backup),
                    start_date=str(start_date),
                    end_date=str(end_date),
                    dry_run=bool(dry_run),
                )
            st.session_state["v153_repair_result"] = repair_result
            if repair_result.get("ok"):
                st.success("修復流程完成。" + ("（Dry Run，未寫入）" if repair_result.get("dry_run") else ""))
            else:
                st.error(f"修復未執行或失敗：{repair_result.get('reason')}")
            st.json(repair_result)

if b3.button("🧹 清除本頁檢查結果", use_container_width=True, key="v153_clear_result"):
    st.session_state["v153_audit_result"] = None
    st.session_state.pop("v153_repair_result", None)
    st.rerun()

st.caption("V153：資料健康檢查中心。建議每次部署修正包後先執行檢查，再決定是否修復。")
