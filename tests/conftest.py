from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from spt_core.db import init_db, reset_for_tests


@pytest.fixture()
def test_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("SPT_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("SPT_ADMIN_PASSWORD", "admin123")
    reset_for_tests()
    init_db()
    yield tmp.name
    reset_for_tests()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture()
def admin_actor():
    return {"username": "admin", "role": "admin", "display_name": "系統管理員"}


@pytest.fixture()
def supervisor_actor():
    return {"username": "boss", "role": "supervisor", "display_name": "主管"}


@pytest.fixture()
def operator_actor():
    return {"username": "op", "role": "operator", "display_name": "作業員"}
