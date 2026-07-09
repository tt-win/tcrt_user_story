from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app


def test_prompt_profile_routes_are_not_mounted() -> None:
    client = TestClient(app)
    base_url = "/api/teams/1/qa-ai-helper/prompt-profiles"

    responses = [
        client.get(base_url),
        client.post(base_url, json={"name": "Style", "testcase_instructions": "Use short steps"}),
        client.put(f"{base_url}/1", json={"name": "Style", "testcase_instructions": "Use short steps"}),
        client.delete(f"{base_url}/1"),
        client.post(f"{base_url}/1/set-default", json={"is_default": True}),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]
