# Proposal — remove-qdrant-support

## Why

Qdrant 在 TCRT 內已是死代碼：全 repo 唯一的呼叫點是 `app/main.py` 啟動時的
non-blocking health check，QA AI Helper 與所有業務功能都不再進行向量檢索
（helper 已走 IR-first 路線，見 `docs/AI_HELPER_IR_FIRST_RUNBOOK.md`）。
`TEXT_EMBEDDING_URL` 的唯一消費者也是 Qdrant service，一併成為孤兒。
`openspec/specs/etl-all-teams` 描述的「同步到 Qdrant」ETL 在 repo 內沒有任何實作。

保留這些帶來的成本：啟動時多一次外部服務連線嘗試與警告噪音、`qdrant-client`
相依套件、一整組無效的 `QDRANT_*` / `TEXT_EMBEDDING_URL` 環境變數與文件、
以及描述不存在功能的 spec。

## What Changes

- 移除 `app/services/qdrant_client.py` 與 `app/main.py` 的啟動 health check /
  關閉 hook。
- 移除整個 `ai/` 目錄（`etl_all_teams.py`、`clear_qdrant.py`、`inspect_qdrant.py`、
  `jira_to_test_case_poc.py`、`llm_config.*`、`runtime_env.py`、`README.md`）——
  全部依賴 `qdrant-client`，套件移除後已無法執行。
- 移除 `app/api/llm_context.py`（`/api/llm-context/*`）——唯一已知消費者是
  `ai/` 的 ETL。注意 `openspec/specs/jira-ticket-to-test-case-poc` 描述的是現役
  QA AI Helper 七屏流程（名稱為歷史遺留），與被刪的 PoC 腳本無關，保留不動。
- 移除 `app/config.py` 的 `QdrantConfig` / `QdrantWeightsConfig` /
  `QdrantLimitConfig`、`Settings.qdrant`、`create_default_config` 的 qdrant 區塊，
  以及 container-runtime 警告清單中的 `QDRANT_URL` / `TEXT_EMBEDDING_URL` 項目。
- 移除 `pyproject.toml` 的 `qdrant-client` 相依。
- 移除 `.env.docker.example` / `README.md` / `docs/docker-app-setup.md` /
  `docs/database-cutover-readiness.md` 中的 `QDRANT_*` 與 `TEXT_EMBEDDING_URL` /
  `EMBEDDING_API_URL` 說明。
- 測試：刪除 `test_qdrant_usage_guard.py`；`test_qdrant_client_service.py` 內
  與 Qdrant 無關的 `Settings` container-runtime / SQLite fail-fast 測試搬到新檔
  `test_settings_container_runtime.py` 後刪除原檔。
- Spec：移除 `etl-all-teams` capability（全部 requirement 標記 REMOVED）。

## Impact

- 行為面：啟動 log 少一段 Qdrant 健康檢查；其餘無使用者可見變化（沒有任何
  功能仰賴 Qdrant）。
- 部署面：`QDRANT_*` / `TEXT_EMBEDDING_URL` 環境變數變成未使用（存在也無害）；
  本機 `config.yaml` 的 `qdrant:` 區塊會被 pydantic 忽略，不需強制清理。
- 若未來要重新引入向量檢索，須開新 change 重新定義契約。
