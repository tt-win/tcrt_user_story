import json

import httpx
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
    AutomationScriptGroupServiceError,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


class FakeCIProvider:
    def __init__(self) -> None:
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []
        self.trigger_calls = []
        # Trigger-scoped variant tracking, kept separate from the legacy
        # call tuples so existing exact-match assertions stay intact.
        self.create_suffixes: list[str] = []
        self.update_suffixes: list[tuple[str, str | None]] = []
        # When set, the first update for a webhook job (truthy job_suffix)
        # raises 404 so the service's update→404→create self-heal runs.
        self.hook_update_raises_404 = False
        self._hook_update_seen = False
        # When set, every update_suite_job raises 404 (simulates a job that is
        # already gone on CI), so the caller's update→404→create self-heal runs.
        self.update_raises_404 = False
        self.delete_view_calls: list[tuple] = []

    @staticmethod
    def _job_name(suite_id: str, suite_name: str, job_suffix: str) -> str:
        return f"tcrt-suite-{suite_id}-{suite_name.lower().replace(' ', '-')}{job_suffix}"

    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
        tcrt_webhook_url: str | None = None,
        job_suffix: str = "",
    ) -> str:
        self.create_calls.append(
            (suite_id, suite_name, test_paths, default_runner_label, git_context, team_id, team_name)
        )
        self.create_suffixes.append(job_suffix)
        return self._job_name(suite_id, suite_name, job_suffix)

    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        git_context: dict | None = None,
        team_id: int | None = None,
        team_name: str | None = None,
        tcrt_webhook_url: str | None = None,
        existing_job_name: str | None = None,
        job_suffix: str = "",
    ) -> str:
        self.update_calls.append(
            (suite_id, suite_name, test_paths, default_runner_label, git_context, team_id, team_name)
        )
        self.update_suffixes.append((job_suffix, existing_job_name))
        if self.update_raises_404:
            request = httpx.Request("POST", "https://ci.example/job/config.xml")
            raise httpx.HTTPStatusError(
                "not found", request=request, response=httpx.Response(404, request=request)
            )
        if job_suffix and self.hook_update_raises_404 and not self._hook_update_seen:
            self._hook_update_seen = True
            request = httpx.Request("POST", "https://ci.example/job/config.xml")
            raise httpx.HTTPStatusError(
                "not found", request=request, response=httpx.Response(404, request=request)
            )
        return self._job_name(suite_id, suite_name, job_suffix)

    async def delete_suite_job(self, suite_id: str, job_name: str) -> None:
        self.delete_calls.append((suite_id, job_name))

    async def delete_view(self, team_id=None, team_name=None) -> None:
        self.delete_view_calls.append((team_id, team_name))

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
async def test_create_group_rejects_scripts_from_multiple_repos(automation_script_group_db):
    """B1: a suite must be single-repo — mixing repos is rejected."""
    ids = automation_script_group_db["ids"]
    async with automation_script_group_db["async_sessionmaker"]() as session:
        a = await session.get(AutomationScript, ids["script_a_id"])
        b = await session.get(AutomationScript, ids["script_b_id"])
        a.ref_repo = "acme/web"
        b.ref_repo = "acme/api"
        await session.flush()

        service = AutomationScriptGroupService(session)
        with pytest.raises(AutomationScriptGroupServiceError):
            await service.create_group(
                team_id=ids["team_id"],
                name="Cross Repo",
                description=None,
                script_ids=[ids["script_a_id"], ids["script_b_id"]],
                ci_provider=FakeCIProvider(),
            )


@pytest.mark.asyncio
async def test_group_resolves_scripts_within_its_repo(automation_script_group_db):
    """Two repos sharing a ref_path must not collide: the suite binds to its
    repo and resolves only that repo's script, and CI checks out that repo."""
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()
    async with automation_script_group_db["async_sessionmaker"]() as session:
        provider = (
            await session.execute(select(TeamAutomationProvider).where(TeamAutomationProvider.team_id == ids["team_id"]))
        ).scalar_one()
        provider.config_json = json.dumps(
            {"repos": [{"owner": "acme", "repo": "web"}, {"owner": "acme", "repo": "api"}], "default_branch": "main"}
        )
        a = await session.get(AutomationScript, ids["script_a_id"])
        b = await session.get(AutomationScript, ids["script_b_id"])
        a.ref_path = "tests/test_login.py"
        a.ref_repo = "acme/web"
        b.ref_path = "tests/test_login.py"
        b.ref_repo = "acme/api"
        await session.flush()

        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Web Login",
            description=None,
            script_ids=[ids["script_a_id"]],
            actor="1",
            ci_provider=fake_ci,
        )

        assert group.ref_repo == "acme/web"
        scripts = await service.load_group_scripts(group=group)
        assert [s.id for s in scripts] == [ids["script_a_id"]]

    # CI checkout URL is the suite's repo, not the other repo sharing the path.
    git_context = fake_ci.create_calls[0][4]
    assert git_context == {"url": "https://github.com/acme/web.git", "branch": "main"}


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
async def test_delete_group_reclaims_allure_project(automation_script_group_db, monkeypatch):
    """Deleting a suite also reclaims its Allure report storage, wired through
    allure_proxy.delete_project_for_group with the suite's team_id + group."""
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    import app.services.automation.allure_proxy as allure_proxy

    calls: list[tuple[int, int]] = []

    async def _spy(*, session, team_id, group):
        calls.append((team_id, group.id))
        return True

    monkeypatch.setattr(allure_proxy, "delete_project_for_group", _spy)

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

    assert calls == [(ids["team_id"], group.id)]


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


@pytest.mark.asyncio
async def test_trigger_group_run_injects_env_bundle_and_masks_inputs(
    automation_script_group_db, monkeypatch
):
    """A suite whose scripts declare TCRT_VARS, triggered with an environment,
    injects a decrypted namespaced TCRT_ENV_BUNDLE into the CI inputs, records
    the environment NAME on the run, and masks the bundle in stored inputs_json."""
    import base64 as _b64
    import secrets as _secrets

    from app.config import get_settings
    from app.models.automation_environment import EnvParamInput
    from app.services.automation.environment_service import EnvironmentService

    monkeypatch.setattr(
        get_settings().automation_provider,
        "encryption_key",
        _b64.b64encode(_secrets.token_bytes(32)).decode(),
    )
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        env_svc = EnvironmentService(session)
        await env_svc.create_environment(
            team_id=ids["team_id"], name="sit", is_default=True,
            params=[
                EnvParamInput(key="BASE_URL", value="https://sit", is_secret=False),
                EnvParamInput(key="API_TOKEN", value="tok_secret", is_secret=True),
            ],
            actor="1",
        )
        script_a = (
            await session.execute(
                select(AutomationScript).where(AutomationScript.id == ids["script_a_id"])
            )
        ).scalar_one()
        script_a.declared_vars_json = json.dumps([
            {"name": "BASE_URL", "secret": False, "required": True},
            {"name": "API_TOKEN", "secret": True, "required": True},
        ])
        await session.flush()

        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Env Suite", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        run = await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id, actor="1",
            environment="sit", ci_provider=fake_ci,
        )
        persisted = (
            await session.execute(select(AutomationRun).where(AutomationRun.id == run.id))
        ).scalar_one()

    # CI inputs carry the decrypted, per-script-namespaced bundle.
    injected = json.loads(fake_ci.trigger_calls[-1][2]["TCRT_ENV_BUNDLE"])
    assert injected["tests/test_login.py"] == {"BASE_URL": "https://sit", "API_TOKEN": "tok_secret"}
    # Reserved meta rides along so the test-side loader can log the active env in
    # the Jenkins console (secrets masked at print time). Never a ref_path.
    assert injected["__tcrt__"] == {"environment": "sit", "secret_keys": ["API_TOKEN"]}
    # Run records the environment NAME only; stored inputs_json masks the bundle.
    assert persisted.environment == "sit"
    assert json.loads(persisted.inputs_json)["TCRT_ENV_BUNDLE"] == "***"


@pytest.mark.asyncio
async def test_update_group_rename_reclaims_allure_and_warns(automation_script_group_db, monkeypatch):
    """Renaming a suite strands its Allure project (id embeds the name slug);
    update_group must reclaim it and surface a user-facing warning."""
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    import app.services.automation.allure_proxy as allure_proxy

    seen: dict = {}

    async def _fake_delete_renamed(*, session, team_id, suite_id, old_name, new_name):
        seen.update(team_id=team_id, suite_id=suite_id, old_name=old_name, new_name=new_name)
        return "tcrt-team-qa-old-name-1"  # pretend a project was deleted

    monkeypatch.setattr(allure_proxy, "delete_renamed_project", _fake_delete_renamed)

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Old Name",
            description=None,
            script_ids=[ids["script_a_id"]],
            ci_provider=fake_ci,
        )
        await service.update_group(
            team_id=ids["team_id"],
            group_id=group.id,
            name="New Name",
            ci_provider=fake_ci,
        )

    assert seen["old_name"] == "Old Name"
    assert seen["new_name"] == "New Name"
    assert seen["suite_id"] == group.id
    assert any("Allure" in w for w in service.last_warnings)


@pytest.mark.asyncio
async def test_update_group_without_rename_does_not_touch_allure(automation_script_group_db, monkeypatch):
    """A non-rename update (description only) must not reclaim any Allure
    project and must leave warnings empty."""
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    import app.services.automation.allure_proxy as allure_proxy

    called = False

    async def _fake_delete_renamed(*, session, team_id, suite_id, old_name, new_name):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(allure_proxy, "delete_renamed_project", _fake_delete_renamed)

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"],
            name="Stable Name",
            description=None,
            script_ids=[ids["script_a_id"]],
            ci_provider=fake_ci,
        )
        await service.update_group(
            team_id=ids["team_id"],
            group_id=group.id,
            description="just a description change",
            description_provided=True,
            ci_provider=fake_ci,
        )

    assert called is False
    assert service.last_warnings == []


@pytest.mark.asyncio
async def test_webhook_trigger_routes_to_dedicated_hook_job(automation_script_group_db):
    """Webhook-triggered runs execute on the suite's `_hook` job and populate
    ci_job_name_webhook, leaving the primary ci_job_name untouched."""
    from app.models.database_models import AutomationRunTrigger

    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        primary_job = group.ci_job_name
        run = await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id,
            triggered_by=AutomationRunTrigger.WEBHOOK, triggered_by_webhook_id=None,
            ci_provider=fake_ci,
        )
        persisted = (
            await session.execute(select(AutomationRun).where(AutomationRun.id == run.id))
        ).scalar_one()
        refreshed = await session.get(AutomationScriptGroup, group.id)

    assert refreshed.ci_job_name == primary_job  # primary untouched
    assert refreshed.ci_job_name_webhook == f"{primary_job}_hook"
    assert persisted.workflow_id == f"{primary_job}_hook"
    assert persisted.triggered_by == AutomationRunTrigger.WEBHOOK
    assert fake_ci.trigger_calls[-1][0] == f"{primary_job}_hook"


@pytest.mark.asyncio
async def test_user_trigger_leaves_webhook_job_unset(automation_script_group_db):
    """Test-Run-Set (USER) triggers run on the primary job and never create a
    webhook job (ci_job_name_webhook stays NULL)."""
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        run = await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id, actor="1", ci_provider=fake_ci,
        )
        refreshed = await session.get(AutomationScriptGroup, group.id)
        persisted = (
            await session.execute(select(AutomationRun).where(AutomationRun.id == run.id))
        ).scalar_one()

    assert refreshed.ci_job_name_webhook is None
    assert persisted.workflow_id == refreshed.ci_job_name
    assert not refreshed.ci_job_name.endswith("_hook")


@pytest.mark.asyncio
async def test_webhook_trigger_lazily_creates_hook_job_on_404(automation_script_group_db):
    """When the webhook job doesn't exist yet, the update→404→create self-heal
    provisions it and still populates ci_job_name_webhook."""
    from app.models.database_models import AutomationRunTrigger

    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()
    fake_ci.hook_update_raises_404 = True

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        primary_job = group.ci_job_name
        await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id,
            triggered_by=AutomationRunTrigger.WEBHOOK, ci_provider=fake_ci,
        )
        refreshed = await session.get(AutomationScriptGroup, group.id)

    # update raised 404 → create fallback ran with the _hook suffix.
    assert "_hook" in fake_ci.create_suffixes
    assert refreshed.ci_job_name_webhook == f"{primary_job}_hook"


@pytest.mark.asyncio
async def test_delete_suite_deletes_both_jobs(automation_script_group_db):
    """A suite that has a webhook job deletes BOTH jobs on delete."""
    from app.models.database_models import AutomationRunTrigger

    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id,
            triggered_by=AutomationRunTrigger.WEBHOOK, ci_provider=fake_ci,
        )
        primary = group.ci_job_name
        webhook = f"{primary}_hook"
        await service.delete_group(team_id=ids["team_id"], group_id=group.id, ci_provider=fake_ci)

    deleted = {name for _, name in fake_ci.delete_calls}
    assert primary in deleted
    assert webhook in deleted


@pytest.mark.asyncio
async def test_rename_suite_with_webhook_job_renames_both(automation_script_group_db, monkeypatch):
    """Renaming a suite that has a webhook job relocates BOTH jobs (each via
    update_suite_job with its own existing name + suffix)."""
    from app.models.database_models import AutomationRunTrigger
    import app.services.automation.allure_proxy as allure_proxy

    async def _noop_delete_renamed(*, session, team_id, suite_id, old_name, new_name):
        return None

    monkeypatch.setattr(allure_proxy, "delete_renamed_project", _noop_delete_renamed)

    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Old Name", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id,
            triggered_by=AutomationRunTrigger.WEBHOOK, ci_provider=fake_ci,
        )
        old_webhook_name = f"{group.ci_job_name}_hook"
        updated = await service.update_group(
            team_id=ids["team_id"], group_id=group.id, name="New Name", ci_provider=fake_ci,
        )

    # The webhook job was relocated: an update with job_suffix="_hook" carried
    # its old name as existing_job_name.
    assert ("_hook", old_webhook_name) in fake_ci.update_suffixes
    assert updated.ci_job_name_webhook == f"{updated.ci_job_name}_hook"
    assert updated.ci_job_name_webhook.endswith("new-name_hook")


@pytest.mark.asyncio
async def test_resync_team_after_rename_relocates_jobs_view_and_allure(
    automation_script_group_db, monkeypatch
):
    """A team rename relocates each suite's primary + webhook jobs to the new
    team name, deletes the old team view, and reclaims the old Allure projects."""
    from app.models.database_models import AutomationRunTrigger
    import app.services.automation.allure_proxy as allure_proxy

    reclaim_seen: dict = {}

    async def _fake_team_reclaim(*, session, team_id, old_team_name, new_team_name):
        reclaim_seen.update(team_id=team_id, old=old_team_name, new=new_team_name)
        return 0

    monkeypatch.setattr(allure_proxy, "delete_projects_for_team_rename", _fake_team_reclaim)

    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        group = await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        # Give the suite a webhook job (lazy-created on first webhook trigger).
        await service.trigger_group_run(
            team_id=ids["team_id"], group_id=group.id,
            triggered_by=AutomationRunTrigger.WEBHOOK, ci_provider=fake_ci,
        )
        old_primary = group.ci_job_name
        old_webhook = group.ci_job_name_webhook

        await service.resync_team_after_rename(
            team_id=ids["team_id"], old_team_name="QA Team", new_team_name="QA Renamed",
            ci_provider=fake_ci,
        )

    # Both variants were relocated via update_suite_job carrying their existing name.
    assert ("", old_primary) in fake_ci.update_suffixes
    assert ("_hook", old_webhook) in fake_ci.update_suffixes
    # The relocate calls used the NEW team name (7th tuple element).
    resync_calls = [c for c in fake_ci.update_calls if c[6] == "QA Renamed"]
    assert len(resync_calls) == 2
    # The orphaned old view was deleted; Allure reclaim got old/new names.
    assert fake_ci.delete_view_calls == [(ids["team_id"], "QA Team")]
    assert reclaim_seen == {"team_id": ids["team_id"], "old": "QA Team", "new": "QA Renamed"}


@pytest.mark.asyncio
async def test_resync_team_after_rename_noop_when_name_unchanged(automation_script_group_db):
    """Same name in and out → nothing touches CI."""
    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        before_updates = len(fake_ci.update_calls)
        await service.resync_team_after_rename(
            team_id=ids["team_id"], old_team_name="QA Team", new_team_name="QA Team",
            ci_provider=fake_ci,
        )

    assert len(fake_ci.update_calls) == before_updates
    assert fake_ci.delete_view_calls == []


@pytest.mark.asyncio
async def test_resync_team_after_rename_creates_job_when_old_missing(
    automation_script_group_db, monkeypatch
):
    """If a suite's old job is already gone on CI (update → 404), the team-rename
    re-sync falls back to creating it under the new name and still completes
    (deletes old view) — the 404 is not a fatal error."""
    import app.services.automation.allure_proxy as allure_proxy

    async def _noop_team_reclaim(*, session, team_id, old_team_name, new_team_name):
        return 0

    monkeypatch.setattr(allure_proxy, "delete_projects_for_team_rename", _noop_team_reclaim)

    ids = automation_script_group_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_script_group_db["async_sessionmaker"]() as session:
        service = AutomationScriptGroupService(session)
        await service.create_group(
            team_id=ids["team_id"], name="Login Regression", description=None,
            script_ids=[ids["script_a_id"]], ci_provider=fake_ci,
        )
        creates_before = len(fake_ci.create_calls)  # 1 from create_group
        # Simulate the suite's old job being absent on Jenkins.
        fake_ci.update_raises_404 = True
        await service.resync_team_after_rename(
            team_id=ids["team_id"], old_team_name="QA Team", new_team_name="QA Renamed",
            ci_provider=fake_ci,
        )

    # The primary job's update 404'd → create fallback ran (no webhook job here).
    assert len(fake_ci.create_calls) == creates_before + 1
    # Re-sync still reached the end of the loop and dropped the old view.
    assert fake_ci.delete_view_calls == [(ids["team_id"], "QA Team")]
