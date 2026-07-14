# Tasks — remove-qdrant-support

## 1. 程式碼移除

- [x] 1.1 刪除 `app/services/qdrant_client.py`。
- [x] 1.2 `app/main.py`：移除啟動 lifespan 內的 Qdrant health check 區塊與
      shutdown 的 `close_qdrant_client()` 呼叫。
- [x] 1.3 `app/config.py`：刪除 `QdrantConfig` / `QdrantWeightsConfig` /
      `QdrantLimitConfig` 類別、`Settings.qdrant` 欄位、`from_env_and_file` 的
      `qdrant=...` 組裝、`create_default_config` 的 `"qdrant"` 區塊，以及
      `_warn_container_runtime_configuration` 中 `QDRANT_URL` /
      `TEXT_EMBEDDING_URL` 兩個檢查項。
- [x] 1.4 `pyproject.toml`：以 `uv remove qdrant-client` 移除相依（同步 uv.lock）。
- [x] 1.5 刪除整個 `ai/` 目錄（ETL 與 PoC 腳本，全數依賴 qdrant-client）。
- [x] 1.6 刪除 `app/api/llm_context.py` 與 `app/main.py` 的 router 註冊
      （唯一消費者是 `ai/` 的 ETL；`jira-ticket-to-test-case-poc` spec 為現役
      QA AI Helper 契約、與被刪 PoC 腳本無關，保留）。

## 2. 測試

- [x] 2.1 將 `test_qdrant_client_service.py` 中與 Qdrant 無關的 Settings 測試
      （container-runtime localhost 警告、SQLite fail-fast ×3、Jira env 等）搬到
      `app/testsuite/test_settings_container_runtime.py`，其餘 Qdrant client 測試
      隨檔刪除。
- [x] 2.2 刪除 `app/testsuite/test_qdrant_usage_guard.py`。
- [x] 2.3 `uv run pytest app/testsuite/test_settings_container_runtime.py -q` 通過；
      全 repo `rg -i qdrant app --glob '*.py'` 無殘留。

## 3. 文件與設定範例

- [x] 3.1 `.env.docker.example`：移除 `QDRANT_*` 全部與 `TEXT_EMBEDDING_URL` /
      `EMBEDDING_API_URL` 區塊；頂部註解同步（外部服務清單不再含 Qdrant/Embedding）。
- [x] 3.2 `README.md`：移除「Qdrant 向量資料庫」env 表與 `TEXT_EMBEDDING_URL` 列。
- [x] 3.3 `docs/docker-app-setup.md`：移除前置條件與範例中的 Qdrant / Text
      Embedding 項目。
- [x] 3.4 `docs/database-cutover-readiness.md`：移除 Qdrant 相關描述（如有）。
- [x] 3.5 `docs/AI_HELPER_IR_FIRST_RUNBOOK.md` 等歷史文件僅屬敘述性提及者，
      維持不動（記錄當時脈絡，不構成使用中的契約）。

## 4. 驗證

- [x] 4.1 `uv run pytest app/testsuite -q`（既有 baseline 失敗之外零新增失敗）。
- [x] 4.2 `uv run ruff check app scripts database_init.py` 對變更檔乾淨。
- [x] 4.3 `openspec validate remove-qdrant-support --strict` 通過。
- [x] 4.4 App 可正常啟動（無 Qdrant 相關 import error）。
