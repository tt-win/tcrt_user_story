# Verification — remove-qdrant-support

## 自動化測試

```
uv run pytest app/testsuite -q
# 759 passed, 30 skipped, 7 failed — 7 個失敗與既有 baseline 完全相同（環境因素
# 或 main 上既有，見下），零新增回歸。
# 數字核對：766（移除前）− 13（test_qdrant_client_service.py 整檔刪除）
# − 1（test_qdrant_usage_guard.py）＋ 7（settings 測試搬到
# test_settings_container_runtime.py）= 759 ✓

uv run pytest app/testsuite/test_settings_container_runtime.py -q
# 7 passed（單獨跑；全套跑時其中 localhost 警告測試會中 main 上既有的
# Alembic fileConfig logging 汙染 order-dependent flake，與本 change 無關）

uv run ruff check app/config.py app/main.py app/testsuite/test_settings_container_runtime.py
# All checks passed!（全 repo 既有 466 個錯誤為 baseline，比移除前 473 個少——
# 刪除的 ai/ 檔案帶走部分既有錯誤）

openspec validate remove-qdrant-support --strict
# Change 'remove-qdrant-support' is valid
```

## 手動驗證

- `uv run python3 -c "import app.main"` → import OK，無 qdrant 相關 ImportError。
- `create_default_config()` 產出的 config.yaml 重新載入成功，`Settings` 不再有
  `qdrant` 屬性。
- 全 repo 殘留掃描（排除 openspec archive、graphify-out 產物、歷史敘述文件
  `docs/AI_HELPER_IR_FIRST_RUNBOOK.md` / `docs/ai_helper_schemas/`、其他 change
  的歷史 tasks/proposal）：程式碼、設定範例、部署文件皆無 Qdrant 殘留。

## 既有 baseline 失敗（7 個，皆與本 change 無關）

- `test_leader_lock_is_exclusive_across_processes`：本機另有 dev server 持
  leader 鎖（環境因素）。
- `test_db_access_guardrails_*`、`test_team_statistics_helper_*` ×3：main 上
  既有（乾淨 HEAD worktree 可重現）。
- `test_settings_loader_expands_qa_ai_helper_model_placeholders`：本機
  gitignored `.env` 的 `QA_AI_HELPER_MODEL_*` 覆蓋測試 YAML（環境因素）。
- `test_settings_warns_when_container_runtime_uses_localhost_services`：main 上
  既有的 Alembic fileConfig logging 汙染 order-dependent flake（單獨跑通過）。

## 範圍備註

- 使用者核准「全部移除」：含 `ai/` 目錄與 `/api/llm-context` 端點。
- `openspec/specs/jira-ticket-to-test-case-poc` 為現役 QA AI Helper 七屏流程
  契約（名稱為歷史遺留），與被刪的 `ai/jira_to_test_case_poc.py` PoC 腳本無關，
  保留不動。
- `prompt-toolkit`/`rich`/`textual`/`pyperclip` 僅供 `ai/` CLI 工具使用，隨
  `ai/` 刪除一併自 pyproject/requirements 移除。
