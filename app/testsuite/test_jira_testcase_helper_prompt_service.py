from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.services.jira_testcase_helper_llm_service import JiraTestCaseHelperLLMService
from app.services.jira_testcase_helper_prompt_service import (
    JiraTestCaseHelperPromptService,
)


def _write_config(path: Path, extra_yaml: str = "") -> None:
    path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n"
        + extra_yaml,
        encoding="utf-8",
    )


def test_helper_model_defaults_from_settings(tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper

    assert helper.models.analysis.model == "google/gemini-3-flash-preview"
    assert helper.models.testcase.model == "google/gemini-3-flash-preview"
    assert helper.models.audit.model == "google/gemini-3-flash-preview"
    assert not hasattr(helper.models, "coverage")
    assert helper.enable_ir_first is True
    assert helper.coverage_backfill_max_rounds == 1
    assert helper.coverage_backfill_chunk_size == 12


def test_stage_model_override_for_available_phases_from_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "ai:\n"
        "  jira_testcase_helper:\n"
        "    models:\n"
        "      analysis:\n"
        "        model: custom/analysis-model\n"
        "      testcase:\n"
        "        model: custom/testcase-model\n"
        "      audit:\n"
        "        model: custom/audit-model\n",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper

    assert helper.models.analysis.model == "custom/analysis-model"
    assert helper.models.testcase.model == "custom/testcase-model"
    assert helper.models.audit.model == "custom/audit-model"


def test_ir_first_flags_can_be_overridden(tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "ai:\n"
        "  jira_testcase_helper:\n"
        "    enable_ir_first: false\n"
        "    coverage_backfill_max_rounds: 2\n"
        "    coverage_backfill_chunk_size: 8\n",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.jira_testcase_helper
    assert helper.enable_ir_first is False
    assert helper.coverage_backfill_max_rounds == 2
    assert helper.coverage_backfill_chunk_size == 8


def test_render_stage_prompt_reads_from_prompt_file(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "analysis.md").write_text(
        "ticket={ticket_key}\nir={requirement_ir_json}",
        encoding="utf-8",
    )

    service = JiraTestCaseHelperPromptService(
        Settings().ai.jira_testcase_helper,
        prompt_dir=prompt_dir,
    )
    rendered = service.render_stage_prompt(
        "analysis",
        {"ticket_key": "TCG-130078", "requirement_ir_json": '{"rid":"REQ-001"}'},
    )
    assert rendered == 'ticket=TCG-130078\nir={"rid":"REQ-001"}'


def test_missing_prompt_file_falls_back_to_machine_template(tmp_path):
    prompt_dir = tmp_path / "missing-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    service = JiraTestCaseHelperPromptService(
        Settings().ai.jira_testcase_helper,
        prompt_dir=prompt_dir,
    )
    rendered = service.render_stage_prompt(
        "testcase",
        {"ticket_key": "TCG-1", "coverage_questions_json": '{"sec":[]}'},
    )
    assert "Testcase 轉換器" in rendered
    assert "TCG=TCG-1" in rendered


def test_render_machine_prompt_falls_back_when_analysis_prompt_lacks_merged_contract(
    tmp_path,
):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "analysis.md").write_text(
        "machine-source {ticket_key} {review_language}",
        encoding="utf-8",
    )

    service = JiraTestCaseHelperPromptService(
        Settings().ai.jira_testcase_helper,
        prompt_dir=prompt_dir,
    )
    rendered = service.render_machine_stage_prompt(
        "analysis",
        {"ticket_key": "TCG-1", "review_language": "繁體中文"},
    )
    assert "Analysis+Coverage 合併轉換器" in rendered
    assert "TCG=TCG-1" in rendered
    assert "REQUIREMENT_IR_JSON" in rendered


def test_render_machine_prompt_uses_file_when_contract_is_merged(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "analysis.md").write_text(
        '一次輸出 analysis 與 coverage，並考慮 happy path/edge test cases/error handling/permission，使用 seed.ax；ticket={ticket_key}{"coverage":true}',
        encoding="utf-8",
    )

    service = JiraTestCaseHelperPromptService(
        Settings().ai.jira_testcase_helper,
        prompt_dir=prompt_dir,
    )
    rendered = service.render_machine_stage_prompt(
        "analysis",
        {"ticket_key": "TCG-9", "review_language": "繁體中文"},
    )
    assert "ticket=TCG-9" in rendered
    assert "seed.ax" in rendered


def test_render_machine_testcase_prompt_requires_detailed_pre_step_exp(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "testcase.md").write_text(
        "簡化 testcase prompt without quality contract",
        encoding="utf-8",
    )

    service = JiraTestCaseHelperPromptService(
        Settings().ai.jira_testcase_helper,
        prompt_dir=prompt_dir,
    )
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
