# User Story Map 權限管理實現

## 概述
為 User Story Map (USM) 功能添加角色型權限控制，Viewer 角色只能查看，無法進行 CRUD 操作。

## 修改內容

### 1. 後端 API 權限檢查

#### `app/api/user_story_maps.py`

**新增導入**:
```python
from app.auth.permission_service import permission_service
from app.auth.models import PermissionType, UserRole
```

**修改的端點**:

1. **GET /team/{team_id}** - 讀取
   - 檢查 `PermissionType.READ`
   - 所有角色都可以讀取（Viewer 包含）

2. **POST /** - 建立
   - 禁止 Viewer 角色
   - 檢查 `PermissionType.WRITE`
   - 必須有團隊寫入權限

3. **PUT /{map_id}** - 更新
   - 禁止 Viewer 角色
   - 檢查 `PermissionType.WRITE`
   - 必須有團隊寫入權限

4. **DELETE /{map_id}** - 刪除
   - 禁止 Viewer 角色
   - 檢查 `PermissionType.WRITE`
   - 必須有團隊寫入權限

**權限檢查代碼示例**:
```python
# Viewer 無法執行 CRUD
if current_user.role == UserRole.VIEWER:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Viewer 無權限執行此操作",
    )

# 檢查團隊權限
perm_check = await permission_service.check_permission_by_team(
    current_user.id, team_id, PermissionType.WRITE, current_user.role
)
if not perm_check.has_permission:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="無權限在此團隊執行操作",
    )
```

### 2. 前端權限管理

#### `app/static/js/user_story_map.js`

**新增函數**:
```javascript
// 檢查是否為 Viewer
function isViewer() {
    const userRole = localStorage.getItem('user_role');
    return userRole === 'viewer';
}

// 禁用 CRUD 按鈕
function disableUsmCrudActions() {
    if (!isViewer()) return;
    
    const crudButtons = [
        'newMapBtn',      // 新增地圖
        'saveMapBtn',     // 保存地圖
        'confirmAddNodeBtn', // 確認新增節點
        'calcTicketsBtn',  // 計算票證
    ];
    
    crudButtons.forEach(btnId => {
        const btn = document.getElementById(btnId);
        if (btn) {
            btn.disabled = true;
            btn.classList.add('opacity-50');
            btn.title = 'Viewer 無權限執行此操作';
        }
    });
}
```

**初始化**:
```javascript
document.addEventListener('DOMContentLoaded', function() {
    initUserStoryMap();
    disableUsmCrudActions();  // 新增
    // ...
});
```

### 3. 保存用戶角色

#### `app/templates/login.html`

登入成功時保存用戶角色到 localStorage:
```javascript
// Save user role to localStorage for permission checks
if (data.user && data.user.role) {
    localStorage.setItem('user_role', data.user.role);
}
```

#### `app/static/js/auth.js`

登出時清除用戶角色:
```javascript
clearToken() {
    // ... existing code ...
    localStorage.removeItem('user_role');  // 新增
    // ... rest of code ...
}
```

## 權限矩陣

| 操作 | Viewer | User | Admin | Super Admin |
|------|--------|------|-------|------------|
| 讀取地圖 | ✓ | ✓ | ✓ | ✓ |
| 建立地圖 | ✗ | ✓ | ✓ | ✓ |
| 更新地圖 | ✗ | ✓ | ✓ | ✓ |
| 刪除地圖 | ✗ | ✓ | ✓ | ✓ |
| 新增節點 | ✗ | ✓ | ✓ | ✓ |
| 計算票證 | ✗ | ✓ | ✓ | ✓ |

## 禁用的 UI 元素（Viewer 用戶）

- 「新增地圖」按鈕
- 「保存地圖」按鈕
- 「計算票證」按鈕
- 「確認新增節點」按鈕
- 節點上的「+子」按鈕
- 節點上的「+同級」按鈕
- 地圖列表中的刪除按鈕

## 實現流程

### 後端流程
1. 使用者發送 CRUD 請求
2. API 檢查用戶角色
3. 如果是 Viewer，立即拒絕 (403)
4. 否則檢查團隊權限
5. 有權限則執行操作，無則拒絕

### 前端流程
1. 使用者登入
2. 後端返回用戶信息，包含角色
3. 前端保存角色到 localStorage
4. 頁面加載時檢查角色
5. 如果是 Viewer，禁用 CRUD 按鈕

## HTTP 響應狀態

### 403 Forbidden - Viewer 無權限
```json
{
    "detail": "Viewer 無權限建立 User Story Map"
}
```

### 403 Forbidden - 無團隊權限
```json
{
    "detail": "無權限在此團隊建立 User Story Map"
}
```

## 測試場景

### Viewer 用戶
1. ✓ 可以查看團隊的 User Story Maps
2. ✗ 無法建立新地圖 (HTTP 403)
3. ✗ 無法更新地圖 (HTTP 403)
4. ✗ 無法刪除地圖 (HTTP 403)
5. ✓ 可以看到所有按鈕，但被禁用
6. ✓ 懸停時顯示「無權限執行此操作」

### User/Admin/Super Admin
1. ✓ 所有 CRUD 操作正常
2. ✓ 按鈕可用且有效

## 變更清單

### 修改的檔案
1. `app/api/user_story_maps.py` - 後端權限檢查
2. `app/static/js/user_story_map.js` - 前端 UI 禁用
3. `app/templates/login.html` - 保存用戶角色
4. `app/static/js/auth.js` - 清除用戶角色

### 新增的檔案
- 無

## 相容性

- ✓ 向下相容：沒有現有角色衝突
- ✓ 無資料庫變更需求
- ✓ 無前端庫升級需求
- ✓ 不影響其他功能

## 部署步驟

1. 部署程式碼變更
2. 重啟應用服務
3. 清除瀏覽器快取（如需要）
4. 測試 Viewer 角色

## 安全考慮

1. ✓ 後端驗證：所有 CRUD 操作都有後端權限檢查
2. ✓ 前端驗證：Viewer UI 按鈕被禁用
3. ✓ 雙重防護：前端+ 後端都有檢查
4. ✓ 不依賴 localStorage：localStorage 只用於 UX，決策權在後端

## 總結

- ✅ Viewer 角色只能讀取
- ✅ CRUD 操作被正確禁用
- ✅ 後端嚴格驗證權限
- ✅ 前端 UI 清晰反映權限
- ✅ 無資料庫變更需求
- ✅ 完全向下相容
