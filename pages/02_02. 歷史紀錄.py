# -*- coding: utf-8 -*-
from services.auth_service import require_module
from services.app_config import TABLE_COLUMNS
from services.ui import apply_theme, records_page, paste_import_box
from services.time_calc import recalc_time_rows

MODULE = "02_history"
apply_theme(); require_module(MODULE, "view")
paste_import_box(MODULE, TABLE_COLUMNS[MODULE])
records_page(MODULE, default_columns=TABLE_COLUMNS[MODULE], recalc_func=recalc_time_rows)
