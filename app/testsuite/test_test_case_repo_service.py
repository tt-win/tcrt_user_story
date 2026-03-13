from pathlib import Path
import sys
import json
import asyncio

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.database_models import (
    Team,
    TestCaseSet as CaseSetModel,
    TestCaseSection as CaseSectionModel,
    TestCaseLocal as CaseModel,
)
from app.services.test_case_repo_service import TestCaseRepoService as RepoService
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
)


@pytest.fixture
def repo_service_db(tmp_path):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = database_bundle["sync_session_factory"]
    AsyncSessionLocal = database_bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(
            name="QA Team",
            description="",
            wiki_token="wiki-token",
            test_case_table_id="tbl-test",
        )
        session.add(team)
        session.commit()

        test_case_set = CaseSetModel(
            team_id=team.id,
            name=f"Default-{team.id}",
            description="",
            is_default=True,
        )
        session.add(test_case_set)
        session.commit()

        section = CaseSectionModel(
            test_case_set_id=test_case_set.id,
            name="Smoke",
            level=1,
            sort_order=0,
        )
        session.add(section)
        session.commit()

        session.add_all(
            [
                CaseModel(
                    team_id=team.id,
                    test_case_set_id=test_case_set.id,
                    test_case_section_id=section.id,
                    test_case_number="TC-001",
                    title="Login",
                    tcg_json=json.dumps(["TCG-1001", "TP-2001"]),
                ),
                CaseModel(
                    team_id=team.id,
                    test_case_set_id=test_case_set.id,
                    test_case_section_id=section.id,
                    test_case_number="TC-002",
                    title="Logout",
                    tcg_json=json.dumps(["TCG-9000"]),
                ),
                CaseModel(
                    team_id=team.id,
                    test_case_set_id=test_case_set.id,
                    test_case_section_id=section.id,
                    test_case_number="TC-003",
                    title="Profile",
                    tcg_json=None,
                ),
            ]
        )
        session.commit()

        team_id = team.id

    yield {
        "team_id": team_id,
        "async_sessionmaker": AsyncSessionLocal,
    }

    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_list_filters_cases_by_tcg_json_content(repo_service_db):
    async with repo_service_db["async_sessionmaker"]() as session:
        service = RepoService(session)

        rows = await service.list(
            team_id=repo_service_db["team_id"],
            tcg_filter="TCG-1001",
            sort_by="test_case_number",
            sort_order="asc",
        )

        assert [row.test_case_number for row in rows] == ["TC-001"]

        rows = await service.list(
            team_id=repo_service_db["team_id"],
            tcg_filter="TP-2001,TCG-9000",
            sort_by="test_case_number",
            sort_order="asc",
        )

        assert [row.test_case_number for row in rows] == ["TC-001", "TC-002"]


@pytest.mark.asyncio
async def test_count_filters_cases_by_tcg_json_content(repo_service_db):
    async with repo_service_db["async_sessionmaker"]() as session:
        service = RepoService(session)

        assert await service.count(
            team_id=repo_service_db["team_id"],
            tcg_filter="TCG-1001",
        ) == 1
        assert await service.count(
            team_id=repo_service_db["team_id"],
            tcg_filter="TP-2001,TCG-9000",
        ) == 2
