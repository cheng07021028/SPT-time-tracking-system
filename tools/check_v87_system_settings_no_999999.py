# -*- coding: utf-8 -*-
from pathlib import Path
p = Path('services/system_settings_service.py')
text = p.read_text(encoding='utf-8')
required = [
    '_v87_display_repair_df',
    '_v87_clean_input_id',
    '_v87_sort_or_default',
    'df = _v87_display_repair_df(df, id_col="id", sort_col="sort_order", group_col="category_name")',
]
missing = [x for x in required if x not in text]
if missing:
    raise SystemExit('V87 check failed, missing: ' + ', '.join(missing))
print('V87 check passed: system settings display sentinel fix is installed.')
