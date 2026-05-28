# -*- coding: utf-8 -*-
"""V159 page route hygiene utilities.

This service detects duplicate Streamlit page files whose names contain old
"#Uxxxx" unicode-escape text.  Duplicate pages slow Streamlit page discovery and
can cause an old page implementation to appear beside the corrected Chinese-name
page.  The cleanup is conservative: it only removes a mojibake page when the
normal decoded page already exists.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import hashlib
import re
from typing import Iterable

MOJIBAKE_PATTERN = re.compile(r"#U([0-9A-Fa-f]{4})")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pages_dir() -> Path:
    return project_root() / "pages"


def _decode_mojibake_name(name: str) -> str:
    def repl(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)
    return MOJIBAKE_PATTERN.sub(repl, name)


def _file_sha1(path: Path) -> str:
    try:
        h = hashlib.sha1()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _safe_stat(path: Path) -> dict:
    try:
        st = path.stat()
        return {
            "size": int(st.st_size),
            "modified_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "sha1": _file_sha1(path),
        }
    except Exception:
        return {"size": 0, "modified_at": "", "sha1": ""}


@dataclass
class PageHygieneItem:
    file_name: str
    decoded_name: str
    file_path: str
    normal_counterpart: str
    has_normal_counterpart: bool
    safe_to_remove: bool
    size: int
    modified_at: str
    sha1: str
    reason: str


def find_mojibake_pages(root: Path | None = None) -> list[PageHygieneItem]:
    pdir = Path(root) if root is not None else pages_dir()
    if not pdir.exists():
        return []
    items: list[PageHygieneItem] = []
    for path in sorted(pdir.glob("*.py")):
        name = path.name
        if not MOJIBAKE_PATTERN.search(name):
            continue
        decoded = _decode_mojibake_name(name)
        counterpart = pdir / decoded
        has_counterpart = counterpart.exists() and counterpart.resolve() != path.resolve()
        stat = _safe_stat(path)
        # Only remove if the exact decoded Chinese-name page exists.  If a module
        # still only has an old #U filename, it must be kept until a normal page is
        # supplied, otherwise Streamlit would lose that module.
        safe = bool(has_counterpart)
        reason = (
            "normal counterpart exists; duplicate old mojibake route"
            if safe else
            "normal counterpart missing; keep file to avoid removing the module"
        )
        items.append(PageHygieneItem(
            file_name=name,
            decoded_name=decoded,
            file_path=str(path.relative_to(project_root()) if path.is_absolute() else path),
            normal_counterpart=str(counterpart.relative_to(project_root()) if counterpart.exists() else Path("pages") / decoded),
            has_normal_counterpart=bool(has_counterpart),
            safe_to_remove=safe,
            size=stat["size"],
            modified_at=stat["modified_at"],
            sha1=stat["sha1"],
            reason=reason,
        ))
    return items


def page_hygiene_rows(items: Iterable[PageHygieneItem] | None = None) -> list[dict]:
    rows: list[dict] = []
    for item in list(items) if items is not None else find_mojibake_pages():
        d = asdict(item)
        d["建議 / Recommendation"] = "可刪除舊亂碼頁" if item.safe_to_remove else "暫時保留"
        rows.append(d)
    return rows


def collect_page_hygiene_status() -> dict:
    pdir = pages_dir()
    py_files = sorted(pdir.glob("*.py")) if pdir.exists() else []
    mojibake = find_mojibake_pages(pdir)
    safe = [x for x in mojibake if x.safe_to_remove]
    keep = [x for x in mojibake if not x.safe_to_remove]
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pages_dir": str(pdir),
        "total_py_pages": len(py_files),
        "mojibake_pages": len(mojibake),
        "safe_to_remove": len(safe),
        "must_keep": len(keep),
        "status": "WARN" if safe else ("INFO" if keep else "OK"),
        "items": page_hygiene_rows(mojibake),
    }


def cleanup_duplicate_mojibake_pages(*, apply: bool = False) -> dict:
    """Remove only safe duplicate #U pages when apply=True.

    The dry-run result is safe for UI display.  This function never removes a
    mojibake page unless the decoded Chinese-name counterpart exists.
    """
    status = collect_page_hygiene_status()
    removed: list[str] = []
    errors: list[dict] = []
    for row in status.get("items", []):
        if not row.get("safe_to_remove"):
            continue
        rel = str(row.get("file_path") or "")
        path = project_root() / rel
        if apply:
            try:
                if path.exists():
                    path.unlink()
                    removed.append(rel)
            except Exception as exc:
                errors.append({"file": rel, "error": str(exc)})
        else:
            removed.append(rel)
    return {
        "ok": not errors,
        "dry_run": not bool(apply),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "planned_or_removed": removed,
        "removed_count": len(removed) if apply else 0,
        "planned_count": len(removed) if not apply else len(removed),
        "errors": errors,
        "before": status,
        "after": collect_page_hygiene_status() if apply else None,
    }
