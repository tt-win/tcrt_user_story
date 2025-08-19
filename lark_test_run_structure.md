# Lark 測試執行表格結構分析

## 表格資訊
- **Wiki Token**: Q4XxwaS2Cif80DkAku9lMKuAgof
- **Table ID**: tbltzUlFtQPNX7t2
- **表格名稱**: Test Run Repository
- **總欄位數**: 10

## 欄位結構詳細分析

### 1. 基本資訊欄位

#### Ticket Number (fldG7lds0R)
- **類型**: 1 (文字)
- **用途**: 測試票據編號
- **範例**: "TCG-100572.010.010", "TCG-100572.010.020", "TCG-100572.010.030"
- **格式**: TCG-{票號}.{主編號}.{子編號}

#### Title (fldl7xA6BW)
- **類型**: 1 (文字)
- **用途**: 測試執行標題
- **範例**: 
  - "查看關聯信息 - 彈框顯示"
  - "查看關聯信息 - 顯示類別和總分"
  - "查看關聯信息 - 顯示分頁功能"

### 2. 測試內容欄位

#### Precondition (fldqVC6iKg)
- **類型**: 1 (文字)
- **用途**: 前置條件
- **範例**: "完成 TCG-100558.010.010 關聯玩家 - 關聯度篩選 - 全部"

#### Steps (fldEgV3mrB)
- **類型**: 1 (文字)
- **用途**: 測試步驟
- **範例**: 
  - "1. 點擊關聯度分數"
  - "1. 展開彈框內各項目\n2. 觀察分數加總以及項目列表"

#### Expected Result (fldWYEr3X2)
- **類型**: 1 (文字)
- **用途**: 預期結果
- **範例**: 
  - "1. 關聯信息彈框應顯示\n2. 關聯信息彈框中分類的數量應與關聯項目欄位數量相同"

### 3. 執行相關欄位

#### Priority (flddNiFNYU)
- **類型**: 3 (單選)
- **用途**: 優先級設定
- **選項**:
  - High (色彩: 22, ID: opthRO1snK)
  - Medium (色彩: 24, ID: optLSPV8YQ)
  - Low (色彩: 26, ID: optFhhVq5Q)

#### Assignee (fldPRa8AhT)
- **類型**: 11 (人員)
- **用途**: 指派執行人員
- **屬性**: 單選模式 (multiple: false)
- **資料結構**:
```json
[{
  "email": "jacky.h@st-win.com.tw",
  "en_name": "Jacky Hsueh", 
  "id": "ou_941beef388982f1f4a1a6ef9c568f21b",
  "name": "Jacky Hsueh"
}]
```

#### Test Result (flduqdwvE9)
- **類型**: 3 (單選)
- **用途**: 測試執行結果
- **選項**:
  - Passed (色彩: 26, ID: optHPgjdvZ)
  - Failed (色彩: 33, ID: optMvzs2wB)
  - Retest (色彩: 24, ID: optxOTZflE)
  - Not Available (色彩: 54, ID: opt44oQRhC)

### 4. 附件欄位

#### Attachment (fldJTGujlh)
- **類型**: 17 (附件)
- **用途**: 測試相關附件
- **特點**: 支援多個檔案上傳

#### Execution Result (flds1Dn2Mn)
- **類型**: 17 (附件)
- **用途**: 執行結果附件（截圖、報告等）
- **資料結構**:
```json
[{
  "file_token": "NjGkb2iGvonNi3x5cURlPjv2gic",
  "name": "截圖 2025-08-06 下午5.12.23.png",
  "size": 139246,
  "tmp_url": "https://open.larksuite.com/open-apis/drive/v1/medias/batch_get_tmp_download_url?file_tokens=NjGkb2iGvonNi3x5cURlPjv2gic",
  "type": "image/png",
  "url": "https://open.larksuite.com/open-apis/drive/v1/medias/NjGkb2iGvonNi3x5cURlPjv2gic/download"
}]
```

## Test Run 與 Test Case 的差異

### 相同欄位:
- Title (標題)
- Priority (優先級) 
- Precondition (前置條件)
- Steps (測試步驟)
- Expected Result (預期結果)
- Assignee (指派人員)
- Attachment (附件)
- Test Result (測試結果)

### Test Run 特有欄位:
- **Ticket Number** (取代 Test Case Number) - 可能是執行時的票據編號
- **Execution Result** - 專門存放執行結果附件（截圖等）

### Test Case 特有欄位:
- 多個關聯欄位 (User Story Map, TCG, 父記錄等)
- 更複雜的關聯結構

## 實作建議

### TestRun 模型核心欄位：
- `ticket_number`: str - 測試票據編號
- `title`: str - 標題
- `priority`: TestCasePriority (Enum) - 優先級（與TestCase共用）
- `precondition`: Optional[str] - 前置條件
- `steps`: Optional[str] - 測試步驟
- `expected_result`: Optional[str] - 預期結果
- `assignee`: Optional[LarkUser] - 指派人員
- `test_result`: Optional[TestResult] (Enum) - 測試結果
- `attachments`: List[LarkAttachment] - 一般附件
- `execution_results`: List[LarkAttachment] - 執行結果附件

### LarkUser 結構：
```python
class LarkUser(BaseModel):
    id: str
    name: str
    en_name: str
    email: str
```

### LarkAttachment 結構：
```python
class LarkAttachment(BaseModel):
    file_token: str
    name: str
    size: int
    type: str
    url: str
    tmp_url: Optional[str] = None
```

## 關係設計建議

TestRun 可能需要關聯到 TestCase，建議增加：
- `related_test_cases`: List[str] - 關聯的測試案例編號
- `test_case_links`: Optional[List[LarkRecord]] - 如果有直接關聯欄位