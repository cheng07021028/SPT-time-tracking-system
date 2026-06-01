# SPT V254 Login Speed Patch

目的：修正登入固定約 15 秒的問題。

修改檔案：
- `streamlit_app.py`
- `services/audit_log_service.py`

修正內容：
1. 首頁登入後不再每次 rerun 都啟動 Neon/PostgreSQL authority bootstrap。
2. 登入紀錄仍會立即寫入 SQLite，保留登入稽核。
3. 11 登入紀錄權威檔改為背景刷新，且登入熱路徑不做 GitHub 同步。
4. 不修改 UI、CSS、theme、表格、按鈕。
5. ZIP 內無 `#Uxxxx` 亂碼檔名。

覆蓋方式：
把本壓縮包內檔案覆蓋到 GitHub 專案相同路徑。
