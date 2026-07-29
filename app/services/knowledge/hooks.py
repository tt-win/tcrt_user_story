"""Knowledge graph event hooks.

These are fire-and-forget enqueue helpers invoked from the TCRT CRUD
endpoints (test_cases, USM) right after a successful DB write.  When
the knowledge graph feature is enabled the enqueue returns True and
the in-memory ``KnowledgeSyncTaskQueue`` picks the task up on a
background worker; when disabled the no-op queue is returned and the
helper is a no-op.

Public API:
- ``enqueue_test_case_sync(test_case_number, operation='upsert')``
- ``enqueue_usm_node_sync(map_id, node_id, operation='upsert')``
- ``start_sync_workers()`` / ``stop_sync_workers()`` — lifecycle hooks
  to be wired into FastAPI ``app.on_event("startup")`` /
  ``"shutdown"`` so the background worker is up while the app serves
  requests.

Operation types: ``"upsert"`` (default) or ``"delete"``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.knowledge.usm_payload import usm_entity_key

LOGGER = logging.getLogger(__name__)


def _resolve_queue() -> Any:
    """Return the active task queue (real or null)."""
    from app.services.knowledge import get_task_queue
    return get_task_queue()


async def enqueue_test_case_sync(
    test_case_number: str,
    *,
    operation: str = "upsert",
    payload: Any = None,
) -> bool:
    """Trigger a Qdrant sync for one test case.

    Returns True if enqueued, False if deduped or feature disabled.
    Safe to call from any endpoint without try/except — the queue's
    worker logs and recovers from individual failures.

    ``payload`` is the full entity dict (with title, precondition, steps,
    expected_result, etc.) when available.  If omitted, the worker will
    still embed but the embedding text will be empty unless the write
    service is enhanced to fetch from the DB.  Callers should always
    pass the full entity when they have it (i.e. at the API CRUD call
    sites).
    """
    if not test_case_number:
        return False
    queue = _resolve_queue()
    try:
        return await queue.enqueue(
            entity_type="test_cases",
            entity_id=test_case_number,
            payload={"operation": operation, "entity": payload} if payload else {"operation": operation},
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "enqueue_test_case_sync(%s, op=%s) failed: %s",
            test_case_number, operation, exc,
        )
        return False


async def enqueue_usm_node_sync(
    map_id: int,
    node_id: str,
    *,
    operation: str = "upsert",
    payload: Any = None,
) -> bool:
    """Trigger a Qdrant sync for one USM node.

    Returns True if enqueued, False if deduped or feature disabled.

    ``payload`` is the full entity dict (with title, description,
    as_a, i_want, so_that, etc.) when available.
    """
    if map_id <= 0 or not node_id:
        return False
    entity_key = usm_entity_key(map_id, node_id)
    queue = _resolve_queue()
    try:
        return await queue.enqueue(
            entity_type="usm_nodes",
            entity_id=entity_key,
            payload={"operation": operation, "entity": payload} if payload else {"operation": operation},
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "enqueue_usm_node_sync(%s, op=%s) failed: %s",
            entity_key,
            operation,
            exc,
        )
        return False


async def enqueue_test_cases_bulk(
    test_case_numbers: list[str | dict[str, Any]],
    *,
    operation: str = "upsert",
) -> int:
    """Bulk enqueue test case syncs. Returns count successfully enqueued.

    Accepts a list of test case numbers (str) or full payload dicts (dict).
    """
    count = 0
    for item in test_case_numbers:
        if isinstance(item, dict):
            tcn = item.get("test_case_number") or item.get("number") or ""
            if await enqueue_test_case_sync(tcn, operation=operation, payload=item):
                count += 1
        elif isinstance(item, str):
            if await enqueue_test_case_sync(item, operation=operation):
                count += 1
    return count


async def enqueue_usm_nodes_bulk(
    node_ids: list[str | dict[str, Any]],
    *,
    map_id: int | None = None,
    operation: str = "upsert",
) -> int:
    """Bulk enqueue USM node syncs. Returns count successfully enqueued.

    Accepts a list of node IDs (str) or full payload dicts (dict).
    """
    count = 0
    for item in node_ids:
        if isinstance(item, dict):
            nid = item.get("node_id") or item.get("id") or ""
            item_map_id = int(item.get("map_id") or map_id or 0)
            if await enqueue_usm_node_sync(
                item_map_id,
                nid,
                operation=operation,
                payload=item,
            ):
                count += 1
        elif isinstance(item, str):
            if await enqueue_usm_node_sync(
                int(map_id or 0),
                item,
                operation=operation,
            ):
                count += 1
    return count


# ----- worker lifecycle -----


async def start_sync_workers() -> None:
    """Start the in-memory sync task queue workers. Idempotent."""
    from app.services.knowledge import (
        get_task_queue,
        get_write_service,
        is_knowledge_graph_enabled,
    )
    queue = get_task_queue()
    if not is_knowledge_graph_enabled():
        # Stop a real queue left by an earlier lifespan before the feature is
        # disabled.  get_task_queue() will return the null queue afterwards.
        await queue.stop()
        LOGGER.debug("start_sync_workers: knowledge graph disabled, skipping")
        return

    # Wire the worker to call write_service.write_entity with the
    # operation extracted from the payload.
    async def _handler(entity_type: str, entity_id: str, payload: Any) -> None:
        svc = get_write_service()
        if not isinstance(payload, dict):
            payload = {}
        operation = payload.get("operation", "upsert")
        # ``entity`` is the full entity dict when the caller had it;
        # otherwise the write service will only have the id and may
        # not produce any embedding text.
        entity = payload.get("entity")
        await svc.write_entity(
            entity_type, entity_id, payload=entity, operation=operation
        )

    queue.set_write_handler(_handler)
    await queue.start()
    LOGGER.info("Knowledge graph sync workers started")


async def stop_sync_workers() -> None:
    """Stop the in-memory sync task queue workers. Idempotent."""
    from app.services.knowledge import get_task_queue

    queue = get_task_queue()
    await queue.stop()
    LOGGER.info("Knowledge graph sync workers stopped")
