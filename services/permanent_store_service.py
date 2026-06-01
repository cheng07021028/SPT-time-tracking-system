# -*- coding: utf-8 -*-
"""Single permanent data root for SPT Time Tracking.

This project keeps the original pages/services/UI, but all formal read/write
state is centralized under DATA_PERMANENT_ROOT so Reboot App will not fall back
to scattered legacy paths.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_PERMANENT_ROOT = DATA_DIR / "permanent_store"
PERSISTENT_MODULES_DIR = DATA_PERMANENT_ROOT / "persistent_modules"
PERSISTENT_STATE_DIR = DATA_PERMANENT_ROOT / "persistent_state"
DATABASE_DIR = DATA_PERMANENT_ROOT / "database"
CONFIG_DIR = DATA_PERMANENT_ROOT / "config"

def ensure_permanent_store() -> None:
    for p in [DATA_PERMANENT_ROOT, PERSISTENT_MODULES_DIR, PERSISTENT_STATE_DIR, DATABASE_DIR, CONFIG_DIR]:
        p.mkdir(parents=True, exist_ok=True)

def permanent_path(*parts: str) -> Path:
    ensure_permanent_store()
    return DATA_PERMANENT_ROOT.joinpath(*parts)

ensure_permanent_store()
