# V253.1 01/02 Neon 加速修正版（無亂碼檔名）

此包修正 V253 壓縮包內 `#Uxxxx` 亂碼檔名問題。

## 覆蓋檔案

- `pages/02_02. 歷史紀錄.py`
- `services/large_table_query_service.py`

## 原則

- 保留 V230 前台操作隔離速度基準
- 保留 Codex Neon/PostgreSQL 方向
- 不修改 UI / CSS / theme / 表格 / 按鈕外觀
- 02 歷史紀錄採用 SQL-first / 快取查詢優先
- ZIP 內已檢查不含 `#Uxxxx` 亂碼檔名
