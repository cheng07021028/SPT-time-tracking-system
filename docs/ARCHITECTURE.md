# 系統架構設計

## 1. 單一真實來源

正式環境以 Neon PostgreSQL / PostgreSQL 作為唯一真實來源。所有模組只透過 `spt_core/services/*` 進行新增、修改、刪除與查詢。

禁止頁面直接：

```python
json.dump(...)
df.to_csv(...)
sqlite3.connect(...)
st.session_state["records"] = ...  # 當權威資料
```

## 2. 分層

```text
pages/*.py
  只處理 UI、表單、按鈕、表格、提示

spt_core/services/*.py
  商業規則、權限、交易、LOG、工時計算

spt_core/db.py
  連線、transaction、SQL 執行、Neon/PostgreSQL/SQLite demo 轉接

Neon PostgreSQL
  生產正式資料
```

## 3. 交易規範

所有修改都必須走：

```text
validate input
check permission
begin transaction
read current authoritative data
apply change
append operation log
commit
return Result
```

## 4. 刪除規範

所有刪除都必須：

1. 權限檢查
2. soft delete：寫入 `deleted_at`, `deleted_by`, `delete_reason`
3. insert `delete_events`
4. append `operation_logs`
5. 所有 active 查詢排除 `deleted_at IS NOT NULL`

不可直接物理刪除正式資料。

## 5. 工時計算

工時計算只在 `time_calculation_service.py`。頁面與查詢模組不可自己算。

## 6. Streamlit 注意事項

- button/form submit 使用 service，避免 render 時自動寫資料。
- `session_state` 只保存登入使用者與 UI 狀態。
- 大量查詢必須分頁或 limit。
- LOG 與登入紀錄不可全量載入。

## 7. Neon / PostgreSQL 注意事項

- 使用 pooled connection string，Streamlit 會因 rerun 產生較多短連線。
- 不要把 connection string 寫死在程式碼。
- 使用 `DATABASE_URL` 或 Streamlit Secrets。
- GitHub 只做備份與程式碼版本，不做即時交易資料庫。
