# SPT-time-tracking-system 260602 轉換結果

本包是依「Neon/PostgreSQL 單一真實來源 + Service Layer + soft delete + LOG」架構，從舊專案 `SPT-time-tracking-system-main (260602).zip` 整理出的乾淨新版。

## 已保留並轉換的必要內容

- `assets/super_plus_logo.png`：保留公司 Logo。
- `app.py`：新版 Streamlit 入口。
- `pages/`：只保留新版必要頁面，移除舊版 `#Uxxxx` 亂碼頁面。
- `spt_core/`：新版核心 service / db / schema / auth / security。
- `database/schema.sql`：Neon/PostgreSQL 正式 schema。
- `scripts/init_db.py`：初始化資料庫。
- `scripts/migrate_legacy_authority.py`：把舊版 permanent_store 匯入新版 Neon/PostgreSQL。
- `scripts/smoke_test.py`：核心流程煙霧測試。
- `tests/`：基本回歸測試。
- `docs/`：部署、架構、模組規格與回歸檢查文件。

## 已剔除的舊版高風險內容

- 根目錄重複 service 檔。
- 舊版大量 patch 工具。
- 舊版 `#Uxxxx` 亂碼頁面檔。
- 舊版 Streamlit 直接讀寫 CSV/JSON/SQLite 的混合邏輯。
- 舊版本機 `.db`、快取、log、煙霧測試輸出。
- 舊版修補報告、重複 README、歷史版本說明。
- 舊版 GitHub 同步作業腳本與 bat 檔。

## 舊資料匯入測試結果

使用舊 ZIP 在 SQLite 測試資料庫上執行匯入，結果如下：

| 類別 | 匯入筆數 |
|---|---:|
| 人員 employees | 92 |
| 製令 work_orders | 601 |
| 工時 time_records | 118 |
| 使用者 users | 106 |
| 權限 account_permissions | 1590 |
| 工段 processes | 44 |
| 工段分類 process_categories | 7 |
| 休息時段 rest_periods | 5 |
| LOG operation_logs | 16 |
| 系統設定 system_settings | 3 |

## 交付前檢查

已執行：

```bash
python -m compileall -q .
pytest -q
DATABASE_URL=sqlite:///data/smoke.db python scripts/smoke_test.py
DATABASE_URL=sqlite:///data/test_migration.db python scripts/migrate_legacy_authority.py "SPT-time-tracking-system-main (260602).zip"
```

結果：

- `pytest`：7 passed
- `smoke_test`：passed
- 舊資料匯入測試：passed
- ZIP 內無 `#Uxxxx` 亂碼檔名
- `spt_core` service 層未直接 import streamlit

## 重要注意

本包沒有把舊的公司資料直接放進 GitHub 上傳包，避免你把 repo 改 Public 時外洩資料。舊資料要用 `scripts/migrate_legacy_authority.py` 從你本機舊 ZIP 匯入到 Neon。
