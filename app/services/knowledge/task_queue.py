"""Knowledge Sync Task Queue.

事件驅動寫入 Qdrant 的 in-memory queue + 背景 worker。
Conditional activation：當知識圖譜停用時，回傳 NullKnowledgeSyncTaskQueue。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Protocol

LOGGER = logging.getLogger(__name__)


class _WriteTask(Protocol):
    entity_type: str
    entity_id: str


WriteServiceFactory = Callable[[], Any]


class KnowledgeSyncTaskQueue:
    """in-memory asyncio.Queue + 背景 worker，支援 dedup 與 graceful shutdown。"""

    def __init__(
        self,
        write_service_factory: WriteServiceFactory,
        *,
        worker_count: int = 1,
        shutdown_timeout: float = 30.0,
    ) -> None:
        self._factory = write_service_factory
        self._worker_count = worker_count
        self._shutdown_timeout = shutdown_timeout
        self._queue: asyncio.Queue[tuple[str, str, Any]] = asyncio.Queue()
        self._pending_keys: set[str] = set()
        self._pending_lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._write_handler: Callable[[str, str, Any], Awaitable[None]] | None = None

    def set_write_handler(self, handler: Callable[[str, str, Any], Awaitable[None]]) -> None:
        """設定實際寫入處理函式（由 KnowledgeWriteService 注入）。"""
        self._write_handler = handler

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self._worker_count):
            task = asyncio.create_task(self._worker_loop(i), name=f"kg-sync-worker-{i}")
            self._workers.append(task)
        LOGGER.info("KnowledgeSyncTaskQueue started with %d worker(s)", self._worker_count)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # 等待 queue 清空（在 timeout 內）
        try:
            await asyncio.wait_for(self._queue.join(), timeout=self._shutdown_timeout)
        except asyncio.TimeoutError:
            LOGGER.warning("Queue drain timed out after %.1fs, forcing stop", self._shutdown_timeout)
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass
        self._workers.clear()
        LOGGER.info("KnowledgeSyncTaskQueue stopped")

    async def enqueue(self, entity_type: str, entity_id: str, payload: Any = None) -> bool:
        """Enqueue a write task. Returns False if deduped (already pending).

        Dedup key includes the operation so that a delete is never dropped
        just because an upsert for the same entity is already pending
        (and vice versa).
        """
        operation = "upsert"
        if isinstance(payload, dict):
            operation = payload.get("operation", "upsert")
        key = f"{entity_type}:{entity_id}:{operation}"
        async with self._pending_lock:
            if key in self._pending_keys:
                LOGGER.debug("Dedup: %s already pending", key)
                return False
            self._pending_keys.add(key)
        await self._queue.put((entity_type, entity_id, payload))
        return True

    async def _worker_loop(self, worker_id: int) -> None:
        LOGGER.debug("kg-sync-worker-%d started", worker_id)
        while self._running:
            try:
                entity_type, entity_id, payload = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            # Reconstruct the full dedup key (includes operation) so that
            # pending_keys.discard correctly removes it.
            _payload_op = "upsert"
            if isinstance(payload, dict):
                _payload_op = payload.get("operation", "upsert")
            full_key = f"{entity_type}:{entity_id}:{_payload_op}"
            try:
                handler = self._write_handler
                if handler is not None:
                    await handler(entity_type, entity_id, payload)
                else:
                    # default: call write service (also used as fallback when
                    # start_sync_workers() was not called, e.g. in tests).
                    # Extract operation from the payload dict so delete tasks
                    # are not silently treated as upsert.
                    svc = self._factory()
                    write_fn = getattr(svc, "write_entity", None)
                    if write_fn is not None:
                        _op = "upsert"
                        _entity = payload
                        if isinstance(payload, dict):
                            _op = payload.get("operation", "upsert")
                            _entity = payload.get("entity")
                        await write_fn(entity_type, entity_id, payload=_entity, operation=_op)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Worker %d failed to process %s: %s", worker_id, full_key, exc)
            finally:
                async with self._pending_lock:
                    self._pending_keys.discard(full_key)
                self._queue.task_done()
        LOGGER.debug("kg-sync-worker-%d stopped", worker_id)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()


class NullKnowledgeSyncTaskQueue:
    """No-op queue used when knowledge graph is disabled."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, entity_type: str, entity_id: str, payload: Any = None) -> bool:
        return False

    def set_write_handler(self, handler: Callable[[str, str, Any], Awaitable[None]]) -> None:
        pass

    @property
    def queue_size(self) -> int:
        return 0
