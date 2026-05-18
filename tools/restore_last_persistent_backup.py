# -*- coding: utf-8 -*-
from pathlib import Path
import sys, json, argparse
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from services.persistence_guard_service import restore_latest_persistent_backup

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-secrets", action="store_true", help="Also restore .streamlit/secrets.toml and config.toml")
    args = parser.parse_args()
    result = restore_latest_persistent_backup(include_secrets=args.include_secrets)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)
