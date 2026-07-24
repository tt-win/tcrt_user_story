"""Hybrid Search service.

結合 Qdrant 語義搜尋 + Neo4j 圖遍歷（read-only）的混合搜尋。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from qdrant_client.http import models as qmodels

from app.config import KnowledgeGraphConfig
from app.services.knowledge.embedding_service import EmbeddingError, EmbeddingService
from app.services.knowledge.neo4j_client import Neo4jClient
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient

LOGGER = logging.getLogger(__name__)

# Logical collection keys TCRT writes by default. jira_references is opt-in.
_DEFAULT_COLLECTIONS = ("test_cases", "usm_nodes")
_LOGICAL_COLLECTIONS = ("test_cases", "usm_nodes", "jira_references")


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
    collections: list[str] = Field(default_factory=lambda: list(_DEFAULT_COLLECTIONS))
    top_k: int = 20
    score_threshold: float = 0.5
    graph_depth: int = 2
    team_id: int | None = None
    allowed_team_ids: list[int] | None = None
    primary_team_id: int | None = None
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
        """Run hybrid search: Qdrant semantic + Neo4j graph.

        Critical failures (e.g. embedding unavailable) raise so the retrieval layer
        can mark the call as degraded and the assistant can fall back to SQL tools.
        Partial Qdrant collection failures are soft and still return whatever hits.
        """
        opts = self._normalize_options(options)

        # Fail closed: explicit empty authorized set must not scan all teams.
        if opts.allowed_team_ids is not None and len(opts.allowed_team_ids) == 0:
            return []

        team_filter = self._build_team_query_filter(opts)
        # allowed_team_ids was non-empty but filter could not be built → treat as empty.
        if opts.allowed_team_ids is not None and team_filter is None:
            return []

        # Step 1: embed query (hard failure → degrade upstream)
        try:
            query_vector = await self._embedding.embed_one(query)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Embedding query failed: %s", exc)
            raise EmbeddingError(f"Embedding query failed: {exc}") from exc

        # Step 2: semantic search across Qdrant collections
        semantic_results: list[KnowledgeSearchResult] = []
        qdrant_collections = self._resolve_collections(opts)
        attempted = 0
        succeeded = 0
        for collection in qdrant_collections:
            attempted += 1
            try:
                hits = await self._qdrant.search(
                    collection=collection,
                    query_vector=query_vector,
                    limit=opts.top_k,
                    score_threshold=opts.score_threshold,
                    query_filter=team_filter,
                )
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Qdrant search on %s failed: %s", collection, exc)
                continue
            for hit in hits:
                semantic_results.append(self._hit_to_result(collection, hit))

        # All attempted collections failed (Qdrant down / wrong names) → hard failure
        # so retrieval marks degraded + trips circuit breaker (SQL fallback can run).
        if attempted > 0 and succeeded == 0:
            raise RuntimeError(
                f"Qdrant search failed for all collections: {qdrant_collections}"
            )

        # Step 3: optional graph expansion (soft; never fails the search)
        if opts.include_graph_expansion and semantic_results and self._neo4j_configured():
            try:
                import asyncio

                await asyncio.wait_for(
                    self._expand_with_graph(semantic_results, opts.graph_depth),
                    timeout=0.15,
                )
            except asyncio.TimeoutError:
                LOGGER.warning("Graph expansion timed out (>150ms), proceeding with semantic results")
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Graph expansion failed: %s", exc)

        # Step 4: dedup + rank (+ defense-in-depth team filter)
        return self._merge_and_rank(semantic_results, opts)

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
        MATCH (t:JiraTicket)
        WHERE t.ticket_key = $key OR t.key = $key
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
        # Drop None values so optional fields keep defaults (e.g. collections=None
        # must NOT become a Pydantic list validation error).
        cleaned = {k: v for k, v in options.items() if v is not None}
        return KnowledgeSearchOptions(**cleaned)

    def _resolve_collections(self, opts: KnowledgeSearchOptions) -> list[str]:
        raw = opts.collections or list(_DEFAULT_COLLECTIONS)
        resolved: list[str] = []
        seen: set[str] = set()
        for name in raw:
            actual = self._map_collection_name(name)
            if actual not in seen:
                seen.add(actual)
                resolved.append(actual)
        return resolved

    def _map_collection_name(self, name: str) -> str:
        """Map logical collection keys to configured Qdrant collection names."""
        mapping = {
            "test_cases": self._config.qdrant.collection_test_cases,
            "usm_nodes": self._config.qdrant.collection_usm_nodes,
            "jira_references": self._config.qdrant.collection_jira_references,
        }
        return mapping.get(name, name)

    def _collection_kind(self, collection: str) -> str:
        """Resolve a physical or logical collection name to entity kind."""
        tc = self._config.qdrant.collection_test_cases
        usm = self._config.qdrant.collection_usm_nodes
        jira = self._config.qdrant.collection_jira_references
        if collection in (tc, "test_cases"):
            return "test_case"
        if collection in (usm, "usm_nodes"):
            return "usm_node"
        if collection in (jira, "jira_references"):
            return "jira_ticket"
        return "unknown"

    def _neo4j_configured(self) -> bool:
        return bool(self._config.neo4j.uri)

    def _build_team_query_filter(self, opts: KnowledgeSearchOptions) -> qmodels.Filter | None:
        """Build Qdrant payload filter for authorized team scope (MatchAny).

        Returns None when no team constraint is requested.
        Returns a filter with MatchAny when team_ids are resolved.
        """
        team_ids = self._resolve_filter_team_ids(opts)
        if team_ids is None:
            return None
        if not team_ids:
            return None
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="team_id",
                    match=qmodels.MatchAny(any=team_ids),
                )
            ]
        )

    @staticmethod
    def _resolve_filter_team_ids(opts: KnowledgeSearchOptions) -> list[int] | None:
        """Return authorized team ids for filtering, or None if unscoped."""
        if opts.allowed_team_ids is not None:
            ids = [int(t) for t in opts.allowed_team_ids if t is not None]
            if opts.primary_team_id is not None:
                ids.append(int(opts.primary_team_id))
            # preserve order, dedupe
            return list(dict.fromkeys(ids))
        if opts.team_id is not None:
            return [int(opts.team_id)]
        if opts.primary_team_id is not None and opts.allowed_team_ids is None:
            # primary alone without allowed list: treat as single-team scope
            return [int(opts.primary_team_id)]
        return None

    def _hit_to_result(self, collection: str, hit: dict[str, Any]) -> KnowledgeSearchResult:
        payload = hit.get("payload", {}) or {}
        kind = self._collection_kind(collection)
        if kind == "jira_ticket":
            entity_type = "jira_ticket"
            entity_id = str(payload.get("jira_ticket") or payload.get("ticket_key") or hit.get("id", ""))
            title = payload.get("title", "") or ""
        elif kind == "test_case":
            entity_type = "test_case"
            entity_id = str(payload.get("test_case_number") or hit.get("id", ""))
            title = payload.get("title", "") or ""
        elif kind == "usm_node":
            entity_type = "usm_node"
            entity_id = str(payload.get("node_id") or hit.get("id", ""))
            title = payload.get("title", "") or ""
        else:
            entity_type = "unknown"
            entity_id = str(hit.get("id", ""))
            title = ""
        snippet = self._build_snippet(payload, title=title)
        # Slim metadata for downstream LLM projection (avoid shipping full steps/body).
        slim_meta = self._slim_metadata(payload)
        return KnowledgeSearchResult(
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            snippet=snippet,
            score=float(hit.get("score", 0.0) or 0.0),
            source="semantic",
            metadata=slim_meta,
        )

    @staticmethod
    def _build_snippet(payload: dict[str, Any], *, title: str = "") -> str:
        """Build a short grounding snippet even when embedding text was not stored."""
        for key in ("text", "chunk_text", "description", "steps", "expected_result", "precondition"):
            raw = payload.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()[:200]
        # USM story shape
        parts = [p for p in (payload.get("as_a"), payload.get("i_want"), payload.get("so_that")) if p]
        if parts:
            return " / ".join(str(p) for p in parts)[:200]
        return (title or "")[:200]

    @staticmethod
    def _slim_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        """Keep only attribution / identity fields for tool results."""
        keep = (
            "team_id",
            "team_name",
            "test_case_number",
            "test_case_set_id",
            "test_case_set_name",
            "section_name",
            "map_id",
            "map_name",
            "node_type",
            "jira_ticket",
            "component_team",
            "priority",
        )
        slim: dict[str, Any] = {}
        for key in keep:
            if key in payload and payload[key] is not None:
                slim[key] = payload[key]
        return slim

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
        del depth  # depth reserved for future multi-hop expansion
        if entity_type == "jira_ticket":
            cypher = """
            MATCH (t:JiraTicket)
            WHERE t.ticket_key = $id OR t.key = $id
            OPTIONAL MATCH (t)-[r:BLOCKS|RELATES_TO|HAS_SUBTASK|EPIC_CONTAINS|DESCRIBES|OWNS]-(other)
            RETURN type(r) as rel, other
            LIMIT 20
            """
        elif entity_type == "test_case":
            cypher = """
            MATCH (tc:TestCase)
            WHERE tc.test_case_number = $id OR tc.id = $id OR tc.id = toInteger($id)
            OPTIONAL MATCH (tc)-[r:DERIVED_FROM|TESTS|DEPENDS_ON]-(other)
            RETURN type(r) as rel, other
            LIMIT 20
            """
        elif entity_type == "usm_node":
            cypher = """
            MATCH (u:USMNode)
            WHERE u.node_id = $id OR u.id = $id
            OPTIONAL MATCH (u)-[r:PARENT_OF|REFERENCES|MAPS_TO|RELATED_TO|HAS_NODE]-(other)
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
        if "ticket_key" in node or "key" in node:
            return "jira_ticket"
        if "test_case_number" in node or "test_case_id" in node:
            return "test_case"
        if "node_id" in node:
            return "usm_node"
        if "feature_id" in node:
            return "feature"
        return "unknown"

    @staticmethod
    def _node_to_entity_id(node: Any) -> str:
        for key in ("ticket_key", "key", "test_case_number", "id", "node_id", "feature_id"):
            if key in node:
                return str(node[key])
        return ""

    @staticmethod
    def _payload_team_id(metadata: dict[str, Any] | None) -> int | None:
        if not metadata:
            return None
        raw = metadata.get("team_id")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _merge_and_rank(
        self,
        results: list[KnowledgeSearchResult],
        opts: KnowledgeSearchOptions,
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

        # Primary team score boosting (+0.05)
        primary = opts.primary_team_id if opts.primary_team_id is not None else opts.team_id
        if primary is not None:
            primary_int = int(primary)
            for r in merged:
                if self._payload_team_id(r.metadata) == primary_int:
                    r.score += 0.05

        # Defense-in-depth team filter (fail-closed: missing team_id is excluded when scoped)
        allowed = self._resolve_filter_team_ids(opts)
        if allowed is not None:
            allowed_set = set(allowed)
            if allowed_set:
                merged = [
                    r
                    for r in merged
                    if (tid := self._payload_team_id(r.metadata)) is not None and tid in allowed_set
                ]
            else:
                merged = []

        # Sort by score desc
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[: opts.top_k]

    @staticmethod
    def _build_impact_cypher(entity_type: str, depth: int) -> str:
        # depth is validated as int before f-string; only used as hop bound.
        safe_depth = max(1, min(int(depth), 5))
        if entity_type == "jira_ticket":
            return f"""
            MATCH (t:JiraTicket {{ticket_key: $id}})
            OPTIONAL MATCH (t)-[:DESCRIBES]->(f:Feature)
            OPTIONAL MATCH (f)-[:AFFECTS*1..{safe_depth}]->(affected:Feature)
            OPTIONAL MATCH (f)<-[:TESTS]-(tc:TestCase)
            OPTIONAL MATCH (affected)<-[:TESTS]-(affected_tc:TestCase)
            RETURN t, f, collect(DISTINCT affected) as affected_features,
                   collect(DISTINCT tc) as test_cases,
                   collect(DISTINCT affected_tc) as affected_test_cases
            """
        elif entity_type == "feature":
            return f"""
            MATCH (f:Feature {{feature_id: $id}})
            OPTIONAL MATCH (f)-[:AFFECTS*1..{safe_depth}]->(affected:Feature)
            OPTIONAL MATCH (f)<-[:TESTS]-(tc:TestCase)
            OPTIONAL MATCH (affected)<-[:TESTS]-(affected_tc:TestCase)
            RETURN f, collect(DISTINCT affected) as affected_features,
                   collect(DISTINCT tc) as test_cases,
                   collect(DISTINCT affected_tc) as affected_test_cases
            """
        else:
            return "MATCH (n) WHERE n.id = $id RETURN n"
