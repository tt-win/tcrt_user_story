# assistant-data-boundary Delta — harden-assistant-knowledge-output-boundary

## ADDED Requirements

### Requirement: 知識檢索降級訊息不得洩漏後端細節

知識檢索（`search_knowledge` / `analyze_knowledge_impact`）於降級（degraded）時回傳的 `message` 欄位 MUST 為通用、與後端無關的固定字串；MUST NOT 內插原始例外物件、後端連線字串、主機位址、埠號、資料庫帳號或堆疊細節。原始例外 MAY 僅寫入伺服器端日誌與觀測性記錄（query log 的 `degrade_reason`），MUST NOT 進入送往 LLM 的工具結果、`assistant_messages` 或 SSE。

此要求適用於所有降級成因（知識圖譜未啟用、斷路器開啟、並發飽和、逾時、後端例外）；`message` 仍可傳達「暫時不可用、建議回退」的語意，但不得攜帶診斷細節。

#### Scenario: 後端例外不洩漏於降級訊息
- **WHEN** 知識搜尋因後端例外而降級（例外訊息含 `bolt://host:port` 或資料庫帳號）
- **THEN** 回傳的 `message` 為通用不可用字串，不含主機、埠、帳號或例外類別細節
- **AND** 送往 LLM 的工具結果與持久化訊息同樣不含這些細節

#### Scenario: 降級語意仍可用於回退判斷
- **WHEN** 知識搜尋降級
- **THEN** 回應仍帶 `status="degraded"` 與 `fallback_recommended=true`，LLM 可據此改用 SQL 關鍵字搜尋

### Requirement: 知識結果進入結構化包裝前 MUST 中和分隔符

知識檢索結果在組成送往 LLM 的結構化包裝（`xml_snippet`，以 `<knowledge_source>...</knowledge_source>` 界定）前，MUST 中和被索引內容（`snippet` 及任何納入包裝的欄位如 `title`）中的結構性分隔符，使被索引內容無法產生或偽造包裝邊界。中和 MUST 在長度截斷之後套用，確保截斷不會產生半截標籤。

此為防止經知識圖譜載入的內容逃出其資料包裝、對 LLM 冒充系統邊界或注入指令（prompt injection via knowledge content）。中和後每筆結果的 `xml_snippet` MUST 僅含恰一組開頭與結尾包裝標籤，且被索引內容中不得出現字面 `</knowledge_source>`。

#### Scenario: 被索引內容無法逃出包裝
- **WHEN** 某 test case／USM 內容含 `</knowledge_source>` 及後續指示文字並被知識搜尋命中
- **THEN** 該結果的 `xml_snippet` 僅含一組包裝標籤，內容中的 `</knowledge_source>` 已被中和，指示文字仍留在包裝內作為資料

#### Scenario: 洩漏防護自動化測試涵蓋知識輸出邊界
- **WHEN** 執行洩漏防護自動化測試
- **THEN** 測試涵蓋（1）降級訊息不含後端細節、（2）被索引內容無法逃出 `xml_snippet` 包裝兩種情境
