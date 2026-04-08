from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql, sqlite
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database_init
from app.audit.database import AuditBase
from app.config import Settings, create_default_config
from app.models.database_models import Base as MainBase
from app.models.qa_ai_helper import (
    QAAIHelperCounterSettings,
    QAAIHelperTeamExtensionHint,
    QAAIHelperSessionCreateRequest,
)
from app.models.user_story_map_db import Base as UserStoryMapBase
from app.services.qa_ai_helper_llm_service import QAAIHelperLLMService
from app.services.qa_ai_helper_prompt_service import QAAIHelperPromptService
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


def _write_config(path: Path, extra_yaml: str = "") -> None:
    path.write_text(
        "app:\n  port: 9999\nopenrouter:\n  api_key: ''\n" + extra_yaml,
        encoding="utf-8",
    )


def test_qa_ai_helper_counter_settings_validate_ten_step_values() -> None:
    settings = QAAIHelperCounterSettings(middle="020", tail="090")

    assert settings.middle == "020"
    assert settings.tail == "090"


def test_qa_ai_helper_counter_settings_reject_non_ten_step_values() -> None:
    with pytest.raises(ValidationError):
        QAAIHelperCounterSettings(middle="015", tail="010")


def test_qa_ai_helper_session_create_request_normalizes_ticket_key() -> None:
    request = QAAIHelperSessionCreateRequest(
        ticket_key="tcg130078",
    )

    assert request.ticket_key == "TCG-130078"


def test_qa_ai_helper_tables_are_in_main_metadata_and_bootstrap_requirements() -> None:
    metadata_tables = {
        "qa_ai_helper_sessions",
        "qa_ai_helper_canonical_revisions",
        "qa_ai_helper_planned_revisions",
        "qa_ai_helper_requirement_deltas",
        "qa_ai_helper_draft_sets",
        "qa_ai_helper_drafts",
        "qa_ai_helper_ticket_snapshots",
        "qa_ai_helper_requirement_plans",
        "qa_ai_helper_plan_sections",
        "qa_ai_helper_verification_items",
        "qa_ai_helper_check_conditions",
        "qa_ai_helper_seed_sets",
        "qa_ai_helper_seed_items",
        "qa_ai_helper_testcase_draft_sets",
        "qa_ai_helper_testcase_drafts",
        "qa_ai_helper_validation_runs",
        "qa_ai_helper_telemetry_events",
        "qa_ai_helper_commit_links",
    }
    required_tables = {
        "qa_ai_helper_sessions",
        "qa_ai_helper_ticket_snapshots",
        "qa_ai_helper_requirement_plans",
        "qa_ai_helper_plan_sections",
        "qa_ai_helper_verification_items",
        "qa_ai_helper_check_conditions",
        "qa_ai_helper_seed_sets",
        "qa_ai_helper_seed_items",
        "qa_ai_helper_testcase_draft_sets",
        "qa_ai_helper_testcase_drafts",
        "qa_ai_helper_telemetry_events",
        "qa_ai_helper_commit_links",
    }

    assert metadata_tables.issubset(set(MainBase.metadata.tables))
    assert required_tables.issubset(set(database_init.MAIN_REQUIRED_TABLES))


def test_qa_ai_helper_large_json_columns_compile_to_mediumtext_on_mysql() -> None:
    mysql_dialect = mysql.dialect()
    sqlite_dialect = sqlite.dialect()
    expected_columns = {
        "qa_ai_helper_sessions": ["source_payload_json"],
        "qa_ai_helper_canonical_revisions": ["content_json", "counter_settings_json"],
        "qa_ai_helper_planned_revisions": [
            "matrix_json",
            "seed_map_json",
            "applicability_overrides_json",
            "selected_references_json",
            "counter_settings_json",
            "impact_summary_json",
        ],
        "qa_ai_helper_requirement_deltas": ["proposed_content_json"],
        "qa_ai_helper_draft_sets": ["summary_json"],
        "qa_ai_helper_drafts": ["body_json", "trace_json"],
        "qa_ai_helper_ticket_snapshots": [
            "raw_ticket_markdown",
            "structured_requirement_json",
            "validation_summary_json",
        ],
        "qa_ai_helper_requirement_plans": [
            "criteria_reference_json",
            "technical_reference_json",
            "autosave_summary_json",
        ],
        "qa_ai_helper_plan_sections": ["given_json", "when_json", "then_json"],
        "qa_ai_helper_verification_items": ["detail_json"],
        "qa_ai_helper_seed_items": [
            "check_condition_refs_json",
            "coverage_tags_json",
            "seed_body_json",
        ],
        "qa_ai_helper_testcase_drafts": ["body_json"],
        "qa_ai_helper_validation_runs": ["summary_json", "errors_json"],
        "qa_ai_helper_telemetry_events": ["payload_json"],
    }

    for table_name, column_names in expected_columns.items():
        table = MainBase.metadata.tables[table_name]
        for column_name in column_names:
            column = table.c[column_name]
            mysql_rendered = str(column.type.compile(dialect=mysql_dialect)).upper()
            sqlite_rendered = str(column.type.compile(dialect=sqlite_dialect)).upper()
            assert mysql_rendered == "MEDIUMTEXT"
            assert sqlite_rendered == "TEXT"


def test_default_text_columns_compile_to_mediumtext_on_mysql_across_targets() -> None:
    mysql_dialect = mysql.dialect()
    representatives = [
        MainBase.metadata.tables["teams"].c["description"],
        MainBase.metadata.tables["test_cases"].c["title"],
        MainBase.metadata.tables["qa_ai_helper_plan_sections"].c["section_title"],
        MainBase.metadata.tables["qa_ai_helper_verification_items"].c["summary"],
        MainBase.metadata.tables["qa_ai_helper_check_conditions"].c["condition_text"],
        MainBase.metadata.tables["qa_ai_helper_seed_items"].c["seed_summary"],
        MainBase.metadata.tables["qa_ai_helper_seed_items"].c["comment_text"],
        AuditBase.metadata.tables["audit_logs"].c["details"],
        UserStoryMapBase.metadata.tables["user_story_maps"].c["description"],
        UserStoryMapBase.metadata.tables["user_story_map_nodes"].c["comment"],
    ]

    for column in representatives:
        mysql_rendered = str(column.type.compile(dialect=mysql_dialect)).upper()
        assert mysql_rendered == "MEDIUMTEXT"


def test_create_default_config_enables_rewritten_helper(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    create_default_config(str(config_path))
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = payload["ai"]["qa_ai_helper"]["models"]

    assert payload["ai"]["jira_testcase_helper"]["enable"] is False
    assert payload["ai"]["qa_ai_helper"]["enable"] is True
    assert models["seed"]["model"] == "google/gemini-3-flash-preview"
    assert models["seed"]["temperature"] == 0.1
    assert models["seed_refine"]["model"] == "google/gemini-3-flash-preview"
    assert models["seed_refine"]["temperature"] == 0.0
    assert models["testcase"]["model"] == "google/gemini-3-flash-preview"
    assert models["testcase"]["temperature"] == 0.0
    assert "repair" not in models


def test_settings_loader_supports_qa_ai_helper_model_env_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "ai:\n"
        "  qa_ai_helper:\n"
        "    models:\n"
        "      seed:\n"
        "        model: yaml/seed\n"
        "        temperature: 0.7\n"
        "      seed_refine:\n"
        "        model: yaml/seed-refine\n"
        "        temperature: 0.6\n"
        "      testcase:\n"
        "        model: yaml/testcase\n"
        "        temperature: 0.5\n",
    )
    monkeypatch.setenv("QA_AI_HELPER_MODEL_SEED", "env/seed")
    monkeypatch.setenv("QA_AI_HELPER_MODEL_SEED_TEMPERATURE", "0.11")
    monkeypatch.setenv("QA_AI_HELPER_MODEL_SEED_REFINE", "env/seed-refine")
    monkeypatch.setenv("QA_AI_HELPER_MODEL_SEED_REFINE_TEMPERATURE", "0.02")
    monkeypatch.setenv("QA_AI_HELPER_MODEL_TESTCASE", "env/testcase")
    monkeypatch.setenv("QA_AI_HELPER_MODEL_TESTCASE_TEMPERATURE", "0.01")

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.qa_ai_helper

    assert helper.models.seed.model == "env/seed"
    assert helper.models.seed.temperature == pytest.approx(0.11)
    assert helper.models.seed_refine is not None
    assert helper.models.seed_refine.model == "env/seed-refine"
    assert helper.models.seed_refine.temperature == pytest.approx(0.02)
    assert helper.models.testcase.model == "env/testcase"
    assert helper.models.testcase.temperature == pytest.approx(0.01)


def test_settings_loader_expands_qa_ai_helper_model_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "ai:\n"
        "  qa_ai_helper:\n"
        "    models:\n"
        "      seed:\n"
        "        model: '${QA_AI_HELPER_TEST_PLACEHOLDER_SEED}'\n"
        "        temperature: '${QA_AI_HELPER_TEST_PLACEHOLDER_SEED_TEMP}'\n"
        "      seed_refine: null\n"
        "      testcase:\n"
        "        model: '${QA_AI_HELPER_TEST_PLACEHOLDER_TESTCASE}'\n"
        "        temperature: '${QA_AI_HELPER_TEST_PLACEHOLDER_TESTCASE_TEMP}'\n",
    )
    monkeypatch.setenv("QA_AI_HELPER_TEST_PLACEHOLDER_SEED", "placeholder/seed")
    monkeypatch.setenv("QA_AI_HELPER_TEST_PLACEHOLDER_SEED_TEMP", "0.1")
    monkeypatch.setenv("QA_AI_HELPER_TEST_PLACEHOLDER_TESTCASE", "placeholder/testcase")
    monkeypatch.setenv("QA_AI_HELPER_TEST_PLACEHOLDER_TESTCASE_TEMP", "0.0")

    loaded = Settings.from_env_and_file(str(config_path))
    helper = loaded.ai.qa_ai_helper

    assert helper.models.seed.model == "placeholder/seed"
    assert helper.models.seed.temperature == pytest.approx(0.1)
    assert helper.models.seed_refine is not None
    assert helper.models.seed_refine.model == "placeholder/seed"
    assert helper.models.seed_refine.temperature == pytest.approx(0.1)
    assert helper.models.testcase.model == "placeholder/testcase"
    assert helper.models.testcase.temperature == pytest.approx(0.0)


def test_settings_loader_rejects_unresolved_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "ai:\n  qa_ai_helper:\n    models:\n      seed:\n        model: '${QA_AI_HELPER_TEST_UNSET_MODEL}'\n",
    )
    monkeypatch.delenv("QA_AI_HELPER_TEST_UNSET_MODEL", raising=False)

    with pytest.raises(ValueError, match="QA_AI_HELPER_TEST_UNSET_MODEL"):
        Settings.from_env_and_file(str(config_path))


def test_qa_ai_helper_stage_model_routing_supports_seed_family(tmp_path: Path) -> None:
    helper = Settings().ai.qa_ai_helper.model_copy(deep=True)
    helper.models.seed.model = "custom/seed"
    helper.models.seed_refine = None
    helper.models.testcase.model = "custom/testcase"
    helper.models.repair = None

    prompt_service = QAAIHelperPromptService(helper, prompt_dir=tmp_path)
    llm_service = QAAIHelperLLMService()
    llm_service._settings = Settings()
    llm_service._settings.ai.qa_ai_helper = helper

    assert prompt_service.get_stage_model("seed").model == "custom/seed"
    assert prompt_service.get_stage_model("seed_refine").model == "custom/seed"
    assert prompt_service.get_stage_model("testcase").model == "custom/testcase"
    assert prompt_service.get_stage_model("repair").model == "custom/testcase"
    assert llm_service.resolve_stage_model_id("seed") == "custom/seed"
    assert llm_service.resolve_stage_model_id("seed_refine") == "custom/seed"
    assert llm_service.resolve_stage_model_id("testcase") == "custom/testcase"
    assert llm_service.resolve_stage_model_id("repair") == "custom/testcase"


def test_team_extension_contract_rejects_non_normalized_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QAAIHelperTeamExtensionHint(
            scenario_key="ac.scenario_001",
            traits=["field_display"],
            constraints=["Must show title"],
            seed_hints=[{"category": "happy", "title_hint": "Verify title"}],
            raw_payload={"unexpected": True},
        )


def test_managed_main_database_upgrade_creates_v3_qa_ai_helper_tables(tmp_path: Path) -> None:
    database_bundle = create_managed_test_database(tmp_path / "qa_ai_helper_v3.db")
    expected_tables = {
        "qa_ai_helper_ticket_snapshots",
        "qa_ai_helper_requirement_plans",
        "qa_ai_helper_plan_sections",
        "qa_ai_helper_verification_items",
        "qa_ai_helper_check_conditions",
        "qa_ai_helper_seed_sets",
        "qa_ai_helper_seed_items",
        "qa_ai_helper_testcase_draft_sets",
        "qa_ai_helper_testcase_drafts",
        "qa_ai_helper_commit_links",
    }

    try:
        inspector = inspect(database_bundle["sync_engine"])
        assert expected_tables.issubset(set(inspector.get_table_names()))
    finally:
        dispose_managed_test_database(database_bundle)
