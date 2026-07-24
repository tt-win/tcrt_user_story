# Design: Cross-Team Knowledge RAG Retrieval Architecture (v2.0)

## Architecture Overview

1. **Casbin Authorization Bounds (`allowed_team_ids`)**:
   - `KnowledgeRetrievalService.search_knowledge` receives `allowed_team_ids: list[int] | None`.
   - If `allowed_team_ids` is specified, Qdrant payload filters use `MatchAny(key="team_id", keywords=allowed_team_ids)` and Neo4j Cypher uses `WHERE n.team_id IN $allowed_team_ids`.

2. **Dual-Route Retrieval (Primary Team + Authorized Cross-Team)**:
   - Route A: Query with `team_id == primary_team_id` for top-5 primary results.
   - Route B: Query with `team_id IN allowed_team_ids` (excluding `primary_team_id`) for top-5 cross-team results.
   - Deduplicate and merge results.

3. **Cypher Graph Safety**:
   - Limit graph traversals to 2 hops (`*1..2`).
   - Limit branch fan-out with `LIMIT 30`.

4. **XML Context & Anti-Blending**:
   - Wrap context entries in `<knowledge_source team_id="..." team_name="...">`.
