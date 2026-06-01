# -*- coding: utf-8 -*-
"""Manual bootstrap/audit utility for V300.13 module authority files.

This tool is safe by default: it creates missing files only and never overwrites
existing records.json files unless --overwrite is explicitly provided.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.module_authority_registry_service import (  # noqa: E402
    DEFAULT_BASE_DIR,
    audit_module_authorities,
    ensure_module_authorities,
    render_authority_inventory_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="V300.13 module authority bootstrap and audit")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR), help="authority base directory")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing authority files (dangerous; default false)")
    parser.add_argument("--audit-only", action="store_true", help="only audit, do not create missing files")
    parser.add_argument("--report", default="V300_13_AUTHORITY_INVENTORY_REPORT_RUNTIME.md", help="markdown report output path")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    if not args.audit_only:
        result = ensure_module_authorities(base_dir=base_dir, overwrite=args.overwrite)
        print("Bootstrap result:")
        print(f"  ok={result['ok']}")
        print(f"  created={result['created_count']}")
        print(f"  preserved={result['preserved_count']}")
        print(f"  errors={result['error_count']}")
        if result.get("errors"):
            for err in result["errors"]:
                print(f"  ERROR {err['path']}: {err['error']}")
    audit = audit_module_authorities(base_dir=base_dir)
    report_md = render_authority_inventory_markdown(audit)
    report_path = Path(args.report)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"Report written: {report_path}")
    print(f"Audit ok={audit['ok']} missing={audit['missing_required_count']} invalid_json={audit['invalid_json_count']}")
    return 0 if audit.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
