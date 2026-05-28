# -*- coding: utf-8 -*-
"""V160 startup hook: set app timezone before Streamlit loads pages."""
try:
    from services.timezone_bootstrap_service import apply_app_timezone
    apply_app_timezone()
except Exception:
    pass
