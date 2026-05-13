# SPT Time Tracking System

超慧科技製造部智慧工時紀錄系統｜Streamlit + SQLite + Excel Import/Export

## 本機執行

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tools\init_database.py
streamlit run streamlit_app.py
```

## 模組

1. 工時紀錄
2. 歷史紀錄
3. 製令管理
4. 人員名單
5. 製令工時分析
6. LOG 查詢
7. 今日未紀錄名單
8. 人員每日工時

## 注意

- `data/database/*.db` 為本機資料庫，預設不推上 GitHub。
- 正式多人使用建議後續升級 PostgreSQL / Supabase。
