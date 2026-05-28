# -*- coding: utf-8 -*-
"""V164 time record repository facade.

Important: this facade delegates all business writes to the existing
services.time_record_service.  It does not bypass daily close locks, tombstones,
event journal, row shard, active-work final-state checks, or 01/02 sync logic.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .base_repository import RepositoryHealth
from .json_authority_repository import AuthorityRepository
from .sqlite_repository import SQLiteRepository


class TimeRecordRepository:
    name = "time_records"

    def __init__(self) -> None:
        self.sqlite = SQLiteRepository("time_records", name="time_records_sqlite")
        self.authority_01 = AuthorityRepository("01_time_records", "time_records", name="01_time_records_authority")
        self.authority_02 = AuthorityRepository("02_history", "time_records", name="02_history_authority")

    @staticmethod
    def _svc():
        from services import time_record_service

        return time_record_service

    def load_records(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        employee_id: str | None = None,
        work_order: str | None = None,
    ) -> pd.DataFrame:
        return self._svc().load_records(start_date=start_date, end_date=end_date, employee_id=employee_id, work_order=work_order)

    def today_records(self, *, include_finished: bool = True, unfinished_only: bool = False) -> pd.DataFrame:
        return self._svc().today_records(include_finished=include_finished, unfinished_only=unfinished_only)

    def get_active_records(
        self,
        employee_id: str | None = None,
        process_name: str | None = None,
        start_date: str | None = None,
        employee_name: str | None = None,
    ) -> pd.DataFrame:
        return self._svc().get_active_records(
            employee_id=employee_id,
            process_name=process_name,
            start_date=start_date,
            employee_name=employee_name,
        )

    def start_work(self, employee: dict[str, Any], work_order: dict[str, Any], process_name: str, remark: str = "", auto_pause_old: bool = True) -> int:
        return int(self._svc().start_work(employee, work_order, process_name, remark=remark, auto_pause_old=auto_pause_old) or 0)

    def finish_work(self, record_id: int, end_action: str, remark: str = "", finish_parallel_group: bool = True) -> int:
        return int(self._svc().finish_work(record_id, end_action, remark=remark, finish_parallel_group=finish_parallel_group) or 0)

    def save_time_records(self, df: pd.DataFrame, recalc_edited_timestamps: bool = False) -> int:
        return int(self._svc().save_time_records(df, recalc_edited_timestamps=recalc_edited_timestamps) or 0)

    def delete_time_records(self, record_ids: list[int], reason: str = "管理員刪除工時紀錄") -> int:
        return int(self._svc().delete_time_records(record_ids, reason=reason) or 0)

    def recalculate_time_records(self, record_ids: list[int] | None = None) -> int:
        return int(self._svc().recalculate_time_records(record_ids) or 0)

    def import_time_records(self, df: pd.DataFrame, recalc: bool = True, source: str = "repository_import") -> dict[str, Any]:
        result = self._svc().import_time_records(df, recalc=recalc, source=source)
        return result if isinstance(result, dict) else {"ok": True, "result": result}

    def health_check(self) -> RepositoryHealth:
        parts = [self.sqlite.health_check(), self.authority_01.health_check(), self.authority_02.health_check()]
        ok = any(p.ok for p in parts)
        total = sum(int(p.row_count or 0) for p in parts)
        return RepositoryHealth(
            name=self.name,
            ok=ok,
            source="facade",
            message="OK" if ok else "No time record source is available",
            row_count=total,
            details={p.name: p.as_dict() for p in parts},
        )
