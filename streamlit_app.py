import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="超慧科技製造部｜工時紀錄系統",
    page_icon="🕒",
    layout="wide"
)

LOGO_PATH = Path("data/logo/super_plus_logo.png")

col1, col2 = st.columns([1, 5])

with col1:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)

with col2:
    st.title("超慧科技製造部｜智慧工時紀錄系統")
    st.caption("Super Plus Tech Manufacturing Time Tracking System")

st.divider()

st.success("系統初始化成功。請從左側選單進入各功能頁。")

st.markdown("""
### 系統模組

1. 工時紀錄  
2. 歷史紀錄  
3. 製令管理  
4. 人員名單  
5. 製令工時分析  
6. LOG 查詢  
7. 今日未紀錄名單  
8. 人員每日工時  
""")