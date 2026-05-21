# -*- coding: utf-8 -*-
"""Compatibility wrapper for the existing GitHub check workflow.

The old v37 script deleted every page filename containing #U directly.
This wrapper delegates to the safer cleanup tool, which first renames #Uxxxx
filenames to real Chinese filenames, and only deletes duplicates when a proper
Chinese filename already exists.
"""
from __future__ import annotations

from cleanup_mojibake_pages import main

if __name__ == "__main__":
    raise SystemExit(main())
