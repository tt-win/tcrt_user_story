"""Tests for Test Run Set 觸發 automation suite 流程。

Verifies:
- Test Run Set accepts `automation_suite_ids` in create / update payload
- `TestRunSetAutomationService.trigger_automation_suites` 寫入 `automation_runs.test_run_set_id`
- 觸發鏈的錯誤情境（空 suites、cross-team suite、suite 不存在）

See `openspec/changes/move-automation-execution-to-test-run-set/`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationScript,
    AutomationScriptFormat,
    AutomationScriptGroup,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
    TestRunSet as TestRunSetDB,
    TestRunSetStatus as TestRunSetStatusEnum,
)
from app.services.test_run_set_automation_service import (
    TestRunSetAutomationService,
    TestRunSetEmptySuitesError,
    TestRunSetNotFoundError,
    TestRunSetSuiteCrossTeamError,
    TestRunSetSuiteNotFoundError,
    TestRunSetSuiteNotInSetError,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def test_run_set_automation_db(tmp_path):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = database_bundle["sync_session_factory"]
    AsyncSessionLocal = database_bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        # Team + storage + CI providers
        team = Team(name="QA Team", description="", wiki_token="t", test_case_table_id="tbl")
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
        ci = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.CI,
            provider_type="ci:jenkins",
            name="Jenkins",
            config_json=json.dumps({"default_runner_label": "linux", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add_all([storage, ci])
        session.commit()

        # Two suites (script groups) and a few scripts
        scripts = [
            AutomationScript(
                team_id=team.id,
                provider_id=storage.id,
                name=f"test_{i}.py",
                script_format=AutomationScriptFormat.PYTEST,
                ref_path=f"tests/test_{i}.py",
                ref_branch="main",
                tags_json="[]",
            )
            for i in range(3)
        ]
        session.add_all(scripts)
        session.commit()

        suites = [
            AutomationScriptGroup(
                team_id=team.id,
                name=f"Suite {i}",
                description="",
                ci_job_name=f"suite-job-{i}",
                ci_job_type="JENKINS",
                script_paths_json=json.dumps([f"tests/test_{i}.py"]),
            )
            for i in range(2)
        ]
        session.add_all(suites)
        session.commit()

        # A set with one suite
        set_one = TestRunSetDB(
            team_id=team.id,
            name="Set with 1 suite",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([suites[0].id]),
        )
        # A set with no suites (empty)
        set_empty = TestRunSetDB(
            team_id=team.id,
            name="Set empty",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([]),
        )
        # A set with multiple suites
        set_many = TestRunSetDB(
            team_id=team.id,
            name="Set with 2 suites",
            description="",
            status=TestRunSetStatusEnum.ACTIVE,
            automation_suite_ids_json=json.dumps([suites[0].id, suites[1].id]),
        )
        session.add_all([set_one, set_empty, set_many])
        session.commit()

        ids = {
            "team_id": team.id,
            "suite_ids": [suites[0].id, suites[1].id],
            "set_one_id": set_one.id,
            "set_empty_id": set_empty.id,
            "set_many_id": set_many.id,
            "ci_provider_id": ci.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}

    dispose_managed_test_database(database_bundle)


class _FakeCIProvider:
    """In-memory CI provider stand-in; never hits the network."""

    def __init__(self, suite_job_name: str) -> None:
        self.suite_job_name = suite_job_name
        self.trigger_calls: list[tuple[str, str, dict]] = []

    async def create_suite_job(self, *args, **kwargs) -> str:
        return self.suite_job_name

    async def update_suite_job(self, *args, **kwargs) -> str:
        return self.suite_job_name

    async def trigger_run(self, workflow_id, branch, inputs):
        self.trigger_calls.append((workflow_id, branch, dict(inputs)))
        from app.services.automation.providers.base import ExternalRunRef

        return ExternalRunRef(
            external_run_id=f"queue-{workflow_id}",
            external_run_url=f"https://ci.example/queue/{workflow_id}",
            raw={},
        )


@pytest.mark.asyncio
async def test_test_run_set_round_trips_automation_suite_ids(test_run_set_automation_db):
    """The `automation_suite_ids` JSON column round-trips through ORM and Pydantic."""
    from app.models.test_run_set import _deserialize_suite_ids

    ids = test_run_set_automation_db["ids"]

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        result = await session.execute(
            select(TestRunSetDB).where(TestRunSetDB.id == ids["set_one_id"])
        )
        set_db = result.scalar_one()

        # ORM column holds JSON
        assert set_db.automation_suite_ids_json is not None
        deserialized = _deserialize_suite_ids(set_db.automation_suite_ids_json)
        assert deserialized == [ids["suite_ids"][0]]

        # Empty set
        result = await session.execute(
            select(TestRunSetDB).where(TestRunSetDB.id == ids["set_empty_id"])
        )
        set_empty = result.scalar_one()
        assert _deserialize_suite_ids(set_empty.automation_suite_ids_json) == []


@pytest.mark.asyncio
async def test_trigger_automation_suites_writes_test_run_set_id(test_run_set_automation_db, monkeypatch):
    """Successful trigger writes `automation_runs.test_run_set_id` and `script_group_id`."""
    from app.services.automation import script_group_service as sgs

    ids = test_run_set_automation_db["ids"]
    fake_ci = _FakeCIProvider(suite_job_name=f"suite-job-{ids['suite_ids'][0]}")
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake_ci)

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        result = await service.trigger_automation_suites(
            team_id=ids["team_id"],
            set_id=ids["set_one_id"],
            actor="1",
        )
        await session.commit()

    assert result["triggered_suite_ids"] == [ids["suite_ids"][0]]
    assert len(result["run_ids"]) == 1
    assert isinstance(result["run_ids"][0], int)
    run_id = result["run_ids"][0]

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        run_db = (
            await session.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
        assert run_db.test_run_set_id == ids["set_one_id"]
        assert run_db.script_group_id == ids["suite_ids"][0]
        assert run_db.automation_script_id is None  # legacy column, never set on new runs
        assert run_db.status == AutomationRunStatus.QUEUED
        assert run_db.triggered_by.value == "USER"


@pytest.mark.asyncio
async def test_trigger_automation_suites_multiple_suites(test_run_set_automation_db, monkeypatch):
    """A set with multiple suites creates one run per suite."""
    from app.services.automation import script_group_service as sgs

    ids = test_run_set_automation_db["ids"]
    fake_ci = _FakeCIProvider(suite_job_name="placeholder")
    # We need to vary the returned job name per call (the suite stores ci_job_name
    # so the trigger method does not call create_suite_job again; but our fake
    # returns "placeholder" regardless — which is fine because the test only
    # asserts that both suites are triggered and produce runs).
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake_ci)

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        result = await service.trigger_automation_suites(
            team_id=ids["team_id"],
            set_id=ids["set_many_id"],
            actor="1",
        )
        await session.commit()

    assert result["triggered_suite_ids"] == ids["suite_ids"]
    assert len(result["run_ids"]) == 2

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        runs = (
            await session.execute(
                select(AutomationRun).where(AutomationRun.test_run_set_id == ids["set_many_id"])
            )
        ).scalars().all()
        assert len(runs) == 2
        assert {r.script_group_id for r in runs} == set(ids["suite_ids"])


@pytest.mark.asyncio
async def test_trigger_single_automation_suite_from_set(test_run_set_automation_db, monkeypatch):
    """A caller can trigger one associated suite without triggering the rest."""
    from app.services.automation import script_group_service as sgs

    ids = test_run_set_automation_db["ids"]
    fake_ci = _FakeCIProvider(suite_job_name="placeholder")
    monkeypatch.setattr(sgs, "instantiate_provider", lambda *a, **kw: fake_ci)

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        result = await service.trigger_automation_suites(
            team_id=ids["team_id"],
            set_id=ids["set_many_id"],
            suite_id=ids["suite_ids"][1],
            actor="1",
        )
        await session.commit()

    assert result["triggered_suite_ids"] == [ids["suite_ids"][1]]
    assert len(result["run_ids"]) == 1

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        runs = (
            await session.execute(
                select(AutomationRun).where(AutomationRun.test_run_set_id == ids["set_many_id"])
            )
        ).scalars().all()
        assert len(runs) == 1
        assert runs[0].script_group_id == ids["suite_ids"][1]


@pytest.mark.asyncio
async def test_trigger_single_automation_suite_not_in_set_raises(test_run_set_automation_db):
    ids = test_run_set_automation_db["ids"]

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        with pytest.raises(TestRunSetSuiteNotInSetError):
            await service.trigger_automation_suites(
                team_id=ids["team_id"],
                set_id=ids["set_one_id"],
                suite_id=ids["suite_ids"][1],
                actor="1",
            )


@pytest.mark.asyncio
async def test_trigger_automation_suites_empty_set_raises(test_run_set_automation_db):
    ids = test_run_set_automation_db["ids"]

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        with pytest.raises(TestRunSetEmptySuitesError):
            await service.trigger_automation_suites(
                team_id=ids["team_id"],
                set_id=ids["set_empty_id"],
                actor="1",
            )


@pytest.mark.asyncio
async def test_trigger_automation_suites_unknown_set_raises(test_run_set_automation_db):
    ids = test_run_set_automation_db["ids"]

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        with pytest.raises(TestRunSetNotFoundError):
            await service.trigger_automation_suites(
                team_id=ids["team_id"],
                set_id=99999,
                actor="1",
            )


@pytest.mark.asyncio
async def test_trigger_automation_suites_cross_team_suite_raises(test_run_set_automation_db):
    """A suite id belonging to another team must be rejected."""
    from app.models.database_models import Team as TeamModel

    ids = test_run_set_automation_db["ids"]

    # Create a second team + suite; bind the first team's set to the second team's suite.
    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        other_team = TeamModel(
            name="Other Team",
            description="",
            wiki_token="t2",
            test_case_table_id="tbl2",
        )
        session.add(other_team)
        await session.flush()
        other_suite = AutomationScriptGroup(
            team_id=other_team.id,
            name="Other Suite",
            description="",
            ci_job_name="other-suite",
            ci_job_type="JENKINS",
            script_paths_json=json.dumps(["tests/other.py"]),
        )
        session.add(other_suite)
        await session.flush()

        set_db = (
            await session.execute(select(TestRunSetDB).where(TestRunSetDB.id == ids["set_one_id"]))
        ).scalar_one()
        set_db.automation_suite_ids_json = json.dumps([other_suite.id])
        await session.commit()

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        with pytest.raises(TestRunSetSuiteCrossTeamError):
            await service.trigger_automation_suites(
                team_id=ids["team_id"],
                set_id=ids["set_one_id"],
                actor="1",
            )


@pytest.mark.asyncio
async def test_trigger_automation_suites_missing_suite_raises(test_run_set_automation_db):
    """A suite id that no longer exists must be rejected."""
    ids = test_run_set_automation_db["ids"]

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        set_db = (
            await session.execute(select(TestRunSetDB).where(TestRunSetDB.id == ids["set_one_id"]))
        ).scalar_one()
        # Point to a suite id that doesn't exist
        set_db.automation_suite_ids_json = json.dumps([999999])
        await session.commit()

    async with test_run_set_automation_db["async_sessionmaker"]() as session:
        service = TestRunSetAutomationService(session)
        with pytest.raises(TestRunSetSuiteNotFoundError):
            await service.trigger_automation_suites(
                team_id=ids["team_id"],
                set_id=ids["set_one_id"],
                actor="1",
            )
