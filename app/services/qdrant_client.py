"""
Qdrant 非同步客戶端服務

提供集中式、可重用的 Qdrant 連線管理：
- 單例化 AsyncQdrantClient（避免每次請求都新建連線）
- 可配置的連線池、並發上限、逾時與重試
- 明確的 startup/shutdown 生命週期
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, TypeVar

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models

from app.config import QdrantConfig, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class QdrantClientService:
    """集中式 Qdrant Client 管理器（async）。"""

    def __init__(self, config: Optional[QdrantConfig] = None):
        settings = get_settings()
        self.config = config or settings.qdrant
        self._client: Optional[AsyncQdrantClient] = None
        self._init_lock = asyncio.Lock()
        self._request_semaphore = asyncio.Semaphore(
            max(1, self.config.max_concurrent_requests)
        )

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is not None:
            return self._client

        async with self._init_lock:
            if self._client is not None:
                return self._client

            init_kwargs: Dict[str, Any] = {
                "url": self.config.url,
                "timeout": self.config.timeout,
                "prefer_grpc": self.config.prefer_grpc,
                "check_compatibility": self.config.check_compatibility,
            }
            if self.config.api_key:
                init_kwargs["api_key"] = self.config.api_key
            if self.config.pool_size > 0:
                init_kwargs["pool_size"] = self.config.pool_size

            self._client = AsyncQdrantClient(**init_kwargs)
            logger.info(
                "Qdrant client 初始化完成: url=%s, pool_size=%s, max_concurrent_requests=%s",
                self.config.url,
                self.config.pool_size,
                self.config.max_concurrent_requests,
            )

        return self._client

    async def _call_with_retry(
        self,
        operation_name: str,
        operation: Callable[[AsyncQdrantClient], Awaitable[T]],
    ) -> T:
        max_retries = max(1, self.config.max_retries)
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                client = await self._get_client()
                async with self._request_semaphore:
                    return await operation(client)
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    logger.error(
                        "Qdrant %s 失敗（重試 %s 次後放棄）: %s",
                        operation_name,
                        max_retries,
                        exc,
                    )
                    raise

                backoff = min(
                    self.config.retry_backoff_seconds * (2 ** (attempt - 1)),
                    self.config.retry_backoff_max_seconds,
                )
                logger.warning(
                    "Qdrant %s 失敗（第 %s/%s 次）: %s，%.2f 秒後重試",
                    operation_name,
                    attempt,
                    max_retries,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)

        if last_error:
            raise last_error
        raise RuntimeError(f"Qdrant {operation_name} 失敗")

    async def health_check(self) -> bool:
        """檢查 Qdrant 可用性（不拋異常）。"""
        try:
            await self._call_with_retry(
                "health_check",
                lambda client: client.get_collections(),
            )
            return True
        except Exception:
            return False

    async def query_points(
        self,
        *,
        collection_name: str,
        query: Any,
        limit: int,
        query_filter: Optional[qdrant_models.Filter] = None,
        with_payload: Any = True,
        with_vectors: bool | Sequence[str] = False,
        score_threshold: Optional[float] = None,
        timeout: Optional[int] = None,
    ) -> qdrant_models.QueryResponse:
        """查詢相似向量點。"""

        async def _run(client: AsyncQdrantClient) -> qdrant_models.QueryResponse:
            return await client.query_points(
                collection_name=collection_name,
                query=query,
                query_filter=query_filter,
                limit=limit,
                with_payload=with_payload,
                with_vectors=with_vectors,
                score_threshold=score_threshold,
                timeout=timeout,
            )

        return await self._call_with_retry("query_points", _run)

    async def retrieve(
        self,
        *,
        collection_name: str,
        point_ids: Sequence[Any],
        with_payload: Any = True,
        with_vectors: bool | Sequence[str] = False,
        timeout: Optional[int] = None,
    ) -> list[qdrant_models.Record]:
        """依 ID 讀取 Qdrant points。"""

        async def _run(client: AsyncQdrantClient) -> list[qdrant_models.Record]:
            return await client.retrieve(
                collection_name=collection_name,
                ids=point_ids,
                with_payload=with_payload,
                with_vectors=with_vectors,
                timeout=timeout,
            )

        return await self._call_with_retry("retrieve", _run)

    async def query_similar_context(
        self,
        embedding: Sequence[float],
        query_filter: Optional[qdrant_models.Filter] = None,
        test_case_limit: Optional[int] = None,
        usm_limit: Optional[int] = None,
    ) -> Dict[str, list[qdrant_models.ScoredPoint]]:
        """
        以既有雙集合策略查詢上下文（test_cases + usm_nodes）。
        回傳結構對齊目前 PoC 的使用方式，方便後續整合 helper 流程。
        """
        vector = list(embedding)
        tc_limit = test_case_limit or self.config.limit.test_cases
        usm_nodes_limit = usm_limit or self.config.limit.usm_nodes

        tc_task = self.query_points(
            collection_name=self.config.collection_test_cases,
            query=vector,
            query_filter=query_filter,
            limit=tc_limit,
            with_payload=True,
            with_vectors=False,
        )
        usm_task = self.query_points(
            collection_name=self.config.collection_usm_nodes,
            query=vector,
            query_filter=query_filter,
            limit=usm_nodes_limit,
            with_payload=True,
            with_vectors=False,
        )

        tc_response, usm_response = await asyncio.gather(tc_task, usm_task)
        return {
            "test_cases": tc_response.points or [],
            "usm_nodes": usm_response.points or [],
        }

    async def query_jira_referances_context(
        self,
        embedding: Sequence[float],
        query_filter: Optional[qdrant_models.Filter] = None,
        limit: Optional[int] = None,
    ) -> list[qdrant_models.ScoredPoint]:
        """
        以 jira_references 集合查詢需求分析所需的相似案例上下文。
        """
        vector = list(embedding)
        target_limit = limit or self.config.limit.jira_referances
        response = await self.query_points(
            collection_name=self.config.collection_jira_referances,
            query=vector,
            query_filter=query_filter,
            limit=target_limit,
            with_payload=True,
            with_vectors=False,
        )
        return response.points or []

    async def query_test_cases_context(
        self,
        embedding: Sequence[float],
        query_filter: Optional[qdrant_models.Filter] = None,
        limit: Optional[int] = None,
    ) -> list[qdrant_models.ScoredPoint]:
        """
        以 test_cases 集合查詢 testcase 產生/審查所需的相似案例上下文。
        """
        vector = list(embedding)
        target_limit = limit or self.config.limit.test_cases
        response = await self.query_points(
            collection_name=self.config.collection_test_cases,
            query=vector,
            query_filter=query_filter,
            limit=target_limit,
            with_payload=True,
            with_vectors=False,
        )
        return response.points or []

    async def close(self) -> None:
        """關閉 Qdrant client，釋放長連線資源。"""
        async with self._init_lock:
            if self._client is None:
                return

            try:
                await self._client.close()
                logger.info("Qdrant client 已關閉")
            finally:
                self._client = None


_qdrant_client_service: Optional[QdrantClientService] = None


def get_qdrant_client() -> QdrantClientService:
    """取得全域 Qdrant client 服務（單例）。"""
    global _qdrant_client_service
    if _qdrant_client_service is None:
        _qdrant_client_service = QdrantClientService()
    return _qdrant_client_service


async def close_qdrant_client() -> None:
    """關閉全域 Qdrant client 服務。"""
    global _qdrant_client_service
    if _qdrant_client_service is None:
        return

    await _qdrant_client_service.close()
    _qdrant_client_service = None
