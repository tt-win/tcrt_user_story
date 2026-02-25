from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
import app.api.test_cases as test_cases_api


class _MockOpenRouterResponse:
    ok = True
    status_code = 200
    headers = {}

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"revised_precondition":"Mock precondition",'
                            '"revised_steps":"1. Click **Login**",'
                            '"revised_expected_result":"User is signed in",'
                            '"suggestions":["Keep wording concise"]}'
                        )
                    }
                }
            ]
        }


def test_ai_assist_endpoint_remains_callable_with_existing_payload(monkeypatch):
    monkeypatch.setattr(test_cases_api.settings.openrouter, "api_key", "test-openrouter-key", raising=False)

    def _fake_post(url, headers=None, json=None, timeout=30):
        assert url == test_cases_api.OPENROUTER_API_URL
        assert isinstance(json, dict)
        assert json.get("messages")
        return _MockOpenRouterResponse()

    monkeypatch.setattr(test_cases_api.requests, "post", _fake_post)

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="pytest-admin",
        role=UserRole.SUPER_ADMIN,
    )

    try:
        client = TestClient(app)
        response = client.post(
            "/api/teams/1/testcases/ai-assist",
            json={
                "precondition": "User is on login page",
                "steps": "click login",
                "expected_result": "login success",
                "ui_locale": "en-US",
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["revised_precondition"] == "Mock precondition"
    assert payload["revised_steps"] == "1. Click **Login**"
    assert payload["revised_expected_result"] == "User is signed in"
    assert payload["suggestions"] == ["Keep wording concise"]
