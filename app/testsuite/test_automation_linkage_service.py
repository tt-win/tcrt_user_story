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
)
from app.services.automation.marker_sync import (
    MARKER_SYNC_CREATED_BY,
    build_marker_note,
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


def _seed_link(*, session, team_id, script_id, test_case_id, link_type, created_by, note=None):
    """Insert a link row directly — the public write API was removed; tests seed via ORM."""
    link = AutomationScriptCaseLink(
        team_id=team_id,
        automation_script_id=script_id,
        test_case_id=test_case_id,
        link_type=link_type,
        note=note,
        created_by=created_by,
    )
    session.add(link)
    session.flush()
    return link


@pytest.mark.asyncio
async def test_list_links_for_script_detailed_includes_case_number_and_title(automation_linkage_db):
    """The read API surfaces the test case number + title for each link."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            created_by="42",
        )
        await session.flush()
        service = AutomationLinkageService(session)
        rows = await service.list_links_for_script_detailed(
            team_id=ids["team_id"], script_id=ids["script_a_id"]
        )

    assert len(rows) == 1
    assert rows[0]["test_case_id"] == ids["case_id"]
    assert rows[0]["test_case_number"] == "TC-001"
    assert rows[0]["title"] == "Login"
    assert rows[0]["created_by"] == "42"


@pytest.mark.asyncio
async def test_list_linked_automation_summarises_links_for_a_case(automation_linkage_db):
    """The read API still returns script summaries for a test case."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
            created_by="42",
        )
        await session.flush()
        service = AutomationLinkageService(session)
        summaries = await service.list_linked_automation(
            team_id=ids["team_id"], test_case_id=ids["case_id"]
        )

    assert summaries[0]["script_id"] == ids["script_a_id"]
    assert summaries[0]["name"] == "test_login.py"
    assert summaries[0]["link_type"] == AutomationScriptLinkType.PRIMARY
    assert summaries[0]["created_by"] == "42"


@pytest.mark.asyncio
async def test_delete_script_cache_cascades_links(automation_linkage_db):
    """Deleting a script's cache cascades its links (FK ON DELETE CASCADE)."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            created_by=MARKER_SYNC_CREATED_BY,
        )
        await session.flush()

        script_service = AutomationScriptService(session)
        await script_service.delete_script_cache(
            team_id=ids["team_id"], script_id=ids["script_a_id"]
        )
        await session.flush()

        links = list((await session.execute(select(AutomationScriptCaseLink))).scalars().all())

    assert links == []


# ------------------------------------------------------------------ marker-sync interface


@pytest.mark.asyncio
async def test_upsert_marker_link_creates_new_link(automation_linkage_db):
    """upsert_marker_link inserts a new marker-sync link when none exists."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        script = (
            await session.execute(
                select(AutomationScript).where(AutomationScript.id == ids["script_a_id"])
            )
        ).scalar_one()
        service = AutomationLinkageService(session)
        link, action = await service.upsert_marker_link(
            team_id=ids["team_id"],
            script=script,
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
            marker_meta={"test_name": "test_login", "line": 12, "marker_raw": "pytest.mark.tcrt"},
        )
        await session.flush()

    assert action == "created"
    assert link.created_by == MARKER_SYNC_CREATED_BY
    assert link.link_type == AutomationScriptLinkType.PRIMARY
    parsed = json.loads(link.note)
    assert parsed["test_name"] == "test_login"
    assert parsed["line"] == 12


@pytest.mark.asyncio
async def test_upsert_marker_link_is_noop_when_unchanged(automation_linkage_db):
    """A second upsert with the same args returns 'unchanged' and does not bump audit."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        script = (
            await session.execute(
                select(AutomationScript).where(AutomationScript.id == ids["script_a_id"])
            )
        ).scalar_one()
        service = AutomationLinkageService(session)
        marker_meta = {"test_name": "test_login", "line": 12, "marker_raw": "pytest.mark.tcrt"}
        _, action1 = await service.upsert_marker_link(
            team_id=ids["team_id"],
            script=script,
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            marker_meta=marker_meta,
        )
        await session.flush()
        _, action2 = await service.upsert_marker_link(
            team_id=ids["team_id"],
            script=script,
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            marker_meta=marker_meta,
        )

    assert action1 == "created"
    assert action2 == "unchanged"


@pytest.mark.asyncio
async def test_upsert_marker_link_skips_non_marker_existing_link(automation_linkage_db):
    """A pre-existing manual/AI link blocks the upsert and returns skipped_conflict."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            created_by="42",  # manual
        )
        await session.flush()
        script = (
            await session.execute(
                select(AutomationScript).where(AutomationScript.id == ids["script_a_id"])
            )
        ).scalar_one()
        service = AutomationLinkageService(session)
        _, action = await service.upsert_marker_link(
            team_id=ids["team_id"],
            script=script,
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
            marker_meta={"test_name": "test_login", "line": 12, "marker_raw": "pytest.mark.tcrt"},
        )

    assert action == "skipped_conflict"


@pytest.mark.asyncio
async def test_delete_marker_link_only_removes_marker_sync(automation_linkage_db):
    """delete_marker_link refuses to touch a manually-created link."""
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            created_by="42",  # manual
        )
        await session.flush()
        service = AutomationLinkageService(session)
        deleted = await service.delete_marker_link(
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
        )
        await session.flush()
        still_there = (
            await session.execute(
                select(AutomationScriptCaseLink).where(
                    AutomationScriptCaseLink.automation_script_id == ids["script_a_id"]
                )
            )
        ).scalar_one()

    assert deleted is False
    assert still_there.created_by == "42"


@pytest.mark.asyncio
async def test_refresh_script_link_count_persists_count(automation_linkage_db):
    ids = automation_linkage_db["ids"]
    async with automation_linkage_db["async_sessionmaker"]() as session:
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"],
            link_type=AutomationScriptLinkType.COVERS,
            created_by=MARKER_SYNC_CREATED_BY,
            note=build_marker_note(test_name="t", line=1, marker_raw="x"),
        )
        _seed_link(
            session=session,
            team_id=ids["team_id"],
            script_id=ids["script_a_id"],
            test_case_id=ids["case_id"] + 999,  # fake id — still counts as a row
            link_type=AutomationScriptLinkType.COVERS,
            created_by=MARKER_SYNC_CREATED_BY,
            note=build_marker_note(test_name="t", line=2, marker_raw="y"),
        )
        await session.flush()
        service = AutomationLinkageService(session)
        count = await service.refresh_script_link_count(script_id=ids["script_a_id"])
        await session.flush()
        script = (
            await session.execute(
                select(AutomationScript).where(AutomationScript.id == ids["script_a_id"])
            )
        ).scalar_one()

    assert count == 2
    assert script.linked_test_case_count == 2
