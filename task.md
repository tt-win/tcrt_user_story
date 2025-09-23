# Authentication Integration Task List

## 階段 1: 後端 API 整合

### 任務 1.1: 建立認證 API 端點

#### ☐ 建立 app/api/auth.py
- ☐ 實作 POST /api/auth/login
  - 驗證 username/email 和 password
  - 使用 auth_service 驗證使用者
  - 使用 session_service 建立 session
  - 返回 JWT tokens 和使用者資訊
- ☐ 實作 POST /api/auth/logout
  - 驗證當前 JWT token
  - 使用 session_service 清除 session
  - 返回成功訊息
- ☐ 實作 POST /api/auth/refresh
  - 驗證 refresh_token
  - 使用 session_service 刷新 session
  - 返回新的 access_token
- ☐ 實作 GET /api/auth/me
  - 驗證當前 JWT token
  - 使用 permission_service 取得權限摘要
  - 返回使用者資訊、權限和可存取團隊

#### ☐ 將 auth.py 加入 API 路由
- ☐ 修改 app/api/__init__.py
- ☐ 導入 auth router
- ☐ 加入到 api_router

### 任務 1.2: 建立使用者管理 API

#### ☐ 建立 app/api/users.py
- ☐ 實作 GET /api/users/ (需要 ADMIN+ 權限)
  - 支援分頁、搜尋、篩選
  - 返回使用者清單
- ☐ 實作 POST /api/users/ (需要 SUPER_ADMIN 權限)
  - 驗證輸入資料
  - 建立新使用者
  - 自動生成初始密碼
- ☐ 實作 PUT /api/users/{user_id} (需要 ADMIN+ 權限)
  - 更新使用者基本資訊
  - 角色變更 (限 SUPER_ADMIN)
  - 密碼重設功能
- ☐ 實作 DELETE /api/users/{user_id} (需要 SUPER_ADMIN 權限)
  - 軟刪除使用者 (設定 is_active = false)

#### ☐ 將 users.py 加入 API 路由
- ☐ 修改 app/api/__init__.py
- ☐ 導入 users router
- ☐ 加入到 api_router

### 任務 1.3: 強化認證依賴

#### ☐ 增強 app/auth/dependencies.py
- ☐ 實作 get_current_user() 依賴
  - 從 Authorization header 取得 JWT token
  - 使用 auth_service 驗證 token
  - 返回 User 物件或拋出 401 錯誤
- ☐ 實作 require_role(role: UserRole) 依賴工廠
  - 檢查使用者角色是否符合要求
  - 拋出 403 錯誤如果權限不足
- ☐ 實作 require_team_permission(team_id, permission) 依賴工廠
  - 使用 permission_service 檢查團隊權限
  - 拋出 403 錯誤如果權限不足
- ☐ 實作統一錯誤處理
  - 401 Unauthorized 錯誤回應
  - 403 Forbidden 錯誤回應
  - 422 Validation Error 錯誤回應

## 階段 2: 現有 API 權限整合

### 任務 2.1: 團隊管理 API 權限整合

#### ☐ 修改 app/api/teams.py
- ☐ 在 GET /teams/ 加入 require_role(UserRole.USER)
- ☐ 在 POST /teams/ 加入 require_role(UserRole.ADMIN)
- ☐ 在 PUT /teams/{id} 加入複合權限檢查
  - ADMIN+ 權限 OR 該團隊 ADMIN 權限
- ☐ 在 DELETE /teams/{id} 加入 require_role(UserRole.SUPER_ADMIN)
- ☐ 修改團隊列表 API 只返回使用者有權限的團隊

### 任務 2.2: 測試案例 API 權限整合

#### ☐ 修改 app/api/test_cases.py
- ☐ 分析現有端點並分類權限需求
- ☐ GET 操作加入團隊 READ+ 權限檢查
- ☐ POST/PUT 操作加入團隊 WRITE+ 權限檢查
- ☐ DELETE 操作加入團隊 ADMIN 權限檢查
- ☐ 確保只能存取有權限的團隊資料

### 任務 2.3: 測試執行 API 權限整合

#### ☐ 修改 app/api/test_run_configs.py
- ☐ 查詢操作加入團隊 READ+ 權限檢查
- ☐ 建立/更新操作加入團隊 WRITE+ 權限檢查
- ☐ 管理操作加入團隊 ADMIN 權限檢查

#### ☐ 修改 app/api/test_run_items.py
- ☐ 查詢操作加入團隊 READ+ 權限檢查
- ☐ 執行/更新操作加入團隊 WRITE+ 權限檢查
- ☐ 批次操作加入團隊 ADMIN 權限檢查

#### ☐ 修改 app/api/test_runs.py
- ☐ 查詢操作加入團隊 READ+ 權限檢查
- ☐ 建立/更新操作加入團隊 WRITE+ 權限檢查

## 階段 3: 前端整合

### 任務 3.1: 建立登入頁面

#### ☐ 建立 app/templates/login.html
- ☐ 設計符合現有風格的登入表單
- ☐ 使用者名稱/Email 輸入欄位
- ☐ 密碼輸入欄位
- ☐ "記住我" 選項
- ☐ 登入按鈕
- ☐ 錯誤訊息顯示區域
- ☐ 載入狀態指示器

#### ☐ 在 app/main.py 加入登入頁面路由
- ☐ 新增 GET /login 路由
- ☐ 檢查是否已登入，已登入則跳轉
- ☐ 支援 redirect_url 參數

### 任務 3.2: 主頁面認證整合

#### ☐ 修改 app/templates/index.html
- ☐ 加入使用者資訊顯示區塊
- ☐ 加入登出按鈕
- ☐ 未登入狀態的處理邏輯

#### ☐ 修改其他主要模板
- ☐ 修改 app/templates/team_management.html
- ☐ 修改 app/templates/test_case_management.html  
- ☐ 修改 app/templates/test_run_management.html
- ☐ 修改 app/templates/test_run_execution.html
- ☐ 基於使用者權限顯示/隱藏功能按鈕

#### ☐ 建立共用認證元件
- ☐ 使用者資訊顯示元件 (partial)
- ☐ 登入狀態檢查元件
- ☐ 權限檢查 JavaScript helper

### 任務 3.3: JavaScript 認證邏輯

#### ☐ 建立 app/static/js/auth.js
- ☐ AuthManager 類別
  - Token 儲存與讀取 (localStorage)
  - 自動 token 刷新邏輯
  - 登入/登出狀態管理
  - 使用者資訊快取
- ☐ API 請求攔截器
  - 自動加入 Authorization header
  - 自動處理 401/403 回應
  - Token 過期自動刷新
- ☐ 頁面認證檢查
  - 頁面載入時檢查登入狀態
  - 未登入自動跳轉至登入頁面
  - 權限不足顯示適當訊息

#### ☐ 整合現有 JavaScript 檔案
- ☐ 修改 app/static/js/app.js
- ☐ 在所有 API 呼叫加入認證檢查
- ☐ 處理認證相關錯誤

## 階段 4: 安全強化

### 任務 4.1: CORS 與安全設定

#### ☐ 修改 app/main.py
- ☐ 加入 CORS 中間件配置
- ☐ 設定允許的來源、方法、標頭
- ☐ 配置安全 Headers
  - Content-Security-Policy
  - X-Frame-Options
  - X-Content-Type-Options

#### ☐ JWT 安全配置
- ☐ 確保 JWT 密鑰從環境變數讀取
- ☐ 設定適當的 token 過期時間
- ☐ 實作 token 黑名單機制 (可選)

### 任務 4.2: 錯誤處理統一化

#### ☐ 建立統一錯誤回應模型
- ☐ AuthError 例外類別
- ☐ PermissionError 例外類別
- ☐ ValidationError 例外類別

#### ☐ 全域例外處理器
- ☐ 401 Unauthorized 處理器
- ☐ 403 Forbidden 處理器  
- ☐ 422 Validation Error 處理器

## 階段 5: 測試與驗證

### 任務 5.1: API 整合測試

#### ☐ 建立 tests/api/test_auth_integration.py
- ☐ 測試登入流程
  - 有效憑證登入成功
  - 無效憑證登入失敗
  - 返回正確的 token 和使用者資訊
- ☐ 測試登出流程
  - 有效 token 登出成功
  - 無效 token 登出失敗
  - session 正確清除
- ☐ 測試 token 刷新
  - 有效 refresh_token 刷新成功
  - 無效 refresh_token 刷新失敗
  - 返回新的 access_token
- ☐ 測試 /api/auth/me
  - 有效 token 返回使用者資訊
  - 無效 token 返回 401 錯誤

#### ☐ 建立 tests/api/test_permissions.py
- ☐ 測試角色權限檢查
  - SUPER_ADMIN 可存取所有端點
  - ADMIN 可存取管理端點
  - USER 可存取一般端點
  - VIEWER 只能存取讀取端點
- ☐ 測試團隊權限檢查
  - 團隊 ADMIN 權限
  - 團隊 WRITE 權限
  - 團隊 READ 權限
  - 無權限存取拒絕

### 任務 5.2: 整合測試

#### ☐ 測試現有功能不受影響
- ☐ 運行現有測試套件
- ☐ 確保所有現有測試通過
- ☐ 測試未認證存取適當拒絕

#### ☐ 效能測試
- ☐ 權限檢查不影響 API 回應時間
- ☐ 快取機制運作正常
- ☐ 並發使用者負載測試

### 任務 5.3: 端到端測試 (選配)

#### ☐ 建立 Playwright 測試
- ☐ 登入流程測試
- ☐ 權限控制 UI 測試
- ☐ 自動跳轉測試
- ☐ 登出流程測試

## 階段 6: 文件與部署

### 任務 6.1: 文件更新

#### ☐ 更新 README.md
- ☐ 加入認證系統說明
- ☐ 更新安裝與設定步驟
- ☐ 加入初始管理員帳號設定

#### ☐ 更新 API 文件
- ☐ 記錄所有新的 API 端點
- ☐ 記錄權限要求
- ☐ 提供 API 使用範例

### 任務 6.2: 部署準備

#### ☐ 環境變數配置
- ☐ JWT_SECRET_KEY
- ☐ JWT_ACCESS_TOKEN_EXPIRE_MINUTES
- ☐ JWT_REFRESH_TOKEN_EXPIRE_DAYS

#### ☐ 資料庫初始化
- ☐ 建立初始管理員帳號腳本
- ☐ 資料庫遷移腳本
- ☐ 權限資料初始化

## 驗收標準

### 功能驗收
- ☐ 使用者可以正常登入/登出
- ☐ 不同角色使用者看到對應的功能選項
- ☐ 權限檢查正確阻止未授權存取
- ☐ Token 自動刷新機制運作正常
- ☐ 現有功能完全不受影響

### 效能驗收
- ☐ API 回應時間增加不超過 50ms
- ☐ 權限快取命中率 > 90%
- ☐ 並發 100 使用者無效能問題

### 安全驗收
- ☐ 無法繞過認證存取保護資源
- ☐ JWT token 安全配置
- ☐ 密碼正確雜湊儲存
- ☐ 輸入驗證防止注入攻擊

### 相容驗收
- ☐ 現有 API 端點保持原有行為
- ☐ 與 Lark 同步功能無衝突
- ☐ 資料庫結構向下相容