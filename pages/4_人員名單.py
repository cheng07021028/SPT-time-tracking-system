# -*- coding: utf-8 -*-
from __future__ import annotations
import pandas as pd
import streamlit as st
from services.theme_service import apply_theme, render_header
from services.master_data_service import load_employees, upsert_employee, import_employees_df
from services.db_service import execute
from services.log_service import write_log

st.set_page_config(page_title="04 人員名單", page_icon="👷", layout="wide")
apply_theme()
render_header("04｜人員名單", "人員主檔、在廠狀態、今日出勤勾選")

TAB_UPLOAD, TAB_PASTE, TAB_MANUAL, TAB_LIST = st.tabs(["Excel 匯入", "貼上資料", "手動新增", "人員狀態管理"])

with TAB_UPLOAD:
    f = st.file_uploader("上傳人員名單 Excel", type=["xlsx", "xlsm", "xls"])
    if f:
        df = pd.read_excel(f)
        st.dataframe(df.head(50), use_container_width=True)
        if st.button("匯入人員資料", use_container_width=True):
            count = import_employees_df(df)
            st.success(f"已匯入 {count} 筆人員資料")
            st.rerun()

with TAB_PASTE:
    st.caption("建議欄位：工號、姓名、單位、職稱、備註。也可用英文欄位：employee_id, employee_name, department, title, note")
    pasted = st.text_area("從 Excel 複製後貼上", height=220)
    if st.button("解析並匯入貼上人員", use_container_width=True) and pasted.strip():
        rows = [line.split("\t") for line in pasted.strip().splitlines()]
        df = pd.DataFrame(rows[1:], columns=rows[0]) if len(rows) > 1 else pd.DataFrame(rows)
        count = import_employees_df(df)
        st.success(f"已匯入 {count} 筆")
        st.rerun()

with TAB_MANUAL:
    with st.form("manual_emp"):
        c1, c2, c3 = st.columns(3)
        emp_id = c1.text_input("工號 *")
        name = c2.text_input("姓名 *")
        dept = c3.text_input("單位")
        title = c1.text_input("職稱")
        note = c2.text_input("備註")
        ok = st.form_submit_button("儲存人員")
    if ok:
        upsert_employee({"employee_id": emp_id, "employee_name": name, "department": dept, "title": title, "note": note})
        write_log("UPSERT_EMPLOYEE", f"新增/更新人員 {emp_id} {name}", "employees", emp_id)
        st.success("已儲存")
        st.rerun()

with TAB_LIST:
    df = load_employees(active_only=False)
    if df.empty:
        st.info("尚無人員資料")
    else:
        edit_cols = ["id", "employee_id", "employee_name", "department", "title", "is_active", "is_in_factory", "is_today_attendance", "note"]
        edited = st.data_editor(df[edit_cols], use_container_width=True, hide_index=True, disabled=["id", "employee_id"], num_rows="fixed")
        if st.button("套用人員勾選狀態", use_container_width=True):
            for _, r in edited.iterrows():
                execute("UPDATE employees SET employee_name=?, department=?, title=?, is_active=?, is_in_factory=?, is_today_attendance=?, note=?, updated_at=datetime('now','localtime') WHERE id=?", (r["employee_name"], r["department"], r["title"], int(r["is_active"]), int(r["is_in_factory"]), int(r["is_today_attendance"]), r["note"], int(r["id"])))
            write_log("UPDATE_EMPLOYEE_STATUS", "更新人員在廠/出勤狀態", "employees")
            st.success("已更新")
            st.rerun()
