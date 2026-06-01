# V300.15 Authority Read/Write Chain Diagnostic Package

## Purpose

This package diagnoses authority-file read/write mismatch for these modules:

- 06. LOG查詢
- 10. 權限管理
- 11. 登入紀錄
- 13. 系統設定

It does **not** modify 01/02 logic, 01/02 display, 01/02 delete/sync, permissions data, system setting data, login records, or log records.

## Files included

- `services/authority_trace_service.py`
- `tools/v30015_authority_trace.py`
- `V300_15_README.md`

## How to run

From project root:

```bash
python tools/v30015_authority_trace.py
```

The command creates:

- `data/permanent_store/authority_trace/v30015_latest_snapshot.json`
- `data/permanent_store/authority_trace/V300_15_AUTHORITY_TRACE_REPORT.md`

## What it checks

For each scoped module, it reports:

- expected authority directory
- expected records/settings/tombstone files
- file existence and row/key counts
- legacy candidate paths that may still overwrite authority after reboot
- warnings when authority files are missing or legacy sources still exist

## Important

This is a diagnostic package only. It is intentionally additive and low-risk. Use its output before V300.16 changes any production read/write behavior.
