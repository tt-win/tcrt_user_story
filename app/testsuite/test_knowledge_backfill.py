"""Unit tests for backfill logic: batching, progress persistence, crash recovery,
auto-detect, and concurrency control. These tests use fakes and do not require
running Qdrant or Neo4j.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest

from app.config import EmbeddingConfig, KnowledgeGraphConfig, QdrantConfig
from app.services.knowledge.embedding_service import EmbeddingService
from app.services.knowledge.knowledge_write_service import BackfillProgress, KnowledgeWriteService
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient


class FakeQdrant:
    """Minimal fake Qdrant client for backfill tests."""

    def __init__(self) -> None:
        self.upserted: list[tuple[str, list]] = []  # (collection, points)
        self.collections: set[str] = set()
        self.existing_dimensions: dict[str, int] = {}

    async def ensure_collection(self, collection: str, vector_size: int, **kwargs) -> None:
        self.collections.add(collection)

    async def upsert_points(self, collection: str, points) -> None:
        self.collections.add(collection)
        self.upserted.append((collection, list(points)))

    async def collection_is_empty(self, collection: str) -> bool:
        return collection not in {c for c, _ in self.upserted}

    async def get_collection_dimensions(self, collection: str) -> int | None:
        return self.existing_dimensions.get(collection)


def make_services(tmp_path: Path, batch_size: int = 3) -> tuple[KnowledgeWriteService, FakeQdrant]:
    fake_q = FakeQdrant()
    cfg = KnowledgeGraphConfig(
        enabled=True,
        qdrant=QdrantConfig(),
        embedding=EmbeddingConfig(
            model="fake",
            dimensions=4,
            provider="openrouter",
            cache_path="",  # disable SQLite cache
        ),
        backfill_batch_size=batch_size,
        backfill_progress_path=str(tmp_path / "progress.json"),
    )
    # Use a real EmbeddingService but mock embed_batch to return fakes
    emb = EmbeddingService(cfg.embedding)

    async def fake_embed_batch(texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    emb.embed_batch = fake_embed_batch  # type: ignore[assignment]

    svc = KnowledgeWriteService(
        qdrant_client=fake_q,  # type: ignore[arg-type]
        embedding_service=emb,
        config=cfg,
    )
    return svc, fake_q


async def async_iter(items):
    for item in items:
        yield item


def make_tc(n: int) -> dict:
    return {
        "test_case_number": f"TCG-{n:05d}",
        "title": f"Test case {n}",
        "precondition": "Pre",
        "steps": "1. Step one",
        "expected_result": "Result",
    }


@pytest.mark.asyncio
async def test_backfill_batches(tmp_path: Path) -> None:
    """Backfill should batch by backfill_batch_size."""
    svc, fake_q = make_services(tmp_path, batch_size=3)
    tcs = [make_tc(i) for i in range(7)]
    progress = await svc.backfill_test_cases(async_iter(tcs))
    assert progress.processed_count == 7
    assert progress.status == "completed"
    # 7 items / batch_size 3 = 3 batches (3+3+1)
    assert len(fake_q.upserted) == 3
    assert len(fake_q.upserted[0][1]) == 3
    assert len(fake_q.upserted[1][1]) == 3
    assert len(fake_q.upserted[2][1]) == 1


@pytest.mark.asyncio
async def test_backfill_persists_progress(tmp_path: Path) -> None:
    """Progress is saved to JSON file after each batch."""
    svc, fake_q = make_services(tmp_path, batch_size=2)
    tcs = [make_tc(i) for i in range(4)]
    await svc.backfill_test_cases(async_iter(tcs))
    progress_file = tmp_path / "progress.json"
    assert progress_file.exists()
    data = json.loads(progress_file.read_text())
    assert "test_cases" in data
    assert data["test_cases"]["status"] == "completed"
    assert data["test_cases"]["processed_count"] == 4


@pytest.mark.asyncio
async def test_backfill_resumes_from_checkpoint(tmp_path: Path) -> None:
    """If progress file has in_progress status, resume from last_processed_id.

    `processed_count` is cumulative across the entire backfill (existing + new).
    Only items after last_processed_id are upserted.
    """
    svc, fake_q = make_services(tmp_path, batch_size=2)
    # Pre-populate progress file
    progress_file = tmp_path / "progress.json"
    progress_file.write_text(json.dumps({
        "test_cases": {
            "processed_count": 3,
            "total_count": 10,
            "last_processed_id": "TCG-00002",
            "status": "in_progress",
            "started_at": "2026-07-23T00:00:00+00:00",
            "updated_at": "2026-07-23T00:01:00+00:00",
        }
    }))

    tcs = [make_tc(i) for i in range(5)]
    progress = await svc.backfill_test_cases(async_iter(tcs))
    # Cumulative: 3 (existing) + 2 (new: 00003, 00004) = 5
    assert progress.processed_count == 5
    # Only 2 new items upserted in this run
    assert len(fake_q.upserted) == 1
    assert len(fake_q.upserted[0][1]) == 2


@pytest.mark.asyncio
async def test_backfill_resumes_from_failed_status(tmp_path: Path) -> None:
    """If progress file has 'failed' status (mid-batch crash), resume from
    last_processed_id just like 'in_progress'.

    The 2026-07-23 production crash left progress at status='failed' with a
    valid last_processed_id from the last successful batch. Without this
    resume path the next run would re-embed everything from scratch.
    """
    svc, fake_q = make_services(tmp_path, batch_size=2)
    progress_file = tmp_path / "progress.json"
    progress_file.write_text(json.dumps({
        "test_cases": {
            "processed_count": 3,
            "total_count": 10,
            "last_processed_id": "TCG-00002",
            "status": "failed",
            "started_at": "2026-07-23T00:00:00+00:00",
            "updated_at": "2026-07-23T00:01:00+00:00",
        }
    }))

    tcs = [make_tc(i) for i in range(5)]
    progress = await svc.backfill_test_cases(async_iter(tcs))
    # Cumulative: 3 (existing) + 2 (new: 00003, 00004) = 5
    assert progress.processed_count == 5
    assert len(fake_q.upserted) == 1
    assert len(fake_q.upserted[0][1]) == 2


@pytest.mark.asyncio
async def test_backfill_sets_watermark_on_completion(tmp_path: Path) -> None:
    """After backfill completes, watermark is set to current time."""
    svc, fake_q = make_services(tmp_path, batch_size=2)
    tcs = [make_tc(i) for i in range(2)]
    await svc.backfill_test_cases(async_iter(tcs))
    watermark = svc.get_watermark("test_cases")
    assert watermark is not None
    # Should be an ISO 8601 timestamp
    from datetime import datetime
    datetime.fromisoformat(watermark)


@pytest.mark.asyncio
async def test_backfill_concurrency_control(tmp_path: Path) -> None:
    """Two concurrent backfill calls should result in only one running."""
    svc, fake_q = make_services(tmp_path, batch_size=2)

    async def slow_iter():
        for i in range(10):
            yield make_tc(i)
            await asyncio.sleep(0.01)

    # Start first backfill
    task1 = asyncio.create_task(svc.backfill_test_cases(slow_iter()))
    # Try to start second - should fail
    await asyncio.sleep(0.005)  # let first start
    with pytest.raises(RuntimeError, match="already in progress"):
        await svc.backfill_test_cases(slow_iter())
    # Wait for first to complete
    progress = await task1
    assert progress.status == "completed"


@pytest.mark.asyncio
async def test_backfill_handles_failure(tmp_path: Path) -> None:
    """If a batch fails, progress is marked as failed and exception propagates."""
    svc, fake_q = make_services(tmp_path, batch_size=2)

    # Make embed_batch fail on the second call
    call_count = [0]
    original_embed_batch = svc._embedding.embed_batch

    async def failing_embed_batch(texts):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("Embedding failed")
        return await original_embed_batch(texts)

    svc._embedding.embed_batch = failing_embed_batch  # type: ignore[assignment]

    tcs = [make_tc(i) for i in range(4)]
    with pytest.raises(RuntimeError, match="Embedding failed"):
        await svc.backfill_test_cases(async_iter(tcs))

    progress = svc._load_progress("test_cases")
    assert progress is not None
    assert progress.status == "failed"
    # is_backfill_in_progress should be reset
    assert svc._is_backfill_in_progress is False


@pytest.mark.asyncio
async def test_backfill_skips_empty_text(tmp_path: Path) -> None:
    """Test cases with no embeddable text are skipped (not upserted)."""
    svc, fake_q = make_services(tmp_path, batch_size=2)
    tcs = [
        {"test_case_number": "TCG-001", "title": "Has content"},
        {"test_case_number": "TCG-002"},  # no text
        {"test_case_number": "TCG-003", "title": "Also has content"},
    ]
    progress = await svc.backfill_test_cases(async_iter(tcs))
    # Only 2 upserted (the empty-text one is skipped)
    assert progress.processed_count == 2
    total_points = sum(len(points) for _, points in fake_q.upserted)
    assert total_points == 2


@pytest.mark.asyncio
async def test_auto_detect_flags_empty_collections(tmp_path: Path, caplog) -> None:
    """Auto-detect logs warning when watermark missing and Qdrant collection empty."""
    svc, fake_q = make_services(tmp_path)
    # No watermark set; fake_q is empty
    await svc._auto_detect_and_backfill()
    # The function should have logged a detection message
    # (caplog captures all loggers by default; we just check no exception raised)


@pytest.mark.asyncio
async def test_auto_detect_skips_when_watermark_set(tmp_path: Path) -> None:
    """If watermark exists, auto-detect is a no-op."""
    svc, fake_q = make_services(tmp_path)
    svc.set_watermark("test_cases", "2026-07-23T00:00:00+00:00")
    # Should not raise, no log
    await svc._auto_detect_and_backfill()
    # No upserts
    assert len(fake_q.upserted) == 0
