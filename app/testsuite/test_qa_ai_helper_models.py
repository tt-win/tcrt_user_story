from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import mysql, sqlite
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database_init
from app.audit.database import AuditBase
from app.config import create_default_config
from app.models.database_models import Base as MainBase
from app.models.qa_ai_helper import (
    QAAIHelperCounterSettings,
    QAAIHelperTeamExtensionHint,
    QAAIHelperSessionCreateRequest,
)
from app.models.user_story_map_db import Base as UserStoryMapBase


def test_qa_ai_helper_counter_settings_validate_ten_step_values() -> None:
    settings = QAAIHelperCounterSettings(middle="020", tail="090")

    assert settings.middle == "020"
    assert settings.tail == "090"


def test_qa_ai_helper_counter_settings_reject_non_ten_step_values() -> None:
    with pytest.raises(ValidationError):
        QAAIHelperCounterSettings(middle="015", tail="010")


def test_qa_ai_helper_session_create_request_normalizes_ticket_and_defaults_comments() -> None:
    request = QAAIHelperSessionCreateRequest(
        target_test_case_set_id=123,
        ticket_key="tcg130078",
    )

    assert request.ticket_key == "TCG-130078"
    assert request.include_comments is False
    assert request.counter_settings.middle == "010"
    assert request.counter_settings.tail == "010"


def test_new_qa_ai_helper_tables_are_in_main_metadata_and_required_tables() -> None:
    expected_tables = {
        "qa_ai_helper_sessions",
        "qa_ai_helper_canonical_revisions",
        "qa_ai_helper_planned_revisions",
        "qa_ai_helper_requirement_deltas",
        "qa_ai_helper_draft_sets",
        "qa_ai_helper_drafts",
        "qa_ai_helper_validation_runs",
        "qa_ai_helper_telemetry_events",
    }

    assert expected_tables.issubset(set(MainBase.metadata.tables))
    assert expected_tables.issubset(set(database_init.MAIN_REQUIRED_TABLES))


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

    assert payload["ai"]["jira_testcase_helper"]["enable"] is False
    assert payload["ai"]["qa_ai_helper"]["enable"] is True
    assert payload["ai"]["qa_ai_helper"]["models"]["repair"] is None


def test_team_extension_contract_rejects_non_normalized_extra_fields() -> None:
    with pytest.raises(ValidationError):
        QAAIHelperTeamExtensionHint(
            scenario_key="ac.scenario_001",
            traits=["field_display"],
            constraints=["Must show title"],
            seed_hints=[{"category": "happy", "title_hint": "Verify title"}],
            raw_payload={"unexpected": True},
        )
