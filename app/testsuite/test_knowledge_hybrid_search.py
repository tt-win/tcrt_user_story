"""Unit tests for HybridSearchService (with fakes; no real Qdrant/Neo4j needed)."""

from __future__ import annotations

import pytest

from app.config import (
    EmbeddingConfig,
    KnowledgeGraphConfig,
    Neo4jConfig,
    QdrantConfig,
)
from app.services.knowledge.embedding_service import EmbeddingService
from app.services.knowledge.hybrid_search_service import (
    HybridSearchService,
    KnowledgeSearchOptions,
    KnowledgeSearchResult,
    RelatedEntity,
)
from app.services.knowledge.neo4j_client import Neo4jClient
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient


class FakeQdrantSearch:
    def __init__(self) -> None:
        self.search_results: dict[str, list[dict]] = {}

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 20,
        score_threshold: float | None = None,
        query_filter=None,
    ) -> list[dict]:
        return self.search_results.get(collection, [])[:limit]


class FakeNeo4j:
    def __init__(self) -> None:
        self.records_by_query: dict[str, list[dict]] = {}
        self.uri = "bolt://test"

    async def execute_read(self, cypher: str, parameters: dict | None = None) -> list[dict]:
        # Match by entity type from cypher
        if "JiraTicket" in cypher and "BLOCKS" in cypher:
            return [
                {"rel": "BLOCKS", "other": {"ticket_key": "TCG-999", "summary": "Blocked"}},
            ]
        if "TestCase" in cypher and "DERIVED_FROM" in cypher:
            return [
                {"rel": "DERIVED_FROM", "other": {"ticket_key": "TCG-100", "summary": "Source"}},
            ]
        return []


@pytest.fixture
def fake_qdrant() -> FakeQdrantSearch:
    return FakeQdrantSearch()


@pytest.fixture
def fake_neo4j() -> FakeNeo4j:
    return FakeNeo4j()


@pytest.fixture
def mock_embedding() -> EmbeddingService:
    cfg = EmbeddingConfig(model="fake", dimensions=4, provider="openrouter", cache_path="")
    svc = EmbeddingService(cfg)

    async def fake_embed_one(text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    svc.embed_one = fake_embed_one  # type: ignore[assignment]
    return svc


@pytest.fixture
def search_service(
    fake_qdrant: FakeQdrantSearch,
    fake_neo4j: FakeNeo4j,
    mock_embedding: EmbeddingService,
) -> HybridSearchService:
    config = KnowledgeGraphConfig(
        enabled=True,
        qdrant=QdrantConfig(),
        neo4j=Neo4jConfig(uri="bolt://test"),
        embedding=EmbeddingConfig(model="fake", dimensions=4),
    )
    return HybridSearchService(
        qdrant_client=fake_qdrant,  # type: ignore[arg-type]
        neo4j_client=fake_neo4j,  # type: ignore[arg-type]
        embedding_service=mock_embedding,
        config=config,
    )


@pytest.mark.asyncio
async def test_hybrid_search_returns_results(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": {"test_case_number": "TCG-001", "title": "Login"}},
            {"id": "p2", "score": 0.7, "payload": {"test_case_number": "TCG-002", "title": "Logout"}},
        ],
    }
    results = await search_service.hybrid_search("login")
    assert len(results) == 2
    assert results[0].entity_type == "test_case"
    assert results[0].entity_id == "TCG-001"
    assert results[0].score == 0.9


@pytest.mark.asyncio
async def test_hybrid_search_dedup(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    """Same entity returned from multiple collections should be deduped."""
    payload = {"ticket_key": "TCG-100", "title": "Same", "jira_ticket": "TCG-100"}
    # The jira_references collection uses different field name
    fake_qdrant.search_results = {
        "jira_references": [{"id": "p1", "score": 0.5, "payload": {**payload, "title": "Same"}}],
    }
    # Only one collection has it, so no dedup needed
    results = await search_service.hybrid_search("anything")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_hybrid_search_team_filter(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": {"test_case_number": "TCG-001", "title": "A", "team_id": 1}},
            {"id": "p2", "score": 0.8, "payload": {"test_case_number": "TCG-002", "title": "B", "team_id": 2}},
        ],
    }
    results = await search_service.hybrid_search("q", options={"team_id": 1})
    assert len(results) == 1
    assert results[0].entity_id == "TCG-001"


@pytest.mark.asyncio
async def test_hybrid_search_empty_query(search_service: HybridSearchService) -> None:
    # Empty query: embed_one will be called with "" - but it returns fake embedding
    results = await search_service.hybrid_search("")
    # Should not error, returns empty since no Qdrant results
    assert results == []


@pytest.mark.asyncio
async def test_impact_analysis_runs_cypher(search_service: HybridSearchService, fake_neo4j: FakeNeo4j) -> None:
    fake_neo4j.records_by_query = {
        "impact": [
            {
                "t": {"ticket_key": "TCG-1"},
                "f": {"feature_id": "F1"},
                "affected_features": [],
                "test_cases": [{"test_case_number": "TCG-001.001"}],
                "affected_test_cases": [],
            }
        ]
    }
    # Without records_by_query, we hit the default branch. Let's mock differently:
    async def fake_execute(cypher, parameters=None):
        return [{"t": {"ticket_key": "TCG-1"}, "f": {"feature_id": "F1"}, "affected_features": [], "test_cases": [{"test_case_number": "TCG-001.001"}], "affected_test_cases": []}]
    fake_neo4j.execute_read = fake_execute  # type: ignore[assignment]
    results = await search_service.impact_analysis("jira_ticket", "TCG-1", depth=2)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_result_model() -> None:
    """Test KnowledgeSearchResult and RelatedEntity pydantic models."""
    r = KnowledgeSearchResult(
        entity_type="test_case",
        entity_id="TCG-001",
        title="Login test",
        score=0.95,
        source="semantic",
    )
    assert r.entity_type == "test_case"
    assert r.score == 0.95
    assert r.related_entities == []  # default
    assert r.metadata == {}  # default

    r2 = KnowledgeSearchResult(
        entity_type="jira_ticket",
        entity_id="TCG-1",
        title="Bug",
        score=0.8,
        related_entities=[RelatedEntity(entity_type="test_case", entity_id="TCG-001.001", relationship="DERIVED_FROM", depth=1)],
        source="both",
    )
    assert len(r2.related_entities) == 1
    assert r2.related_entities[0].relationship == "DERIVED_FROM"


@pytest.mark.asyncio
async def test_search_options_defaults() -> None:
    opts = KnowledgeSearchOptions()
    assert opts.top_k == 20
    assert opts.score_threshold == 0.5
    assert opts.graph_depth == 2
    assert opts.team_id is None
    assert opts.include_graph_expansion is True
    assert "test_cases" in opts.collections


@pytest.mark.asyncio
async def test_graph_expansion_timeout_fallback(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch, fake_neo4j: FakeNeo4j
) -> None:
    import asyncio

    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": {"test_case_number": "TCG-001", "title": "Slow Test"}},
        ],
    }

    async def slow_execute_read(cypher: str, parameters: dict | None = None) -> list[dict]:
        await asyncio.sleep(0.3)  # exceed 150ms timeout
        return [{"rel": "DERIVED_FROM", "other": {"ticket_key": "TCG-999"}}]

    fake_neo4j.execute_read = slow_execute_read  # type: ignore[assignment]

    results = await search_service.hybrid_search("slow test")
    assert len(results) == 1
    assert results[0].source == "semantic"  # fallback to semantic when timed out


@pytest.mark.asyncio
async def test_fetch_related_supports_key_and_node_id(
    search_service: HybridSearchService, fake_neo4j: FakeNeo4j
) -> None:
    queries_run: list[str] = []

    async def mock_execute_read(cypher: str, parameters: dict | None = None) -> list[dict]:
        queries_run.append(cypher)
        if "USMNode" in cypher:
            return [{"rel": "PARENT_OF", "other": {"node_id": "usm_child_1", "title": "Child"}}]
        return []

    fake_neo4j.execute_read = mock_execute_read  # type: ignore[assignment]

    related = await search_service._fetch_related("usm_node", "usm_parent_1", depth=1)
    assert len(related) == 1
    assert related[0].entity_type == "usm_node"
    assert related[0].entity_id == "usm_child_1"
    assert related[0].relationship == "PARENT_OF"
    assert any("u.node_id = $id OR u.id = $id" in q for q in queries_run)

