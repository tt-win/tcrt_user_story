"""Regression tests for red-team review findings (Pass 2 fixes).

Covers:
- BUG-24: POST /api/knowledge/backfill returns 410 Gone instead of fake-queued
- BUG-25: /api/knowledge/health never reports a hard 'healthy' for embedding
  when the feature is disabled, and returns enabled=false without
  connecting to Qdrant/Neo4j.
- BUG-29: when KNOWLEDGE_GRAPH_ENABLED=false, the health endpoint returns
  components.status='disabled' and must NOT touch Qdrant/Neo4j clients.
- BUG-35: dimension mismatch in _ensure_collections returns False and does
  NOT mutate the shared KnowledgeGraphConfig singleton's `enabled` flag.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import knowledge as knowledge_api
from app.config import (
    EmbeddingConfig,
    KnowledgeGraphConfig,
    QdrantConfig,
)


# ---- BUG-24 ----


def test_backfill_endpoint_returns_410() -> None:
    """POST /api/knowledge/backfill must surface deprecation, not fake-queue."""
    with pytest.raises(HTTPException) as exc:
        # Bypass the Depends(_require_admin_dep) by calling the underlying
        # coroutine with a fake admin user.
        import asyncio

        async def _run():
            return await knowledge_api.backfill(entity="all", _admin=SimpleNamespace(id=1))

        result = asyncio.run(_run())
        assert result is None  # unreachable, satisfies type-checker

    assert exc.value.status_code == 410
    assert "deprecated" in exc.value.detail.lower()


# ---- BUG-29 + BUG-25 ----


@pytest.mark.asyncio
async def test_health_does_not_connect_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When KG is disabled, the health endpoint must short-circuit and never
    instantiate the Qdrant/Neo4j clients (which would attempt connections)."""
    # Sentinel: if any of these getters is called, fail the test.
    def _fail(*args, **kwargs):
        raise AssertionError("disabled endpoint must not access Qdrant/Neo4j client")

    monkeypatch.setattr(knowledge_api, "is_knowledge_graph_enabled", lambda: False)
    # The get_*_client getters are imported lazily inside the health function,
    # so we must patch their source modules.
    import app.services.knowledge as kg_module

    monkeypatch.setattr(kg_module, "get_qdrant_client", _fail)
    monkeypatch.setattr(kg_module, "get_neo4j_client", _fail)
    monkeypatch.setattr(knowledge_api, "get_write_service", _fail)

    response = await knowledge_api.health(_admin=SimpleNamespace(id=1))
    assert response["enabled"] is False
    assert response["status"] == "disabled"
    # Components must be 'disabled' (no live health check)
    assert response["components"]["qdrant"]["status"] == "disabled"
    assert response["components"]["neo4j"]["status"] == "disabled"
    assert response["components"]["embedding"]["status"] == "disabled"
    # backfill must be present but all None
    assert response["backfill"] == {"test_cases": None, "usm_nodes": None}


@pytest.mark.asyncio
async def test_health_connects_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When KG is enabled, the health endpoint DOES instantiate clients and
    call health_check()."""
    monkeypatch.setattr(knowledge_api, "is_knowledge_graph_enabled", lambda: True)

    qdrant_mock = AsyncMock()
    qdrant_mock.health_check = AsyncMock(return_value=True)
    qdrant_mock.list_collections = AsyncMock(return_value=["test_cases"])
    neo4j_mock = AsyncMock()
    neo4j_mock.health_check = AsyncMock(return_value=True)
    write_mock = AsyncMock()
    write_mock._load_progress = lambda entity_type: None  # type: ignore[assignment]

    import app.services.knowledge as kg_module

    monkeypatch.setattr(kg_module, "get_qdrant_client", lambda: qdrant_mock)
    monkeypatch.setattr(kg_module, "get_neo4j_client", lambda: neo4j_mock)
    monkeypatch.setattr(knowledge_api, "get_write_service", lambda: write_mock)

    response = await knowledge_api.health(_admin=SimpleNamespace(id=1))
    assert response["enabled"] is True
    assert response["status"] == "healthy"
    assert response["components"]["qdrant"]["status"] == "healthy"
    assert response["components"]["qdrant"]["collections"] == ["test_cases"]
    assert response["components"]["neo4j"]["status"] == "healthy"
    # Embedding is "configured" (not "healthy" — we have no live ping)
    assert response["components"]["embedding"]["status"] == "configured"


# ---- BUG-35 ----


@pytest.mark.asyncio
async def test_ensure_collections_returns_false_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dimension mismatch returns False and does NOT mutate shared config."""
    cfg = KnowledgeGraphConfig(
        enabled=True,
        qdrant=QdrantConfig(
            url="http://localhost:6333",
            collection_test_cases="t1",
            collection_usm_nodes="u1",
        ),
        embedding=EmbeddingConfig(
            model="m",
            dimensions=1024,  # configured
            provider="openrouter",
            api_key="k",
        ),
    )
    # Fake qdrant client: existing collection has dim=768 (mismatch)
    fake_qdrant = AsyncMock()
    fake_qdrant.get_collection_dimensions = AsyncMock(return_value=768)
    fake_qdrant.ensure_collection = AsyncMock()

    from app.services.knowledge.knowledge_write_service import KnowledgeWriteService

    svc = KnowledgeWriteService(
        qdrant_client=fake_qdrant,
        embedding_service=AsyncMock(),
        config=cfg,
    )
    ok = await svc._ensure_collections()
    assert ok is False
    # CRITICAL: the shared config must NOT have been mutated.
    assert cfg.enabled is True, "_ensure_collections must not mutate config.enabled"
    # ensure_collection must NOT have been called on the mismatched collection
    fake_qdrant.ensure_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collections_returns_true_when_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """When dimensions match, returns True and collections are created."""
    cfg = KnowledgeGraphConfig(
        enabled=True,
        qdrant=QdrantConfig(
            url="http://localhost:6333",
            collection_test_cases="t1",
            collection_usm_nodes="u1",
        ),
        embedding=EmbeddingConfig(
            model="m",
            dimensions=1024,
            provider="openrouter",
            api_key="k",
        ),
    )
    fake_qdrant = AsyncMock()
    fake_qdrant.get_collection_dimensions = AsyncMock(return_value=None)  # new
    fake_qdrant.ensure_collection = AsyncMock()

    from app.services.knowledge.knowledge_write_service import KnowledgeWriteService

    svc = KnowledgeWriteService(
        qdrant_client=fake_qdrant,
        embedding_service=AsyncMock(),
        config=cfg,
    )
    ok = await svc._ensure_collections()
    assert ok is True
    # Both collections should have been ensured
    assert fake_qdrant.ensure_collection.call_count == 2
