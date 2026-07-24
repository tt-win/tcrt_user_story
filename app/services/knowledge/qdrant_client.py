"""Qdrant async client wrapper for knowledge graph.

提供 health check、upsert / search / scroll、multi-collection 支援。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import QdrantConfig

LOGGER = logging.getLogger(__name__)


class QdrantKnowledgeClient:
    """Qdrant client wrapper for knowledge graph (read + write)."""

    def __init__(self, config: QdrantConfig) -> None:
        self._config = config
        self._client: AsyncQdrantClient | None = None

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            client_kwargs: dict[str, Any] = {
                "url": self._config.url,
                "timeout": self._config.timeout,
                "prefer_grpc": self._config.prefer_grpc,
            }
            if self._config.api_key:
                client_kwargs["api_key"] = self._config.api_key
            if self._config.prefer_grpc and self._config.grpc_use_tls:
                if self._config.grpc_tls_ca_cert:
                    client_kwargs["grpc_options"] = {
                        "ssl_root_certificates": self._config.grpc_tls_ca_cert,
                    }
            self._client = AsyncQdrantClient(**client_kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Qdrant health check failed: %s", exc)
            return False

    async def list_collections(self) -> list[str]:
        """List all collection names. Returns [] on failure."""
        try:
            client = await self._get_client()
            response = await client.get_collections()
            return [c.name for c in response.collections]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("list_collections failed: %s", exc)
            return []

    async def get_collection_dimensions(self, collection: str) -> int | None:
        try:
            client = await self._get_client()
            info = await client.get_collection(collection_name=collection)
            return info.config.params.vectors.size  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to read collection %s dimensions: %s", collection, exc)
            return None

    async def collection_exists(self, collection: str) -> bool:
        try:
            client = await self._get_client()
            return await client.collection_exists(collection_name=collection)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("collection_exists(%s) failed: %s", collection, exc)
            return False

    async def collection_is_empty(self, collection: str) -> bool:
        try:
            client = await self._get_client()
            info = await client.get_collection(collection_name=collection)
            # 優先使用 indexed_vectors_count（若可用），否則 fallback 到 points_count
            count = getattr(info, "indexed_vectors_count", None) or getattr(info, "points_count", 0)
            return (count or 0) == 0
        except Exception:
            return True  # 不存在視為空

    async def create_collection(
        self,
        collection: str,
        vector_size: int,
        distance: qmodels.Distance = qmodels.Distance.COSINE,
        on_disk_payload: bool = True,
    ) -> None:
        client = await self._get_client()
        await client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=distance,
                on_disk=on_disk_payload,
            ),
        )
        LOGGER.info("Created Qdrant collection: %s (dim=%d)", collection, vector_size)

    async def ensure_collection(
        self,
        collection: str,
        vector_size: int,
        distance: qmodels.Distance = qmodels.Distance.COSINE,
    ) -> None:
        if not await self.collection_exists(collection):
            await self.create_collection(collection, vector_size, distance)

    async def upsert_points(
        self,
        collection: str,
        points: Iterable[qmodels.PointStruct],
    ) -> None:
        client = await self._get_client()
        await client.upsert(collection_name=collection, points=list(points), wait=True)

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 20,
        score_threshold: float | None = None,
        query_filter: qmodels.Filter | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search.

        Uses ``query_points`` (qdrant-client >=1.12); the legacy ``.search`` API
        was removed in recent clients and would raise AttributeError at runtime.
        """
        client = await self._get_client()
        # Prefer query_points (current API); fall back to search for older clients.
        if hasattr(client, "query_points"):
            response = await client.query_points(
                collection_name=collection,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )
            points = getattr(response, "points", None) or []
        else:
            points = await client.search(
                collection_name=collection,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False,
            )
        return [
            {"id": str(r.id), "score": r.score, "payload": r.payload or {}}
            for r in points
        ]

    async def scroll(
        self,
        collection: str,
        limit: int = 100,
        offset: Any | None = None,
        query_filter: qmodels.Filter | None = None,
        with_payload: bool = True,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        """Scroll a collection. Returns (points, next_offset)."""
        client = await self._get_client()
        records, next_offset = await client.scroll(
            collection_name=collection,
            limit=limit,
            offset=offset,
            scroll_filter=query_filter,
            with_payload=with_payload,
            with_vectors=False,
        )
        return (
            [{"id": str(r.id), "payload": r.payload or {}} for r in records],
            next_offset,
        )

    async def delete_by_filter(
        self,
        collection: str,
        query_filter: qmodels.Filter,
    ) -> None:
        client = await self._get_client()
        await client.delete(collection_name=collection, points_selector=query_filter, wait=True)
