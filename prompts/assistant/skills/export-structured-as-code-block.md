---
id: export-structured-as-code-block
name: 把 list / 設定檔 / 任何結構化文字輸出成可一鍵拷貝的程式碼區塊
description: 當使用者要把查詢結果、任意清單、設定檔片段、JSON / YAML / TOML / ENV / Shell / Python / SQL / HTML / XML / diff / log 等結構化純文字匯出、整理、轉成、輸出、或要可一鍵拷貝時，輸出 fenced 程式碼區塊，前端會自動加上一鍵複製按鈕。
triggers:
  # CSV / TSV
  - csv
  - CSV
  - 匯出 csv
  - 轉 csv
  - 整理成 csv
  - 變成 csv
  - 輸出 csv
  - export csv
  - 給我 csv
  - csv 格式
  - tsv
  # JSON / YAML / TOML / INI / ENV
  - 匯出 json
  - 輸出 json
  - 給我 json
  - json 格式
  - 輸出 yaml
  - 給我 yaml
  - 輸出 toml
  - 給我 toml
  - 輸出 ini
  - 給我 .env
  - 給我 env
  - 設定檔
  - 組態檔
  - 設定檔格式
  - 配置文件
  - config 檔
  - 給我設定
  # Code / script
  - 給我 code
  - 給我 程式碼
  - 給我 程式
  - 給我 腳本
  - 給我 shell
  - 給我 bash
  - 給我 python
  - 給我 sql
  - 給我 curl
  - shell script
  - 輸出程式碼
  - 範例程式
  - sample code
  - 給我範例
  - 一鍵複製
  - 可拷貝
  - 方便拷貝
---

# 把結構化文字輸出成可一鍵拷貝的程式碼區塊

當使用者要把任何**結構化純文字**（清單、設定檔、程式碼片段、查詢結果）以可一鍵拷貝
的形式輸出時，本 skill 規範輸出的格式與互動期望。

支援的常見格式（不限於此清單，只要意義上是「結構化純文字」皆適用）：
- **資料**：CSV、TSV、JSON、JSON Lines (`.jsonl`)、XML
- **設定 / 組態**：YAML、TOML、INI、`.env`、nginx config、crontab
- **程式 / 腳本**：Python、JavaScript / TypeScript、Shell (bash / zsh / sh)、
  SQL、HTML / Jinja、CSS、GraphQL
- **其他**：diff、patch、log、Markdown frontmatter、純固定欄位對齊

---

## 輸出格式（強制）

1. **使用 fenced code block** 並以正確的**語言標籤**標明格式：
   - CSV → ` ```csv `、JSON → ` ```json `、YAML → ` ```yaml `、Python → ` ```python `、
     Shell → ` ```bash `、SQL → ` ```sql `、HTML → ` ```html `、diff → ` ```diff `
   - **語言標籤必須正確**，前端 markdown 渲染器（marked.js）會把它變成
     `<pre><code class="language-csv">` 等，前端 CSS 與一鍵複製按鈕依賴此 class。
   - 若無適合標籤（例如自由格式的純文字對齊），用 ` ```text `。

2. **第一行若是表頭/標頭/註解，留在 code block 內**。不要在 code block 內加
   `# 說明`、`// comment` 之外的解說文字；解說放在 code block **外面**，
   用一般 markdown 段落。

3. **結尾可選加簡短說明**（行數、欄位清單、版本、來源），但**不要寫在 code block 裡**。
   例：先輸出 fenced block，再用一行 `共 3 筆，欄位：test_case_number / title / priority。`

4. **不要把 markdown 表格**（`| col1 | col2 |`）**當作 CSV/JSON 輸出**。
   使用者要求 CSV / JSON / YAML / 程式碼時必須是 fenced block。

---

## 各格式跳脫規則（嚴格遵守，否則對應工具會解析失敗）

### CSV / TSV
- 含 `,`（或 tab 在 TSV）、雙引號 `"`、換行（`\n` 或 `\r\n`）、CR（`\r`）的欄位，
  **必須**用雙引號包起來。
- 內部 `"` 寫成兩個 `""`，**不要**用反斜線跳脫。
- 沒特殊字元的欄位可省略雙引號，但用雙引號包起來也合法。
- 數字、enum（`High` / `Medium` / `Low`）不必 quote。
- 空值留空（`a,,c`），不要寫 `null` 或 `N/A`，除非使用者明確要求。
- 編碼 UTF-8，**不加 BOM**，除非使用者要求「給 Excel 用」可加 `\ufeff`。
- 第一行是欄位 header（用業務欄位名，不要用 row id / 內部欄位名）。

### JSON
- 物件用雙引號 key；陣列、字串、數字、布林、null 標準 JSON。
- 縮排 2 或 4 空白都行，但**整份回覆保持一致**。
- 不要加 `// 註解`（JSON 規範不支援）；解說放 code block 外。
- 時間用 ISO 8601（`2026-07-24T15:30:00+08:00`）；金額用字串或整數（避免浮點誤差）。

### YAML
- 用 2 空白縮排，**不要用 tab**。
- 字串若含特殊字元（`:`、`#`、`-` 開頭、數字開頭、true/false/null 等）需用
  單引號 `'` 或雙引號 `"` 包起來；單引號內 `'` 寫成 `''`。
- 多行字串用 `|`（保留換行）或 `>`（摺疊換行）。
- 不要在字串未 quote 處混用 true / false / null / yes / no（會被當布林）。

### TOML
- 區段用 `[section]`、陣列用 `[[items]]`、時間用 ISO 8601。
- 字串三引號 `"""` 支援多行。

### .env / INI
- `.env` 一行一對 `KEY=VALUE`；含空格的值用單/雙引號包起來；`#` 開頭是註解。
- INI 區段用 `[section]`，key = value；不要混 tab 與空白。

### Shell
- 開頭加 `#!/usr/bin/env bash`（或對應 shell）與 `set -euo pipefail` 作為安全預設。
- 變數建議大寫、雙引號包起來（`"$VAR"`）避免 word splitting。
- 不要用 `sudo` / `rm -rf /` 之類的危險指令；若需要，**先在 code block 外**提示使用者確認。

### Python / JavaScript
- 不要引入未在 history 裡見過的第三方套件；若需外部依賴，先在 code block 外說明安裝指令。
- 處理檔案 / 網路 / 系統狀態的操作要附錯誤處理（try/except、`.catch()`）。
- 不要寫 `eval` / `exec`（除非使用者明確要求並已說明風險）。

### SQL
- 關鍵字大寫（`SELECT`、`FROM`、`WHERE`），表/欄位名依原 schema 大小寫。
- 參數化查詢（`%s`、`?`）寫死值要明確標示，**不要把敏感資料硬編進 WHERE**。
- 加註解標明預期影響（`-- 影響：3 筆`）。

### HTML / Jinja
- 屬性值雙引號；表單欄位需有 name / id。
- 避免 inline style 與 inline script（XSS 風險）。
- Jinja 變數用 `{{ var }}`、控制用 `{% if %}`，不要混用其他模板語法。

### diff / patch
- 統一 ` ```diff `；`+` / `-` / ` `（空白）前綴；檔案 header 用 `--- a/path` 與 `+++ b/path`。
- 不要輸出多於 50 個 hunk（太大請改用 `.patch` 附件）。

### log
- 語言標籤用 ` ```log ` 或 ` ```text `。**不要把 log 偽裝成 CSV**。

---

## 禁止事項

- 不要在 code block 內加額外解說行、`#` / `//` 開頭的註解（**僅限** 該語言原生支援的
  註解語法，例如 Python `#`、SQL `--`、Shell `#`）。
- 不要省略欄位值（不要寫 `...` 或 `etc.`），每個項目必須填完所有選定欄位。
- 不要把 markdown 表格（`| col1 | col2 |`）當 CSV / JSON 輸出。
- 不要在 code block 內塞 markdown 連結 `[text](url)`；連結是聊天視覺元素，
  不是結構化欄位值。
- 不要在 CSV / JSON / YAML 內裸放純數字 row id（test case id、set id 等）當作欄位
  名稱或 key；用業務識別字（`test_case_number`、`set_name` 等）。

---

## 大資料量處理

- 若清單 > 50 列，**先提醒**使用者：「資料量較大，內嵌在對話中可能造成後續回合
  token 負擔。建議改用頁面上的『匯出』按鈕（如 [Test Run] 頁面、Test Case 搜尋頁等）。」
  並詢問是否仍要內嵌。
- 真的內嵌時，**全部列都要輸出**（不要截斷、不要寫 `...`），但每列精簡。
- 極大資料（> 500 列）：直接建議匯出檔案，不要硬塞對話。

---

## 多檔 / 多格式輸出

對話只能回文字，若使用者要「CSV 一份 + JSON schema 一份」這類多檔輸出：

- 第一個 fenced block 放第一份，結尾說「接下來是 JSON schema 部分」。
- 另起一個 fenced block 放第二份。
- 不要硬塞進同一個 code block。

---

## 與 deep link 規則的互動

- CSV / JSON / YAML 等結構化檔是給人匯出到 Excel / Sheets / 編輯器用的純文字，
  **不要在欄位值內塞 markdown 連結** `[text](url)`。
- 若使用者額外要求「CSV 裡要能跳轉」，可加一欄 `url`，值是 `_deep_links` 的純 URL。

---

# 範例

## 範例 1：CSV（test case list）

使用者：「把剛剛那 3 筆 case 整理成 csv」

```
已整理成 CSV，可直接一鍵拷貝：

\`\`\`csv
test_case_number,title,priority
TCG-114460.030.060,登入流程驗證,High
TCG-114460.030.070,登入失敗處理,Medium
TCG-114460.030.080,登入錯誤訊息顯示,Low
\`\`\`

共 3 筆，欄位：test_case_number / title / priority。
```

錯誤：沒加 `csv` 語言標籤、用 markdown 表格代替、含逗號欄位未 quote。

## 範例 2：JSON

使用者：「把這個 config 給我 json 格式」

```
\`\`\`json
{
  "app": {
    "name": "TCRT",
    "port": 9999,
    "database_url": "mysql+asyncmy://root:***@127.0.0.1:3306/tcrt_main"
  },
  "features": {
    "deep_links_enabled": true,
    "skill_approval_required": false
  }
}
\`\`\`

注意：密碼已用 `***` 遮罩，部署前請替換為實際值。
```

## 範例 3：YAML

使用者：「給我 kubernetes deployment yaml」

```
\`\`\`yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tcrt
  labels:
    app: tcrt
spec:
  replicas: 2
  selector:
    matchLabels:
      app: tcrt
  template:
    metadata:
      labels:
        app: tcrt
    spec:
      containers:
        - name: tcrt
          image: ghcr.io/tt-win/tcrt_user_story:latest
          ports:
            - containerPort: 9999
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: tcrt-secrets
                  key: database-url
\`\`\`
```

## 範例 4：Shell script

使用者：「給我一個清理舊 test run 的 shell script」

```
\`\`\`bash
#!/usr/bin/env bash
set -euo pipefail

# 刪除 30 天前且狀態為 completed 的 test run
DAYS_OLD=30
STATUS="completed"

mysql -h 127.0.0.1 -u tcrt -p"$DB_PASSWORD" tcrt_main -e "
  DELETE FROM test_runs
  WHERE status = '$STATUS'
    AND created_at < DATE_SUB(NOW(), INTERVAL $DAYS_OLD DAY);
"
echo "Done."
\`\`\`

⚠️ 此腳本會刪除資料，建議先在 staging 環境驗證。
```

## 範例 5：Python script

使用者：「幫我寫一個讀這個 CSV 統計每個 priority 數量的 python」

```
\`\`\`python
import csv
from collections import Counter

with open("test_cases.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    counts = Counter(row["priority"] for row in reader)

for priority, n in counts.most_common():
    print(f"{priority}: {n}")
\`\`\`

執行：`python count.py`。若無 `test_cases.csv`，先把 CSV 存到同目錄。
```

## 範例 6：.env 設定檔

使用者：「給我 .env 設定檔」

```
\`\`\`.env
APP_ENV=production
DATABASE_URL=mysql+asyncmy://user:password@db-host:3306/tcrt_main
REDIS_URL=redis://redis-host:6379/0
SECRET_KEY=replace-with-32-char-random-string
ALLOWED_HOSTS=tcrt.example.com
\`\`\`

請將 `password` 與 `SECRET_KEY` 替換為實際值，勿直接 commit 此檔（已加入 `.gitignore`）。
```

## 範例 7：含特殊字元的 CSV（逗號 / 雙引號 / 換行）

- title = `登入, 註冊, 與忘記密碼` → 整欄 quote：`(quote)...,"登入, 註冊, 與忘記密碼",High`
- title = `他說 "OK" 後繼續` → 內部 `"` 變 `""`：`"他說 ""OK"" 後繼續"`
- 含換行的 steps：整欄 quote 並保留換行（CSV 規範允許換行在引號內）
