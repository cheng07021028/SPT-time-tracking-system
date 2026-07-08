# -*- coding: utf-8 -*-
"""05｜製令工時分析：依 P/N / Part No. 萃取作業內容（組裝 Unit）。

設計原則：
- 只產生 05 分析用衍生欄位，不寫回 01/02 工時權威資料。
- 解析依據使用者提供的產品型式編碼原則與 Unit 名詞說明。
- 大量資料以「唯一 P/N 對照表」方式處理，避免逐列重複解析拖慢 05。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


def _blank(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"none", "nan", "nat", "null"} else text


def _nfkc_upper(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _blank(value)).upper()
    text = text.replace("–", "-").replace("—", "-").replace("－", "-").replace("_", "-")
    return text


def _clean_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _nfkc_upper(value))


WAFER_CARRIER_MAP: dict[str, str] = {
    "6": "Carrier：6吋 Cassette（晶舟盒）",
    "8": "Carrier：8吋 Cassette（晶舟盒）",
    "C": "Carrier：12吋 FOUP（晶舟盒）",
}

SMIF_MAP: dict[str, str] = {
    "S": "SMIF Type",
    "R": "Non SMIF Type",
}

MACHINE_TYPE_MAP: dict[str, str] = {
    "EB2": "機台Type：EB2（Embedded Loadport）",
    "EB4": "機台Type：EB4（Embedded Loadport）",
    "EB4L": "機台Type：EB4L（Embedded Loadport）",
    "SB2": "機台Type：SB2",
    "SB4": "機台Type：SB4",
    "SB4L": "機台Type：SB4L",
    "SB3L": "機台Type：SB3L",
    "EFEM": "機台Type：EFEM",
    "SORTER": "機台Type：Sorter",
    "NTB": "機台Type：NTB",
    "FCLP": "機台Type：FCLP",
    "BWBS": "機台Type：BWBS",
    "BENCH": "機台Type：Bench",
}

# P/N 文字若直接出現 Unit 名稱，補充顯示。 這些名詞來自使用者提供的圖片說明。
KEYWORD_UNIT_RULES: list[tuple[str, str]] = [
    ("ROBOT", "Robot（大氣晶圓傳輸機械手臂）"),
    ("LOADPORT", "Loadport（承載台）"),
    ("LOADPORT", "Loadport（承載台）"),
    ("ALIGNER", "Aligner（晶圓調整儀）"),
    ("CARRIERIDREADER", "Carrier ID Reader（RF / Barcode Reader）"),
    ("RFREADER", "Carrier ID Reader（RF Reader）"),
    ("BARCODEREADER", "Barcode Reader（條碼掃讀）"),
    ("OCR", "OCR（文字序號辨識）"),
    ("CLEANUNIT", "Clean Unit / FFU（空氣過濾系統）"),
    ("FFU", "Clean Unit / FFU（空氣過濾系統）"),
    ("IONIZER", "Ionizer（靜電消除離子棒）"),
    ("SIGNALTOWER", "Signal Tower（訊號燈塔）"),
    ("TOUCHPANEL", "Touch Panel（觸控式面板）"),
    ("KEYBOARDMOUSE", "Keyboard & Mouse（鍵盤與滑鼠）"),
    ("KEYBOARD", "Keyboard & Mouse（鍵盤與滑鼠）"),
    ("MOUSE", "Keyboard & Mouse（鍵盤與滑鼠）"),
    ("IPC", "IPC（工業電腦）"),
    ("EMOSWITCH", "EMO Switch（緊急停止開關）"),
    ("EMO", "EMO Switch（緊急停止開關）"),
    ("AREASENSOR", "Area Sensor / Light Curtain（安全光閘）"),
    ("LIGHTCURTAIN", "Area Sensor / Light Curtain（安全光閘）"),
    ("POWERUNIT", "Power Unit（電源供給裝置）"),
    ("FACILITY", "Facility（真空與氣體設備）"),
    ("XTABLE", "X Table"),
    ("TURNTABLE", "Turn Table"),
]

_CODE_RE = re.compile(r"([A-Z0-9]{6,12})\s*[-]\s*([A-Z0-9]{2,6})(?:\s*[-]\s*([A-Z0-9]{1,6}))?")


def _append_unique(items: list[str], value: str) -> None:
    text = _blank(value)
    if not text:
        return
    if text not in items:
        items.append(text)


def _digit_count(ch: str) -> int | None:
    return int(ch) if isinstance(ch, str) and ch.isdigit() else None


def _machine_label(code: str) -> str:
    key = _clean_key(code)
    if not key:
        return ""
    return MACHINE_TYPE_MAP.get(key, f"機台Type：{key}")


def _looks_like_product_base(base_code: Any) -> bool:
    base = _clean_key(base_code)
    if len(base) < 5:
        return False
    smif_code = base[-5]
    wafer_code = base[-4]
    robot_code = base[-3]
    loadport_code = base[-2]
    aligner_code = base[-1]
    return (
        smif_code in SMIF_MAP
        and wafer_code in WAFER_CARRIER_MAP
        and robot_code.isalnum()
        and loadport_code.isalnum()
        and aligner_code.isalnum()
    )


def _extract_code_parts(part_no: Any) -> tuple[str, str, str]:
    """Return (base_code, machine_type, serial) from a P/N-like text.

    Example: 4TSC121-EB2-22 -> (4TSC121, EB2, 22)
    Some historical files may include an extra customer letter before SMIF code,
    so the parser reads b~f from the right side of the first segment.
    """
    text = _nfkc_upper(part_no)
    matches = [m for m in _CODE_RE.finditer(text) if _looks_like_product_base(m.group(1))]
    if not matches:
        return "", "", ""

    # Prefer records with a known model segment; otherwise use the first P/N-like candidate.
    def _score(m: re.Match) -> tuple[int, int]:
        model_key = _clean_key(m.group(2) or "")
        known = 1 if model_key in MACHINE_TYPE_MAP else 0
        return known, len(m.group(0) or "")

    best = sorted(matches, key=_score, reverse=True)[0]
    return _blank(best.group(1)), _blank(best.group(2)), _blank(best.group(3))


def _keyword_units(part_no: Any) -> list[str]:
    key = _clean_key(part_no)
    if not key:
        return []
    items: list[str] = []
    for keyword, label in KEYWORD_UNIT_RULES:
        if keyword in key:
            _append_unique(items, label)
    return items


def parse_operation_content_from_part_no(part_no: Any) -> str:
    """Parse P/N / Part No. into a readable assembly Unit summary.

    Parsed fields from the product code:
    - b：SMIF 分類碼（S / R）
    - c：晶圓大小（6 / 8 / C）
    - d：Robot 數量
    - e：Loadport / Elevator / Turn Table / X Table 數量或組合碼
    - f：Aligner 數量
    - g~j：機台 Type（例如 EB2、EB4L、SB2）
    """
    base_code, machine_type, _serial = _extract_code_parts(part_no)
    items: list[str] = []

    machine_label = _machine_label(machine_type)
    _append_unique(items, machine_label)

    if base_code and len(_clean_key(base_code)) >= 5:
        base = _clean_key(base_code)
        smif_code = base[-5]
        wafer_code = base[-4]
        robot_code = base[-3]
        loadport_code = base[-2]
        aligner_code = base[-1]

        _append_unique(items, WAFER_CARRIER_MAP.get(wafer_code, ""))
        _append_unique(items, SMIF_MAP.get(smif_code, ""))

        robot_count = _digit_count(robot_code)
        if robot_count and robot_count > 0:
            _append_unique(items, f"Robot（大氣晶圓傳輸機械手臂）×{robot_count}")

        loadport_count = _digit_count(loadport_code)
        if loadport_count and loadport_count > 0:
            _append_unique(items, f"Loadport（承載台）×{loadport_count}")
        elif loadport_code and loadport_code != "0":
            _append_unique(items, f"Loadport / Elevator / Turn Table / X Table 組合碼：{loadport_code}")

        aligner_count = _digit_count(aligner_code)
        if aligner_count and aligner_count > 0:
            _append_unique(items, f"Aligner（晶圓調整儀）×{aligner_count}")

    # If the P/N itself spells out optional Units, append them as supplementary hints.
    for label in _keyword_units(part_no):
        _append_unique(items, label)

    return "、".join(items)


def apply_operation_content_column(
    df: pd.DataFrame,
    *,
    source_column: str = "part_no",
    column_name: str = "operation_content",
) -> pd.DataFrame:
    """Add 作業內容 / Operation Content column based on P/N / Part No.

    Uses a unique-value map so 100k rows with repeated P/N values do not parse
    the same text repeatedly. This is a display/report derived column only.
    """
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    if out.empty:
        out[column_name] = pd.Series(dtype="object")
        return out
    if source_column not in out.columns:
        out[column_name] = ""
        return out

    source = out[source_column].fillna("").astype(str)
    unique_values = source.drop_duplicates().tolist()
    mapping = {value: parse_operation_content_from_part_no(value) for value in unique_values}
    out[column_name] = source.map(mapping).fillna("")
    return out


def audit_operation_content_service() -> dict[str, Any]:
    return {
        "version": "V1",
        "source_column": "part_no",
        "output_column": "operation_content",
        "authority": "derived_only_no_writeback",
        "code_fields": ["SMIF", "wafer_size", "robot_count", "loadport_code", "aligner_count", "machine_type"],
    }
