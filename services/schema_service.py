from __future__ import annotations

from typing import Dict, List

DEFAULT_SCHEMAS: Dict[str, List[str]] = {
    "employees": ["員工編號", "姓名", "到職日", "累積年資", "職 稱", "課別", "部 門", "工段", "人力來源", "是否直接人力", "可用比例", "啟用", "備註"],
    "dispatch": ["員工編號", "姓名", "到職日", "累積年資", "課別", "部 門", "外包商年資", "工段", "人力來源", "是否直接人力", "可用比例", "啟用", "備註"],
    "schedule": ["WO", "客戶", "P/N", "Type", "Category", "組立地點", "機台入庫日", "MOVE IN", "月份", "台數", "PO", "工期", "標準工時", "需求工時", "狀態", "備註"],
    "standard_hours": ["客戶", "P/N", "Type", "Category", "標準工時", "標準天數", "版本", "是否啟用", "備註"],
    "work_calendar": ["月份", "月份數字", "月起日", "月迄日", "六日天數", "週六天數", "週日天數", "法定假日", "補班日", "扣除六日工作日", "正常工作日", "備註"],
    "capacity_summary_excel": ["月份", "每月機台數", "工作天數", "需求總工時", "正常可用工時", "正常稼動率", "正常產能負荷", "含加班可用工時", "含加班稼動率", "含加班產能負荷"],
    "capacity_adjustments": ["月份", "調整工時", "備註"],
    "users": ["帳號", "姓名", "角色", "啟用", "可查看模組", "可編輯模組", "備註"],
    "role_permissions": ["角色", "模組編號", "模組名稱", "可查看", "可新增", "可編輯", "可刪除", "可匯出", "可同步GitHub", "備註"],
    "module_notes": ["模組", "標題", "內容", "建立人", "建立時間", "狀態"],
}

TABLE_DISPLAY_NAMES: Dict[str, str] = {
    "employees": "01. 超慧員工名單",
    "dispatch": "02. 派遣名單",
    "schedule": "05. 排程表",
    "standard_hours": "06. 標準工時",
    "work_calendar": "07. 工作天數設定",
    "capacity_summary_excel": "Excel 原始彙整表",
    "capacity_adjustments": "04. 產能調整工時",
    "users": "11. 使用者與角色權限",
    "role_permissions": "11. 角色模組權限",
    "module_notes": "模組備註",
}

COLUMN_ALIASES: Dict[str, Dict[str, str]] = {
    "employees": {"累計年資": "累積年資"},
    "dispatch": {"累計年資": "累積年資"},
}


def schema_for_table(table_name: str) -> List[str]:
    return list(DEFAULT_SCHEMAS.get(table_name, []))


def canonical_column_name(table_name: str, column: str) -> str:
    text = str(column).strip()
    return COLUMN_ALIASES.get(table_name, {}).get(text, text)


def normalize_columns(table_name: str, columns: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for col in list(columns) + schema_for_table(table_name):
        text = canonical_column_name(table_name, str(col).strip())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
