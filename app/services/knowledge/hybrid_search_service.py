"""Hybrid Search service.

結合 Qdrant 語義搜尋 + Neo4j 圖遍歷（read-only）的混合搜尋。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.config import KnowledgeGraphConfig
from app.services.knowledge.embedding_service import EmbeddingService
from app.services.knowledge.neo4j_client import Neo4jClient
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient

LOGGER = logging.getLogger(__name__)


class RelatedEntity(BaseModel):
    entity_type: str
    entity_id: str
    relationship: str
    depth: int


class KnowledgeSearchResult(BaseModel):
    entity_type: str
    entity_id: str
    title: str
    snippet: str = ""
    score: float = 0.0
    source: str = "semantic"  # "semantic" | "graph" | "both"
    metadata: dict[str, Any] = Field(default_factory=dict)
    related_entities: list[RelatedEntity] = Field(default_factory=list)


class KnowledgeSearchOptions(BaseModel):
    collections: list[str] = Field(default_factory=lambda: ["test_cases", "usm_nodes", "jira_references"])
    top_k: int = 20
    score_threshold: float = 0.5
    graph_depth: int = 2
    team_id: int | None = None
    entity_types: list[str] | None = None
    include_graph_expansion: bool = True


class HybridSearchService:
    """Qdrant semantic + Neo4j graph (read-only) hybrid search."""

    def __init__(
        self,
        qdrant_client: QdrantKnowledgeClient,
        neo4j_client: Neo4jClient,
        embedding_service: EmbeddingService,
        config: KnowledgeGraphConfig,
    ) -> None:
        self._qdrant = qdrant_client
        self._neo4j = neo4j_client
        self._embedding = embedding_service
        self._config = config

    async def hybrid_search(
        self,
        query: str,
        options: dict[str, Any] | KnowledgeSearchOptions | None = None,
    ) -> list[KnowledgeSearchResult]:
        """Run hybrid search: Qdrant semantic + Neo4j graph."""
        opts = self._normalize_options(options)
        # Step 1: embed query
        try:
            query_vector = await self._embedding.embed_one(query)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Embedding query failed: %s", exc)
            return []

        # Step 2: semantic search across Qdrant collections
        semantic_results: list[KnowledgeSearchResult] = []
        qdrant_collections = self._resolve_collections(opts)
        for collection in qdrant_collections:
            try:
                hits = await self._qdrant.search(
                    collection=collection,
                    query_vector=query_vector,
                    limit=opts.top_k,
                    score_threshold=opts.score_threshold,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Qdrant search on %s failed: %s", collection, exc)
                continue
            for hit in hits:
                semantic_results.append(self._hit_to_result(collection, hit))

        # Step 3: optional graph expansion
        if opts.include_graph_expansion and semantic_results and self._neo4j_configured():
            try:
                await self._expand_with_graph(semantic_results, opts.graph_depth)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Graph expansion failed: %s", exc)

        # Step 4: dedup + rank
        merged = self._merge_and_rank(semantic_results, opts)
        return merged

    async def impact_analysis(
        self,
        entity_type: str,
        entity_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Traverse graph from a given entity to find affected entities."""
        if not self._neo4j_configured():
            return []
        cypher = self._build_impact_cypher(entity_type, depth)
        try:
            results = await self._neo4j.execute_read(cypher, {"id": entity_id})
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Impact analysis Cypher failed: %s", exc)
            return []
        return results

    async def context_for_qa_helper(
        self, jira_ticket_key: str
    ) -> dict[str, Any]:
        """Build context for QA AI Helper: existing test cases, related features, etc."""
        empty: dict[str, Any] = {
            "ticket": [],
            "features": [],
            "existing_test_cases": [],
            "related_tickets": [],
            "subtasks": [],
        }
        if not self._neo4j_configured():
            return empty
        cypher = """
        MATCH (t:JiraTicket {ticket_key: $key})
        OPTIONAL MATCH (t)-[:DESCRIBES]->(f:Feature)
        OPTIONAL MATCH (f)<-[:TESTS]-(existing_tc:TestCase)
        OPTIONAL MATCH (t)-[:BLOCKS|RELATES_TO]-(related:JiraTicket)
        OPTIONAL MATCH (t)-[:HAS_SUBTASK]->(sub:JiraTicket)
        RETURN t,
               collect(DISTINCT f) as features,
               collect(DISTINCT existing_tc) as existing_tcs,
               collect(DISTINCT related) as related_tickets,
               collect(DISTINCT sub) as subtasks
        """
        try:
            results = await self._neo4j.execute_read(cypher, {"key": jira_ticket_key})
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Context builder failed: %s", exc)
            return empty
        if not results:
            return empty
        record = results[0]
        return {
            "ticket": dict(record.get("t") or {}),
            "features": [dict(f) for f in (record.get("features") or []) if f],
            "existing_test_cases": [dict(tc) for tc in (record.get("existing_tcs") or []) if tc],
            "related_tickets": [dict(r) for r in (record.get("related_tickets") or []) if r],
            "subtasks": [dict(s) for s in (record.get("subtasks") or []) if s],
        }

    # ----- internal helpers -----

    def _normalize_options(
        self, options: dict[str, Any] | KnowledgeSearchOptions | None
    ) -> KnowledgeSearchOptions:
        if options is None:
            return KnowledgeSearchOptions()
        if isinstance(options, KnowledgeSearchOptions):
            return options
        return KnowledgeSearchOptions(**options)

    def _resolve_collections(self, opts: KnowledgeSearchOptions) -> list[str]:
        if not opts.collections:
            return [
                self._config.qdrant.collection_test_cases,
                self._config.qdrant.collection_usm_nodes,
                self._config.qdrant.collection_jira_references,
            ]
        return opts.collections

    def _neo4j_configured(self) -> bool:
        return bool(self._config.neo4j.uri)

    @staticmethod
    def _hit_to_result(collection: str, hit: dict[str, Any]) -> KnowledgeSearchResult:
        payload = hit.get("payload", {}) or {}
        if collection == "jira_references":
            entity_type = "jira_ticket"
            entity_id = payload.get("jira_ticket", hit.get("id", ""))
            title = payload.get("title", "")
        elif collection == "test_cases":
            entity_type = "test_case"
            entity_id = payload.get("test_case_number", hit.get("id", ""))
            title = payload.get("title", "")
        elif collection == "usm_nodes":
            entity_type = "usm_node"
            entity_id = payload.get("node_id", hit.get("id", ""))
            title = payload.get("title", "")
        else:
            entity_type = "unknown"
            entity_id = hit.get("id", "")
            title = ""
        snippet = (payload.get("text") or payload.get("chunk_text") or "")[:200]
        return KnowledgeSearchResult(
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            snippet=snippet,
            score=hit.get("score", 0.0),
            source="semantic",
            metadata=payload,
        )

    async def _expand_with_graph(
        self, results: list[KnowledgeSearchResult], depth: int
    ) -> None:
        """For top results, query Neo4j for related entities and attach to metadata."""
        for result in results[: min(5, len(results))]:  # only top 5
            related = await self._fetch_related(result.entity_type, result.entity_id, depth)
            result.related_entities = related
            if related:
                result.source = "both"

    async def _fetch_related(
        self, entity_type: str, entity_id: str, depth: int
    ) -> list[RelatedEntity]:
        if entity_type == "jira_ticket":
            cypher = """
            MATCH (t:JiraTicket {ticket_key: $id})
            OPTIONAL MATCH (t)-[r:BLOCKS|RELATES_TO|HAS_SUBTASK|EPIC_CONTAINS|DESCRIBES]-(other)
            RETURN type(r) as rel, other
            LIMIT 20
            """
        elif entity_type == "test_case":
            cypher = """
            MATCH (tc:TestCase {test_case_number: $id})
            OPTIONAL MATCH (tc)-[r:DERIVED_FROM|TESTS|DEPENDS_ON]-(other)
            RETURN type(r) as rel, other
            LIMIT 20
            """
        elif entity_type == "usm_node":
            cypher = """
            MATCH (u:USMNode {node_id: $id})
            OPTIONAL MATCH (u)-[r:PARENT_OF|REFERENCES|MAPS_TO|RELATED_TO]-(other)
            RETURN type(r) as rel, other
            LIMIT 20
            """
        else:
            return []
        try:
            records = await self._neo4j.execute_read(cypher, {"id": entity_id})
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Related fetch failed: %s", exc)
            return []
        related: list[RelatedEntity] = []
        for r in records:
            rel = r.get("rel")
            other = r.get("other")
            if not rel or not other:
                continue
            other_type = self._node_to_entity_type(other)
            other_id = self._node_to_entity_id(other)
            related.append(
                RelatedEntity(
                    entity_type=other_type,
                    entity_id=other_id,
                    relationship=rel,
                    depth=1,
                )
            )
        return related

    @staticmethod
    def _node_to_entity_type(node: Any) -> str:
        # node is a dict; check for type markers in payload
        if "ticket_key" in node:
            return "jira_ticket"
        if "test_case_number" in node:
            return "test_case"
        if "node_id" in node:
            return "usm_node"
        if "feature_id" in node:
            return "feature"
        return "unknown"

    @staticmethod
    def _node_to_entity_id(node: Any) -> str:
        for key in ("ticket_key", "test_case_number", "node_id", "feature_id"):
            if key in node:
                return str(node[key])
        return ""

    @staticmethod
    def _merge_and_rank(
        results: list[KnowledgeSearchResult], opts: KnowledgeSearchOptions
    ) -> list[KnowledgeSearchResult]:
        # Deduplicate by (entity_type, entity_id)
        seen: dict[tuple[str, str], KnowledgeSearchResult] = {}
        for r in results:
            key = (r.entity_type, r.entity_id)
            if key not in seen:
                seen[key] = r
            else:
                existing = seen[key]
                # Take the higher score
                if r.score > existing.score:
                    existing.score = r.score
                # Merge related entities
                existing.related_entities.extend(r.related_entities)
        merged = list(seen.values())
        # Filter by entity_types if specified
        if opts.entity_types:
            merged = [r for r in merged if r.entity_type in opts.entity_types]
        # Filter by team_id if specified
        if opts.team_id is not None:
            merged = [r for r in merged if r.metadata.get("team_id") == opts.team_id]
        # Sort by score desc
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[: opts.top_k]

    @staticmethod
    def _build_impact_cypher(entity_type: str, depth: int) -> str:
        if entity_type == "jira_ticket":
            return f"""
            MATCH (t:JiraTicket {{ticket_key: $id}})
            OPTIONAL MATCH (t)-[:DESCRIBES]->(f:Feature)
            OPTIONAL MATCH (f)-[:AFFECTS*1..{depth}]->(affected:Feature)
            OPTIONAL MATCH (f)<-[:TESTS]-(tc:TestCase)
            OPTIONAL MATCH (affected)<-[:TESTS]-(affected_tc:TestCase)
            RETURN t, f, collect(DISTINCT affected) as affected_features,
                   collect(DISTINCT tc) as test_cases,
                   collect(DISTINCT affected_tc) as affected_test_cases
            """
        elif entity_type == "feature":
            return f"""
            MATCH (f:Feature {{feature_id: $id}})
            OPTIONAL MATCH (f)-[:AFFECTS*1..{depth}]->(affected:Feature)
            OPTIONAL MATCH (f)<-[:TESTS]-(tc:TestCase)
            OPTIONAL MATCH (affected)<-[:TESTS]-(affected_tc:TestCase)
            RETURN f, collect(DISTINCT affected) as affected_features,
                   collect(DISTINCT tc) as test_cases,
                   collect(DISTINCT affected_tc) as affected_test_cases
            """
        else:
            return "MATCH (n) WHERE n.id = $id RETURN n"
