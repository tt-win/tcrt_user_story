# USM 文字編輯格式規範

## 設計目標

提供一個類似 Mermaid 但更簡化的語法，讓使用者可以用純文字方式編輯 User Story Map，支援：

1. 使用縮排表達節點的父子關係
2. 包含資料庫所有必要欄位
3. 支援自訂 node_id（alias），也可自動生成
4. 易讀易寫，適合版本控制

## 語法規範

### 基本結構

```
[@node_id] 節點類型: 標題
  屬性1: 值
  屬性2: 值
  
  [@child_id] 子節點類型: 子標題
    子節點屬性: 值
```

### 節點類型

- `root:` - 根節點
- `feature:` - 功能分類節點 (feature_category)
- `story:` - 使用者故事節點 (user_story)

### 必要欄位

每個節點至少需要：
- **節點類型和標題**（第一行）
- 其他欄位可選

### 可選欄位

- `desc:` - 描述 (description)
- `comment:` - 註解
- `jira:` - Jira tickets（逗號分隔）
- `product:` - 產品名稱
- `team:` - 團隊名稱
- `team_tags:` - 團隊標籤（逗號分隔）
- `related:` - 相關節點（逗號分隔的 node_id）
- `as_a:` - BDD: As a（角色）
- `i_want:` - BDD: I want（需求）
- `so_that:` - BDD: So that（目的）

### Node ID 規則

1. **自訂 ID**：使用 `[@custom_id]` 前綴
   - 可使用英數字、底線、連字號
   - 例如：`[@accounts]`, `[@get_balance]`

2. **自動生成**：不寫 `[@...]` 則自動生成
   - 根節點：`root_` + 8位隨機16進制
   - 一般節點：`node_` + 當前時間戳

3. **引用其他節點**：在 `related:` 欄位中使用 node_id

## 範例

### 範例 1：完整的 ACS 系統範例

```usm
[@acs_root] root: ACS
  desc: Account System 帳戶系統
  
  [@accounts] story: accounts
    jira: TCG-123456
    
  [@get_balance] story: 获取玩家的总余额（根据customerId）
    desc: GET /accounts/customer/{customerId}/balance
    jira: TCG-122992
    as_a: 上层模块
    i_want: 获取玩家的账户列表 (根据customerId）
    
  [@get_accounts_by_customer] story: 获取玩家的账户列表 (根据customerId）
    desc: GET /accounts/customer/{customerId}
    jira: TCG-122994
    as_a: 上层模块
    i_want: 获取玩家的账户列表 (根据accountId列表）
    
  [@get_accounts_by_ids] story: 获取玩家的账户列表 (根据accountId列表）
    desc: GET /accounts
    jira: TCG-122995
    as_a: 上层模块
    i_want: 获取特定账户信息 (根据accountId）
    
  [@user_management] feature: 用戶管理
    desc: 用戶相關功能
    team: Backend Team
    
    [@create_user] story: 新增用戶
      desc: POST /users
      jira: TCG-100001, TCG-100002
      as_a: 系統管理員
      i_want: 能夠新增新用戶
      so_that: 可以擴展系統使用者
      related: @get_balance
      
    [@update_user] story: 更新用戶資料
      desc: PUT /users/{userId}
      jira: TCG-100003
      as_a: 系統管理員
      i_want: 能夠更新用戶資料
      
    [@delete_user] story: 刪除用戶
      desc: DELETE /users/{userId}
      jira: TCG-100004
      as_a: 系統管理員
      i_want: 能夠刪除用戶
      comment: 需要考慮軟刪除機制
```

### 範例 2：簡化版（使用自動生成 ID）

```usm
root: 電商平台

  feature: 商品管理
    
    story: 新增商品
      desc: POST /products
      jira: SHOP-001
      as_a: 商家
      i_want: 能夠新增新商品
      so_that: 可以販售商品
      
    story: 編輯商品
      desc: PUT /products/{id}
      jira: SHOP-002
      as_a: 商家
      i_want: 能夠編輯商品資訊
      
  feature: 訂單管理
    
    story: 建立訂單
      desc: POST /orders
      jira: SHOP-010
      as_a: 買家
      i_want: 能夠建立訂單
      so_that: 可以購買商品
      
    story: 查詢訂單
      desc: GET /orders/{id}
      jira: SHOP-011
```

### 範例 3：混合使用自訂和自動 ID

```usm
[@payment_system] root: 支付系統

  [@alipay] feature: 支付寶整合
    team: Payment Team
    
    story: 支付寶支付
      desc: 整合支付寶 API
      jira: PAY-001
      related: @payment_system
      
  feature: 信用卡支付
    
    [@credit_card_pay] story: 信用卡支付處理
      jira: PAY-010
      related: @alipay
```

## 註解

使用 `#` 開頭的行為註解，會被解析器忽略：

```usm
# 這是註解
root: 系統名稱
  # 這也是註解
  story: 功能說明
```

## 空行

空行會被忽略，可用於增加可讀性：

```usm
root: 系統

  feature: 功能A
    story: 故事1
    
    story: 故事2

  feature: 功能B
    story: 故事3
```

## 縮排規則

- 使用 2 或 4 個空格縮排（統一使用，不可混用）
- Tab 會被轉換為 4 個空格
- 子節點必須比父節點多一層縮排
- 同層節點使用相同縮排

## 多行值

某些欄位（如 desc, comment）支援多行，使用 `|` 表示：

```usm
story: 複雜功能
  desc: |
    這是第一行描述
    這是第二行描述
    這是第三行描述
  comment: |
    註解也可以多行
    方便撰寫詳細說明
```

## 資料庫欄位映射

| USM 格式 | 資料庫欄位 | 說明 |
|---------|-----------|------|
| `[@id]` | node_id | 節點 ID |
| `root:/feature:/story:` | node_type | 節點類型 |
| 標題（冒號後） | title | 節點標題 |
| `desc:` | description | 描述 |
| `comment:` | comment | 註解 |
| `jira:` | jira_tickets | Jira tickets (JSON array) |
| `product:` | product | 產品 |
| `team:` | team | 團隊 |
| `team_tags:` | team_tags | 團隊標籤 (JSON array) |
| `related:` | related_ids | 相關節點 (JSON array) |
| `as_a:` | as_a | BDD: As a |
| `i_want:` | i_want | BDD: I want |
| `so_that:` | so_that | BDD: So that |
| （自動計算） | parent_id | 父節點 ID |
| （自動計算） | children_ids | 子節點 IDs (JSON array) |
| （自動計算） | level | 層級（0 開始） |
| （UI 編輯） | position_x | X 座標（自動佈局後設定） |
| （UI 編輯） | position_y | Y 座標（自動佈局後設定） |
| （自動） | aggregated_tickets | 聚合的 tickets (JSON array) |

## 解析流程

1. **詞法分析**：逐行讀取，識別縮排層級、節點類型、屬性
2. **語法分析**：建立樹狀結構，確定父子關係
3. **ID 處理**：
   - 解析自訂 ID
   - 為無 ID 節點生成 ID
   - 驗證 ID 唯一性
4. **關聯解析**：解析 `related:` 欄位中的節點引用
5. **資料轉換**：轉換為資料庫格式
6. **驗證**：檢查必要欄位、資料型別

## 匯出流程

1. 從資料庫讀取節點
2. 根據 parent_id 和 level 重建樹狀結構
3. 按層級和位置排序節點
4. 轉換為 USM 文字格式
5. 輸出帶縮排的文字

## 錯誤處理

常見錯誤：
- 縮排不一致
- 重複的 node_id
- 引用不存在的 node_id
- 節點類型錯誤
- user_story 節點不可有子節點

## 實作建議

### Parser 實作（Python）

```python
class USMParser:
    def parse(self, text: str) -> UserStoryMap:
        """解析 USM 文字格式"""
        lines = self._preprocess(text)
        nodes = self._parse_nodes(lines)
        self._validate(nodes)
        self._resolve_relations(nodes)
        return self._build_map(nodes)
    
    def _preprocess(self, text: str) -> List[Line]:
        """預處理：處理註解、空行、縮排"""
        pass
    
    def _parse_nodes(self, lines: List[Line]) -> List[Node]:
        """解析節點"""
        pass
    
    def _validate(self, nodes: List[Node]):
        """驗證節點"""
        pass
    
    def _resolve_relations(self, nodes: List[Node]):
        """解析關聯"""
        pass

class USMExporter:
    def export(self, map: UserStoryMap) -> str:
        """匯出為 USM 文字格式"""
        pass
```

### 整合到現有系統

1. 新增 API endpoint：
   - `POST /api/usm/import` - 匯入 USM 文字
   - `GET /api/usm/export/{map_id}` - 匯出為 USM 文字

2. 前端整合：
   - 新增文字編輯器（Monaco Editor 或 CodeMirror）
   - 支援語法高亮
   - 即時驗證和錯誤提示
   - 雙向同步（文字 ↔ 視覺化）

3. 版本控制：
   - 可以將 USM 文字檔存入 Git
   - 便於 Code Review
   - 追蹤變更歷史

## 未來擴展

- 支援匯入/匯出其他格式（YAML, JSON）
- 語法自動補全
- 智慧縮排
- 批次操作命令
- 範本系統
