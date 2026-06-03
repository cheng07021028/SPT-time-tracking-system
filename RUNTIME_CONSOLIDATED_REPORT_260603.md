# SPT Runtime Consolidated Build Report - 2026-06-03

## Build goal

This package is the next-step runtime consolidation build after `SPT-time-tracking-neon-full-ui-retained-260603.zip`.

Goals:

- Keep the existing Streamlit `app.py` entry point.
- Keep the existing `pages/` UI structure and V2.84-style theme/CSS files.
- Do not restore `streamlit_app.py`.
- Remove the heaviest old runtime patch stack from 01/02 time-record operations.
- Make 03/04 master-data writes go through DB/Neon service instead of local JSON/GitHub authority.
- Keep local/GitHub files as manual backup/export tools only, not runtime authority.
- Preserve function names imported by existing pages so the UI does not need a full redesign.

## Main changes in this build

### 1. Rewritten runtime service for 01/02

`services/time_record_service.py` was replaced with a clean runtime service.

Old state:

- About 32k lines.
- More than 50 duplicate definitions of core functions such as `start_work`, `finish_work`, `load_records`, `today_records`, and `delete_time_records`.
- High risk of hidden override order bugs, slow page loads, delete resurrection, and button actions being swallowed by old reconciliation layers.

New state:

- Single implementation for each exported function.
- Uses `services.db_service` only.
- Supports start, finish, pause/off-duty/complete, today records, history records, import, save, recalculation, and soft delete.
- Supports parallel/same-time finish averaging when `finish_parallel_group=True`.
- Deletes are soft deletes with `deleted_at`, `deleted_by`, and `delete_reason`.
- No local JSON/GitHub write-through inside 01/02 button hot path.

### 2. Rewritten runtime service for 03/04

`services/crud_table_service.py` was replaced with a DB-backed service for:

- `load_work_orders`
- `save_work_orders`
- `load_employees`
- `save_employees`

New behavior:

- Runtime reads/writes go through `services.db_service`.
- Upsert by natural keys: `work_order` for work orders and `employee_id` for employees.
- Soft delete for checked rows.
- Existing UI function names are preserved.
- Local JSON/GitHub is not used as a runtime authority.

### 3. Rewritten master-data fast service

`services/master_data_service.py` now uses `crud_table_service` and only keeps a short in-process cache for 01 dropdowns.

### 4. Rewritten delete unifier

`services/time_record_delete_unifier_service.py` now routes deletion to `time_record_service.delete_time_records`.

Old local tombstone/authority-file writes are removed from runtime delete actions.

### 5. Page compatibility patches

`pages/03_03. 製令管理.py` and `pages/04_04. 人員名單.py` were patched so checked delete rows are passed to the new save services instead of being silently dropped before save.

`pages/03_03. 製令管理.py` OneDrive mapped-sync helper now writes through `save_work_orders` rather than direct SQLite/local authority sync.

## Files changed

- `services/time_record_service.py`
- `services/crud_table_service.py`
- `services/master_data_service.py`
- `services/time_record_delete_unifier_service.py`
- `pages/03_03. 製令管理.py`
- `pages/04_04. 人員名單.py`

## Tests performed

Commands executed:

```bash
python -m compileall -q app.py pages services spt_core scripts tests
pytest -q
python scripts/smoke_test.py
python scripts/validate_v32.py
PYTHONPATH=. python /tmp/test_v63_runtime.py
```

Results:

- `compileall`: passed
- `pytest`: 7 passed
- `smoke_test`: passed
- `validate_v32`: passed
- V63 runtime service regression: passed
- Modified service import/function checks: passed

The V63 runtime regression covered:

- Create/update work order
- Create/update employee
- Start work
- Query active work
- Finish work
- Load history
- Soft delete time record
- Confirm soft-deleted row is no longer visible

## What this build intentionally does not change

- CSS/theme visual styling is not changed.
- Page layout is not rebuilt.
- `app.py` remains the only entry point.
- `pages/` remains available to preserve the current multi-page UI.
- Backup/diagnostic modules remain present, but should be treated as manual tools, not data authority.

## Remaining known work after this build

This package consolidates the highest-risk runtime services first. The remaining lower-priority consolidation areas are:

1. `services/security_service.py` / `services/permission_service.py`: eventually map old `auth_*` tables to clean `users/account_permissions/login_events` tables.
2. `services/system_settings_service.py`: keep 13 settings fully in Neon tables and avoid any settings fallback from local JSON.
3. 06/11/99: add more explicit query limits and page-level profiling for production Neon logs.
4. 09/12/14/98: keep as backup/diagnostic only; do not allow them to become runtime authority again.

## Deployment note

Streamlit Cloud main file remains:

```text
app.py
```

Neon/PostgreSQL remains the expected production authority. SQLite fallback is only for local tests.
