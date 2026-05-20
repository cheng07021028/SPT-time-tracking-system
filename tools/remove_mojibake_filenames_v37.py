# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PAGES=ROOT/'pages'
removed=[]
for p in list(PAGES.glob('*.py')):
    if '#U' in p.name or 'Φ' in p.name or '╜' in p.name or 'τ' in p.name:
        removed.append(p.name)
        p.unlink()
if removed:
    print('Removed mojibake page files:')
    print('\n'.join(removed))
else:
    print('No mojibake page files found.')
