"""Unit tests for QdrantKnowledgeClient.search (query_points compatibility)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import QdrantConfig
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient


@pytest.mark.asyncio
async def test_search_uses_query_points_when_available() -> None:
    client_wrapper = QdrantKnowledgeClient(QdrantConfig(url="http://localhost:6333"))
    fake = MagicMock()
    fake.query_points = AsyncMock(
        return_value=SimpleNamespace(
            points=[
                SimpleNamespace(id="abc", score=0.91, payload={"title": "T", "team_id": 1}),
            ]
        )
    )
    client_wrapper._client = fake

    hits = await client_wrapper.search(
        collection="test_cases",
        query_vector=[0.1, 0.2],
        limit=5,
        score_threshold=0.5,
        query_filter=None,
    )
    assert hits == [{"id": "abc", "score": 0.91, "payload": {"title": "T", "team_id": 1}}]
    fake.query_points.assert_awaited_once()
    kwargs = fake.query_points.await_args.kwargs
    assert kwargs["collection_name"] == "test_cases"
    assert kwargs["query"] == [0.1, 0.2]
    assert kwargs["limit"] == 5
    assert kwargs["score_threshold"] == 0.5


@pytest.mark.asyncio
async def test_search_falls_back_to_legacy_search() -> None:
    client_wrapper = QdrantKnowledgeClient(QdrantConfig(url="http://localhost:6333"))
    fake = MagicMock(spec=["search"])  # no query_points
    fake.search = AsyncMock(
        return_value=[SimpleNamespace(id=7, score=0.5, payload={"title": "legacy"})]
    )
    client_wrapper._client = fake

    hits = await client_wrapper.search("usm_nodes", [0.0], limit=3)
    assert hits[0]["id"] == "7"
    assert hits[0]["payload"]["title"] == "legacy"
    fake.search.assert_awaited_once()
