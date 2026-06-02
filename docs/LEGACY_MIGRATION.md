# 舊版資料匯入 Neon / PostgreSQL

## 目的

把舊專案 `data/permanent_store/modules/*/records.json` 中的正式資料匯入新版單一真實來源資料庫。

## 不要把舊資料上傳到 Public GitHub

如果你的 GitHub repo 是 Public，不要把舊 ZIP、舊 `data/permanent_store`、`.env`、Neon `DATABASE_URL`、公司製令、人員、工時資料放到 repo。

## 匯入步驟

1. 在本機放好舊 ZIP，例如：

```text
D:\SPT\SPT-time-tracking-system-main (260602).zip
```

2. 在新版專案資料夾建立 `.env`：

```env
DATABASE_URL="postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/DB?sslmode=require"
SPT_ADMIN_USERNAME="admin"
SPT_ADMIN_PASSWORD="請換成強密碼"
SPT_TIMEZONE="Asia/Taipei"
```

3. 初始化資料庫：

```bash
python scripts/init_db.py
```

4. 匯入舊資料：

```bash
python scripts/migrate_legacy_authority.py "D:\SPT\SPT-time-tracking-system-main (260602).zip"
```

## 匯入對照

| 舊模組 | 新資料表 |
|---|---|
| 01_time_records / 02_history | time_records |
| 03_work_orders | work_orders |
| 04_employees | employees |
| 10_permissions auth_users | users |
| 10_permissions auth_account_permissions | account_permissions |
| 13_system_settings process_options | processes |
| 13_system_settings rest_periods | rest_periods |
| 06_log_query records.jsonl | operation_logs |

## 登入密碼

新版支援舊版兩種密碼 hash：

- `pbkdf2_sha256$iterations$salt_base64$hash_base64`
- `pbkdf2_sha256$salt_text$hash_hex`

所以舊帳號匯入後可沿用舊密碼。若某些帳號登入失敗，請用管理員在 10 權限管理內重設密碼。
