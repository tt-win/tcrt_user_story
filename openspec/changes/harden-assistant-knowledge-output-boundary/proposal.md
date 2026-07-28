## Why

紅隊測試（`app/testsuite/test_assistant_knowledge_redteam.py`）以探針重現兩個知識檢索的資料輸出邊界缺口，且與現行 `assistant-data-boundary` 契約矛盾：

1. **底層例外原文外洩**：`search_knowledge` 降級時，`KnowledgeRetrievalService` 把原始例外訊息塞進 `result["message"]`（探針取得 `Knowledge search unavailable: Neo4j bolt://secret-host:7687 auth failed for user neo4j`），而 `search_knowledge` 工具的 projection allowlist 含 `message` → 基礎設施位址／帳號等內部細節直達 LLM 與持久化訊息。
2. **知識內容逃逸 XML 包裝**：被索引的 test case／USM 內容若含 `</knowledge_source>`，`xml_snippet` 未跳脫即輸出，payload 以「包裝外文字」出現在 LLM context，構成經知識圖譜的 prompt injection 載體。

兩者都是資料安全問題（rule：AI helper / 外送邊界變更需點出影響），現在修是因為知識工具已整合進全域助手且預設可被任何角色讀取。

## What Changes

- `KnowledgeRetrievalService` 降級回應的 `message` 改為**通用、不含後端細節**的固定字串；原始例外只進伺服器端日誌，不進工具結果、`assistant_messages`、SSE。
- 知識結果的 `snippet` / `title` 在組成 `xml_snippet` 前先**中和結構性分隔符**（`<knowledge_source>` / `</knowledge_source>` 及角括號），使被索引內容無法逃出其包裝或偽造包裝邊界。
- 既有紅隊測試中對應的兩個 `xfail(strict=True)`（`test_H1_*`、`test_INJ1_*`）翻轉為正向斷言。
- 不改變團隊授權模型、不改 Qdrant/Neo4j 查詢、不改 projection allowlist 欄位集合。

## Capabilities

### New Capabilities
<!-- 無新增 capability -->

### Modified Capabilities
- `assistant-data-boundary`: 新增兩條 requirement——(1) 知識檢索降級訊息不得洩漏後端／基礎設施細節；(2) 知識結果內容進入結構化包裝前 MUST 中和分隔符，防止經知識圖譜的包裝逃逸與 prompt injection。同時把洩漏防護自動化測試涵蓋範圍擴及這兩條。

## Impact

- 程式：`app/services/knowledge/retrieval_service.py`（degraded `message`、`_process_results_generator` 的 `xml_snippet` 組裝）。若 `xml_snippet` 由 `hybrid_search_service` 端組出，一併於該處中和。
- 測試：`app/testsuite/test_assistant_knowledge_redteam.py`（翻轉兩個 xfail）；沿用既有 fake Qdrant/Neo4j，無需外部服務。
- 無 migration、無 schema、無 API 介面變更；行為變更僅限於「送往 LLM 的字串內容」，對正常查詢結果為 no-op。
- 相容性：降級 `message` 字串內容改變，但其語意（degraded + `fallback_recommended`）不變，LLM 回退 SQL 的行為不受影響。
