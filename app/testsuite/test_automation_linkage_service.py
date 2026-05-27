import json

import pytest
from sqlalchemy import select

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
from app.services.automation.linkage_service import (
    AutomationLinkageService,
    PrimaryAutomationLinkConflictError,
)
from app.services.automation.script_service import AutomationScriptService
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


@pytest.fixture
def automation_linkage_db(tmp_path):
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

        provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "example", "repo": "automation", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        case_set = CaseSetModel(team_id=team.id, name="Default", description="", is_default=True)
        session.add_all([provider, case_set])
        session.commit()

        section = CaseSectionModel(test_case_set_id=case_set.id, name="Smoke", level=1, sort_order=0)
        session.add(section)
        session.commit()

        case = CaseModel(
            team_id=team.id,
            test_case_set_id=case_set.id,
            test_case_section_id=section.id,
            test_case_number="TC-001",
            title="Login",
        )
        script_a = AutomationScript(
            team_id=team.id,
            provider_id=provider.id,
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            tags_json="[]",
        )
        script_b = AutomationScript(
            team_id=team.id,
            provider_id=provider.id,
            name="test_logout.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_logout.py",
            ref_branch="main",
            tags_json="[]",
        )
        session.add_all([case, script_a, script_b])
        session.commit()

        ids = {
            "team_id": team.id,
            "case_id": case.id,
            "script_a_id": script_a.id,
            "script_b_id": script_b.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}

    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_create_link_and_list_linked_automation(automation_linkage_db):
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        service = AutomationLinkageService(session)
        link = await service.create_link(
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
            note="main automation",
            actor="1",
        )
        summaries = await service.list_linked_automation(team_id=ids["team_id"], test_case_id=ids["case_id"])

    assert link.link_type == AutomationScriptLinkType.PRIMARY
    assert summaries[0]["script_id"] == ids["script_a_id"]
    assert summaries[0]["name"] == "test_login.py"
    assert summaries[0]["link_type"] == AutomationScriptLinkType.PRIMARY


@pytest.mark.asyncio
async def test_primary_link_is_unique_per_test_case(automation_linkage_db):
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        service = AutomationLinkageService(session)
        await service.create_link(
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
        )

        with pytest.raises(PrimaryAutomationLinkConflictError):
            await service.create_link(
                team_id=ids["team_id"],
                script_id=ids["script_b_id"],
                test_case_id=ids["case_id"],
                link_type=AutomationScriptLinkType.PRIMARY,
            )


@pytest.mark.asyncio
async def test_update_link_to_primary_checks_existing_primary(automation_linkage_db):
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        service = AutomationLinkageService(session)
        await service.create_link(
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
        )
        covers = await service.create_link(
            team_id=ids["team_id"],
            script_id=ids["script_b_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
        )

        with pytest.raises(PrimaryAutomationLinkConflictError):
            await service.update_link(
                team_id=ids["team_id"],
                script_id=ids["script_b_id"],
                link_id=covers.id,
                link_type=AutomationScriptLinkType.PRIMARY,
            )


@pytest.mark.asyncio
async def test_delete_link_refreshes_script_link_count(automation_linkage_db):
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        service = AutomationLinkageService(session)
        link = await service.create_link(
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
        )
        await service.delete_link(team_id=ids["team_id"], script_id=ids["script_a_id"], link_id=link.id)

        script = (
            await session.execute(select(AutomationScript).where(AutomationScript.id == ids["script_a_id"]))
        ).scalar_one()
        links = list((await session.execute(select(AutomationScriptCaseLink))).scalars().all())

    assert script.linked_test_case_count == 0
    assert links == []


@pytest.mark.asyncio
async def test_delete_script_cache_cascades_links(automation_linkage_db):
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        linkage_service = AutomationLinkageService(session)
        await linkage_service.create_link(
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
        )

        script_service = AutomationScriptService(session)
        await script_service.delete_script_cache(team_id=ids["team_id"], script_id=ids["script_a_id"])
        await session.flush()

        links = list((await session.execute(select(AutomationScriptCaseLink))).scalars().all())

    assert links == []
