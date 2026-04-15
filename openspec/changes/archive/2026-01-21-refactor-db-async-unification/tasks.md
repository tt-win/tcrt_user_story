## 1. 盤點與界線
- [ ] 1.1 盤點所有 `get_sync_db` 與同步 session 使用點（含 main/audit/usm）
- [ ] 1.2 標記哪些屬於 Web runtime、哪些屬於離線工具（script/init）

## 2. 非同步存取設計與支援
- [x] 2.1 定義 AsyncSession 注入與共用模式（主 DB / audit DB / USM DB）
- [x] 2.2 定義同步存取的隔離策略（僅限離線工具或 threadpool 封裝）

## 3. 逐步改寫與相容
- [ ] 3.1 將 API 路由改用 AsyncSession，移除對同步 session 的直接依賴
- [ ] 3.2 將服務層改為 async 版本並調整呼叫鏈
- [x] 3.3 更新 audit/usm 相關流程以符合 async-only
- [x] 3.4 增加防呆（lint/測試/啟動時檢查）避免 Web runtime 誤用同步 DB

## 4. 驗證與回歸
- [ ] 4.1 更新測試/fixtures 以支援 async-only DB
- [ ] 4.2 針對核心 API（test case / test run / USM / audit）做回歸比對
- [ ] 4.3 執行測試並記錄結果（不得破壞既有功能）
