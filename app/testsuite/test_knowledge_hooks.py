"""Tests for knowledge graph event hooks and the new delete methods.

Covers:
- delete_test_case / delete_usm_node (Qdrant delete-by-filter)
- enqueue_test_case_sync / enqueue_usm_node_sync (hooks layer)
- start_sync_workers / stop_sync_workers (worker lifecycle)
- write_entity operation="delete" dispatch
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import (
    EmbeddingConfig,
    KnowledgeGraphConfig,
    QdrantConfig,
)
from app.services.knowledge.knowledge_write_service import KnowledgeWriteService


def _make_svc() -> tuple[KnowledgeWriteService, AsyncMock]:
    cfg = KnowledgeGraphConfig(
        enabled=True,
        qdrant=QdrantConfig(
            url="http://localhost:6333",
            collection_test_cases="t1",
            collection_usm_nodes="u1",
        ),
        embedding=EmbeddingConfig(
            model="m",
            dimensions=4,
            provider="openai",
            base_url="https://x.example.com/v1",
            api_key="k",
            cache_path="",  # disable SQLite
        ),
    )
    fake_qdrant = AsyncMock()
    fake_qdrant.delete_by_filter = AsyncMock()
    fake_embed = AsyncMock()
    svc = KnowledgeWriteService(
        qdrant_client=fake_qdrant,  # type: ignore[arg-type]
        embedding_service=fake_embed,  # type: ignore[arg-type]
        config=cfg,
    )
    return svc, fake_qdrant


# ---- delete_test_case ----


@pytest.mark.asyncio
async def test_delete_test_case_calls_qdrant_with_filter() -> None:
    svc, fake_qdrant = _make_svc()
    await svc.delete_test_case("TCG-001.001.001")
    fake_qdrant.delete_by_filter.assert_called_once()
    call_args = fake_qdrant.delete_by_filter.await_args
    assert call_args.kwargs["collection"] == "t1"
    flt = call_args.kwargs["query_filter"]
    # Verify filter structure
    assert flt.must[0].key == "test_case_number"
    assert flt.must[0].match.value == "TCG-001.001.001"


@pytest.mark.asyncio
async def test_delete_test_case_empty_string_is_noop() -> None:
    """Empty test_case_number is a no-op (don't blow up on bad data)."""
    svc, fake_qdrant = _make_svc()
    await svc.delete_test_case("")
    fake_qdrant.delete_by_filter.assert_not_called()


# ---- delete_usm_node ----


@pytest.mark.asyncio
async def test_delete_usm_node_calls_qdrant_with_filter() -> None:
    svc, fake_qdrant = _make_svc()
    await svc.delete_usm_node("usm-1.1")
    call_args = fake_qdrant.delete_by_filter.await_args
    assert call_args.kwargs["collection"] == "u1"
    flt = call_args.kwargs["query_filter"]
    assert flt.must[0].key == "node_id"
    assert flt.must[0].match.value == "usm-1.1"


@pytest.mark.asyncio
async def test_delete_usm_node_empty_string_is_noop() -> None:
    svc, fake_qdrant = _make_svc()
    await svc.delete_usm_node("")
    fake_qdrant.delete_by_filter.assert_not_called()


# ---- write_entity dispatch on operation="delete" ----


@pytest.mark.asyncio
async def test_write_entity_delete_dispatches_to_test_case() -> None:
    svc, fake_qdrant = _make_svc()
    await svc.write_entity("test_cases", "TCG-X", operation="delete")
    fake_qdrant.delete_by_filter.assert_called_once()
    assert fake_qdrant.delete_by_filter.await_args.kwargs["collection"] == "t1"


@pytest.mark.asyncio
async def test_write_entity_delete_dispatches_to_usm() -> None:
    svc, fake_qdrant = _make_svc()
    await svc.write_entity("usm_nodes", "usm-1", operation="delete")
    fake_qdrant.delete_by_filter.assert_called_once()
    assert fake_qdrant.delete_by_filter.await_args.kwargs["collection"] == "u1"


@pytest.mark.asyncio
async def test_write_entity_unknown_entity_type_is_warning() -> None:
    """Unknown entity types must not raise — they're a warning, not an error."""
    svc, fake_qdrant = _make_svc()
    # Should not raise
    await svc.write_entity("nonsense", "x", payload={"operation": "delete"})


# ---- task_queue default path: operation extracted from payload ----


@pytest.mark.asyncio
async def test_task_queue_default_path_delete_calls_delete_entity() -> None:
    """Bug #2 regression: worker default path (no handler) must extract
    operation='delete' from payload and NOT treat delete as upsert."""
    from app.services.knowledge.task_queue import KnowledgeSyncTaskQueue

    svc, fake_qdrant = _make_svc()
    queue = KnowledgeSyncTaskQueue(write_service_factory=lambda: svc)
    # Do NOT set a write handler — exercise the default path
    await queue.start()
    try:
        await queue.enqueue(
            entity_type="test_cases",
            entity_id="TCG-DEL-001",
            payload={"operation": "delete"},
        )
        await asyncio.wait_for(queue._queue.join(), timeout=3.0)
    finally:
        await queue.stop()

    # delete_by_filter should have been called (not upsert_points)
    fake_qdrant.delete_by_filter.assert_called_once()
    fake_qdrant.upsert_points.assert_not_called()


@pytest.mark.asyncio
async def test_task_queue_dedup_key_separates_upsert_and_delete() -> None:
    """Bug #4 regression: upsert and delete for the same entity must NOT
    dedup each other — both should be enqueued."""
    from app.services.knowledge.task_queue import KnowledgeSyncTaskQueue

    received: list[str] = []

    async def _handler(entity_type: str, entity_id: str, payload: Any) -> None:
        op = (payload or {}).get("operation", "upsert")
        received.append(op)
        await asyncio.sleep(0)  # yield

    svc, _ = _make_svc()
    queue = KnowledgeSyncTaskQueue(write_service_factory=lambda: svc)
    queue.set_write_handler(_handler)
    await queue.start()
    try:
        r1 = await queue.enqueue("test_cases", "TCG-1", payload={"operation": "upsert"})
        r2 = await queue.enqueue("test_cases", "TCG-1", payload={"operation": "delete"})
        await asyncio.wait_for(queue._queue.join(), timeout=3.0)
    finally:
        await queue.stop()

    assert r1 is True, "upsert should be enqueued"
    assert r2 is True, "delete should also be enqueued (different dedup key)"
    assert "upsert" in received
    assert "delete" in received



# ---- hooks module: enqueue_test_case_sync ----


@pytest.mark.asyncio
async def test_enqueue_test_case_sync_returns_false_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When knowledge graph is disabled, the hook must be a no-op."""
    import app.services.knowledge as kg_module

    # Reset singleton
    monkeypatch.setattr(kg_module, "_task_queue", None)
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: False)

    from app.services.knowledge.hooks import enqueue_test_case_sync

    enqueued = await enqueue_test_case_sync("TCG-001")
    assert enqueued is False


@pytest.mark.asyncio
async def test_enqueue_test_case_sync_enqueues_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When KG enabled, enqueue_test_case_sync must call queue.enqueue."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: True)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)

    # Reload hooks module to pick up the patched get_task_queue
    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    enqueued = await hooks.enqueue_test_case_sync("TCG-001")
    assert enqueued is True
    fake_queue.enqueue.assert_called_once()
    # The payload should include the operation
    call = fake_queue.enqueue.await_args
    assert call.kwargs["entity_type"] == "test_cases"
    assert call.kwargs["entity_id"] == "TCG-001"
    assert call.kwargs["payload"]["operation"] == "upsert"

    # Restore original
    importlib.reload(hooks)


@pytest.mark.asyncio
async def test_enqueue_test_case_sync_delete_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """operation='delete' is encoded in the payload."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: True)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    enqueued = await hooks.enqueue_test_case_sync("TCG-001", operation="delete")
    assert enqueued is True
    assert fake_queue.enqueue.await_args.kwargs["payload"]["operation"] == "delete"

    importlib.reload(hooks)


@pytest.mark.asyncio
async def test_enqueue_test_case_sync_empty_id_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty test_case_number is a no-op (don't pollute the queue)."""
    from app.services.knowledge.hooks import enqueue_test_case_sync

    assert await enqueue_test_case_sync("") is False
    assert await enqueue_test_case_sync("", operation="delete") is False


# ---- hooks module: enqueue_usm_node_sync ----


@pytest.mark.asyncio
async def test_enqueue_usm_node_sync_enqueues_with_correct_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """USM hook uses entity_type='usm_nodes' and the node_id as id."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: True)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    enqueued = await hooks.enqueue_usm_node_sync("usm-1.1", operation="delete")
    assert enqueued is True
    call = fake_queue.enqueue.await_args
    assert call.kwargs["entity_type"] == "usm_nodes"
    assert call.kwargs["entity_id"] == "usm-1.1"
    assert call.kwargs["payload"]["operation"] == "delete"

    importlib.reload(hooks)


# ---- bulk helpers ----


@pytest.mark.asyncio
async def test_enqueues_bulk_test_cases_calls_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk helper enqueues each id and returns the success count."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    # First 2 succeed, third dedupes
    fake_queue.enqueue = AsyncMock(side_effect=[True, True, False, True])
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: True)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    count = await hooks.enqueue_test_cases_bulk(["a", "b", "c", "d"])
    assert count == 3
    assert fake_queue.enqueue.await_count == 4

    importlib.reload(hooks)


@pytest.mark.asyncio
async def test_enqueues_bulk_test_cases_with_dict_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bulk helper handles dict items with payload correctly."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: True)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    items = [
        {"test_case_number": "TC-001", "title": "Title 1", "steps": "Step 1"},
        {"test_case_number": "TC-002", "title": "Title 2", "steps": "Step 2"},
    ]
    count = await hooks.enqueue_test_cases_bulk(items)
    assert count == 2
    assert fake_queue.enqueue.await_count == 2
    calls = fake_queue.enqueue.call_args_list
    assert calls[0].kwargs["payload"] == {"operation": "upsert", "entity": items[0]}
    assert calls[1].kwargs["payload"] == {"operation": "upsert", "entity": items[1]}

    importlib.reload(hooks)


# ---- worker lifecycle ----


@pytest.mark.asyncio
async def test_start_sync_workers_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start_sync_workers must not raise when KG is disabled."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.start = AsyncMock()
    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: False)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)
    monkeypatch.setattr(kg_module, "get_write_service", lambda: MagicMock())

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    await hooks.start_sync_workers()
    fake_queue.start.assert_not_called()

    importlib.reload(hooks)


@pytest.mark.asyncio
async def test_start_sync_workers_wires_handler_and_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When enabled, start_sync_workers must set the write handler and call start()."""
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.set_write_handler = MagicMock()
    fake_queue.start = AsyncMock()

    captured_handler = {}

    def _capture(handler):
        captured_handler["handler"] = handler

    fake_queue.set_write_handler.side_effect = _capture

    fake_write = MagicMock()
    fake_write.write_entity = AsyncMock()

    monkeypatch.setattr(kg_module, "is_knowledge_graph_enabled", lambda: True)
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)
    monkeypatch.setattr(kg_module, "get_write_service", lambda: fake_write)

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    await hooks.start_sync_workers()
    fake_queue.set_write_handler.assert_called_once()
    fake_queue.start.assert_called_once()

    # Verify the handler dispatches to write_entity with operation
    handler = captured_handler["handler"]
    await handler("test_cases", "TCG-001", {"operation": "delete"})
    fake_write.write_entity.assert_called_once_with(
        "test_cases", "TCG-001", payload=None, operation="delete"
    )

    importlib.reload(hooks)


@pytest.mark.asyncio
async def test_stop_sync_workers_calls_queue_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.knowledge as kg_module

    fake_queue = AsyncMock()
    fake_queue.stop = AsyncMock()
    monkeypatch.setattr(kg_module, "_task_queue", fake_queue)
    monkeypatch.setattr(kg_module, "get_task_queue", lambda: fake_queue)

    import importlib
    from app.services.knowledge import hooks
    importlib.reload(hooks)

    await hooks.stop_sync_workers()
    fake_queue.stop.assert_called_once()

    importlib.reload(hooks)
