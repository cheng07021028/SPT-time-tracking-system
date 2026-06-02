# 模組規格

## 01 工時紀錄

- 開始作業：驗證人員、製令、工段、權限。
- group_key：`work_date|employee_id|process_code|start_time_bucket_3min`。
- 同 group_key 可同時作業。
- 不同 group_key 開始作業時，依設定自動暫停舊 active 紀錄。
- 完工可選擇同 group_key 一起完工。
- 群組平均：同 group_key 且有 end_time 的紀錄，`average_minutes = work_minutes / group_count`。
- 刪除：只有 admin，可 soft delete + delete_event + LOG。

## 02 工時查詢

- 與 01 共用 `time_records`。
- 預設不顯示 `deleted_at IS NOT NULL`。
- 可依日期、工號、製令、工段、狀態查詢。

## 03 製令管理

- 主鍵：`work_order_no`。
- 已有工時紀錄的製令不可刪除，應改為 `closed` 或 `hold`。
- 新增/修改/刪除都要 LOG。

## 04 人員名單

- 主鍵：`employee_id`。
- 新增前檢查工號唯一。
- 支援 idempotency key，防止 Streamlit rerun 重複新增。

## 06 LOG 查詢

- `operation_logs` append-only。
- 預設只查最近 N 筆。
- 不執行資料修復，不影響主資料。

## 10 權限管理

角色：

| 角色 | 說明 |
|---|---|
| operator | 一般作業員 |
| supervisor | 主管，可維護製令 |
| admin | 系統管理員 |

權限由 `permission_service.py` 統一判斷。

## 11 登入紀錄

- 登入成功/失敗都寫入 `login_events`。
- 查詢限量，不全量掃描。

## 13 系統設定

- 設定存 `system_settings`。
- 工段存 `processes`。
- service 層不得 import Streamlit。
