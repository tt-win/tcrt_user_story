# Role-Based 權限管理系統 - 實作任務清單

## 任務執行順序說明

本任務清單按照依賴關係排序，必須按順序執行以確保系統穩定性。每個任務完成後請勾選 ✅。

---

## 階段一：環境準備與依賴安裝

### 🔧 Task 1: 安裝新增依賴套件
- [ ] 更新 `requirements.txt` 加入認證相關套件（統一採用 PyJWT）
  - [ ] 新增 `PyJWT==2.8.0`
  - [ ] 新增 `passlib[bcrypt]==1.7.4`
  - [ ] 移除 `python-jose[...]` 相關依賴（如有）
- [ ] 執行 `pip install -r requirements.txt` 安裝新套件
- [ ] 驗證套件安裝成功（import 測試）

### 📝 Task 2: 更新設定檔結構
- [ ] 擴展 `app/config.py` 加入認證設定
  - [ ] 新增 `AuthConfig` 類別（enable_auth、jwt_expire_days 等）
  - [ ] 新增 `AuditConfig` 類別（enable_audit、batch_size、cleanup_days 等）
  - [ ] 整合到 `Settings` 主設定類別
- [ ] 更新 `config.yaml.example` 加入範例設定
  - [ ] 新增 auth 設定區塊（jwt_secret_key 僅占位，值來自環境變數）
  - [ ] 新增 audit 設定區塊
- [ ] 確保向下相容性（既有設定不受影響）

---

## 階段二：資料模型建立

### 🗃️ Task 3: 建立認證資料模型
- [ ] 建立 `app/auth/` 目錄結構
  - [ ] 創建 `app/auth/__init__.py`
  - [ ] 創建 `app/auth/models.py`
  - [ ] 創建 `app/auth/auth_service.py`
  - [ ] 創建 `app/auth/permission_service.py`
  - [ ] 創建 `app/auth/password_service.py`
  - [ ] 創建 `app/auth/dependencies.py`

- [ ] 實作 `app/auth/models.py` 內容
  - [ ] 定義 `UserRole` 枚舉
  - [ ] 定義 `PermissionType` 枚舉
  - [ ] 定義 `User` Pydantic 模型
  - [ ] 定義 `UserCreate`, `UserUpdate` 請求模型
  - [ ] 定義 `LoginRequest`, `LoginResponse` 模型
  - [ ] 定義 `TokenData` 模型

### 🗃️ Task 4: 建立審計資料模型
- [ ] 建立 `app/audit/` 目錄結構
  - [ ] 創建 `app/audit/__init__.py`
  - [ ] 創建 `app/audit/models.py`
  - [ ] 創建 `app/audit/audit_service.py`
  - [ ] 創建 `app/audit/database.py`

- [ ] 實作 `app/audit/models.py` 內容
  - [ ] 定義 `ActionType` 枚舉
  - [ ] 定義 `ResourceType` 枚舉
  - [ ] 定義 `AuditLog` Pydantic 模型
  - [ ] 定義 `AuditLogCreate` 請求模型
  - [ ] 定義 `AuditLogQuery` 查詢模型

### 🗃️ Task 5: 擴展資料庫模型
- [ ] 更新 `app/models/database_models.py`
  - [ ] 新增 `User` SQLAlchemy 模型
  - [ ] 新增 `UserTeamPermission` SQLAlchemy 模型
  - [ ] 新增 `ActiveSession` SQLAlchemy 模型
  - [ ] 更新 `create_database_tables()` 函式

- [ ] 實作 `app/audit/database.py`
  - [ ] 建立獨立的審計資料庫引擎
  - [ ] 新增 `AuditLogDB` SQLAlchemy 模型
  - [ ] 實作 `create_audit_database_tables()` 函式

---

## 階段三：核心服務實作

### 🔐 Task 6: 實作認證服務
- [ ] 實作 `app/auth/auth_service.py`
  - [ ] 實作 `create_access_token()` 函式
  - [ ] 實作 `verify_token()` 函式
  - [ ] 實作 `refresh_token()` 函式
  - [ ] 實作 `revoke_token()` 函式
  - [ ] 實作 JWT 編解碼邏輯

- [ ] 實作 `app/auth/password_service.py`
  - [ ] 實作 `hash_password()` 函式
  - [ ] 實作 `verify_password()` 函式
  - [ ] 實作密碼強度檢查
  - [ ] 實作 `generate_temp_password()` 函式

### 🔐 Task 7: 實作權限檢查服務
- [ ] 實作 `app/auth/permission_service.py`
  - [ ] 實作 `check_user_role()` 函式（落實預設拒絕）
  - [ ] 實作 `check_team_permission()` 函式（資源所屬團隊權限優先）
  - [ ] 實作 `get_user_accessible_teams()` 函式
  - [ ] 實作 `has_resource_permission()` 函式
  - [ ] 實作權限快取機制（TTL 5 分鐘）
  - [ ] 提供 `clear_cache(user_id, team_id)` 以便授權變更時清除

- [ ] 實作 `app/auth/dependencies.py`
  - [ ] 實作 `get_current_user()` 依賴（驗證 Bearer Token、檢查 jti 未撤銷）
  - [ ] 實作 `require_role()` 依賴工廠
  - [ ] 實作 `require_team_permission()` 依賴工廠
  - [ ] 實作 `require_admin()` 快捷依賴
  - [ ] 實作 `require_super_admin()` 快捷依賴

### 📊 Task 8: 實作審計服務
- [ ] 實作 `app/audit/audit_service.py`
  - [ ] 實作 `log_action()` 函式（非同步批次寫入，具隊列上限與降級策略）
  - [ ] 實作 `get_audit_logs()` 查詢函式（時間/操作者/資源條件）
  - [ ] 實作 `export_audit_logs()` 匯出函式（欄位白名單、CSV/JSON、可選 UTF-8 BOM）
  - [ ] 實作 `cleanup_old_logs()` 清理函式（依設定天數）
  - [ ] 不記錄敏感資訊（密碼、完整 Token、PII）

---

## 階段四：API 端點實作

### 🌐 Task 9: 實作認證 API
- [ ] 建立 `app/api/auth.py`
  - [ ] 實作 `POST /api/auth/login` 登入端點（回傳 Bearer Token）
  - [ ] 實作 `POST /api/auth/logout` 登出端點（撤銷 jti）
  - [ ] 實作 `POST /api/auth/refresh-token` 刷新端點（若採用 Refresh）
  - [ ] 實作 `GET /api/auth/me` 目前使用者資訊端點
  - [ ] 實作 `POST /api/auth/change-password` 修改密碼端點
  - [ ] 統一 401/403 回應結構（code、message）

### 🌐 Task 10: 實作使用者管理 API
- [ ] 建立 `app/api/users.py`
  - [ ] 實作 `GET /api/users` 使用者列表端點
  - [ ] 實作 `POST /api/users` 建立使用者端點
  - [ ] 實作 `GET /api/users/{user_id}` 使用者詳情端點
  - [ ] 實作 `PUT /api/users/{user_id}` 更新使用者端點
  - [ ] 實作 `DELETE /api/users/{user_id}` 刪除使用者端點
  - [ ] 實作 `POST /api/users/{user_id}/reset-password` 重設密碼端點

### 🌐 Task 11: 實作權限管理 API
- [ ] 建立 `app/api/permissions.py`
  - [ ] 實作 `GET /api/permissions/teams/{team_id}/users` 團隊成員權限列表
  - [ ] 實作 `POST /api/permissions/teams/{team_id}/users` 授予團隊權限
  - [ ] 實作 `PUT /api/permissions/teams/{team_id}/users/{user_id}` 修改權限
  - [ ] 實作 `DELETE /api/permissions/teams/{team_id}/users/{user_id}` 撤銷權限

### 🌐 Task 12: 實作會話管理 API
- [ ] 建立 `app/api/sessions.py`
  - [ ] 實作 `GET /api/sessions` 線上使用者列表端點（Super Admin）
  - [ ] 實作 `DELETE /api/sessions/{user_id}` 踢掉指定使用者端點（撤銷該使用者所有 jti）
  - [ ] 實作會話清理背景任務

### 🌐 Task 13: 實作審計 API
- [ ] 建立 `app/api/audit.py`
  - [ ] 實作 `GET /api/audit/logs` 審計記錄列表端點
  - [ ] 實作 `GET /api/audit/logs/export` 匯出審計記錄端點
  - [ ] 加入搜尋、篩選、分頁功能

---

## 階段五：前端登入系統實作

### 🎨 Task 14: 建立登入頁面模板
- [ ] 建立認證相關模板目錄
  - [ ] 創建 `app/templates/auth/` 目錄

- [ ] 實作登入頁面模板
  - [ ] 創建 `app/templates/auth/login.html`
  - [ ] 設計簡潔的登入表單 UI
  - [ ] 整合 Bootstrap 5 樣式
  - [ ] 加入多語系支援（i18n）
  - [ ] 實作響應式設計（手機版相容）

- [ ] 實作登入頁面功能
  - [ ] 使用者名稱/密碼輸入欄位
  - [ ] 記住登入 checkbox
  - [ ] 登入按鈕與載入狀態
  - [ ] 錯誤訊息顯示區域
  - [ ] 忘記密碼提示（管理員聯繫）

### 🎨 Task 15: 實作登入頁面路由與邏輯
- [ ] 在 `app/main.py` 加入登入頁面路由
  - [ ] 實作 `GET /login` 路由
  - [ ] 檢查已登入狀態，自動重導向首頁
  - [ ] 處理登入成功後的重導向邏輯

- [ ] 建立登入頁面專用 JavaScript
  - [ ] 創建 `app/static/js/login.js`
  - [ ] 實作登入表單提交邏輯
  - [ ] 實作 API 呼叫與錯誤處理
  - [ ] 實作 Token 儲存與頁面重導向（僅用記憶體或 sessionStorage，避免 localStorage）
  - [ ] 實作載入狀態與使用者回饋

### 🎨 Task 16: 實作主導航認證整合
- [ ] 更新主導航模板
  - [ ] 修改 `app/templates` 中的 base 模板
  - [ ] 加入使用者資訊顯示區域
  - [ ] 加入登出按鈕
  - [ ] 根據使用者角色顯示/隱藏選單項目
  - [ ] 語系文案集中於 `app/static/js/i18n/`（避免硬編碼）

- [ ] 更新導航 JavaScript
  - [ ] 修改現有的 navigation.js 或建立新的
  - [ ] 實作使用者資訊取得邏輯
  - [ ] 實作登出功能
  - [ ] 實作權限檢查與選單控制（頁面切換時重新校驗）

---

## 階段六：既有 API 權限整合

### 🔒 Task 17: 更新 Teams API 權限
- [ ] 修改 `app/api/teams.py`
  - [ ] 所有端點加入使用者認證檢查
  - [ ] `GET /api/teams` 僅返回有權限的團隊
  - [ ] `POST /api/teams` 僅 Admin+ 可建立
  - [ ] `PUT /api/teams/{team_id}` 檢查團隊管理權限
  - [ ] `DELETE /api/teams/{team_id}` 僅 Super Admin 可刪除
  - [ ] 加入審計記錄（Team Setting CRUD）

### 🔒 Task 18: 更新 Test Cases API 權限
- [ ] 修改 `app/api/test_cases.py`
  - [ ] 所有端點加入團隊權限檢查
  - [ ] `GET` 端點檢查 READ 權限
  - [ ] `POST, PUT, DELETE` 端點檢查 WRITE 權限
  - [ ] 加入審計記錄（Test Case CRUD）

### 🔒 Task 19: 更新 Test Run 相關 API 權限
- [ ] 修改 `app/api/test_run_configs.py`
  - [ ] 所有端點加入團隊權限檢查
  - [ ] 權限檢查邏輯與 test_cases 一致
  - [ ] 加入審計記錄（Test Run CRUD）

- [ ] 修改 `app/api/test_run_items.py`
  - [ ] 同上權限檢查邏輯
  - [ ] 加入審計記錄

- [ ] 修改 `app/api/test_runs.py`
  - [ ] 同上權限檢查邏輯
  - [ ] 加入審計記錄

### 🔒 Task 20: 更新其他 API 端點權限
- [ ] 檢查並更新以下 API 端點：
  - [ ] `app/api/attachments.py` - 嚴格走權限檢查（不得開白名單）
  - [ ] `app/api/contacts.py` - 基於團隊權限
  - [ ] `app/api/jira.py` - 基於團隊權限
  - [ ] `app/api/admin.py` - 僅 Super Admin 可存取
  - [ ] `app/api/organization_sync.py` - 僅 Admin+ 可存取

---

## 階段七：管理頁面實作

### 🎨 Task 21: 建立使用者管理頁面
- [ ] 實作使用者管理頁面
  - [ ] 創建 `app/templates/auth/user_management.html`
  - [ ] 實作使用者列表表格
  - [ ] 實作新增使用者 Modal
  - [ ] 實作編輯使用者 Modal
  - [ ] 實作密碼重設功能
  - [ ] 實作角色變更功能
  - [ ] 僅 Admin+ 可見此頁面

- [ ] 在 `app/main.py` 加入使用者管理頁面路由
  - [ ] 實作 `GET /user-management` 路由
  - [ ] 加入權限檢查（Admin+）

### 🎨 Task 22: 建立權限管理頁面
- [ ] 實作團隊權限管理介面
  - [ ] 在團隊管理頁面加入權限管理區塊
  - [ ] 實作成員權限列表
  - [ ] 實作權限授予/撤銷功能
  - [ ] 實作跨團隊權限管理

### 🎨 Task 23: 建立審計頁面
- [ ] 建立審計相關模板目錄
  - [ ] 創建 `app/templates/audit/` 目錄

- [ ] 實作審計記錄頁面
  - [ ] 創建 `app/templates/audit/audit_logs.html`
  - [ ] 實作審計記錄表格
  - [ ] 實作進階搜尋功能
  - [ ] 實作 CSV 匯出功能
  - [ ] 實作時間範圍篩選

- [ ] 在 `app/main.py` 加入審計頁面路由
  - [ ] 實作 `GET /audit-logs` 路由
  - [ ] 加入權限檢查（Admin+）

---

## 階段八：前端 JavaScript 整合

### ⚡ Task 24: 實作前端認證服務
- [ ] 建立 `app/static/js/auth.js`
  - [ ] 實作 `AuthService` 類別
  - [ ] 實作 Token 儲存與管理
  - [ ] 實作自動登出機制
  - [ ] 實作權限檢查函式
  - [ ] 實作 401/403 錯誤處理

### ⚡ Task 25: 更新既有頁面權限控制
- [ ] 更新各個頁面的 JavaScript
  - [ ] `app/static/js/team_management.js` - 加入權限檢查
  - [ ] `app/static/js/test_case_management.js` - 加入權限檢查  
  - [ ] `app/static/js/test_run_management.js` - 加入權限檢查
  - [ ] `app/static/js/test_run_execution.js` - 加入權限檢查

---

## 階段九：認證中介軟體與路由整合

### 🛣️ Task 26: 實作認證中介軟體
- [ ] 建立 `app/middleware/auth_middleware.py`
  - [ ] 實作全域認證檢查中介軟體
  - [ ] 實作白名單機制（/login、/health、/static/*、/reports/*）
  - [ ] 實作自動重導向邏輯（未認證→登入頁）
  - [ ] 整合到 FastAPI 應用程式

### 🛣️ Task 27: 更新路由註冊
- [ ] 更新 `app/api/__init__.py`
  - [ ] 加入新的認證相關路由
  - [ ] 加入使用者管理路由
  - [ ] 加入權限管理路由
  - [ ] 加入會話管理路由
  - [ ] 加入審計路由

---

## 階段十：資料庫遷移與初始化

### 🔄 Task 28: 建立資料庫遷移腳本與備份
- [ ] 創建 `scripts/migrate_add_auth_system.py`
  - [ ] 遷移前自動備份 DB（test_case_repo.db、audit.db）
  - [ ] 檢查現有資料庫結構（可重入）
  - [ ] 建立新的認證表格（users、user_team_permissions、active_sessions）
  - [ ] 建立獨立審計資料庫與索引
  - [ ] 建立預設 Super Admin 帳號（臨時密碼）
  - [ ] 驗證遷移結果（事務性，出錯回滾）

- [ ] 更新 `database_init.py`
  - [ ] 整合認證表格建立與索引
  - [ ] 整合審計資料庫建立
  - [ ] 加入預設資料初始化

### 🔄 Task 29: 建立 Lark 同步整合
- [ ] 更新 Lark 使用者同步服務
  - [ ] 修改使用者同步時自動建立對應 User 記錄
  - [ ] 實作 Lark User 與系統 User 的關聯邏輯
  - [ ] 確保同步過程不影響既有功能

---

## 階段十一：測試與驗證

### 🧪 Task 30: 實作測試
- [ ] 建立測試目錄結構
  - [ ] 創建 `app/tests/auth/`
  - [ ] 創建 `app/tests/audit/`

- [ ] 單元/整合測試
  - [ ] 測試 JWT Token 生成與驗證（含 jti）
  - [ ] 測試密碼雜湊與驗證
  - [ ] 測試權限矩陣（4 角色 × 3 資源 × 讀/寫）
  - [ ] 401 vs 403 行為：無 Token → 401；無權限 → 403
  - [ ] 踢人：Super Admin 撤銷 jti 後，下一請求被拒絕

- [ ] 流程/E2E 測試
  - [ ] 登入→存取受保護資源→登出
  - [ ] 權限不足時的錯誤處理
  - [ ] Token 過期時的自動處理

### 🧪 Task 31: 整合測試與相容性驗證
- [ ] 測試與現有功能的相容性
  - [ ] 確保 Lark 同步功能正常
  - [ ] 確保既有 API 端點功能正常
  - [ ] 確保既有前端頁面正常運作

- [ ] 效能與安全性測試
  - [ ] 權限檢查響應時間測試
  - [ ] 審計寫入壓力測試（驗證隊列上限與降級）
  - [ ] 並發使用者認證測試
  - [ ] 簡易暴力登入速率限制（可選）

---

## 階段十二：文件與部署

### 📚 Task 32: 更新文件與部署準備
- [ ] 更新 README.md
  - [ ] 加入認證系統說明（Bearer Token、風險與取捨）
  - [ ] 更新安裝指南與環境變數（JWT_SECRET_KEY）
  - [ ] 加入初始管理員設定說明

- [ ] 更新 WARP.md
  - [ ] 加入認證系統開發指南
  - [ ] 加入常用開發指令

- [ ] 更新運維腳本
  - [ ] `start.sh` 啟動前先執行遷移（非破壞性）
  - [ ] 設定 JSON 結構化日誌輸出（認證/權限拒絕）

- [ ] 最終驗證與部署準備
  - [ ] 完整功能測試（含登入頁面）
  - [ ] 確保所有頁面都有適當的認證保護
  - [ ] 驗證登入/登出流程完整運作
  - [ ] 健康檢查 `/health` 僅回傳狀態，無機敏資訊

---

## 總計任務統計

- **總任務數**: 32 個主要任務
- **預估開發時間**: 15-20 工作天
- **登入系統重點任務**: Task 14-16 (登入頁面實作)
- **關鍵里程碑**: 
  - 階段一~三：基礎架構建立 (4-5天)
  - 階段四：API 實作 (2-3天)
  - **階段五：登入系統實作 (2-3天) ⭐**
  - 階段六：既有 API 權限整合 (3-4天)
  - 階段七：管理頁面實作 (2-3天)
  - 階段八~十二：整合、測試與部署 (3-4天)

## 前端登入系統核心要求

1. **登入頁面** (`/login`): 獨立的登入頁面，包含帳密輸入與記住登入功能
2. **認證中介軟體**: 自動檢查認證狀態，未登入自動重導向登入頁
3. **主導航整合**: 顯示使用者資訊、登出按鈕、根據角色控制選單
4. **Token 管理**: JavaScript 端的 Token 儲存、過期檢查、自動刷新

## 緊急回滾計劃

如遇重大問題，可依以下順序回滾：
1. 停用認證中介軟體 (Task 26)
2. 移除 API 權限檢查 (Task 17-20)
3. 使用 git 回退到實作前的版本