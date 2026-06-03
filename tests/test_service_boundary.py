from __future__ import annotations

from pathlib import Path


def test_services_do_not_import_streamlit():
    root = Path(__file__).resolve().parents[1] / "spt_core" / "services"
    offenders = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import streamlit" in text or "from streamlit" in text or "st." in text:
            offenders.append(str(path))
    assert offenders == []
