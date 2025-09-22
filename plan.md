# Role-Based 權限管理系統 - 技術實作計劃

## 架構設計概覽

基於現有 FastAPI + SQLAlchemy 架構，新增權限管理模組，採用最小侵入性原則，確保與現有 Lark 同步功能完全相容。

## 技術棧決策

### 核心技術
- **認證機制**：JWT Token (使用 PyJWT)
- **權限控制**：基於角色的存取控制 (RBAC)
- **密碼加密**：bcrypt 雜湊
- **審計資料庫**：獨立 SQLite (audit.db)
- **快取機制**：記憶體快取 (functools.lru_cache)

### 新增依賴套件
```text
PyJWT==2.8.0             # JWT Token 處理（統一採用 PyJWT）
passlib[bcrypt]==1.7.4   # 密碼雜湊
```

說明：為降低複雜度，JWT 套件統一採用 PyJWT，不再同時引入 python-jose。

## 資料庫設計

### 1. 角色與權限定義

#### 1.1 角色權限對應表

| 角色 (Role)       | 資源類型           | 權限                                           |
|----------------------|---------------------|------------------------------------------------|
| **Viewer**           | Team                | 只能讀取自己團隊及被授權團隊的基本資訊            |
|                      | Test Case          | 只能讀取自己團隊及被授權團隊的測試案例            |
|                      | Test Run           | 只能讀取自己團隊及被授權團隊的測試執行            |
|                      | Audit              | 無審計讀取權限                                |
| **User**             | Team                | 讀取自己團隊及被授權團隊的基本資訊                |
|                      | Test Case          | 完整 CRUD 操作（自己團隊及被授權團隊）                |
|                      | Test Run           | 完整 CRUD 操作（自己團隊及被授權團隊）                |
|                      | Audit              | 無審計讀取權限                                |
| **Admin**            | Team                | 完整 CRUD 操作（設定管理、團隊成員管理）              |
|                      | Test Case          | 完整 CRUD 操作（包含 User 全部權限）                |
|                      | Test Run           | 完整 CRUD 操作（包含 User 全部權限）                |
|                      | Audit              | 可檢視自己團隊的審計記錄                         |
|                      | Users              | 可管理自己團隊的使用者和密碼                      |
| **Super Admin**      | Team                | 完整 CRUD 操作（所有團隊）                         |
|                      | Test Case          | 完整 CRUD 操作（所有團隊）                         |
|                      | Test Run           | 完整 CRUD 操作（所有團隊）                         |
|                      | Audit              | 可檢視所有團隊的審計記錄                         |
|                      | Users              | 可管理所有使用者和密碼                           |
|                      | Sessions           | 可踩掉線上使用者                                |

### 2. 角色定義 (Enum)

#### 2.1 UserRole 枚舉
```python
# app/auth/models.py
from enum import Enum

class UserRole(str, Enum):
    VIEWER = "viewer"        # 檢視者：只能檢視
    USER = "user"            # 使用者：可進行 CRUD 操作
    ADMIN = "admin"          # 團隊管理員：可管理團隊設定與成員
    SUPER_ADMIN = "super_admin"  # 超級管理員：系統所有權限
```

#### 2.2 PermissionType 枚舉
```python
# app/auth/models.py
class PermissionType(str, Enum):
    READ = "read"            # 檢視權限
    WRITE = "write"          # 寫入權限（包含 CREATE/UPDATE/DELETE）
    ADMIN = "admin"          # 管理權限（團隊設定、成員管理）
```

#### 2.3 ActionType 枚舉（審計用）
```python
# app/audit/models.py
class ActionType(str, Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

class ResourceType(str, Enum):
    TEAM_SETTING = "team_setting"
    TEST_RUN = "test_run"
    TEST_CASE = "test_case"
```

### 3. 主資料庫 (test_case_repo.db) 新增表格

#### 3.1 users 表格
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    lark_user_id VARCHAR(100) NULL,  -- 關聯 LarkUser
    role VARCHAR(20) NOT NULL,       -- 'viewer', 'user', 'admin', 'super_admin'
    primary_team_id INTEGER NULL,   -- 關聯 Team 表格
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER NULL,         -- 關聯建立者
    FOREIGN KEY (lark_user_id) REFERENCES lark_users(user_id),
    FOREIGN KEY (primary_team_id) REFERENCES teams(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    CHECK (role IN ('viewer', 'user', 'admin', 'super_admin'))
);
```

#### 3.2 user_team_permissions 表格（跨團隊權限）
```sql
CREATE TABLE user_team_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    permission_type VARCHAR(10) NOT NULL,  -- 'read', 'write', 'admin'
    CHECK (permission_type IN ('read', 'write', 'admin')),
    granted_by INTEGER NOT NULL,      -- 授權者
    granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (team_id) REFERENCES teams(id),
    FOREIGN KEY (granted_by) REFERENCES users(id),
    UNIQUE(user_id, team_id)
);
```

#### 3.3 active_sessions 表格（會話管理）
```sql
CREATE TABLE active_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_jti VARCHAR(255) NOT NULL UNIQUE,  -- JWT ID
    issued_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    user_agent VARCHAR(500) NULL,
    ip_address VARCHAR(45) NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### 4. 審計資料庫 (audit.db)

#### 審計資料最小化與隱私
- 不記錄敏感資料（密碼、完整 Token、PII）。
- details 僅存必要差異欄位，並可遮罩。
- 時間一律採用伺服器 UTC；匯出時可選時區轉換。

#### 4.1 audit_logs 表格
```sql
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL,
    username VARCHAR(100) NOT NULL,
    action_type VARCHAR(10) NOT NULL,   -- 'CREATE', 'READ', 'UPDATE', 'DELETE'
    resource_type VARCHAR(20) NOT NULL, -- 'team_setting', 'test_run', 'test_case'
    resource_id VARCHAR(100) NOT NULL,
    team_id INTEGER NOT NULL,
    details TEXT NULL,                -- JSON 格式操作詳情
    ip_address VARCHAR(45) NULL,
    user_agent VARCHAR(500) NULL,
    INDEX ix_audit_user_time (user_id, timestamp),
    INDEX ix_audit_team_time (team_id, timestamp),
    INDEX ix_audit_resource (resource_type, resource_id)
);
```

## API 架構設計

### 1. 認證 & 權限模組結構

```
app/
├── auth/
│   ├── __init__.py
│   ├── models.py          # 認證相關資料模型
│   ├── auth_service.py    # 認證服務
│   ├── permission_service.py  # 權限檢查服務
│   ├── password_service.py    # 密碼管理服務
│   └── dependencies.py    # FastAPI 依賴注入
├── audit/
│   ├── __init__.py
│   ├── models.py          # 審計資料模型
│   ├── audit_service.py   # 審計記錄服務
│   └── database.py        # 審計資料庫引擎
```

### 2. API 端點設計

#### 2.1 認證 API (/api/auth/)
```python
POST /api/auth/login           # 使用者登入
POST /api/auth/logout          # 使用者登出
POST /api/auth/refresh-token   # 重新整理 Token
GET  /api/auth/me              # 取得目前使用者資訊
POST /api/auth/change-password # 變更密碼
```

#### 2.2 使用者管理 API (/api/users/)
```python
GET    /api/users              # 列出使用者（Admin+）
POST   /api/users              # 建立使用者（Admin+）
GET    /api/users/{user_id}    # 取得使用者資訊
PUT    /api/users/{user_id}    # 更新使用者資訊
DELETE /api/users/{user_id}    # 刪除使用者（Super Admin）
POST   /api/users/{user_id}/reset-password  # 重設密碼（Admin+）
```

#### 2.3 權限管理 API (/api/permissions/)
```python
GET  /api/permissions/teams/{team_id}/users    # 團隊成員權限列表
POST /api/permissions/teams/{team_id}/users    # 授予團隊權限
PUT  /api/permissions/teams/{team_id}/users/{user_id}  # 修改權限
DELETE /api/permissions/teams/{team_id}/users/{user_id}  # 撤銷權限
```

#### 2.4 會話管理 API (/api/sessions/)
```python
GET    /api/sessions           # 線上使用者列表（Super Admin）
DELETE /api/sessions/{user_id} # 踢掉指定使用者（Super Admin）
```

#### 2.5 審計 API (/api/audit/)
```python
GET /api/audit/logs            # 審計記錄列表
GET /api/audit/logs/export     # 匯出審計記錄（CSV）
```

### 3. 權限檢查裝飾器設計

#### 3.1 FastAPI 依賴注入
```python
# app/auth/dependencies.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer

async def get_current_user(token: str = Security(HTTPBearer())) -> User:
    """取得目前登入使用者"""
    pass

async def require_role(required_role: UserRole):
    """檢查使用者角色權限"""
    def dependency(current_user: User = Depends(get_current_user)):
        if not has_role_permission(current_user.role, required_role):
            raise HTTPException(403, "權限不足")
        return current_user
    return dependency

async def require_team_permission(team_id: int, required_permission: str):
    """檢查團隊權限"""
    def dependency(current_user: User = Depends(get_current_user)):
        if not has_team_permission(current_user, team_id, required_permission):
            raise HTTPException(403, "無權限存取此團隊")
        return current_user
    return dependency
```

#### 3.2 權限檢查應用範例
```python
# 既有 API 端點加入權限檢查
@router.get("/teams/{team_id}/test-cases")
async def get_test_cases(
    team_id: int,
    current_user: User = Depends(require_team_permission(team_id, "read"))
):
    pass

@router.post("/teams/{team_id}/test-cases") 
async def create_test_case(
    team_id: int,
    current_user: User = Depends(require_team_permission(team_id, "write"))
):
    pass
```

## 前端整合設計

### 1. 登入頁面
- **路徑**：`/login`
- **模板**：`app/templates/auth/login.html`
- **功能**：使用者名稱/密碼登入，記住登入選項

### 2. 權限管理頁面
- **路徑**：`/user-management`（Admin+ 可見）
- **模板**：`app/templates/auth/user_management.html`
- **功能**：使用者 CRUD、密碼重設、權限授予

### 3. 審計頁面
- **路徑**：`/audit-logs`（Admin+ 可見）
- **模板**：`app/templates/audit/audit_logs.html`
- **功能**：審計記錄檢視、搜尋、匯出

### 4. JavaScript 權限控制
```javascript
// app/static/js/auth.js
class AuthService {
    static async checkPermission(resource, action) {
        // 檢查使用者權限，控制 UI 元素顯示
    }
    
    static async getCurrentUser() {
        // 取得目前使用者資訊
    }
    
    static handleUnauthorized() {
        // 處理權限不足，重導向登入頁
    }
}
```

## 與現有系統整合策略

### 0. 中介軟體白名單
- 白名單：/login、/health、/static/*、/reports/*。
- attachments 不在白名單，必須走權限檢查（涉及私檔）。

### 1. 資料庫整合

### 1. 資料庫整合
- **現有表格**：不修改任何現有表格結構
- **關聯設計**：透過 `lark_user_id` 關聯既有 `LarkUser` 表格
- **Team 關聯**：透過 `primary_team_id` 關聯既有 `Team` 表格

### 2. API 相容性
- 既有端點：保持所有現有 API 端點不變。
- 權限注入：在既有路由中加入權限檢查依賴。
- 錯誤處理：統一 401/403 回應結構（code、message），前端依此處理重導向與提示。

### 3. Lark 同步相容性
- User 同步：`LarkUser` 同步時自動檢查/建立對應的 `User` 記錄。
- Department 同步：`LarkDepartment` 與 `Team` 的關聯保持不變。
- 內部任務呼叫：若 scheduler 需 loopback 呼叫 API，使用內部憑證或繞過中介軟體的內部白名單機制。

## 安全性考量

### 0. RBAC 衝突與預設策略
- 預設拒絕：無明確授權時一律 403。
- 衝突解決：以資源所屬團隊的「精確授權」為最高優先；若無，回退到使用者的主團隊角色；再無則拒絕。
- 資源歸屬判定：統一經由服務層函式取得 team_id，避免重複且不一致的判定邏輯。

### 1. Token 與傳遞安全
- JWT 密鑰：必須由環境變數提供，定期輪換；config.yaml.example 僅保留占位。
- Token 內容：僅包含必要資訊（user_id, role, exp, jti）。
- 傳遞方式：統一使用 Authorization: Bearer <token>；前端「記住登入」僅建議 sessionStorage 或記憶體，不使用長期 localStorage。
- 非 HTTPS 風險：在僅 HTTP 的環境下，請明確知悉 Token 攔截風險；若改用 httpOnly Cookie，則必須加上 CSRF 防護，且依舊受 HTTP 環境限制。
- JTI 黑名單：所有受保護端點在依賴中需比對 token 的 jti 是否被撤銷（支援 Super Admin 踢人）。
- Refresh Token：可選，短期 Access + 長期 Refresh 方案；若未採用，則以較短存活時間與重新登入替代。

### 2. 密碼安全
- 雜湊演算法：bcrypt，cost factor = 12。
- 密碼規則：最少 8 字元，包含數字與字母。
- 重設機制：僅 Admin+ 可重設他人密碼；Audit 僅記錄行為，不記錄新密碼。

### 3. 會話管理
- 會話記錄：所有活動會話記錄於 active_sessions（含 jti、issued_at、expires_at、UA、IP）。
- 自動清理：背景排程定期清理過期會話與撤銷記錄。
- 強制登出：Super Admin 可即時撤銷特定 jti；下一次請求即被拒絕。

## 效能優化策略

### 1. 權限檢查快取
- 使用者與團隊權限：記憶體快取 TTL 5 分鐘。
- 快取失效：權限變更（授予/撤銷）時，透過 permission_service.clear_cache(user_id, team_id) 主動清除。

### 2. 審計寫入優化
- 非同步寫入：背景任務批次寫入；提供隊列上限（backpressure）與降級策略，避免高峰期記憶體膨脹。
- 批次寫入：累積多筆記錄後批次寫入。
- 索引優化：針對常用查詢建立複合索引。

### 3. 資料庫分離
- 讀寫分離：審計資料庫獨立，避免影響主系統。
- 定期歸檔：舊審計記錄定期歸檔或清理；匯出時採欄位白名單，支援 CSV（可選 BOM）與 JSON。

## 設定檔擴展

### config.yaml 新增項目
```yaml
app:
  # 既有設定...
  enable_auth: true
  jwt_secret_key: "${JWT_SECRET_KEY_ENV}"   # 必須由環境變數提供
  jwt_expire_days: 7
  password_reset_expire_hours: 24
  session_cleanup_days: 30

audit:
  enable_audit: true
  database_url: "sqlite:///./audit.db"
  batch_size: 100
  cleanup_days: 365
```

注意：jwt_secret_key 僅作占位；實際值必須來自環境變數。

## 部署考量

### 0. 遷移與備援
- 遷移腳本需具備「全或無」交易性，出錯回滾並回報。
- 可重入（idempotent）：已存在之表/欄位需跳過並提示。
- 遷移前先備份資料庫（test_case_repo.db、audit.db），並提供回復步驟說明。

### 1. 資料庫遷移
- 建立遷移腳本：`scripts/migrate_add_auth_system.py`
- 預設管理員帳號建立（Super Admin）。
- 既有資料相容性檢查與索引建立。

### 2. 初始化設定
- Super Admin 帳號初始化（產出臨時密碼，要求首次登入變更）。
- 預設角色權限設定。
- 審計資料庫建立與索引建立。

### 3. 向下相容性
- 既有功能完全不受影響；權限系統可灰度啟用（enable_auth）。
- 緊急關閉權限檢查開關可回退至原行為。
