# Proposal: Cross-Team Knowledge RAG Retrieval Architecture

## Intent
Enable cross-team knowledge search and impact analysis for AI Assistant and QA AI Helper while maintaining strict Casbin authorization bounds (`allowed_team_ids`) and performance safety.

## Scope
- Support `allowed_team_ids: list[int]` in `KnowledgeRetrievalService` and `HybridSearchService`.
- Implement Dual-Route Retrieval (Primary Team Top-5 + Authorized Cross-Team Top-5).
- Restrict Cypher graph expansion to `MAX_HOPS=2` and `LIMIT 30` per node.
- Wrap RAG context in `<knowledge_source>` XML tags with team metadata.
- Update AI Assistant tools `search_knowledge` and `analyze_knowledge_impact`.

## Verification
- `openspec validate cross-team-rag --strict`
- `uv run pytest app/testsuite/test_knowledge_retrieval_service.py app/testsuite/test_tools_knowledge.py -q`
