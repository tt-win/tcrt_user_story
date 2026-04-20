from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
import app.main as main_module


def test_version_endpoint_sets_version_and_no_store_headers(monkeypatch):
    monkeypatch.setattr(main_module.version_service, "get_server_timestamp", lambda: 1357913579)

    client = TestClient(app)
    response = client.get("/api/version/")

    assert response.status_code == 200
    assert response.json()["server_timestamp"] == 1357913579
    assert response.headers["x-tcrt-server-version"] == "1357913579"
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_static_assets_require_revalidation(monkeypatch):
    monkeypatch.setattr(main_module.version_service, "get_server_timestamp", lambda: 2468024680)

    client = TestClient(app)
    response = client.get("/static/js/version-checker.js")

    assert response.status_code == 200
    assert response.headers["x-tcrt-server-version"] == "2468024680"
    assert response.headers["cache-control"] == "no-cache, must-revalidate, max-age=0"


def test_index_embeds_dynamic_server_version(monkeypatch):
    monkeypatch.setattr(main_module.version_service, "get_server_timestamp", lambda: 9753197531)

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert 'window.__TCRT_SERVER_VERSION__ = "9753197531";' in response.text
    assert '/static/js/version-checker.js?v=9753197531' in response.text
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
