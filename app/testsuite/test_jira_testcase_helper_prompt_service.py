from app.config import Settings
from app.services.jira_testcase_helper_llm_service import JiraTestCaseHelperLLMService
from app.services.jira_testcase_helper_prompt_service import (
    JiraTestCaseHelperPromptService,
)


def test_helper_model_defaults_from_settings(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper

    assert helper.models.analysis.model == "google/gemini-3-flash-preview"
    assert helper.models.coverage.model == "openai/gpt-5.2"
    assert helper.models.testcase.model == "google/gemini-3-flash-preview"
    assert helper.models.audit.model == "google/gemini-3-flash-preview"
    assert helper.enable_ir_first is True
    assert helper.coverage_backfill_max_rounds == 1
    assert helper.coverage_backfill_chunk_size == 12
    assert "{requirement_ir_json}" in helper.prompts.analysis
    assert "{missing_ids_json}" in helper.prompts.coverage_backfill
    assert "JSON.parse" in helper.prompts.coverage
    assert "{coverage_questions_json}" in helper.prompts.testcase
    assert "{testcase_json}" in helper.prompts.audit


def test_render_analysis_prompt_with_replacements():
    service = JiraTestCaseHelperPromptService(Settings().ai.jira_testcase_helper)

    rendered = service.render_stage_prompt(
        "analysis",
        {
            "review_language": "繁體中文",
            "ticket_key": "TCG-130078",
            "requirement_ir_json": '{"scenarios":[{"rid":"REQ-001"}]}',
            "similar_cases": "Similar Case 1: ...",
        },
    )

    assert "TCG-130078" in rendered
    assert "REQ-001" in rendered
    assert "{ticket_key}" not in rendered


def test_render_requirement_ir_prompt_with_replacements():
    service = JiraTestCaseHelperPromptService(Settings().ai.jira_testcase_helper)

    rendered = service.render_stage_prompt(
        "requirement_ir",
        {
            "review_language": "繁體中文",
            "ticket_key": "TCG-93178",
            "ticket_summary": "Reference 欄位規則調整",
            "ticket_description": "需要保留 fixed/sortable/format 規則",
            "ticket_components": "Search",
            "similar_cases": "case-A",
        },
    )
    assert "TCG-93178" in rendered
    assert "fixed_lr" in rendered
    assert "{ticket_description}" not in rendered


def test_render_audit_prompt_with_testcase_payload():
    service = JiraTestCaseHelperPromptService(Settings().ai.jira_testcase_helper)

    rendered = service.render_stage_prompt(
        "audit",
        {
            "output_language": "English",
            "coverage_questions_json": "{\"sec\":[]}",
            "testcase_json": "{\"tc\":[{\"id\":\"TCG-1.010.010\"}]}",
            "ticket_key": "TCG-1",
        },
    )

    assert "English" in rendered
    assert "TCG-1.010.010" in rendered
    assert "{testcase_json}" not in rendered


def test_custom_prompt_override_from_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n"
        "ai:\n"
        "  jira_testcase_helper:\n"
        "    models:\n"
        "      coverage:\n"
        "        model: openai/gpt-5.2-custom\n"
        "    prompts:\n"
        "      analysis: 'custom analysis for {ticket_key}'\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper

    assert helper.models.coverage.model == "openai/gpt-5.2-custom"

    service = JiraTestCaseHelperPromptService(helper)
    rendered = service.render_stage_prompt("analysis", {"ticket_key": "TCG-99"})
    assert rendered == "custom analysis for TCG-99"


def test_stage_model_override_for_all_phases_from_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n"
        "ai:\n"
        "  jira_testcase_helper:\n"
        "    models:\n"
        "      analysis:\n"
        "        model: custom/analysis-model\n"
        "      coverage:\n"
        "        model: custom/coverage-model\n"
        "      testcase:\n"
        "        model: custom/testcase-model\n"
        "      audit:\n"
        "        model: custom/audit-model\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper

    assert helper.models.analysis.model == "custom/analysis-model"
    assert helper.models.coverage.model == "custom/coverage-model"
    assert helper.models.testcase.model == "custom/testcase-model"
    assert helper.models.audit.model == "custom/audit-model"


def test_ir_first_config_and_prompt_keys_can_be_overridden(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n"
        "ai:\n"
          "  jira_testcase_helper:\n"
          "    enable_ir_first: false\n"
          "    coverage_backfill_max_rounds: 2\n"
          "    coverage_backfill_chunk_size: 8\n"
          "    prompts:\n"
          "      requirement_ir: 'ir prompt {ticket_key}'\n"
          "      coverage_backfill: 'backfill {missing_ids_json}'\n",
          encoding="utf-8",
      )

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper
    assert helper.enable_ir_first is False
    assert helper.coverage_backfill_max_rounds == 2
    assert helper.coverage_backfill_chunk_size == 8
    assert helper.prompts.requirement_ir == "ir prompt {ticket_key}"
    assert helper.prompts.coverage_backfill == "backfill {missing_ids_json}"


def test_render_machine_prompt_falls_back_when_analysis_prompt_lacks_merged_contract(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n"
        "ai:\n"
        "  jira_testcase_helper:\n"
        "    prompts:\n"
        "      analysis: 'machine-source {ticket_key} {review_language}'\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    service = JiraTestCaseHelperPromptService(loaded.ai.jira_testcase_helper)
    rendered = service.render_machine_stage_prompt(
        "analysis",
        {"ticket_key": "TCG-1", "review_language": "繁體中文"},
    )
    assert "Analysis+Coverage 合併轉換器" in rendered
    assert "TCG=TCG-1" in rendered
    assert "REQUIREMENT_IR_JSON" in rendered


def test_render_machine_prompt_uses_config_analysis_when_contract_is_merged(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n"
        "ai:\n"
        "  jira_testcase_helper:\n"
        "    prompts:\n"
        "      analysis: '一次輸出 analysis 與 coverage，並考慮 happy path/edge test cases/error handling/permission，使用 seed.ax；ticket={ticket_key}'\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    service = JiraTestCaseHelperPromptService(loaded.ai.jira_testcase_helper)
    rendered = service.render_machine_stage_prompt(
        "analysis",
        {"ticket_key": "TCG-9", "review_language": "繁體中文"},
    )
    assert "ticket=TCG-9" in rendered
    assert "seed.ax" in rendered


def test_render_machine_testcase_prompt_requires_detailed_pre_step_exp(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n",
        encoding="utf-8",
    )
    loaded = Settings.from_env_and_file(str(config_path))
    service = JiraTestCaseHelperPromptService(loaded.ai.jira_testcase_helper)
    rendered = service.render_machine_stage_prompt(
        "testcase",
        {
            "output_language": "繁體中文",
            "ticket_key": "TCG-130078",
            "section_name": "Auth",
            "section_no": "010",
            "coverage_questions_json": '{"sec":[]}',
        },
    )

    assert ("pre 必須至少 2 條" in rendered) or ("pre 至少 2 條" in rendered)
    assert ("s 必須至少 3 步" in rendered) or ("s 至少 3 步" in rendered)
    assert "exp 必須且只能" in rendered
    assert (
        "禁止在 pre/s/exp 使用 REF/同上/略/TBD/N/A" in rendered
        or "pre/s/exp 禁止出現 REF/同上/略/TBD/N/A" in rendered
    )


def test_prompt_service_exposes_contract_versions():
    helper = Settings().ai.jira_testcase_helper
    service = JiraTestCaseHelperPromptService(helper)
    versions = service.get_contract_versions()
    assert versions["prompt_contract_version"] == helper.prompt_contract_version
    assert versions["payload_contract_version"] == helper.payload_contract_version


def test_legacy_stage_model_alias_resolves_to_preview():
    assert (
        JiraTestCaseHelperLLMService._resolve_stage_model_id("google/gemini-3-flash")
        == "google/gemini-3-flash-preview"
    )


def test_non_legacy_stage_model_alias_keeps_original():
    assert (
        JiraTestCaseHelperLLMService._resolve_stage_model_id("openai/gpt-5.2")
        == "openai/gpt-5.2"
    )


def test_parse_json_payload_handles_unescaped_newline_in_string():
    raw = """
```json
{
  "sec": [
    {
      "g": "Auth",
      "it": [
        {
          "id": "010.001",
          "t": "登入成功
流程",
          "det": ["帳號密碼正確"]
        }
      ]
    }
  ],
  "it": [
    {
      "id": "010.001",
      "t": "登入成功
流程",
      "det": ["帳號密碼正確"]
    }
  ]
}
```
""".strip()

    parsed = JiraTestCaseHelperLLMService.parse_json_payload(raw)
    assert isinstance(parsed, dict)
    assert parsed["sec"][0]["it"][0]["id"] == "010.001"
    assert parsed["sec"][0]["it"][0]["t"] == "登入成功\n流程"


def test_parse_json_payload_extracts_json_from_wrapped_text_and_trailing_comma():
    raw = """
這是 coverage 結果，請取 JSON：
```json
{
  "seed": [
    {
      "g": "Auth",
      "t": "登入成功",
      "cat": "happy",
      "st": "ok",
      "ref": ["010.001"],
    }
  ],
}
```
""".strip()

    parsed = JiraTestCaseHelperLLMService.parse_json_payload(raw)
    assert isinstance(parsed, dict)
    assert parsed["seed"][0]["g"] == "Auth"


def test_parse_json_payload_repairs_missing_commas_in_coverage_payload():
    raw = """
coverage 結果如下：
```json
{
  "seed": [
    {
      "g": "Auth"
      "t": "登入成功流程",
      "cat": "happy",
      "st": "ok"
      "ref": ["010.001"]
    }
    {
      "g": "Auth",
      "t": "OTP 過期錯誤",
      "cat": "negative",
      "st": "ok",
      "ref": ["010.002"]
    }
  ]
}
```
""".strip()

    parsed = JiraTestCaseHelperLLMService.parse_json_payload(raw)
    assert isinstance(parsed, dict)
    assert len(parsed["seed"]) == 2
    assert parsed["seed"][0]["g"] == "Auth"
    assert parsed["seed"][0]["st"] == "ok"
    assert parsed["seed"][1]["ref"] == ["010.002"]


def test_extract_response_content_supports_message_content_parts():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "output_text", "text": "{\"seed\":["},
                        {"type": "output_text", "text": "{\"g\":\"Auth\"}]}"}
                    ]
                }
            }
        ]
    }
    content = JiraTestCaseHelperLLMService._extract_response_content(payload)
    assert content == "{\"seed\":[\n{\"g\":\"Auth\"}]}"


def test_extract_response_content_falls_back_to_tool_call_arguments():
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "emit_json",
                                "arguments": "{\"seed\":[{\"g\":\"Auth\"}]}",
                            }
                        }
                    ],
                }
            }
        ]
    }
    content = JiraTestCaseHelperLLMService._extract_response_content(payload)
    assert content == "{\"seed\":[{\"g\":\"Auth\"}]}"
