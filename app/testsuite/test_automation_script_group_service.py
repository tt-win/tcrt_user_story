import json

import pytest
from sqlalchemy import select

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationScript,
    AutomationScriptFormat,
    AutomationScriptGroup,
    AutomationScriptGroupJobType,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
)
from app.services.automation.providers.base import ExternalRunRef
from app.services.automation.script_group_service import (
    AutomationScriptGroupScriptNotFoundError,
    AutomationScriptGroupService,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


class FakeCIProvider:
    def __init__(self) -> None:
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []
        self.trigger_calls = []

    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
    ) -> str:
        self.create_calls.append(
            (suite_id, suite_name, test_paths, default_runner_label, git_context, team_id, team_name)
        )
        return f"tcrt-suite-{suite_id}-{suite_name.lower().replace(' ', '-')}"

    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
    ) -> str:
        self.update_calls.append(
            (suite_id, suite_name, test_paths, default_runner_label, git_context, team_id, team_name)
        )
        return f"tcrt-suite-{suite_id}-{suite_name.lower().replace(' ', '-')}"

    async def delete_suite_job(self, suite_id: str, job_name: str) -> None:
        self.delete_calls.append((suite_id, job_name))

    async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef:
        self.trigger_calls.append((workflow_id, branch, inputs))
        return ExternalRunRef(
            external_run_id="queue:123",
            external_run_url="https://jenkins.example/queue/item/123/",
            raw={"job_name": workflow_id},
        )


@pytest.fixture
def automation_script_group_db(tmp_path):
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

        storage_provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "example", "repo": "automation", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        # CI providers are org-scoped — live in system_automation_providers.
        ci_provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.CI,
            provider_type="ci:jenkins",
            name="Jenkins",
            config_json=json.dumps({"default_runner_label": "linux", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add_all([storage_provider, ci_provider])
        session.commit()

        script_a = AutomationScript(
            team_id=team.id,
            provider_id=storage_provider.id,
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            tags_json="[]",
        )
        script_b = AutomationScript(
            team_id=team.id,
            provider_id=storage_provider.id,
            name="test_logout.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_logout.py",
            ref_branch="main",
            tags_json="[]",
        )
        session.add_all([script_a, script_b])
        session.commit()

        ids = {
            "team_id": team.id,
            "script_a_id": script_a.id,
            "script_b_id": script_b.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}

    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_create_group_calls_ci_provider_and_stores_paths(automation_script_group_db):
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Login Regression",
            description="critical auth flows",
            script_ids=[ids["script_a_id"], ids["script_b_id"]],
            actor="1",
            ci_provider=fake_ci,
        )

    assert group.ci_job_name == f"tcrt-suite-{group.id}-login-regression"
    assert group.ci_job_type == AutomationScriptGroupJobType.JENKINS
    assert json.loads(group.script_paths_json) == ["tests/test_login.py", "tests/test_logout.py"]
    assert fake_ci.create_calls == [
        (
            str(group.id),
            "Login Regression",
            ["tests/test_login.py", "tests/test_logout.py"],
            "linux",
            {"url": "https://github.com/example/automation.git", "branch": "main"},
            ids["team_id"],
            "QA Team",
        )
    ]


@pytest.mark.asyncio
async def test_create_group_validates_script_ids(automation_script_group_db):
    ids = automation_script_group_db["ids"]

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        with pytest.raises(AutomationScriptGroupScriptNotFoundError):
            await service.create_group(
                team_id=ids["team_id"],
                name="Broken Suite",
                description=None,
                script_ids=[ids["script_a_id"], 999999],
                ci_provider=FakeCIProvider(),
            )


@pytest.mark.asyncio
async def test_update_group_syncs_ci_provider(automation_script_group_db):
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Login Regression",
            description="auth flows",
            script_ids=[ids["script_a_id"]],
            ci_provider=fake_ci,
        )
        updated = await service.update_group(
            team_id=ids["team_id"],
            group_id=group.id,
            name="Auth Regression",
            description=None,
            description_provided=True,
            script_ids=[ids["script_b_id"], ids["script_a_id"]],
            ci_provider=fake_ci,
        )

    assert updated.name == "Auth Regression"
    assert updated.description is None
    assert json.loads(updated.script_paths_json) == ["tests/test_logout.py", "tests/test_login.py"]
    assert fake_ci.update_calls == [
        (
            str(group.id),
            "Auth Regression",
            ["tests/test_logout.py", "tests/test_login.py"],
            "linux",
            {"url": "https://github.com/example/automation.git", "branch": "main"},
            ids["team_id"],
            "QA Team",
        )
    ]


@pytest.mark.asyncio
async def test_delete_group_deletes_ci_job_and_row(automation_script_group_db):
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Login Regression",
            description=None,
            script_ids=[ids["script_a_id"]],
            ci_provider=fake_ci,
        )
        await service.delete_group(team_id=ids["team_id"], group_id=group.id, ci_provider=fake_ci)
        groups = list((await session.execute(select(AutomationScriptGroup))).scalars().all())

    assert groups == []
    assert fake_ci.delete_calls == [(str(group.id), group.ci_job_name)]


@pytest.mark.asyncio
async def test_trigger_group_run_creates_suite_level_run(automation_script_group_db):
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Login Regression",
            description=None,
            script_ids=[ids["script_a_id"], ids["script_b_id"]],
            ci_provider=fake_ci,
        )
        run = await service.trigger_group_run(
            team_id=ids["team_id"],
            group_id=group.id,
            actor="1",
            ci_provider=fake_ci,
        )
        persisted_run = (await session.execute(select(AutomationRun).where(AutomationRun.id == run.id))).scalar_one()

    assert persisted_run.script_group_id == group.id
    assert persisted_run.automation_script_id is None
    assert persisted_run.workflow_id == group.ci_job_name
    assert persisted_run.external_run_id == "queue:123"
    assert fake_ci.trigger_calls[0][0] == group.ci_job_name
    assert fake_ci.trigger_calls[0][1] == "main"
    assert fake_ci.trigger_calls[0][2]["runner_label"] == "linux"
    assert json.loads(fake_ci.trigger_calls[0][2]["test_paths"]) == [
        "tests/test_login.py",
        "tests/test_logout.py",
    ]
    assert fake_ci.trigger_calls[0][2]["tcrt_run_id"] == persisted_run.tcrt_correlation_id
