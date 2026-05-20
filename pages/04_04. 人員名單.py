# -*- coding: utf-8 -*-
from services.auth_service import require_module
from services.app_config import TABLE_COLUMNS
from services.ui import apply_theme, records_page, paste_import_box

MODULE = "04_employees"
apply_theme(); require_module(MODULE, "view")
paste_import_box(MODULE, TABLE_COLUMNS[MODULE])
records_page(MODULE, default_columns=TABLE_COLUMNS[MODULE])
