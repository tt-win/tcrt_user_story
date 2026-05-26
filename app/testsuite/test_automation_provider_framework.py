import base64
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.api.system_automation_providers import (
    discover_runners_for_saved_system_provider,
    test_system_provider_connection as call_system_provider_connection,
    update_system_provider,
)
from app.config import get_settings
from app.db_access.main import MainAccessBoundary
from app.models.automation_provider import AutomationProviderUpdate
from app.models.database_models import AutomationProviderSlot, SystemAutomationProvider
from app.services.automation.provider_credential_service import (
    CredentialEncryptionError,
    decrypt_credentials,
    encrypted_credentials_fingerprint,
    encrypt_credentials,
)
from app.services.automation.providers.base import HealthStatus, RunnerRef
from app.services.automation.provider_registry import ProviderRegistryError, validate_provider_payload
from app.services.automation.providers.allure_result import AllureResultProvider
from app.services.automation.providers.github_actions_ci import GitHubActionsCIProvider
from app.services.automation.providers.github_storage import GitHubStorageProvider
from app.services.automation.providers.jenkins_ci import JenkinsCIProvider
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _boundary(async_session_factory) -> MainAccessBoundary:
    @asynccontextmanager
    async def _session_provider():
        async with async_session_factory() as session:
            yield session

    return MainAccessBoundary(
        session_provider=_session_provider,
        session_provider_name="test_automation_provider_framework",
    )


def _super_admin() -> SimpleNamespace:
    return SimpleNamespace(id=1, username="admin", role="super_admin")


def _seed_system_jenkins_provider(session_factory, credentials: dict[str, str]) -> int:
    encrypted = encrypt_credentials(credentials)
    with session_factory() as session:
        provider = SystemAutomationProvider(
            provider_slot=AutomationProviderSlot.CI,
            provider_type="ci:jenkins",
            name="Jenkins",
            config_json=json.dumps({"base_url": "https://jenkins.example.test", "default_runner_label": "any"}),
            credentials_encrypted=encrypted,
            is_active=True,
        )
        session.add(provider)
        session.commit()
        return int(provider.id)


def test_provider_credentials_encrypt_decrypt_and_preserve_fingerprint(monkeypatch):
    monkeypatch.setenv("AUTOMATION_PROVIDER_ENCRYPTION_KEY", _key())
    encrypted = encrypt_credentials({"pat": "ghp_1234567890abcd"})

    assert encrypted
    assert "ghp_1234567890abcd" not in encrypted
    assert encrypted_credentials_fingerprint(encrypted) == "pat:***abcd"
    assert decrypt_credentials(encrypted) == {"pat": "ghp_1234567890abcd"}


def test_provider_credentials_require_valid_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("AUTOMATION_PROVIDER_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(get_settings().automation_provider, "encryption_key", "")

    with pytest.raises(CredentialEncryptionError):
        encrypt_credentials({"pat": "ghp_test"})


def test_system_provider_update_preserves_credentials_when_edit_form_is_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings().automation_provider, "encryption_key", _key())
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    session_factory = database_bundle["sync_session_factory"]
    main_boundary = _boundary(database_bundle["async_session_factory"])
    provider_id = _seed_system_jenkins_provider(
        session_factory,
        {"username": "qa-user", "api_token": "old-token"},
    )

    try:
        async def exercise_blank_update():
            await update_system_provider(
                provider_id,
                AutomationProviderUpdate(
                    config={"base_url": "https://jenkins.example.test", "default_runner_label": "linux"},
                    credentials={},
                ),
                request=None,
                current_user=_super_admin(),
                main_boundary=main_boundary,
            )

        asyncio.run(exercise_blank_update())

        with session_factory() as session:
            provider = session.get(SystemAutomationProvider, provider_id)
            assert decrypt_credentials(provider.credentials_encrypted) == {
                "username": "qa-user",
                "api_token": "old-token",
            }

        async def exercise_partial_update():
            await update_system_provider(
                provider_id,
                AutomationProviderUpdate(credentials={"api_token": "new-token"}),
                request=None,
                current_user=_super_admin(),
                main_boundary=main_boundary,
            )

        asyncio.run(exercise_partial_update())

        with session_factory() as session:
            provider = session.get(SystemAutomationProvider, provider_id)
            assert decrypt_credentials(provider.credentials_encrypted) == {
                "username": "qa-user",
                "api_token": "new-token",
            }
    finally:
        dispose_managed_test_database(database_bundle)


def test_saved_system_provider_test_and_runner_discovery_use_stored_credentials(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(get_settings().automation_provider, "encryption_key", _key())
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    session_factory = database_bundle["sync_session_factory"]
    main_boundary = _boundary(database_bundle["async_session_factory"])
    provider_id = _seed_system_jenkins_provider(
        session_factory,
        {"username": "qa-user", "api_token": "saved-token"},
    )
    seen: dict[str, dict[str, str | None]] = {}

    async def fake_health_check(self):
        seen["health"] = self.credentials.model_dump()
        return HealthStatus(status="OK", message="ok")

    async def fake_list_runners(self):
        seen["runners"] = self.credentials.model_dump()
        return [RunnerRef(id=1, name="linux-agent", status="online", labels=["linux"])]

    monkeypatch.setattr(JenkinsCIProvider, "health_check", fake_health_check)
    monkeypatch.setattr(JenkinsCIProvider, "list_runners", fake_list_runners)

    try:
        async def exercise():
            health_result = await call_system_provider_connection(
                provider_id,
                request=None,
                current_user=_super_admin(),
                main_boundary=main_boundary,
            )
            runners_result = await discover_runners_for_saved_system_provider(
                provider_id,
                main_boundary=main_boundary,
            )
            return health_result, runners_result

        health, runners = asyncio.run(exercise())

        assert health.status == "OK"
        assert runners["labels"] == ["any", "linux", "linux-agent"]
        assert seen == {
            "health": {"username": "qa-user", "api_token": "saved-token", "job_token": None},
            "runners": {"username": "qa-user", "api_token": "saved-token", "job_token": None},
        }
    finally:
        dispose_managed_test_database(database_bundle)


def test_provider_registry_validates_known_provider_payloads():
    validate_provider_payload(
        "storage:github",
        {"owner": "example", "repo": "tests", "default_branch": "main"},
        {"pat": "ghp_test"},
    )

    with pytest.raises(ProviderRegistryError):
        validate_provider_payload("storage:unknown", {}, {})


def test_github_actions_suite_template_preserves_github_expressions():
    provider = GitHubActionsCIProvider({"owner": "example", "repo": "tests"}, {"pat": "ghp_test"})
    content = provider._render_suite_workflow(
        suite_id="smoke",
        suite_name="Smoke Suite",
        test_paths=["tests/test_login.py"],
        default_runner_label="ubuntu-latest",
    )

    assert "name: TCRT Suite - Smoke Suite" in content
    assert "${{ github.event.inputs.runner_label }}" in content
    assert "tests/test_login.py" in content


@pytest.mark.asyncio
async def test_github_storage_read_script_uses_etag_cache(monkeypatch):
    provider = GitHubStorageProvider({"owner": "example", "repo": "tests"}, {"pat": "ghp_test"})
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        request = httpx.Request(method, f"https://api.github.test{path}")
        return httpx.Response(304, request=request)

    monkeypatch.setattr(provider, "_request", fake_request)

    content = await provider.read_script("tests/test_login.py", etag='"etag-1"')

    assert content.not_modified is True
    assert content.content == ""
    assert content.etag == '"etag-1"'
    assert calls[0][2]["headers"] == {"If-None-Match": '"etag-1"'}
    assert calls[0][2]["raise_for_status"] is False


@pytest.mark.asyncio
async def test_github_storage_list_scripts_returns_empty_for_missing_path(monkeypatch):
    provider = GitHubStorageProvider({"owner": "example", "repo": "tests"}, {"pat": "ghp_test"})

    async def fake_request(method, path, **kwargs):
        request = httpx.Request(method, f"https://api.github.test{path}")
        return httpx.Response(404, request=request)

    monkeypatch.setattr(provider, "_request", fake_request)

    assert await provider.list_scripts("missing") == []


@pytest.mark.asyncio
async def test_github_actions_trigger_marks_correlation_as_best_effort(monkeypatch):
    provider = GitHubActionsCIProvider({"owner": "example", "repo": "tests"}, {"pat": "ghp_test"})
    calls = []
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        request = httpx.Request(method, f"https://api.github.test{path}")
        if method == "POST":
            return httpx.Response(204, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "workflow_runs": [
                    {
                        "id": 123,
                        "html_url": "https://github.com/example/tests/actions/runs/123",
                        "created_at": created_at,
                    }
                ]
            },
        )

    monkeypatch.setattr(provider, "_request", fake_request)

    ref = await provider.trigger_run("suite.yml", "main", {"tcrt_run_id": "run-1"})

    assert ref.external_run_id == "123"
    assert calls[0][2]["json"]["inputs"]["tcrt_run_id"] == "run-1"
    assert ref.raw["correlation_strategy"] == "recent_workflow_dispatch_run"
    assert ref.raw["correlation_verified"] is False


@pytest.mark.asyncio
async def test_github_actions_trigger_reports_missing_workflow_dispatch(monkeypatch):
    provider = GitHubActionsCIProvider({"owner": "example", "repo": "tests"}, {"pat": "ghp_test"})

    async def fake_request(method, path, **kwargs):
        request = httpx.Request(method, f"https://api.github.test{path}")
        response = httpx.Response(
            422,
            request=request,
            json={"message": "Workflow does not have 'workflow_dispatch' trigger"},
        )
        raise httpx.HTTPStatusError("422", request=request, response=response)

    monkeypatch.setattr(provider, "_request", fake_request)

    with pytest.raises(RuntimeError, match="workflow_dispatch"):
        await provider.trigger_run("suite.yml", "main", {})


@pytest.mark.asyncio
async def test_jenkins_auto_view_uses_list_view_xml(monkeypatch):
    provider = JenkinsCIProvider(
        {"base_url": "https://jenkins.example.test", "auto_manage_views": True, "view_name_template": "TCRT"},
        {"username": "qa", "api_token": "token"},
    )
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        request = httpx.Request(method, f"https://jenkins.example.test{path}")
        if method == "GET":
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(provider, "_request", fake_request)

    await provider._ensure_view_contains_job("tcrt-suite-login")

    create_view_call = next(call for call in calls if call[1] == "/createView")
    assert create_view_call[2]["params"] == {"name": "TCRT"}
    assert create_view_call[2]["headers"] == {"Content-Type": "application/xml"}
    assert b"<hudson.model.ListView>" in create_view_call[2]["content"]
    assert b"<name>TCRT</name>" in create_view_call[2]["content"]


@pytest.mark.asyncio
async def test_jenkins_download_build_artifacts_zip_returns_none_for_queue_id():
    """Queue-state runs have no built build yet — return None instead of 404'ing."""
    provider = JenkinsCIProvider(
        {"base_url": "https://jenkins.example.test"},
        {"username": "qa", "api_token": "token"},
    )
    assert await provider.download_build_artifacts_zip("queue:42") is None


@pytest.mark.asyncio
async def test_jenkins_download_build_artifacts_zip_streams_bytes(monkeypatch):
    """Returns the zip payload Jenkins serves at /artifact/*zip*/archive.zip."""
    provider = JenkinsCIProvider(
        {"base_url": "https://jenkins.example.test"},
        {"username": "qa", "api_token": "token"},
    )

    async def fake_request(method, path, **kwargs):
        assert method == "GET"
        assert path.endswith("/artifact/*zip*/archive.zip")
        request = httpx.Request(method, path)
        return httpx.Response(200, request=request, content=b"PKfake-zip-bytes")

    monkeypatch.setattr(provider, "_request", fake_request)

    payload = await provider.download_build_artifacts_zip(
        "https://jenkins.example.test/job/foo/6#6"
    )
    assert payload == b"PKfake-zip-bytes"


@pytest.mark.asyncio
async def test_jenkins_download_build_artifacts_zip_handles_404_as_no_artifacts(monkeypatch):
    """Jenkins returns 404 when the build archived nothing — that's a normal
    "no allure-results" outcome, not an exception."""
    provider = JenkinsCIProvider(
        {"base_url": "https://jenkins.example.test"},
        {"username": "qa", "api_token": "token"},
    )

    async def fake_request(method, path, **kwargs):
        request = httpx.Request(method, path)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(provider, "_request", fake_request)

    payload = await provider.download_build_artifacts_zip(
        "https://jenkins.example.test/job/foo/6#6"
    )
    assert payload is None


@pytest.mark.asyncio
async def test_allure_result_provider_formats_run_url():
    provider = AllureResultProvider(
        {
            "base_url": "https://allure.internal",
            "project": "frontend",
            "run_url_template": "{base_url}/projects/{project}/launches/{ci_external_run_id}",
        },
        {},
    )

    assert await provider.get_run_report_url("run-123") == (
        "https://allure.internal/projects/frontend/launches/run-123"
    )


@pytest.mark.asyncio
async def test_allure_result_provider_returns_none_without_template():
    # No run_url_template configured — CI is expected to post report_url via
    # the run-status webhook, so backfill must no-op rather than produce a
    # placeholder URL. Especially important for allure-docker-service, where
    # the CI external run id (e.g. Jenkins "<build_url>#<id>") has no reliable
    # mapping to an Allure report id.
    provider = AllureResultProvider(
        {"base_url": "https://allure.internal", "project": "frontend"},
        {},
    )

    assert await provider.get_run_report_url("run-123") is None


# ---------------------------------------------------------------- runner discovery


class _StubRunner:
    """Lightweight stand-in for RunnerRef in helper tests (avoids Pydantic overhead)."""

    def __init__(self, name, labels):
        self._d = {"id": 0, "name": name, "os": "", "status": "online", "busy": False, "labels": labels}

    def model_dump(self):
        return dict(self._d)


def test_collect_runner_labels_drops_jenkins_internal_slug_keeps_displayname():
    """Jenkins built-in node should surface as 'Built-In Node', not the
    internal canonical slug 'built-in' that Jenkins hardcodes."""
    from app.api.automation_providers import _collect_runner_labels

    runners = [_StubRunner("Built-In Node", ["built-in", "Built-In Node"])]
    _, labels = _collect_runner_labels(runners, default_label="Any")
    assert labels == ["Any", "Built-In Node"]


def test_collect_runner_labels_keeps_custom_jenkins_tags():
    """Custom labels on a non-built-in agent (linux, docker, ...) must stay."""
    from app.api.automation_providers import _collect_runner_labels

    runners = [_StubRunner("linux-agent-1", ["linux-agent-1", "linux", "docker"])]
    _, labels = _collect_runner_labels(runners, default_label="Any")
    assert labels == ["Any", "docker", "linux", "linux-agent-1"]


def test_collect_runner_labels_handles_github_actions_self_hosted_runner():
    """GH Actions runners expose 'self-hosted' + OS labels; runner name is a
    valid `runs-on` value so it stays in the list."""
    from app.api.automation_providers import _collect_runner_labels

    runners = [_StubRunner("runner-01", ["self-hosted", "Linux", "X64", "runner-01"])]
    _, labels = _collect_runner_labels(runners, default_label="ubuntu-latest")
    assert labels == ["Linux", "runner-01", "self-hosted", "ubuntu-latest", "X64"]


def test_collect_runner_labels_drops_legacy_master_alias_on_builtin():
    """Older Jenkins still tags built-in node with 'master'. Both slugs drop."""
    from app.api.automation_providers import _collect_runner_labels

    runners = [_StubRunner("Built-In Node", ["master", "built-in", "Built-In Node"])]
    _, labels = _collect_runner_labels(runners, default_label="Any")
    assert labels == ["Any", "Built-In Node"]


def test_collect_runner_labels_dedupes_case_insensitively():
    """Same label in different cases collapses to one (first-seen casing)."""
    from app.api.automation_providers import _collect_runner_labels

    runners = [_StubRunner("agent-1", ["Linux", "linux", "DOCKER"])]
    _, labels = _collect_runner_labels(runners, default_label=None)
    # First-seen casing wins; "linux" gets dropped because "Linux" came first
    assert "Linux" in labels
    assert "linux" not in labels
    assert "DOCKER" in labels


@pytest.mark.asyncio
async def test_jenkins_list_runners_parses_assigned_labels(monkeypatch):
    """Mock the Jenkins /computer/api/json response and verify it surfaces
    each node with its assigned labels intact."""
    provider = JenkinsCIProvider(
        {"base_url": "https://jenkins.example.test"},
        {"username": "qa", "api_token": "token"},
    )
    calls: list[tuple[str, str]] = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path))
        request = httpx.Request(method, f"https://jenkins.example.test{path}")
        body = {
            "computer": [
                {
                    "displayName": "Built-In Node",
                    "idle": True,
                    "offline": False,
                    "assignedLabels": [{"name": "built-in"}, {"name": "Built-In Node"}],
                },
                {
                    "displayName": "linux-agent-1",
                    "idle": False,
                    "offline": False,
                    "assignedLabels": [{"name": "linux-agent-1"}, {"name": "linux"}],
                },
            ],
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(provider, "_request", fake_request)
    runners = await provider.list_runners()

    assert calls == [("GET", "/computer/api/json")]
    assert len(runners) == 2
    assert runners[0].name == "Built-In Node"
    assert runners[0].status == "online"
    assert runners[0].busy is False
    assert "built-in" in runners[0].labels
    assert runners[1].name == "linux-agent-1"
    assert runners[1].busy is True  # idle=False
    assert "linux" in runners[1].labels


@pytest.mark.asyncio
async def test_github_actions_list_runners_parses_repo_runners(monkeypatch):
    """Mock the GH Actions /actions/runners response and verify it returns
    runners with their default + custom labels."""
    provider = GitHubActionsCIProvider(
        {"owner": "example", "repo": "tests"},
        {"pat": "ghp_test"},
    )
    calls: list[tuple[str, str]] = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path))
        request = httpx.Request(method, f"https://api.github.test{path}")
        body = {
            "runners": [
                {
                    "id": 1,
                    "name": "runner-01",
                    "os": "linux",
                    "status": "online",
                    "busy": False,
                    "labels": [
                        {"name": "self-hosted"},
                        {"name": "Linux"},
                        {"name": "X64"},
                    ],
                },
                {
                    "id": 2,
                    "name": "runner-02",
                    "os": "linux",
                    "status": "online",
                    "busy": True,
                    "labels": [
                        {"name": "self-hosted"},
                        {"name": "Linux"},
                        {"name": "gpu"},
                    ],
                },
            ],
        }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(provider, "_request", fake_request)
    runners = await provider.list_runners()

    assert calls == [("GET", "/repos/example/tests/actions/runners")]
    assert [r.name for r in runners] == ["runner-01", "runner-02"]
    assert "gpu" in runners[1].labels
    assert runners[1].busy is True
