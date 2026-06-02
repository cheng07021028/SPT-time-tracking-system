# 超慧科技製造部_工時紀錄 / SPT-time-tracking-system

這是依新版專業架構整理後的乾淨版本：

```text
Streamlit UI
  ↓
Service Layer
  ↓
Transaction / Permission / LOG / Soft Delete
  ↓
Neon PostgreSQL / PostgreSQL 單一真實來源
```

## 重要原則

- Neon PostgreSQL 是正式單一真實來源。
- SQLite 只可作本機 demo / 測試，不作正式多人資料庫。
- GitHub 只放程式碼，不放 `.env`、資料庫密碼、公司正式資料。
- 所有新增、修改、刪除都必須走 service。
- 所有刪除都用 soft delete + delete_events + operation_logs，避免 Reboot 後復活。
- `pages/` 不直接讀寫檔案或資料庫。

## 快速啟動

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts/init_db.py
streamlit run app.py
```

macOS / Linux：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_db.py
streamlit run app.py
```

## Neon / Streamlit Cloud 設定

Streamlit Cloud 的 Main file path 請填：

```text
app.py
```

Secrets 範例：

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/DB?sslmode=require"
SPT_ADMIN_USERNAME = "admin"
SPT_ADMIN_PASSWORD = "請換成強密碼"
SPT_TIMEZONE = "Asia/Taipei"
```

## 舊資料匯入

不要把舊公司資料上傳到 Public GitHub。請在本機用腳本匯入 Neon：

```bash
python scripts/migrate_legacy_authority.py "D:\SPT\SPT-time-tracking-system-main (260602).zip"
```

詳細看：

```text
docs/LEGACY_MIGRATION.md
MIGRATION_RESULT_260602.md
```

## 已保留的必要頁面

- 01 工時紀錄
- 02 工時查詢
- 03 製令管理
- 04 人員名單
- 06 LOG 查詢
- 10 權限管理
- 11 登入紀錄
- 13 系統設定

舊版 05 / 07 / 08 / 09 / 12 / 14 / 98 / 99 先不放入正式主線，避免把舊版不統一的讀寫邏輯帶回來；後續要重建時應從 service 層補功能，而不是搬回舊頁面。
