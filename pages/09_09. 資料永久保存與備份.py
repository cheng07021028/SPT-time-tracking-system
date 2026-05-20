# -*- coding: utf-8 -*-
import shutil
from pathlib import Path
import pandas as pd
import streamlit as st

from services.auth_service import require_module, current_user
from services.ui import apply_theme, page_header
from services.permanent_store import STORE_ROOT, store_health, stamp, log_event

MODULE = "09_persistence"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)
st.success("正式資料唯一來源：data/permanent_store。Reboot App 後只會讀取此路徑，不再從多個舊路徑猜資料。")
health = store_health()
st.code(health["root"])
st.dataframe(pd.DataFrame(health["modules"]), use_container_width=True, hide_index=True)
if st.button("建立永久資料備份 ZIP", type="primary"):
    require_module(MODULE, "export")
    out = Path("exports")
    out.mkdir(exist_ok=True)
    zip_base = out / f"permanent_store_backup_{stamp()}"
    zip_path = shutil.make_archive(str(zip_base), "zip", STORE_ROOT)
    log_event(MODULE, "backup_zip", current_user(), "OK", zip_path)
    st.success(f"已建立：{zip_path}")
    st.download_button("下載備份 ZIP", Path(zip_path).read_bytes(), file_name=Path(zip_path).name, mime="application/zip")
