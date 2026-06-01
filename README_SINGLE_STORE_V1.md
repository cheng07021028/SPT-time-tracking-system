# SPT Time Tracking - Preserve UI Single Store V1

本版以原始上傳專案為基底，保留原本 13 個 Streamlit 模組、頁面顯示、表單樣式、CSS、業務邏輯與串接。

唯一架構性變動：正式讀寫資料集中到：

```text
data/permanent_store/
```

正式資料子路徑：

```text
data/permanent_store/persistent_modules/
data/permanent_store/persistent_state/
data/permanent_store/database/
data/permanent_store/config/
```

舊版根目錄下的 `data/persistent_modules`、`data/persistent_state`、`data/database`、`data/config` 已移除，避免 Reboot App 後多路徑互相覆蓋或讀錯。

頁面檔名已從 `#Uxxxx` 修正為正常中文檔名，但內容不重寫。

檢查：

```bash
python -m compileall -q streamlit_app.py services pages tools
python tools/check_single_store_preserve_ui.py
```
