"""Neo4j async driver wrapper (read-only) for knowledge graph.

TCRT 對 Neo4j 僅做唯讀查詢（graph traversal）。
所有 write / schema 管理由獨立服務 `qa_knowledge_graph` 負責。
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import Neo4jConfig

LOGGER = logging.getLogger(__name__)


class Neo4jClient:
    """Read-only Neo4j client wrapper for graph traversal queries."""

    def __init__(self, config: Neo4jConfig) -> None:
        self._config = config
        self._driver: AsyncDriver | None = None

    async def _get_driver(self) -> AsyncDriver:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self._config.uri,
                auth=(self._config.username, self._config.password) if self._config.password else None,
                max_connection_pool_size=self._config.max_connection_pool_size,
                connection_timeout=self._config.connection_timeout,
            )
        return self._driver

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def health_check(self) -> bool:
        try:
            driver = await self._get_driver()
            async with driver.session(database=self._config.database) as session:
                result = await session.run("RETURN 1 AS ok")
                record = await result.single()
                return record is not None and record.get("ok") == 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Neo4j health check failed: %s", exc)
            return False

    async def execute_read(self, cypher: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only Cypher query and return records as list of dicts."""
        driver = await self._get_driver()
        async with driver.session(database=self._config.database) as session:
            result = await session.run(cypher, parameters or {})
            records = []
            async for record in result:
                records.append(dict(record))
            return records

    async def execute_read_single(self, cypher: str, parameters: dict[str, Any] | None = None) -> dict[str, Any] | None:
        results = await self.execute_read(cypher, parameters)
        return results[0] if results else None
