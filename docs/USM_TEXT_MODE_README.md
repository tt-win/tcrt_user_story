# USM 文字編輯模式

## 概述

USM (User Story Map) 文字編輯模式提供一個類似 Mermaid 的簡化語法，讓使用者可以用純文字方式編輯 User Story Map。

## 核心特性

✅ **使用縮排表達父子關係** - 類似 YAML 或 Python 的縮排語法  
✅ **包含資料庫所有必要欄位** - 支援 USM 資料庫的完整欄位  
✅ **支援自訂 node_id (alias)** - 使用 `[@id]` 語法或自動生成  
✅ **易讀易寫** - 適合版本控制和 Code Review  
✅ **雙向轉換** - 可以從文字匯入，也可以匯出為文字  

## 文件結構

```
tcrt_user_story/
├── docs/
│   ├── USM_TEXT_FORMAT_SPEC.md      # 完整規範文件
│   ├── usm_example_from_db.usm      # 基於實際資料的範例
│   └── USM_TEXT_MODE_README.md      # 本文件
├── app/
│   └── services/
│       └── usm_text_parser.py       # Parser 和 Exporter 實作
└── test_usm_parser.py               # 測試檔案
```

## 快速開始

### 基本語法

```usm
# 註解以 # 開頭

[@custom_id] root: 系統名稱
  desc: 系統描述
  
  [@feature_a] feature: 功能A
    team: 開發團隊
    
    [@story_1] story: 使用者故事1
      desc: 故事描述
      jira: PROJ-001, PROJ-002
      as_a: 使用者
      i_want: 能夠登入
      so_that: 可以使用系統
      
    story: 使用者故事2
      # 沒有 [@id] 會自動生成
```

### 節點類型

- `root:` - 根節點 (對應資料庫的 `root`)
- `feature:` - 功能分類 (對應 `feature_category`)
- `story:` - 使用者故事 (對應 `user_story`)

### 支援的欄位

| USM 語法 | 資料庫欄位 | 說明 |
|---------|-----------|------|
| `[@id]` | node_id | 自訂節點 ID |
| `desc:` | description | 描述 |
| `comment:` | comment | 註解 |
| `jira:` | jira_tickets | Jira tickets (逗號分隔) |
| `product:` | product | 產品名稱 |
| `team:` | team | 團隊名稱 |
| `team_tags:` | team_tags | 團隊標籤 (逗號分隔) |
| `related:` | related_ids | 相關節點 (使用 @id) |
| `as_a:` | as_a | BDD: As a |
| `i_want:` | i_want | BDD: I want |
| `so_that:` | so_that | BDD: So that |

### Node ID 規則

1. **自訂 ID**: `[@my_custom_id]` - 使用英數字、底線、連字號
2. **自動生成**: 
   - 根節點: `root_` + 8位隨機16進制 (例: `root_abc12345`)
   - 一般節點: `node_` + 毫秒時間戳 (例: `node_1764745931954`)

### 多行欄位

使用 `|` 表示多行內容：

```usm
story: 複雜功能
  desc: |
    第一行描述
    第二行描述
    第三行描述
  comment: |
    多行註解
```

### 關聯節點

使用 `@id` 語法引用其他節點：

```usm
[@node_a] story: 節點A

[@node_b] story: 節點B
  related: @node_a

[@node_c] story: 節點C
  related: @node_a, @node_b
```

## 使用方式

### Python API

```python
from app.services.usm_text_parser import (
    parse_usm_text, 
    export_to_usm_text,
    convert_usm_nodes_to_db_format
)

# 解析文字
with open('my_map.usm', 'r') as f:
    text = f.read()

nodes = parse_usm_text(text)

# 轉換為資料庫格式
db_nodes = convert_usm_nodes_to_db_format(nodes, map_id=1)

# 匯出為文字
from_db_nodes = [...] # 從資料庫讀取
text = export_to_usm_text(from_db_nodes)

with open('exported.usm', 'w') as f:
    f.write(text)
```

### 錯誤處理

```python
from app.services.usm_text_parser import parse_usm_text, ParseError

try:
    nodes = parse_usm_text(text)
except ParseError as e:
    print(f"解析錯誤在第 {e.line_num} 行: {e.message}")
```

## 測試

執行完整測試套件：

```bash
cd /Users/hideman/code/tcrt_user_story
python test_usm_parser.py
```

測試涵蓋：
- ✅ 基本解析
- ✅ 自動 ID 生成
- ✅ 匯出功能
- ✅ 多行欄位
- ✅ 關聯節點
- ✅ 錯誤處理
- ✅ 往返轉換 (parse → export → parse)

## 實際範例

查看 `docs/usm_example_from_db.usm` 以查看基於實際 ACS 系統資料的完整範例。

## 下一步：整合到系統

### 1. API Endpoints

需要新增以下 API：

```python
# app/api/user_story_maps.py

@router.post("/api/usm/{map_id}/import-text")
async def import_usm_text(
    map_id: int,
    text: str,
    db: AsyncSession = Depends(get_usm_db)
):
    """從 USM 文字匯入節點"""
    try:
        nodes = parse_usm_text(text)
        db_nodes = convert_usm_nodes_to_db_format(nodes, map_id)
        # 儲存到資料庫...
        return {"status": "success", "nodes": len(nodes)}
    except ParseError as e:
        raise HTTPException(
            status_code=400,
            detail=f"解析錯誤在第 {e.line_num} 行: {e.message}"
        )

@router.get("/api/usm/{map_id}/export-text")
async def export_usm_text(
    map_id: int,
    db: AsyncSession = Depends(get_usm_db)
):
    """匯出 USM 為文字格式"""
    # 從資料庫讀取節點...
    text = export_to_usm_text(nodes)
    return {"text": text}
```

### 2. 前端整合

建議使用 Monaco Editor 或 CodeMirror：

```html
<!-- 新增文字編輯器標籤 -->
<div class="tab-pane" id="text-editor">
    <div id="usm-text-editor" style="height: 600px;"></div>
    <button id="importFromText">匯入</button>
    <button id="exportToText">匯出</button>
</div>
```

```javascript
// 初始化編輯器
const editor = monaco.editor.create(
    document.getElementById('usm-text-editor'), 
    {
        value: '# USM Text Format\n',
        language: 'yaml', // 使用 YAML 高亮
        theme: 'vs-dark'
    }
);

// 匯入
document.getElementById('importFromText').addEventListener('click', async () => {
    const text = editor.getValue();
    const response = await fetch(`/api/usm/${mapId}/import-text`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text})
    });
    // 重新載入地圖...
});

// 匯出
document.getElementById('exportToText').addEventListener('click', async () => {
    const response = await fetch(`/api/usm/${mapId}/export-text`);
    const data = await response.json();
    editor.setValue(data.text);
});
```

### 3. 語法高亮

可以定義自訂 Monaco 語法：

```javascript
monaco.languages.register({ id: 'usm' });

monaco.languages.setMonarchTokensProvider('usm', {
    tokenizer: {
        root: [
            [/#.*$/, 'comment'],
            [/\[@\w+\]/, 'keyword'],
            [/\b(root|feature|story):\s/, 'type'],
            [/\b(desc|jira|team|related|as_a|i_want|so_that):\s/, 'attribute'],
        ]
    }
});
```

### 4. 版本控制整合

將 USM 文字檔加入 Git：

```bash
# 匯出當前地圖
curl http://localhost:8000/api/usm/1/export-text > maps/acs_system.usm

# 提交到版本控制
git add maps/acs_system.usm
git commit -m "Update ACS user story map"

# Code Review
git diff maps/acs_system.usm
```

## 優點

1. **易於版本控制** - 純文字格式，Git diff 清晰可讀
2. **批次編輯** - 可用文字編輯器快速修改多個節點
3. **可程式化** - 支援腳本生成和轉換
4. **易於分享** - 文字檔可輕鬆分享和協作
5. **備份簡單** - 純文字備份和恢復都很簡單

## 限制

1. **位置資訊** - 不保留精確的 X/Y 座標（需自動佈局）
2. **視覺化** - 無法呈現複雜的視覺佈局
3. **學習曲線** - 需要學習語法（但很簡單）

## 貢獻

歡迎提交 Issue 和 Pull Request！

## 授權

與主專案相同授權
