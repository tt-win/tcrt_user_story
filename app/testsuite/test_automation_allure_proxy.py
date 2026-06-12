"""Tests for the Jenkins → TCRT → Allure proxy flow.

These mock the Allure HTTP server with a stand-in ``httpx.AsyncClient`` so the
suite stays self-contained (no Docker required) and the assertions stay
focused on the proxy's responsibilities: project_id resolution, idempotent
project ensure, per-file upload, and report URL capture.
"""
from __future__ import annotations

import io
import json
import tarfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationRun,
    AutomationRunStatus,
    AutomationRunTrigger,
    AutomationScript,
    AutomationScriptGroup,
    AutomationScriptGroupJobType,
    SystemAutomationProvider,
    Team,
    TeamAutomationProvider,
)
from app.services.automation import allure_proxy as proxy_module
from app.services.automation.allure_proxy import (
    AllureProxyError,
    AllureProxyNotConfiguredError,
    upload_run_results,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
)


@pytest.fixture
def proxy_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]
    AsyncSessionLocal = bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(name="QA Team", description="", wiki_token="t", test_case_table_id="tbl")
        session.add(team)
        session.flush()

        provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.CI,
            provider_type="ci:jenkins",
            name="Jenkins",
            config_json="{}",
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(provider)
        session.flush()

        # Storage provider is team-scoped (system-level only carries CI/RESULT).
        # AutomationScript requires provider_id NOT NULL, so we wire one here.
        storage_provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub Storage",
            config_json="{}",
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(storage_provider)
        session.flush()

        script = AutomationScript(
            team_id=team.id,
            provider_id=storage_provider.id,
            name="Admin APIs",
            ref_path="tests/test_admin_apis.py",
            ref_branch="main",
            description="",
        )
        session.add(script)
        session.flush()

        group = AutomationScriptGroup(
            team_id=team.id,
            name="Smoke Suite",
            description="",
            script_paths_json=json.dumps(["tests/a.py"]),
            ci_job_type=AutomationScriptGroupJobType.JENKINS,
            created_by="1",
            updated_by="1",
        )
        session.add(group)
        session.flush()

        run_for_script = AutomationRun(
            team_id=team.id,
            automation_script_id=script.id,
            provider_id=provider.id,
            status=AutomationRunStatus.SUCCEEDED,
            triggered_by=AutomationRunTrigger.USER,
            tcrt_correlation_id="corr-script-1",
            external_run_id="6",
            workflow_id="tcrt-suite-script-1-script-test_admin_apis-py",
            branch="main",
            inputs_json="{}",
        )
        session.add(run_for_script)

        run_for_group = AutomationRun(
            team_id=team.id,
            script_group_id=group.id,
            provider_id=provider.id,
            status=AutomationRunStatus.SUCCEEDED,
            triggered_by=AutomationRunTrigger.USER,
            tcrt_correlation_id="corr-group-1",
            external_run_id="7",
            workflow_id="tcrt-suite-{}-smoke-suite".format(group.id),
            branch="main",
            inputs_json="{}",
        )
        session.add(run_for_group)
        session.commit()

        ids = {
            "team_id": team.id,
            "script_run_id": run_for_script.id,
            "group_run_id": run_for_group.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}
    dispose_managed_test_database(bundle)


def _make_archive(files: dict[str, bytes]) -> bytes:
    """Build an allure-results.tgz containing the given filename → bytes map."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, payload in files.items():
            info = tarfile.TarInfo(name=f"allure-results/{name}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _make_jenkins_zip(files: dict[str, bytes]) -> bytes:
    """Mimic Jenkins's /artifact/*zip*/archive.zip layout, where everything
    is nested under an ``archive/`` prefix."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in files.items():
            zf.writestr(f"archive/allure-results/{name}", payload)
    return buf.getvalue()


class _FakeAllureClient:
    """Stand-in for ``httpx.AsyncClient`` that records calls and returns canned
    responses, so we can assert on the proxy's HTTP interaction shape without
    starting an Allure server."""

    def __init__(self, report_url: str = "http://127.0.0.1:5050/allure-docker-service/projects/tcrt-team-qa-team/reports/3/index.html"):
        self.report_url = report_url
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        # Project ensure: 201 first time, 405 thereafter is realistic but we
        # just return 201 — the proxy treats both as fine.
        return httpx.Response(201, request=httpx.Request("POST", url))

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "generate-report" in url:
            return httpx.Response(
                200,
                json={"data": {"report_url": self.report_url}},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, request=httpx.Request("GET", url))


class _ProjectCreationFailsAllureClient(_FakeAllureClient):
    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return httpx.Response(
            400,
            json={"meta_data": {"message": "project root missing"}},
            request=httpx.Request("POST", url),
        )

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "/allure-docker-service/projects/" in url:
            return httpx.Response(
                404,
                json={"meta_data": {"message": "project not found"}},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, request=httpx.Request("GET", url))


class _ProcessingThenReadyAllureClient(_FakeAllureClient):
    """generate-report returns the transient "Processing files… Try later!" 400
    for the first ``stall`` calls, then succeeds. Models Allure's async result
    ingestion so we can assert the proxy retries instead of giving up."""

    def __init__(self, stall: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.stall = stall
        self.generate_calls = 0
        self.send_calls = 0

    async def post(self, url, **kwargs):
        if "send-results" in url:
            self.send_calls += 1
        return await super().post(url, **kwargs)

    async def get(self, url, **kwargs):
        if "generate-report" in url:
            self.calls.append(("GET", url, kwargs))
            self.generate_calls += 1
            if self.generate_calls <= self.stall:
                return httpx.Response(
                    400,
                    json={"meta_data": {"message": (
                        f"Processing files for project_id 'x'. Try later!"
                    )}},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(
                200,
                json={"data": {"report_url": self.report_url}},
                request=httpx.Request("GET", url),
            )
        return await super().get(url, **kwargs)


class _AlwaysProcessingAllureClient(_ProcessingThenReadyAllureClient):
    def __init__(self, **kwargs):
        super().__init__(stall=10_000, **kwargs)


@pytest.mark.asyncio
async def test_generate_report_retries_while_allure_is_processing(proxy_db, monkeypatch):
    """A transient "Try later!" 400 from generate-report must be retried (not
    surfaced as a failure), and the retry must NOT re-send results — re-sending
    restarts ingestion and would livelock the poll."""
    ids = proxy_db["ids"]

    fake = _ProcessingThenReadyAllureClient(stall=2)
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)
    # No real waiting between retries.
    monkeypatch.setattr(proxy_module.asyncio, "sleep", AsyncMock())

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    archive = _make_archive({"a-result.json": b"{}", "b-result.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        report_url = await upload_run_results(
            session=session, run=run, archive_bytes=archive
        )

    assert report_url.endswith("/index.html")
    assert run.report_url == report_url
    # Polled generate-report 3 times (2 "processing" + 1 success)…
    assert fake.generate_calls == 3
    # …but the 2 files were sent exactly once — retries must not re-upload.
    assert fake.send_calls == 2


@pytest.mark.asyncio
async def test_generate_report_raises_if_processing_never_clears(proxy_db, monkeypatch):
    """If Allure stays busy past the retry budget, the proxy raises (leaving the
    run pending for a later backfill) rather than fabricating a report URL."""
    ids = proxy_db["ids"]

    fake = _AlwaysProcessingAllureClient()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)
    monkeypatch.setattr(proxy_module.asyncio, "sleep", AsyncMock())

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    archive = _make_archive({"r.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        with pytest.raises(AllureProxyError, match="still processing"):
            await upload_run_results(session=session, run=run, archive_bytes=archive)

    assert run.report_url is None
    # Bounded: 1 initial + len(_GENERATE_RETRY_DELAYS) retries.
    assert fake.generate_calls == len(proxy_module._GENERATE_RETRY_DELAYS) + 1


@pytest.mark.asyncio
async def test_upload_run_results_happy_path_for_script_run(proxy_db, monkeypatch):
    """End-to-end: archive → ensure project → upload files → capture report URL."""
    ids = proxy_db["ids"]

    fake = _FakeAllureClient()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)

    # Force settings to expose a base_url so the proxy doesn't skip.
    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    archive = _make_archive({"abc-result.json": b"{}", "def-attachment.txt": b"hi"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        report_url = await upload_run_results(
            session=session, run=run, archive_bytes=archive
        )

    # report_url written through and returned
    assert report_url.endswith("/index.html")
    assert run.report_url == report_url

    # 1 project ensure + N send-results + 1 generate-report
    methods_urls = [(m, u) for (m, u, _kw) in fake.calls]
    assert any("/allure-docker-service/projects" in u and m == "POST" for m, u in methods_urls)
    send_calls = [u for m, u in methods_urls if "/send-results" in u and m == "POST"]
    assert len(send_calls) == 2  # two files in the archive
    assert any("/generate-report" in u and m == "GET" for m, u in methods_urls)

    # All send-results carry the team-slug-derived project_id
    for _m, _u, kw in fake.calls:
        if "send-results" in _u:
            assert kw["params"]["project_id"] == "tcrt-team-qa-team"
            assert kw["params"]["force_project_creation"] == "true"


@pytest.mark.asyncio
async def test_upload_run_results_uses_suite_slug_for_group_run(proxy_db, monkeypatch):
    """Template using {suite_slug} expands from script_group.name for suite runs."""
    ids = proxy_db["ids"]

    fake = _FakeAllureClient()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-{suite_slug}",
        ),
    )

    archive = _make_archive({"result.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["group_run_id"])
        )).scalar_one()

        await upload_run_results(session=session, run=run, archive_bytes=archive)

    # The send-results param should reflect the suite slug from the group's name.
    project_ids = {
        kw["params"]["project_id"]
        for _m, _u, kw in fake.calls
        if "send-results" in _u
    }
    assert project_ids == {"tcrt-smoke-suite"}


@pytest.mark.asyncio
async def test_upload_run_results_cleans_results_before_send(proxy_db, monkeypatch):
    """Each report must reflect only the current run: the proxy clears the
    results staging dir (clean-results) before uploading this run's files, so a
    report never accumulates prior executions' test cases. Prior report builds +
    trend history are untouched, so past results stay viewable."""
    ids = proxy_db["ids"]

    fake = _FakeAllureClient()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(base_url="http://127.0.0.1:5050", api_token=""),
    )

    archive = _make_archive({"a-result.json": b"{}", "b-result.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()
        await upload_run_results(session=session, run=run, archive_bytes=archive)

    # clean-results must fire exactly once, and strictly before any send-results.
    clean_idx = [i for i, (m, u, _kw) in enumerate(fake.calls) if "clean-results" in u]
    send_idx = [i for i, (m, u, _kw) in enumerate(fake.calls) if "send-results" in u]
    assert len(clean_idx) == 1
    assert send_idx
    assert clean_idx[0] < min(send_idx)

    # clean-results targets this run's own project (not a blanket wipe), and it
    # matches the project the results are sent to.
    clean_project = fake.calls[clean_idx[0]][2]["params"]["project_id"]
    send_project = fake.calls[send_idx[0]][2]["params"]["project_id"]
    assert clean_project == send_project
    assert "script-" in clean_project


@pytest.mark.asyncio
async def test_upload_run_results_raises_when_allure_project_cannot_be_created(
    proxy_db,
    monkeypatch,
):
    """A broken Allure projects volume should surface as a clear proxy error,
    not as a missing report URL or a later generate-report 404."""
    ids = proxy_db["ids"]

    fake = _ProjectCreationFailsAllureClient()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    archive = _make_archive({"result.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        with pytest.raises(AllureProxyError, match="was not created"):
            await upload_run_results(session=session, run=run, archive_bytes=archive)

    send_params = [
        kw["params"]
        for m, u, kw in fake.calls
        if m == "POST" and "/send-results" in u
    ]
    assert send_params
    assert send_params[0]["force_project_creation"] == "true"
    assert not any("/generate-report" in u for _m, u, _kw in fake.calls)


@pytest.mark.asyncio
async def test_default_template_isolates_script_and_suite_projects(proxy_db, monkeypatch):
    """With the shipped default template, a single-script run and a suite run
    must resolve to different Allure projects so their reports don't merge."""
    ids = proxy_db["ids"]

    import app.config as cfg_mod
    # Use the real default template (no override) to lock in the separation.
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(base_url="http://127.0.0.1:5050", api_token=""),
    )

    archive = _make_archive({"result.json": b"{}"})

    async def _project_id_for(run_id: int) -> str:
        fake = _FakeAllureClient()
        monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)
        async with proxy_db["async_sessionmaker"]() as session:
            from sqlalchemy import select
            run = (await session.execute(
                select(AutomationRun).where(AutomationRun.id == run_id)
            )).scalar_one()
            await upload_run_results(session=session, run=run, archive_bytes=archive)
        return next(
            kw["params"]["project_id"]
            for _m, u, kw in fake.calls
            if "send-results" in u
        )

    script_project = await _project_id_for(ids["script_run_id"])
    suite_project = await _project_id_for(ids["group_run_id"])

    assert script_project != suite_project
    assert "tests-test_admin_apis-py" in script_project
    assert "script-" in script_project
    assert "smoke-suite" in suite_project


@pytest.mark.asyncio
async def test_upload_run_results_raises_when_not_configured(proxy_db, monkeypatch):
    """Empty base_url means the integration is disabled — proxy must refuse loudly."""
    ids = proxy_db["ids"]

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(base_url="", api_token="", project_id_template="x"),
    )

    archive = _make_archive({"r.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        with pytest.raises(AllureProxyNotConfiguredError):
            await upload_run_results(session=session, run=run, archive_bytes=archive)


@pytest.mark.asyncio
async def test_upload_run_results_accepts_jenkins_zip_layout(proxy_db, monkeypatch):
    """Jenkins's /artifact/*zip*/archive.zip namespaces files under
    ``archive/allure-results/`` — the proxy must locate and forward them
    despite the extra nesting that doesn't appear in the tar.gz layout."""
    ids = proxy_db["ids"]

    fake = _FakeAllureClient()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", lambda **kw: fake)

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    archive = _make_jenkins_zip({"result-1.json": b"{}", "result-2.json": b"{}"})

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        await upload_run_results(session=session, run=run, archive_bytes=archive)

    send_calls = [u for m, u, _ in fake.calls if "send-results" in u]
    assert len(send_calls) == 2  # both files made it through despite the archive/ prefix


@pytest.mark.asyncio
async def test_upload_run_results_raises_on_invalid_archive(proxy_db, monkeypatch):
    """Garbage bytes should produce a clear AllureProxyError, not a stack trace."""
    ids = proxy_db["ids"]

    import app.config as cfg_mod
    monkeypatch.setattr(
        cfg_mod.get_settings().automation_provider,
        "allure",
        cfg_mod.AllureConfig(
            base_url="http://127.0.0.1:5050",
            api_token="",
            project_id_template="tcrt-team-{team_slug}",
        ),
    )

    async with proxy_db["async_sessionmaker"]() as session:
        from sqlalchemy import select
        run = (await session.execute(
            select(AutomationRun).where(AutomationRun.id == ids["script_run_id"])
        )).scalar_one()

        with pytest.raises(AllureProxyError):
            await upload_run_results(
                session=session, run=run, archive_bytes=b"not a tar.gz"
            )
