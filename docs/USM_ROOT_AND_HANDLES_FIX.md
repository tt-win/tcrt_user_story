# User Story Map 連接點與根節點修復

## 修復的問題

### 1. ✅ 根節點仍可新增同級節點
**問題**: 原本只檢查 `parentId`，但根節點的 `parentId` 可能是 `null`，檢查不夠嚴謹。

**修改前**:
```javascript
if (!siblingNode.data.parentId) {
    alert('根節點不能新增同級節點');
    return;
}
```

**修改後**:
```javascript
// Root node cannot have siblings - check by level and parentId
if (siblingNode.data.level === 0 || !siblingNode.data.parentId) {
    alert('根節點不能新增同級節點');
    return;
}
```

**改進**:
- 同時檢查 `level === 0` 和 `parentId`
- 雙重保險，確保根節點（level 0）無法新增同級節點

---

### 2. ✅ 子節點連線預設連接點
**問題**: 新增子節點時，連線沒有指定連接點，由系統隨機選擇。

**需求**: 
- 父節點：從右側連接點出發
- 子節點：連到左側連接點

**修改前**:
```javascript
setEdges((eds) => eds.concat({
    id: `edge_${Date.now()}`,
    source: nodeData.parentId,
    target: newNode.id,
    type: 'smoothstep',
    markerEnd: {
        type: MarkerType.ArrowClosed,
    },
}));
```

**修改後**:
```javascript
setEdges((eds) => eds.concat({
    id: `edge_${Date.now()}`,
    source: nodeData.parentId,
    sourceHandle: 'right',  // 從父節點右側
    target: newNode.id,
    targetHandle: 'left',   // 到子節點左側
    type: 'smoothstep',
    markerEnd: {
        type: MarkerType.ArrowClosed,
    },
}));
```

**效果**:
- 父子關係連線一致性：永遠從右到左
- 符合由左到右的樹狀結構
- 視覺上更清晰

---

## 視覺效果

### 連線方向

```
修改前（隨機）:
    Root
    ↓ ← 可能從下方
    Child

修改後（固定）:
    Root  →  Child
    (右)     (左)
```

### 樹狀結構

```
          Root
         (100,100)
             │
        (right)
             │
             ↓
         ┌───(left)
         │
    Feature A
    (400,100)
         │
    (right)
         │
         ↓
     ┌───(left)
     │
  Story A1
  (700,100)
```

---

## 根節點檢查邏輯

### 判斷根節點的條件

**主要條件**:
- `level === 0`

**次要條件**:
- `parentId === null` 或 `parentId === undefined`

**邏輯**:
```javascript
if (level === 0 || !parentId) {
    // 這是根節點
}
```

使用 OR (||) 而非 AND (&&) 是為了涵蓋所有情況：
- 正常根節點：level=0, parentId=null
- 舊資料：level=0, parentId 可能未設定
- 異常狀態：level > 0 但 parentId=null（也視為根層級）

---

## 連接點 ID

React Flow 連接點的 ID 對應：

| Handle ID | 位置 | 用途 |
|-----------|------|------|
| `top` | 上方 | 接收從上方來的連線 |
| `bottom` | 下方 | 發出往下的連線 |
| `left` | 左側 | **接收父節點連線** ⭐ |
| `right` | 右側 | **發出到子節點連線** ⭐ |

---

## 測試案例

### 測試 1: 根節點限制
```
步驟:
1. 選擇 Root 節點（level=0）
2. 點擊「同級」按鈕

預期:
✓ 顯示「根節點不能新增同級節點」
✓ 不開啟新增對話框
```

### 測試 2: 非根節點可新增同級
```
步驟:
1. 選擇 Feature 節點（level=1, parentId=root_xxx）
2. 點擊「同級」按鈕

預期:
✓ 開啟新增對話框
✓ 可以新增同級節點
```

### 測試 3: 連接點方向
```
步驟:
1. 從 Root 新增子節點 Feature
2. 檢查連線方向

預期:
✓ 連線從 Root 右側出發
✓ 連線到 Feature 左側
✓ 箭頭指向 Feature
```

### 測試 4: 多層級連接
```
步驟:
1. Root → Feature → Story 三層結構
2. 檢查所有連線

預期:
✓ 所有連線都是 (右→左) 方向
✓ 符合樹狀結構
```

---

## 修改檔案

- `app/static/js/user_story_map.js`
  - `addSiblingNode()` - 增強根節點檢查
  - `addNode()` - 指定連接點

---

## 程式碼對比

### addSiblingNode 函數

```diff
const addSiblingNode = useCallback((siblingId) => {
    const siblingNode = nodes.find(n => n.id === siblingId);
    if (!siblingNode) return;
    
-   // Root node cannot have siblings
-   if (!siblingNode.data.parentId) {
+   // Root node cannot have siblings - check by level and parentId
+   if (siblingNode.data.level === 0 || !siblingNode.data.parentId) {
        alert('根節點不能新增同級節點');
        return;
    }
    
    const modal = new bootstrap.Modal(document.getElementById('addNodeModal'));
    modal.show();
    
    window._tempParentId = siblingNode.data.parentId;
    window._tempParentLevel = (siblingNode.data.level || 1) - 1;
}, [nodes]);
```

### 連線建立

```diff
if (nodeData.parentId) {
    setEdges((eds) => eds.concat({
        id: `edge_${Date.now()}`,
        source: nodeData.parentId,
+       sourceHandle: 'right',  // 從父節點右側
        target: newNode.id,
+       targetHandle: 'left',   // 到子節點左側
        type: 'smoothstep',
        markerEnd: {
            type: MarkerType.ArrowClosed,
        },
    }));
}
```

---

## 總結

✅ **修復完成**
- 根節點檢查更嚴謹（level + parentId 雙重檢查）
- 連線固定從右到左（符合樹狀結構）
- 視覺一致性提升

✅ **測試通過**
- 根節點無法新增同級節點
- 非根節點可正常新增同級節點
- 所有父子連線方向一致

✅ **可以使用**
- 無需重新初始化資料庫
- 重啟服務即可生效
