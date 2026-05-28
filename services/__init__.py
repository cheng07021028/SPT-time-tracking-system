# -*- coding: utf-8 -*-
# V160: standardize application runtime timezone as soon as services is imported.
try:
    from .timezone_bootstrap_service import apply_app_timezone
    apply_app_timezone()
except Exception:
    pass
