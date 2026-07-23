## Tasks

- [ ] 1. 新增 `app/services/assistant/deep_links.py`：`build_deep_links()` 函式與 `_LINK_RULES` 規則表
- [ ] 2. 修改 `app/services/assistant/tools_test_cases.py`：`create_test_case`、`bulk_create_test_cases`、`bulk_clone_test_cases` 的 projection 追加 `"_deep_links"`
- [ ] 3. 修改 `app/services/assistant/tools_test_case_sets.py`：`create_test_case_set` 的 projection 追加 `"_deep_links"`
- [ ] 4. 修改 `app/services/assistant/tools_test_runs.py`：`create_test_run_config`、`create_test_run_set`、`restart_test_run` 的 projection 追加 `"_deep_links"`
- [ ] 5. 修改 `app/services/assistant/conversation_service.py`：`append_tool_call_and_result` 在 `json.dumps` 前注入 `build_deep_links()` 結果
- [ ] 6. 修改 `app/services/assistant/conversation_service.py`：`finalize_confirm_outcome` 新增 `tool_arguments` 參數並在 `json.dumps` 前注入 `build_deep_links()` 結果
- [ ] 7. 修改 `app/services/assistant/assistant_agent_service.py`：`run_confirm_turn` 呼叫 `finalize_confirm_outcome` 時傳入 `tool_arguments`（從 `execution_payload.body_params` 重建）
- [ ] 8. 修改 `prompts/assistant/system.md`：在「路徑總結」段落追加 `_deep_links` markdown 連結指示
- [ ] 9. 修改 `app/static/js/test-run-management/init.js`：讀取 `?set_id=` query param 自動開啟 set detail modal
- [ ] 10. 新增 `app/testsuite/test_assistant_deep_links.py`：測 `build_deep_links()` 各 tool name、缺 ID、壞 ID 型別、特殊字元 encoding
- [ ] 11. 擴充既有 assistant 測試：驗證 create 類 tool result 含 `_deep_links`
- [ ] 12. 驗證：`openspec validate add-assistant-deep-links --strict` + `uv run ruff check` + `uv run pytest app/testsuite/test_assistant_deep_links.py -q` + `node --check app/static/js/test-run-management/init.js`
- [ ] 13. 修改 `app/services/assistant/tools_test_cases.py`：`create_test_case` 的 `body_schema` 新增 `temp_upload_id` 欄位（可選 string）
- [ ] 14. 修改 `app/services/assistant/assistant_agent_service.py`：`_run_llm_loop` 在 tool call 為 `create_test_case` 時自動注入 `temp_upload_id`
- [ ] 15. 修改 `app/services/assistant/attachment_storage.py`：新增 `staging_dir()` 與 `stage_assistant_attachments()` helper
- [ ] 16. 修改 `prompts/assistant/system.md`：新增附件指示，告知 LLM 系統自動處理附件