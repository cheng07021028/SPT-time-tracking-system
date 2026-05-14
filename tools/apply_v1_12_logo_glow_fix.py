# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
logo = ROOT / "data" / "logo" / "super_plus_logo.png"
legacy = ROOT / "data" / "logo" / "logococo(黑字).png"

print("=" * 60)
print("SPT Time Tracking V1.12 Logo + Glow Fix")
print("=" * 60)

if logo.exists():
    print(f"OK logo exists: {logo}")
elif legacy.exists():
    logo.write_bytes(legacy.read_bytes())
    print(f"Copied legacy logo to: {logo}")
else:
    print("WARNING: logo not found. Please put super_plus_logo.png in data/logo/.")

print("Please restart Streamlit after applying this patch.")
print("Done.")
