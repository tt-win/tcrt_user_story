## ADDED Requirements

### Requirement: 知識圖譜查詢的全面記錄涵蓋

系統 SHALL 對每一次知識圖譜 / RAG 查詢寫入恰好一筆查詢記錄，涵蓋所有公開查詢入口：AI 助手工具（`search_knowledge`、`analyze_knowledge_impact`）、admin API（`GET /api/knowledge/search`、`GET /api/knowledge/impact`），以及未來經 `KnowledgeRetrievalService.build_rag_context_for_qa_helper` 進入的 QA AI Helper grounding。

業務層方法（`KnowledgeRetrievalService.search_knowledge`、`analyze_impact`）SHALL 在其**每一條回傳路徑**（含知識圖譜停用、斷路器跳脫、併發滿載快失、空查詢、無授權團隊等降級路徑，以及成功、逾時、例外路徑）各記錄一筆，使降級事件可被事後回溯。直呼 `HybridSearchService` 而不經業務層的 admin 端點 SHALL 於端點自行記錄，且 MUST NOT 為記錄而改變其既有 request/response 契約。

記錄為純觀測性疊加：MUST NOT 改變任何既有查詢的參數、篩選、結果形狀或錯誤傳遞行為。

#### Scenario: AI 助手查詢被記錄
- **WHEN** AI 助手執行 `search_knowledge` 或 `analyze_knowledge_impact` 工具且知識圖譜啟用
- **THEN** 系統寫入一筆查詢記錄，`source` 標示為助手來源，含查詢內容與結果摘要

#### Scenario: 降級查詢仍被記錄
- **WHEN** 斷路器處於跳脫狀態或併發已滿導致 `search_knowledge` 於前置檢查即快失回傳
- **THEN** 系統仍寫入一筆記錄，其 `process` 診斷標示對應的降級原因碼，`status` 標示為 degraded

#### Scenario: admin 端點查詢被記錄且契約不變
- **WHEN** 使用者呼叫 `GET /api/knowledge/search` 或 `GET /api/knowledge/impact`
- **THEN** 系統寫入一筆 `source` 標示為 API 來源的記錄，且該端點回傳的參數、結果形狀與錯誤行為與未啟用本功能時完全一致

#### Scenario: 每次查詢恰好一筆、無重覆計數
- **WHEN** 一次 `search_knowledge` 呼叫在內部因 dual-route 而多次呼叫底層 `HybridSearchService.hybrid_search`
- **THEN** 系統僅為該次查詢寫入一筆記錄，不因內部多次底層呼叫而重覆

### Requirement: 查詢記錄內容與資料安全

每筆查詢記錄 SHALL 包含：發生時間、來源（`source`）、操作類型（search／impact）、發起者（可用時的 user_id／username）、查詢內容（`search` 為查詢字串，`impact` 為 entity 型別與 id）、團隊授權範圍（primary 與 allowed teams）、查詢參數（top_k、score_threshold）、結果狀態（success／degraded）與降級原因、耗時、結果筆數、**過程診斷** `process`（dual-route 是否啟用、各 collection 嘗試/命中數、graph 是否展開/逾時、斷路器狀態），以及**精簡結果摘要** `results_summary`。

`results_summary` 每項 SHALL 僅含 entity 型別、id、截斷後的標題、分數、來源與 team_id，且 MUST NOT 包含結果全文 snippet，以避免敏感測試資料落地。查詢內容、結果標題與錯誤字串於落地前 SHALL 套用值級敏感資訊遮蔽（比照 `redact_sensitive`），並 SHALL 套用大小上限，超限時安全截斷而非整筆丟棄。

#### Scenario: 結果摘要不含全文
- **WHEN** 一次查詢命中多筆結果
- **THEN** 記錄的 `results_summary` 僅存每筆的型別/id/截斷標題/分數/來源/team_id，不含全文或 xml snippet

#### Scenario: 敏感內容被遮蔽
- **WHEN** 查詢字串或錯誤訊息內含疑似憑證樣式字串（如 Bearer token、`key=value`）
- **THEN** 落地的記錄中該等片段已被遮蔽

#### Scenario: 過大內容被截斷而非丟棄
- **WHEN** 待記錄的過程或結果摘要 JSON 超過設定的大小上限
- **THEN** 記錄以安全截斷後的內容落地，該筆記錄仍成功寫入

### Requirement: Fail-safe 非阻斷寫入

查詢記錄寫入 SHALL 為 fail-safe：記錄失敗（序列化錯誤、audit DB 不可用、鎖等待等）MUST NOT 使任何知識圖譜查詢失敗、降級或阻斷，且 MUST NOT 影響 `KnowledgeRetrievalService` 的斷路器失敗計數。

寫入 SHALL 在業務層 semaphore 釋放之後、且在斷路器 `try/except` 之外進行；查詢路徑上的記錄動作 SHALL 為有界且非阻塞（緩衝 append，實際 DB 寫入由批次 flush 承擔），MUST NOT 於查詢路徑上同步等待 DB I/O。系統關機時 SHALL 於 audit DB 連線釋放之前 flush 尚未寫出的緩衝記錄。

#### Scenario: 記錄失敗不影響查詢
- **WHEN** 查詢成功但記錄寫入拋出例外
- **THEN** 查詢照常回傳成功結果，斷路器失敗計數不增加，錯誤僅記於伺服器 log

#### Scenario: 記錄不佔用查詢併發預算
- **WHEN** 一次 `search_knowledge` 查詢完成
- **THEN** 記錄動作在併發 semaphore 釋放之後才進行，不因記錄的 DB 寫入而佔用查詢併發格

#### Scenario: 關機時緩衝不遺失
- **WHEN** 應用進入關機流程且緩衝中仍有未寫出的記錄
- **THEN** 系統於 audit DB 連線釋放前 flush 這些記錄

### Requirement: 專用可攜儲存與保留清理

查詢記錄 SHALL 持久化於 audit DB 的專用表 `knowledge_query_logs`，其 schema 與遷移 MUST 跨 SQLite、MySQL 8 與 PostgreSQL 16 可攜（JSON 內容以可攜 TEXT 型別＋序列化字串儲存，列舉欄以非原生列舉字串儲存）。

系統 SHALL 提供以保留天數為界的清理：刪除早於保留期的記錄，且清理 SQL MUST 為跨三種引擎可攜（以時間戳條件刪除，MUST NOT 使用單一引擎專屬的 `DELETE ... LIMIT` 或自我參照子查詢的列數上限刪除）。清理 SHALL 週期性執行而非每次寫入皆執行，避免與其他 audit 寫入爭用寫鎖。功能 SHALL 可經設定旗標停用；停用時不寫入任何記錄。

#### Scenario: 逾保留期記錄被清理
- **WHEN** 清理執行且存在早於保留天數的記錄
- **THEN** 這些記錄被刪除，保留期內的記錄不受影響

#### Scenario: 功能停用時不記錄
- **WHEN** 記錄功能經設定旗標停用
- **THEN** 任何知識圖譜查詢皆不產生記錄，查詢行為不受影響

### Requirement: Super Admin 唯讀查詢記錄 API

系統 SHALL 提供唯讀 API `GET /api/admin/knowledge-query-logs`（及單筆詳情端點），受 `require_super_admin` 保護，支援分頁與依來源、狀態、團隊、時間區間、查詢文字的篩選，回應 SHALL 帶 `Cache-Control: no-store`。因記錄可含跨團隊資訊，該 API MUST NOT 對低於 Super Admin 的角色開放。

#### Scenario: Super Admin 分頁查詢
- **WHEN** Super Admin 呼叫該 API 並帶分頁與篩選參數
- **THEN** 回傳符合條件的記錄分頁結果與總數

#### Scenario: 非 Super Admin 被拒
- **WHEN** 非 Super Admin 角色呼叫該 API
- **THEN** 請求被後端拒絕（403）

### Requirement: /system-logs 知識圖譜查詢記錄分頁

`/system-logs` 頁面 SHALL 提供一個**獨立分頁**「知識圖譜查詢記錄」，沿用該頁既有的 Super Admin 授權模型與分頁 shell。此分頁 SHALL 於被切換顯示時才延遲載入其資料（`shown.bs.tab`），MUST NOT 因其存在而在其他分頁被開啟時即主動抓取查詢記錄。

分頁 SHALL 提供篩選列、分頁表格與單筆詳情檢視；表格列內容 MUST 以 `createElement`／`textContent` 落地（延續本頁禁用 `innerHTML` 的安全契約）。所有使用者可見文案 SHALL 提供 en-US、zh-CN、zh-TW 三語系並經 i18n 機制輸出（含筆數等參數化文案與經共用格式器呈現的時間戳），MUST NOT 硬編寫死字串。

#### Scenario: 分頁延遲載入
- **WHEN** Super Admin 首次切換至知識圖譜查詢記錄分頁
- **THEN** 該分頁才發出查詢記錄 API 請求並渲染第一頁；切換至其他分頁不觸發此請求

#### Scenario: 列內容安全渲染
- **WHEN** 某筆記錄的查詢文字含 HTML 樣式字元
- **THEN** 該內容以純文字呈現，不被當作 HTML 解譯

#### Scenario: 三語系文案
- **WHEN** 使用者切換介面語言為 en-US、zh-CN 或 zh-TW
- **THEN** 該分頁的欄位標題、篩選標籤、狀態與筆數文案皆以對應語系顯示
