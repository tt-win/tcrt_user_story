"""Tests for AI link suggestion service.

Critical security tests assert that the prompt payload sent to OpenRouter
contains ONLY the whitelisted fields (test_name, docstring, file_imports,
ref_path, script_format, candidate_cases). Function bodies, fixture
contents, or neighbouring test code MUST NOT appear in the outbound HTTP
body.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptFormat,
    Team,
    TeamAutomationProvider,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
)
from app.services.automation.ai_link_suggest_service import (
    AILinkSuggestError,
    AILinkSuggestService,
    _extract_target_test,
    _parse_openrouter_response,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
)


# ---------------------------------------------------------------------------
# Fake HTTP transport — captures every outbound call for inspection.
# ---------------------------------------------------------------------------


class _CapturingHTTPClient:
    """Replacement for httpx.AsyncClient context manager used by the service."""

    def __init__(self, response_payload: dict[str, Any] | None = None,
                 raise_error: Exception | None = None,
                 status_code: int = 200):
        self.calls: list[dict[str, Any]] = []
        self._response_payload = response_payload or {}
        self._raise_error = raise_error
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self._raise_error is not None:
            raise self._raise_error
        return httpx.Response(
            self._status_code,
            json=self._response_payload,
            request=httpx.Request("POST", url),
        )


def _make_client_factory(client: _CapturingHTTPClient):
    def factory():
        return client
    return factory


# ---------------------------------------------------------------------------
# DB fixture.
# ---------------------------------------------------------------------------


@pytest.fixture
def ai_db(tmp_path, monkeypatch):
    # Stub OpenRouter key so the service goes down the LLM call path.
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.openrouter, "api_key", "test-key", raising=False)

    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]
    AsyncSessionLocal = bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(name="QA", description="", wiki_token="t", test_case_table_id="tbl")
        session.add(team)
        session.commit()

        provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "x", "repo": "y"}),
            credentials_encrypted=None,
            is_active=True,
        )
        case_set = TestCaseSet(team_id=team.id, name="Default", description="", is_default=True)
        session.add_all([provider, case_set])
        session.commit()
        section = TestCaseSection(test_case_set_id=case_set.id, name="Smoke", level=1, sort_order=0)
        session.add(section)
        session.commit()

        tc001 = TestCaseLocal(
            team_id=team.id, test_case_set_id=case_set.id, test_case_section_id=section.id,
            test_case_number="TC-001", title="Login with 2FA succeeds",
            steps="Open login, enter creds, type OTP",
            expected_result="Redirected to dashboard",
        )
        tc002 = TestCaseLocal(
            team_id=team.id, test_case_set_id=case_set.id, test_case_section_id=section.id,
            test_case_number="TC-002", title="Logout returns to landing",
        )
        tc003 = TestCaseLocal(
            team_id=team.id, test_case_set_id=case_set.id, test_case_section_id=section.id,
            test_case_number="TC-003", title="Reset password via email",
        )
        script = AutomationScript(
            team_id=team.id, provider_id=provider.id,
            name="test_login.py", script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/auth/test_login.py", ref_branch="main", tags_json="[]",
            cached_content=(
                "import pytest\n"
                "from pages.login_page import LoginPage\n"
                "\n"
                "DB_PASSWORD = 'super-secret-do-not-leak'\n"
                "\n"
                "def test_login_with_2fa(page):\n"
                "    \"\"\"Verifies the 2FA login flow.\"\"\"\n"
                "    page.goto('/login')\n"
                "    page.fill('#user', 'qa')\n"
                "    page.fill('#pass', DB_PASSWORD)\n"
                "    assert page.url == '/dashboard'\n"
                "\n"
                "def test_logout(page):\n"
                "    page.click('#logout')\n"
            ),
        )
        session.add_all([tc001, tc002, tc003, script])
        session.commit()

        ids = {
            "team_id": team.id,
            "script_id": script.id,
            "tc001_id": tc001.id,
            "tc002_id": tc002.id,
            "tc003_id": tc003.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}
    dispose_managed_test_database(bundle)


# ---------------------------------------------------------------------------
# Pure helper tests.
# ---------------------------------------------------------------------------


def test_extract_target_test_returns_docstring_and_imports():
    content = (
        "import os\n"
        "from app.utils import helper\n"
        "\n"
        "def test_login():\n"
        "    \"\"\"Happy path.\"\"\"\n"
        "    pass\n"
    )
    docstring, imports = _extract_target_test(content, "test_login")
    assert docstring == "Happy path."
    assert "os" in imports
    assert "app.utils" in imports


def test_extract_target_test_missing_returns_empty():
    docstring, imports = _extract_target_test("def other(): pass\n", "test_missing")
    assert docstring is None
    assert imports == []


def test_parse_openrouter_response_filters_hallucinated_ids():
    candidates = [{"id": 5, "number": "TC-005", "title": "Real case", "summary": ""}]
    payload = {
        "choices": [
            {"message": {"content": json.dumps({"suggestions": [
                {"test_case_id": 5, "confidence": 0.9, "rationale": "ok"},
                {"test_case_id": 999, "confidence": 0.8, "rationale": "hallucinated"},
            ]})}}
        ]
    }
    result = _parse_openrouter_response(payload, candidates)
    assert [s.test_case_id for s in result.suggestions] == [5]
    assert result.error_summary is None


# ---------------------------------------------------------------------------
# Privacy guard: outbound HTTP body MUST NOT contain function body or secrets.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_outbound_payload_excludes_function_body(ai_db):
    ids = ai_db["ids"]
    client = _CapturingHTTPClient(response_payload={
        "choices": [
            {"message": {"content": json.dumps({"suggestions": [
                {"test_case_id": ids["tc001_id"], "confidence": 0.92, "rationale": "2FA match"},
            ]})}}
        ]
    })

    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
            actor="42",
        )

    assert len(client.calls) == 1
    # Inspect the user-prompt content the LLM sees.
    body = client.calls[0]["json"]
    user_msg = next(m for m in body["messages"] if m["role"] == "user")
    user_content = user_msg["content"]
    # CRITICAL: secret literal from function body must NOT appear in prompt
    assert "super-secret-do-not-leak" not in user_content
    # CRITICAL: neighbouring test body must NOT appear
    assert "test_logout" not in user_content
    assert "page.click('#logout')" not in user_content
    # CRITICAL: the target test body must also NOT appear (only docstring + imports)
    assert "page.goto" not in user_content
    assert "page.fill" not in user_content
    # Sanity: whitelisted fields ARE in the prompt
    assert "test_login_with_2fa" in user_content
    assert "Verifies the 2FA login flow." in user_content   # docstring
    assert "pages.login_page" in user_content               # imports
    assert "TC-001" in user_content                          # candidate
    # Service returned the suggestion
    assert result.suggestions[0].test_case_id == ids["tc001_id"]
    assert result.suggestions[0].confidence == 0.92
    assert result.error_summary is None


@pytest.mark.asyncio
async def test_suggest_filters_low_confidence(ai_db):
    ids = ai_db["ids"]
    client = _CapturingHTTPClient(response_payload={
        "choices": [
            {"message": {"content": json.dumps({"suggestions": [
                {"test_case_id": ids["tc001_id"], "confidence": 0.91, "rationale": "high"},
                {"test_case_id": ids["tc002_id"], "confidence": 0.72, "rationale": "mid"},
                {"test_case_id": ids["tc003_id"], "confidence": 0.45, "rationale": "low"},
            ]})}}
        ]
    })

    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
        )

    ids_returned = [s.test_case_id for s in result.suggestions]
    # < 0.60 filtered out, ≥ 0.60 retained
    assert ids["tc001_id"] in ids_returned
    assert ids["tc002_id"] in ids_returned
    assert ids["tc003_id"] not in ids_returned
    # Sorted by confidence descending
    confidences = [s.confidence for s in result.suggestions]
    assert confidences == sorted(confidences, reverse=True)


@pytest.mark.asyncio
async def test_suggest_returns_empty_when_no_api_key(ai_db, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().openrouter, "api_key", "", raising=False)
    ids = ai_db["ids"]
    client = _CapturingHTTPClient()
    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
        )
    assert result.suggestions == []
    assert result.error_summary == "ai_disabled"
    assert client.calls == []  # never made the HTTP call


@pytest.mark.asyncio
async def test_suggest_handles_http_5xx(ai_db):
    ids = ai_db["ids"]
    error = httpx.HTTPStatusError(
        "500 Internal",
        request=httpx.Request("POST", "x"),
        response=httpx.Response(500, request=httpx.Request("POST", "x")),
    )
    client = _CapturingHTTPClient(raise_error=error)
    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
        )
    assert result.suggestions == []
    assert result.error_summary == "http_500"


@pytest.mark.asyncio
async def test_suggest_handles_timeout(ai_db):
    ids = ai_db["ids"]
    client = _CapturingHTTPClient(raise_error=httpx.TimeoutException("timeout"))
    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
        )
    assert result.suggestions == []
    assert result.error_summary == "timeout"


@pytest.mark.asyncio
async def test_suggest_handles_non_json_response(ai_db):
    ids = ai_db["ids"]
    client = _CapturingHTTPClient(response_payload={
        "choices": [{"message": {"content": "not-json"}}]
    })
    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
        )
    assert result.suggestions == []
    assert result.error_summary == "non_json_response"


@pytest.mark.asyncio
async def test_suggest_skips_items_with_missing_confidence(ai_db):
    ids = ai_db["ids"]
    client = _CapturingHTTPClient(response_payload={
        "choices": [{"message": {"content": json.dumps({"suggestions": [
            {"test_case_id": ids["tc001_id"], "rationale": "missing confidence"},
            {"test_case_id": ids["tc002_id"], "confidence": 0.88, "rationale": "ok"},
        ]})}}]
    })
    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        result = await service.suggest(
            team_id=ids["team_id"], script_id=ids["script_id"],
            test_name="test_login_with_2fa",
            http_client_factory=_make_client_factory(client),
        )
    assert [s.test_case_id for s in result.suggestions] == [ids["tc002_id"]]


@pytest.mark.asyncio
async def test_suggest_raises_when_script_not_found(ai_db):
    ids = ai_db["ids"]
    client = _CapturingHTTPClient()
    async with ai_db["async_sessionmaker"]() as session:
        service = AILinkSuggestService(session)
        with pytest.raises(AILinkSuggestError):
            await service.suggest(
                team_id=ids["team_id"], script_id=999999,
                test_name="test_login_with_2fa",
                http_client_factory=_make_client_factory(client),
            )
