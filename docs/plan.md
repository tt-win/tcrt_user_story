# Authentication Integration Implementation Plan

基於已完成的認證與權限服務，本計劃將其整合到主應用程式中。

## 已完成的基礎建設 ✅

1. **認證系統** (app/auth/)
   - JWT 服務 (auth_service.py)
   - Session 管理 (session_service.py)  
   - 密碼服務 (password_service.py)
   - 權限服務 (permission_service.py)
   - 認證依賴 (dependencies.py)
   - 資料模型 (models.py)

2. **資料庫模型** (app/models/database_models.py)
   - User 表格
   - UserSession 表格
   - UserTeamPermission 表格
   - PasswordResetToken 表格

3. **測試驗證** ✅
   - 認證系統整合測試通過
   - 權限服務整合測試通過

## 實作階段

### 階段 1: 後端 API 整合

#### 1.1 建立認證 API 端點
**目標**: 提供前端使用的認證 API
**檔案**: `app/api/auth.py`

**端點設計**:
- `POST /api/auth/login` - 使用者登入
  - 輸入: username/email + password
  - 輸出: access_token, refresh_token, user_info
- `POST /api/auth/logout` - 使用者登出
  - 清除 session 記錄
- `POST /api/auth/refresh` - 刷新 token
  - 輸入: refresh_token
  - 輸出: 新的 access_token
- `GET /api/auth/me` - 取得使用者資訊
  - 輸出: user_info + permissions + accessible_teams

#### 1.2 建立使用者管理 API
**目標**: 提供管理員管理使用者的功能
**檔案**: `app/api/users.py`

**端點設計**:
- `GET /api/users/` - 列出使用者 (需 ADMIN+ 權限)
- `POST /api/users/` - 建立使用者 (需 SUPER_ADMIN 權限)
- `PUT /api/users/{user_id}` - 更新使用者 (需 ADMIN+ 權限)
- `DELETE /api/users/{user_id}` - 刪除使用者 (需 SUPER_ADMIN 權限)

#### 1.3 強化認證依賴
**目標**: 提供便利的權限檢查依賴
**檔案**: `app/auth/dependencies.py` (增強)

**新增依賴**:
- `get_current_user()` - 取得目前使用者
- `require_role(role: UserRole)` - 要求特定角色
- `require_team_permission(team_id: int, permission: PermissionType)` - 要求團隊權限

### 階段 2: 現有 API 權限整合

#### 2.1 團隊管理 API 權限
**檔案**: `app/api/teams.py`
- GET 操作: 需要 USER+ 權限
- 建立/更新: 需要 ADMIN+ 權限或團隊 ADMIN 權限
- 刪除: 需要 SUPER_ADMIN 權限

#### 2.2 測試案例 API 權限  
**檔案**: `app/api/test_cases.py`
- GET 操作: 需要團隊 READ+ 權限
- 寫入操作: 需要團隊 WRITE+ 權限
- 管理操作: 需要團隊 ADMIN 權限

#### 2.3 測試執行 API 權限
**檔案**: `app/api/test_run_*.py`
- 查詢: 需要團隊 READ+ 權限
- 執行/更新: 需要團隊 WRITE+ 權限
- 管理: 需要團隊 ADMIN 權限

### 階段 3: 前端整合

#### 3.1 登入頁面
**目標**: 建立使用者登入介面
**檔案**: `app/templates/login.html`

**功能**:
- 使用者名稱/密碼輸入表單
- 記住登入選項
- 錯誤訊息顯示
- 自動跳轉邏輯

#### 3.2 主頁面認證整合
**檔案**: `app/templates/*.html`

**修改項目**:
- 加入使用者資訊顯示區塊
- 登出按鈕
- 未登入時跳轉登入頁面
- 基於權限顯示/隱藏 UI 元素

#### 3.3 JavaScript 認證邏輯
**檔案**: `app/static/js/auth.js`

**功能**:
- Token 儲存與管理
- 自動 token 刷新
- API 請求攔截器 (自動帶入 Authorization header)
- 認證狀態管理
- 未授權處理邏輯

### 階段 4: 安全強化

#### 4.1 中間件整合
**目標**: 統一的認證中間件
**檔案**: `app/middleware/auth.py` (新建)

**功能**:
- 自動 JWT 驗證
- 統一錯誤處理
- 安全 Headers 設定

#### 4.2 CORS 與安全設定
**檔案**: `app/main.py`

**配置**:
- CORS 中間件設定
- 安全 Headers
- Cookie 安全設定 (HttpOnly, SameSite)

### 階段 5: 測試與驗證

#### 5.1 API 整合測試
**檔案**: `tests/api/test_auth_integration.py`

**測試範圍**:
- 登入/登出流程
- Token 刷新機制
- 權限保護的 API 端點
- 錯誤處理場景

#### 5.2 前端測試 (選配)
**工具**: Playwright
**測試範圍**:
- 登入流程
- 權限控制 UI
- 自動跳轉邏輯

## 風險與緩解策略

### 風險 1: 現有功能受影響
**緩解**: 
- 逐步導入權限檢查
- 保持向下相容
- 充分測試現有流程

### 風險 2: 效能影響
**緩解**:
- 使用權限快取
- 非同步處理
- 效能監控

### 風險 3: 安全漏洞
**緩解**:
- JWT 最佳實作
- 輸入驗證
- 安全測試

## 交付物清單

### 後端交付物
- [ ] `app/api/auth.py` - 認證 API 端點
- [ ] `app/api/users.py` - 使用者管理 API
- [ ] 增強的 `app/auth/dependencies.py`
- [ ] 整合權限的現有 API 檔案
- [ ] `app/middleware/auth.py` - 認證中間件

### 前端交付物  
- [ ] `app/templates/login.html` - 登入頁面
- [ ] 修改的主要模板檔案
- [ ] `app/static/js/auth.js` - 認證邏輯
- [ ] 修改的 CSS 樣式

### 測試交付物
- [ ] API 整合測試
- [ ] 權限檢查測試
- [ ] 前端流程測試 (選配)

### 文件交付物
- [ ] API 文件更新
- [ ] 部署指南
- [ ] 使用者手冊

## 里程碑

1. **M1 - 後端 API 完成** (預估 2-3 天)
   - 認證 API 端點實作完成
   - 現有 API 權限整合完成
   - 基本測試通過

2. **M2 - 前端整合完成** (預估 1-2 天)  
   - 登入頁面完成
   - 主頁面認證整合完成
   - JavaScript 認證邏輯完成

3. **M3 - 系統完整測試** (預估 1 天)
   - 端到端測試通過
   - 效能測試通過
   - 安全測試通過

## 成功標準

1. ✅ 使用者可以正常登入/登出
2. ✅ 權限檢查正確運作
3. ✅ 現有功能正常運作
4. ✅ API 回應時間不受顯著影響  
5. ✅ 所有測試通過
6. ✅ 安全性要求符合規格

## 後續優化 (Phase 2)

1. 密碼重設功能
2. 使用者管理 UI
3. 權限管理介面
4. 審計日誌查詢介面
5. 批次使用者操作