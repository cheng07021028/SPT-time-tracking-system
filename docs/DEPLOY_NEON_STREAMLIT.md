# Neon + Streamlit 部署說明

## Neon

1. 到 Neon Console 建立 Project。
2. 建立 database。
3. 點 Connect 取得 connection string。
4. 建議 Streamlit 使用 pooled connection string，通常 hostname 會包含 `-pooler`。
5. 確認 connection string 包含 `sslmode=require`。

## 本機

```bash
cp .env.example .env
# 修改 DATABASE_URL 與管理員密碼
pip install -r requirements.txt
python scripts/init_db.py
streamlit run app.py
```

## Streamlit Community Cloud

1. 把專案上傳 GitHub。
2. Streamlit Cloud 指向 `app.py`。
3. 在 Secrets 放入：

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/DB?sslmode=require"
SPT_ADMIN_USERNAME = "admin"
SPT_ADMIN_PASSWORD = "請換成強密碼"
SPT_TIMEZONE = "Asia/Taipei"
```

## 資料安全

- 不要把 `.env` 或 `.streamlit/secrets.toml` commit 到 GitHub。
- `SPT_ADMIN_PASSWORD` 初次啟動後應修改。
- 生產環境建議只讓管理員有 10 / 13 頁面權限。
