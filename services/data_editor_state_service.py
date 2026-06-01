# -*- coding: utf-8 -*-
"""Safe Streamlit data_editor state helpers.

Purpose:
- Keep unsaved data_editor changes stable across Streamlit reruns.
- Read widget delta state (edited_rows / added_rows / deleted_rows) when a page
  button is placed above the editor and would otherwise run before the editor's
  returned DataFrame is copied back to the page draft.

This module only transforms in-memory DataFrames. It does not save business data,
change permissions, or touch permanent storage.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st


def _is_empty_state(state: Any) -> bool:
    if not isinstance(state, dict):
        return True
    return not bool(state.get("edited_rows") or state.get("added_rows") or state.get("deleted_rows"))


def _as_int_index(value: Any) -> int | None:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        return int(float(text))
    except Exception:
        return None


def apply_data_editor_widget_state(source_df: pd.DataFrame, widget_state: Any) -> pd.DataFrame:
    """Apply Streamlit data_editor delta state to a DataFrame.

    Streamlit keeps the widget delta in st.session_state[editor_key] with keys like:
    - edited_rows: {row_index: {column_name: value}}
    - added_rows: [{column_name: value}, ...]
    - deleted_rows: [row_index, ...]

    The function is conservative: if no valid widget state exists, it returns a copy
    of source_df. Missing columns are added only when the widget delta explicitly
    references them. This prevents accidental data loss in pages with hidden columns.
    """
    base = source_df.copy() if isinstance(source_df, pd.DataFrame) else pd.DataFrame()
    if _is_empty_state(widget_state):
        return base

    state = dict(widget_state or {})
    out = base.copy().reset_index(drop=True)

    # 1) Apply edited cell values against original row positions.
    edited_rows = state.get("edited_rows") or {}
    if isinstance(edited_rows, dict):
        for raw_idx, changes in edited_rows.items():
            idx = _as_int_index(raw_idx)
            if idx is None or idx < 0 or idx >= len(out) or not isinstance(changes, dict):
                continue
            for col, value in changes.items():
                if col not in out.columns:
                    out[col] = None
                try:
                    out.at[idx, col] = value
                except Exception:
                    pass

    # 2) Delete rows after edits. Drop by original integer positions.
    deleted_rows = state.get("deleted_rows") or []
    delete_positions: set[int] = set()
    if isinstance(deleted_rows, (list, tuple, set)):
        for raw_idx in deleted_rows:
            idx = _as_int_index(raw_idx)
            if idx is not None and 0 <= idx < len(out):
                delete_positions.add(idx)
    if delete_positions:
        keep_mask = [i not in delete_positions for i in range(len(out))]
        out = out.loc[keep_mask].reset_index(drop=True)

    # 3) Append dynamic rows.
    added_rows = state.get("added_rows") or []
    if isinstance(added_rows, list) and added_rows:
        clean_rows: list[dict[str, Any]] = []
        for row in added_rows:
            if not isinstance(row, dict):
                continue
            clean = dict(row)
            if not clean:
                continue
            for col in clean:
                if col not in out.columns:
                    out[col] = None
            # Keep a row only if at least one value is not blank.
            has_value = False
            for value in clean.values():
                try:
                    if pd.isna(value):
                        continue
                except Exception:
                    pass
                if str(value).strip() != "":
                    has_value = True
                    break
            if has_value:
                clean_rows.append(clean)
        if clean_rows:
            add_df = pd.DataFrame(clean_rows)
            for col in out.columns:
                if col not in add_df.columns:
                    add_df[col] = None
            out = pd.concat([out, add_df[out.columns]], ignore_index=True)

    return out.reset_index(drop=True)


def commit_editor_widget_state_to_session(
    *,
    state_key: str,
    editor_key: str,
    to_editor_df: Callable[[pd.DataFrame], pd.DataFrame],
    from_editor_df: Callable[[pd.DataFrame], pd.DataFrame],
    ensure_df: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> bool:
    """Commit data_editor widget delta into a page-owned draft DataFrame.

    Use this before any button above a data_editor mutates the draft, and before
    reading KPI counts from the draft. It prevents checkbox/text edits from being
    overwritten by an older session_state DataFrame.
    """
    try:
        widget_state = st.session_state.get(editor_key)
        if _is_empty_state(widget_state):
            return False
        current = st.session_state.get(state_key, pd.DataFrame())
        if not isinstance(current, pd.DataFrame):
            current = pd.DataFrame()
        editor_base = to_editor_df(current)
        committed_editor = apply_data_editor_widget_state(editor_base, widget_state)
        committed_internal = from_editor_df(committed_editor)
        if ensure_df is not None:
            committed_internal = ensure_df(committed_internal)
        st.session_state[state_key] = committed_internal.copy()
        return True
    except Exception:
        return False


def clear_data_editor_widget_key(editor_key: str) -> None:
    """Remove one Streamlit data_editor widget state key if present."""
    try:
        st.session_state.pop(editor_key, None)
    except Exception:
        pass
