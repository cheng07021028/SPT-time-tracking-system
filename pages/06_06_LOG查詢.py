from __future__ import annotations

import pandas as pd
import streamlit as st

from spt_core.auth import require_login
from spt_core.db import init_db
from spt_core.services.log_service import list_logs
from spt_core.services.permission_service import require_permission
from spt_core.ui import render_result, setup_page

setup_page("06 LOG 查詢")
init_db()
user = require_login()
perm = require_permission(user, "log.view")
if not perm.ok:
    render_result(perm)
    st.stop()

st.title("06. LOG 查詢")
module = st.text_input("模組篩選，可空白")
actor = st.text_input("操作者篩選，可空白")
limit = st.number_input("筆數", min_value=10, max_value=5000, value=300, step=50)
result = list_logs(module=module.strip() or None, actor=actor.strip() or None, limit=int(limit))
if result.ok and result.data:
    st.dataframe(pd.DataFrame(result.data), use_container_width=True, hide_index=True)
else:
    st.info("查無 LOG。")
