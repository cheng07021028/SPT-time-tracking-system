# -*- coding: utf-8 -*-
"""Clean Streamlit page filenames that were accidentally saved as #Uxxxx text.

Use in GitHub Actions or locally from the repository root:
    python tools/cleanup_mojibake_pages.py

Behavior:
- pages/02_02. #U6b77#U53f2#U7d00#U9304.py -> pages/02_02. 歷史紀錄.py
- If the decoded Chinese file already exists, the #Uxxxx duplicate is deleted.
- __pycache__ files under pages/ are removed because they should not be tracked.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

U_PATTERN = re.compile(r"#U([0-9a-fA-F]{4,6})")
BAD_MARKERS = ("#U", "�", "╜", "τ", "Φ")


def decode_hash_u_name(name: str) -> str:
    """Decode literal #Uxxxx groups in a filename to real Unicode characters."""

    def repl(match: re.Match[str]) -> str:
        code = int(match.group(1), 16)
        try:
            return chr(code)
        except ValueError:
            return match.group(0)

    return U_PATTERN.sub(repl, name)


def has_mojibake_marker(path: Path) -> bool:
    return any(marker in path.name for marker in BAD_MARKERS)


def remove_pycache(pages_dir: Path) -> list[str]:
    removed: list[str] = []
    for cache_dir in pages_dir.rglob("__pycache__"):
        if cache_dir.is_dir():
            removed.append(str(cache_dir.relative_to(pages_dir.parent)))
            shutil.rmtree(cache_dir, ignore_errors=True)
    return removed


def clean_pages(root: Path, dry_run: bool = False) -> int:
    pages_dir = root / "pages"
    if not pages_dir.exists():
        print(f"ERROR: pages directory not found: {pages_dir}", file=sys.stderr)
        return 2

    actions: list[str] = []
    errors: list[str] = []

    # Remove cache first. Streamlit/Python can recreate it; Git should not keep it.
    removed_cache = remove_pycache(pages_dir) if not dry_run else [str(p.relative_to(root)) for p in pages_dir.rglob("__pycache__")]
    for item in removed_cache:
        actions.append(f"REMOVE_CACHE {item}")

    candidates = sorted([p for p in pages_dir.glob("*.py") if has_mojibake_marker(p)], key=lambda p: p.name)

    for src in candidates:
        decoded_name = decode_hash_u_name(src.name)

        # If no valid decoding is possible, skip instead of deleting business pages blindly.
        if decoded_name == src.name and "#U" in src.name:
            errors.append(f"SKIP_UNDECODED {src.relative_to(root)}")
            continue

        dst = src.with_name(decoded_name)

        if dst == src:
            continue

        if dst.exists():
            # Keep the proper Chinese filename and remove the #U duplicate.
            actions.append(f"DELETE_DUPLICATE {src.relative_to(root)} -> keep {dst.relative_to(root)}")
            if not dry_run:
                src.unlink()
            continue

        actions.append(f"RENAME {src.relative_to(root)} -> {dst.relative_to(root)}")
        if not dry_run:
            src.rename(dst)

    if actions:
        print("Mojibake cleanup actions:")
        for line in actions:
            print(f"- {line}")
    else:
        print("No mojibake page filenames found.")

    if errors:
        print("Warnings:", file=sys.stderr)
        for line in errors:
            print(f"- {line}", file=sys.stderr)

    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing files")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    return clean_pages(root=root, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
