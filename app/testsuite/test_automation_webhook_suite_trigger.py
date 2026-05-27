import json

import pytest
from sqlalchemy import select

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunTrigger,
    AutomationScript,
    AutomationScriptFormat,
    AutomationWebhookDirection,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
)
from app.services.automation.providers.base import ExternalRunRef
from app.services.automation.script_group_service import AutomationScriptGroupService
from app.services.automation.webhook_service import (
    AutomationWebhookNoSuiteBoundError,
    AutomationWebhookService,
    AutomationWebhookSuiteBindingError,
    AutomationWebhookSuiteNotFoundError,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


class FakeCIProvider:
    def __init__(self) -> None:
        self.trigger_calls = []

    async def create_suite_job(self, suite_id, suite_name, test_paths, default_runner_label, **kwargs) -> str:
        return f"tcrt-suite-{suite_id}-{suite_name.lower().replace(' ', '-')}"

    async def update_suite_job(self, suite_id, suite_name, test_paths, default_runner_label, **kwargs) -> str:
        return f"tcrt-suite-{suite_id}-{suite_name.lower().replace(' ', '-')}"

    async def trigger_run(self, workflow_id, branch, inputs) -> ExternalRunRef:
        self.trigger_calls.append((workflow_id, branch, inputs))
        return ExternalRunRef(
            external_run_id="queue:777",
            external_run_url="https://jenkins.example/queue/item/777/",
            raw={"job_name": workflow_id},
        )


@pytest.fixture
def suite_trigger_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]
    AsyncSessionLocal = bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(name="QA Team", description="", wiki_token="w", test_case_table_id="tbl")
        other_team = Team(name="Other Team", description="", wiki_token="w2", test_case_table_id="tbl2")
        session.add_all([team, other_team])
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

        script = AutomationScript(
            team_id=team.id,
            provider_id=storage.id,
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            tags_json="[]",
        )
        session.add(script)
        session.commit()

        ids = {
            "team_id": team.id,
            "other_team_id": other_team.id,
            "script_id": script.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}
    dispose_managed_test_database(bundle)


async def _make_group(service_factory, ids, fake_ci):
    group = await service_factory.create_group(
        team_id=ids["team_id"],
        name="Login Regression",
        description=None,
        script_ids=[ids["script_id"]],
        actor="1",
        ci_provider=fake_ci,
    )
    return group


@pytest.mark.asyncio
async def test_trigger_suite_run_creates_webhook_triggered_run(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    fake_ci = FakeCIProvider()
    async with suite_trigger_db["async_sessionmaker"]() as session:
        group_service = AutomationScriptGroupService(session)
        group = await _make_group(group_service, ids, fake_ci)

        webhook_service = AutomationWebhookService(session)
        webhook, _t, _s = await webhook_service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="Trigger Hook",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
            script_group_id=group.id,
        )

        run = await webhook_service.trigger_suite_run(webhook=webhook, ci_provider=fake_ci)
        persisted = (await session.execute(select(AutomationRun).where(AutomationRun.id == run.id))).scalar_one()

    assert persisted.triggered_by == AutomationRunTrigger.WEBHOOK
    assert persisted.triggered_by_webhook_id == webhook.id
    assert persisted.script_group_id == group.id
    assert persisted.external_run_id == "queue:777"
    assert webhook.last_status == "TRIGGERED"
    assert webhook.last_triggered_at is not None
    assert fake_ci.trigger_calls[0][1] == "main"


@pytest.mark.asyncio
async def test_trigger_suite_run_passes_branch_and_inputs(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    fake_ci = FakeCIProvider()
    async with suite_trigger_db["async_sessionmaker"]() as session:
        group_service = AutomationScriptGroupService(session)
        group = await _make_group(group_service, ids, fake_ci)
        webhook_service = AutomationWebhookService(session)
        webhook, _t, _s = await webhook_service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="Trigger Hook",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
            script_group_id=group.id,
        )
        await webhook_service.trigger_suite_run(
            webhook=webhook,
            branch="release",
            inputs={"FOO": "bar"},
            ci_provider=fake_ci,
        )

    workflow, branch, sent_inputs = fake_ci.trigger_calls[0]
    assert branch == "release"
    assert sent_inputs["FOO"] == "bar"


@pytest.mark.asyncio
async def test_trigger_suite_run_no_suite_bound_raises(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    async with suite_trigger_db["async_sessionmaker"]() as session:
        webhook_service = AutomationWebhookService(session)
        webhook, _t, _s = await webhook_service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="Unbound",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        with pytest.raises(AutomationWebhookNoSuiteBoundError):
            await webhook_service.trigger_suite_run(webhook=webhook, ci_provider=FakeCIProvider())


@pytest.mark.asyncio
async def test_trigger_suite_run_suite_deleted_raises(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    async with suite_trigger_db["async_sessionmaker"]() as session:
        webhook_service = AutomationWebhookService(session)
        webhook, _t, _s = await webhook_service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="Dangling",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        # Simulate the bound suite having been deleted: point at a non-existent id
        # directly, bypassing CRUD validation.
        webhook.script_group_id = 999999
        await session.flush()
        with pytest.raises(AutomationWebhookSuiteNotFoundError):
            await webhook_service.trigger_suite_run(webhook=webhook, ci_provider=FakeCIProvider())


@pytest.mark.asyncio
async def test_create_webhook_rejects_suite_on_outbound(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    fake_ci = FakeCIProvider()
    async with suite_trigger_db["async_sessionmaker"]() as session:
        group = await _make_group(AutomationScriptGroupService(session), ids, fake_ci)
        webhook_service = AutomationWebhookService(session)
        with pytest.raises(AutomationWebhookSuiteBindingError):
            await webhook_service.create_webhook(
                team_id=ids["team_id"],
                direction=AutomationWebhookDirection.OUTBOUND,
                name="Out",
                target_url="https://hook.example",
                events=["run.completed"],
                is_active=True,
                actor="1",
                script_group_id=group.id,
            )


@pytest.mark.asyncio
async def test_create_webhook_rejects_cross_team_suite(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    fake_ci = FakeCIProvider()
    async with suite_trigger_db["async_sessionmaker"]() as session:
        group = await _make_group(AutomationScriptGroupService(session), ids, fake_ci)
        webhook_service = AutomationWebhookService(session)
        # Same group id, but bind it under a different team.
        with pytest.raises(AutomationWebhookSuiteBindingError):
            await webhook_service.create_webhook(
                team_id=ids["other_team_id"],
                direction=AutomationWebhookDirection.INBOUND,
                name="In",
                target_url=None,
                events=[],
                is_active=True,
                actor="1",
                script_group_id=group.id,
            )


@pytest.mark.asyncio
async def test_update_webhook_sets_and_clears_suite_binding(suite_trigger_db):
    ids = suite_trigger_db["ids"]
    fake_ci = FakeCIProvider()
    async with suite_trigger_db["async_sessionmaker"]() as session:
        group = await _make_group(AutomationScriptGroupService(session), ids, fake_ci)
        webhook_service = AutomationWebhookService(session)
        webhook, _t, _s = await webhook_service.create_webhook(
            team_id=ids["team_id"],
            direction=AutomationWebhookDirection.INBOUND,
            name="In",
            target_url=None,
            events=[],
            is_active=True,
            actor="1",
        )
        bound = await webhook_service.update_webhook(
            team_id=ids["team_id"],
            webhook_id=webhook.id,
            actor="1",
            script_group_id=group.id,
            script_group_id_provided=True,
        )
        assert bound.script_group_id == group.id

        cleared = await webhook_service.update_webhook(
            team_id=ids["team_id"],
            webhook_id=webhook.id,
            actor="1",
            script_group_id=None,
            script_group_id_provided=True,
        )
        assert cleared.script_group_id is None
