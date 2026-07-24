"""Unit tests for HybridSearchService (with fakes; no real Qdrant/Neo4j needed)."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import (
    EmbeddingConfig,
    KnowledgeGraphConfig,
    Neo4jConfig,
    QdrantConfig,
)
from app.services.knowledge.embedding_service import EmbeddingError, EmbeddingService
from app.services.knowledge.hybrid_search_service import (
    HybridSearchService,
    KnowledgeSearchOptions,
    KnowledgeSearchResult,
    RelatedEntity,
)


class FakeQdrantSearch:
    def __init__(self) -> None:
        self.search_results: dict[str, list[dict]] = {}
        self.last_filters: list[Any] = []

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 20,
        score_threshold: float | None = None,
        query_filter=None,
    ) -> list[dict]:
        self.last_filters.append(query_filter)
        hits = self.search_results.get(collection, [])
        # Simulate Qdrant MatchAny on team_id (missing team_id does NOT match)
        if query_filter is not None:
            allowed: set[int] = set()
            for cond in getattr(query_filter, "must", None) or []:
                match = getattr(cond, "match", None)
                any_vals = getattr(match, "any", None) if match is not None else None
                if any_vals:
                    allowed.update(int(v) for v in any_vals)
            if allowed:
                filtered = []
                for h in hits:
                    raw = (h.get("payload") or {}).get("team_id")
                    if raw is None:
                        continue
                    try:
                        if int(raw) in allowed:
                            filtered.append(h)
                    except (TypeError, ValueError):
                        continue
                hits = filtered
        return hits[:limit]


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
    payload = {"test_case_number": "TCG-100", "title": "Same", "team_id": 1}
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": payload},
            {"id": "p2", "score": 0.5, "payload": payload},  # same entity_id, lower score
        ],
    }
    results = await search_service.hybrid_search("anything")
    assert len(results) == 1
    assert results[0].entity_id == "TCG-100"
    assert results[0].score == 0.9


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
    assert any(f is not None for f in fake_qdrant.last_filters)


@pytest.mark.asyncio
async def test_hybrid_search_allowed_team_ids_filter(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": {"test_case_number": "TC-1", "title": "品牌推送", "team_id": 1}},
            {"id": "p2", "score": 0.85, "payload": {"test_case_number": "TC-2", "title": "其他", "team_id": 9}},
            {"id": "p3", "score": 0.8, "payload": {"test_case_number": "TC-3", "title": "品牌推送B", "team_id": 2}},
        ],
    }
    results = await search_service.hybrid_search(
        "品牌推送",
        options={"allowed_team_ids": [1, 2]},
    )
    assert {r.entity_id for r in results} == {"TC-1", "TC-3"}


@pytest.mark.asyncio
async def test_hybrid_search_empty_allowed_team_ids_fail_closed(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": {"test_case_number": "TC-1", "title": "A", "team_id": 1}},
        ],
    }
    results = await search_service.hybrid_search("q", options={"allowed_team_ids": []})
    assert results == []
    assert fake_qdrant.last_filters == []  # must not hit Qdrant


@pytest.mark.asyncio
async def test_hybrid_search_null_team_id_excluded_when_scoped(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    """Red-team: missing team_id must not leak through authorized post-filter."""
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.95, "payload": {"test_case_number": "TC-null", "title": "NoTeam"}},
            {"id": "p2", "score": 0.9, "payload": {"test_case_number": "TC-1", "title": "Ok", "team_id": 1}},
        ],
    }
    # Without Qdrant filter simulation path: force post-filter only by injecting
    # unfiltered hits via allowed_team_ids after search — FakeQdrant drops nulls
    # when filter present, so also unit-test post-filter directly.
    opts = KnowledgeSearchOptions(allowed_team_ids=[1])
    from app.services.knowledge.hybrid_search_service import KnowledgeSearchResult

    raw = [
        KnowledgeSearchResult(entity_type="test_case", entity_id="TC-null", title="NoTeam", score=0.95, metadata={}),
        KnowledgeSearchResult(
            entity_type="test_case", entity_id="TC-1", title="Ok", score=0.9, metadata={"team_id": 1}
        ),
    ]
    merged = search_service._merge_and_rank(raw, opts)
    assert [r.entity_id for r in merged] == ["TC-1"]

    results = await search_service.hybrid_search("q", options={"allowed_team_ids": [1]})
    assert all(r.entity_id != "TC-null" for r in results)


@pytest.mark.asyncio
async def test_hybrid_search_all_qdrant_collections_fail_raises(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("qdrant down")

    fake_qdrant.search = boom  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="Qdrant search failed for all"):
        await search_service.hybrid_search("anything")


@pytest.mark.asyncio
async def test_hybrid_search_collections_none_uses_defaults(
    search_service: HybridSearchService, fake_qdrant: FakeQdrantSearch
) -> None:
    """Regression: callers often pass collections=None; must not ValidationError."""
    fake_qdrant.search_results = {
        "test_cases": [
            {"id": "p1", "score": 0.9, "payload": {"test_case_number": "TC-1", "title": "Ok"}},
        ],
    }
    results = await search_service.hybrid_search(
        "ok",
        options={
            "top_k": 5,
            "score_threshold": 0.55,
            "primary_team_id": None,
            "allowed_team_ids": None,
            "collections": None,
        },
    )
    assert len(results) == 1
    assert results[0].entity_id == "TC-1"


@pytest.mark.asyncio
async def test_hybrid_search_embedding_failure_raises(
    search_service: HybridSearchService, mock_embedding: EmbeddingService
) -> None:
    async def boom(text: str) -> list[float]:
        raise RuntimeError("embedding down")

    mock_embedding.embed_one = boom  # type: ignore[assignment]
    with pytest.raises(EmbeddingError):
        await search_service.hybrid_search("anything")


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
    assert "usm_nodes" in opts.collections
    # jira is opt-in (not in default write set)
    assert "jira_references" not in opts.collections


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

