"""GET /test-run-sets/{set_id}/automation-covered-cases

Covered = PRIMARY/COVERS link from a script belonging to a suite attached to
the set. Suite-scoped (other scripts' links don't count) and REFERENCES links
don't count.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptFormat,
    AutomationScriptGroup,
    AutomationScriptLinkType,
    Team,
    TeamAutomationProvider,
    TestCaseLocal,
    TestCaseSet,
    TestRunSet as TestRunSetDB,
    TestRunSetStatus as TestRunSetStatusEnum,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def covered_cases_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "covered_cases.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=7, username="covered-cases-tester", full_name="Tester", role=UserRole.SUPER_ADMIN,
    )

    with bundle["sync_session_factory"]() as session:
        team = Team(name="Covered Team", description="", wiki_token="w", test_case_table_id="tbl")
        session.add(team)
        session.commit()

        storage = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "ex", "repo": "auto", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        case_set = TestCaseSet(team_id=team.id, name="Default", description="", is_default=True)
        session.add_all([storage, case_set])
        session.commit()

        in_suite_script = AutomationScript(
            team_id=team.id, provider_id=storage.id, name="test_in_suite.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_in_suite.py", ref_branch="main", tags_json="[]",
        )
        outside_script = AutomationScript(
            team_id=team.id, provider_id=storage.id, name="test_outside.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_outside.py", ref_branch="main", tags_json="[]",
        )
        session.add_all([in_suite_script, outside_script])
        session.commit()

        suite = AutomationScriptGroup(
            team_id=team.id, name="Suite", description="",
            ci_job_name="suite-job", ci_job_type="JENKINS",
            script_paths_json=json.dumps(["tests/test_in_suite.py"]),
        )
        session.add(suite)
        session.commit()

        cases = [
            TestCaseLocal(team_id=team.id, test_case_set_id=case_set.id,
                          test_case_number=f"TC-00{i}", title=f"Case {i}")
            for i in range(1, 5)
        ]
        session.add_all(cases)
        session.commit()

        links = [
            # covered: PRIMARY from the in-suite script
            AutomationScriptCaseLink(team_id=team.id, automation_script_id=in_suite_script.id,
                                     test_case_id=cases[0].id, link_type=AutomationScriptLinkType.PRIMARY),
            # NOT covered by this set: link belongs to a script outside the suite
            AutomationScriptCaseLink(team_id=team.id, automation_script_id=outside_script.id,
                                     test_case_id=cases[1].id, link_type=AutomationScriptLinkType.COVERS),
            # NOT covered: REFERENCES doesn't count
            AutomationScriptCaseLink(team_id=team.id, automation_script_id=in_suite_script.id,
                                     test_case_id=cases[2].id, link_type=AutomationScriptLinkType.REFERENCES),
        ]
        session.add_all(links)
        session.commit()

        set_with_suite = TestRunSetDB(
            team_id=team.id, name="With suite", description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([suite.id]),
        )
        set_empty = TestRunSetDB(
            team_id=team.id, name="No suites", description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([]),
        )
        session.add_all([set_with_suite, set_empty])
        session.commit()

        ids = {
            "team_id": team.id,
            "set_with_suite_id": set_with_suite.id,
            "set_empty_id": set_empty.id,
            "covered_case_id": cases[0].id,
        }

    yield {"ids": ids}

    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)


def test_covered_cases_scoped_to_set_suites(covered_cases_db):
    ids = covered_cases_db["ids"]
    client = TestClient(app)

    response = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_with_suite_id']}/automation-covered-cases"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["test_case_numbers"] == ["TC-001"]
    assert body["test_case_ids"] == [ids["covered_case_id"]]


def test_covered_cases_empty_for_set_without_suites(covered_cases_db):
    ids = covered_cases_db["ids"]
    client = TestClient(app)

    response = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_empty_id']}/automation-covered-cases"
    )
    assert response.status_code == 200
    assert response.json() == {"test_case_ids": [], "test_case_numbers": []}


def test_set_detail_includes_automation_covered_case_count(covered_cases_db):
    ids = covered_cases_db["ids"]
    client = TestClient(app)

    response = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_with_suite_id']}"
    )
    assert response.status_code == 200
    assert response.json()["automation_covered_case_count"] == 1

    response = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/{ids['set_empty_id']}"
    )
    assert response.status_code == 200
    assert response.json()["automation_covered_case_count"] == 0


def test_covered_cases_unknown_set_404(covered_cases_db):
    ids = covered_cases_db["ids"]
    client = TestClient(app)

    response = client.get(
        f"/api/teams/{ids['team_id']}/test-run-sets/999999/automation-covered-cases"
    )
    assert response.status_code == 404
