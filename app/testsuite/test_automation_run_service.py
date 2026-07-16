import json
import re
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import mysql

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationScript,
    AutomationScriptFormat,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
)
from app.services.automation.providers.base import ExternalRunRef, RunStatusSnapshot
from app.services.automation.run_service import (
    AutomationRunAlreadyTerminalError,
    AutomationRunExternalIdMissingError,
    AutomationRunNotFoundError,
    AutomationRunService,
    _pending_run_order_clauses,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


def test_pending_run_order_clauses_compile_for_mysql_without_nulls_first() -> None:
    statement = select(AutomationRun.id).order_by(*_pending_run_order_clauses())

    compiled = str(statement.compile(dialect=mysql.dialect())).upper()

    assert "NULLS FIRST" not in compiled
    assert "CASE WHEN" in compiled
    assert "LAST_SYNCED_AT IS NULL" in compiled


class FakeCIProvider:
    def __init__(self) -> None:
        self.create_job_calls: list[tuple[str, str, list[str], str]] = []
        self.update_job_calls: list[tuple[str, str, list[str], str]] = []
        self.trigger_calls: list[tuple[str, str, dict]] = []
        self.cancel_calls: list[str] = []
        self.get_status_calls: list[str] = []
        self.next_snapshot: RunStatusSnapshot | None = None
        self.update_job_raises_404 = False

    async def create_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        **kwargs,
    ) -> str:
        self.create_job_calls.append((suite_id, suite_name, list(test_paths), default_runner_label))
        return f"tcrt-suite-{suite_id}-{_slug(suite_name)}"

    async def update_suite_job(
        self,
        suite_id: str,
        suite_name: str,
        test_paths: list[str],
        default_runner_label: str,
        **kwargs,
    ) -> str:
        self.update_job_calls.append((suite_id, suite_name, list(test_paths), default_runner_label))
        if self.update_job_raises_404:
            request = httpx.Request("POST", "https://ci.example/job/config.xml")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return f"tcrt-suite-{suite_id}-{_slug(suite_name)}"

    async def trigger_run(self, workflow_id: str, branch: str, inputs: dict[str, str]) -> ExternalRunRef:
        self.trigger_calls.append((workflow_id, branch, dict(inputs)))
        return ExternalRunRef(
            external_run_id="queue:42",
            external_run_url="https://ci.example/queue/42",
            raw={},
        )

    async def cancel_run(self, external_run_id: str) -> None:
        self.cancel_calls.append(external_run_id)

    async def get_run_status(self, external_run_id: str) -> RunStatusSnapshot:
        self.get_status_calls.append(external_run_id)
        return self.next_snapshot or RunStatusSnapshot(
            status="RUNNING",
            external_run_id=external_run_id,
        )


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower() or "suite"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_run(
    session,
    *,
    team_id: int,
    script_id: int,
    ci_provider_id: int,
    actor: str = "1",
    workflow_id: str = "automation-tests",
    branch: str = "main",
    runner_label: str = "linux",
    triggered_by: AutomationRunTrigger = AutomationRunTrigger.USER,
    external_run_id: str = "queue:42",
    external_run_url: str = "https://ci.example/queue/42",
    status: AutomationRunStatus = AutomationRunStatus.QUEUED,
    script_group_id: int | None = None,
    triggered_by_webhook_id: int | None = None,
    inputs: dict | None = None,
    started_at: datetime | None = None,
) -> AutomationRun:
    """Insert an AutomationRun row directly via ORM.

    Replaces the historical `AutomationRunService.trigger_script(...)` call
    sites — the public trigger path has been removed; runs are now created
    by `TestRunSetService.trigger_automation_suites`. See
    `move-automation-execution-to-test-run-set`.
    """
    now = _utcnow()
    run = AutomationRun(
        team_id=team_id,
        automation_script_id=script_id,
        script_group_id=script_group_id,
        provider_id=ci_provider_id,
        external_run_id=external_run_id,
        external_run_url=external_run_url,
        status=status,
        triggered_by=triggered_by,
        triggered_by_user_id=actor,
        triggered_by_webhook_id=triggered_by_webhook_id,
        tcrt_correlation_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        branch=branch,
        inputs_json=json.dumps(inputs or {"tcrt_run_id": "test", "runner_label": runner_label}),
        runner_label=runner_label,
        started_at=started_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    return run


@pytest.fixture
def automation_run_db(tmp_path):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = database_bundle["sync_session_factory"]
    AsyncSessionLocal = database_bundle["async_session_factory"]

    with SyncSessionLocal() as session:
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

        ids = {"team_id": team.id, "script_id": script.id, "ci_provider_id": ci.id}

    yield {
        "ids": ids,
        "async_sessionmaker": AsyncSessionLocal,
    }

    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_cancel_run_marks_cancelled_and_calls_provider(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            workflow_id="job-cancel",
            external_run_id="run-1",
        )
        service = AutomationRunService(session)
        cancelled = await service.cancel_run(
            team_id=ids["team_id"], run_id=run.id, actor="qa", ci_provider=fake_ci
        )

    assert cancelled.status == AutomationRunStatus.CANCELLED
    assert fake_ci.cancel_calls == ["run-1"]


@pytest.mark.asyncio
async def test_cancel_run_rejects_terminal(automation_run_db):
    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.SUCCEEDED,
        )
        service = AutomationRunService(session)
        with pytest.raises(AutomationRunAlreadyTerminalError):
            await service.cancel_run(team_id=ids["team_id"], run_id=run.id)


@pytest.mark.asyncio
async def test_reconcile_with_missing_external_id_marks_unknown(automation_run_db):
    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            external_run_id=None,
        )
        service = AutomationRunService(session)
        reconciled = await service.reconcile_run(
            team_id=ids["team_id"], run_id=run.id, ci_provider=FakeCIProvider()
        )

    assert reconciled.status == AutomationRunStatus.UNKNOWN
    assert reconciled.external_run_id is None


@pytest.mark.asyncio
async def test_reconcile_with_manual_external_id_then_syncs(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()
    fake_ci.next_snapshot = RunStatusSnapshot(
        status="FAILED",
        external_run_id="user-supplied-99",
        finished_at="2024-01-01T10:00:00Z",
        duration_ms=12_000,
    )

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            external_run_id=None,
        )
        service = AutomationRunService(session)
        reconciled = await service.reconcile_run(
            team_id=ids["team_id"],
            run_id=run.id,
            external_run_id="user-supplied-99",
            ci_provider=fake_ci,
        )

    assert reconciled.external_run_id == "user-supplied-99"
    assert reconciled.status == AutomationRunStatus.FAILED
    assert fake_ci.get_status_calls == ["user-supplied-99"]


@pytest.mark.asyncio
async def test_sync_pending_skips_runs_without_external_id(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_run_db["async_sessionmaker"]() as session:
        await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            external_run_id=None,
        )
        service = AutomationRunService(session)
        synced = await service.sync_pending_runs(team_id=ids["team_id"])

    assert synced == []
    assert fake_ci.get_status_calls == []


@pytest.mark.asyncio
async def test_get_run_not_found(automation_run_db):
    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        with pytest.raises(AutomationRunNotFoundError):
            await service.get_run(team_id=ids["team_id"], run_id=9999)


@pytest.mark.asyncio
async def test_sync_run_requires_external_id(automation_run_db):
    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            external_run_id=None,
        )
        service = AutomationRunService(session)
        with pytest.raises(AutomationRunExternalIdMissingError):
            await service.sync_run(team_id=ids["team_id"], run_id=run.id)


@pytest.mark.asyncio
async def test_maybe_fill_report_url_uses_result_provider_when_terminal(automation_run_db):
    from app.models.database_models import SystemAutomationProvider, AutomationProviderSlot
    from app.services.automation.run_service import maybe_fill_report_url

    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        result_provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.RESULT,
            provider_type="result:allure",
            name="Allure",
            config_json=json.dumps(
                {
                    "base_url": "https://allure.example",
                    "run_url_template": "{base_url}/runs/{ci_external_run_id}",
                    "embed_mode": "link",
                }
            ),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(result_provider)
        await session.flush()

        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.SUCCEEDED,
        )
        await maybe_fill_report_url(session=session, run=run)

    assert run.report_url is not None
    assert "allure.example" in run.report_url


@pytest.mark.asyncio
async def test_maybe_fill_report_url_pulls_from_jenkins_and_proxies_to_allure(
    automation_run_db, monkeypatch
):
    from app.services.automation.run_service import maybe_fill_report_url

    ids = automation_run_db["ids"]

    class FakeResultProvider:
        async def get_run_report_url(self, external_run_id: str):
            return f"https://allure.example/report/{external_run_id}"

    class FakeCIWithArtifacts:
        async def download_build_artifacts_zip(self, external_run_id: str) -> bytes:
            return b"fake-zip"

    upload_calls: list[bytes] = []

    async def fake_upload(*, session, run, archive_bytes):
        upload_calls.append(archive_bytes)
        run.report_url = f"https://allure.example/uploaded/{run.external_run_id}"

    monkeypatch.setattr(
        "app.services.automation.allure_proxy.upload_run_results", fake_upload
    )

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.SUCCEEDED,
        )
        await maybe_fill_report_url(
            session=session, run=run, ci_provider=FakeCIWithArtifacts()
        )

    assert upload_calls == [b"fake-zip"]
    assert run.report_url == f"https://allure.example/uploaded/{run.external_run_id}"


@pytest.mark.asyncio
async def test_maybe_fill_report_url_noop_when_provider_has_no_template(automation_run_db):
    """Terminal run with Result provider but no run_url_template configured → no-op.

    Allure-docker-service users must leave run_url_template empty and let CI post
    the real report_url via webhook. The provider must NOT fall back to a synthesized
    URL in that case.
    """
    from app.models.database_models import SystemAutomationProvider, AutomationProviderSlot
    from app.services.automation.run_service import maybe_fill_report_url

    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        # Register a result provider so load_result_provider doesn't return None,
        # but the provider implementation doesn't have a URL template.
        result_provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.RESULT,
            provider_type="result:allure",
            name="Allure",
            config_json=json.dumps({"base_url": "https://allure.example"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(result_provider)
        await session.flush()

        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.SUCCEEDED,
        )
        await maybe_fill_report_url(session=session, run=run)

    # No template → no report URL
    assert run.report_url is None


@pytest.mark.asyncio
async def test_maybe_fill_report_url_skips_when_no_result_provider(automation_run_db):
    from app.services.automation.run_service import maybe_fill_report_url

    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.SUCCEEDED,
        )
        # No result provider configured → no-op
        await maybe_fill_report_url(session=session, run=run)

    assert run.report_url is None


@pytest.mark.asyncio
async def test_maybe_fill_report_url_noop_when_not_terminal(automation_run_db):
    from app.models.database_models import SystemAutomationProvider, AutomationProviderSlot
    from app.services.automation.run_service import maybe_fill_report_url

    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        result_provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.RESULT,
            provider_type="result:allure",
            name="Allure",
            config_json=json.dumps({"base_url": "https://allure.example"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(result_provider)
        await session.flush()

        run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.RUNNING,
        )
        # Not terminal → no-op
        await maybe_fill_report_url(session=session, run=run)

    assert run.report_url is None


@pytest.mark.asyncio
async def test_list_runs_filters_by_triggered_by_webhook_id(automation_run_db):
    """Webhook-triggered runs (test_run_set_id NULL) are listed by webhook id."""
    ids = automation_run_db["ids"]

    async with automation_run_db["async_sessionmaker"]() as session:
        webhook_run = await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            triggered_by=AutomationRunTrigger.WEBHOOK,
            triggered_by_webhook_id=7,
            external_run_id="run-webhook",
        )
        # A run from a different webhook, plus a user-triggered run — both excluded.
        await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            triggered_by=AutomationRunTrigger.WEBHOOK,
            triggered_by_webhook_id=8,
            external_run_id="run-other-webhook",
        )
        await _seed_run(
            session,
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            ci_provider_id=ids["ci_provider_id"],
            external_run_id="run-user",
        )

        service = AutomationRunService(session)
        rows, next_cursor, total = await service.list_runs(
            team_id=ids["team_id"], triggered_by_webhook_id=7
        )

    assert [r.id for r in rows] == [webhook_run.id]
    assert total == 1
    assert next_cursor is None
