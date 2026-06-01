# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

APP_TITLE = "超慧科技製造部｜智慧工時紀錄系統"
APP_SUBTITLE = "SPT Manufacturing Time Tracking System"

@dataclass(frozen=True)
class ModuleInfo:
    key: str
    no: str
    title: str
    title_en: str
    desc: str
    page_file: str

MODULES: list[ModuleInfo] = [
    ModuleInfo("01_time_records", "01", "工時紀錄", "Time Records", "即時登錄、開始/結束、工時計算、同步保存", "01_01. 工時紀錄.py"),
    ModuleInfo("02_history", "02", "歷史紀錄", "History", "歷史工時明細、查詢、編輯、匯出", "02_02. 歷史紀錄.py"),
    ModuleInfo("03_work_orders", "03", "製令管理", "Work Orders", "製令主檔、貼上匯入、啟用停用、永久保存", "03_03. 製令管理.py"),
    ModuleInfo("04_employees", "04", "人員名單", "Employees", "人員主檔、出勤狀態、部門資料維護", "04_04. 人員名單.py"),
    ModuleInfo("05_analysis", "05", "製令工時分析", "Work Order Analysis", "製令累積工時、工段統計、圖表分析", "05_05. 製令工時分析.py"),
    ModuleInfo("06_logs", "06", "LOG查詢", "System Logs", "操作紀錄、異常紀錄、日期區間刪除", "06_06. LOG查詢.py"),
    ModuleInfo("07_missing", "07", "今日未紀錄名單", "Missing Today", "出勤但尚未紀錄工時的人員清單", "07_07. 今日未紀錄名單.py"),
    ModuleInfo("08_daily_hours", "08", "人員每日工時", "Daily Hours", "每日人員工時彙總、篩選與匯出", "08_08. 人員每日工時.py"),
    ModuleInfo("09_persistence", "09", "資料永久保存與備份", "Persistence", "單一路徑保存、備份、匯出、健康檢查", "09_09. 資料永久保存與備份.py"),
    ModuleInfo("10_permissions", "10", "權限管理", "Permissions", "帳號、角色、模組權限、閒置登出設定", "10_10. 權限管理.py"),
    ModuleInfo("11_login_logs", "11", "登入紀錄", "Login Logs", "登入、登出、權限不足與安全事件查詢", "11_11. 登入紀錄.py"),
    ModuleInfo("12_module_persistence", "12", "模組永久紀錄中心", "Module Persistence Center", "每個模組的 records/settings/backups 檢查", "12_12. 模組永久紀錄中心.py"),
    ModuleInfo("13_system_settings", "13", "系統設定", "System Settings", "工段、作業項目、休息時間、共用參數", "13_13. 系統設定.py"),
    ModuleInfo("99_speed_diagnostic", "99", "效能診斷", "Performance Diagnostic", "效能測速、慢查詢與錯誤事件診斷；限系統管理員", "99_99. 效能診斷.py"),
]
MODULE_BY_KEY = {m.key: m for m in MODULES}

TABLE_COLUMNS: dict[str, list[str]] = {
    "01_time_records": ["日期", "製令", "P/N", "機型", "工段", "工號", "姓名", "狀態", "開始時間", "結束時間", "工時小計", "累積工時", "備註"],
    "02_history": ["日期", "製令", "P/N", "機型", "工段", "工號", "姓名", "狀態", "開始時間", "結束時間", "工時小計", "累積工時", "備註"],
    "03_work_orders": ["製令", "P/N", "料號", "機型", "組立地點", "數量", "狀態", "啟用", "備註"],
    "04_employees": ["工號", "姓名", "單位", "職稱", "班別", "在職", "今日出勤", "帳號", "備註"],
    "06_logs": ["時間", "模組", "動作", "使用者", "結果", "訊息"],
    "10_permissions": ["帳號", "密碼", "姓名", "角色", "啟用", "備註"],
    "13_system_settings_process": ["工段分類", "工段", "啟用", "排序", "備註"],
    "13_system_settings_rest": ["名稱", "開始", "結束", "啟用", "備註"],
}

DEFAULT_REST_PERIODS = [
    {"名稱": "上午休息", "開始": "10:30", "結束": "10:45", "啟用": True, "備註": "固定休息"},
    {"名稱": "午休", "開始": "12:00", "結束": "13:00", "啟用": True, "備註": "固定休息"},
    {"名稱": "下午休息", "開始": "15:00", "結束": "15:15", "啟用": True, "備註": "固定休息"},
    {"名稱": "晚餐", "開始": "18:00", "結束": "18:30", "啟用": True, "備註": "固定休息"},
    {"名稱": "夜間休息", "開始": "20:00", "結束": "20:15", "啟用": True, "備註": "固定休息"},
]

DEFAULT_PROCESS_OPTIONS = [
    {"工段分類": "組裝", "工段": "S.T", "啟用": True, "排序": 10, "備註": "預設，可自行修改"},
    {"工段分類": "組裝", "工段": "收機", "啟用": True, "排序": 20, "備註": "預設，可自行修改"},
    {"工段分類": "包裝", "工段": "打包", "啟用": True, "排序": 30, "備註": "預設，可自行修改"},
]

ROLE_OPTIONS = ["admin", "manager", "leader", "operator", "viewer"]
ACTIONS = ["view", "edit", "delete", "import", "export", "manage"]
