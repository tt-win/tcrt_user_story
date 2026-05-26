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
