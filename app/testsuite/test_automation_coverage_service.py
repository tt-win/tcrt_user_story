import json
from datetime import datetime, timedelta

import pytest

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptFormat,
    AutomationScriptLinkType,
    Team,
    TeamAutomationProvider,
    TestCaseLocal as CaseModel,
    TestCaseSection as CaseSectionModel,
    TestCaseSet as CaseSetModel,
)
from app.services.automation.coverage_service import AutomationCoverageService
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


@pytest.fixture
def automation_coverage_db(tmp_path):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = database_bundle["sync_session_factory"]
    AsyncSessionLocal = database_bundle["async_session_factory"]
    now = datetime.utcnow()

    with SyncSessionLocal() as session:
        team = Team(name="QA Team", description="", wiki_token="wiki-token", test_case_table_id="tbl-test")
        session.add(team)
        session.commit()

        provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "example", "repo": "automation"}),
            credentials_encrypted=None,
            is_active=True,
        )
        case_set = CaseSetModel(team_id=team.id, name="Default", description="", is_default=True)
        session.add_all([provider, case_set])
        session.commit()

        section = CaseSectionModel(test_case_set_id=case_set.id, name="Smoke", level=1, sort_order=0)
        session.add(section)
        session.commit()

        cases = [
            CaseModel(
                team_id=team.id,
                test_case_set_id=case_set.id,
                test_case_section_id=section.id,
                test_case_number=f"TC-00{index}",
                title=title,
            )
            for index, title in enumerate(["Login", "Logout", "Profile", "Search"], start=1)
        ]
        scripts = [
            AutomationScript(
                team_id=team.id,
                provider_id=provider.id,
                name="test_login.py",
                script_format=AutomationScriptFormat.PYTEST,
                ref_path="tests/test_login.py",
                ref_branch="main",
                tags_json="[]",
            ),
            AutomationScript(
                team_id=team.id,
                provider_id=provider.id,
                name="test_logout.py",
                script_format=AutomationScriptFormat.PYTEST,
                ref_path="tests/test_logout.py",
                ref_branch="main",
                tags_json="[]",
            ),
            AutomationScript(
                team_id=team.id,
                provider_id=provider.id,
                name="test_profile.py",
                script_format=AutomationScriptFormat.PYTEST,
                ref_path="tests/test_profile.py",
                ref_branch="main",
                tags_json="[]",
            ),
        ]
        session.add_all([*cases, *scripts])
        session.commit()

        links = [
            AutomationScriptCaseLink(
                team_id=team.id,
                automation_script_id=scripts[0].id,
                test_case_id=cases[0].id,
                link_type=AutomationScriptLinkType.PRIMARY,
                created_at=now - timedelta(days=9),
            ),
            AutomationScriptCaseLink(
                team_id=team.id,
                automation_script_id=scripts[1].id,
                test_case_id=cases[1].id,
                link_type=AutomationScriptLinkType.COVERS,
                created_at=now - timedelta(days=2),
            ),
            AutomationScriptCaseLink(
                team_id=team.id,
                automation_script_id=scripts[2].id,
                test_case_id=cases[2].id,
                link_type=AutomationScriptLinkType.REFERENCES,
                created_at=now - timedelta(days=1),
            ),
        ]
        session.add_all(links)
        session.commit()
        ids = {"team_id": team.id}

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}
    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_compute_coverage_counts_uncovered_cases(automation_coverage_db):
    ids = automation_coverage_db["ids"]
    async with automation_coverage_db["async_sessionmaker"]() as session:
        service = AutomationCoverageService(session)
        coverage = await service.compute_coverage(team_id=ids["team_id"])

    assert coverage["total_test_cases"] == 4
    assert coverage["with_primary_link"] == 1
    assert coverage["with_covers_link"] == 1
    assert coverage["with_any_link"] == 2
    assert coverage["uncovered_count"] == 2
    assert [item["test_case_number"] for item in coverage["uncovered_sample"]] == ["TC-003", "TC-004"]
    assert coverage["by_format"] == {"PYTEST": 3}

    assert coverage["trend"][-1]["with_any_link"] == 2
    assert coverage["trend"][-1]["coverage_rate"] == 50.0

    # Group rollup: dotless numbers each form their own group; REFERENCES-only
    # links (TC-003) do NOT count as coverage.
    assert {g["group"]: (g["total"], g["covered"], g["primary"]) for g in coverage["by_group"]} == {
        "TC-001": (1, 1, 1),
        "TC-002": (1, 1, 0),
        "TC-003": (1, 0, 0),
        "TC-004": (1, 0, 0),
    }

    # Covered cases carry their linked scripts (link list shows all types,
    # but only PRIMARY/COVERS-linked cases appear here).
    covered = {item["test_case_number"]: item for item in coverage["covered_cases"]}
    assert set(covered) == {"TC-001", "TC-002"}
    assert [(l["script_name"], l["link_type"]) for l in covered["TC-001"]["links"]] == [
        ("test_login.py", "PRIMARY"),
    ]
    assert [(l["script_name"], l["link_type"]) for l in covered["TC-002"]["links"]] == [
        ("test_logout.py", "COVERS"),
    ]
