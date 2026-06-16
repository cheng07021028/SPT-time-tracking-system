# 測試報告

## 已執行

- `python -m compileall streamlit_app.py services pages`：通過。
- `services.capacity_engine.calculate_capacity()` 加入 `capacity_adjustments` 後測試通過。
  - 1月原始需求工時 8872.0h。
  - 加入 1月調整工時 100h 後，需求總工時變為 8972.0h。
- `services.org_chart_service.render_org_component_html()` 樹枝圖 HTML 產生測試通過。
- `services.org_chart_service.render_org_html()` 卷軸式 HTML 產生測試通過。
- `services.powerbi_theme` 圖表數據標籤安全字串測試通過。
- ZIP 檔名檢查通過，沒有 `#Uxxxx` 亂碼檔名。

## 注意

目前測試環境未安裝 Streamlit，因此未在本機啟動完整 Streamlit 畫面；已完成 Python 語法與核心服務函式測試。覆蓋到 Streamlit Cloud 後，請使用 Manage app → Reboot app 清除舊快取。
