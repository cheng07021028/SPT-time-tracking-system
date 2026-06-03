# -*- coding: utf-8 -*-
"""V166E duplicate row guards for editable master tables.

The functions here only remove exact / key-identical duplicate rows before a
save operation.  They never renumber IDs, never delete tombstones, and never
rewrite 01/02 with partial page data.
"""
from __future__ import annotations

from typing import Iterable, Sequence
import pandas as pd


def _blank(v: object) -> bool:
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v).strip().lower() in {"", "none", "nan", "nat", "null", "<na>"}


def _norm(v: object) -> str:
    if _blank(v):
        return ""
    return str(v).strip()


def drop_duplicate_by_keys(df: pd.DataFrame, keys: Sequence[str], *, keep: str = "last", ignore_blank_key: bool = True) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    present = [k for k in keys if k in out.columns]
    if not present:
        return out
    marker = out[present].astype(str).apply(lambda s: "|".join(_norm(x) for x in s), axis=1)
    if ignore_blank_key:
        mask_key = marker.astype(str).str.replace("|", "", regex=False).str.strip() != ""
        deduped = pd.concat([
            out.loc[~mask_key],
            out.loc[mask_key].assign(_v166e_dedupe_key=marker.loc[mask_key]).drop_duplicates("_v166e_dedupe_key", keep=keep).drop(columns=["_v166e_dedupe_key"]),
        ], ignore_index=True)
        return deduped.reindex(columns=out.columns)
    return out.assign(_v166e_dedupe_key=marker).drop_duplicates("_v166e_dedupe_key", keep=keep).drop(columns=["_v166e_dedupe_key"]).reindex(columns=out.columns)


def drop_exact_duplicate_rows(df: pd.DataFrame, *, ignore_columns: Iterable[str] = ()) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    cols = [c for c in out.columns if c not in set(ignore_columns or [])]
    if not cols:
        return out
    return out.drop_duplicates(subset=cols, keep="last").reset_index(drop=True)


def dedupe_work_orders_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    # Completely blank rows are editor placeholders; keep at most one before save.
    out = drop_duplicate_by_keys(out, ["work_order"], keep="last", ignore_blank_key=True)
    out = drop_exact_duplicate_rows(out, ignore_columns=["id"])
    return out.reset_index(drop=True)


def dedupe_employees_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = drop_duplicate_by_keys(out, ["employee_id"], keep="last", ignore_blank_key=True)
    out = drop_exact_duplicate_rows(out, ignore_columns=["id"])
    return out.reset_index(drop=True)


def dedupe_time_records_exact(df: pd.DataFrame) -> pd.DataFrame:
    """Remove only exact duplicate time rows; do not collapse legitimate status variants."""
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if out.empty:
        return out
    ignore_cols = [c for c in ["id", "ID", "updated_at", "更新時間 / Updated At"] if c in out.columns]
    return drop_exact_duplicate_rows(out, ignore_columns=ignore_cols).reset_index(drop=True)
