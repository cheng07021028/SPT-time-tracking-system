from __future__ import annotations

import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from services.capacity_engine import summarize_manpower
from services.data_loader import load_table
from services.org_chart_service import (
    build_people_frame,
    delete_org_layout_record,
    delete_org_structure_record,
    get_org_layout_record,
    get_org_structure_frame,
    list_org_layout_records,
    org_people_signature,
    rebuild_org_structure_frame,
    render_org_component_html,
    render_org_html,
    export_org_chart_layout_xlsx_bytes,
    save_org_layout_record,
    save_org_structure_frame,
)
from services.page_utils import render_configurable_view, render_module_report_download
from services.powerbi_theme import chart_spec, render_powerbi_chart, style_powerbi_figure
from services.ui_theme import apply_tech_theme, render_hero, render_human_help
from services.year_service import available_years_from_frames, filter_by_year

st.set_page_config(page_title="03. 製造部組織圖", page_icon="🛰️", layout="wide")
apply_tech_theme()
render_hero("03. 製造部組織圖", "將階層式樹狀圖直接改成你提供圖片的排列方式：上方統計表、主管層、製造部、製一課/製二課、各工段與人員卡片清楚分區。")
render_human_help([
    "本頁不是新增 Excel 版面模式，而是把原本的『階層式樹狀圖（可拖拉卡片）』直接改成你提供圖片的階層排列與配色。",
    "主要結構為：人力統計表 → 主管層 → 製造部 → 製一課 / 製二課 → 工段 → 職稱 / 人力來源 → 人員，並在卡片內保留機型資訊。",
    "組織圖預設為瀏覽模式；按「啟動編輯」後，才會顯示新增、刪除、修改文字、拖曳微調位置、移到最上層/最下層與版面保存功能。",
    "若要讓調整後版面 Reboot 後仍保留，請在組織圖內按「複製永久記錄碼」，貼到本頁「永久記錄」區塊後按「儲存永久記錄」。",
    "正式人員資料仍以 01. 超慧員工名單與 02. 派遣名單為權威；新增或修改人員後，03 會依課別、工段、職稱與人力來源自動放入對應位置並更新上方人力統計。",
])

employees = load_table("employees")
dispatch = load_table("dispatch")
years = available_years_from_frames([employees, dispatch])
selected_year = st.selectbox("顯示/分析年份", years, index=len(years)-1, key="org_year_filter")
employees_year = filter_by_year(employees, selected_year)
dispatch_year = filter_by_year(dispatch, selected_year)
people = build_people_frame(employees_year, dispatch_year)
summary = summarize_manpower(employees_year, dispatch_year, target_year=selected_year)

with st.form("org_filter_form"):
    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)
    dept_options = sorted([x for x in people.get("部門", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    course_options = sorted([x for x in people.get("課別", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    title_options = sorted([x for x in people.get("職稱", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    machine_options = sorted([x for x in people.get("機型", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    stage_options = sorted([x for x in people.get("工段", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    source_options = sorted([x for x in people.get("人力來源", []).dropna().astype(str).unique().tolist()]) if not people.empty else []
    selected_depts = c1.multiselect("部門", dept_options, default=dept_options)
    selected_courses = c2.multiselect("課別", course_options, default=course_options)
    selected_titles = c3.multiselect("職稱", title_options, default=title_options)
    selected_machines = c4.multiselect("機型", machine_options, default=machine_options)
    selected_stages = c5.multiselect("工段", stage_options, default=stage_options)
    selected_sources = c6.multiselect("人力來源", source_options, default=source_options)
    st.form_submit_button("套用組織圖篩選", type="primary")

view = people.copy()
if selected_depts:
    view = view[view["部門"].astype(str).isin(selected_depts)]
if selected_courses:
    view = view[view["課別"].astype(str).isin(selected_courses)]
if selected_titles:
    view = view[view["職稱"].astype(str).isin(selected_titles)]
if selected_machines:
    view = view[view["機型"].astype(str).isin(selected_machines)]
if selected_stages:
    view = view[view["工段"].astype(str).isin(selected_stages)]
if selected_sources:
    view = view[view["人力來源"].astype(str).isin(selected_sources)]

org_source_signature = org_people_signature(view)
st.info(
    f"03 組織圖已直接連動 01/02 權威名單：目前篩選後 {len(view)} 人。"
    "新增人員後會依課別、工段、職稱、人力來源自動出現在相關位置；上方人力統計表也會即時依目前組織圖重新計算。"
)

layout_filter_snapshot = {
    "部門": selected_depts,
    "課別": selected_courses,
    "職稱": selected_titles,
    "機型": selected_machines,
    "工段": selected_stages,
    "人力來源": selected_sources,
}


structure_df = get_org_structure_frame(selected_year, view)
with st.expander("組織架構位置設定（依此架構排列目前 01/02 人員）", expanded=False):
    st.markdown(
        """
        這裡設定的是組織圖的**架構卡片**，不是直接改人員資料。組織圖會依此規則把目前 01/02 名單自動放到對應位置：
        **製造部 → 課別 → 組別 → 職稱/人員**。組別可用「工段清單」指定要收哪些工段；多個工段請用逗號分隔。
        多出來或不是你要的架構卡片，可以勾選「刪除」後按「儲存架構設定並套用」，會永久從本年度架構設定移除。
        """
    )
    st.info(
        "範例：最上層『製造部』可設定管理職稱=經理；第二層『製一課/製二課』可設定管理職稱=課長,主任；"
        "第三層『組別』可把多個工段放在同一組，例如 工段清單=模組,配電,配線。儲存後，上方組織圖會依此架構重新排列。"
    )
    edited_structure = st.data_editor(
        structure_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"org_structure_editor_{selected_year}",
        height=360,
        column_config={
            "刪除": st.column_config.CheckboxColumn("刪除", default=False, help="勾選後按『儲存架構設定並套用』，會永久移除此架構卡片。"),
            "啟用": st.column_config.CheckboxColumn("啟用", default=True, help="取消勾選後，此架構卡片不參與組織圖排列；重建草稿時會保留此設定。"),
            "層級": st.column_config.NumberColumn("層級", min_value=1, max_value=6, step=1, format="%d"),
            "架構類型": st.column_config.SelectboxColumn("架構類型", options=["部門", "課別", "組別"], required=True),
            "顯示名稱": st.column_config.TextColumn("顯示名稱", required=True),
            "上層": st.column_config.TextColumn("上層"),
            "課別": st.column_config.TextColumn("課別"),
            "工段清單": st.column_config.TextColumn("工段清單（逗號分隔）"),
            "管理職稱清單": st.column_config.TextColumn("管理職稱清單"),
            "成員職稱清單": st.column_config.TextColumn("成員職稱清單"),
            "排序": st.column_config.NumberColumn("排序", step=1, format="%d"),
        },
    )
    c_struct1, c_struct2, c_struct3 = st.columns([1.4, 1.2, 1])
    with c_struct1:
        save_structure_clicked = st.button("儲存架構設定並套用", type="primary", key=f"save_org_structure_{selected_year}")
    with c_struct2:
        rebuild_structure_clicked = st.button("由目前名單重建架構草稿", key=f"rebuild_org_structure_{selected_year}")
    with c_struct3:
        delete_structure_clicked = st.button("刪除本年度架構設定", key=f"delete_org_structure_{selected_year}")
    if save_structure_clicked:
        try:
            structure_df = save_org_structure_frame(selected_year, edited_structure, user="streamlit")
            st.success("已永久儲存組織架構設定；已勾選『刪除』的架構卡片已移除，上方組織圖會依此架構排列目前 01/02 人員。")
            st.rerun()
        except Exception as exc:
            st.error(f"組織架構設定儲存失敗：{exc}")
    if rebuild_structure_clicked:
        try:
            structure_df = rebuild_org_structure_frame(selected_year, view, user="streamlit")
            st.success("已依 製造部 → 課別 → 組別 → 職稱/人員 的階層重建架構草稿並永久儲存；既有架構的啟用/停用狀態會保留，不會再全部勾回啟用。")
            st.rerun()
        except Exception as exc:
            st.error(f"重建架構草稿失敗：{exc}")
    if delete_structure_clicked:
        if delete_org_structure_record(selected_year, user="streamlit"):
            st.success("已刪除本年度架構設定；系統會回到依 01/02 名單自動產生架構。")
            st.rerun()
        else:
            st.warning("目前年度沒有已保存的架構設定。")

layout_records = list_org_layout_records(selected_year)
layout_label_to_id = {"不套用永久記錄，使用 01/02 即時計算版面": ""}
for record in layout_records:
    label = f"{record.get('name', '未命名版面')}｜{record.get('saved_at', '')}"
    layout_label_to_id[label] = str(record.get("id", ""))
selected_layout_label = st.selectbox(
    "製造部階層式組織圖永久記錄",
    list(layout_label_to_id.keys()),
    index=0,
    key=f"org_layout_record_select_{selected_year}",
    help="永久記錄只影響 03 組織圖展示版面，不會覆蓋 01/02 權威人員資料。",
)
selected_layout_id = layout_label_to_id.get(selected_layout_label, "")
selected_layout_record = get_org_layout_record(selected_layout_id) if selected_layout_id else None
selected_layout_html = selected_layout_record.get("html") if selected_layout_record else None
if selected_layout_record:
    st.info(f"已套用永久記錄：{selected_layout_record.get('name', '未命名版面')}；上方人力統計與製造部總數仍會依目前 01/02 名單重新計算。若要讓新增人員自動依最新課別/工段展開，請選擇『不套用永久記錄』或重新儲存永久記錄。")

if view.empty:
    st.warning("目前篩選條件下沒有組織人力資料。")
else:
    view_mode = st.radio(
        "組織圖顯示模式",
        ["階層式樹狀圖（可拖拉卡片）", "卷軸式分類清單"],
        horizontal=True,
        index=0,
    )
    if view_mode == "階層式樹狀圖（可拖拉卡片）":
        try:
            org_xlsx = export_org_chart_layout_xlsx_bytes(view, year=selected_year, structure_settings=structure_df)
            st.download_button(
                "下載Excel版面（真正 .xlsx，不會空白）",
                data=org_xlsx,
                file_name=f"製造部組織圖_版面匯出_{selected_year}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"download_org_chart_layout_xlsx_{selected_year}_{org_source_signature}",
                type="primary",
                help="此按鈕由 Streamlit 伺服端產生真正 xlsx，避免瀏覽器端匯出造成 Excel 修復或空白。",
            )
        except Exception as exc:
            st.error(f"Excel 版面檔產生失敗：{exc}")
        with st.expander("組織圖顯示範圍 / 縮放 / 畫布設定", expanded=False):
            st.caption("若組織圖太大或卷軸可移動範圍不足，可在此調整外層視窗高度、畫布大小與預設縮放。畫布只影響 03 展示，不會修改 01/02 權威人員資料。")
            c_view1, c_view2, c_view3, c_view4, c_view5 = st.columns([1, 1, 1, 1, 1.2])
            org_viewport_height = c_view1.slider("視窗高度(px)", 900, 2400, 1680, 100, key=f"org_viewport_height_{selected_year}")
            org_canvas_width = c_view2.slider("畫布寬度(px)", 3000, 7000, 4200, 200, key=f"org_canvas_width_{selected_year}")
            org_canvas_height = c_view3.slider("畫布高度(px)", 1900, 5200, 3000, 200, key=f"org_canvas_height_{selected_year}")
            org_default_zoom = c_view4.slider("預設縮放(%)", 20, 180, 70, 5, key=f"org_default_zoom_{selected_year}")
            org_auto_expand_canvas = c_view5.checkbox("自動依卡片範圍擴大畫布", value=True, key=f"org_auto_expand_canvas_{selected_year}")
            st.info("建議：人員多或階層很寬時，先用預設 70% 檢視；若仍看不到完整圖，按組織圖工具列的『完整顯示』或『畫布＋20%』。")
        component_height = int(org_viewport_height) + 260
        components.html(
            render_org_component_html(
                view,
                saved_layout_html=selected_layout_html,
                storage_key_suffix=f"{selected_year}_{selected_layout_id or 'live'}_{org_source_signature}",
                year=selected_year,
                structure_settings=structure_df,
                viewport_height=int(org_viewport_height),
                canvas_width=int(org_canvas_width),
                canvas_height=int(org_canvas_height),
                default_zoom=int(org_default_zoom),
                auto_expand_canvas=bool(org_auto_expand_canvas),
            ),
            height=component_height,
            scrolling=True,
        )
        st.caption("此組織圖直接由 01/02 最新名單產生；新增人員會依課別、機型、工段、職稱、人力來源自動放入對應位置。上方工具列可調整縮放比例、完整顯示、畫布大小、回到左上與全螢幕播放；Excel 請使用組織圖上方的 Streamlit『下載Excel版面』按鈕。")
    else:
        st.markdown(f'<div class="org-scroll-wrap">{render_org_html(view)}</div>', unsafe_allow_html=True)

with st.expander("製造部階層式組織圖永久記錄", expanded=False):
    st.markdown(
        """
        操作方式：先在上方階層式組織圖按「啟動編輯」，完成拖曳、文字修改或最上層/最下層調整後，
        按「複製永久記錄碼」。再把記錄碼貼到下方欄位，按「儲存永久記錄」。
        永久記錄只保存 03 組織圖展示版面，不會修改 01/02 人員權威資料。
        """
    )
    with st.form("org_layout_save_form", clear_on_submit=False):
        c_save1, c_save2 = st.columns([1, 2])
        layout_name = c_save1.text_input("永久記錄名稱", value=f"{selected_year} 製造部組織圖")
        layout_code = c_save2.text_area("貼上永久記錄碼", height=160, placeholder="請貼上從組織圖按『複製永久記錄碼』取得的內容")
        save_layout_clicked = st.form_submit_button("儲存永久記錄", type="primary")
    if save_layout_clicked:
        try:
            saved = save_org_layout_record(layout_name, selected_year, layout_code, filters=layout_filter_snapshot, user="streamlit")
            st.success(f"已儲存永久記錄：{saved.get('name')}。重新整理後可從上方下拉選單套用。")
            st.rerun()
        except Exception as exc:
            st.error(f"永久記錄儲存失敗：{exc}")
    if selected_layout_record:
        c_del1, c_del2 = st.columns([1, 3])
        with c_del1:
            delete_clicked = st.button("刪除目前永久記錄", type="secondary")
        with c_del2:
            st.caption(f"目前套用：{selected_layout_record.get('name', '未命名版面')}｜{selected_layout_record.get('saved_at', '')}")
        if delete_clicked:
            if delete_org_layout_record(selected_layout_id, user="streamlit"):
                st.success("已刪除目前永久記錄。")
                st.rerun()
            else:
                st.warning("找不到可刪除的永久記錄。")

st.subheader("組織 Power BI 風格摘要")
if not summary.empty:
    c1, c2 = st.columns([1, 1])
    with c1:
        fig = px.bar(summary, x="工段", y="有效人力", color="課別", title="工段有效人力")
        render_powerbi_chart(style_powerbi_figure(fig, height=360, yaxis_title="有效人力"), key="org_effective_people")
    with c2:
        src = summary.groupby("人力來源", as_index=False).agg(有效人力=("有效人力", "sum"))
        fig2 = px.pie(src, names="人力來源", values="有效人力", title="人力來源占比", hole=0.48)
        fig2 = style_powerbi_figure(fig2, height=390)
        fig2.update_traces(
            textposition="outside",
            automargin=True,
            domain={"x": [0.08, 0.92], "y": [0.20, 0.94]},
            marker={"line": {"color": "rgba(255,255,255,0.55)", "width": 1}},
        )
        fig2.update_layout(
            meta={"spt_safe_pie_labels": True, "spt_pie_show_mode": "label+percent"},
            legend={
                "orientation": "h",
                "yanchor": "top",
                "y": -0.08,
                "xanchor": "center",
                "x": 0.5,
                "bgcolor": "rgba(2,6,23,0.58)",
                "bordercolor": "rgba(56,189,248,0.25)",
                "borderwidth": 1,
            },
            margin={"l": 86, "r": 86, "t": 82, "b": 118},
        )
        render_powerbi_chart(fig2, key="org_source_mix")
else:
    src = summary.copy()

st.subheader("組織摘要表")
render_configurable_view(summary, "org_summary", "03. 組織人力摘要", height=420)

st.subheader("03. 模組完整匯出")
source_mix = summary.groupby("人力來源", as_index=False).agg(有效人力=("有效人力", "sum")) if not summary.empty and "人力來源" in summary.columns else summary.copy()
render_module_report_download(
    "03.製造部組織圖",
    {"組織明細": view, "組織摘要": summary, "人力來源占比": source_mix},
    chart_specs=[
        chart_spec("bar", "工段有效人力", "組織摘要", "工段", ["有效人力"]),
        chart_spec("pie", "人力來源占比", "人力來源占比", "人力來源", ["有效人力"]),
    ],
    metadata={"模組": "03. 製造部組織圖", "顯示年份": selected_year, "匯出內容": "組織明細、摘要與圖表"},
    key="export_org_module",
)
