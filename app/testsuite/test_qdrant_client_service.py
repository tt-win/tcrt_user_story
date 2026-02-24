from types import SimpleNamespace

import pytest

from app.config import QdrantConfig, Settings
import app.services.qdrant_client as qdrant_module


class FakeAsyncQdrantClient:
    instances = []
    fail_query_attempts = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.query_call_count = 0
        self.retrieve_call_count = 0
        FakeAsyncQdrantClient.instances.append(self)

    async def get_collections(self):
        return SimpleNamespace(collections=[])

    async def query_points(self, **kwargs):
        self.query_call_count += 1
        if FakeAsyncQdrantClient.fail_query_attempts > 0:
            FakeAsyncQdrantClient.fail_query_attempts -= 1
            raise RuntimeError("temporary qdrant error")

        collection_name = kwargs.get("collection_name", "")
        point = SimpleNamespace(payload={"collection": collection_name}, score=0.91)
        return SimpleNamespace(points=[point])

    async def retrieve(self, **kwargs):
        self.retrieve_call_count += 1
        ids = kwargs.get("ids", [])
        return [SimpleNamespace(id=point_id) for point_id in ids]

    async def close(self, **kwargs):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_qdrant_singleton_state():
    qdrant_module._qdrant_client_service = None
    FakeAsyncQdrantClient.instances = []
    FakeAsyncQdrantClient.fail_query_attempts = 0
    yield
    qdrant_module._qdrant_client_service = None


def test_settings_qdrant_defaults_without_qdrant_block(tmp_path, monkeypatch):
    for key in [
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "QDRANT_TIMEOUT",
        "QDRANT_PREFER_GRPC",
        "QDRANT_POOL_SIZE",
        "QDRANT_MAX_CONCURRENT_REQUESTS",
        "QDRANT_MAX_RETRIES",
        "QDRANT_RETRY_BACKOFF_SECONDS",
        "QDRANT_RETRY_BACKOFF_MAX_SECONDS",
        "QDRANT_CHECK_COMPATIBILITY",
        "QDRANT_COLLECTION_JIRA_REFERENCES",
        "QDRANT_COLLECTION_JIRA_REFERANCES",
        "QDRANT_COLLECTION_TEST_CASES",
        "QDRANT_COLLECTION_USM_NODES",
    ]:
        monkeypatch.delenv(key, raising=False)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.qdrant.url == "http://localhost:6333"
    assert loaded.qdrant.collection_jira_referances == "jira_references"
    assert loaded.qdrant.collection_test_cases == "test_cases"
    assert loaded.qdrant.collection_usm_nodes == "usm_nodes"
    assert loaded.qdrant.limit.jira_referances == 20
    assert loaded.qdrant.limit.test_cases == 14
    assert loaded.qdrant.limit.usm_nodes == 6


def test_settings_qdrant_legacy_collection_env_is_normalized(tmp_path, monkeypatch):
    monkeypatch.delenv("QDRANT_COLLECTION_JIRA_REFERENCES", raising=False)
    monkeypatch.setenv("QDRANT_COLLECTION_JIRA_REFERANCES", "jira_referances")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  port: 9999\n"
        "openrouter:\n"
        "  api_key: ''\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.qdrant.collection_jira_referances == "jira_references"


@pytest.mark.asyncio
async def test_qdrant_client_service_reuses_single_async_client(monkeypatch):
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", FakeAsyncQdrantClient)

    service = qdrant_module.QdrantClientService(
        config=QdrantConfig(
            url="http://qdrant.internal:6333",
            pool_size=8,
            max_concurrent_requests=2,
        )
    )

    assert await service.health_check() is True
    assert await service.health_check() is True

    assert len(FakeAsyncQdrantClient.instances) == 1
    fake_client = FakeAsyncQdrantClient.instances[0]
    assert fake_client.kwargs["url"] == "http://qdrant.internal:6333"
    assert fake_client.kwargs["pool_size"] == 8
    assert fake_client.kwargs["timeout"] == 30

    await service.close()
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_qdrant_client_service_retries_query_and_returns_context(monkeypatch):
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", FakeAsyncQdrantClient)
    FakeAsyncQdrantClient.fail_query_attempts = 1

    service = qdrant_module.QdrantClientService(
        config=QdrantConfig(
            max_retries=3,
            retry_backoff_seconds=0,
            retry_backoff_max_seconds=0,
        )
    )

    result = await service.query_similar_context([0.1, 0.2, 0.3])

    assert "test_cases" in result
    assert "usm_nodes" in result
    assert len(result["test_cases"]) == 1
    assert len(result["usm_nodes"]) == 1


@pytest.mark.asyncio
async def test_qdrant_client_service_queries_jira_referances_collection(monkeypatch):
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", FakeAsyncQdrantClient)

    service = qdrant_module.QdrantClientService(
        config=QdrantConfig(
            collection_jira_referances="jira_references",
            max_retries=1,
        )
    )

    points = await service.query_jira_referances_context([0.1, 0.2, 0.3])
    assert len(points) == 1
    assert points[0].payload["collection"] == "jira_references"


@pytest.mark.asyncio
async def test_global_qdrant_client_singleton_and_close(monkeypatch):
    monkeypatch.setattr(qdrant_module, "AsyncQdrantClient", FakeAsyncQdrantClient)

    service1 = qdrant_module.get_qdrant_client()
    service2 = qdrant_module.get_qdrant_client()
    assert service1 is service2

    await service1.health_check()
    assert len(FakeAsyncQdrantClient.instances) == 1

    await qdrant_module.close_qdrant_client()
    assert qdrant_module._qdrant_client_service is None
    assert FakeAsyncQdrantClient.instances[0].closed is True
