"""Integration tests for KnowledgeWriteService.

These tests require a running Qdrant instance. They are skipped by default;
set TCRT_RUN_KG_INTEGRATION=1 to enable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from app.config import EmbeddingConfig, KnowledgeGraphConfig, QdrantConfig
from app.services.knowledge.embedding_service import EmbeddingService
from app.services.knowledge.knowledge_write_service import KnowledgeWriteService
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient

pytestmark = pytest.mark.skipif(
    not os.getenv("TCRT_RUN_KG_INTEGRATION"),
    reason="Integration tests require running Qdrant. Set TCRT_RUN_KG_INTEGRATION=1 to enable.",
)


@pytest.fixture
def test_qdrant_config() -> QdrantConfig:
    return QdrantConfig(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        collection_test_cases=f"test_test_cases_{uuid.uuid4().hex[:8]}",
        collection_usm_nodes=f"test_usm_nodes_{uuid.uuid4().hex[:8]}",
    )


@pytest.fixture
def test_embedding_config(tmp_path: Path) -> EmbeddingConfig:
    return EmbeddingConfig(
        model="fake-model",
        dimensions=4,
        provider="openrouter",  # will fail without API, but we mock
        cache_path=str(tmp_path / "cache.db"),
    )


@pytest.fixture
def mock_embedding_service(
    monkeypatch: pytest.MonkeyPatch, test_embedding_config: EmbeddingConfig
):
    """Embedding service that returns fake embeddings (no real API call)."""
    svc = EmbeddingService(test_embedding_config)

    async def fake_embed_one(text: str) -> list[float]:
        return [len(text) * 0.001, 0.1, 0.2, 0.3][: test_embedding_config.dimensions]

    async def fake_embed_batch(texts: list[str]) -> list[list[float]]:
        return [
            [len(t) * 0.001, 0.1, 0.2, 0.3][: test_embedding_config.dimensions]
            for t in texts
        ]

    monkeypatch.setattr(svc, "embed_one", fake_embed_one)
    monkeypatch.setattr(svc, "embed_batch", fake_embed_batch)
    return svc


@pytest_asyncio.fixture
async def write_service(
    test_qdrant_config: QdrantConfig,
    test_embedding_config: EmbeddingConfig,
    mock_embedding_service,
) -> AsyncIterator[KnowledgeWriteService]:
    qdrant = QdrantKnowledgeClient(test_qdrant_config)
    config = KnowledgeGraphConfig(
        enabled=True,
        qdrant=test_qdrant_config,
        embedding=test_embedding_config,
    )
    svc = KnowledgeWriteService(qdrant, mock_embedding_service, config)
    yield svc
    await svc.close()


@pytest.mark.asyncio
async def test_ensure_collections(write_service: KnowledgeWriteService) -> None:
    await write_service._ensure_collections()
    assert await write_service._qdrant.collection_exists(
        write_service._config.qdrant.collection_test_cases
    )
    assert await write_service._qdrant.collection_exists(
        write_service._config.qdrant.collection_usm_nodes
    )


@pytest.mark.asyncio
async def test_write_single_test_case(write_service: KnowledgeWriteService) -> None:
    await write_service._ensure_collections()
    tc = {
        "test_case_number": "TCG-001.001.001",
        "title": "Login test",
        "precondition": "User exists",
        "steps": "1. Go to login",
        "expected_result": "Login succeeds",
        "jira_tickets": ["TCG-100"],
        "tags": ["smoke"],
    }
    await write_service.write_test_case(tc)
    # Verify upserted by checking collection count
    points, _ = await write_service._qdrant.scroll(
        write_service._config.qdrant.collection_test_cases, limit=10
    )
    assert any(p["payload"].get("test_case_number") == "TCG-001.001.001" for p in points)


@pytest.mark.asyncio
async def test_idempotent_upsert(write_service: KnowledgeWriteService) -> None:
    """Writing the same test case twice should not create duplicates."""
    await write_service._ensure_collections()
    tc = {
        "test_case_number": "TCG-DUP.001",
        "title": "Dup test",
        "precondition": "",
        "steps": "",
        "expected_result": "",
    }
    await write_service.write_test_case(tc)
    await write_service.write_test_case(tc)
    points, _ = await write_service._qdrant.scroll(
        write_service._config.qdrant.collection_test_cases, limit=100
    )
    matching = [p for p in points if p["payload"].get("test_case_number") == "TCG-DUP.001"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_event_hook_write_entity(write_service: KnowledgeWriteService) -> None:
    await write_service._ensure_collections()
    await write_service.write_entity(
        "test_cases",
        "TCG-EVT.001",
        {"test_case_number": "TCG-EVT.001", "title": "Event test"},
    )
    points, _ = await write_service._qdrant.scroll(
        write_service._config.qdrant.collection_test_cases, limit=10
    )
    assert any(p["payload"].get("test_case_number") == "TCG-EVT.001" for p in points)
