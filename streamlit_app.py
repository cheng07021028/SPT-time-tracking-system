"""Compatibility entrypoint for Streamlit Cloud.

The cleaned Neon architecture keeps the real application in app.py, but some
existing Streamlit deployments still point to streamlit_app.py. Keeping this
thin wrapper lets both entry paths work without duplicating business logic.
"""

import app  # noqa: F401  # Importing app runs the Streamlit application.
