# Tasks — integrate-knowledge-rag-engine

## Tasks

- [ ] Implement `KnowledgeRetrievalService` in `app/services/knowledge/retrieval_service.py` with team isolation, circuit breaker, semaphore, and safe truncation. <!-- id: 0 -->
- [ ] Implement AI Assistant knowledge tools in `app/services/assistant/tools_knowledge.py` and register in `tools_catalog.py`. <!-- id: 1 -->
- [ ] Integrate RAG grounding into QA AI Helper (`app/services/qa_ai_helper_service.py` & `planner.py`). <!-- id: 2 -->
- [ ] Implement unit and integration tests in `app/testsuite/test_knowledge_retrieval_service.py` and `app/testsuite/test_tools_knowledge.py`. <!-- id: 3 -->
- [ ] Validate OpenSpec change proposal with `openspec validate integrate-knowledge-rag-engine --strict`. <!-- id: 4 -->
