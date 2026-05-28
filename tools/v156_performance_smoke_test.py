# -*- coding: utf-8 -*-
"""V156 performance smoke test.

This script is intentionally read-only. It imports the optimized services and prints
basic timings for repeated reads. It does not modify time records, permissions,
logs, or authority files.
"""
from __future__ import annotations

import time


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def main() -> int:
    print("V156 performance smoke test start")

    t = time.perf_counter()
    from services.permanent_authority_service import df_from_table, load_authority  # noqa
    print(f"import permanent_authority_service: {_ms(t)} ms")

    for module_key, table in [
        ("01_time_records", "time_records"),
        ("02_history", "time_records"),
        ("03_work_orders", "work_orders"),
        ("04_employees", "employees"),
        ("10_permissions", "auth_users"),
    ]:
        t1 = time.perf_counter()
        try:
            df1 = df_from_table(module_key, table)
            n1 = len(df1) if hasattr(df1, "__len__") else 0
            first = _ms(t1)
            t2 = time.perf_counter()
            df2 = df_from_table(module_key, table)
            n2 = len(df2) if hasattr(df2, "__len__") else 0
            second = _ms(t2)
            print(f"{module_key}/{table}: rows={n1}/{n2}, first={first} ms, cached={second} ms")
        except Exception as exc:
            print(f"{module_key}/{table}: skipped ({exc})")

    t = time.perf_counter()
    try:
        from services.permission_service import get_users, get_account_permissions
        u1 = get_users(); p1 = get_account_permissions()
        first = _ms(t)
        t2 = time.perf_counter(); u2 = get_users(); p2 = get_account_permissions(); second = _ms(t2)
        print(f"permissions: users={len(u1)}/{len(u2)}, perms={len(p1)}/{len(p2)}, first={first} ms, cached={second} ms")
    except Exception as exc:
        print(f"permissions: skipped ({exc})")

    print("V156 performance smoke test done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
