# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from services.auth_service import require_module
from services.ui import apply_theme, page_header
from services.permanent_store import STORE_ROOT, store_health

MODULE = "12_module_persistence"
apply_theme(); require_module(MODULE, "view")
page_header(MODULE)
st.markdown("""
此中心只檢查唯一正式資料源：`data/permanent_store/`。  
舊版 `persistent_modules`、`persistent_state`、SQLite 不再作為正式讀寫來源，避免 Reboot App 後讀錯檔。
""")
health = store_health()
st.code(str(STORE_ROOT))
df = pd.DataFrame(health["modules"])
st.dataframe(df, use_container_width=True, hide_index=True)
with st.expander("資料夾規格"):
    st.code("""data/permanent_store/
├─ manifest.json
├─ system/
│  ├─ users.json
│  ├─ permissions.json
│  ├─ security_settings.json
│  ├─ login_logs.jsonl
│  └─ audit_logs.jsonl
├─ modules/
│  └─ <module_key>/
│     ├─ records.json
│     ├─ settings.json
│     └─ audit.jsonl
└─ _backups/
   └─ 每次覆寫前自動備份
""")
