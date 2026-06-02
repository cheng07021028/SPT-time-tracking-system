# V32 Neon 單一真實來源與效能方案

本版本固定規則：

- Neon/PostgreSQL 是 Streamlit Cloud 正式單一真實來源。
- GitHub 只作程式碼與備份快照，不作即時資料權威。
- JSON / permanent_store / SQLite 只作 fallback、cache、匯入來源或本機測試。
- 所有新增、修改、刪除必須透過 service/db_service/neon_authority_service 寫入 Neon。
- 所有刪除採 soft delete / delete_event / operation log；不得物理刪除有效資料。
- 20 台電腦、50 人同時操作時，常用按鈕目標 2~3 秒完成。

V32 加強項目：

1. PostgreSQL 啟動時自動補齊 performance indexes。
2. 關閉 Neon 模式下 GitHub/local JSON 自動還原覆蓋。
3. 06 LOG 正式改用 Neon system_logs 直接查詢與 soft delete。
4. 07 每日出勤紀錄改用 Neon spt_module_authority。
5. 99 效能診斷新增架構合規與 2~3 秒效能快測。
6. 備份還原預設不能覆蓋 Neon；需顯式設定 SPT_ALLOW_BACKUP_RESTORE_TO_NEON=1。
