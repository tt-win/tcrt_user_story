# Lark 測試案例表格結構分析

## 表格資訊
- **Wiki Token**: Q4XxwaS2Cif80DkAku9lMKuAgof
- **Table ID**: tbl4SVQt73VfL690
- **表格名稱**: CRD Test Case Repo
- **總欄位數**: 14

## 欄位結構詳細分析

### 1. 核心測試案例欄位

#### Test Case Number (fldBlyJ7dK)
- **類型**: 1 (文字)
- **用途**: 測試案例編號
- **範例**: "TCG-93178.010.010", "TCG-93178.010.020", "TCG-93178.020.010"
- **格式**: TCG-{票號}.{主編號}.{子編號}

#### Title (fldSA7tdAU)
- **類型**: 1 (文字)
- **用途**: 測試案例標題
- **範例**: 
  - "Associated User - Completely new user with no related information"
  - "Associated User - Completely new user with username relation"
  - "Associated User - Relation score - Same Login IP"

#### Priority (fldziAv0Ks)
- **類型**: 3 (單選)
- **用途**: 優先級設定
- **選項**:
  - High (色彩: 22, ID: opthRO1snK)
  - Medium (色彩: 24, ID: optLSPV8YQ)
  - Low (色彩: 26, ID: optFhhVq5Q)

#### Precondition (fld9Avx1q1)
- **類型**: 1 (文字)
- **用途**: 前置條件描述
- **特點**: 支援多行文字，包含詳細的設定步驟
- **範例**: "ID generator\n\n----------\n\nCreate a new username with ID generator..."

#### Steps (fldzn61QAd)
- **類型**: 1 (文字)
- **用途**: 測試步驟
- **特點**: 支援多行文字，包含編號的步驟列表
- **範例**: "1. Login to TAC with valid account\n2. Navigate to Player Management..."

#### Expected Result (fldp1YE4fD)
- **類型**: 1 (文字)
- **用途**: 預期結果描述
- **特點**: 支援多行文字，包含編號的預期結果列表
- **範例**: "1. No users should be found\n2. No data icon should be displayed..."

#### Attachment (fldt9XFcbN)
- **類型**: 17 (附件)
- **用途**: 測試案例相關附件
- **特點**: 支援多個檔案上傳

#### Assignee (fldurl1SP2)
- **類型**: 11 (人員)
- **用途**: 測試案例指派人員
- **屬性**: 單選模式 (multiple: false)

#### Test Result (fld8UsatcN)
- **類型**: 3 (單選)
- **用途**: 測試執行結果
- **選項**:
  - Passed (色彩: 26, ID: optHPgjdvZ)
  - Failed (色彩: 33, ID: optMvzs2wB)
  - Retest (色彩: 24, ID: optxOTZflE)
  - Not Available (色彩: 54, ID: opt44oQRhC)

### 2. 關聯欄位

#### User Story Map (fldZxlTPYC)
- **類型**: 21 (關聯記錄)
- **關聯表格**: CRD User Story Map (tbl2Yy9f8MTOtQPP)
- **反向欄位**: CRD Test Case Repo (fldYvPGWF0)
- **屬性**: 多選 (multiple: true)

#### TCG (fldYxbn4vE)
- **類型**: 21 (關聯記錄)
- **關聯表格**: TCG Tickets (tblcK6eF3yQCuwwl)
- **反向欄位**: CRD Test Case Repo (fldgTdil9w)
- **屬性**: 多選 (multiple: true)

#### 父記錄 (fld2u5Ifp0)
- **類型**: 18 (關聯記錄)
- **關聯表格**: CRD Test Case Repo (tbl4SVQt73VfL690) - 自關聯
- **屬性**: 單選 (multiple: false)

#### CRD User Story Map 副本-CRD Test Case Repo (fldKERmvpD)
- **類型**: 21 (關聯記錄)
- **關聯表格**: testing (tblovGcG5mC9sHRP)
- **反向欄位**: CRD Test Case Repo (fldYvPGWF0)
- **屬性**: 多選 (multiple: true)

#### testing 副本 (fldEHPgR7a)
- **類型**: 21 (關聯記錄)
- **關聯表格**: Sample United User Story Map (tblCSb0cGzQrDEd1)
- **反向欄位**: CRD Test Case Repo (fldYvPGWF0)
- **屬性**: 多選 (multiple: true)

## Lark 欄位類型對應

| Lark 類型 | 類型名稱 | 對應 Python 類型 | 備註 |
|-----------|----------|-------------------|------|
| 1 | Text | str | 文字欄位 |
| 3 | SingleSelect | str (Enum) | 單選，有預定義選項 |
| 11 | User | str | 人員欄位 |
| 17 | Attachment | List[Dict] | 附件列表 |
| 18 | Lookup | Dict | 查找欄位 |
| 21 | Link | List[Dict] | 關聯記錄 |

## 關聯記錄資料結構

關聯記錄欄位返回的資料結構：
```json
[
  {
    "record_ids": ["recuSBJAfVaZ5F"],
    "table_id": "tblovGcG5mC9sHRP",
    "text": "Story-CRM-00004",
    "text_arr": ["Story-CRM-00004"],
    "type": "text"
  }
]
```

## 範例記錄資料

```json
{
  "Test Case Number": "TCG-93178.010.010",
  "Title": "Associated User - Completely new user with no related information",
  "Priority": "Medium",
  "Precondition": "ID generator\n\n----------\n\nCreate a new username...",
  "Steps": "1. Login to TAC with valid account\n2. Navigate to Player Management...",
  "Expected Result": "1. No users should be found\n2. No data icon should be displayed...",
  "TCG": [{"record_ids": ["recuRbIdgfdKe1"], "table_id": "tblcK6eF3yQCuwwl", "text": "TCG-93178"}],
  "User Story Map": [{"record_ids": ["recuRjrxCW74FL"], "table_id": "tbl2Yy9f8MTOtQPP", "text": "Story-CRM-00030"}]
}
```

## 實作建議

### TestCase 模型核心欄位：
- `test_case_number`: str - 測試案例編號
- `title`: str - 標題
- `priority`: TestCasePriority (Enum) - 優先級
- `precondition`: Optional[str] - 前置條件
- `steps`: Optional[str] - 測試步驟
- `expected_result`: Optional[str] - 預期結果
- `attachments`: List[Attachment] - 附件列表
- `assignee`: Optional[str] - 指派人員
- `test_result`: Optional[TestResult] (Enum) - 測試結果

### 關聯欄位：
- `user_story_map_links`: List[LarkRecord] - User Story Map 關聯
- `tcg_links`: List[LarkRecord] - TCG 票據關聯
- `parent_record`: Optional[LarkRecord] - 父記錄關聯

### Lark 同步欄位：
- `lark_record_id`: Optional[str] - Lark 記錄 ID
- `lark_field_mapping`: Dict[str, str] - 欄位 ID 映射