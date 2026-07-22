"""Per-process turn runner 監督器（design D4/D7）。

runner 由此監督器管理、獨立於任何單一 HTTP 請求或 `StreamingResponse` generator 的生命週期；
SSE 訂閱者斷線只結束該訂閱者，不影響仍在背景執行的 runner（見 spec assistant-agent-loop
「SSE 事件協定、detached runner 與跨 worker 續傳」）。另提供 non-blocking 的 per-worker 名額限制
（`max_active_turns_per_worker`），本機 slot 不足時 MUST NOT 建立 turn。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


class ProcessSlotLimiter:
    """non-blocking 的 per-process 併發上限（不可用 asyncio.Semaphore 的 blocking acquire）。"""

    def __init__(self, limit: int):
        self._limit = limit
        self._count = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._count >= self._limit:
                return False
            self._count += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def in_use(self) -> int:
        return self._count


class RunnerSupervisor:
    def __init__(self, limit: int):
        self._limiter = ProcessSlotLimiter(limit)
        self._tasks: dict[str, asyncio.Task] = {}

    async def try_start(self, turn_key: str, coro_factory: Callable[[], Awaitable[None]]) -> bool:
        """取得本機 slot 並啟動 runner；slot 不足回 False（呼叫端應回 429/503，不建立 turn）。"""
        if not await self._limiter.try_acquire():
            return False
        self.spawn_reserved(turn_key, coro_factory)
        return True

    async def try_reserve_slot(self) -> bool:
        """僅取得本機 slot，不啟動 runner（呼叫端需在確定要新建 turn 前先取得名額；
        若確定不需要啟動 runner——例如冪等重播命中既有 turn——MUST 呼叫 `release_slot()`）。"""
        return await self._limiter.try_acquire()

    async def release_slot(self) -> None:
        """釋放一個以 `try_reserve_slot()` 取得、但最終未用於啟動 runner 的 slot。"""
        await self._limiter.release()

    def spawn_reserved(self, turn_key: str, coro_factory: Callable[[], Awaitable[None]]) -> None:
        """在已透過 `try_reserve_slot()` 取得 slot 的前提下啟動 runner（不再重複 acquire）。"""

        async def _wrapper() -> None:
            try:
                await coro_factory()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "assistant runner crashed turn_key=%s error_type=%s",
                    turn_key,
                    type(exc).__name__,
                )
            finally:
                self._tasks.pop(turn_key, None)
                await self._limiter.release()

        task = asyncio.create_task(_wrapper(), name=f"assistant-turn-{turn_key}")
        self._tasks[turn_key] = task

    def is_running(self, turn_key: str) -> bool:
        return turn_key in self._tasks

    @property
    def slots_in_use(self) -> int:
        return self._limiter.in_use


_supervisor_singleton: Optional[RunnerSupervisor] = None


def get_runner_supervisor(limit: int) -> RunnerSupervisor:
    global _supervisor_singleton
    if _supervisor_singleton is None:
        _supervisor_singleton = RunnerSupervisor(limit)
    return _supervisor_singleton
