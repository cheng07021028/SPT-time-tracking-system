V2.59｜下拉選單 / 多選篩選文字被切修正包

用途：
- 修正 selectbox / multiselect 的 Choose options、No options to select、已選標籤文字被上下切掉。
- 保留不出現白點 / 白色方塊。
- 不恢復執行結果重播面板。
- 不修改資料、權限、工時計算、篩選邏輯。

使用方式：
1. 將本壓縮包解到專案根目錄。
2. 執行：python tools/apply_v259_select_text_fix.py
3. 重新啟動 Streamlit。

原因：
直接覆蓋 services/theme_service.py 可能會把你現有的 LOGO、全系統字體、登入頁與按鈕樣式覆蓋掉，
所以本版使用 append-only patch，只在原檔案最後追加 CSS 修正區塊。
