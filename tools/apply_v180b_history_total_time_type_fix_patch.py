# -*- coding: utf-8 -*-
"""
V180B｜02 歷史紀錄總工時 TypeError 修復 Patch

目的：
- 修正 pages/02_02. 歷史紀錄.py 內 df['work_hours'].sum() 遇到數字與 00:00:00 字串混合時崩潰。
- 不改畫面、不改 CSS、不改 theme、不改表格渲染、不改刪除流程。

用法：
    python tools/apply_v180b_history_total_time_type_fix_patch.py
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGE = PROJECT_ROOT / "pages" / "02_02. 歷史紀錄.py"
MARKER = "# === V180B_HISTORY_TOTAL_TIME_TYPE_FIX_BEGIN ==="

HELPER = r'''
# === V180B_HISTORY_TOTAL_TIME_TYPE_FIX_BEGIN ===
def _v180b_parse_work_hours_to_decimal_hours(value):
    """Safely convert mixed work_hours values to decimal hours.

    Supported inputs:
    - numeric hours, e.g. 0.16
    - HH:MM:SS, e.g. 00:09:36
    - H:MM, e.g. 1:30
    - strings with blanks, commas, or legacy labels
    Invalid/blank values are treated as 0.
    """
    try:
        if value is None:
            return 0.0
        # pandas/numpy missing values
        try:
            import pandas as _pd  # local import: app already depends on pandas
            if _pd.isna(value):
                return 0.0
        except Exception:
            pass
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        if text.lower() in {"nan", "none", "null", "nat", "未按結束", "清空"}:
            return 0.0
        # Remove common human-readable decorations without changing real values.
        text = text.replace(",", "").replace("小時", "").strip()
        text = text.replace("時", ":").replace("分", ":").replace("秒", "")
        if ":" in text:
            parts = [p for p in text.split(":") if p != ""]
            nums = []
            for p in parts[:3]:
                try:
                    nums.append(float(p))
                except Exception:
                    nums.append(0.0)
            while len(nums) < 3:
                nums.append(0.0)
            h, m, s = nums[0], nums[1], nums[2]
            return max(0.0, h + m / 60.0 + s / 3600.0)
        return max(0.0, float(text))
    except Exception:
        return 0.0


def _v180b_decimal_hours_to_hms(total_hours):
    try:
        seconds = int(round(float(total_hours) * 3600))
    except Exception:
        seconds = 0
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _v180b_safe_work_hours_total_hms(df):
    """Return total work hours as HH:MM:SS without pandas mixed-type sum."""
    try:
        if df is None or getattr(df, "empty", True) or "work_hours" not in getattr(df, "columns", []):
            return "00:00:00"
        total = 0.0
        for value in df["work_hours"].tolist():
            total += _v180b_parse_work_hours_to_decimal_hours(value)
        return _v180b_decimal_hours_to_hms(total)
    except Exception:
        return "00:00:00"
# === V180B_HISTORY_TOTAL_TIME_TYPE_FIX_END ===
'''


def _insert_helper(text: str) -> str:
    if MARKER in text:
        return text
    # Prefer to insert after imports; otherwise insert at top.
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:200]):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from ") or not stripped:
            insert_at = i + 1
            continue
        # Keep module constants/comments near top; break at first code after imports.
        if insert_at > 0:
            break
    return "\n".join(lines[:insert_at]) + "\n" + HELPER.strip() + "\n" + "\n".join(lines[insert_at:]) + "\n"


def _replace_metric(text: str) -> str:
    # Exact older expression from the Streamlit traceback.
    old_expr = "hours_to_hms(df['work_hours'].sum()) if not df.empty and 'work_hours' in df.columns else \"00:00:00\""
    if old_expr in text:
        text = text.replace(old_expr, "_v180b_safe_work_hours_total_hms(df)")

    # Common variant with double quotes.
    old_expr2 = 'hours_to_hms(df["work_hours"].sum()) if not df.empty and "work_hours" in df.columns else "00:00:00"'
    if old_expr2 in text:
        text = text.replace(old_expr2, "_v180b_safe_work_hours_total_hms(df)")

    # Generic replacement inside metric call if formatting is slightly different.
    pattern = re.compile(
        r"hours_to_hms\(\s*df\s*\[\s*(['\"])work_hours\1\s*\]\s*\.sum\(\s*\)\s*\)\s*"
        r"if\s+not\s+df\.empty\s+and\s+(['\"])work_hours\2\s+in\s+df\.columns\s+else\s+(['\"])00:00:00\3"
    )
    text = pattern.sub("_v180b_safe_work_hours_total_hms(df)", text)
    return text


def main() -> int:
    if not PAGE.exists():
        print(f"找不到檔案：{PAGE}")
        return 1
    original = PAGE.read_text(encoding="utf-8")
    patched = _insert_helper(original)
    patched = _replace_metric(patched)

    if patched == original:
        if "df['work_hours'].sum()" not in original and 'df["work_hours"].sum()' not in original:
            print("V180B：未找到舊版混合型別 sum 寫法，可能已修正。")
            return 0
        print("V180B：找到 df['work_hours'].sum()，但未能自動替換，請人工檢查。")
        return 2

    backup = PAGE.with_suffix(PAGE.suffix + ".v180b.bak")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    PAGE.write_text(patched, encoding="utf-8")
    print("V180B：已修正 02 歷史紀錄總工時 mixed-type sum TypeError。")
    print(f"備份：{backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
