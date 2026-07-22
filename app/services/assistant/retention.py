"""Assistant 背景維護 ticker（design；spec assistant-agent-loop「reconciliation」、
assistant-conversations「Retention 清理」、assistant-action-confirmation「at-most-once」）。

兩條獨立 asyncio 迴圈，模式仿 `app/services/automation/background.py`：
- recovery loop（預設 60s）：orphan turn／executing pending 收斂為終態、逾期 pending 標 expired。
  時效性較高——使用者體驗（確認卡是否還可操作）直接受影響，故頻率較快。
- purge loop（預設 600s）：過期對話／附檔／rate-limit bucket 清理，以及 runtime admission
  counter reconciliation。皆為維運性質，不需高頻。

每一輪迭代皆 best-effort：單輪例外只記錄，不中斷 ticker；由 `main.py` 的背景服務 leader
選舉啟動/停止（與 `automation_background_manager` 同一機制，避免多 worker 重複執行）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from app.config import AssistantConfig
from app.services.assistant import attachment_storage
from app.services.assistant.conversation_service import ConversationService

logger = logging.getLogger(__name__)

RECOVERY_INTERVAL_SECONDS = 60
PURGE_INTERVAL_SECONDS = 600


def _unlink_best_effort(relative_path: str) -> None:
    with contextlib.suppress(OSError, ValueError):
        attachment_storage.resolve_stored_path(relative_path).unlink(missing_ok=True)


class AssistantRetentionManager:
    """Owns the two background asyncio tasks for assistant recovery + retention."""

    def __init__(self, conversation_service: ConversationService) -> None:
        self._conversation_service = conversation_service
        self._tasks: list[asyncio.Task] = []
        self._stop_event: Optional[asyncio.Event] = None

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop_event = asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._recovery_loop(), name="assistant-recovery"),
            asyncio.create_task(self._purge_loop(), name="assistant-purge"),
        ]
        logger.info("Assistant retention ticker started")

    async def stop(self) -> None:
        if not self._tasks:
            return
        if self._stop_event:
            self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []
        logger.info("Assistant retention ticker stopped")

    async def _recovery_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self._run_recovery_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("assistant recovery loop iteration failed: %s", exc)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=RECOVERY_INTERVAL_SECONDS)

    async def _purge_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self._run_purge_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("assistant purge loop iteration failed: %s", exc)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=PURGE_INTERVAL_SECONDS)

    async def _run_recovery_once(self) -> None:
        svc = self._conversation_service
        recovered_turns = await svc.recover_orphan_turns()
        recovered_pending = await svc.recover_orphan_executing_pending()
        expired = await svc.expire_stale_pending()
        if recovered_turns or recovered_pending or expired:
            logger.info(
                "assistant recovery: orphan_turns=%d orphan_executing=%d expired_pending=%d",
                recovered_turns, recovered_pending, expired,
            )

    async def _run_purge_once(self) -> None:
        svc = self._conversation_service
        conv_files = await svc.purge_expired_conversations()
        for relative_path in conv_files:
            _unlink_best_effort(relative_path)
        upload_files = await svc.purge_expired_uploaded_files()
        for relative_path in upload_files:
            _unlink_best_effort(relative_path)
        purged_buckets = await svc.purge_expired_rate_limit_buckets()
        await svc.reconcile_admission_counters()
        if conv_files or upload_files or purged_buckets:
            logger.info(
                "assistant purge: expired_conversations=%d expired_uploads=%d expired_rate_buckets=%d",
                len(conv_files), len(upload_files), purged_buckets,
            )


_manager_singleton: Optional[AssistantRetentionManager] = None


def get_assistant_retention_manager(config: AssistantConfig) -> AssistantRetentionManager:
    global _manager_singleton
    if _manager_singleton is None:
        from app.db_access.main import get_main_access_boundary

        _manager_singleton = AssistantRetentionManager(ConversationService(get_main_access_boundary(), config))
    return _manager_singleton
