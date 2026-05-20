# -*- coding: utf-8 -*-
"""Unified Streamlit button / editor-state rules for SPT time tracking system.

Purpose
-------
This module centralizes the *rules* for buttons that control editable tables:
edit mode, reload, add row, select-all/clear checkbox columns, and editor-key
rotation.  Page files still need to import and call these helpers; adding this
file alone will not change existing buttons automatically.

Design rules
------------
1. Page buttons should not directly mutate Streamlit widget keys after the
   widget has already been created.
2. Buttons should mutate a page-owned draft DataFrame, then bump an editor
   revision key so st.data_editor gets a new key on the next rerun.
3. Data-editor drafts are stored in st.session_state as pandas DataFrames.
4. The real save action must be handled by each page/service; this file never
   decides business data persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st


DataFrameFactory = Callable[[], pd.DataFrame]


@dataclass(frozen=True)
class EditorBinding:
    """Configuration for one editable table on a page."""

    page_key: str
    draft_key: str
    edit_key: str
    rev_key: str
    base_editor_key: str


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "是", "啟用", "active"}


def bump_revision(rev_key: str, step: int = 1) -> int:
    """Increment a revision counter and return the new value."""
    try:
        current = int(st.session_state.get(rev_key, 0))
    except Exception:
        current = 0
    st.session_state[rev_key] = current + int(step or 1)
    return int(st.session_state[rev_key])


def current_editor_key(binding: EditorBinding) -> str:
    """Return a stable data_editor key that changes after bulk button actions."""
    rev = int(st.session_state.get(binding.rev_key, 0) or 0)
    return f"{binding.base_editor_key}_{rev}"


def get_draft_df(draft_key: str, source_factory: Optional[DataFrameFactory] = None) -> pd.DataFrame:
    """Return a copy of the draft DataFrame, loading it once when missing."""
    obj = st.session_state.get(draft_key)
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if source_factory is not None:
        try:
            df = source_factory()
            if not isinstance(df, pd.DataFrame):
                df = pd.DataFrame()
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()
    st.session_state[draft_key] = df.copy()
    return df.copy()


def set_draft_df(draft_key: str, df: pd.DataFrame, rev_key: Optional[str] = None) -> pd.DataFrame:
    """Store a draft DataFrame and optionally rotate editor revision."""
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()
    st.session_state[draft_key] = df.copy()
    if rev_key:
        bump_revision(rev_key)
    return df.copy()


def set_edit_mode(binding: EditorBinding, enabled: bool, source_factory: Optional[DataFrameFactory] = None, *, reload_on_enable: bool = False) -> None:
    """Set edit mode.

    For Enable Edit, the default is to keep the current on-screen draft instead
    of reloading old SQLite/JSON.  Set reload_on_enable=True only for pages that
    explicitly need a fresh authoritative reload.
    """
    st.session_state[binding.edit_key] = bool(enabled)
    if enabled:
        if reload_on_enable or not isinstance(st.session_state.get(binding.draft_key), pd.DataFrame):
            get_draft_df(binding.draft_key, source_factory)
    else:
        # Lock edit: discard unsaved draft by reloading current authoritative data.
        if source_factory is not None:
            try:
                st.session_state[binding.draft_key] = source_factory().copy()
            except Exception:
                pass
    bump_revision(binding.rev_key)


def reload_draft(binding: EditorBinding, source_factory: DataFrameFactory) -> None:
    """Force reload the draft from authoritative page source."""
    try:
        df = source_factory()
        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame()
    except Exception:
        df = pd.DataFrame()
    set_draft_df(binding.draft_key, df, binding.rev_key)


def add_blank_row(binding: EditorBinding, blank_row: Mapping[str, object], *, at_top: bool = True, source_factory: Optional[DataFrameFactory] = None) -> None:
    """Add one blank row to the editable draft."""
    df = get_draft_df(binding.draft_key, source_factory)
    row_df = pd.DataFrame([dict(blank_row or {})])
    if at_top:
        out = pd.concat([row_df, df], ignore_index=True)
    else:
        out = pd.concat([df, row_df], ignore_index=True)
    set_draft_df(binding.draft_key, out, binding.rev_key)


def ensure_columns(df: pd.DataFrame, columns: Sequence[str], default: object = False) -> pd.DataFrame:
    """Ensure columns exist on a DataFrame."""
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    for col in columns:
        if col not in out.columns:
            out[col] = default
    return out


def set_checkbox_column(binding: EditorBinding, column: str, value: bool, source_factory: Optional[DataFrameFactory] = None) -> None:
    """Set an entire checkbox column to True/False and rotate editor key."""
    df = get_draft_df(binding.draft_key, source_factory)
    if column not in df.columns:
        df.insert(0, column, False)
    df[column] = bool(value)
    set_draft_df(binding.draft_key, df, binding.rev_key)


def set_many_checkbox_columns(binding: EditorBinding, columns: Iterable[str], value: bool, source_factory: Optional[DataFrameFactory] = None) -> None:
    """Set multiple checkbox columns to True/False."""
    df = get_draft_df(binding.draft_key, source_factory)
    for column in columns:
        if column not in df.columns:
            df[column] = False
        df[column] = bool(value)
    set_draft_df(binding.draft_key, df, binding.rev_key)


def clear_widget_state(prefixes: Iterable[str]) -> None:
    """Remove Streamlit widget/session keys by prefix.

    Must be called before the next widget with the same key is created, usually
    from a button callback followed by editor-key rotation.
    """
    prefixes = tuple(str(p) for p in prefixes if str(p))
    if not prefixes:
        return
    for key in list(st.session_state.keys()):
        if any(str(key).startswith(p) for p in prefixes):
            try:
                del st.session_state[key]
            except Exception:
                pass


def copy_edited_to_draft(binding: EditorBinding, edited_df: pd.DataFrame) -> pd.DataFrame:
    """Persist current data_editor output into the draft state."""
    return set_draft_df(binding.draft_key, edited_df if isinstance(edited_df, pd.DataFrame) else pd.DataFrame(), None)


def selected_rows(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Return rows where a checkbox-like column is selected."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return pd.DataFrame(columns=list(df.columns) if isinstance(df, pd.DataFrame) else [])
    mask = df[column].apply(_as_bool)
    return df.loc[mask].copy()


def selected_ids(df: pd.DataFrame, select_column: str, id_column: str = "id") -> list:
    """Return selected record ids from a checkbox column."""
    rows = selected_rows(df, select_column)
    if rows.empty or id_column not in rows.columns:
        return []
    ids = []
    for v in rows[id_column].tolist():
        try:
            if str(v).strip() != "":
                ids.append(int(v))
        except Exception:
            ids.append(v)
    return ids


def render_button(label: str, *, key: str, on_click=None, args=None, disabled: bool = False, button_type: str = "secondary", width: str = "stretch") -> bool:
    """Streamlit button wrapper using new width API when available.

    Keeps old Streamlit compatibility by falling back to use_container_width.
    """
    kwargs = {"key": key, "disabled": disabled, "type": button_type}
    if on_click is not None:
        kwargs["on_click"] = on_click
        kwargs["args"] = tuple(args or ())
    try:
        return st.button(label, width=width, **kwargs)
    except TypeError:
        return st.button(label, use_container_width=(width == "stretch"), **kwargs)
