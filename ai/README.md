# AI RAG System 設計與使用說明書

本文件詳細說明 Test Case Repository Tool (TCRT) 的 AI RAG (Retrieval-Augmented Generation) 系統架構、資料流與操作方式，供後續開發與維護參考。

## 1. 系統架構

本系統旨在透過 RAG 技術，讓 LLM 能夠基於 TCRT 內部的測試案例 (Test Cases) 與使用者故事地圖 (User Story Map, USM) 資料，回答使用者的問題。

### 核心組件

1.  **FastAPI Backend (`app/api/llm_context.py`)**:
    *   提供專用的資料提取端點，將結構化資料轉換為語意化文本。
    *   負責權限檢查與資料過濾。
2.  **ETL Scripts (`ai/etl_all_teams.py`)**:
    *   負責從 Backend 提取資料。
    *   呼叫 Embedding Service 產生向量。
    *   將資料與向量寫入 Vector Database。
3.  **Vector Database (Qdrant)**:
    *   儲存 Test Case 與 USM Node 的向量與 Metadata。
    *   提供向量相似度搜尋與 Metadata 過濾。
4.  **RAG Client (`ai/rag_cli.py`)**:
    *   使用者互動介面 (CLI)。
    *   負責意圖識別、混合搜尋、結構化擴展與 Prompt 組裝。
    *   呼叫 LLM 生成回答。
5.  **LLM & Embedding Services**:
    *   **LLM**: OpenRouter (預設模型: `google/gemini-2.0-flash-001`)。
    *   **Embedding**: 本地服務 (預設模型: `text-embedding-bge-m3`, 維度: 1024)。

---

## 2. 資料流 (Data Flow)

### 2.1 資料準備 (ETL)

1.  **提取 (Extract)**: ETL 腳本呼叫 `/api/llm-context/test-cases` 與 `/api/llm-context/usm`。
    *   API 會將 `title`, `steps`, `expected_result` 等欄位組合成單一 `text` 欄位。
    *   API 會將 `children_ids`, `related_node_ids`, `tcg_tickets` 等關聯資訊放入 `metadata`。
2.  **轉換 (Transform)**:
    *   將 `text` 送往 Embedding Service 取得 1024 維向量。
    *   產生 deterministic UUID (基於 `id` 與 `resource_type`) 以避免重複寫入。
3.  **載入 (Load)**:
    *   分批 (Batch Size: 50) 寫入 Qdrant 的 `test_cases` 與 `usm_nodes` Collections。

### 2.2 檢索與生成 (RAG)

1.  **使用者提問**: 使用者在 CLI 輸入問題。
2.  **查詢改寫 (Rewrite)**: LLM 根據對話歷史 (History) 改寫問題，補全指代不明的詞彙。
3.  **意圖識別**:
    *   **Team Intent**: 偵測是否包含團隊關鍵字 (如 `ARD`, `GED`) -> 產生 Qdrant Filter。
    *   **Resource Intent**: 偵測是問「測試案例」還是「需求」 -> 決定搜尋哪個 Collection。
4.  **混合搜尋 (Hybrid Search)**:
    *   Qdrant 根據向量相似度 + Metadata Filter 進行檢索。
5.  **結構化擴展 (Structural Expansion)**:
    *   若搜到 USM Node，自動撈取其子節點 (Children) 內容。
    *   若搜到 USM Node，自動根據 `jira_tickets` 撈取關聯的 Test Cases。
6.  **生成回答**:
    *   將原始檢索結果 + 擴展資料組裝成 Context。
    *   LLM 根據 Context 與 System Prompt 生成 Markdown 格式回答。
    *   CLI 使用 `rich` 函式庫渲染 Markdown。

---

## 3. 檔案說明

所有腳本位於 `ai/` 目錄下：

| 檔案名稱 | 用途 | 關鍵函式/類別 |
| :--- | :--- | :--- |
| **`etl_all_teams.py`** | **核心 ETL 腳本**。處理所有團隊的資料同步。 | `process_team`, `process_items_in_batches` |
| **`rag_cli.py`** | **RAG 互動介面**。包含完整的檢索與問答邏輯。 | `rewrite_query`, `expand_search_results`, `query_llm` |
| `clear_qdrant.py` | 清空 Qdrant 中的所有 Collections。 | `clear_collections` |
| `inspect_qdrant.py` | 檢驗 Qdrant 中的資料筆數與範例內容。 | `inspect_collection` |
| `etl_retry_teams.py` | (備用) 僅針對特定團隊重試 ETL，用於處理 Timeout。 | `TARGET_TEAM_IDS` |
| `test_llm_context.py`| (測試用) 測試 Backend Context API 是否正常回傳。 | `get_test_cases_context` |

---

## 4. 環境設定與配置

### 必要的環境變數/常數

在 `ai/rag_cli.py` 與 `ai/etl_all_teams.py` 中可調整以下設定：

*   `QDRANT_URL`: Qdrant 服務位址 (預設 `http://localhost:6333`)
*   `TEXT_EMBEDDING_URL`: Embedding 服務位址 (預設 `http://127.0.0.1:1234/v1/embeddings`)
*   `LLM_API_URL`: LLM Chat Completion 端點
*   `OPENROUTER_API_KEY`: OpenRouter API Key
*   `VECTOR_SIZE`: **1024** (對應 `text-embedding-bge-m3`)
*   `COLLECTION_TC`: `test_cases`
*   `COLLECTION_USM`: `usm_nodes`

### 相依套件

*   `qdrant-client`
*   `requests`
*   `prompt_toolkit` (CLI 互動)
*   `rich` (CLI 排版)

---

## 5. 開發指南 (How-to)

### 如何新增新的 Metadata 欄位？

1.  修改 `app/api/llm_context.py`:
    *   在 `EmbeddingDocument` 的 `metadata` 中加入新欄位。
    *   在 `get_test_cases_context` 或 `get_usm_context` 中填入資料。
2.  執行 `python ai/etl_all_teams.py` 更新 Qdrant 資料。

### 如何更換 Embedding 模型？

1.  確認 Embedding Server 支援新模型。
2.  修改 `ai/etl_all_teams.py`:
    *   更新 `VECTOR_SIZE` (例如改回 768)。
    *   更新 `get_embeddings` 中的 `model` 名稱。
3.  修改 `ai/rag_cli.py`:
    *   更新 `get_embedding` 中的 `model` 名稱。
4.  執行 `python ai/clear_qdrant.py` (因為維度變更必須重建 Collection)。
5.  執行 `python ai/etl_all_teams.py`。

### 如何調整檢索準確度？

1.  **調整 `TOP_K`**: 在 `rag_cli.py` 中增加或減少檢索筆數。
2.  **調整 `SCORE_THRESHOLD`**: 設定相似度門檻，過濾低相關性的結果。
3.  **優化 Intent Detection**: 在 `detect_team_intent` 或 `detect_resource_intent` 中增加關鍵字或改用 LLM 進行意圖判斷。

---

## 6. 常見問題

*   **Q: ETL 執行時發生 Timeout?**
    *   A: 腳本已實作分批處理 (`BATCH_SIZE=50`)。若仍發生，可嘗試降低 Batch Size 或檢查網路連線。
*   **Q: 搜尋不到剛新增的資料？**
    *   A: 目前 ETL 是手動觸發的。資料變更後需重新執行 `python ai/etl_all_teams.py`。未來可考慮在 Backend 實作即時 Hook 或定時排程。
*   **Q: `Vector dimension error`?**
    *   A: 表示 Qdrant Collection 的維度與 Embedding 模型不符。請執行 `clear_qdrant.py` 後重新 ETL。
