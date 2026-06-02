# -*- coding: utf-8 -*-
"""V166E editor stability guards.

This module is intentionally UI-only:
- it does not write business data;
- it does not change 01/02 transaction flow;
- it only reduces duplicate rapid add-clicks and restores scroll position after Streamlit reruns.
"""
from __future__ import annotations

import time
from typing import Any

import streamlit as st

_ORIGINAL_BUTTON = None

_DUPLICATE_SENSITIVE_TOKENS = (
    "新增空白列", "Add Row", "新增帳號", "Add User",
    "新增資料", "Create", "建立待補", "從 LOG 建立",
)


def _button_identity(label: Any, key: Any) -> str:
    if key is not None:
        return str(key)
    return "label::" + str(label)


def _is_duplicate_sensitive(label: Any, key: Any) -> bool:
    text = f"{label} {key or ''}"
    return any(token in text for token in _DUPLICATE_SENSITIVE_TOKENS)


def install_duplicate_button_guard(window_seconds: float = 1.25) -> None:
    """Install a conservative duplicate-click guard for add/create buttons.

    Streamlit normally returns True once per click, but under heavy rerun or browser
    resubmission some legacy add-row buttons may be evaluated more than once.  This
    guard suppresses only rapid repeated Add/Create-style button events with the
    same key/label.  Refresh/check/export/repair buttons are not suppressed.
    """
    global _ORIGINAL_BUTTON
    if getattr(st, "_spt_v166e_duplicate_button_guard_installed", False):
        return
    _ORIGINAL_BUTTON = st.button

    def guarded_button(label, *args, **kwargs):  # type: ignore[no-untyped-def]
        pressed = _ORIGINAL_BUTTON(label, *args, **kwargs)
        if not pressed:
            return pressed
        key = kwargs.get("key")
        if not _is_duplicate_sensitive(label, key):
            return pressed
        ident = _button_identity(label, key)
        now = time.monotonic()
        store_key = "_spt_v166e_last_duplicate_sensitive_button"
        last = st.session_state.get(store_key, {})
        try:
            last_ident = str(last.get("id", ""))
            last_ts = float(last.get("ts", 0.0))
        except Exception:
            last_ident, last_ts = "", 0.0
        if last_ident == ident and (now - last_ts) < float(window_seconds):
            return False
        st.session_state[store_key] = {"id": ident, "ts": now}
        return pressed

    st.button = guarded_button  # type: ignore[assignment]
    st._spt_v166e_duplicate_button_guard_installed = True  # type: ignore[attr-defined]


def inject_scroll_position_guard() -> None:
    """Persist/restore page scroll when data_editor reruns the page.

    Best-effort only.  Any browser/security restriction is silently ignored so it
    cannot break the application.
    """
    try:
        import streamlit.components.v1 as components
        components.html(
            """
<script>
(function(){
  try {
    const parentWin = window.parent;
    const parentDoc = parentWin.document;
    const key = 'SPT_V166E_SCROLL_Y::' + parentWin.location.pathname + parentWin.location.search;
    if (!parentWin.__SPT_V166E_SCROLL_GUARD__) {
      parentWin.__SPT_V166E_SCROLL_GUARD__ = true;
      let lastSave = 0;
      const save = function(){
        const now = Date.now();
        if (now - lastSave < 120) return;
        lastSave = now;
        try { parentWin.localStorage.setItem(key, String(parentWin.scrollY || parentDoc.documentElement.scrollTop || 0)); } catch(e) {}
      };
      parentWin.addEventListener('scroll', save, {passive:true});
      parentDoc.addEventListener('input', save, true);
      parentDoc.addEventListener('change', save, true);
      parentDoc.addEventListener('click', function(ev){
        try {
          const t = ev.target;
          if (!t) return;
          if (String(t.tagName || '').match(/INPUT|TEXTAREA|SELECT|BUTTON/)) save();
          if (t.closest && (t.closest('[data-testid="stDataEditor"]') || t.closest('[data-testid="stDataFrame"]'))) save();
        } catch(e) {}
      }, true);
    }
    const restore = function(){
      try {
        const raw = parentWin.localStorage.getItem(key);
        if (!raw) return;
        const y = parseInt(raw, 10);
        if (!isNaN(y) && y > 80) parentWin.scrollTo({top:y, left:0, behavior:'auto'});
      } catch(e) {}
    };
    setTimeout(restore, 40);
    setTimeout(restore, 180);
    setTimeout(restore, 420);
  } catch(e) {}
})();
</script>
            """,
            height=0,
            width=0,
        )
    except Exception:
        pass


def install_editor_stability_guards() -> None:
    install_duplicate_button_guard()
    inject_scroll_position_guard()
