"""知識圖譜服務模組。

提供 Qdrant 寫入（TestCase / USM）、Neo4j 唯讀查詢、混合搜尋等能力。
所有 client 連線採用 lazy init 模式：第一次呼叫對應 getter 時建立，
不於 import 時建立（避免無設定時啟動失敗）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import KnowledgeGraphConfig, Settings, get_settings

if TYPE_CHECKING:
    from app.services.knowledge.embedding_service import EmbeddingService
    from app.services.knowledge.hybrid_search_service import HybridSearchService
    from app.services.knowledge.knowledge_write_service import KnowledgeWriteService
    from app.services.knowledge.neo4j_client import Neo4jClient
    from app.services.knowledge.qdrant_client import QdrantKnowledgeClient
    from app.services.knowledge.task_queue import KnowledgeSyncTaskQueue as _KnowledgeSyncTaskQueue
    from app.services.knowledge.task_queue import NullKnowledgeSyncTaskQueue  # noqa: F401
    KnowledgeSyncTaskQueue = _KnowledgeSyncTaskQueue  # explicit re-export

LOGGER = logging.getLogger(__name__)


def is_knowledge_graph_enabled(settings: Settings | None = None) -> bool:
    """判斷知識圖譜是否啟用（opt-in 檢查）。"""
    s = settings or get_settings()
    kg = s.knowledge_graph
    if not kg.enabled:
        return False
    if not kg.qdrant.url:
        LOGGER.warning("Knowledge graph enabled but QDRANT_URL not set; disabling")
        return False
    if kg.embedding.dimensions <= 0:
        LOGGER.warning("EMBEDDING_DIMENSIONS must be positive; disabling knowledge graph")
        return False
    if kg.embedding.provider == "openrouter" and not kg.embedding.api_key:
        LOGGER.warning("EMBEDDING_API_KEY required for openrouter provider; disabling knowledge graph")
        return False
    return True


def get_knowledge_graph_config() -> KnowledgeGraphConfig:
    return get_settings().knowledge_graph


# Singleton placeholders — populated on first use.
_qdrant_client: "QdrantKnowledgeClient | None" = None
_neo4j_client: "Neo4jClient | None" = None
_embedding_service: "EmbeddingService | None" = None
_write_service: "KnowledgeWriteService | None" = None
_hybrid_search: "HybridSearchService | None" = None
_retrieval_service: Any = None
_task_queue: Any = None  # Union[KnowledgeSyncTaskQueue, NullKnowledgeSyncTaskQueue]
_query_log_service: Any = None


def get_qdrant_client() -> "QdrantKnowledgeClient":
    global _qdrant_client
    if _qdrant_client is None:
        from app.services.knowledge.qdrant_client import QdrantKnowledgeClient

        _qdrant_client = QdrantKnowledgeClient(get_knowledge_graph_config().qdrant)
    return _qdrant_client


def get_neo4j_client() -> "Neo4jClient":
    global _neo4j_client
    if _neo4j_client is None:
        from app.services.knowledge.neo4j_client import Neo4jClient

        _neo4j_client = Neo4jClient(get_knowledge_graph_config().neo4j)
    return _neo4j_client


def get_embedding_service() -> "EmbeddingService":
    global _embedding_service
    if _embedding_service is None:
        from app.services.knowledge.embedding_service import EmbeddingService

        _embedding_service = EmbeddingService(get_knowledge_graph_config().embedding)
    return _embedding_service


def get_write_service() -> "KnowledgeWriteService":
    global _write_service
    if _write_service is None:
        from app.services.knowledge.knowledge_write_service import KnowledgeWriteService

        _write_service = KnowledgeWriteService(
            qdrant_client=get_qdrant_client(),
            embedding_service=get_embedding_service(),
            config=get_knowledge_graph_config(),
        )
    return _write_service


def get_hybrid_search() -> "HybridSearchService":
    global _hybrid_search
    if _hybrid_search is None:
        from app.services.knowledge.hybrid_search_service import HybridSearchService

        _hybrid_search = HybridSearchService(
            qdrant_client=get_qdrant_client(),
            neo4j_client=get_neo4j_client(),
            embedding_service=get_embedding_service(),
            config=get_knowledge_graph_config(),
        )
    return _hybrid_search


def get_retrieval_service() -> Any:
    global _retrieval_service
    if _retrieval_service is None:
        from app.services.knowledge.retrieval_service import KnowledgeRetrievalService

        _retrieval_service = KnowledgeRetrievalService()
    return _retrieval_service


def get_task_queue() -> Any:
    """取得 task queue。若知識圖譜停用，回傳 NullKnowledgeSyncTaskQueue。"""
    global _task_queue
    if _task_queue is None:
        if is_knowledge_graph_enabled():
            from app.services.knowledge.task_queue import KnowledgeSyncTaskQueue

            _task_queue = KnowledgeSyncTaskQueue(
                write_service_factory=get_write_service,
            )
        else:
            from app.services.knowledge.task_queue import NullKnowledgeSyncTaskQueue

            _task_queue = NullKnowledgeSyncTaskQueue()
    return _task_queue


def get_query_log_service() -> Any:
    """取得 knowledge_query_logs 寫入器 singleton（fail-safe 緩衝／批次 flush）。"""
    global _query_log_service
    if _query_log_service is None:
        from app.services.knowledge.query_log_service import KnowledgeQueryLogService

        _query_log_service = KnowledgeQueryLogService()
    return _query_log_service


def reset_singletons_for_test() -> None:
    """測試用：重置所有 singleton。"""
    global _qdrant_client, _neo4j_client, _embedding_service, _write_service, _hybrid_search, _retrieval_service, _task_queue, _query_log_service
    _qdrant_client = None
    _neo4j_client = None
    _embedding_service = None
    _write_service = None
    _hybrid_search = None
    _retrieval_service = None
    _task_queue = None
    _query_log_service = None

