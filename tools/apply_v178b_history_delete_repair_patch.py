# -*- coding: utf-8 -*-
"""Apply V178B 02 History strict delete repair patch.

Safe patch:
- no CSS/theme/rendering changes;
- no table layout changes;
- patches backend delete wrapper and makes 02 page checkbox id extraction robust;
- idempotent and backs up touched files.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
MARKER = "# ======================= V178B HISTORY DELETE STRICT REPAIR ======================="

BLOCK = r'''
# ======================= V178B HISTORY DELETE STRICT REPAIR =======================
# Backend-only repair for 02 History delete not taking effect.
# - 02_history is the authority for history display;
# - deletion writes tombstones and removes the row from 02_history, 01_time_records, and SQLite cache;
# - no CSS/theme/page rendering changes.
try:
    from services import history_delete_repair_service as _v178b_history_delete
except Exception:  # pragma: no cover
    _v178b_history_delete = None  # type: ignore

try:
    _v178b_prev_delete_time_records = delete_time_records
except Exception:
    _v178b_prev_delete_time_records = None


def delete_time_records(record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:  # type: ignore[override]
    if _v178b_history_delete is None:
        return int(_v178b_prev_delete_time_records(record_ids, reason=reason) or 0) if callable(_v178b_prev_delete_time_records) else 0
    try:
        result = _v178b_history_delete.delete_history_records_strict(
            record_ids,
            reason=reason,
            previous_delete_callable=_v178b_prev_delete_time_records if callable(_v178b_prev_delete_time_records) else None,
        )
        return int((result or {}).get("deleted_count") or 0)
    except Exception as exc:
        try:
            write_log("V178B_DELETE_ERROR", f"V178B 嚴格刪除失敗，回退原刪除流程：{exc}", "time_records", level="ERROR")
        except Exception:
            pass
        return int(_v178b_prev_delete_time_records(record_ids, reason=reason) or 0) if callable(_v178b_prev_delete_time_records) else 0


def delete_time_records_v178b_strict(record_ids: list[int], reason: str = "02 歷史紀錄嚴格刪除", editor_df=None) -> dict:  # type: ignore[override]
    if _v178b_history_delete is None:
        n = delete_time_records(record_ids, reason=reason)
        return {"ok": bool(n), "deleted_count": int(n or 0), "ids": record_ids or []}
    return _v178b_history_delete.delete_history_records_strict(
        record_ids,
        reason=reason,
        editor_df=editor_df,
        previous_delete_callable=_v178b_prev_delete_time_records if callable(_v178b_prev_delete_time_records) else None,
    )
# ===================== END V178B HISTORY DELETE STRICT REPAIR =====================
'''


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak_v178b_{STAMP}"))


def append_once(path: Path, marker: str, block: str) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in text:
        return False
    backup(path)
    path.write_text(text.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")
    return True


def find_history_pages() -> list[Path]:
    pages = ROOT / "pages"
    if not pages.exists():
        return []
    out = []
    for p in pages.glob("02_02*.py"):
        out.append(p)
    return out


def patch_page(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False
    original = text

    # 1) Make the local _checked_ids helper robust for ID / ID localized labels.
    old = '''                def _checked_ids(frame: pd.DataFrame, col: str) -> list[int]:\n                    if frame is None or frame.empty or col not in frame.columns or "id" not in frame.columns:\n                        return []\n                    try:\n                        mask = frame[col].map(lambda v: str(v).strip().lower() in {"true", "1", "yes", "y", "on", "勾選", "是"} if not isinstance(v, bool) else v)\n                        return [int(x) for x in frame.loc[mask, "id"].dropna().tolist()]\n                    except Exception:\n                        return []\n'''
    new = '''                def _checked_ids(frame: pd.DataFrame, col: str) -> list[int]:\n                    try:\n                        from services.history_delete_repair_service import checked_ids_from_editor\n                        got = checked_ids_from_editor(frame, col)\n                        if got:\n                            return got\n                    except Exception:\n                        pass\n                    if frame is None or frame.empty or col not in frame.columns:\n                        return []\n                    id_col = "id" if "id" in frame.columns else ("ID / ID" if "ID / ID" in frame.columns else ("ID" if "ID" in frame.columns else None))\n                    if not id_col:\n                        return []\n                    try:\n                        mask = frame[col].map(lambda v: str(v).strip().lower() in {"true", "1", "yes", "y", "on", "勾選", "是"} if not isinstance(v, bool) else v)\n                        return [int(float(str(x))) for x in frame.loc[mask, id_col].dropna().tolist()]\n                    except Exception:\n                        return []\n'''
    if old in text:
        text = text.replace(old, new, 1)
        changed = True

    # 2) Use strict V178B delete helper, but keep old delete_time_records fallback.
    old2 = '''                        count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")\n                        st.session_state[delete_select_key] = []\n'''
    new2 = '''                        try:\n                            from services.time_record_service import delete_time_records_v178b_strict\n                            _v178b_delete_result = delete_time_records_v178b_strict(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除", editor_df=edited)\n                            count = int((_v178b_delete_result or {}).get("deleted_count") or 0)\n                        except Exception:\n                            count = delete_time_records(delete_ids, reason="02 歷史紀錄啟動編輯後整列刪除")\n                        st.session_state[delete_select_key] = []\n'''
    if old2 in text:
        text = text.replace(old2, new2, 1)
        changed = True

    if changed and text != original:
        backup(path)
        path.write_text(text, encoding="utf-8")
    return changed


def main() -> int:
    changed = []
    tr = ROOT / "services" / "time_record_service.py"
    if append_once(tr, MARKER, BLOCK):
        changed.append(str(tr.relative_to(ROOT)))
    for page in find_history_pages():
        if patch_page(page):
            changed.append(str(page.relative_to(ROOT)))
    print("V178B history delete repair patch applied.")
    if changed:
        print("Modified:")
        for p in changed:
            print(" -", p)
    else:
        print("No changes needed; V178B patch already present or target patterns not found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
