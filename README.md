# SPT Time Tracking System

超慧科技製造部智慧工時紀錄系統｜Streamlit + PostgreSQL/SQLite + Excel Import/Export

## 本機執行

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tools\init_database.py
streamlit run streamlit_app.py
```

## 雲端 PostgreSQL

設定以下任一環境變數後，系統會使用 PostgreSQL；未設定時仍保留 SQLite 本機模式。

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
```

Streamlit Cloud Secrets 也可以使用：

```toml
[connections.postgresql]
url = "postgresql://USER:PASSWORD@HOST:5432/DBNAME"
```

雲端防呆：在 Streamlit Cloud 上執行時，如果沒有設定 PostgreSQL 連線，系統會阻止 SQLite fallback，避免新工時寫進重開後會消失的本機暫存檔。只有臨時測試時才設定 `SPT_ALLOW_SQLITE_ON_CLOUD=1`。

第一次升級既有資料時執行：

```bat
python tools\migrate_authority_to_postgres.py
```

Streamlit Cloud 部署時：

1. App entry point: `streamlit_app.py`
2. Secrets 加入 `DATABASE_URL`
3. 部署前或第一次啟動後執行 migration script 匯入 `data/permanent_store/modules` 既有資料

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

- `data/database/*.db` / `data/permanent_store/database/*.db` 是本機 SQLite fallback。
- 正式多人/雲端使用請設定 PostgreSQL，避免 Streamlit Cloud 重啟後本機 SQLite 快取落後。
