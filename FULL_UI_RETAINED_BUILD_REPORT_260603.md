# SPT-time-tracking-system full UI retained Neon rebuild report 260603

## Build purpose

This package keeps the existing Streamlit UI/pages/services as the function and layout source, while removing the dual-entry conflict and adding the missing clean-schema migration path.

## What changed

1. Formal entry point is now `app.py`.
   - The former full UI home page from `streamlit_app.py` has been moved into `app.py`.
   - `streamlit_app.py` has been removed.

2. Existing UI/function pages are retained.
   - `pages/` is kept because Streamlit multipage UI depends on it.
   - Page filenames were converted from `#Uxxxx` mojibake to normal UTF-8 Chinese filenames.
   - 17 pages are present: 01-15, 98, 99.

3. V2.84-style UI is retained.
   - `services/theme_service.py`, `services/ui_size_service.py`, `services/table_ui_service.py`, and original page layout services are kept.
   - The old clean skeleton `app.py` was not used as the UI source.

4. Neon/PostgreSQL authority compatibility was improved.
   - `requirements.txt` now uses `psycopg[binary,pool]>=3.2` for `psycopg_pool`.
   - `spt_core/schema.py` now includes `module_authority` and its indexes.
   - Added `scripts/migrate_legacy_to_clean.py` for legacy-table/permanent-store to clean schema migration.
   - `services/db_service.py` now creates/adds `spt_module_authority.kind` and `updated_by` compatibility columns.
   - `services/neon_authority_service.py` now normalizes old `spt_module_authority` rows and uses update-then-insert instead of relying on `ON CONFLICT`, preventing failures when old tables lack a unique `(module_key, kind)` constraint.

5. 08 compatibility fix.
   - `services/time_record_service.py` now exposes `load_daily_record_summary_sql()` as a wrapper to the optimized implementation in `large_table_query_service`.

6. Hot-path cleanup.
   - `app.py` no longer bootstraps local `permanent_store` on home/login render.
   - Backup/restore and heavy maintenance stay in manual modules such as 09/14/15/99.

7. Cleanup.
   - Removed `streamlit_app.py`.
   - Removed `.pytest_cache`, `__pycache__`, `*.pyc`.
   - Removed duplicate root `logo/` folder.
   - Removed generated local DB files from the package.
   - Verified no `#Uxxxx` filenames remain.

## Tests run

- `python -m compileall app.py pages services spt_core scripts tests`
- `pytest -q` -> 7 passed
- `python scripts/smoke_test.py` -> passed
- `python scripts/validate_v32.py` -> passed
- Static page/service symbol scan -> passed
- Cleanup/name check -> passed
- Legacy migration dry-run on uploaded ZIP -> planned employees 90, work_orders 599, system_settings 1

## Deployment note

Set Streamlit Cloud main file to:

```text
app.py
```

Do not point Streamlit Cloud to `streamlit_app.py`; that file is intentionally removed.

## Migration commands

Same Neon database legacy tables to clean schema:

```bash
python scripts/migrate_legacy_to_clean.py --same-database
```

Old ZIP/permanent_store to clean schema dry run:

```bash
python scripts/migrate_legacy_to_clean.py --legacy-path "舊專案.zip" --skip-same-database --dry-run
```

Old ZIP/permanent_store import:

```bash
python scripts/migrate_legacy_to_clean.py --legacy-path "舊專案.zip" --skip-same-database
```

## Important limitation

This version intentionally retains the original full UI services to avoid deleting existing functionality. It does not replace every old service with a brand-new clean implementation in one pass, because doing so would risk losing functions, buttons, and page-specific behavior. The immediate conflict fixes are entry unification, schema compatibility, migration path, hot-path cleanup, and filename cleanup.
