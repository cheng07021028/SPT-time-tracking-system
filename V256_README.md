# V256 登入與 01 前台點選加速修正包

## 修改檔案
- `streamlit_app.py`
- `services/security_service.py`
- `services/time_record_service.py`

## 修正目標
- APP 開啟已可 2~3 秒，V256 保留此改善。
- 登入 15 秒：改成登入熱路徑只查帳號/密碼/角色，不跑完整 Neon/PostgreSQL schema 初始化。
- 進入 01 約 15 秒：01/02 顯示改 SQL-first，不在正常頁面載入時掃描 01/02 authority JSON、row shards、event journal。
- 按鈕確認約 60 秒：開始/結束按鈕前台只完成 SQL 交易與畫面快取清除；JSON 權威檔、row shard、event journal 備份改為 daemon worker 延後處理。

## 保留原則
- 不修改 UI / CSS / theme / 表格 / 按鈕外觀。
- 不提供 `#Uxxxx` 亂碼檔名。
- 不改正式欄位排版。
- 不刪除既有功能，只把重工作業移出前台熱路徑。

## 建議測試
1. Reboot App。
2. 打開 APP：確認維持 2~3 秒左右。
3. 登入兩次：記錄秒數。
4. 進入 01. 工時紀錄：記錄秒數。
5. 測開始作業、暫停、完工、下班：記錄按鈕確認秒數。
6. 到 02. 歷史紀錄確認剛剛新增/結束資料可查到。
