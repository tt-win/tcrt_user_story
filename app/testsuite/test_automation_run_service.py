import json
import re

import httpx
import pytest

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
    AutomationScriptNotFoundForRunError,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


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
        "sync_session_factory": SyncSessionLocal,
    }
    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_trigger_script_creates_run_and_calls_provider(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            actor="1",
            workflow_id="automation-tests",
            branch="feature/foo",
            inputs={"extra": "x"},
            ci_provider=fake_ci,
        )

    assert run.workflow_id == "automation-tests"
    assert run.branch == "feature/foo"
    assert run.automation_script_id == ids["script_id"]
    assert run.script_group_id is None
    assert run.status == AutomationRunStatus.QUEUED
    assert run.triggered_by == AutomationRunTrigger.USER
    assert run.runner_label == "linux"
    assert run.external_run_id == "queue:42"
    assert fake_ci.trigger_calls[0][0] == "automation-tests"
    inputs_persisted = json.loads(run.inputs_json)
    assert inputs_persisted["test_paths"] == json.dumps(["tests/test_login.py"], ensure_ascii=False)
    assert inputs_persisted["runner_label"] == "linux"
    assert inputs_persisted["tcrt_run_id"] == run.tcrt_correlation_id
    assert inputs_persisted["extra"] == "x"


@pytest.mark.asyncio
async def test_trigger_script_without_workflow_updates_managed_script_job(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id=None,
            ci_provider=fake_ci,
        )

    expected_workflow = "tcrt-suite-script-1-script-test_login-py"
    assert run.workflow_id == expected_workflow
    assert fake_ci.update_job_calls == [
        ("script-1", "Script test_login.py", ["tests/test_login.py"], "linux")
    ]
    assert fake_ci.create_job_calls == []
    assert fake_ci.trigger_calls[0][0] == expected_workflow


@pytest.mark.asyncio
async def test_trigger_script_without_workflow_creates_managed_script_job_when_missing(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()
    fake_ci.update_job_raises_404 = True

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id=None,
            ci_provider=fake_ci,
        )

    expected_workflow = "tcrt-suite-script-1-script-test_login-py"
    assert run.workflow_id == expected_workflow
    assert fake_ci.update_job_calls == [
        ("script-1", "Script test_login.py", ["tests/test_login.py"], "linux")
    ]
    assert fake_ci.create_job_calls == [
        ("script-1", "Script test_login.py", ["tests/test_login.py"], "linux")
    ]
    assert fake_ci.trigger_calls[0][0] == expected_workflow


@pytest.mark.asyncio
async def test_trigger_script_unknown_script_raises(automation_run_db):
    ids = automation_run_db["ids"]
    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        with pytest.raises(AutomationScriptNotFoundForRunError):
            await service.trigger_script(
                team_id=ids["team_id"],
                script_id=999_999,
                workflow_id="any",
                ci_provider=FakeCIProvider(),
            )


@pytest.mark.asyncio
async def test_cancel_run_marks_cancelled_and_calls_provider(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-a",
            ci_provider=fake_ci,
        )
        cancelled = await service.cancel_run(
            team_id=ids["team_id"],
            run_id=run.id,
            actor="1",
            ci_provider=fake_ci,
        )

    assert cancelled.status == AutomationRunStatus.CANCELLED
    assert fake_ci.cancel_calls == ["queue:42"]
    assert cancelled.finished_at is not None


@pytest.mark.asyncio
async def test_cancel_run_rejects_terminal(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()
    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-a",
            ci_provider=fake_ci,
        )
        run.status = AutomationRunStatus.SUCCEEDED
        await session.flush()

        with pytest.raises(AutomationRunAlreadyTerminalError):
            await service.cancel_run(
                team_id=ids["team_id"],
                run_id=run.id,
                ci_provider=fake_ci,
            )


@pytest.mark.asyncio
async def test_reconcile_with_missing_external_id_marks_unknown(automation_run_db):
    ids = automation_run_db["ids"]
    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        # Trigger then strip external_run_id to simulate failed match
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-x",
            ci_provider=FakeCIProvider(),
        )
        run.external_run_id = None
        run.status = AutomationRunStatus.QUEUED
        await session.flush()

        reconciled = await service.reconcile_run(
            team_id=ids["team_id"],
            run_id=run.id,
            external_run_id=None,
        )

    assert reconciled.status == AutomationRunStatus.UNKNOWN
    assert reconciled.last_synced_at is not None


@pytest.mark.asyncio
async def test_reconcile_with_manual_external_id_then_syncs(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()
    fake_ci.next_snapshot = RunStatusSnapshot(
        status="SUCCEEDED",
        external_run_id="manual:99",
        external_run_url="https://ci.example/run/99",
        duration_ms=12345,
    )

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-y",
            ci_provider=fake_ci,
        )
        run.external_run_id = None
        await session.flush()

        reconciled = await service.reconcile_run(
            team_id=ids["team_id"],
            run_id=run.id,
            external_run_id="manual:99",
            ci_provider=fake_ci,
        )

    assert reconciled.external_run_id == "manual:99"
    assert reconciled.status == AutomationRunStatus.SUCCEEDED
    assert reconciled.finished_at is not None
    assert reconciled.duration_ms == 12345


@pytest.mark.asyncio
async def test_sync_pending_skips_runs_without_external_id(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()
    fake_ci.next_snapshot = RunStatusSnapshot(
        status="RUNNING",
        external_run_id="queue:42",
    )

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        # Pin the provider lookup so we don't try to hit a real Jenkins.
        async def _fixed_provider(_run):
            return fake_ci
        service._provider_from_run_record = _fixed_provider  # type: ignore[assignment]

        with_external = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-a",
            ci_provider=fake_ci,
        )

        # Manually craft a second QUEUED run lacking external_run_id
        orphan = AutomationRun(
            team_id=ids["team_id"],
            automation_script_id=ids["script_id"],
            provider_id=ids["ci_provider_id"],
            status=AutomationRunStatus.QUEUED,
            triggered_by=AutomationRunTrigger.USER,
            tcrt_correlation_id="orphan-corr",
            workflow_id="job-a",
            branch="main",
            inputs_json="{}",
        )
        session.add(orphan)
        await session.flush()

        synced = await service.sync_pending_runs(team_id=ids["team_id"])

    assert len(synced) == 1
    assert synced[0].id == with_external.id
    assert fake_ci.get_status_calls == ["queue:42"]


@pytest.mark.asyncio
async def test_get_run_not_found(automation_run_db):
    ids = automation_run_db["ids"]
    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        with pytest.raises(AutomationRunNotFoundError):
            await service.get_run(team_id=ids["team_id"], run_id=999_999)


@pytest.mark.asyncio
async def test_sync_run_requires_external_id(automation_run_db):
    ids = automation_run_db["ids"]
    fake_ci = FakeCIProvider()
    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)
        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-a",
            ci_provider=fake_ci,
        )
        run.external_run_id = None
        await session.flush()

        with pytest.raises(AutomationRunExternalIdMissingError):
            await service.sync_run(team_id=ids["team_id"], run_id=run.id, ci_provider=fake_ci)


@pytest.mark.asyncio
async def test_maybe_fill_report_url_uses_result_provider_when_terminal(automation_run_db):
    """A terminal run with no report_url should get one filled from the active Result provider."""
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

        # Create a terminal run with no report_url
        service = AutomationRunService(session)

        class _FakeCI:
            async def trigger_run(self, *a, **kw):
                return ExternalRunRef(external_run_id="queue:99", external_run_url="https://ci/99")

        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-z",
            ci_provider=_FakeCI(),
        )
        run.status = AutomationRunStatus.SUCCEEDED
        run.report_url = None
        await session.flush()

        await maybe_fill_report_url(session=session, run=run)
        assert run.report_url == "https://allure.example/runs/queue:99"


@pytest.mark.asyncio
async def test_maybe_fill_report_url_pulls_from_jenkins_and_proxies_to_allure(
    automation_run_db, monkeypatch
):
    """End-to-end pull path: ci_provider has download_build_artifacts_zip,
    proxy forwards bytes to local Allure, run.report_url is populated."""
    from app.services.automation.run_service import maybe_fill_report_url
    from app.services.automation import allure_proxy as proxy_module
    import app.config as cfg_mod
    import io, zipfile, httpx

    ids = automation_run_db["ids"]

    # Allure proxy must be configured for the upload to proceed.
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    # Stand-in for httpx.AsyncClient used by the proxy.
    class _FakeAllure:
        calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, url, **kw):
            self.calls.append(("POST", url))
            return httpx.Response(201, request=httpx.Request("POST", url))

        async def get(self, url, **kw):
            self.calls.append(("GET", url))
            if "generate-report" in url:
                return httpx.Response(
                    200,
                    json={"data": {"report_url": "http://127.0.0.1:5050/r/9/index.html"}},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(200, request=httpx.Request("GET", url))

    fake = _FakeAllure()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)

    # Build a Jenkins-style ZIP that the fake provider will hand back.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("archive/allure-results/r.json", b"{}")
    jenkins_zip = buf.getvalue()

    class _FakeJenkins:
        async def download_build_artifacts_zip(self, external_run_id):
            assert external_run_id == "https://jenkins/job/x/1#1"
            return jenkins_zip

    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)

        class _FakeCI:
            async def trigger_run(self, *a, **kw):
                return ExternalRunRef(external_run_id="queue:1", external_run_url="https://ci/1")

        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-y",
            ci_provider=_FakeCI(),
        )
        run.status = AutomationRunStatus.SUCCEEDED
        run.external_run_id = "https://jenkins/job/x/1#1"
        run.report_url = None
        await session.flush()

        await maybe_fill_report_url(
            session=session, run=run, ci_provider=_FakeJenkins()
        )

        assert run.report_url == "http://127.0.0.1:5050/r/9/index.html"
        # The proxy actually made an Allure send-results call (proves the zip
        # was extracted past Jenkins's `archive/` prefix).
        assert any("/send-results" in u for _m, u in fake.calls)


@pytest.mark.asyncio
async def test_maybe_fill_report_url_noop_when_provider_has_no_template(automation_run_db):
    """Terminal run with Result provider but no run_url_template configured → no-op.

    Allure-docker-service users must leave run_url_template empty and let CI post
    the real report_url via webhook (Allure's report_id has no reliable mapping
    to the CI external_run_id). The provider must NOT fall back to a synthesized
    URL in that case.
    """
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

        service = AutomationRunService(session)

        class _FakeCI:
            async def trigger_run(self, *a, **kw):
                return ExternalRunRef(external_run_id="queue:7", external_run_url="https://ci/7")

        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-w",
            ci_provider=_FakeCI(),
        )
        run.status = AutomationRunStatus.SUCCEEDED
        run.report_url = None
        await session.flush()

        await maybe_fill_report_url(session=session, run=run)
        assert run.report_url is None


@pytest.mark.asyncio
async def test_maybe_fill_report_url_skips_when_no_result_provider(automation_run_db):
    """When no Result provider exists, report_url stays None and no exception is raised."""
    from app.services.automation.run_service import maybe_fill_report_url

    ids = automation_run_db["ids"]
    async with automation_run_db["async_sessionmaker"]() as session:
        service = AutomationRunService(session)

        class _FakeCI:
            async def trigger_run(self, *a, **kw):
                return ExternalRunRef(external_run_id="queue:1", external_run_url="https://ci/1")

        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-y",
            ci_provider=_FakeCI(),
        )
        run.status = AutomationRunStatus.SUCCEEDED
        run.report_url = None
        await session.flush()

        await maybe_fill_report_url(session=session, run=run)
        assert run.report_url is None


@pytest.mark.asyncio
async def test_maybe_fill_report_url_noop_when_not_terminal(automation_run_db):
    """Non-terminal runs (QUEUED / RUNNING) should not get a report_url."""
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

        service = AutomationRunService(session)

        class _FakeCI:
            async def trigger_run(self, *a, **kw):
                return ExternalRunRef(external_run_id="queue:2", external_run_url="https://ci/2")

        run = await service.trigger_script(
            team_id=ids["team_id"],
            script_id=ids["script_id"],
            workflow_id="job-x",
            ci_provider=_FakeCI(),
        )
        # status stays QUEUED — not terminal
        await maybe_fill_report_url(session=session, run=run)
        assert run.report_url is None
