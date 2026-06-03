# Validation Report

Date: 2026-06-02
Project: 超慧科技製造部_工時紀錄 / SPT-time-tracking-system
Package: SPT-Neon-Core-v1.0

## Checks Performed

- `python -m compileall .` passed.
- `pytest -q` passed: 7 tests.
- `python scripts/smoke_test.py` passed.
- Checked filenames: no `#Uxxxx` mojibake filenames found.
- Checked service boundary: `spt_core/services/*.py` does not import Streamlit.

## Tested Core Behaviors

- Employee creation with unique employee ID.
- Work order creation with unique work order number.
- Start work transaction.
- Finish work transaction.
- Group average with 3-minute bucket.
- Soft delete and hidden active query.
- Operation LOG writing.
- Permission blocking for operator-level restricted action.

## Important Notes

- Production should use Neon PostgreSQL / PostgreSQL through `DATABASE_URL`.
- Local SQLite mode is provided only for demo and automated tests.
- First-run default admin password must be changed before production use.
